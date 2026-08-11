"""对账引擎测试：验证四种差异类型识别与修正逻辑。

测试覆盖：
  - matched:           两边股数相等且成本价差 < 0.01
  - mismatch:          两边都有但股数/成本不符
  - only_settlement:   交割单有、日志没有
  - only_position_log: 日志有、交割单没有
  - fix: only_settlement → 补 buy 日志
  - fix: mismatch → clear + buy 重建
  - delete: only_position_log → 删除该标的全部日志
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import polars as pl

# 在导入被测模块前，先重定向数据目录到临时目录
_ORIGINAL_DATA_DIR = None


def setup_module():
    """测试前：把数据目录指向临时目录，保护真实数据。"""
    global _ORIGINAL_DATA_DIR
    from app.config import settings
    _ORIGINAL_DATA_DIR = settings.data_dir
    tmp = Path(tempfile.mkdtemp(prefix="reconcile_test_"))
    (tmp / "user_data").mkdir(parents=True, exist_ok=True)
    settings.data_dir = tmp


def teardown_module():
    """测试后：恢复原始数据目录。"""
    global _ORIGINAL_DATA_DIR
    if _ORIGINAL_DATA_DIR:
        from app.config import settings
        shutil.rmtree(str(settings.data_dir), ignore_errors=True)
        settings.data_dir = _ORIGINAL_DATA_DIR
        _ORIGINAL_DATA_DIR = None


def _write_parquet(path: Path, rows: list[dict], schema: dict) -> None:
    df = pl.DataFrame(rows, schema=schema)
    df.write_parquet(path)


def _reset_stores():
    """清空 position_log 和 settlement_records 两个 parquet。"""
    from app.config import settings
    user_dir = settings.data_dir / "user_data"
    for name in ("position_log.parquet", "settlement_records.parquet"):
        p = user_dir / name
        if p.exists():
            p.unlink()


# ════════════════════════════════════════════════════════════
#  Fixture helpers
# ════════════════════════════════════════════════════════════

def _make_settlement_rows(records: list[dict]) -> list[dict]:
    """构造交割单记录，自动补齐 id / created_at / batch_id。"""
    rows = []
    for i, r in enumerate(records, start=1):
        rows.append({
            "id": i,
            "trade_date": r.get("trade_date", "2026-07-01"),
            "symbol": r["symbol"],
            "name": r.get("name", ""),
            "direction": r["direction"],  # 买入 / 卖出
            "price": float(r.get("price", 10)),
            "volume": int(r.get("volume", 100)),
            "amount": float(r.get("amount", 1000)),
            "commission": float(r.get("commission", 0)),
            "stamp_duty": float(r.get("stamp_duty", 0)),
            "transfer_fee": float(r.get("transfer_fee", 0)),
            "net_amount": float(r.get("net_amount", 1000)),
            "source": r.get("source", "test"),
            "batch_id": r.get("batch_id", "test-batch"),
            "created_at": "2026-07-01T00:00:00",
        })
    return rows


def _write_settlements(records: list[dict]) -> None:
    from app.config import settings
    rows = _make_settlement_rows(records)
    schema = {
        "id": pl.Int64, "trade_date": pl.Utf8, "symbol": pl.Utf8,
        "name": pl.Utf8, "direction": pl.Utf8, "price": pl.Float64,
        "volume": pl.Int64, "amount": pl.Float64, "commission": pl.Float64,
        "stamp_duty": pl.Float64, "transfer_fee": pl.Float64,
        "net_amount": pl.Float64, "source": pl.Utf8, "batch_id": pl.Utf8,
        "created_at": pl.Utf8,
    }
    p = settings.data_dir / "user_data" / "settlement_records.parquet"
    _write_parquet(p, rows, schema)


def _write_position_logs(logs: list[dict]) -> None:
    from app.config import settings
    from app.services.position_log import _SCHEMA
    rows = []
    for i, log in enumerate(logs, start=1):
        rows.append({
            "id": i,
            "op_date": log.get("op_date", "2026-07-01"),
            "op_type": log["op_type"],
            "symbol": log["symbol"],
            "name": log.get("name", ""),
            "price": float(log.get("price")) if log.get("price") is not None else None,
            "volume": float(log.get("volume")) if log.get("volume") is not None else None,
            "amount": float(log.get("amount")) if log.get("amount") is not None else None,
            "commission": float(log.get("commission", 0)),
            "stamp_duty": float(log.get("stamp_duty", 0)),
            "transfer_fee": float(log.get("transfer_fee", 0)),
            "note": log.get("note", ""),
            "source": log.get("source", "manual"),
            "settlement_id": log.get("settlement_id"),
            "settlement_batch_id": log.get("settlement_batch_id"),
            "created_at": "2026-07-01T00:00:00",
        })
    p = settings.data_dir / "user_data" / "position_log.parquet"
    _write_parquet(p, rows, _SCHEMA)


# ════════════════════════════════════════════════════════════
#  Tests
# ════════════════════════════════════════════════════════════

class TestComputePositionsFromSettlements:
    """交割单 FIFO 推导持仓测试。"""

    def test_simple_buy(self):
        """单笔买入：持仓 = 买入量。"""
        from app.services.reconcile import compute_positions_from_settlements
        records = _make_settlement_rows([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        result = compute_positions_from_settlements(records)
        assert "000001" in result
        pos = result["000001"]
        assert pos.shares == 1000
        assert pos.cost_price == 10.0
        assert pos.total_cost == 10000.0

    def test_fifo_sell_partial(self):
        """先买后卖部分：FIFO 扣减。"""
        from app.services.reconcile import compute_positions_from_settlements
        records = _make_settlement_rows([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
            {"symbol": "000001", "direction": "卖出", "price": 12, "volume": 300},
        ])
        result = compute_positions_from_settlements(records)
        assert "000001" in result
        pos = result["000001"]
        assert pos.shares == 700
        assert pos.cost_price == 10.0
        assert pos.total_cost == 7000.0

    def test_fifo_multi_buy_weighted_avg(self):
        """多笔买入：加权平均成本。"""
        from app.services.reconcile import compute_positions_from_settlements
        records = _make_settlement_rows([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 500},
            {"symbol": "000001", "direction": "买入", "price": 20, "volume": 500},
        ])
        result = compute_positions_from_settlements(records)
        pos = result["000001"]
        assert pos.shares == 1000
        assert pos.cost_price == 15.0  # (10*500 + 20*500) / 1000
        assert pos.total_cost == 15000.0

    def test_fifo_sell_all(self):
        """全部卖出后持仓为空。"""
        from app.services.reconcile import compute_positions_from_settlements
        records = _make_settlement_rows([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 500},
            {"symbol": "000001", "direction": "卖出", "price": 12, "volume": 500},
        ])
        result = compute_positions_from_settlements(records)
        assert "000001" not in result


class TestReconcile:
    """对账差异类型识别测试。"""

    def test_matched(self):
        """两边持仓完全一致 → matched。"""
        _reset_stores()
        # 交割单：买入 000001 1000 股 @10
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        # 操作日志：买入 000001 1000 股 @10
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 1000},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()
        assert len(items) == 1
        item = items[0]
        assert item["symbol"] == "000001"
        assert item["diff_type"] == "matched"
        assert item["shares_delta"] == 0.0
        assert abs(item["cost_delta"]) < 0.01

    def test_mismatch_shares(self):
        """两边股数不同 → mismatch。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 800},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()
        item = items[0]
        assert item["diff_type"] == "mismatch"
        assert item["shares_delta"] == -200.0  # log(800) - settlement(1000)

    def test_mismatch_cost(self):
        """两边成本不同 → mismatch。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 12, "volume": 1000},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()
        item = items[0]
        assert item["diff_type"] == "mismatch"
        assert item["shares_delta"] == 0.0
        assert item["cost_delta"] == 2.0

    def test_only_settlement(self):
        """交割单有、日志没有 → only_settlement。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        # 不写日志

        from app.services.reconcile import reconcile
        items = reconcile()
        assert len(items) == 1
        item = items[0]
        assert item["diff_type"] == "only_settlement"
        assert item["settlement_pos"] is not None
        assert item["log_pos"] is None

    def test_only_position_log(self):
        """日志有、交割单没有 → only_position_log。"""
        _reset_stores()
        # 不写交割单
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 1000},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()
        assert len(items) == 1
        item = items[0]
        assert item["diff_type"] == "only_position_log"
        assert item["settlement_pos"] is None
        assert item["log_pos"] is not None

    def test_empty_both(self):
        """两边都没有数据 → 空列表。"""
        _reset_stores()
        from app.services.reconcile import reconcile
        items = reconcile()
        assert items == []

    def test_mixed(self):
        """混合场景：多个标的，多种差异类型。"""
        _reset_stores()
        # 交割单：000001(买入1000@10), 000002(买入500@20)
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
            {"symbol": "000002", "direction": "买入", "price": 20, "volume": 500},
        ])
        # 日志：000001(买入1000@10) matched, 000003(买入300@15) only_position_log
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 1000},
            {"op_type": "buy", "symbol": "000003", "price": 15, "volume": 300},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()
        assert len(items) == 3

        # 按差异类型排序后，差异项在前
        types = [i["diff_type"] for i in items]
        assert types[:2] == ["only_settlement", "only_position_log"]  # order=0
        assert types[2] == "matched"  # order=2


