"""持仓服务(当前持仓清单)。

存储:`data/user_data/positions.parquet`。
一个 symbol 一行,重复录入执行 upsert(覆盖)。
字段:symbol/shares/cost_price/opened_at/note/added_at。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = {
    "symbol": pl.Utf8,
    "shares": pl.Float64,
    "cost_price": pl.Float64,
    "opened_at": pl.Utf8,
    "note": pl.Utf8,
    "added_at": pl.Utf8,
}


def _path() -> Path:
    p = settings.data_dir / "user_data" / "positions.parquet"
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
    return df.to_dicts()


def upsert(
    symbol: str,
    shares: float,
    cost_price: float,
    opened_at: str | None = None,
    note: str = "",
) -> list[dict]:
    p = _path()
    if p.exists():
        df = pl.read_parquet(p)
        if not df.is_empty() and symbol in df["symbol"].to_list():
            df = df.filter(pl.col("symbol") != symbol)
    else:
        df = _empty()

    now = datetime.utcnow().isoformat(timespec="seconds")
    new_row = pl.DataFrame({
        "symbol": [symbol],
        "shares": [float(shares)],
        "cost_price": [float(cost_price)],
        "opened_at": [opened_at or ""],
        "note": [note or ""],
        "added_at": [now],
    }, schema=_SCHEMA)
    out = pl.concat([df, new_row], how="diagonal_relaxed")
    out.write_parquet(p)
    return out.to_dicts()


def update(symbol: str, **fields) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    if df.is_empty() or symbol not in df["symbol"].to_list():
        return df.to_dicts()
    exprs = []
    for k, v in fields.items():
        if k in _SCHEMA and k != "symbol" and v is not None:
            exprs.append(pl.when(pl.col("symbol") == symbol).then(pl.lit(v)).otherwise(pl.col(k)).alias(k))
    if exprs:
        df = df.with_columns(exprs)
    df.write_parquet(p)
    return df.to_dicts()


def remove(symbol: str) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    df = df.filter(pl.col("symbol") != symbol)
    df.write_parquet(p)
    return df.to_dicts()


def clear() -> int:
    p = _path()
    if not p.exists():
        return 0
    df = pl.read_parquet(p)
    count = df.height
    if count > 0:
        _empty().write_parquet(p)
    return count
