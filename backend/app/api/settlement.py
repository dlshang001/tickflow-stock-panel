"""交割单导入 / 查询 / 统计 API。"""
from __future__ import annotations

import json
import logging
import time

import anyio
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import reconcile, settlement, settlement_parser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settlement", tags=["settlement"])

_MAX_BYTES = 30 * 1024 * 1024  # 30MB


@router.post("/import")
async def import_settlement(
    file: UploadFile = File(...),
    dry_run: bool = Query(True, description="true=仅解析预览不落库; false=确认导入"),
):
    """上传交割单 Excel/CSV。

    - dry_run=true：解析 + 内存去重，返回预览（parse_errors / filtered_stats / new_count）。
    - dry_run=false：解析 + 去重落库 + 幂等同步到 position_log。
    """
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "仅支持 .xlsx / .xls / .csv 文件")

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > _MAX_BYTES:
        raise HTTPException(400, "文件过大（上限 30MB）")

    try:
        parsed = await anyio.to_thread.run_sync(
            lambda: settlement_parser.parse_settlement(data, file.filename or "settlement"),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("settlement parse failed")
        raise HTTPException(500, f"解析失败: {e}") from e

    records = parsed["records"]

    if dry_run:
        preview = settlement.preview_import(records)
        return {
            "dry_run": True,
            "format": parsed["format"],
            "total_rows": parsed["total_rows"],
            "parse_errors": parsed["parse_errors"],
            "filtered_stats": parsed["filtered_stats"],
            **preview,
        }

    # 提交导入
    try:
        result = await anyio.to_thread.run_sync(
            lambda: settlement.commit_import(records),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("settlement commit failed")
        raise HTTPException(500, f"导入失败: {e}") from e

    return {
        "dry_run": False,
        "format": parsed["format"],
        "total_rows": parsed["total_rows"],
        "parse_errors": parsed["parse_errors"],
        "filtered_stats": parsed["filtered_stats"],
        **result,
    }


@router.get("/records")
def records(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=1000),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    symbol: str | None = Query(None),
):
    """交割单明细分页查询。"""
    return settlement.list_records(
        date_from=date_from, date_to=date_to, symbol=symbol, page=page, size=size,
    )


@router.delete("/records")
def clear_records(batch_id: str | None = Query(None)):
    """清空全部交割单（默认），或删除指定批次。级联清理 source=settlement 的操作日志。"""
    if batch_id:
        removed = settlement.delete_by_batch(batch_id)
        return {"removed": removed}
    return {"removed": settlement.clear_all()}


@router.get("/stats")
def stats():
    """交割单聚合统计（阶段 4 扩展为图表时序）。"""
    return settlement.compute_stats()


class ReconFixRequest(BaseModel):
    symbol: str
    action: str = "fix"   # fix | delete


@router.get("/reconcile")
def get_reconcile():
    """对账：比较交割单推导持仓与操作日志推导持仓。"""
    items = reconcile.reconcile()
    summary = {
        "total": len(items),
        "matched": sum(1 for i in items if i["diff_type"] == "matched"),
        "mismatch": sum(1 for i in items if i["diff_type"] == "mismatch"),
        "only_settlement": sum(1 for i in items if i["diff_type"] == "only_settlement"),
        "only_position_log": sum(1 for i in items if i["diff_type"] == "only_position_log"),
    }
    return {"items": items, "summary": summary}


@router.post("/reconcile/fix")
def fix_reconcile(req: ReconFixRequest):
    """修正对账差异（fix 按交割单对齐；delete 删除该标的全部日志）。"""
    try:
        result = reconcile.fix_item(req.symbol, req.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 返回修正后的对账结果
    items = reconcile.reconcile()
    return {**result, "items": items}


class AnalyzeRequest(BaseModel):
    focus: str = ""
    skill_id: str | None = None
    skill_params: dict | None = None


@router.post("/analyze")
async def analyze_settlement(request: Request, req: AnalyzeRequest):
    """AI 交割单分析 — 威科夫交易行为分析 Skill，NDJSON 流式返回。

    与持仓复盘完全独立的分析 Skill，使用专属 System Prompt 和数据组装逻辑。
    专注于：交易风格评估、买卖时机质量、盈亏回顾、费用效率、月度节奏、对账异常。
    流结束后自动归档报告。
    协议:
      {"type":"meta","summary"}
      {"type":"delta","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    from app.services.settlement_analyzer import analyze_settlement_stream

    # skill_id 预校验:不存在/类别不匹配直接 400,不静默 fallback
    if req.skill_id:
        from app.ai_skills import registry
        try:
            skill = registry.get_skill(req.skill_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if skill.meta.get("category") != "settlement":
            raise HTTPException(
                400,
                f"Skill {req.skill_id}(类别 {skill.meta.get('category')}) "
                f"不适用于交割单分析,期望 category=settlement",
            )

    async def stream_gen():
        from app.services import settlement_reports

        meta: dict = {}
        content_parts: list[str] = []
        async for chunk in analyze_settlement_stream(
            req.focus,
            skill_id=req.skill_id,
            skill_params=req.skill_params,
        ):
            try:
                evt = json.loads(chunk)
                if evt.get("type") == "meta":
                    meta = evt
                elif evt.get("type") == "delta":
                    content_parts.append(evt.get("content", ""))
            except Exception:  # noqa: BLE001
                pass
            yield chunk + "\n"

        content = "".join(content_parts).strip()
        if content:
            try:
                settlement_reports.save_report({
                    "as_of": meta.get("as_of") or "",
                    "focus": req.focus or "",
                    "content": content,
                    "summary": meta.get("summary") or {},
                    "count": meta.get("summary", {}).get("records_count", 0),
                    "skill_id": meta.get("skill_id"),
                    "skill_name": meta.get("skill_name"),
                    "skill_params": meta.get("skill_params") or {},
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("auto-save settlement report failed: %s", e)

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reports")
def list_settlement_reports():
    """获取全部历史交割单分析报告(按时间降序,后端已裁剪到上限)。"""
    from app.services import settlement_reports
    return {"reports": settlement_reports.list_reports()}


@router.delete("/reports/{report_id}")
def delete_settlement_report(report_id: str):
    """删除一条交割单分析报告。"""
    from app.services import settlement_reports
    ok = settlement_reports.delete_report(report_id)
    return {"ok": ok}
