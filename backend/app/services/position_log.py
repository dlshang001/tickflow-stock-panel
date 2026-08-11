"""操作日志存储 + FIFO 持仓引擎（阶段 0 地基）。

设计要点见 docs/POSITION_SETTLEMENT_DESIGN.md。

一期范围：
  - 操作类型仅 buy / sell / clear（initial 用于历史迁移，语义同 buy）。
  - 单用户、本地 Parquet 存储：data/user_data/position_log.parquet。
  - 写操作全部走模块级 Lock + 临时文件原子替换。
  - 当前持仓由 compute_positions() 从日志按 FIFO 派生，不再直接存持仓数字。

存储字段见 _SCHEMA。现金(free_cash)存于 preferences.json，与买卖联动由
调用方(add_trade)统一处理，本模块只提供读写与校验。
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

# 一期操作类型；initial 仅由历史迁移写入，语义等同 buy
OpType = Literal["buy", "sell", "clear", "initial"]
LogSource = Literal["manual", "settlement", "migration"]

_OP_TYPES = ("buy", "sell", "clear", "initial")
_SOURCES = ("manual", "settlement", "migration")

_SCHEMA: dict[str, type[pl.DataType]] = {
    "id": pl.Int64,
    "op_date": pl.Utf8,
    "op_type": pl.Utf8,
    "symbol": pl.Utf8,
    "name": pl.Utf8,
    "price": pl.Float64,
    "volume": pl.Float64,
    "amount": pl.Float64,
    "commission": pl.Float64,
    "stamp_duty": pl.Float64,
    "transfer_fee": pl.Float64,
    "note": pl.Utf8,
    "source": pl.Utf8,
    "settlement_id": pl.Int64,
    "settlement_batch_id": pl.Utf8,
    "created_at": pl.Utf8,
}

# 写锁：请求线程可能并发"读-改-写"同一个 parquet，串行化写路径。
_lock = threading.Lock()


# ════════════════════════════════════════════════════════════
#  存储底座
# ════════════════════════════════════════════════════════════

def _path() -> Path:
    p = settings.data_dir / "user_data" / "position_log.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _legacy_positions_path() -> Path:
    return settings.data_dir / "user_data" / "positions.parquet"


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_SCHEMA)


def _read() -> pl.DataFrame:
    p = _path()
    if not p.exists():
        return _empty()
    df = pl.read_parquet(p)
    if df.is_empty():
        return _empty()
    # 补齐可能缺失的列（历史版本向前兼容）
    for col, dtype in _SCHEMA.items():
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(dtype).alias(col))
    return df


def _write(df: pl.DataFrame) -> None:
    """原子写：临时文件 + os.replace，避免进程中断留下半截 parquet。"""
    p = _path()
    tmp = p.with_suffix(p.suffix + ".tmp")
    df.write_parquet(tmp)
    os.replace(tmp, p)


def _next_id(df: pl.DataFrame) -> int:
    if df.is_empty():
        return 1
    return int(df["id"].max()) + 1


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()


def _row_to_dict(row: dict) -> dict:
    """把一行规整为对外 JSON 友好的 dict（NaN→None）。"""
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, float) and (v != v):  # NaN
            out[k] = None
    return out


# ════════════════════════════════════════════════════════════
#  查询
# ════════════════════════════════════════════════════════════

def list_logs(symbol: str | None = None) -> list[dict]:
    """返回操作日志，按 (op_date, id) 升序。可选按 symbol 过滤。"""
    df = _read()
    if df.is_empty():
        return []
    df = df.sort(["op_date", "id"])
    if isinstance(symbol, str) and symbol:
        df = df.filter(pl.col("symbol") == symbol)
    return [_row_to_dict(r) for r in df.to_dicts()]


def has_migration_logs() -> bool:
    """是否已存在迁移日志（用于迁移幂等判断）。"""
    df = _read()
    if df.is_empty():
        return False
    return df.filter(pl.col("source") == "migration").height > 0


# ════════════════════════════════════════════════════════════
#  FIFO 持仓引擎
# ════════════════════════════════════════════════════════════

@dataclass
class BuyLot:
    price: float
    volume: float
    date: str
    log_id: int | None = None


@dataclass
class ComputedPosition:
    symbol: str
    name: str
    shares: float
    cost_price: float       # 剩余批次加权平均成本
    total_cost: float
    buy_date: str | None    # 最早建仓日
    opened_at: str | None   # 别名，对齐旧 PositionEntry
    note: str
    added_at: str           # 该标的最早一条日志的 created_at


def _round_money(v: float) -> float:
    return round(v + 1e-9, 2)


def _round_price(v: float) -> float:
    return round(v + 1e-9, 4)


def compute_positions(logs: list[dict] | None = None) -> list[ComputedPosition]:
    """从操作日志按 FIFO 计算当前持仓。

    规则：
      buy/initial → 入队一个批次
      sell        → 从队首逐批扣减（不得超过当前持仓）
      clear       → 清空该标的买入队列
    返回剩余批次 = 当前持仓，成本为剩余批次加权平均。
    """
    if logs is None:
        logs = list_logs()
    if not logs:
        return []

    by_symbol: dict[str, list[dict]] = {}
    for log in logs:
        by_symbol.setdefault(log["symbol"], []).append(log)

    result: list[ComputedPosition] = []
    for symbol, sym_logs in by_symbol.items():
        ordered = sorted(sym_logs, key=lambda r: (r.get("op_date") or "", r.get("id") or 0))
        queue: list[BuyLot] = []
        consumed: list[dict] = []

        for log in ordered:
            consumed.append(log)
            op = log.get("op_type")
            price = log.get("price")
            volume = log.get("volume")

            if op in ("buy", "initial"):
                if price is not None and volume and volume > 0:
                    queue.append(BuyLot(
                        price=float(price),
                        volume=float(volume),
                        date=log.get("op_date") or "",
                        log_id=log.get("id"),
                    ))
            elif op == "sell":
                if volume and volume > 0:
                    remaining = float(volume)
                    while remaining > 1e-9 and queue:
                        lot = queue[0]
                        matched = min(lot.volume, remaining)
                        lot.volume -= matched
                        remaining -= matched
                        if lot.volume <= 1e-9:
                            queue.pop(0)
            elif op == "clear":
                queue.clear()

        if not queue:
            continue

        total_shares = sum(lot.volume for lot in queue)
        if total_shares <= 1e-9:
            continue
        total_cost = sum(lot.price * lot.volume for lot in queue)
        avg_price = total_cost / total_shares

        # 名称：取该标的第一条非空 name
        name = symbol
        for r in consumed:
            if r.get("name"):
                name = r["name"]
                break
        # note：取最新一条非空备注
        note = ""
        for r in reversed(consumed):
            if r.get("note"):
                note = r["note"]
                break
        added_at = consumed[0].get("created_at") or ""

        result.append(ComputedPosition(
            symbol=symbol,
            name=name,
            shares=_round_money(total_shares),
            cost_price=_round_price(avg_price),
            total_cost=_round_money(total_cost),
            buy_date=queue[0].date or None,
            opened_at=queue[0].date or None,
            note=note,
            added_at=added_at,
        ))

    result.sort(key=lambda p: p.symbol)
    return result


def get_position(symbol: str, logs: list[dict] | None = None) -> ComputedPosition | None:
    for p in compute_positions(logs):
        if p.symbol == symbol:
            return p
    return None


class TradeError(ValueError):
    """交易业务校验失败（卖出超量/现金不足等），API 层映射为 400。"""


@dataclass
class TradeResult:
    log: dict
    positions: list[dict]   # 交易后的当前持仓（ComputedPosition 字典化）
    free_cash: float


def add_trade(
    op_type: str,
    symbol: str,
    price: float | None = None,
    volume: float | None = None,
    op_date: str | None = None,
    commission: float = 0.0,
    stamp_duty: float = 0.0,
    transfer_fee: float = 0.0,
    note: str = "",
    name: str = "",
    source: LogSource = "manual",
    settlement_id: int | None = None,
    settlement_batch_id: str | None = None,
) -> TradeResult:
    """写入一笔交易并联动可用资金。

    业务规则：
      - buy：必须有 price>0、volume>0；现金流为 -(成交额+费用)，不得使现金为负。
      - sell：必须有 price>0、volume>0，且成交量不得超过 FIFO 当前持仓；
              现金流为 +(成交额-费用)。
      - clear：清仓。price 必填；volume 缺省=当前持仓量（一次性清空）。
    写日志与调现金在同一把锁内完成，避免并发读到中间状态。
    """
    symbol = str(symbol or "").strip()
    if not symbol:
        raise TradeError("证券代码不能为空")

    with _lock:
        # 先基于当前日志计算持仓，做校验
        current = get_position(symbol, list_logs())
        fees = float(commission) + float(stamp_duty) + float(transfer_fee)
        amount: float | None = None

        if op_type in ("buy", "initial"):
            if price is None or price <= 0:
                raise TradeError("买入价格必须大于 0")
            if not volume or volume <= 0:
                raise TradeError("买入数量必须大于 0")
            amount = round(float(price) * float(volume) + 1e-9, 2)
            cash_delta = -(amount + fees)
            vol: float | None = float(volume)

        elif op_type == "sell":
            if price is None or price <= 0:
                raise TradeError("卖出价格必须大于 0")
            if not volume or volume <= 0:
                raise TradeError("卖出数量必须大于 0")
            held = current.shares if current else 0.0
            if float(volume) - held > 1e-6:
                raise TradeError(
                    f"卖出数量 {float(volume):g} 超过当前持仓 {held:g}"
                )
            amount = round(float(price) * float(volume) + 1e-9, 2)
            cash_delta = amount - fees
            vol = float(volume)

        elif op_type == "clear":
            if price is None or price <= 0:
                raise TradeError("清仓价格必须大于 0")
            held = current.shares if current else 0.0
            if held <= 0:
                raise TradeError("当前无持仓，无法清仓")
            amount = round(float(price) * held + 1e-9, 2)
            cash_delta = amount - fees
            vol = held  # 全清

        else:
            raise TradeError(f"不支持的操作类型: {op_type}")

        # 现金校验（买入可能导致透支）
        cash_now = get_free_cash()
        if cash_now + cash_delta < -1e-6:
            raise TradeError(
                f"可用资金不足：当前 {cash_now:.2f}，本次需 "
                f"{-cash_delta:.2f}"
            )

        log = _insert_log_locked({
            "op_date": op_date or _today(),
            "op_type": op_type,
            "symbol": symbol,
            "name": name or (current.name if current else ""),
            "price": float(price),
            "volume": vol,
            "amount": amount,
            "commission": float(commission),
            "stamp_duty": float(stamp_duty),
            "transfer_fee": float(transfer_fee),
            "note": note,
            "source": source,
            "settlement_id": settlement_id,
            "settlement_batch_id": settlement_batch_id,
        })

        # 联动现金
        new_cash = set_free_cash(cash_now + cash_delta)

        positions = [
            _computed_to_dict(p) for p in compute_positions(list_logs())
        ]
        return TradeResult(log=log, positions=positions, free_cash=new_cash)


def _computed_to_dict(p: ComputedPosition) -> dict:
    return {
        "symbol": p.symbol,
        "name": p.name,
        "shares": p.shares,
        "cost_price": p.cost_price,
        "total_cost": p.total_cost,
        "buy_date": p.buy_date,
        "opened_at": p.opened_at,
        "note": p.note,
        "added_at": p.added_at,
    }


# ════════════════════════════════════════════════════════════
#  写入（底层）
# ════════════════════════════════════════════════════════════

def _normalize_log(log: dict) -> dict:
    """补齐字段、做类型/取值归一化。"""
    op_type = log.get("op_type")
    if op_type not in _OP_TYPES:
        raise ValueError(f"invalid op_type: {op_type!r}")
    source = log.get("source", "manual")
    if source not in _SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    symbol = str(log.get("symbol") or "").strip()
    if not symbol:
        raise ValueError("symbol is required")

    price = log.get("price")
    price = float(price) if price not in (None, "") else None
    volume = log.get("volume")
    volume = float(volume) if volume not in (None, "") else None
    amount = log.get("amount")
    amount = float(amount) if amount not in (None, "") else None

    return {
        "op_date": str(log.get("op_date") or _today()),
        "op_type": op_type,
        "symbol": symbol,
        "name": str(log.get("name") or ""),
        "price": price,
        "volume": volume,
        "amount": amount,
        "commission": float(log.get("commission") or 0),
        "stamp_duty": float(log.get("stamp_duty") or 0),
        "transfer_fee": float(log.get("transfer_fee") or 0),
        "note": str(log.get("note") or ""),
        "source": source,
        "settlement_id": int(log["settlement_id"]) if log.get("settlement_id") else None,
        "settlement_batch_id": str(log["settlement_batch_id"]) if log.get("settlement_batch_id") else None,
    }


def _insert_log_locked(log: dict) -> dict:
    """插入单条日志（调用方必须已持有 _lock）。返回含 id/created_at 的记录。"""
    df = _read()
    norm = _normalize_log(log)
    norm["id"] = _next_id(df)
    norm["created_at"] = _now_iso()
    new_row = pl.DataFrame([norm], schema=_SCHEMA)
    out = pl.concat([df, new_row], how="diagonal_relaxed")
    _write(out)
    return _row_to_dict(norm)


def insert_log(log: dict) -> dict:
    """插入单条日志，返回含 id/created_at 的完整记录。"""
    with _lock:
        return _insert_log_locked(log)


def insert_logs_batch(logs: list[dict], batch_size: int = 500) -> int:
    """批量插入。自动补齐 id/created_at。返回插入条数。"""
    if not logs:
        return 0
    with _lock:
        df = _read()
        next_id = _next_id(df)
        created = _now_iso()
        rows: list[dict] = []
        for log in logs:
            norm = _normalize_log(log)
            norm["id"] = next_id
            norm["created_at"] = created
            next_id += 1
            rows.append(norm)
        # polars 批量构造
        new_df = pl.DataFrame(rows, schema=_SCHEMA)
        out = pl.concat([df, new_df], how="diagonal_relaxed")
        _write(out)
        return len(rows)


def delete_log(log_id: int) -> bool:
    """删除单条日志。返回是否删除了记录。"""
    with _lock:
        df = _read()
        if df.is_empty() or log_id not in df["id"].to_list():
            return False
        out = df.filter(pl.col("id") != log_id)
        _write(out)
        return True


def delete_logs_by_symbol(symbol: str, source: LogSource | None = None) -> int:
    """删除某标的全部（或某来源）日志。返回删除条数。"""
    with _lock:
        df = _read()
        if df.is_empty():
            return 0
        mask = pl.col("symbol") == symbol
        if source:
            mask = mask & (pl.col("source") == source)
        before = df.height
        out = df.filter(~mask)
        _write(out)
        return before - out.height


def delete_logs_by_source(source: LogSource) -> int:
    """删除指定来源的全部日志（如清空交割单时级联清理）。"""
    with _lock:
        df = _read()
        if df.is_empty():
            return 0
        before = df.height
        out = df.filter(pl.col("source") != source)
        _write(out)
        return before - out.height


def sync_from_settlements(records: list[dict]) -> int:
    """把交割单记录幂等同步为 position_log（source='settlement'）。

    records 中每条需含 id/symbol/name/direction/price/volume/amount/
    commission/stamp_duty/transfer_fee/trade_date/batch_id。
    按 settlement_id 去重，已同步的跳过。返回新增日志条数。

    注意：本函数直接写日志，不联动 free_cash（现金以交割单实际发生额为准由对账/统计处理，
    一期避免与手动交易的现金变动重复计算）。
    """
    if not records:
        return 0
    with _lock:
        df = _read()
        existing_ids: set[int] = set()
        if not df.is_empty():
            existing_ids = {
                int(x) for x in df.filter(pl.col("source") == "settlement")
                .get_column("settlement_id").drop_nulls().to_list()
            }

        next_id = _next_id(df)
        created = _now_iso()
        rows: list[dict] = []
        for r in records:
            sid = int(r["id"])
            if sid in existing_ids:
                continue
            direction = str(r.get("direction") or "").strip()
            op_type = "buy" if direction == "买入" else "sell"
            price = float(r.get("price") or 0)
            volume = float(r.get("volume") or 0)
            amount = float(r.get("amount") or 0)
            rows.append({
                "id": next_id,
                "op_date": str(r["trade_date"]),
                "op_type": op_type,
                "symbol": str(r["symbol"]),
                "name": str(r.get("name") or ""),
                "price": price,
                "volume": volume,
                "amount": amount,
                "commission": float(r.get("commission") or 0),
                "stamp_duty": float(r.get("stamp_duty") or 0),
                "transfer_fee": float(r.get("transfer_fee") or 0),
                "note": f"交割单 {direction}",
                "source": "settlement",
                "settlement_id": sid,
                "settlement_batch_id": str(r.get("batch_id") or ""),
                "created_at": created,
            })
            next_id += 1

        if not rows:
            return 0
        new_df = pl.DataFrame(rows, schema=_SCHEMA)
        out = pl.concat([df, new_df], how="diagonal_relaxed")
        _write(out)
        logger.info("synced %d settlement records to position_log", len(rows))
        return len(rows)


def clear_all_logs() -> int:
    """清空全部日志。返回删除条数。"""
    with _lock:
        df = _read()
        n = df.height
        _write(_empty())
        return n


# ════════════════════════════════════════════════════════════
#  现金（存 preferences.json）
# ════════════════════════════════════════════════════════════

def get_free_cash() -> float:
    from app.services import preferences
    return float(preferences.load().get("free_cash", 0) or 0)


def set_free_cash(value: float) -> float:
    from app.services import preferences
    v = max(0.0, round(float(value) + 1e-9, 2))
    preferences.save({"free_cash": v})
    return v


def adjust_free_cash(delta: float) -> float:
    """在当前现金基础上增减；结果不低于 0，否则抛 ValueError。"""
    with _lock:
        current = get_free_cash()
        new_v = round(current + float(delta) + 1e-9, 2)
        if new_v < 0:
            raise ValueError(
                f"可用资金不足: 当前 {current:.2f}, 本次变动 {delta:.2f}, 结果 {new_v:.2f}"
            )
        return set_free_cash(new_v)


# ════════════════════════════════════════════════════════════
#  历史迁移：positions.parquet → position_log（source=migration）
# ════════════════════════════════════════════════════════════

def migrate_legacy_positions() -> int:
    """把旧 positions.parquet 的每条持仓转成一条 buy 日志。

    幂等：若已存在 source='migration' 的日志则跳过。
    迁移前把旧文件备份为 positions.parquet.bak。
    返回写入的日志条数（跳过则返回 0）。
    """
    with _lock:
        existing = _read()
        if not existing.is_empty() and existing.filter(pl.col("source") == "migration").height > 0:
            logger.info("legacy positions already migrated, skip")
            return 0

        legacy = _legacy_positions_path()
        if not legacy.exists():
            logger.info("no legacy positions.parquet found, skip migration")
            return 0

        # 备份旧文件
        backup = legacy.with_suffix(legacy.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(legacy, backup)
            logger.info("legacy positions backed up: %s", backup)

        old = pl.read_parquet(legacy)
        if old.is_empty():
            logger.info("legacy positions.parquet is empty, nothing to migrate")
            return 0

        next_id = _next_id(existing)
        created = _now_iso()
        rows: list[dict] = []
        for r in old.to_dicts():
            shares = float(r.get("shares") or 0)
            if shares <= 0:
                continue
            price = float(r.get("cost_price") or 0)
            op_date = str(r.get("opened_at") or _today())
            # opened_at 可能不是合法日期，兜底
            if len(op_date) < 10:
                op_date = _today()
            else:
                op_date = op_date[:10]
            rows.append({
                "id": next_id,
                "op_date": op_date,
                "op_type": "initial",
                "symbol": str(r.get("symbol") or "").strip(),
                "name": str(r.get("name") or ""),
                "price": price,
                "volume": shares,
                "amount": round(price * shares + 1e-9, 2),
                "commission": 0.0,
                "stamp_duty": 0.0,
                "transfer_fee": 0.0,
                "note": "历史持仓迁移",
                "source": "migration",
                "settlement_id": None,
                "settlement_batch_id": None,
                "created_at": str(r.get("added_at") or created),
            })
            next_id += 1

        if not rows:
            return 0

        new_df = pl.DataFrame(rows, schema=_SCHEMA)
        out = pl.concat([existing, new_df], how="diagonal_relaxed")
        _write(out)
        logger.info("legacy positions migrated: %d rows", len(rows))
        return len(rows)
