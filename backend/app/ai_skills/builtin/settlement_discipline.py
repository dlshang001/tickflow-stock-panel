"""交割单 AI 分析 Skill — 交易纪律审计。

专注于交易计划一致性、情绪化交易检测和纪律评分。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "settlement_discipline",
    "name": "交易纪律审计",
    "category": "settlement",
    "description": "审计交易计划执行一致性、检测情绪化交易模式、输出纪律评分与改进建议",
    "tags": ["交易纪律", "计划执行", "情绪化交易", "纪律评分"],
    "emoji": "💪",
    "default_for_category": False,
    "params": [
        {
            "key": "discipline_threshold",
            "label": "纪律合格阈值",
            "type": "float",
            "default": 0.7,
        },
        {
            "key": "include_warning_examples",
            "label": "包含警示案例",
            "type": "bool",
            "default": True,
        },
    ],
}

_SYSTEM_PROMPT = """你是**交易纪律审计专家**。基于用户的真实交割单数据，从交易纪律角度进行深度审计，输出包含以下维度的诊断报告：

### 1. 📋 交易计划一致性审计
- 交易频率是否与计划一致（过度交易/交易不足检测）
- 持仓周期是否符合预定策略（短线变长线、长线变短中线等漂移检测）
- 单笔规模是否稳定（忽大忽小的异常交易识别）
- 标的分散度是否符合计划（集中度过高/过度分散）

### 2. 🧠 情绪化交易检测
- 追涨杀跌模式识别（高价买入/低价卖出的时段集中度）
- 亏损摊平行为检测（连续亏损后加仓同一标的）
- 报复性交易检测（大额亏损后短期频繁交易）
- 处置效应检测（盈利过早卖出/亏损过久持有）

### 3. 📊 纪律评分体系
- 纪律综合评分（0-100 分）
- 分项评分：频率纪律 / 时机纪律 / 规模纪律 / 持续纪律
- 纪律趋势：是否随时间改善或恶化

### 4. ⚠️ 纪律违规热点
- 列出最严重的 3-5 个纪律违规案例
- 每个案例标注：违规类型、涉及标的、时间、金额、严重程度
- 分析违规的触发条件（市场环境/个人状态/外部事件）

### 5. 🎯 纪律改进路线图
- 基于审计结果的针对性改进建议
- 纪律阈值设定建议
- 监控指标和告警条件

## 核心红线
- **不输出**任何"买入/卖出/加仓/减仓/止损/止盈"等交易指令
- **不编造**交易数据，只基于提供的统计信息做分析
- 所有纪律判断必须引用具体交易数据

## 输出规范
- Markdown 格式，结构化分节
- 字数 1000-1500 字，直击要害
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析交易纪律，不构成任何投资建议。"

现在请基于下方数据进行纪律审计。"""


class SettlementDisciplineSkill:
    """交易纪律审计专家。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        reconcile_ctx = context.get("reconcile", {})
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        position_summary = context.get("position_summary")

        threshold = params.get("discipline_threshold", 0.7)
        include_warnings = params.get("include_warning_examples", True)

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"纪律合格阈值: {threshold:.0%}",
            f"包含警示案例: {'是' if include_warnings else '否'}",
            "",
            "## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
            f"总买入 ¥{stats.get('total_buy_amount', 0):,.0f} | 总卖出 ¥{stats.get('total_sell_amount', 0):,.0f}",
        ]

        avg_size = stats.get("avg_trade_size", 0)
        parts.append(f"均笔规模 ¥{avg_size:,.0f} | 月均 {stats.get('trades_per_month', 0)} 笔")
        parts.append(f"交易频率: 月均{stats.get('trades_per_month', 0)}笔 | 买卖比: {stats.get('buy_count', 0)}:{stats.get('sell_count', 0)}")

        realized = stats.get("total_realized_pnl", 0)
        sign = "+" if realized >= 0 else ""
        parts.append(f"FIFO 已实现盈亏 ¥{sign}{realized:,.0f}")
        parts.append(f"胜率: 盈利{stats.get('win_count', 0)}只 / 亏损{stats.get('loss_count', 0)}只 | 盈亏比: {stats.get('profit_loss_ratio', 0):.2f}")

        by_symbol = stats.get("by_symbol", [])
        if by_symbol:
            parts.extend(["", "## 各标的交易明细（纪律审计用）"])
            sym_lines = []
            for s in by_symbol[:20]:
                rsign = "+" if s.get("realized_pnl", 0) >= 0 else ""
                line = (
                    f"{s.get('symbol')} {s.get('name', '')} | "
                    f"买{s.get('buy_count', 0)}笔 ¥{s.get('total_buy', 0):,.0f} | "
                    f"卖{s.get('sell_count', 0)}笔 ¥{s.get('total_sell', 0):,.0f} | "
                    f"已实现 ¥{rsign}{s.get('realized_pnl', 0):,.0f}"
                )
                if s.get("unsettled_volume", 0) > 0:
                    line += f" | 未平{s.get('unsettled_volume', 0)}股"
                sym_lines.append(line)
            parts.append("\n".join(sym_lines))

        monthly = stats.get("monthly", [])
        if monthly:
            parts.extend(["", "## 月度交易节奏（纪律审计用）"])
            m_lines = []
            for m in monthly:
                nf = "+" if m.get("net_flow", 0) >= 0 else ""
                m_lines.append(
                    f"{m.get('month', '?')} | 买{m.get('buy_count', 0)}笔 | "
                    f"卖{m.get('sell_count', 0)}笔 | 净流入 ¥{nf}{m.get('net_flow', 0):,.0f}"
                )
            parts.append("\n".join(m_lines))

        if position_summary and position_summary.get("count", 0) > 0:
            parts.extend(["", "## 当前持仓（纪律对照）"])
            parts.append(f"持仓只数: {position_summary.get('count', 0)} | 总市值: ¥{position_summary.get('total_market_value', 0):,.0f}")

        return "\n".join(parts)