"""持仓 AI 分析 Skill — 再平衡建议。

聚焦持仓目标配置与当前状态的偏离度分析,提供客观的调仓方向参考。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "holdings_rebalancing",
    "name": "持仓再平衡分析",
    "category": "holdings",
    "description": "基于目标配置与当前持仓的偏离度分析,客观提示超配/低配维度,提供再平衡方向参考",
    "tags": ["再平衡", "资产配置", "偏离度", "调仓方向"],
    "emoji": "🔄",
    "default_for_category": False,
    "params": [
        {
            "key": "deviation_threshold_pct",
            "label": "偏离预警阈值(%)",
            "type": "float",
            "default": 5.0,
            "description": "偏离阈值(与目标仓位的偏离容忍度, %)",
            "min": 0,
            "max": 100,
        },
        {
            "key": "max_single_position_pct",
            "label": "单票上限(%)",
            "type": "float",
            "default": 40.0,
            "description": "单只持仓最大占比(超限提示, %)",
            "min": 0,
            "max": 100,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位组合再平衡分析专家。你的任务是:基于用户提供的当前持仓配置与目标配置的偏离度数据,客观提示需要关注的超配/低配维度。

## 分析框架

### 1. 📊 当前配置快照
- 各行业/概念/个股的市值占比
- 与目标配置的偏离度(超配/低配程度)
- 整体配置结构评估(集中 vs 分散)

### 2. 🎯 偏离度诊断
- 超过偏离阈值的行业/概念/个股
- 偏离方向(超配 = 当前 > 目标,低配 = 当前 < 目标)
- 偏离幅度与潜在影响评估

### 3. 🔄 再平衡方向参考
- 需要关注的超配维度(客观提示"某行业/概念占比 XX%,超过阈值 YY%")
- 需要关注的低配维度(客观提示"某行业/概念占比 XX%,低于阈值 YY%")
- 单票集中度预警(超过单票上限的标的)
- **仅提示方向,不给出具体买卖指令**

### 4. ⚠️ 再平衡风险提示
- 市场流动性评估(在当前市场环境下,调整成本可能较高)
- 板块轮动风险(当前超配板块是否处于弱势)
- 交易成本估算(基于偏离幅度的预期调仓成本)

## 核心红线
- **绝对不输出**"买入/卖出/加仓/减仓/换仓/止损/止盈"等任何交易指令
- **不指定**具体的操作标的或价格
- 只客观陈述偏离事实与潜在关注方向
- 所有分析引用具体数据,不做主观判断

## 输出规范
- Markdown 格式,结构化分节
- 字数 800-1500 字
- 无数据的维度直接说明"数据不足"
- 末尾附:"> ⚠️ 本内容由 AI 基于持仓数据生成,仅客观分析配置偏离度,不构成任何投资建议或买卖指令。"

现在请基于下方数据进行再平衡分析。"""


class HoldingsRebalancingSkill:
    """持仓再平衡分析 — 偏离度诊断与调仓方向提示。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        summary = context.get("summary", {})
        holdings = context.get("holdings", [])
        concentration = context.get("concentration", {})
        sector_context = context.get("sector_context", {})
        market = context.get("market_snapshot", {})

        threshold = params.get("deviation_threshold_pct", 5.0)
        max_single = params.get("max_single_position_pct", 40.0)

        total_mv = summary.get("total_market_value", 0) or 1

        positions = []
        for h in holdings:
            mv = h.get("market_value") or 0
            pct = round(mv / total_mv * 100, 2) if total_mv else 0
            over_limit = pct > max_single
            positions.append({
                "symbol": h.get("symbol"),
                "name": h.get("name"),
                "market_value": mv,
                "pct_of_total": pct,
                "pnl_pct": h.get("pnl_pct"),
                "day_change_pct": h.get("day_change_pct"),
                "over_single_limit": over_limit,
                "distance_to_limit": round(max_single - pct, 2),
            })
        positions.sort(key=lambda x: x["pct_of_total"], reverse=True)

        over_limit_positions = [p for p in positions if p["over_single_limit"]]
        near_limit_positions = [p for p in positions if not p["over_single_limit"] and p["distance_to_limit"] < 5]

        industry_deviation = []
        for ind in concentration.get("industry", []):
            ind_pct = ind.get("pct", 0)
            deviation_from_mid = abs(ind_pct - 100 / max(len(concentration.get("industry", [])), 1))
            flag = "超配关注" if ind_pct > (100 / max(len(concentration.get("industry", [])), 1) + threshold) else ""
            if not flag and ind_pct < 5:
                flag = "低配关注"
            industry_deviation.append({
                "industry": ind.get("name"),
                "current_pct": ind_pct,
                "symbols_count": len(ind.get("symbols", [])),
                "deviation_flag": flag,
                "market_rank": next(
                    (si.get("rank") for si in sector_context.get("industries", [])
                     if si.get("name") == ind.get("name")),
                    None
                ),
                "market_avg_pct": next(
                    (si.get("market_avg_pct") for si in sector_context.get("industries", [])
                     if si.get("name") == ind.get("name")),
                    None
                ),
            })

        concepts = concentration.get("concept", [])
        concept_deviation = []
        for concept in concepts:
            concept_pct = concept.get("pct", 0)
            flag = "超配关注" if concept_pct > threshold * 2 else ""
            concept_deviation.append({
                "concept": concept.get("name"),
                "current_pct": concept_pct,
                "symbols_count": len(concept.get("symbols", [])),
                "deviation_flag": flag,
            })

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"偏离预警阈值: {threshold}% | 单票上限: {max_single}%",
            "",
            "## 当前持仓配置快照",
            f"持仓只数: {summary.get('count', 0)} | 总市值: ¥{total_mv:,.2f}",
            "",
            "## 个股持仓分布(按占比降序)",
            "```json",
            json.dumps(positions, ensure_ascii=False),
            "```",
        ]

        if over_limit_positions:
            parts.extend([
                "",
                f"## ⚠️ 单票超过 {max_single}% 上限的标的({len(over_limit_positions)} 只)",
                "```json",
                json.dumps(over_limit_positions, ensure_ascii=False),
                "```",
            ])

        if near_limit_positions:
            parts.extend([
                "",
                f"## 📌 接近单票上限(距上限 < 5%)的标的({len(near_limit_positions)} 只)",
                "```json",
                json.dumps(near_limit_positions, ensure_ascii=False),
                "```",
            ])

        parts.extend([
            "",
            "## 行业配置偏离度分析",
            "```json",
            json.dumps(industry_deviation, ensure_ascii=False),
            "```",
            "",
            "## 概念配置偏离度分析",
            "```json",
            json.dumps(concept_deviation, ensure_ascii=False),
            "```",
            "",
            "## 大盘环境参考(用于评估市场调整风险)",
            "```json",
            json.dumps({
                "emotion": market.get("emotion"),
                "indices": market.get("indices"),
                "breadth": market.get("breadth"),
                "limit": market.get("limit"),
            }, ensure_ascii=False),
            "```",
        ])

        return "\n".join(parts)