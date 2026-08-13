"""数据备份与恢复服务 (优化项 10)。

备份 `data/user_data/` 目录到 `data/backups/` 下的带时间戳 zip 文件。
恢复时先解压到临时目录校验, 再原子替换 user_data 内容。

安全策略:
  - 备份: 只打包 user_data/ 下的文件, 不触碰 parquet 行情数据 (体积大且可重新同步)
  - 恢复: 先解压到临时目录, 校验结构后再替换; 失败时保留现有数据不变
  - 文件名: 严格校验, 禁止路径穿越 (../)
"""
from __future__ import annotations

import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 备份存储目录
BACKUP_DIR_NAME = "backups"
# 单文件最大数 (防止恶意/异常 zip)
MAX_RESTORE_FILES = 500
MAX_RESTORE_SIZE_MB = 200


def _backup_dir() -> Path:
    d = Path(settings.data_dir) / BACKUP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_data_dir() -> Path:
    return Path(settings.data_dir) / "user_data"


def _safe_filename(name: str) -> str:
    """校验文件名, 禁止路径穿越。"""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"非法文件名: {name}")
    return name


def create_backup() -> dict:
    """打包 user_data/ 目录为带时间戳的 zip 文件。

    返回 {filename, size_mb, file_count, created_at}
    """
    user_data = _user_data_dir()
    backup_dir = _backup_dir()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{ts}.zip"
    backup_path = backup_dir / filename
    # 同秒内多次备份: 追加序号避免覆盖
    if backup_path.exists():
        i = 1
        while (backup_dir / f"backup_{ts}_{i}.zip").exists():
            i += 1
        filename = f"backup_{ts}_{i}.zip"
        backup_path = backup_dir / filename

    # 临时文件 → rename, 避免中途异常留下半截 zip
    tmp_path = backup_path.with_suffix(".tmp")

    file_count = 0
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if user_data.exists():
            for fp in user_data.rglob("*"):
                if fp.is_file():
                    arcname = fp.relative_to(user_data)
                    zf.write(fp, arcname)
                    file_count += 1

    tmp_path.replace(backup_path)

    size_mb = backup_path.stat().st_size / (1024 * 1024)
    logger.info("备份完成: %s (%d 文件, %.2f MB)", filename, file_count, size_mb)

    return {
        "filename": filename,
        "size_mb": round(size_mb, 2),
        "file_count": file_count,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def list_backups() -> list[dict]:
    """列出所有备份文件, 按时间倒序。"""
    backup_dir = _backup_dir()
    backups = []
    for fp in backup_dir.glob("backup_*.zip"):
        stat = fp.stat()
        backups.append({
            "filename": fp.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "_mtime": stat.st_mtime,
        })
    backups.sort(key=lambda b: b["_mtime"], reverse=True)
    for b in backups:
        del b["_mtime"]
    return backups


def restore_backup(filename: str) -> dict:
    """从 zip 备份恢复 user_data/ 目录。

    安全步骤:
      1. 校验文件名 (防路径穿越)
      2. 解压到临时目录
      3. 校验文件数和总大小
      4. 备份当前 user_data 为 .bak
      5. 替换 user_data 内容
      6. 删除 .bak

    返回 {restored_files, filename}
    """
    safe_name = _safe_filename(filename)
    backup_path = _backup_dir() / safe_name

    if not backup_path.exists():
        raise FileNotFoundError(f"备份文件不存在: {filename}")

    user_data = _user_data_dir()
    tmp_extract = _backup_dir() / f"_restore_tmp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        # 1. 解压到临时目录
        tmp_extract.mkdir(parents=True, exist_ok=True)
        file_count = 0
        total_size = 0
        with zipfile.ZipFile(backup_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                file_count += 1
                total_size += info.file_size
                if file_count > MAX_RESTORE_FILES:
                    raise ValueError(f"备份文件数超过上限 ({MAX_RESTORE_FILES})")
                if total_size > MAX_RESTORE_SIZE_MB * 1024 * 1024:
                    raise ValueError(f"备份总大小超过上限 ({MAX_RESTORE_SIZE_MB} MB)")
            zf.extractall(tmp_extract)

        # 2. 备份当前 user_data (如果存在)
        bak_dir = None
        if user_data.exists() and any(user_data.iterdir()):
            bak_dir = user_data.with_name("user_data.bak")
            if bak_dir.exists():
                shutil.rmtree(bak_dir)
            user_data.rename(bak_dir)

        # 3. 移动解压内容到 user_data
        try:
            user_data.mkdir(parents=True, exist_ok=True)
            for item in tmp_extract.iterdir():
                shutil.move(str(item), str(user_data / item.name))
        except Exception:
            # 恢复失败: 回滚到 .bak
            if bak_dir and bak_dir.exists():
                if user_data.exists():
                    shutil.rmtree(user_data)
                bak_dir.rename(user_data)
            raise

        # 4. 删除 .bak
        if bak_dir and bak_dir.exists():
            shutil.rmtree(bak_dir)

        logger.info("恢复完成: %s (%d 文件)", filename, file_count)
        return {"restored_files": file_count, "filename": filename}

    finally:
        # 清理临时目录
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract, ignore_errors=True)


def delete_backup(filename: str) -> dict:
    """删除指定备份文件。"""
    safe_name = _safe_filename(filename)
    backup_path = _backup_dir() / safe_name

    if not backup_path.exists():
        raise FileNotFoundError(f"备份文件不存在: {filename}")

    backup_path.unlink()
    logger.info("备份已删除: %s", filename)
    return {"deleted": filename}
