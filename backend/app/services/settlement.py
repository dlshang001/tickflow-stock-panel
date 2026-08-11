"""交割单存储服务。

存储：data/user_data/settlement_records.parquet
去重键（service 层内存判重）：(symbol, trade_date, direction, price, volume)
所有写操作走模块级 Lock + 临时文件原子替换，与 position_log 同款。
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

import polars as pl

from app.config import settings
from app.services import position_log

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, type[pl.DataType]] = {
    "id": pl.Int64,
    "trade_date": pl.Utf8,
    "symbol": pl.Utf8,
    "name": pl.Utf8,
    "direction": pl.Utf8,        # 买入 / 卖出
    "price": pl.Float64,
    "volume": pl.Int64,
    "amount": pl.Float64,
    "commission": pl.Float64,
    "stamp_duty": pl.Float64,
    "transfer_fee": pl.Float64,
    "net_amount": pl.Float64,
    "source": pl.Utf8,
    "batch_id": pl.Utf8,
    "created_at": pl.Utf8,
}

_lock = threading.Lock()


def _path() -> Path:
    p = settings.data_dir / "user_data" / "settlement_records.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_SCHEMA)


def _read() -> pl.DataFrame:
    p = _path()
    if not p.exists():
        return _empty()
    df = pl.read_parquet(p)
    if df.is_empty():
        return _empty()
    for col, dtype in _SCHEMA.items():
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(dtype).alias(col))
    return df


def _write(df: pl.DataFrame) -> None:
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


def _row_to_dict(row: dict) -> dict:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, float) and v != v:
            out[k] = None
    return out


def _dedup_key(rec: dict) -> tuple:
    return (
        str(rec.get("symbol")),
        str(rec.get("trade_date")),
        str(rec.get("direction")),
        round(float(rec.get("price") or 0), 4),
        int(rec.get("volume") or 0),
    )


# ════════════════════════════════════════════════════════════
#  查询
# ════════════════════════════════════════════════════════════

def list_records(
    date_from: str | None = None,
    date_to: str | None = None,
    symbol: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    df = _read()
    if df.is_empty():
        return {"rows": [], "total": 0, "page": page, "size": size, "summary": _summary([])}

    df = df.sort(["trade_date", "id"], descending=[True, True])
    if date_from:
        df = df.filter(pl.col("trade_date") >= date_from)
    if date_to:
        df = df.filter(pl.col("trade_date") <= date_to)
    if symbol:
        df = df.filter(pl.col("symbol") == symbol)

    total = df.height
    start = max(0, (page - 1) * size)
    page_df = df.slice(start, size)
    rows = [_row_to_dict(r) for r in page_df.to_dicts()]
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "size": size,
        "summary": _summary([_row_to_dict(r) for r in df.to_dicts()]),
    }


def latest_date() -> str | None:
    df = _read()
    if df.is_empty():
        return None
    return str(df["trade_date"].max())


def all_records() -> list[dict]:
    df = _read()
    if df.is_empty():
        return []
    return [_row_to_dict(r) for r in df.sort(["trade_date", "id"]).to_dicts()]


# ════════════════════════════════════════════════════════════
#  导入
# ════════════════════════════════════════════════════════════

def preview_import(records: list[dict]) -> dict:
    """对比现有库，计算新增/重复（不落库）。"""
    df = _read()
    existing_keys = _existing_keys(df)
    new_records = [r for r in records if _dedup_key(r) not in existing_keys]
    return {
        "preview": new_records,
        "new_count": len(new_records),
        "skipped": len(records) - len(new_records),
        "latest_db_date": str(df["trade_date"].max()) if not df.is_empty() else None,
    }


def commit_import(records: list[dict], batch_id: str | None = None) -> dict:
    """落库：去重后写入，并把新增记录幂等同步到 position_log。

    返回 {imported, skipped, batch_id}。
    """
    with _lock:
        df = _read()
        existing_keys = _existing_keys(df)
        bid = batch_id or str(uuid.uuid4())
        created = _now_iso()
        next_id = _next_id(df)

        new_rows: list[dict] = []
        for rec in records:
            key = _dedup_key(rec)
            if key in existing_keys:
                continue
            row = {
                "id": next_id,
                "trade_date": str(rec["trade_date"]),
                "symbol": str(rec["symbol"]),
                "name": str(rec.get("name") or ""),
                "direction": str(rec["direction"]),
                "price": float(rec.get("price") or 0),
                "volume": int(rec.get("volume") or 0),
                "amount": float(rec.get("amount") or 0),
                "commission": float(rec.get("commission") or 0),
                "stamp_duty": float(rec.get("stamp_duty") or 0),
                "transfer_fee": float(rec.get("transfer_fee") or 0),
                "net_amount": float(rec.get("net_amount") or 0),
                "source": str(rec.get("source") or "tonghuashun_settlement"),
                "batch_id": bid,
                "created_at": created,
            }
            new_rows.append(row)
            existing_keys.add(key)
            next_id += 1

        imported = len(new_rows)
        if new_rows:
            new_df = pl.DataFrame(new_rows, schema=_SCHEMA)
            out = pl.concat([df, new_df], how="diagonal_relaxed")
            _write(out)
            logger.info("settlement import: %d new records (batch=%s)", imported, bid)

    # 同步到操作日志（锁外即可，其内部自有锁；幂等）
    if new_rows:
        position_log.sync_from_settlements(new_rows)

    return {"imported": imported, "skipped": len(records) - imported, "batch_id": bid}


def _existing_keys(df: pl.DataFrame) -> set[tuple]:
    if df.is_empty():
        return set()
    return {
        (
            str(r["symbol"]), str(r["trade_date"]), str(r["direction"]),
            round(float(r["price"]), 4), int(r["volume"]),
        )
        for r in df.to_dicts()
    }


# ════════════════════════════════════════════════════════════
#  删除
# ════════════════════════════════════════════════════════════

def clear_all() -> int:
    """清空全部交割单。同时删除由交割单生成的 position_log 记录。"""
    with _lock:
        df = _read()
        n = df.height
        _write(_empty())
    # 级联清理 source=settlement 的操作日志
    position_log.delete_logs_by_source("settlement")
    return n


def delete_by_batch(batch_id: str) -> int:
    with _lock:
        df = _read()
        if df.is_empty():
            return 0
        before = df.height
        out = df.filter(pl.col("batch_id") != batch_id)
        _write(out)
        return before - out.height


# ════════════════════════════════════════════════════════════
#  统计
# ════════════════════════════════════════════════════════════

def _summary(records: list[dict]) -> dict:
    buy_count = sell_count = 0
    buy_amount = sell_amount = 0.0
    commission = stamp = transfer = 0.0
    for r in records:
        commission += float(r.get("commission") or 0)
        stamp += float(r.get("stamp_duty") or 0)
        transfer += float(r.get("transfer_fee") or 0)
        if r.get("direction") == "买入":
            buy_count += 1
            buy_amount += float(r.get("amount") or 0)
        elif r.get("direction") == "卖出":
            sell_count += 1
            sell_amount += float(r.get("amount") or 0)
    return {
        "count": len(records),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "buy_amount": round(buy_amount + 1e-9, 2),
        "sell_amount": round(sell_amount + 1e-9, 2),
        "commission": round(commission + 1e-9, 2),
        "stamp_duty": round(stamp + 1e-9, 2),
        "transfer_fee": round(transfer + 1e-9, 2),
        "total_fees": round(commission + stamp + transfer + 1e-9, 2),
    }


def compute_stats() -> dict:
    """聚合统计（图表数据）。

    返回：
      summary:           汇总（笔数/金额/费用）
      realized_pnl_curve: 按日期累积已实现盈亏 [{date, pnl, cumulative}]
      monthly:           月度盈亏 [{month, pnl, buy_amount, sell_amount}]
      by_symbol:         单票盈亏 [{symbol, name, pnl, buy_count, sell_count}]
      fees:              费用明细
      records_count:     总记录数
    """
    records = all_records()
    if not records:
        return {
            "summary": _summary([]),
            "realized_pnl_curve": [],
            "monthly": [],
            "by_symbol": [],
            "fees": {"commission": 0, "stamp_duty": 0, "transfer_fee": 0, "total": 0},
            "records_count": 0,
        }

    # ── 已实现盈亏（FIFO 配对） ──
    by_symbol: dict[str, list[dict]] = {}
    for r in records:
        by_symbol.setdefault(str(r["symbol"]), []).append(r)

    pnl_events: list[dict] = []  # [{date, symbol, name, pnl}]
    symbol_pnl: dict[str, dict] = {}  # symbol → {name, pnl, buy_count, sell_count}

    for sym, recs in by_symbol.items():
        ordered = sorted(recs, key=lambda r: (str(r.get("trade_date") or ""), int(r.get("id") or 0)))
        queue: list[dict] = []  # [{price, volume, date}]
        name = sym
        sym_pnl = 0.0
        buy_cnt = sell_cnt = 0
        for r in ordered:
            if r.get("name"):
                name = str(r["name"])
            direction = str(r.get("direction") or "").strip()
            price = float(r.get("price") or 0)
            volume = float(r.get("volume") or 0)
            if direction == "买入":
                if price > 0 and volume > 0:
                    queue.append({"price": price, "volume": volume, "date": str(r.get("trade_date") or "")})
                buy_cnt += 1
            elif direction == "卖出":
                sell_cnt += 1
                remaining = volume
                while remaining > 1e-9 and queue:
                    lot = queue[0]
                    matched = min(lot["volume"], remaining)
                    realized = (price - lot["price"]) * matched
                    sym_pnl += realized
                    pnl_events.append({
                        "date": str(r.get("trade_date") or ""),
                        "symbol": sym,
                        "name": name,
                        "pnl": round(realized + 1e-9, 2),
                    })
                    lot["volume"] -= matched
                    remaining -= matched
                    if lot["volume"] <= 1e-9:
                        queue.pop(0)
        symbol_pnl[sym] = {
            "symbol": sym,
            "name": name,
            "pnl": round(sym_pnl + 1e-9, 2),
            "buy_count": buy_cnt,
            "sell_count": sell_cnt,
        }

    # ── 累积盈亏曲线（按日期排序） ──
    pnl_events.sort(key=lambda e: e["date"])
    pnl_curve: list[dict] = []
    cumulative = 0.0
    for e in pnl_events:
        cumulative += e["pnl"]
        pnl_curve.append({
            "date": e["date"],
            "pnl": e["pnl"],
            "cumulative": round(cumulative + 1e-9, 2),
        })

    # ── 月度盈亏 ──
    monthly_map: dict[str, dict] = {}
    for e in pnl_events:
        month = e["date"][:7]  # YYYY-MM
        if month not in monthly_map:
            monthly_map[month] = {"month": month, "pnl": 0.0, "buy_amount": 0.0, "sell_amount": 0.0}
        monthly_map[month]["pnl"] += e["pnl"]
    # 补充买卖金额
    for r in records:
        month = str(r.get("trade_date") or "")[:7]
        if month not in monthly_map:
            monthly_map[month] = {"month": month, "pnl": 0.0, "buy_amount": 0.0, "sell_amount": 0.0}
        direction = str(r.get("direction") or "").strip()
        amount = float(r.get("amount") or 0)
        if direction == "买入":
            monthly_map[month]["buy_amount"] += amount
        elif direction == "卖出":
            monthly_map[month]["sell_amount"] += amount
    monthly = sorted(monthly_map.values(), key=lambda m: m["month"])
    for m in monthly:
        m["pnl"] = round(m["pnl"] + 1e-9, 2)
        m["buy_amount"] = round(m["buy_amount"] + 1e-9, 2)
        m["sell_amount"] = round(m["sell_amount"] + 1e-9, 2)

    # ── 单票盈亏（按盈亏绝对值排序） ──
    by_symbol_list = sorted(symbol_pnl.values(), key=lambda s: abs(s["pnl"]), reverse=True)

    # ── 费用明细 ──
    s = _summary(records)
    fees = {
        "commission": s["commission"],
        "stamp_duty": s["stamp_duty"],
        "transfer_fee": s["transfer_fee"],
        "total": s["total_fees"],
    }

    return {
        "summary": s,
        "realized_pnl_curve": pnl_curve,
        "monthly": monthly,
        "by_symbol": by_symbol_list,
        "fees": fees,
        "records_count": len(records),
    }