class TestFixItem:
    """修正操作测试。"""

    def test_fix_only_settlement(self):
        """only_settlement → fix 补 buy 日志，修正后变为 matched。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        # 不写日志

        from app.services.reconcile import reconcile, fix_item
        items_before = reconcile()
        assert items_before[0]["diff_type"] == "only_settlement"

        result = fix_item("000001", "fix")
        assert result["ok"] is True
        assert result["diff_type"] == "only_settlement"

        # 修正后重新对账
        items_after = reconcile()
        assert len(items_after) == 1
        assert items_after[0]["diff_type"] == "matched"

    def test_fix_mismatch(self):
        """mismatch → fix 清空旧持仓 + 按交割单重建 → matched。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 12, "volume": 800},
        ])

        from app.services.reconcile import reconcile, fix_item
        items_before = reconcile()
        assert items_before[0]["diff_type"] == "mismatch"

        result = fix_item("000001", "fix")
        assert result["ok"] is True

        items_after = reconcile()
        assert items_after[0]["diff_type"] == "matched"
        assert items_after[0]["settlement_pos"]["shares"] == items_after[0]["log_pos"]["shares"]
        assert items_after[0]["settlement_pos"]["cost_price"] == items_after[0]["log_pos"]["cost_price"]

    def test_fix_only_position_log_raises(self):
        """only_position_log → fix 应抛异常（需用 delete）。"""
        _reset_stores()
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 500},
        ])

        from app.services.reconcile import fix_item
        import pytest
        with pytest.raises(ValueError, match="日志独有持仓无法自动修正"):
            fix_item("000001", "fix")

    def test_delete_only_position_log(self):
        """only_position_log → delete 删除日志后，对账为空。"""
        _reset_stores()
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 500},
        ])

        from app.services.reconcile import reconcile, fix_item
        items_before = reconcile()
        assert items_before[0]["diff_type"] == "only_position_log"

        result = fix_item("000001", "delete")
        assert result["ok"] is True

        items_after = reconcile()
        assert items_after == []

    def test_fix_mismatch_with_fifo_sell_history(self):
        """mismatch 修正：日志有买卖历史导致最终持仓不同，修正后对齐。"""
        _reset_stores()
        # 交割单：买入 1000@10，卖出 200@12 → 持仓 800@10
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000, "trade_date": "2026-07-01"},
            {"symbol": "000001", "direction": "卖出", "price": 12, "volume": 200, "trade_date": "2026-07-02"},
        ])
        # 日志：买入 1000@10，卖出 500@12 → 持仓 500@10（与交割单不符）
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 1000, "op_date": "2026-07-01"},
            {"op_type": "sell", "symbol": "000001", "price": 12, "volume": 500, "op_date": "2026-07-02"},
        ])

        from app.services.reconcile import reconcile, fix_item
        items_before = reconcile()
        assert items_before[0]["diff_type"] == "mismatch"

        fix_item("000001", "fix")

        items_after = reconcile()
        assert items_after[0]["diff_type"] == "matched"
        assert items_after[0]["settlement_pos"]["shares"] == 800
        assert items_after[0]["log_pos"]["shares"] == 800

    def test_invalid_action_raises(self):
        """无效的 action 抛异常。"""
        _reset_stores()
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
        ])

        from app.services.reconcile import fix_item
        import pytest
        with pytest.raises(ValueError, match="不支持的修正动作"):
            fix_item("000001", "invalid")

    def test_unknown_symbol_raises(self):
        """对账中不存在的 symbol 抛异常。"""
        _reset_stores()
        from app.services.reconcile import fix_item
        import pytest
        with pytest.raises(ValueError, match="未找到标的"):
            fix_item("999999", "fix")


