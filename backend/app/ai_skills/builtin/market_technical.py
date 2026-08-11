"""大盘技术面分析 Skill — 技术指标视角。

专注于均线系统、成交量、支撑压力位、背离信号等技术维度分析。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "market_technical",
    "name": "大盘技术面分析",
    "category": "market",
    "description": "技术分析视角:均线系统、成交量分析、支撑压力位、背离信号检测",
    "tags": ["技术分析", "均线", "成交量", "支撑压力", "背离"],
    "emoji": "📈",
    "default_for_category": False,
    "params": [
        {
            "key": "include_divergence_analysis",
            "label": "包含背离分析",
            "type": "bool",
            "default": True,
        },
        {
            "key": "timeframe",
            "label": "分析周期",
            "type": "select",
            "options": ["日线", "周线", "月线"],
            "default": "日线",
        },
    ],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股技术分析经验的市场分析师,擅长从均线系统、成交量结构、支撑压力位与背离信号中客观识别市场技术状态,产出一份**客观、中立、不包含任何买卖或操作建议**的技术面分析报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/抄底/逃顶/止损/止盈"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**当前市场的技术结构与信号,不给出交易决策
- 所有技术判断必须基于提供的数据,不臆测不存在的指标

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 📊 均线系统分析
- 主要指数当前价位与 MA5 / MA10 / MA20 / MA60 的位置关系(站上/跌破/纠缠)
- 均线多空排列状态(多头排列 / 空头排列 / 均线纠缠)
- 均线斜率变化(上行 / 走平 / 下行)

### 2. 📉 成交量分析
- 当日成交额与近期均值(5 日 / 20 日)的对比(放量 / 缩量 / 正常)
- 量价配合度(价涨量增 / 价涨量缩 / 价跌量增 / 价跌量缩)
- 量能异动信号(量比突变 / 成交额突破关键阈值)

### 3. 🎯 支撑与压力
- 主要指数当前位置的关键支撑位与压力位(基于近期高低点与均线推断)
- 支撑/压力位的有效性判断(多次验证 / 首次触及 / 已突破)
- 若已知近期波动区间,分析当前位置在区间中的相对位置

### 4. 🔄 背离信号检测
- 价格创新高/新低但成交量未配合的量价背离
- 指数与主要板块之间的结构性背离
- 若数据包含 MACD / RSI 等指标,识别潜在的顶背离或底背离信号

### 5. 📐 技术形态总结
- 当前市场技术状态的定性描述(强势 / 震荡 / 弱势 / 反转信号)
- 关键技术信号汇总(均线状态 + 量能 + 背离)
- 技术面需要关注的风险点或机会点

## 分析准则(务必遵守)

0. **只输出结论,不输出思考过程**:直接给结论,不要写分析步骤或方法论
1. **数据说话**:每个技术判断引用具体数值(如"上证站上 MA5 与 MA10,但受制于 MA20")
2. **客观中立**:只陈述技术事实,不做预测,不给方向
3. **结构优先**:先看均线系统,再看量价配合,最后看背离与形态
4. **不输出操作指令**:不写任何交易建议或买卖方向
5. **简明客观**:总字数 800-1500 字,重在技术信号的客观解读

现在请基于下方数据进行技术面分析。"""


def _fmt_pct(v: float | None, suffix: str = "%") -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}{suffix}" if suffix else f"{v:.2f}"


def _build_indices_tech_block(overview: dict, timeframe: str) -> str:
    indices = overview.get("indices") or []
    if not indices:
        return "(暂无指数技术数据)"

    lines = [f"分析周期: {timeframe}", ""]
    for idx in indices:
        name = idx.get("name") or idx.get("symbol")
        price = idx.get("last_price")
        chg = idx.get("change_pct")
        price_s = f"{price:.2f}" if price is not None else "—"

        ma5 = idx.get("ma5")
        ma10 = idx.get("ma10")
        ma20 = idx.get("ma20")
        ma60 = idx.get("ma60")

        ma_parts = []
        for label, val in [("MA5", ma5), ("MA10", ma10), ("MA20", ma20), ("MA60", ma60)]:
            if val is not None and price is not None:
                diff_pct = (price - val) / val * 100
                position = "上方" if diff_pct > 0 else "下方"
                ma_parts.append(f"{label} {val:.2f}(价在{position} {abs(diff_pct):.2f}%)")

        ma_line = " | ".join(ma_parts) if ma_parts else "均线数据缺失"
        lines.append(f"- {name}: {price_s} ({_fmt_pct(chg)})")
        lines.append(f"  均线: {ma_line}")

    return "\n".join(lines)


