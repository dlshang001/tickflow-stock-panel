"""AI 持仓复盘服务 — 账户组合视角的客观复盘。

职责:
  组合当前全部持仓(成本/股数/建仓日)+ 每只标的的最新行情指标 +
  近期日 K 趋势 + 大盘环境 → 拼装组合复盘系统提示词 → 流式调用 LLM。

设计要点:
  - 与 stock_analyzer(单只四维深度分析) 区分:本服务是"账户组合视角",
    逐只只给压缩摘要(不把 N 只 × 90 根 K 线全塞进去,控制 token)。
  - 红线与现有 AI 分析一致:客观陈述,不输出任何买卖/仓位/止损止盈建议。
  - 行业/概念集中度取数成本高,v1 以盈亏分布 + 涨跌结构 + 技术状态聚合替代。

不知道: HTTP、前端、配置持久化。
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from typing import AsyncIterator

import polars as pl

from app.indicators.levels import compute_levels

logger = logging.getLogger(__name__)

# 每只持仓注入最近多少根日 K(仅用于趋势/价位,组合复盘比单只分析更精简)
_KLINE_WINDOW = 30


# ================================================================
# 数据装配
# ================================================================

def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _holding_days(opened_at: str | None) -> int | None:
    if not opened_at:
        return None
    try:
        d = date.fromisoformat(opened_at[:10])
        return (date.today() - d).days
    except (ValueError, TypeError):
        return None


def _trend_tag(df: pl.DataFrame) -> str:
    """从近 N 根 K 线提炼一句客观趋势标签。"""
    if df.is_empty() or "close" not in df.columns or df.height < 5:
        return "数据不足"
    close = df["close"].to_list()
    last = _safe_float(close[-1])
    ma5 = _safe_float(df["ma5"][-1]) if "ma5" in df.columns and df.height >= 5 else None
    ma20 = _safe_float(df["ma20"][-1]) if "ma20" in df.columns and df.height >= 20 else None
    if last is None:
        return "数据不足"
    tags = []
    if ma5 and ma20:
        if last > ma5 > ma20:
            tags.append("均线多头")
        elif last < ma5 < ma20:
            tags.append("均线空头")
        elif last > ma20:
            tags.append("站上MA20")
        else:
            tags.append("跌破MA20")
    # 近 5 日涨跌幅
    prev = _safe_float(close[-6]) if len(close) >= 6 else None
    if prev:
        chg5 = (last - prev) / prev * 100
        tags.append(f"近5日{chg5:+.1f}%")
    return "，".join(tags) if tags else "震荡"


def _summarize_holding(repo, pos: dict, enriched_map: dict) -> dict | None:
    """把一只持仓压缩成一个摘要 dict(用于注入 prompt,控制 token)。"""
    symbol = pos.get("symbol")
    if not symbol:
        return None

    shares = _safe_float(pos.get("shares")) or 0.0
    cost = _safe_float(pos.get("cost_price"))
    enr = enriched_map.get(symbol) or {}
    last = _safe_float(enr.get("close"))

    # 持仓自身数值
    market_value = (last * shares) if last is not None else None
    cost_value = (cost * shares) if cost is not None else None
    pnl_amt = ((last - cost) * shares) if (last is not None and cost is not None) else None
    pnl_pct = ((last - cost) / cost) if (last is not None and cost) else None
    day_pct = _safe_float(enr.get("change_pct"))
    days = _holding_days(pos.get("opened_at"))

    # 趋势 + 关键价位(从近 K 线算,失败则降级只用 enriched)
    asset_type = repo.resolve_asset_type(symbol)
    trend = "数据不足"
    nearest_support = None
    nearest_resistance = None
    try:
        start = date.today()
        from datetime import timedelta
        df = repo.get_daily_asset(asset_type, symbol, start - timedelta(days=_KLINE_WINDOW * 2), start)
        if not df.is_empty():
            df = df.tail(_KLINE_WINDOW)
            trend = _trend_tag(df)
            levels = compute_levels(df)
            # 从 levels 里挑离现价最近的支撑/压力
            if last is not None:
                supports, resistances = [], []
                for group in levels.values():
                    if not isinstance(group, list):
                        continue
                    for item in group:
                        price = item.get("price") if isinstance(item, dict) else None
                        if price is None:
                            continue
                        if price < last:
                            supports.append(price)
                        elif price > last:
                            resistances.append(price)
                nearest_support = max(supports) if supports else None
                nearest_resistance = min(resistances) if resistances else None
    except Exception as e:  # noqa: BLE001
        logger.debug("position analyze kline/levels failed for %s: %s", symbol, e)

    return {
        "symbol": symbol,
        "name": enr.get("name"),
        "shares": shares,
        "cost_price": cost,
        "last_price": last,
        "market_value": round(market_value, 2) if market_value is not None else None,
        "pnl_amount": round(pnl_amt, 2) if pnl_amt is not None else None,
        "pnl_pct": round(pnl_pct * 100, 2) if pnl_pct is not None else None,
        "day_change_pct": round(day_pct, 2) if day_pct is not None else None,
        "holding_days": days,
        "trend": trend,
        "rsi14": _safe_float(enr.get("rsi_14")),
        "vol_ratio": _safe_float(enr.get("vol_ratio_5d")),
        "ma5": _safe_float(enr.get("ma5")),
        "ma20": _safe_float(enr.get("ma20")),
        "nearest_support": round(nearest_support, 2) if nearest_support else None,
        "nearest_resistance": round(nearest_resistance, 2) if nearest_resistance else None,
        "consecutive_limit_ups": enr.get("consecutive_limit_ups"),
        "note": pos.get("note") or "",
    }


def _build_market_snapshot(quote_service) -> dict:
    """轻量大盘快照:主要指数 + 涨跌家数。失败则返回空,不阻断复盘。"""
    snap: dict = {"indices": [], "breadth": None}
    try:
        if quote_service is not None:
            idx = quote_service.get_index_quotes()
            rows = idx if isinstance(idx, list) else idx.get("rows", []) if isinstance(idx, dict) else []
            for r in rows[:6]:
                snap["indices"].append({
                    "name": r.get("name"),
                    "change_pct": _safe_float(r.get("change_pct")),
                })
    except Exception as e:  # noqa: BLE001
        logger.debug("position analyze market snapshot failed: %s", e)
    return snap


def _build_portfolio_summary(holdings: list[dict]) -> dict:
    """账户级聚合:总市值/总成本/总盈亏/盈亏分布。"""
    total_mv = sum(h["market_value"] for h in holdings if h.get("market_value"))
    total_cost = sum((h.get("cost_price") or 0) * h.get("shares", 0) for h in holdings)
    total_pnl = sum(h["pnl_amount"] for h in holdings if h.get("pnl_amount") is not None)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None

    winners = [h for h in holdings if (h.get("pnl_pct") or 0) > 0]
    losers = [h for h in holdings if (h.get("pnl_pct") or 0) < 0]
    day_up = [h for h in holdings if (h.get("day_change_pct") or 0) > 0]
    day_down = [h for h in holdings if (h.get("day_change_pct") or 0) < 0]

    top = sorted(holdings, key=lambda h: h.get("pnl_amount") or 0, reverse=True)
    return {
        "count": len(holdings),
        "total_market_value": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2) if total_pnl_pct is not None else None,
        "winners": len(winners),
        "losers": len(losers),
        "day_up": len(day_up),
        "day_down": len(day_down),
        "top_contributors": [
            {"symbol": h["symbol"], "name": h.get("name"), "pnl_amount": h["pnl_amount"], "pnl_pct": h["pnl_pct"]}
            for h in top[:3]
        ],
        "bottom_contributors": [
            {"symbol": h["symbol"], "name": h.get("name"), "pnl_amount": h["pnl_amount"], "pnl_pct": h["pnl_pct"]}
            for h in top[-3:][::-1]
        ],
    }


# ================================================================
# 系统提示词 —— 账户组合客观复盘框架
# 红线:只做客观状态陈述,不输出任何买卖/仓位/止损止盈建议。
# ================================================================

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股研究经验的组合复盘分析师。你的任务是:基于用户提供的**当前持仓数据**与**大盘环境**,产出一份客观、中立、不包含任何买卖或操作建议的账户持仓复盘报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/调仓/换仓/止损/止盈/清仓/观望/建议持有/目标价"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**账户的盈亏结构、板块/风格暴露、每只持仓的技术状态与潜在风险,让读者自行判断
- 只描述"现在是什么状态",不描述"应该怎么做"

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构,不要输出 JSON 或代码块。

### 1. 📊 账户概览(2-4 句)
基于提供的账户汇总数据,客观描述:总市值、总浮盈亏(额与比例)、今日涨跌只数对比、盈利/亏损只数、整体仓位的盈亏分布。数据说话,不评价操作好坏。

### 2. 🌡️ 大盘环境与持仓对照(2-3 句)
基于提供的主要指数涨跌,客观描述今日大盘环境,并客观陈述持仓整体是强于还是弱于大盘(用今日上涨只数占比与指数对比)。不臆测后市。

### 3. 📈 持仓逐只状态
对每一只持仓,用 1-2 句客观描述其:浮动盈亏(额/比例)、持仓天数、趋势标签、距当前价最近的支撑/压力位、RSI/量能等指标状态。
- 用**简洁的 Markdown 表格**呈现(列:代码、名称、浮盈亏、今日、趋势、技术状态)
- 表格之后,对浮盈亏较大或技术状态值得注意的标的用 2-4 句客观补充
- 每条只陈述事实,不写操作建议

### 4. ⚠️ 风险点与结构观察
客观列出(不超过 5 条):
- 盈亏分布是否分化(单只贡献过大/拖后腿)
- 哪些标的跌破关键均线或距支撑位较近
- 哪些标的 RSI 超买/超卖或量能异常
- 持仓只数集中度(是否过度集中于少数标的)
只做客观提示,不下"应该减仓"等结论。

### 5. 🔍 值得关注的客观信号
列出后续可观察的客观量价信号(如某均线得失、某压力位能否放量突破、量能变化),**不附任何操作结论**。

## 准则

1. 数据说话:每个判断引用具体数值,严禁空泛套话
2. 客观中立:只陈述状态与风险,不输出任何交易指令
3. 简明有密度:总字数 800-1500 字,便于扫读
4. 无数据的维度直接说明"数据不足",不要编造

## 免责声明
报告末尾附一行:"> ⚠️ 本内容由 AI 基于公开行情数据生成,仅客观陈述持仓状态,不构成任何投资建议或买卖指令。交易有风险,入市需谨慎。"

现在请基于下方数据进行复盘。"""


