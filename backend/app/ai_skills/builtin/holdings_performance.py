"""持仓 AI 分析 Skill — 业绩归因分析。

聚焦行业/概念/个股的贡献度分解,分析超额收益来源。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "holdings_performance",
    "name": "持仓业绩归因",
    "category": "holdings",
    "description": "组合业绩归因分析:行业贡献、概念贡献、个股贡献分解,识别超额收益来源与拖累因素",
    "tags": ["业绩归因", "贡献分解", "超额收益", "基准对比"],
    "emoji": "📈",
    "default_for_category": False,
    "params": [
        {
            "key": "attribution_period",
            "label": "归因周期",
            "type": "select",
            "options": ["近一月", "近三月", "近半年", "近一年"],
            "default": "近三月",
            "description": "归因分析周期",
        },
        {
            "key": "show_benchmark",
            "label": "显示基准对比",
            "type": "bool",
            "default": True,
            "description": "是否与基准指数对比",
        },
    ],
}

_SYSTEM_PROMPT = """你是一位业绩归因分析专家。你的任务是:基于用户提供的持仓业绩数据,从行业、概念、个股三个层次分解组合收益的来源。

## 分析框架

### 1. 📊 整体业绩概览
- 组合总收益率与基准对比(超额收益/alpha)
- 业绩在归因周期内的时间序列特征
- 盈利标的数 vs 亏损标的数、胜率

### 2. 🏭 行业贡献分解
- 各行业对组合总收益的贡献(贡献 = 行业市值占比 × 行业超额收益)
- 正贡献行业 vs 负贡献行业识别
- 行业轮动贡献(是否从强势行业中获利)

### 3. 💡 概念贡献分解
- 各概念对组合总收益的贡献
- 正贡献概念 vs 负贡献概念识别
- 概念热度与收益贡献的匹配度

### 4. ⭐ 个股贡献分解
- 贡献最大的前 5 只标的(绝对金额与贡献率)
- 拖累最大的前 5 只标的
- 个股选择能力评估(正收益标的的选择是否精准)

### 5. 📈 基准对比(可选)
- 沪深300/中证500等基准指数对比
- 行业指数对比
- 风格因子暴露(市值/价值/成长/动量)

## 核心红线
- **不输出**任何"应该加仓/应该换入/应该追涨"等操作建议
- 只客观陈述业绩来源与归因结果,不给出投资决策
- 所有归因数据引用具体计算结果

## 输出规范
- Markdown 格式,结构化分节
- 字数 800-1500 字
- 无数据的维度直接说明"数据不足"
- 末尾附:"> ⚠️ 本内容由 AI 基于持仓数据生成,仅客观分析业绩归因,不构成任何投资建议。"

