"""持仓 AI 分析 Skill — 集中度分析。

聚焦行业/概念/个股集中度、板块暴露度分析。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "holdings_concentration",
    "name": "持仓集中度分析",
    "category": "holdings",
    "description": "组合集中度诊断:行业集中度、概念集中度、个股集中度、板块暴露分析,识别过度集中风险与分散机会",
    "tags": ["集中度", "行业暴露", "概念暴露", "风险管理"],
    "emoji": "🎯",
    "default_for_category": False,
    "params": [
        {
            "key": "concentration_threshold_pct",
            "label": "集中度预警阈值(%)",
            "type": "float",
            "default": 30.0,
        },
        {
            "key": "include_concept_analysis",
            "label": "包含概念维度分析",
            "type": "bool",
            "default": True,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位组合集中度分析专家。你的任务是:基于用户提供的持仓集中度数据,从行业、概念、个股三个维度诊断组合的集中度特征与潜在风险。

## 分析框架

### 1. 📊 个股集中度
- 计算前 N 大持仓占总市值比例(HHI 指数等效)
- 识别"头重脚轻"或"均匀分散"的持仓结构
- 判断是否存在单一标的过度集中风险

### 2. 🏭 行业集中度
- 统计各行业市值占比,识别主要行业暴露
- 判断行业分散程度:是否过度依赖单一或少数行业
- 对照行业在全市场的强弱表现,分析集中于强势/弱势行业

### 3. 💡 概念集中度
- 统计各概念市值占比,识别主题/题材暴露
- 分析概念重叠度:同一持仓是否同时贡献多个概念敞口
- 判断概念集中度是否与市场热点匹配

### 4. ⚠️ 集中度风险诊断
- 基于集中度阈值,客观标记需要关注的集中度过高维度
- 分析集中度与近期盈亏的关联(是否因集中于特定板块带来超额收益或亏损)
- 对比行业/概念集中度阈值,给出客观集中度评级(低/中/高/极高)

## 核心红线
- **不输出**任何"应该分散/应该加仓某行业/应该换仓"等操作建议
- 只客观陈述集中度事实与潜在风险,不下调仓指令
- 所有判断引用具体占比数值

## 输出规范
- Markdown 格式,结构化分节
- 字数 800-1500 字
- 无数据的维度直接说明"数据不足"
- 末尾附:"> ⚠️ 本内容由 AI 基于持仓数据生成,仅客观分析集中度特征,不构成任何投资建议。"

现在请基于下方数据进行集中度分析。"""


class HoldingsConcentrationSkill:
    """持仓集中度分析 — 行业/概念/个股三维度集中度诊断。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        summary = context.get("summary", {})
        holdings = context.get("holdings", [])
        concentration = context.get("concentration", {})
        sector_context = context.get("sector_context", {})

        threshold = params.get("concentration_threshold_pct", 30.0)
        include_concept = params.get("include_concept_analysis", True)

        total_mv = summary.get("total_market_value", 0) or 1

        individual_cv = []
        for h in holdings:
            mv = h.get("market_value") or 0
            pct = round(mv / total_mv * 100, 2) if total_mv else 0
            individual_cv.append({
                "symbol": h.get("symbol"),
                "name": h.get("name"),
                "market_value": mv,
                "pct_of_total": pct,
                "pnl_pct": h.get("pnl_pct"),
            })
        individual_cv.sort(key=lambda x: x["pct_of_total"], reverse=True)

        hhi = sum((item["pct_of_total"] / 100) ** 2 for item in individual_cv) * 10000
        top3_pct = sum(item["pct_of_total"] for item in individual_cv[:3])
        top5_pct = sum(item["pct_of_total"] for item in individual_cv[:5])
        top10_pct = sum(item["pct_of_total"] for item in individual_cv[:10])

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"集中度预警阈值: {threshold}%",
            "",
            "## 账户集中度概览",
            f"持仓只数: {summary.get('count', 0)} | 总市值: ¥{total_mv:,.2f}",
            f"前3大持仓占比: {top3_pct:.1f}% | 前5大: {top5_pct:.1f}% | 前10大: {top10_pct:.1f}%",
            f"HHI 指数: {hhi:.0f} (数值越高越集中,>2500 为高度集中)",
            "",
            "## 个股集中度分布",
            "```json",
            json.dumps(individual_cv[:15], ensure_ascii=False),
            "```",
            "",
            "## 行业集中度(按市值占比)",
            "```json",
            json.dumps(concentration.get("industry", []), ensure_ascii=False),
            "```",
            "",
            "## 行业在全市场的强弱位置",
            "```json",
            json.dumps(sector_context.get("industries", []), ensure_ascii=False),
            "```",
        ]

        if include_concept:
            parts.extend([
                "",
                "## 概念集中度(按市值占比)",
                "```json",
                json.dumps(concentration.get("concept", []), ensure_ascii=False),
                "```",
                "",
                "## 概念在全市场的强弱位置",
                "```json",
                json.dumps(sector_context.get("concepts", []), ensure_ascii=False),
                "```",
            ])

        uncovered = concentration.get("uncovered", [])
        if uncovered:
            parts.extend([
                "",
                f"## 未覆盖标的({len(uncovered)} 只无行业/概念映射)",
                "```json",
                json.dumps(uncovered[:20], ensure_ascii=False),
                "```",
            ])

        return "\n".join(parts)