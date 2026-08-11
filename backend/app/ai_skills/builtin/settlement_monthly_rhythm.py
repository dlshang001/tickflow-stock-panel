"""交割单 AI 分析 Skill — 月度节奏诊断。

专注于月度盈亏分布、季节性模式和交易节奏优化。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "settlement_monthly_rhythm",
    "name": "月度节奏诊断",
    "category": "settlement",
    "description": "分析月度盈亏分布、季节性交易模式，提供节奏优化建议",
    "tags": ["月度节奏", "季节性", "盈亏分布", "交易节奏"],
    "emoji": "📅",
    "default_for_category": False,
    "params": [
        {
            "key": "include_seasonal_analysis",
            "label": "包含季节性分析",
            "type": "bool",
            "default": True,
        },
        {
            "key": "show_weekly_distribution",
            "label": "显示周度分布",
            "type": "bool",
            "default": False,
        },
    ],
}

_SYSTEM_PROMPT = """你是**月度交易节奏诊断专家**。基于用户的真实交割单数据，从时间节奏角度进行深度诊断，输出包含以下维度的分析报告：

### 1. 📅 月度盈亏全景
- 各月度盈亏金额及趋势
- 盈利月份 vs 亏损月份分布
- 月度盈亏标准差（稳定性评估）
- 最佳/最差月份识别

### 2. 🌊 季节性模式识别
- 季度性盈亏规律（Q1/Q2/Q3/Q4 对比）
- 特定月份的系统性倾向（如年末效应、春季行情等）
- 月度活跃度与盈亏的相关性
- 闰年/特殊事件影响排除

### 3. 📊 交易节奏健康度
- 交易频率的月度稳定性（是否均匀分布）
- 盈亏节奏匹配度（赚的月份是否多交易、亏的月份是否少交易）
- 节奏一致性评分
- 异常节奏检测（某月交易过度/交易不足）

### 4. 🎯 节奏优化建议
- 基于历史数据的最优交易节奏
- 哪些月份应加强/减少交易
- 节奏偏离的预警机制
- 年度交易计划框架

## 核心红线
- **不输出**任何"买入/卖出/加仓/减仓/止损/止盈"等交易指令
- **不编造**交易数据，只基于提供的统计信息做分析
- 所有节奏判断必须引用具体月份数据

## 输出规范
- Markdown 格式，结构化分节
- 字数 800-1200 字，图表描述性强
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析交易节奏，不构成任何投资建议。"

现在请基于下方数据进行月度节奏诊断。"""


class SettlementMonthlyRhythmSkill:
    """月度交易节奏诊断专家。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        reconcile_ctx = context.get("reconcile", {})
        if isinstance(reconcile_ctx, list):
            reconcile_ctx = {"anomalies": reconcile_ctx}
        position_summary = context.get("position_summary")

        include_seasonal = params.get("include_seasonal_analysis", True)
        show_weekly = params.get("show_weekly_distribution", False)

        parts: list[str] = [
            f"分析日期: {date.today().isoformat()}",
            f"包含季节性分析: {'是' if include_seasonal else '否'}",
            f"显示周度分布: {'是' if show_weekly else '否'}",
            "",
            "## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
            f"总买入 ¥{stats.get('total_buy_amount', 0):,.0f} | 总卖出 ¥{stats.get('total_sell_amount', 0):,.0f}",
        ]

        realized = stats.get("total_realized_pnl", 0)
        sign = "+" if realized >= 0 else ""
        parts.append(f"FIFO 已实现盈亏 ¥{sign}{realized:,.0f}")

        monthly = stats.get("monthly", [])
        if monthly:
            parts.extend(["", "## 月度交易分布（节奏诊断主数据）"])
            m_lines = []
            total_monthly_net = 0
            profitable_months = 0
            losing_months = 0
            for m in monthly:
                nf = "+" if m.get("net_flow", 0) >= 0 else ""
                net = m.get("net_flow", 0)
                total_monthly_net += net
                if net > 0:
                    profitable_months += 1
                elif net < 0:
                    losing_months += 0
                m_lines.append(
                    f"{m.get('month', '?')} | 买{m.get('buy_count', 0)}笔 ¥{m.get('buy_amount', 0):,.0f} | "
                    f"卖{m.get('sell_count', 0)}笔 ¥{m.get('sell_amount', 0):,.0f} | "
                    f"费用¥{m.get('fee', 0):,.0f} | 净流入 ¥{nf}{net:,.0f}"
                )
            parts.append("\n".join(m_lines))

            parts.extend([
                "",
                "## 月度节奏汇总",
                f"盈利月份: {profitable_months}个 | 亏损月份: {losing_months}个 | 持平月份: {len(monthly) - profitable_months - losing_months}个",
                f"月度净流入合计: ¥{total_monthly_net:,.0f}",
            ])

            if len(monthly) >= 3:
                q1 = sum(m.get("net_flow", 0) for m in monthly if m.get("month", "").endswith(("-01", "-02", "-03")))
                q2 = sum(m.get("net_flow", 0) for m in monthly if m.get("month", "").endswith(("-04", "-05", "-06")))
                q3 = sum(m.get("net_flow", 0) for m in monthly if m.get("month", "").endswith(("-07", "-08", "-09")))
                q4 = sum(m.get("net_flow", 0) for m in monthly if m.get("month", "").endswith(("-10", "-11", "-12")))
                parts.extend([
                    "",
                    "## 季度分布（季节性分析）" if include_seasonal else "",
                    f"Q1 ¥{q1:,.0f} | Q2 ¥{q2:,.0f} | Q3 ¥{q3:,.0f} | Q4 ¥{q4:,.0f}",
                ])

        by_symbol = stats.get("by_symbol", [])
        if by_symbol:
            parts.extend(["", "## 各标的盈亏汇总"])
            sym_lines = []
            for s in by_symbol[:15]:
                rsign = "+" if s.get("realized_pnl", 0) >= 0 else ""
                line = (
                    f"{s.get('symbol')} {s.get('name', '')} | "
                    f"买{s.get('buy_count', 0)}笔 | 卖{s.get('sell_count', 0)}笔 | "
                    f"已实现 ¥{rsign}{s.get('realized_pnl', 0):,.0f}"
                )
                sym_lines.append(line)
            parts.append("\n".join(sym_lines))

        return "\n".join(parts)