def _build_user_prompt(summary: dict, holdings: list[dict], market: dict, focus: str) -> str:
    parts: list[str] = [
        f"复盘日期: {date.today().isoformat()}",
        "",
        "## 账户汇总",
        "```json",
        json.dumps(summary, ensure_ascii=False),
        "```",
        "",
        "## 持仓明细(每只已压缩为摘要,含成本/盈亏/趋势/关键价位/指标)",
        "```json",
        json.dumps(holdings, ensure_ascii=False),
        "```",
        "",
        "## 大盘环境",
        "```json",
        json.dumps(market, ensure_ascii=False),
        "```",
    ]
    from app.services.ai_provider import sanitize_focus
    safe_focus = sanitize_focus(focus)
    if safe_focus:
        parts.extend(["", f"本次复盘请特别关注: {safe_focus}"])
    return "\n".join(parts)


# ================================================================
# 流式入口
# ================================================================

async def analyze_positions_stream(
    repo,
    quote_service,
    positions_rows: list[dict],
    focus: str = "",
) -> AsyncIterator[str]:
    """流式持仓复盘:yield 出每个 NDJSON 事件。

    协议:
      {"type":"meta","count","summary"}   账户摘要
      {"type":"delta","content":"..."}    逐 chunk 文本
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    if not positions_rows:
        yield json.dumps({"type": "error", "message": "当前没有持仓,无法复盘"}, ensure_ascii=False)
        return

    # 1. 取 enriched 最新行情(股票 + ETF),构建 symbol -> quote 映射
    enriched_map: dict[str, dict] = {}
    try:
        etf_set = repo.get_etf_symbol_set()
        df_e, _ = repo.get_enriched_latest()
        df_etf, _ = repo.get_enriched_latest_asset("etf")
        for df in (df_e, df_etf):
            if df.is_empty() or "symbol" not in df.columns:
                continue
            for r in df.to_dicts():
                enriched_map[r["symbol"]] = r
        # 名称回填(enriched 可能没有 name)
        name_map = repo.get_name_map([p.get("symbol") for p in positions_rows])
        for sym, nm in name_map.items():
            enriched_map.setdefault(sym, {})["name"] = nm
        _ = etf_set  # 资产分流已由 get_enriched_latest_asset 覆盖
    except Exception as e:  # noqa: BLE001
        logger.exception("load enriched for position analyze failed: %s", e)
        yield json.dumps({"type": "error", "message": f"加载行情数据失败: {e}"}, ensure_ascii=False)
        return

    # 2. 逐只压缩摘要
    holdings: list[dict] = []
    for pos in positions_rows:
        h = _summarize_holding(repo, pos, enriched_map)
        if h:
            holdings.append(h)
    if not holdings:
        yield json.dumps({"type": "error", "message": "持仓数据无法解析"}, ensure_ascii=False)
        return

    summary = _build_portfolio_summary(holdings)
    market = _build_market_snapshot(quote_service)

    # 3. meta
    yield json.dumps({
        "type": "meta",
        "count": summary["count"],
        "summary": summary,
        "as_of": date.today().isoformat(),
    }, ensure_ascii=False)

    # 4. 流式 LLM
    try:
        from app.services.ai_provider import stream_ai_text

        user_prompt = _build_user_prompt(summary, holdings, market, focus)
        async for delta in stream_ai_text(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=4000,
        ):
            yield json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        logger.exception("AI position analyze failed: %s", e)
        yield json.dumps({"type": "error", "message": f"AI 复盘失败: {e}"}, ensure_ascii=False)
        return

    yield json.dumps({"type": "done"}, ensure_ascii=False)
