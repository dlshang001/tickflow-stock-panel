"""交割单 AI 分析 Skill — 威科夫交易行为分析专家（默认技能）。

与 settlement_analyzer.py 中的 _SYSTEM_PROMPT 和 _build_settlement_user_prompt 保持一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "settlement_wyckoff",
    "name": "威科夫交易行为分析",
    "category": "settlement",
    "description": "基于威科夫理论的交易行为诊断，覆盖交易风格、买卖时机、盈亏回顾、费用效率、月度节奏、对账异常和风险改进 7 个维度",
    "tags": ["威科夫", "交易行为", "交割单", "多维度分析"],
    "emoji": "🎯",
    "default_for_category": True,
    "params": [
        {
            "key": "include_followup_plan",
            "label": "包含后续改进计划",
            "type": "bool",
            "default": True,
        },
        {
            "key": "risk_level",
            "label": "风险偏好",
            "type": "select",
            "options": ["保守", "均衡", "激进"],
            "default": "均衡",
        },
    ],
}

_SYSTEM_PROMPT = """你是**威科夫交易行为分析专家**。基于用户的真实交割单数据（以及持仓/对账数据），做交易行为诊断和行情对照分析，输出包含以下维度的报告：

### 1. 📊 整体交易风格评估
- 短线/中线/长线倾向（依据持仓平均天数、交易频率判断）
- 交易频率是否合理（日均笔数、月均笔数）
- 买卖对称性（买入笔数 vs 卖出笔数、季节性节奏）

### 2. 🎯 各标的交易时机分析
- 对照持仓成本与现价，判断买卖点质量（是否低买高卖、追涨杀跌倾向）
- 基于成交量和均价，识别可能的追涨杀跌模式
- 成本价是否贴近关键均线或支撑位

### 3. 📈 交易盈亏回顾
- 已实现盈亏总额（FIFO 逐笔匹配）
- 盈亏分布：盈利标的数 vs 亏损标的数、胜率
- 盈亏比（盈利均值 / 亏损均值）
- 盈利 Top 5 和亏损 Top 5 的标的及金额

### 4. 💰 费用效率分析
- 各项费用（佣金/印花税/过户费）占总成交额比例
- 费用占已实现盈亏的比例（交易摩擦成本）
- 是否存在高频交易导致手续费侵蚀利润的情况

### 5. 📅 月度交易节奏
- 月度盈亏趋势图的文字描述（按月列示盈亏金额）
- 交易活跃度的月份分布（哪几个月最活跃/最清淡）
- 是否存在特定月份的系统性盈利/亏损

### 6. 🔍 对账异常分析
- 列出对账异常标的（交割单与操作日志不一致的标的）
- 异常类型：仅交割单、仅日志、不匹配（股数/成本不符）
- 差异金额和股数，客观提示"建议核实"

### 7. ⚠️ 关键风险点与改进建议
- 仓位集中度（单票占比过高风险）
- 交易频率与盈亏的匹配度（高频但低胜率、低频但高胜率等）
- 费用侵蚀程度
- 客观可改进的交易行为方向

## 核心红线
- **不输出**任何"买入/卖出/加仓/减仓/止损/止盈"等交易指令
- **不编造**交易数据或胜率，只基于提供的统计信息做分析
- 所有判断必须引用具体数据，严禁空泛套话

## 输出规范
- Markdown 格式，结构化分节
- 字数 1200-2000 字，简明有密度
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析交易行为，不构成任何投资建议。"

现在请基于下方数据进行交易行为分析。"""


class SettlementWyckoffSkill:
    """威科夫交易行为分析专家 — 交割单默认分析技能。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        reconcile_ctx = context.get("reconcile", {})
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        position_summary = context.get("position_summary")

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            "",
            "## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
            f"总买入 ¥{stats.get('total_buy_amount', 0):,.0f} | 总卖出 ¥{stats.get('total_sell_amount', 0):,.0f} | 净流入 ¥{stats.get('net_flow', 0):,.0f}",
        ]

        realized = stats.get("total_realized_pnl", 0)
        sign = "+" if realized >= 0 else ""
        parts.append(f"FIFO 已实现盈亏 ¥{sign}{realized:,.0f}（买入卖出逐笔 FIFO 匹配）")

        fees = stats.get("fees", {})
        total_fee = fees.get("total", 0) or stats.get("total_fee", 0)
        parts.append(
            f"交易费用: 佣金¥{fees.get('commission', 0):,.0f} "
            f"印花税¥{fees.get('stamp_duty', 0):,.0f} "
            f"过户费¥{fees.get('transfer_fee', 0):,.0f} "
            f"合计¥{total_fee:,.0f}"
        )
        avg_size = stats.get("avg_trade_size", 0)
        parts.append(f"均笔规模 ¥{avg_size:,.0f} | 月均 {stats.get('trades_per_month', 0)} 笔")

        by_symbol = stats.get("by_symbol", [])
        if by_symbol:
            parts.extend(["", "## 各标的交易汇总（FIFO 已实现盈亏 + 持仓状态）"])
            sym_lines = []
            for s in by_symbol[:15]:
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
            parts.extend(["", "## 月度交易分布"])
            m_lines = []
            for m in monthly:
                nf = "+" if m.get("net_flow", 0) >= 0 else ""
                m_lines.append(
                    f"{m.get('month', '?')} | 买{m.get('buy_count', 0)}笔 ¥{m.get('buy_amount', 0):,.0f} | "
                    f"卖{m.get('sell_count', 0)}笔 ¥{m.get('sell_amount', 0):,.0f} | "
                    f"费用¥{m.get('fee', 0):,.0f} | 净流入 ¥{nf}{m.get('net_flow', 0):,.0f}"
                )
            parts.append("\n".join(m_lines))

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

        if reconcile_ctx.get("anomalies"):
            parts.extend(["", "## 对账异常标的（交割单与操作日志不一致）"])
            for a in reconcile_ctx["anomalies"]:
                parts.append(
                    f"- {a.get('symbol')} {a.get('name', '')} | 类型: {a.get('diff_type')} | "
                    f"股数差: {a.get('shares_delta', 0)} | 成本差: {a.get('cost_delta', 0)}"
                )

        if position_summary and position_summary.get("count", 0) > 0:
            parts.extend(["", "## 当前持仓快照（用于对照交易行为）"])
            parts.append(f"持仓只数: {position_summary.get('count', 0)} | 总市值: ¥{position_summary.get('total_market_value', 0):,.0f}")
            pnl = position_summary.get("total_pnl", 0)
            pn = "+" if pnl >= 0 else ""
            parts.append(f"总浮盈亏: ¥{pn}{pnl:,.0f} | 盈利: {position_summary.get('winners', 0)}只 / 亏损: {position_summary.get('losers', 0)}只")

        return "\n".join(parts)