def _build_volume_block(overview: dict) -> str:
    amt = overview.get("amount") or {}
    act = overview.get("activity") or {}
    total_amount = amt.get("total") or 0
    amount_yi = total_amount / 1e8 if total_amount else 0

    vol_ratio = act.get("vol_ratio", 1)
    turnover = act.get("avg_turnover", 0)

    lines = [
        f"- 两市成交额: {amount_yi:.0f} 亿元",
        f"- 量比(5日均): {vol_ratio:.2f}",
        f"- 平均换手率: {turnover:.2f}%",
    ]

    amt_5d = amt.get("avg_5d")
    amt_20d = amt.get("avg_20d")
    if amt_5d:
        lines.append(f"- 5日均成交额: {amt_5d / 1e8:.0f} 亿元")
    if amt_20d:
        lines.append(f"- 20日均成交额: {amt_20d / 1e8:.0f} 亿元")

    return "\n".join(lines)


def _build_trend_block(overview: dict) -> str:
    tr = overview.get("trend") or {}
    lines = [
        "- 站上 MA5 占比: {:.0f}%".format(tr.get("above_ma5_pct", 0)),
        "- 站上 MA20 占比: {:.0f}%".format(tr.get("above_ma20_pct", 0)),
        "- 站上 MA60 占比: {:.0f}%".format(tr.get("above_ma60_pct", 0)),
    ]
    return "\n".join(lines)


def _build_divergence_block(overview: dict) -> str:
    div = overview.get("divergence") or {}
    if not div:
        return "(无背离检测数据)"

    lines = []
    for key, items in div.items():
        if items:
            div_type = "顶背离" if "top" in key.lower() else "底背离" if "bottom" in key.lower() else key
            for item in items[:3]:
                lines.append(f"- {div_type}: {item.get('description', str(item))}")

    return "\n".join(lines) if lines else "(未检测到明显背离信号)"


def _build_support_resistance_block(overview: dict) -> str:
    sr = overview.get("support_resistance") or {}
    if not sr:
        return "(无支撑压力位数据)"

    lines = []
    for idx_name, levels in sr.items():
        supports = levels.get("support", [])
        resistances = levels.get("resistance", [])
        if supports:
            sup_str = "、".join(f"{s:.2f}" for s in supports[:3])
            lines.append(f"- {idx_name} 支撑位: {sup_str}")
        if resistances:
            res_str = "、".join(f"{r:.2f}" for r in resistances[:3])
            lines.append(f"- {idx_name} 压力位: {res_str}")

    return "\n".join(lines) if lines else "(无支撑压力位数据)"


def _build_user_prompt(overview: dict, timeframe: str, include_divergence: bool) -> str:
    as_of = overview.get("as_of") or "今日"

    parts: list[str] = [
        f"分析日期: {as_of}",
        f"分析周期: {timeframe}",
        "",
        "## 指数技术指标",
        _build_indices_tech_block(overview, timeframe),
        "",
        "## 成交量分析",
        _build_volume_block(overview),
        "",
        "## 均线站位",
        _build_trend_block(overview),
    ]

    if include_divergence:
        parts.extend(["", "## 背离信号检测", _build_divergence_block(overview)])

    parts.extend(["", "## 支撑与压力", _build_support_resistance_block(overview)])

    return "\n".join(parts)


class MarketTechnicalSkill:
    """大盘技术面分析 — 技术指标视角。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        overview = context.get("market_overview") or {}
        timeframe = params.get("timeframe", "日线")
        include_divergence = params.get("include_divergence_analysis", True)

        return _build_user_prompt(overview, timeframe, include_divergence)