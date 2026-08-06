"""大喵观察票池 API。"""
from __future__ import annotations

import logging
import time

import polars as pl
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.watchlist import _WATCHLIST_COLS
from app.services import damiao_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/damiao-pool", tags=["damiao-pool"])

# 观察/收官分类枚举
WATCH_CATEGORIES = {"new_watch", "new_open", "holding_todo", "old_deng", "t_add"}
EXIT_CATEGORIES = {"take_profit", "stop_loss", "closed"}
VALID_CATEGORIES = WATCH_CATEGORIES | EXIT_CATEGORIES


class AddRequest(BaseModel):
    symbol: str
    source_date: str = ""
    category: str = "new_watch"
    strategy: str = ""
    note: str = ""
    anchor_price: float | None = None


class UpdateRequest(BaseModel):
    source_date: str | None = None
    category: str | None = None
    strategy: str | None = None
    anchor_price: float | None = None
    exit_price: float | None = None
    note: str | None = None


class ExitRequest(BaseModel):
    category: str = "closed"
    exit_price: float | None = None


class BatchParseRequest(BaseModel):
    text: str


class BatchAddItem(BaseModel):
    symbol: str
    category: str = "new_watch"
    note: str = ""


class BatchAddRequest(BaseModel):
    items: list[BatchAddItem]
    source_date: str = ""


