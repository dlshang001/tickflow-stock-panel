"""优化项 8 断点续传与失败重试测试。

覆盖:
  - _fetch_with_retry 指数退避重试 (临时失败后成功 / 耗尽抛异常)
  - sync_daily_batch chunk 重试 + on_chunk_success + failed_out
  - sync_state 断点续传 (同范围未完成保留 done / 不同范围新建 / finish 后重跑)
  - check_daily_integrity 完整性校验 (缺失段 / 低覆盖)
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl
import pytest

from app.services import kline_sync, sync_state
from app.tickflow.repository import DataStore, KlineRepository

CANONICAL = {
    "open": [10.0], "high": [11.0], "low": [9.0],
    "close": [10.5], "volume": [1000.0], "amount": [10000.0],
}


def _daily_df(symbols: list[str], d: date) -> pl.DataFrame:
    n = len(symbols)
    return pl.DataFrame({
        "symbol": symbols,
        "date": [d] * n,
        **{k: [v[0]] * n for k, v in CANONICAL.items()},
    })


# ── _fetch_with_retry ──────────────────────────────────
def test_fetch_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    out = kline_sync._fetch_with_retry(flaky, what="x", attempts=3, base_delay=0)
    assert out == "ok"
    assert calls["n"] == 3


def test_fetch_with_retry_raises_after_exhausted():
    with pytest.raises(ConnectionError):
        kline_sync._fetch_with_retry(
            lambda: (_ for _ in ()).throw(ConnectionError("x")),
            what="x", attempts=3, base_delay=0,
        )


# ── sync_daily_batch chunk 重试 ────────────────────────
def test_sync_daily_batch_retries_transient_failure(monkeypatch):
    """前 2 次 chunk 拉取抛异常, 第 3 次成功 → 不进入 failed, 正常出数据。"""
    tf = MagicMock()
    calls = {"n": 0}

    def batch(chunk, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("boom")
        return _daily_df(list(chunk), date(2026, 1, 5))

    tf.klines.batch = batch
    monkeypatch.setattr(kline_sync, "get_client", lambda: tf)
    monkeypatch.setattr(kline_sync, "sleep_between_batches", lambda i, rpm: None)

    failed: list[str] = []
    done: list[list[str]] = []
    df = kline_sync.sync_daily_batch(
        ["600000.SH", "000001.SZ"], batch_size=2, rpm=None,
        on_chunk_success=done.append, failed_out=failed,
        retries=3, retry_base_delay=0,
    )
    assert calls["n"] == 3        # 重试 2 次后成功
    assert failed == []           # 未落入失败集合
    assert done == [["600000.SH", "000001.SZ"]]
    assert df.height == 2


def test_sync_daily_batch_exhausted_chunk_goes_to_failed(monkeypatch):
    """重试耗尽仍失败 → chunk 标的进 failed_out, 不影响其他 chunk。"""
    tf = MagicMock()

    def batch(chunk, **kwargs):
        raise ConnectionError("down")

    tf.klines.batch = batch
    monkeypatch.setattr(kline_sync, "get_client", lambda: tf)
    monkeypatch.setattr(kline_sync, "sleep_between_batches", lambda i, rpm: None)

    failed: list[str] = []
    df = kline_sync.sync_daily_batch(
        ["600000.SH", "000001.SZ"], batch_size=2, rpm=None,
        failed_out=failed, retries=2, retry_base_delay=0,
    )
    assert sorted(failed) == ["000001.SZ", "600000.SH"]
    assert df.height == 0


# ── sync_state 断点续传 ────────────────────────────────
def _stub_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_state, "settings", SimpleNamespace(data_dir=tmp_path))


def test_begin_extend_resumes_same_range(monkeypatch, tmp_path):
    _stub_data_dir(monkeypatch, tmp_path)
    s = sync_state
    s.begin_extend(date(2020, 1, 1), date(2024, 6, 1), ["A", "B", "C"])
    s.mark_extend_done(["A", "B"])
    # 同范围重跑 → 保留已完成 symbol
    t2 = s.begin_extend(date(2020, 1, 1), date(2024, 6, 1), ["A", "B", "C", "D"])
    assert t2["done"] == ["A", "B"]
    # 不同范围 → 新建, 从头
    t3 = s.begin_extend(date(2019, 1, 1), date(2024, 6, 1), ["A", "B", "C"])
    assert t3["done"] == []
    # finish 后同范围重跑 → 从头
    s.finish_extend()
    t4 = s.begin_extend(date(2020, 1, 1), date(2024, 6, 1), ["A", "B", "C"])
    assert t4["done"] == []


def test_begin_extend_filters_stale_symbols(monkeypatch, tmp_path):
    """续传时过滤掉已不在本次标的池的 symbol。"""
    _stub_data_dir(monkeypatch, tmp_path)
    s = sync_state
    s.begin_extend(date(2020, 1, 1), date(2024, 6, 1), ["A", "B", "C"])
    s.mark_extend_done(["A", "B", "X"])  # X 已不在池中
    t2 = s.begin_extend(date(2020, 1, 1), date(2024, 6, 1), ["A", "C"])
    assert t2["done"] == ["A"]


# ── check_daily_integrity ──────────────────────────────
def _write_daily(repo, d: date, symbols: list[str]):
    p = repo.store.data_dir / "kline_daily" / f"date={d.isoformat()}" / "part.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    _daily_df(symbols, d).write_parquet(p)


def test_check_daily_integrity_reports_gap_and_low_coverage(tmp_path):
    repo = KlineRepository(DataStore(tmp_path))
    # 两个数据日期间隔 7 天 > 5 → 疑似缺失段; 第二个日期覆盖率低
    _write_daily(repo, date(2026, 7, 1), ["A", "B", "C"])
    _write_daily(repo, date(2026, 7, 8), ["A"])
    res = kline_sync.check_daily_integrity(repo)
    assert res["dates"] == 2
    assert res["missing_gap_count"] == 1
    assert res["low_coverage_count"] == 1
    assert res["max_coverage"] == 3


def test_check_daily_integrity_ok_with_weekend_gap(tmp_path):
    """周五~周一间隔 3 天 (≤5) 不算缺失。"""
    repo = KlineRepository(DataStore(tmp_path))
    _write_daily(repo, date(2026, 7, 3), ["A", "B", "C"])
    _write_daily(repo, date(2026, 7, 6), ["A", "B", "C"])
    res = kline_sync.check_daily_integrity(repo)
    assert res["missing_gap_count"] == 0
    assert res["low_coverage_count"] == 0


def test_check_daily_integrity_empty(tmp_path):
    repo = KlineRepository(DataStore(tmp_path))
    res = kline_sync.check_daily_integrity(repo)
    assert res["dates"] == 0
