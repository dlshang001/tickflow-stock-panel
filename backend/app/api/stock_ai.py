"""个股 AI 技术分析流式接口。

与 /api/rps/rotation-analyze 的 NDJSON 协议完全对齐:
  {"type":"meta","symbol","summary"}
  {"type":"delta","content":"..."}
  {"type":"error","message":"..."}
  {"type":"done"}

前端可复用同一套流式渲染组件。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.stock_ai_analyzer import analyze_stock_ai_stream

router = APIRouter(prefix="/api/stock-ai-analyze", tags=["stock-ai"])


class StockAiAnalyzeRequest(BaseModel):
    """个股 AI 技术分析请求。"""
    symbol: str = Field(..., description="标的代码,如 300666.SZ")
    focus: str = Field("", description="可选:用户追加的分析关注点")


@router.post("")
async def stock_ai_analyze(request: Request, req: StockAiAnalyzeRequest):
    """AI 个股技术分析(含板块联动) — NDJSON 流式返回。

    装配个股技术指标 + 行业/概念板块数据 → 客观技术分析提示词 →
    流式调用 LLM → 逐 chunk 以 NDJSON 推给前端(每行一个 JSON)。
    """
    if not req.symbol:
        raise ValueError("symbol 不能为空")

    repo = request.app.state.repo

    async def stream_gen():
        async for chunk in analyze_stock_ai_stream(repo, req.symbol, req.focus):
            yield chunk + "\n"

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