def _with_names(rows: list[dict], request: Request) -> list[dict]:
    if not rows:
        return rows
    try:
        name_by_symbol = request.app.state.repo.get_name_map([r.get("symbol") for r in rows])
        if not name_by_symbol:
            return rows
        return [{**row, "name": name_by_symbol.get(row.get("symbol"))} for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.debug("attach damiao names failed: %s", e)
        return rows


@router.get("")
def list_all(request: Request):
    return {"rows": _with_names(damiao_pool.list_rows(), request)}


@router.post("")
def add_one(req: AddRequest, request: Request):
    category = req.category if req.category in VALID_CATEGORIES else "new_watch"
    anchor = req.anchor_price
    if anchor is None:
        capset = getattr(request.app.state, "capabilities", None)
        anchor = damiao_pool.resolve_anchor_price(req.symbol, request.app.state.repo, capset)
    rows = damiao_pool.add(
        symbol=req.symbol,
        source_date=req.source_date,
        category=category,
        strategy=req.strategy,
        note=req.note,
        anchor_price=float(anchor) if anchor is not None else None,
    )
    return {"rows": _with_names(rows, request), "anchor_price": anchor}


@router.post("/batch-parse")
def batch_parse(req: BatchParseRequest, request: Request):
    """预览解析:把群主预案文本解析成候选股票列表(不落库)。"""
    from app.services import damiao_batch
    try:
        inst_df = request.app.state.repo.get_instruments()
        items = damiao_batch.parse_text(req.text or "", inst_df)
        return {"items": items, "count": len(items)}
    except Exception as e:  # noqa: BLE001
        logger.exception("batch parse failed: %s", e)
        return {"items": [], "count": 0, "error": str(e)}


@router.post("/batch-add")
def batch_add(req: BatchAddRequest, request: Request):
    """确认批量入库:按用户确认后的 items 逐条 add,自动取锚定价。"""
    capset = getattr(request.app.state, "capabilities", None)
    repo = request.app.state.repo
    added: list[dict] = []
    for item in req.items:
        category = item.category if item.category in VALID_CATEGORIES else "new_watch"
        anchor = damiao_pool.resolve_anchor_price(item.symbol, repo, capset)
        damiao_pool.add(
            symbol=item.symbol,
            source_date=req.source_date,
            category=category,
            note=item.note,
            anchor_price=float(anchor) if anchor is not None else None,
        )
        added.append({"symbol": item.symbol, "category": category, "anchor_price": anchor})
    rows = _with_names(damiao_pool.list_rows(), request)
    return {"rows": rows, "added": added, "count": len(added)}


@router.patch("/{row_id}")
def update_one(row_id: str, req: UpdateRequest, request: Request):
    fields = req.model_dump(exclude_none=True)
    if "category" in fields and fields["category"] not in VALID_CATEGORIES:
        fields.pop("category")
    rows = damiao_pool.update(row_id, **fields)
    return {"rows": _with_names(rows, request)}


@router.post("/{row_id}/exit")
def mark_exit(row_id: str, req: ExitRequest, request: Request):
    category = req.category if req.category in EXIT_CATEGORIES else "closed"
    rows = damiao_pool.mark_exit(row_id, category=category, exit_price=req.exit_price)
    return {"rows": _with_names(rows, request)}


@router.delete("/{row_id}")
def remove_one(row_id: str, request: Request):
    rows = damiao_pool.remove(row_id)
    return {"rows": _with_names(rows, request)}


@router.delete("")
def clear_all():
    removed = damiao_pool.clear()
    return {"removed": removed}


# 票池自身字段(拼回 enriched 行)
_POOL_FIELDS = [
    "id", "symbol", "added_at", "source_date", "category",
    "strategy", "anchor_price", "exit_price", "note",
]


@router.get("/enriched")
def pool_enriched(
    request: Request,
    ext_columns: str | None = Query(None, description="逗号分隔的 ext 列: config_id.field_name"),
):
    """票池 enriched 数据 — 以票池记录为主表 LEFT JOIN enriched 最新日缓存。

    与 watchlist enriched 的关键差异:主表以「推荐事件」为单位(含 id),
    同 symbol 可有多行,LEFT JOIN 后各自独立得到当前行情。
    """
    t0 = time.perf_counter()

    repo = request.app.state.repo
    records = damiao_pool.list_rows()
    if not records:
        return {"rows": [], "as_of": None, "elapsed_ms": 0}

    pool_df = pl.DataFrame(records)
    symbols = pool_df["symbol"].to_list()

    etf_set = repo.get_etf_symbol_set()
    # 取行情:股票/ETF 各查一次,构建 symbol->quote 字典,再按 records 顺序拼回
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
    # 按 records 顺序展开;缺失行情的行用空 dict(后续列为 null),保证每行一条记录
    quote_rows = [quote_map.get(s, {}) for s in symbols]
    q = pl.DataFrame(quote_rows, infer_schema_length=None)

    # 若行情 DataFrame 缺 symbol 列(全部未命中),补上 symbol 保证后续 JOIN
    if "symbol" not in q.columns:
        q = q.with_columns(pl.Series("symbol", symbols))

    # JOIN 名称 + float_shares
    df_i = repo.get_instruments()
    if not df_i.is_empty() and "float_shares" in df_i.columns:
        q = q.join(df_i.select(["symbol", "float_shares"]), on="symbol", how="left")
    name_map = repo.get_name_map(symbols)
    q = q.with_columns(
        pl.col("symbol").replace_strict(name_map, default=None, return_dtype=pl.Utf8).alias("name")
    )

    keep = [c for c in _WATCHLIST_COLS + ["name", "float_shares"] if c in q.columns]
    q = q.select(keep)

    # 把票池自身字段拼回(按行序对齐:q 的行序即 records 顺序)
    for f in _POOL_FIELDS:
        if f == "symbol":
            continue
        q = q.with_columns(pl.Series(f, [r.get(f) for r in records]))

    # 动态 ext JOIN (与 watchlist 一致)
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
                logger.debug("damiao ext join failed for %s.%s: %s", config_id, field_name, e)

    # sanitize NaN / Inf
    float_cols = [c for c in q.columns if q[c].dtype.is_float()]
    if float_cols:
        q = q.with_columns([
            pl.when(pl.col(c).is_nan() | pl.col(c).is_infinite())
              .then(None).otherwise(pl.col(c)).alias(c)
            for c in float_cols
        ])

    has_stock = any(s not in etf_set for s in symbols)
    has_etf = any(s in etf_set for s in symbols)
    dates = [
        d for d, present in ((cache_date, has_stock), (etf_date, has_etf))
        if present and d is not None
    ]
    as_of = min(dates) if dates else None
    rows = q.to_dicts()
    elapsed = (time.perf_counter() - t0) * 1000
    return {"rows": rows, "as_of": str(as_of) if as_of else None, "elapsed_ms": elapsed}
