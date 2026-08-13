"""定时复盘「节假日跳过」测试 — 优化项 3b。

覆盖:
  - _is_trading_day 的判据 (周末/节假日/无数据兜底)
  - 三个定时复盘 job 在非交易日跳过、不触发下游
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.jobs import daily_pipeline

THU = date(2026, 8, 13)  # 周四
SAT = date(2026, 8, 15)  # 周六


class _FakeRepo:
    def __init__(self, latest_daily):
        self._latest = latest_daily

    def latest_daily_date(self):
        return self._latest


def _freeze_today(monkeypatch, d: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return d

    monkeypatch.setattr(daily_pipeline, "date", _FixedDate)


# ── _is_trading_day 判据 ─────────────────────────────────
def test_trading_day_when_daily_has_today(monkeypatch):
    """工作日 + 本地日K含今日 → 交易日。"""
    _freeze_today(monkeypatch, THU)
    assert daily_pipeline._is_trading_day(_FakeRepo(THU)) is True


def test_non_trading_day_on_holiday(monkeypatch):
    """工作日 + 日K停在上一交易日 (法定节假日) → 非交易日。"""
    _freeze_today(monkeypatch, THU)
    assert daily_pipeline._is_trading_day(_FakeRepo(THU - timedelta(days=1))) is False


def test_non_trading_day_on_weekend(monkeypatch):
    """周末 → 非交易日 (Cron 已排除, 兜底仍生效)。"""
    _freeze_today(monkeypatch, SAT)
    assert daily_pipeline._is_trading_day(_FakeRepo(SAT)) is False


def test_trading_day_default_true_when_no_data(monkeypatch):
    """无日K数据 → 保守返回 True (不跳过), 交由 stale 检查兜底。"""
    _freeze_today(monkeypatch, THU)
    assert daily_pipeline._is_trading_day(_FakeRepo(None)) is True


def test_trading_day_default_true_when_repo_raises(monkeypatch):
    """repo 读取异常 → 保守返回 True (不跳过)。"""

    class _RaisingRepo:
        def latest_daily_date(self):
            raise RuntimeError("db down")

    _freeze_today(monkeypatch, THU)
    assert daily_pipeline._is_trading_day(_RaisingRepo()) is True


# ── 三个定时复盘 job 非交易日跳过 ─────────────────────────
def _stub_scheduler(monkeypatch, ai_key=True):
    monkeypatch.setattr(daily_pipeline, "_scheduled_review_stale", lambda repo: False)
    monkeypatch.setattr(daily_pipeline, "_is_trading_day", lambda repo: False)
    import app.secrets_store as ss
    monkeypatch.setattr(ss, "get_ai_key", lambda: ai_key)


def test_scheduled_review_skipped_on_non_trading_day(monkeypatch):
    """大盘复盘: 非交易日不触发流式生成。"""
    import asyncio
    _stub_scheduler(monkeypatch)
    called: list[str] = []

    async def _fake_stream(*a, **k):
        called.append("stream")

    monkeypatch.setattr(daily_pipeline, "_stream_review_with_retry", _fake_stream)
    asyncio.run(daily_pipeline._run_scheduled_review(_FakeRepo(None)))
    assert called == []


def test_scheduled_position_review_skipped_on_non_trading_day(monkeypatch):
    """持仓复盘: 非交易日不读取持仓列表。"""
    import asyncio
    _stub_scheduler(monkeypatch)
    import app.services.positions as positions
    called: list[str] = []
    monkeypatch.setattr(positions, "list_rows", lambda: called.append("list") or [])
    asyncio.run(daily_pipeline._run_scheduled_position_review(_FakeRepo(None)))
    assert called == []


def test_scheduled_settlement_review_skipped_on_non_trading_day(monkeypatch):
    """交割单分析: 非交易日不读取记录。"""
    import asyncio
    _stub_scheduler(monkeypatch)
    import app.services.settlement as settlement
    called: list[str] = []
    monkeypatch.setattr(settlement, "all_records", lambda: called.append("list") or [])
    asyncio.run(daily_pipeline._run_scheduled_settlement_review(_FakeRepo(None)))
    assert called == []
