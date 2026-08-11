"""持仓服务（当前持仓清单）—— FIFO 适配层。

阶段 0 起，持仓不再直接存储，而是由 position_log 中的操作日志按 FIFO 派生
（见 position_log.compute_positions）。本模块保留原有函数签名，供现有
API 层（app/api/positions.py）与持仓分析器无感切换：

  - list_rows()  返回字段对齐旧 PositionEntry：
      symbol/shares/cost_price/opened_at/note/added_at
  - upsert/update/remove/clear 映射为日志写入，过渡期保持旧前端可用：
      upsert(symbol, shares, cost_price, ...)
        · 当前无该 symbol 持仓 → 写一条 buy（建仓/加仓叠加 FIFO）
        · 当前已有持仓 → 先 clear 再 buy（语义等同旧版"覆盖为新数量/成本"）
      update(symbol, **fields)      → clear + 按更新后字段 buy 重建
      remove(symbol)                → 写一条 clear
      clear()                       → 清空全部日志

注意：旧的 data/user_data/positions.parquet 已由 position_log.migrate_legacy_positions()
在启动时迁移为 source='migration' 的日志，并备份为 positions.parquet.bak。
本模块不再读写该文件。
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.services import position_log as plog

logger = logging.getLogger(__name__)

# 对外暴露的字段顺序（与旧 PositionEntry 一致）
_FIELDS = ["symbol", "shares", "cost_price", "opened_at", "note", "added_at"]


def _position_to_row(p: plog.ComputedPosition) -> dict:
    return {
        "symbol": p.symbol,
        "shares": p.shares,
        "cost_price": p.cost_price,
        "opened_at": p.opened_at or "",
        "note": p.note,
        "added_at": p.added_at,
        "name": p.name,
    }


def list_rows() -> list[dict]:
    """返回当前持仓（FIFO 派生），字段对齐旧结构。"""
    positions = plog.compute_positions()
    return [_position_to_row(p) for p in positions]


def _rebuild(symbol: str, shares: float, cost_price: float, opened_at: str, note: str) -> None:
    """用 clear + buy 把某标的重建为指定持仓（覆盖语义）。"""
    existing = plog.get_position(symbol)
    if existing is not None:
        plog.insert_log({
            "op_type": "clear",
            "symbol": symbol,
            "price": existing.cost_price,
            "volume": existing.shares,
            "op_date": opened_at or _today(),
            "note": "编辑重建",
            "source": "manual",
        })
    if shares and shares > 0:
        plog.insert_log({
            "op_type": "buy",
            "symbol": symbol,
            "price": float(cost_price),
            "volume": float(shares),
            "amount": round(float(cost_price) * float(shares) + 1e-9, 2),
            "op_date": opened_at or _today(),
            "note": note or "",
            "source": "manual",
        })


def _today() -> str:
    return datetime.now().date().isoformat()


def upsert(
    symbol: str,
    shares: float,
    cost_price: float,
    opened_at: str | None = None,
    note: str = "",
) -> list[dict]:
    """新增/覆盖一条持仓（旧版直接覆盖语义，过渡期保留）。"""
    _rebuild(symbol, float(shares), float(cost_price), opened_at or "", note or "")
    return list_rows()


def update(symbol: str, **fields) -> list[dict]:
    """更新持仓字段。仅 shares/cost_price/opened_at/note 有意义。

    采用 clear + buy 重建，使新的股数/成本成为当前持仓（覆盖语义）。
    未提供的字段沿用当前持仓值。
    """
    current = plog.get_position(symbol)
    if current is None:
        return list_rows()

    shares = float(fields.get("shares", current.shares))
    cost_price = float(fields.get("cost_price", current.cost_price))
    opened_at = fields.get("opened_at")
    opened_at = opened_at if opened_at is not None else (current.opened_at or "")
    note = fields.get("note")
    note = note if note is not None else current.note
    _rebuild(symbol, shares, cost_price, opened_at, note)
    return list_rows()


def remove(symbol: str) -> list[dict]:
    """删除一条持仓 → 写一条 clear 日志。"""
    current = plog.get_position(symbol)
    if current is not None:
        plog.insert_log({
            "op_type": "clear",
            "symbol": symbol,
            "price": current.cost_price,
            "volume": current.shares,
            "op_date": _today(),
            "note": "删除持仓",
            "source": "manual",
        })
    return list_rows()


def clear() -> int:
    """清空全部持仓日志。返回删除条数。"""
    return plog.clear_all_logs()
