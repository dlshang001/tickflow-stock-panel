"""持仓 API。"""
from __future__ import annotations

import logging
import time

import polars as pl
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.watchlist import _WATCHLIST_COLS
from app.services import positions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])

_POS_FIELDS = ["shares", "cost_price", "opened_at", "note", "added_at"]


class UpsertRequest(BaseModel):
    symbol: str
    shares: float
    cost_price: float
    opened_at: str | None = ""
    note: str = ""


class UpdateRequest(BaseModel):
    shares: float | None = None
    cost_price: float | None = None
    opened_at: str | None = None
    note: str | None = None


def _with_names(rows: list[dict], request: Request) -> list[dict]:
    if not rows:
        return rows
    try:
        name_by_symbol = request.app.state.repo.get_name_map([r.get("symbol") for r in rows])
        if not name_by_symbol:
            return rows
        return [{**row, "name": name_by_symbol.get(row.get("symbol"))} for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.debug("attach positions names failed: %s", e)
        return rows


@router.get("")
def list_all(request: Request):
    return {"rows": _with_names(positions.list_rows(), request)}


@router.post("")
def upsert_one(req: UpsertRequest, request: Request):
    rows = positions.upsert(
        symbol=req.symbol,
        shares=req.shares,
        cost_price=req.cost_price,
        opened_at=req.opened_at or "",
        note=req.note,
    )
    return {"rows": _with_names(rows, request)}


@router.patch("/{symbol}")
def update_one(symbol: str, req: UpdateRequest, request: Request):
    fields = req.model_dump(exclude_none=True)
    rows = positions.update(symbol, **fields)
    return {"rows": _with_names(rows, request)}


@router.delete("/{symbol}")
def remove_one(symbol: str, request: Request):
    rows = positions.remove(symbol)
    return {"rows": _with_names(rows, request)}


@router.delete("")
def clear_all():
    return {"removed": positions.clear()}


@router.get("/enriched")
def positions_enriched(
    request: Request,
    ext_columns: str | None = Query(None, description="逗号分隔的 ext 列: config_id.field_name"),
):
    """持仓 enriched — 以持仓为主表 LEFT JOIN enriched 最新日缓存。"""
    t0 = time.perf_counter()

    repo = request.app.state.repo
    records = positions.list_rows()
    if not records:
        return {"rows": [], "as_of": None, "elapsed_ms": 0}

    pos_df = pl.DataFrame(records)
    symbols = pos_df["symbol"].to_list()

    etf_set = repo.get_etf_symbol_set()
    df_e, cache_date = repo.get_enriched_latest()
    df_etf_all, etf_date = repo.get_enriched_latest_asset("etf")

    stock_map: dict[str, dict] = {}
    if not df_e.is_empty() and "symbol" in df_e.columns:
        stock_syms = {s for s in symbols if s not in etf_set}
        if stock_syms:
            sub = df_e.filter(pl.col("symbol").is_in(list(stock_syms)))
            if not sub.is_empty():
                stock_map = {r["symbol"]: r for r in sub.to_dicts()}

    etf_map: dict[str, dict] = {}
    if not df_etf_all.is_empty() and "symbol" in df_etf_all.columns:
        etf_syms = {s for s in symbols if s in etf_set}
        if etf_syms:
            sub = df_etf_all.filter(pl.col("symbol").is_in(list(etf_syms)))
            if not sub.is_empty():
                etf_map = {r["symbol"]: r for r in sub.to_dicts()}

    quote_map = {**stock_map, **etf_map}
    quote_rows = [quote_map.get(s, {}) for s in symbols]
    q = pl.DataFrame(quote_rows, infer_schema_length=None)
    if "symbol" not in q.columns:
        q = q.with_columns(pl.Series("symbol", symbols))

    df_i = repo.get_instruments()
    if not df_i.is_empty() and "float_shares" in df_i.columns:
        q = q.join(df_i.select(["symbol", "float_shares"]), on="symbol", how="left")
    name_map = repo.get_name_map(symbols)
    q = q.with_columns(
        pl.col("symbol").replace_strict(name_map, default=None, return_dtype=pl.Utf8).alias("name")
    )

    keep = [c for c in _WATCHLIST_COLS + ["name", "float_shares"] if c in q.columns]
    q = q.select(keep)

    # 拼回持仓字段(按 records 顺序)
    for f in _POS_FIELDS:
        q = q.with_columns(pl.Series(f, [r.get(f) for r in records]))

    if ext_columns:
        from app.api.watchlist import _parse_ext_columns
        from app.api.ext_data import _read_ext_dataframe
        from app.services.ext_data import ExtConfigStore

        db = repo.store.db
        data_dir = repo.store.data_dir
        ext_store = ExtConfigStore(data_dir)
        configs = {c.id: c for c in ext_store.load_all()}
        for config_id, field_name in _parse_ext_columns(ext_columns):
            view_name = f"ext_{config_id}"
            ext_col_name = f"{config_id}__{field_name}"
            try:
                cfg = configs.get(config_id)
                if cfg:
                    ext_df, _ = _read_ext_dataframe(cfg, data_dir)
                else:
                    ext_df = pl.from_arrow(db.query(
                        f"SELECT symbol, \"{field_name}\" FROM {view_name}"
                    ).arrow())
                if not ext_df.is_empty() and "symbol" in ext_df.columns:
                    ext_df = (
                        ext_df
                        .select(["symbol", field_name])
                        .unique(subset=["symbol"], keep="last")
                        .rename({field_name: ext_col_name})
                    )
                    q = q.join(ext_df, on="symbol", how="left")
            except Exception as e:  # noqa: BLE001
                logger.debug("positions ext join failed for %s.%s: %s", config_id, field_name, e)

    float_cols = [c for c in q.columns if q[c].dtype.is_float()]
    if float_cols:
        q = q.with_columns([
            pl.when(pl.col(c).is_nan() | pl.col(c).is_infinite())
              .then(None).otherwise(pl.col(c)).alias(c)
            for c in float_cols
        ])

    dates = [d for d in (cache_date, etf_date) if d is not None]
    as_of = min(dates) if dates else None
    rows = q.to_dicts()
    elapsed = (time.perf_counter() - t0) * 1000
    return {"rows": rows, "as_of": str(as_of) if as_of else None, "elapsed_ms": elapsed}
