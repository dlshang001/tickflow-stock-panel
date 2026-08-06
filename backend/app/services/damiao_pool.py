"""大喵观察票池服务(按推荐事件存储)。

存储:`data/user_data/damiao_pool.parquet`。
每条记录 = 一次推荐事件(唯一 id),同一只票不同日期可重复出现。
字段:id/symbol/added_at/source_date/category/strategy/anchor_price/exit_price/note。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = {
    "id": pl.Utf8,
    "symbol": pl.Utf8,
    "added_at": pl.Utf8,
    "source_date": pl.Utf8,
    "category": pl.Utf8,
    "strategy": pl.Utf8,
    "anchor_price": pl.Float64,
    "exit_price": pl.Float64,
    "note": pl.Utf8,
}


def _path() -> Path:
    p = settings.data_dir / "user_data" / "damiao_pool.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_SCHEMA)


def list_rows() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    if df.is_empty():
        return []
    # 新加的在前
    return df.sort("added_at", descending=True, nulls_last=True).to_dicts()


def add(
    symbol: str,
    source_date: str = "",
    category: str = "new_watch",
    strategy: str = "",
    note: str = "",
    anchor_price: float | None = None,
) -> list[dict]:
    p = _path()
    if p.exists():
        df = pl.read_parquet(p)
    else:
        df = _empty()

    row_id = f"dm_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    new_row = pl.DataFrame({
        "id": [row_id],
        "symbol": [symbol],
        "added_at": [datetime.utcnow().isoformat(timespec="seconds")],
        "source_date": [source_date or datetime.now().strftime("%Y-%m-%d")],
        "category": [category or "new_watch"],
        "strategy": [strategy or ""],
        "anchor_price": [anchor_price],
        "exit_price": [None],
        "note": [note or ""],
    }, schema=_SCHEMA)
    out = pl.concat([new_row, df], how="diagonal_relaxed")
    out.write_parquet(p)
    return out.sort("added_at", descending=True, nulls_last=True).to_dicts()


def update(row_id: str, **fields) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    if df.is_empty() or row_id not in df["id"].to_list():
        return df.sort("added_at", descending=True, nulls_last=True).to_dicts()
    exprs = []
    for k, v in fields.items():
        if k in _SCHEMA and v is not None:
            exprs.append(pl.when(pl.col("id") == row_id).then(pl.lit(v)).otherwise(pl.col(k)).alias(k))
    if exprs:
        df = df.with_columns(exprs)
    df.write_parquet(p)
    return df.sort("added_at", descending=True, nulls_last=True).to_dicts()


def mark_exit(row_id: str, category: str, exit_price: float | None = None) -> list[dict]:
    return update(row_id, category=category, exit_price=exit_price)


def remove(row_id: str) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    df = df.filter(pl.col("id") != row_id)
    df.write_parquet(p)
    return df.sort("added_at", descending=True, nulls_last=True).to_dicts()


def clear() -> int:
    p = _path()
    if not p.exists():
        return 0
    df = pl.read_parquet(p)
    count = df.height
    if count > 0:
        _empty().write_parquet(p)
    return count


def resolve_anchor_price(symbol: str, repo, capset) -> float | None:
    """按 实时价 -> 当日收盘价 顺序取锚定价;都取不到返回 None。"""
    price: float | None = None
    # 1. 实时价
    try:
        from app.services import watchlist as _wl
        quotes = _wl.fetch_quotes([symbol], capset)
        if quotes:
            q = quotes[0]
            raw = q.get("price") or q.get("last_price")
            if raw is not None:
                price = float(raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("anchor realtime quote failed for %s: %s", symbol, e)

    if price is not None:
        return price

    # 2. 当日收盘价(从 enriched 缓存)
    try:
        if repo is not None:
            etf_set = repo.get_etf_symbol_set()
            if symbol in etf_set:
                df_e, _ = repo.get_enriched_latest_asset("etf")
            else:
                df_e, _ = repo.get_enriched_latest()
            if not df_e.is_empty() and "symbol" in df_e.columns and "close" in df_e.columns:
                hit = df_e.filter(pl.col("symbol") == symbol)
                if not hit.is_empty():
                    val = hit["close"][0]
                    if val is not None:
                        return float(val)
    except Exception as e:  # noqa: BLE001
        logger.debug("anchor close fallback failed for %s: %s", symbol, e)

    return None
