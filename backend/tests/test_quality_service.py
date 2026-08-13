"""数据质量校验服务测试 (优化项 9)。

覆盖:
- check_daily_integrity 复用 (空库/正常/缺口)
- check_price_anomalies: 涨跌幅超阈值检测
- check_negative_volume: 负成交量检测
- check_data_quality: 综合报告与质量等级
"""
from __future__ import annotations

import datetime as _dt

import polars as pl
import pytest

from app.services import quality_service
from app.tickflow.repository import DataStore, KlineRepository


@pytest.fixture()
def repo(tmp_path):
    return KlineRepository(DataStore(tmp_path))


def _write_daily(repo, rows):
    """写入日 K 数据到 kline_daily 分区。"""
    df = pl.DataFrame(rows)
    # 按 date 分组写入分区
    for (d,), group in df.partition_by("date", as_dict=True).items():
        ds = str(d)
        out = repo.store.data_dir / "kline_daily" / f"date={ds}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        group.write_parquet(out)


def test_check_data_quality_empty_repo(repo):
    """空库: 返回 ok 等级, 无异常"""
    report = quality_service.check_data_quality(repo)
    assert report["summary"]["grade"] == "ok"
    assert report["summary"]["total_issues"] == 0
    assert report["price_anomalies"]["count"] == 0
    assert report["negative_volume"]["count"] == 0


def test_check_price_anomalies_detects_big_jump(repo):
    """涨跌幅 > 20% 被检测到"""
    base = _dt.date(2026, 1, 10)
    rows = [
        {"symbol": "600000.SH", "date": base, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "volume": 1000.0, "amount": 10000.0},
        # 次日暴涨 50%
        {"symbol": "600000.SH", "date": base + _dt.timedelta(days=1), "open": 15.0, "high": 15.5, "low": 14.8, "close": 15.0, "volume": 2000.0, "amount": 30000.0},
    ]
    _write_daily(repo, rows)
    report = quality_service.check_price_anomalies(
        repo, start=base - _dt.timedelta(days=10)
    )
    assert report["count"] >= 1
    assert report["anomalies"][0]["symbol"] == "600000.SH"
    assert report["anomalies"][0]["pct_change"] == 50.0


def test_check_price_anomalies_ignores_normal_change(repo):
    """正常涨跌幅 (< 20%) 不被标记"""
    base = _dt.date(2026, 1, 10)
    rows = [
        {"symbol": "600001.SH", "date": base, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "volume": 1000.0, "amount": 10000.0},
        # 次日涨 5%
        {"symbol": "600001.SH", "date": base + _dt.timedelta(days=1), "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 1100.0, "amount": 11500.0},
    ]
    _write_daily(repo, rows)
    report = quality_service.check_price_anomalies(
        repo, start=base - _dt.timedelta(days=10)
    )
    assert report["count"] == 0


def test_check_negative_volume(repo):
    """负成交量被检测到"""
    base = _dt.date(2026, 1, 10)
    rows = [
        {"symbol": "600002.SH", "date": base, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "volume": -100.0, "amount": 10000.0},
        {"symbol": "600003.SH", "date": base, "open": 20.0, "high": 20.5, "low": 19.8, "close": 20.0, "volume": 500.0, "amount": -5000.0},
    ]
    _write_daily(repo, rows)
    report = quality_service.check_negative_volume(
        repo, start=base - _dt.timedelta(days=10)
    )
    assert report["count"] == 2


def test_check_data_quality_grade_warning(repo):
    """有少量异常 → warning 等级"""
    base = _dt.date(2026, 1, 10)
    rows = [
        {"symbol": "600004.SH", "date": base, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "volume": 1000.0, "amount": 10000.0},
        {"symbol": "600004.SH", "date": base + _dt.timedelta(days=1), "open": 15.0, "high": 15.5, "low": 14.8, "close": 15.0, "volume": 2000.0, "amount": 30000.0},
    ]
    _write_daily(repo, rows)
    report = quality_service.check_data_quality(repo, start=base - _dt.timedelta(days=10))
    assert report["summary"]["grade"] == "warning"
    assert report["summary"]["anomaly_count"] >= 1
