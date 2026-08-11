"""持仓 AI 分析 Skill — 风险暴露分析。

聚焦最大回撤、Beta 系数、相关性、流动性风险等维度。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "holdings_risk",
    "name": "持仓风险分析",
    "category": "holdings",
    "description": "组合风险诊断:最大回撤、Beta 系数、市场相关性、流动性风险、波动率分析",
    "tags": ["风险", "波动率", "Beta", "流动性"],
    "emoji": "⚠️",
    "default_for_category": False,
    "params": [
        {
            "key": "risk_free_rate",
            "label": "无风险利率",
            "type": "float",
            "default": 0.02,
        },
        {
            "key": "include_stress_test",
            "label": "包含压力测试",
            "type": "bool",
            "default": False,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位组合风险管理专家。你的任务是:基于用户提供的持仓风险指标数据,从多个风险维度客观评估组合的风险暴露状况。

## 分析框架

### 1. 📉 回撤风险分析
- 最大回撤幅度与持续时间
- 当前回撤位置在历史回撤中的分位数
- 回撤恢复难度评估(基于波动率与趋势)

### 2. 📐 Beta 系数与市场相关性
- 组合整体 Beta(系统性风险暴露)
- 各持仓与大盘指数的相关性
- 行业/概念层面的 Beta 聚合
- 组合分散化程度(平均相关系数)

### 3. 💧 流动性风险
- 各持仓的成交量与换手率
- 大额持仓的流动性覆盖(持仓市值 / 日均成交额)
- 潜在冲击成本评估

### 4. 📊 波动率与 VaR
- 组合年化波动率
- 条件风险价值(C-VaR)估算
- 下行风险与上行风险不对称性
- 基于无风险利率的风险溢价分析

### 5. 🔬 压力测试(可选)
- 历史极端行情下的组合表现
- 板块轮动下的风险敞口变化
- 利率/政策变动敏感场景

## 核心红线
- **不输出**任何"应该减仓/应该对冲/应该止损"等操作建议
- 只客观陈述风险状态与量化指标,不给出风险决策
- 所有风险指标必须引用具体数值与计算方法

## 输出规范
- Markdown 格式,结构化分节
- 字数 800-1500 字
- 无数据的维度直接说明"数据不足"
- 末尾附:"> ⚠️ 本内容由 AI 基于持仓数据生成,仅客观分析风险指标,不构成任何投资建议。"

现在请基于下方数据进行风险分析。"""


class HoldingsRiskSkill:
    """持仓风险分析 — 回撤、Beta、相关性、流动性、波动率。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        summary = context.get("summary", {})
        holdings = context.get("holdings", [])
        market = context.get("market_snapshot", {})
        concentration = context.get("concentration", {})

        rf_rate = params.get("risk_free_rate", 0.02)
        include_stress = params.get("include_stress_test", False)

        total_mv = summary.get("total_market_value", 0) or 1

        risk_metrics = []
        for h in holdings:
            mv = h.get("market_value") or 0
            pnl_pct = h.get("pnl_pct")
            day_chg = h.get("day_change_pct")
            vol_ratio = h.get("vol_ratio")
            rsi = h.get("rsi14")
            pct = round(mv / total_mv * 100, 2) if total_mv else 0

            risk_score_components = []
            if pnl_pct is not None:
                if pnl_pct < -20:
                    risk_score_components.append("深度套牢")
                elif pnl_pct < -10:
                    risk_score_components.append("中度浮亏")
                elif pnl_pct > 30:
                    risk_score_components.append("大幅浮盈(获利回吐风险)")

            if day_chg is not None:
                if day_chg < -5:
                    risk_score_components.append("单日大跌")
                elif day_chg > 5:
                    risk_score_components.append("单日大涨(追高风险)")

            if rsi is not None:
                if rsi > 80:
                    risk_score_components.append("RSI 超买")
                elif rsi < 20:
                    risk_score_components.append("RSI 超卖")

            if vol_ratio is not None:
                if vol_ratio > 3:
                    risk_score_components.append("量能异常放大")
                elif vol_ratio < 0.5:
                    risk_score_components.append("量能萎缩")

            risk_metrics.append({
                "symbol": h.get("symbol"),
                "name": h.get("name"),
                "pct_of_total": pct,
                "pnl_pct": pnl_pct,
                "day_change_pct": day_chg,
                "rsi14": rsi,
                "vol_ratio": vol_ratio,
                "trend": h.get("trend"),
                "nearest_support": h.get("nearest_support"),
                "nearest_resistance": h.get("nearest_resistance"),
                "risk_flags": risk_score_components,
            })

        risk_metrics.sort(key=lambda x: len(x["risk_flags"]), reverse=True)

        total_pnl = summary.get("total_pnl", 0) or 0
        total_pnl_pct = summary.get("total_pnl_pct", 0) or 0
        winners = summary.get("winners", 0)
        losers = summary.get("losers", 0)
        avg_pnl_pct = total_pnl_pct / (winners + losers) if (winners + losers) else 0

        negative = [h for h in holdings if (h.get("pnl_pct") or 0) < 0]
        positive = [h for h in holdings if (h.get("pnl_pct") or 0) > 0]
        max_loss = min((h.get("pnl_pct") or 0) for h in holdings) if holdings else 0
        max_gain = max((h.get("pnl_pct") or 0) for h in holdings) if holdings else 0
        loss_severity = sum(h.get("pnl_pct", 0) ** 2 for h in negative) ** 0.5 if negative else 0

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"无风险利率: {rf_rate:.1%}",
            "",
            "## 组合风险概览",
            f"持仓只数: {summary.get('count', 0)} | 总市值: ¥{total_mv:,.2f}",
            f"总浮盈亏: ¥{total_pnl:,.2f} ({total_pnl_pct:.2f}%)",
            f"盈利: {winners}只 / 亏损: {losers}只 | 平均盈亏: {avg_pnl_pct:.2f}%",
            f"最大单幅盈利: {max_gain:.2f}% | 最大单幅亏损: {max_loss:.2f}%",
            f"下行风险(亏损标的波动): {loss_severity:.2f}%",
            "",
            "## 各持仓风险指标",
            "```json",
            json.dumps(risk_metrics, ensure_ascii=False),
            "```",
            "",
            "## 行业风险暴露",
            "```json",
            json.dumps(concentration.get("industry", []), ensure_ascii=False),
            "```",
            "",
            "## 大盘环境(用于评估系统性风险)",
            "```json",
            json.dumps({
                "emotion": market.get("emotion"),
                "indices": market.get("indices"),
                "breadth": market.get("breadth"),
                "limit": market.get("limit"),
            }, ensure_ascii=False),
            "```",
        ]

        if include_stress:
            parts.extend([
                "",
                "## 压力测试场景(基于历史行情假设)",
                "- 若大盘单日下跌 5%,基于当前行业集中度估算组合潜在影响",
                "- 若行业轮动加速,集中持仓的板块可能面临的调整压力",
                "- 若流动性收紧,高持仓集中度标的的潜在冲击成本",
            ])

        return "\n".join(parts)