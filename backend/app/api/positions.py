"""持仓 API。"""
from __future__ import annotations

import json
import logging
import time
from typing import Literal

import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.watchlist import _WATCHLIST_COLS
from app.services import positions
from app.services import position_log

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


class AnalyzeRequest(BaseModel):
    """AI 持仓复盘请求。"""
    focus: str = ""
    skill_id: str | None = None
    skill_params: dict | None = None


class SaveReportRequest(BaseModel):
    """保存一条 AI 持仓复盘报告。"""
    as_of: str
    focus: str = ""
    content: str
    summary: dict | None = None
    count: int = 0


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


# ---------------------------------------------------------------------------
# 操作日志（事件溯源）— 阶段 1
# ---------------------------------------------------------------------------

class AddLogRequest(BaseModel):
    op_type: Literal["buy", "sell", "clear"]
    symbol: str
    price: float | None = None
    volume: float | None = None
    op_date: str | None = None
    name: str = ""
    commission: float = 0
    stamp_duty: float = 0
    transfer_fee: float = 0
    note: str = ""


class CashRequest(BaseModel):
    free_cash: float = Field(..., ge=0)


@router.get("/logs")
def list_logs(symbol: str | None = Query(None)):
    """操作日志列表，按 (op_date, id) 升序。"""
    return {"logs": position_log.list_logs(symbol)}


@router.post("/logs")
def add_log(req: AddLogRequest):
    """写入一笔买入/卖出/清仓操作，联动可用资金。

    返回交易后的当前持仓与现金。业务校验失败返回 400。
    """
    try:
        result = position_log.add_trade(
            op_type=req.op_type,
            symbol=req.symbol,
            price=req.price,
            volume=req.volume,
            op_date=req.op_date,
            name=req.name,
            commission=req.commission,
            stamp_duty=req.stamp_duty,
            transfer_fee=req.transfer_fee,
            note=req.note,
            source="manual",
        )
    except position_log.TradeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "log": result.log,
        "rows": result.positions,
        "free_cash": result.free_cash,
    }


@router.delete("/logs/{log_id}")
def delete_log(log_id: int):
    ok = position_log.delete_log(log_id)
    if not ok:
        raise HTTPException(status_code=404, detail="日志不存在")
    return {
        "ok": True,
        "rows": [
            {
                "symbol": p.symbol, "name": p.name, "shares": p.shares,
                "cost_price": p.cost_price, "opened_at": p.opened_at,
                "note": p.note, "added_at": p.added_at,
            }
            for p in position_log.compute_positions()
        ],
    }


@router.get("/cash")
def get_cash():
    return {"free_cash": position_log.get_free_cash()}


@router.put("/cash")
def set_cash(req: CashRequest):
    return {"free_cash": position_log.set_free_cash(req.free_cash)}


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


@router.post("/analyze")
async def analyze_positions(request: Request, req: AnalyzeRequest):
    """AI 持仓复盘 — NDJSON 流式返回。

    装配当前全部持仓 + enriched 行情 + 每只近 K 线关键价位 → 组合复盘提示词 →
    流式调用 LLM。流结束后自动归档一份报告(历史最多 30 条)。协议:
      {"type":"meta","count","summary"}
      {"type":"delta","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    from app.services.position_analyzer import analyze_positions_stream

    # skill_id 预校验:不存在/类别不匹配直接 400,不静默 fallback
    if req.skill_id:
        from app.ai_skills import registry
        try:
            skill = registry.get_skill(req.skill_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if skill.meta.get("category") != "holdings":
            raise HTTPException(
                400,
                f"Skill {req.skill_id}(类别 {skill.meta.get('category')}) "
                f"不适用于持仓分析,期望 category=holdings",
            )

    repo = request.app.state.repo
    quote_service = getattr(request.app.state, "quote_service", None)
    pos_rows = positions.list_rows()

    async def stream_gen():
        from app.services import position_reports

        meta: dict = {}
        content_parts: list[str] = []
        async for chunk in analyze_positions_stream(
            repo, quote_service, pos_rows, req.focus,
            skill_id=req.skill_id,
            skill_params=req.skill_params,
        ):
            # 解析出 meta 与正文,用于流结束后归档
            try:
                evt = json.loads(chunk)
                if evt.get("type") == "meta":
                    meta = evt
                elif evt.get("type") == "delta":
                    content_parts.append(evt.get("content", ""))
            except Exception:  # noqa: BLE001
                pass
            yield chunk + "\n"

        # 自动归档(仅当有正文且正常结束)
        content = "".join(content_parts).strip()
        if content:
            try:
                summary = meta.get("summary") or {}
                position_reports.save_report({
                    "as_of": meta.get("as_of") or "",
                    "focus": req.focus or "",
                    "content": content,
                    "summary": summary,
                    "count": meta.get("count") or summary.get("count") or len(pos_rows),
                    "skill_id": meta.get("skill_id"),
                    "skill_name": meta.get("skill_name"),
                    "skill_params": meta.get("skill_params") or {},
                    "model": meta.get("model"),
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("auto-save position report failed: %s", e)

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reports")
def list_position_reports():
    """获取全部历史持仓复盘报告(按时间降序,后端已裁剪到上限)。"""
    from app.services import position_reports
    return {"reports": position_reports.list_reports()}


@router.post("/reports")
def save_position_report(req: SaveReportRequest):
    """手动保存一条持仓复盘报告(一般由流结束自动归档,此端点供重试/编辑场景)。"""
    from app.services import position_reports
    report = position_reports.save_report({
        "as_of": req.as_of,
        "focus": req.focus,
        "content": req.content,
        "summary": req.summary or {},
        "count": req.count,
    })
    return {"ok": True, "report": report}


@router.delete("/reports/{report_id}")
def delete_position_report(report_id: str):
    """删除一条持仓复盘报告。"""
    from app.services import position_reports
    ok = position_reports.delete_report(report_id)
    return {"ok": ok}
