"""备份恢复服务测试 (优化项 10)。

覆盖:
- create_backup: 生成带时间戳 zip, 包含 user_data 文件
- list_backups: 列出备份, 按时间倒序
- restore_backup: 解压恢复, 验证文件完整性
- delete_backup: 删除指定备份
- 安全: 路径穿越防护
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import backup_service


@pytest.fixture()
def setup_data_dir(monkeypatch, tmp_path):
    """模拟 data_dir, 写入测试 user_data 文件。"""
    data_dir = tmp_path / "data"
    user_data = data_dir / "user_data"
    user_data.mkdir(parents=True)

    # 写入测试文件
    (user_data / "preferences.json").write_text(json.dumps({"key": "value"}))
    (user_data / "positions.parquet").write_bytes(b"fake parquet data")
    sub = user_data / "monitor_rules"
    sub.mkdir()
    (sub / "rule1.json").write_text(json.dumps({"name": "test"}))

    monkeypatch.setattr(backup_service.settings, "data_dir", data_dir)
    return data_dir


def test_create_backup_generates_zip(setup_data_dir):
    """备份生成带时间戳 zip 文件"""
    result = backup_service.create_backup()
    assert "filename" in result
    assert result["filename"].startswith("backup_")
    assert result["filename"].endswith(".zip")
    assert result["file_count"] == 3  # preferences.json + positions.parquet + rule1.json
    assert result["size_mb"] >= 0  # 小文件可能 round 到 0

    backup_path = setup_data_dir / "backups" / result["filename"]
    assert backup_path.exists()


def test_list_backups_sorted_desc(setup_data_dir):
    """备份列表按时间倒序"""
    import time
    b1 = backup_service.create_backup()
    time.sleep(0.1)
    b2 = backup_service.create_backup()

    backups = backup_service.list_backups()
    assert len(backups) == 2
    assert backups[0]["filename"] == b2["filename"]
    assert backups[1]["filename"] == b1["filename"]


def test_restore_backup_restores_files(setup_data_dir):
    """恢复能还原 user_data 文件"""
    # 先备份
    backup = backup_service.create_backup()
    filename = backup["filename"]

    # 修改 user_data (模拟数据损坏)
    user_data = setup_data_dir / "user_data"
    (user_data / "preferences.json").write_text("corrupted")
    (user_data / "new_file.txt").write_text("should be removed after restore")

    # 恢复
    result = backup_service.restore_backup(filename)
    assert result["restored_files"] == 3

    # 验证恢复后的内容
    assert (user_data / "preferences.json").read_text() == json.dumps({"key": "value"})
    assert (user_data / "positions.parquet").read_bytes() == b"fake parquet data"
    assert not (user_data / "new_file.txt").exists()


def test_delete_backup(setup_data_dir):
    """删除备份文件"""
    backup = backup_service.create_backup()
    filename = backup["filename"]

    backup_service.delete_backup(filename)

    backup_path = setup_data_dir / "backups" / filename
    assert not backup_path.exists()


def test_restore_nonexistent_raises(setup_data_dir):
    """恢复不存在的备份文件报错"""
    with pytest.raises(FileNotFoundError):
        backup_service.restore_backup("nonexistent.zip")


def test_safe_filename_rejects_traversal():
    """文件名校验拒绝路径穿越"""
    with pytest.raises(ValueError):
        backup_service._safe_filename("../etc/passwd")
    with pytest.raises(ValueError):
        backup_service._safe_filename("foo/bar.zip")
    with pytest.raises(ValueError):
        backup_service._safe_filename("")

    assert backup_service._safe_filename("backup_ok.zip") == "backup_ok.zip"
