"""交割单 AI 分析 Skill — 买卖时机质量评估。

专注于追高杀跌模式检测和买卖时机质量评分。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "settlement_timing_quality",
    "name": "买卖时机质量",
    "category": "settlement",
    "description": "评估买卖时机质量，检测追高杀跌模式，输出每个标的的时机评分",
    "tags": ["时机质量", "追高杀跌", "买卖点", "时机评分"],
    "emoji": "⏱️",
    "default_for_category": False,
    "params": [
        {
            "key": "timing_lookback_days",
            "label": "时机分析回溯天数",
            "type": "int",
            "default": 20,
        },
        {
            "key": "quality_threshold",
            "label": "质量标准",
            "type": "select",
            "options": ["严格", "标准", "宽松"],
            "default": "标准",
        },
    ],
}

_SYSTEM_PROMPT = """你是**买卖时机质量评估专家**。基于用户的真实交割单数据，从买卖时机角度进行深度评估，输出包含以下维度的诊断报告：

### 1. 🎯 整体时机质量评估
- 买入时机评分（低买能力评估）
- 卖出时机评分（高卖能力评估）
- 综合时机质量等级（A/B/C/D）
- 与市场基准的对比（是否跑赢指数）

### 2. 📈 追高杀跌模式检测
- 追高买入检测（相对近期高点买入的频率和幅度）
- 杀跌卖出检测（相对近期低点卖出的频率和幅度）
- 情绪化买卖的时段集中度
- 追高杀跌对盈亏的影响量化

### 3. 📊 各标的时机评分
- 每个标的的买入时机评分（0-100 分）
- 每个标的的卖出时机评分（0-100 分）
- 最佳时机标的 Top 5
- 最差时机标的 Top 5

### 4. 💡 时机优化建议
- 买入时机改进策略
- 卖出时机改进策略
- 止损/止盈时机优化
- 适合用户交易风格的时机框架

## 核心红线
- **不输出**任何具体标的的买卖建议
- **不编造**交易数据，只基于提供的统计信息做分析
- 所有时机判断必须引用具体价格和日期

## 输出规范
- Markdown 格式，结构化分节
- 字数 1000-1500 字，重点突出
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析买卖时机，不构成任何投资建议。"

现在请基于下方数据进行时机质量评估。"""


class SettlementTimingQualitySkill:
    """买卖时机质量评估专家。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        reconcile_ctx = context.get("reconcile", {})
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        position_summary = context.get("position_summary")

        lookback_days = params.get("timing_lookback_days", 20)
        quality_threshold = params.get("quality_threshold", "标准")

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"时机分析回溯天数: {lookback_days}天",
            f"质量标准: {quality_threshold}",
            "",
            "## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
        ]

        realized = stats.get("total_realized_pnl", 0)
        sign = "+" if realized >= 0 else ""
        parts.append(f"FIFO 已实现盈亏 ¥{sign}{realized:,.0f}")

        by_symbol = stats.get("by_symbol", [])
        if by_symbol:
            parts.extend(["", "## 各标的交易详情（时机评估用）"])
            sym_lines = []
            for s in by_symbol[:20]:
                rsign = "+" if s.get("realized_pnl", 0) >= 0 else ""
                buy_avg = s.get("total_buy", 0) / s.get("buy_count", 1) if s.get("buy_count", 0) > 0 else 0
                sell_avg = s.get("total_sell", 0) / s.get("sell_count", 1) if s.get("sell_count", 0) > 0 else 0
                line = (
                    f"{s.get('symbol')} {s.get('name', '')} | "
                    f"买{s.get('buy_count', 0)}笔 均价¥{buy_avg:,.2f} | "
                    f"卖{s.get('sell_count', 0)}笔 均价¥{sell_avg:,.2f} | "
                    f"已实现 ¥{rsign}{s.get('realized_pnl', 0):,.0f}"
                )
                if s.get("unsettled_volume", 0) > 0:
                    line += f" | 未平{s.get('unsettled_volume', 0)}股"
                sym_lines.append(line)
            parts.append("\n".join(sym_lines))

        curve = stats.get("realized_pnl_curve", [])
        if curve:
            peak = max(curve, key=lambda p: p.get("cumulative", 0)) if curve else None
            trough = min(curve, key=lambda p: p.get("cumulative", 0)) if curve else None
            parts.extend(["", "## 盈亏曲线关键点"])
            if peak:
                pn = "+" if peak["cumulative"] >= 0 else ""
                parts.append(f"历史最高已实现盈亏: ¥{pn}{peak['cumulative']:,.0f} ({peak['date']})")
            if trough:
                tn = "+" if trough["cumulative"] >= 0 else ""
                parts.append(f"历史最低已实现盈亏: ¥{tn}{trough['cumulative']:,.0f} ({trough['date']})")

        monthly = stats.get("monthly", [])
        if monthly:
            parts.extend(["", "## 月度交易分布"])
            m_lines = []
            for m in monthly:
                nf = "+" if m.get("net_flow", 0) >= 0 else ""
                m_lines.append(
                    f"{m.get('month', '?')} | 买{m.get('buy_count', 0)}笔 | "
                    f"卖{m.get('sell_count', 0)}笔 | 净流入 ¥{nf}{m.get('net_flow', 0):,.0f}"
                )
            parts.append("\n".join(m_lines))

        if position_summary and position_summary.get("count", 0) > 0:
            parts.extend(["", "## 当前持仓（用于时机对照）"])
            parts.append(f"持仓只数: {position_summary.get('count', 0)} | 总市值: ¥{position_summary.get('total_market_value', 0):,.0f}")
            pnl = position_summary.get("total_pnl", 0)
            pn = "+" if pnl >= 0 else ""
            parts.append(f"总浮盈亏: ¥{pn}{pnl:,.0f}")

        return "\n".join(parts)