class TestReconcileSummary:
    """对账汇总统计测试。"""

    def test_summary_counts(self):
        """汇总各类型数量正确。"""
        _reset_stores()
        # 交割单：000001(matched), 000002(only_settlement), 000003(mismatch)
        _write_settlements([
            {"symbol": "000001", "direction": "买入", "price": 10, "volume": 1000},
            {"symbol": "000002", "direction": "买入", "price": 20, "volume": 500},
            {"symbol": "000003", "direction": "买入", "price": 15, "volume": 300},
        ])
        # 日志：000001(matched), 000003(股数不同), 000004(only_position_log)
        _write_position_logs([
            {"op_type": "buy", "symbol": "000001", "price": 10, "volume": 1000},
            {"op_type": "buy", "symbol": "000003", "price": 15, "volume": 200},  # 股数不同
            {"op_type": "buy", "symbol": "000004", "price": 8, "volume": 600},
        ])

        from app.services.reconcile import reconcile
        items = reconcile()

        matched = sum(1 for i in items if i["diff_type"] == "matched")
        mismatch = sum(1 for i in items if i["diff_type"] == "mismatch")
        only_settlement = sum(1 for i in items if i["diff_type"] == "only_settlement")
        only_position_log = sum(1 for i in items if i["diff_type"] == "only_position_log")

        assert matched == 1     # 000001
        assert mismatch == 1    # 000003
        assert only_settlement == 1  # 000002
        assert only_position_log == 1  # 000004
        assert len(items) == 4