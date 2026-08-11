"""对账引擎：比较「交割单推导持仓」与「操作日志推导持仓」。

两套数据各自按 FIFO 计算当前持仓后逐标的比对，输出差异类型：
  matched           两边股数相等且成本价差 < 0.01
  mismatch          两边都有但股数/成本不符
  only_settlement   交割单有、日志没有
  only_position_log 日志有、交割单没有

修正动作：
  fix：
    only_settlement → 按交割单推导结果补一条 buy 日志
    mismatch        → 先 clear 清空旧持仓，再按交割单 buy 重建
    only_position_log → 不自动 fix（删除由 delete 处理）
  delete：删除该标的全部日志（重新同步）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services import position_log, settlement

logger = logging.getLogger(__name__)

COST_EPS = 0.01


@dataclass
class Snapshot:
    symbol: str
    name: str
    shares: float
    cost_price: float
    total_cost: float


def _snapshot(p: position_log.ComputedPosition) -> Snapshot:
    return Snapshot(
        symbol=p.symbol, name=p.name,
        shares=p.shares, cost_price=p.cost_price, total_cost=p.total_cost,
    )


def compute_positions_from_settlements(records: list[dict]) -> dict[str, Snapshot]:
    """从交割单记录按 FIFO 推导当前持仓。

    与 position_log.compute_positions 同算法，但输入字段不同：
    direction(买入/卖出)、price、volume。
    """
    by_symbol: dict[str, list[dict]] = {}
    for r in records:
        by_symbol.setdefault(str(r["symbol"]), []).append(r)

    result: dict[str, Snapshot] = {}
    for symbol, recs in by_symbol.items():
        ordered = sorted(recs, key=lambda r: (str(r.get("trade_date") or ""), int(r.get("id") or 0)))
        queue: list[position_log.BuyLot] = []
        name = symbol
        for r in ordered:
            if r.get("name"):
                name = str(r["name"])
            direction = str(r.get("direction") or "").strip()
            price = float(r.get("price") or 0)
            volume = float(r.get("volume") or 0)
            if direction == "买入":
                if price > 0 and volume > 0:
                    queue.append(position_log.BuyLot(price=price, volume=volume, date=str(r.get("trade_date") or "")))
            elif direction == "卖出":
                remaining = volume
                while remaining > 1e-9 and queue:
                    lot = queue[0]
                    matched = min(lot.volume, remaining)
                    lot.volume -= matched
                    remaining -= matched
                    if lot.volume <= 1e-9:
                        queue.pop(0)

        if not queue:
            continue
        total_shares = sum(l.volume for l in queue)
        if total_shares <= 1e-9:
            continue
        total_cost = sum(l.price * l.volume for l in queue)
        result[symbol] = Snapshot(
            symbol=symbol, name=name,
            shares=round(total_shares + 1e-9, 2),
            cost_price=round(total_cost / total_shares + 1e-9, 4),
            total_cost=round(total_cost + 1e-9, 2),
        )
    return result


def reconcile() -> list[dict]:
    """返回对账结果列表，差异项排在前面。"""
    settlement_records = settlement.all_records()
    set_pos = compute_positions_from_settlements(settlement_records)

    log_positions = position_log.compute_positions()
    log_pos = {p.symbol: _snapshot(p) for p in log_positions}

    all_symbols = sorted(set(set_pos) | set(log_pos))
    items: list[dict] = []
    for sym in all_symbols:
        sp = set_pos.get(sym)
        lp = log_pos.get(sym)
        if sp and lp:
            shares_match = abs(sp.shares - lp.shares) < 1e-6
            cost_match = abs(sp.cost_price - lp.cost_price) < COST_EPS
            diff = "matched" if (shares_match and cost_match) else "mismatch"
        elif sp and not lp:
            diff = "only_settlement"
        else:
            diff = "only_position_log"

        items.append({
            "symbol": sym,
            "name": (sp.name if sp else None) or (lp.name if lp else sym),
            "diff_type": diff,
            "settlement_pos": _snap_dict(sp),
            "log_pos": _snap_dict(lp),
            "shares_delta": round((lp.shares if lp else 0) - (sp.shares if sp else 0), 2),
            "cost_delta": round((lp.cost_price if lp else 0) - (sp.cost_price if sp else 0), 4),
            "total_cost_delta": round((lp.total_cost if lp else 0) - (sp.total_cost if sp else 0), 2),
        })

    order = {"only_settlement": 0, "only_position_log": 0, "mismatch": 1, "matched": 2}
    items.sort(key=lambda x: order.get(x["diff_type"], 9))
    return items


def _snap_dict(s: Snapshot | None) -> dict | None:
    if s is None:
        return None
    return {"shares": s.shares, "cost_price": s.cost_price, "total_cost": s.total_cost}


def fix_item(symbol: str, action: str) -> dict:
    """修正对账差异。

    action='fix'：
      - only_settlement：按交割单快照补一条 buy 日志
      - mismatch：先 clear 再按交割单 buy 重建
    action='delete'：删除该标的全部操作日志
    返回 {ok, diff_type, items?}（调用方通常会重新拉取对账结果）。
    """
    if action not in ("fix", "delete"):
        raise ValueError(f"不支持的修正动作: {action}")

    items_before = {i["symbol"]: i for i in reconcile()}
    item = items_before.get(symbol)
    if item is None:
        raise ValueError(f"未找到标的 {symbol} 的对账记录")

    diff = item["diff_type"]

    if action == "delete":
        position_log.delete_logs_by_symbol(symbol)
        logger.info("reconcile delete: %s logs removed for %s", "all", symbol)
        return {"ok": True, "action": "delete", "symbol": symbol, "diff_type": diff}

    # fix
    sp = item["settlement_pos"]
    if diff == "only_position_log":
        raise ValueError("日志独有持仓无法自动修正，请使用删除")
    if not sp:
        raise ValueError(f"标的 {symbol} 缺少交割单持仓，无法修正")

    if diff == "mismatch":
        # 清空旧持仓后重建
        lp = item["log_pos"]
        position_log.insert_log({
            "op_type": "clear",
            "symbol": symbol,
            "name": item["name"],
            "price": lp["cost_price"] if lp else sp["cost_price"],
            "volume": lp["shares"] if lp else None,
            "op_date": None,
            "note": "对账修正-清空",
            "source": "manual",
        })

    # only_settlement 或 mismatch 重建：补一条 buy
    position_log.insert_log({
        "op_type": "buy",
        "symbol": symbol,
        "name": item["name"],
        "price": sp["cost_price"],
        "volume": sp["shares"],
        "amount": sp["total_cost"],
        "op_date": None,
        "note": "对账修正",
        "source": "manual",
    })
    logger.info("reconcile fix: %s rebuilt to settlement snapshot for %s", diff, symbol)
    return {"ok": True, "action": "fix", "symbol": symbol, "diff_type": diff}
