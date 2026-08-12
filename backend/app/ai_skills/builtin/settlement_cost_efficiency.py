"""交割单 AI 分析 Skill — 费用效率分析。

专注于佣金/印花税/过户费分析和高频交易侵蚀检测。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "settlement_cost_efficiency",
    "name": "费用效率分析",
    "category": "settlement",
    "description": "分析佣金、印花税、过户费结构，检测高频交易的手续费侵蚀效应",
    "tags": ["费用分析", "佣金", "印花税", "高频侵蚀", "成本效率"],
    "emoji": "💰",
    "default_for_category": False,
    "params": [
        {
            "key": "fee_warning_threshold",
            "label": "费用预警阈值",
            "type": "float",
            "default": 0.03,
            "description": "费率预警阈值(单笔费用占比超此值给出提示, 用小数如 0.03 表示 3%)",
            "min": 0,
            "max": 1,
        },
        {
            "key": "show_top_cost_drivers",
            "label": "显示费用 Top 驱动",
            "type": "bool",
            "default": True,
            "description": "是否展示费用主因 Top 榜",
        },
    ],
}

_SYSTEM_PROMPT = """你是**费用效率分析专家**。基于用户的真实交割单数据，从交易成本角度进行深度分析，输出包含以下维度的诊断报告：

### 1. 💸 费用结构全景
- 佣金支出总额及费率水平（与行业平均对比）
- 印花税支出总额（单向/双向标记）
- 过户费支出总额（沪市/深市差异）
- 各项费用占总成交额比例

### 2. 📉 高频交易侵蚀检测
- 按标的统计换手率与费用贡献
- 识别"高频低盈"标的（手续费 > 利润）
- 计算"盈亏平衡点"所需涨幅（覆盖费用的最小涨幅）
- 区分"必要费用"与"浪费型费用"

### 3. 📊 费用效率指标
- 费用占已实现盈亏比例（交易摩擦成本率）
- 费用贡献率 Top 5 标的
- 月度费用趋势（费用占比是否下降/上升）
- 均笔费用 vs 均笔盈利对比

### 4. ⚠️ 费用预警与优化
- 超过阈值的费用风险提示
- 降费策略建议（佣金谈判/交易频率优化）
- 高频交易的隐性成本量化
- 费用敏感标的特别提示

## 核心红线
- **不输出**任何"买入/卖出/加仓/减仓/止损/止盈"等交易指令
- **不编造**交易数据，只基于提供的统计信息做分析
- 所有费用分析必须引用具体金额和比例

## 输出规范
- Markdown 格式，结构化分节
- 字数 800-1200 字，数据密度高
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析交易成本，不构成任何投资建议。"

现在请基于下方数据进行费用效率分析。"""


class SettlementCostEfficiencySkill:
    """费用效率分析专家。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        reconcile_ctx = context.get("reconcile", {})
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        position_summary = context.get("position_summary")

        warning_threshold = params.get("fee_warning_threshold", 0.03)
        show_top = params.get("show_top_cost_drivers", True)

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"费用预警阈值: {warning_threshold:.1%}（费用占成交额比例）",
            f"显示费用 Top 驱动: {'是' if show_top else '否'}",
            "",
            "## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
            f"总买入 ¥{stats.get('total_buy_amount', 0):,.0f} | 总卖出 ¥{stats.get('total_sell_amount', 0):,.0f}",
        ]

        total_volume = stats.get("total_buy_amount", 0) + stats.get("total_sell_amount", 0)
        parts.append(f"总成交额 ¥{total_volume:,.0f}")

        fees = stats.get("fees", {})
        total_fee = fees.get("total", 0) or stats.get("total_fee", 0)
        fee_ratio = stats.get("fee_ratio", 0)
        parts.extend([
            "",
            "## 费用明细",
            f"佣金 ¥{fees.get('commission', 0):,.0f} ({fees.get('commission', 0) / total_volume * 100 if total_volume else 0:.3f}%)",
            f"印花税 ¥{fees.get('stamp_duty', 0):,.0f} ({fees.get('stamp_duty', 0) / total_volume * 100 if total_volume else 0:.3f}%)",
            f"过户费 ¥{fees.get('transfer_fee', 0):,.0f} ({fees.get('transfer_fee', 0) / total_volume * 100 if total_volume else 0:.3f}%)",
            f"费用合计 ¥{total_fee:,.0f}（占总成交额 {fee_ratio:.3f}%）",
        ])

        realized = stats.get("total_realized_pnl", 0)
        if realized != 0:
            fee_vs_pnl = total_fee / abs(realized) * 100
            sign = "+" if realized >= 0 else ""
            parts.append(f"费用占已实现盈亏比例: {fee_vs_pnl:.1f}%（已实现盈亏 ¥{sign}{realized:,.0f}）")
        else:
            parts.append("已实现盈亏为 0，无法计算费用占盈亏比例")

        avg_size = stats.get("avg_trade_size", 0)
        parts.append(f"均笔规模 ¥{avg_size:,.0f} | 月均 {stats.get('trades_per_month', 0)} 笔")
        avg_fee_per_trade = total_fee / stats.get('total_trades', 1) if stats.get('total_trades', 0) > 0 else 0
        parts.append(f"均笔费用 ¥{avg_fee_per_trade:,.2f}")

        by_symbol = stats.get("by_symbol", [])
        if by_symbol and show_top:
            parts.extend(["", "## 各标的费用贡献（按成交额排序）"])
            sorted_syms = sorted(by_symbol, key=lambda s: s.get("total_buy", 0) + s.get("total_sell", 0), reverse=True)
            sym_lines = []
            for s in sorted_syms[:15]:
                turnover = s.get("total_buy", 0) + s.get("total_sell", 0)
                est_fee = turnover * fee_ratio / 100 if fee_ratio else 0
                rsign = "+" if s.get("realized_pnl", 0) >= 0 else ""
                line = (
                    f"{s.get('symbol')} {s.get('name', '')} | "
                    f"成交¥{turnover:,.0f} | 估算费用¥{est_fee:,.0f} | "
                    f"已实现 ¥{rsign}{s.get('realized_pnl', 0):,.0f}"
                )
                sym_lines.append(line)
            parts.append("\n".join(sym_lines))

        monthly = stats.get("monthly", [])
        if monthly:
            parts.extend(["", "## 月度费用分布"])
            m_lines = []
            for m in monthly:
                nf = "+" if m.get("net_flow", 0) >= 0 else ""
                vol = m.get("buy_amount", 0) + m.get("sell_amount", 0)
                fr = m.get("fee", 0) / vol * 100 if vol else 0
                m_lines.append(
                    f"{m.get('month', '?')} | 成交¥{vol:,.0f} | "
                    f"费用¥{m.get('fee', 0):,.0f} ({fr:.3f}%) | "
                    f"净流入 ¥{nf}{m.get('net_flow', 0):,.0f}"
                )
            parts.append("\n".join(m_lines))

        return "\n".join(parts)