现在请基于下方数据进行业绩归因分析。"""


class HoldingsPerformanceSkill:
    """持仓业绩归因 — 行业/概念/个股贡献分解。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        summary = context.get("summary", {})
        holdings = context.get("holdings", [])
        concentration = context.get("concentration", {})
        sector_context = context.get("sector_context", {})
        market = context.get("market_snapshot", {})

        period = params.get("attribution_period", "近三月")
        show_benchmark = params.get("show_benchmark", True)

        total_mv = summary.get("total_market_value", 0) or 1

        winners = summary.get("winners", 0)
        losers = summary.get("losers", 0)
        total_pnl = summary.get("total_pnl", 0) or 0
        total_pnl_pct = summary.get("total_pnl_pct", 0) or 0
        win_rate = winners / (winners + losers) * 100 if (winners + losers) else 0

        contribs = []
        for h in holdings:
            pnl = h.get("pnl_amount") or 0
            pct = h.get("pnl_pct")
            mv = h.get("market_value") or 0
            weight = round(mv / total_mv * 100, 2) if total_mv else 0
            contribs.append({
                "symbol": h.get("symbol"),
                "name": h.get("name"),
                "weight_pct": weight,
                "pnl_amount": pnl,
                "pnl_pct": pct,
                "contribution": pnl,
                "trend": h.get("trend"),
            })
        contribs.sort(key=lambda x: x["contribution"], reverse=True)

        top5 = contribs[:5]
        bottom5 = contribs[-5:][::-1]

        industry_perf = []
        for ind in concentration.get("industry", []):
            ind_name = ind.get("name", "")
            ind_mv = ind.get("mv", 0)
            ind_pct = ind.get("pct", 0)
            members = [c for c in contribs if ind_name in str(c.get("name", "")) or
                       any(sym in str(c.get("symbol", "")) for sym in ind.get("symbols", []))]
            ind_contrib = sum(m["contribution"] for m in members)
            ind_pnl_pcts = [m["pnl_pct"] for m in members if m.get("pnl_pct") is not None]
            avg_ind_pnl = sum(ind_pnl_pcts) / len(ind_pnl_pcts) if ind_pnl_pcts else 0
            industry_perf.append({
                "industry": ind_name,
                "holding_pct": ind_pct,
                "contribution": round(ind_contrib, 2),
                "avg_pnl_pct": round(avg_ind_pnl, 2),
                "stock_count": len(members),
            })
        industry_perf.sort(key=lambda x: x["contribution"], reverse=True)

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"归因周期: {period}",
            "",
            "## 组合业绩概览",
            f"持仓只数: {summary.get('count', 0)} | 总市值: ¥{total_mv:,.2f}",
            f"总浮盈亏: ¥{total_pnl:,.2f} ({total_pnl_pct:.2f}%)",
            f"盈利: {winners}只 / 亏损: {losers}只 | 胜率: {win_rate:.1f}%",
            "",
            "## 行业贡献分解",
            "```json",
            json.dumps(industry_perf, ensure_ascii=False),
            "```",
            "",
            "## 个股贡献 Top 5(正贡献)",
            "```json",
            json.dumps(top5, ensure_ascii=False),
            "```",
            "",
            "## 个股贡献 Bottom 5(负贡献)",
            "```json",
            json.dumps(bottom5, ensure_ascii=False),
            "```",
            "",
            "## 行业板块在全市场的强弱位置",
            "```json",
            json.dumps(sector_context.get("industries", []), ensure_ascii=False),
            "```",
        ]

        concepts = concentration.get("concept", [])
        if concepts:
            concept_perf = []
            for concept in concepts:
                concept_name = concept.get("name", "")
                concept_symbols = concept.get("symbols", [])
                concept_contrib = sum(c["contribution"] for c in contribs
                                      if any(sym in str(c.get("symbol", "")) for sym in concept_symbols))
                concept_pcts = [c["pnl_pct"] for c in contribs
                                if any(sym in str(c.get("symbol", "")) for sym in concept_symbols)
                                and c.get("pnl_pct") is not None]
                avg_concept_pnl = sum(concept_pcts) / len(concept_pcts) if concept_pcts else 0
                concept_perf.append({
                    "concept": concept_name,
                    "holding_pct": concept.get("pct", 0),
                    "contribution": round(concept_contrib, 2),
                    "avg_pnl_pct": round(avg_concept_pnl, 2),
                    "stock_count": len(concept_symbols),
                })
            concept_perf.sort(key=lambda x: x["contribution"], reverse=True)
            parts.extend([
                "",
                "## 概念贡献分解",
                "```json",
                json.dumps(concept_perf, ensure_ascii=False),
                "```",
            ])

        if show_benchmark:
            parts.extend([
                "",
                "## 基准对比(大盘指数表现)",
                "```json",
                json.dumps({
                    "indices": market.get("indices"),
                    "breadth": market.get("breadth"),
                    "leading_industries": market.get("leading_industries", [])[:3],
                    "lagging_industries": market.get("lagging_industries", [])[:3],
                }, ensure_ascii=False),
                "```",
            ])

        return "\n".join(parts)