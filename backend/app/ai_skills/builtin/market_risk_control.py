"""大盘风险控制 Skill — 风险管理视角。

专注于仓位管理、止损位设定、风险预警信号分析。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "market_risk_control",
    "name": "大盘风险控制分析",
    "category": "market",
    "description": "风险控制视角:仓位管理建议、止损位设定、风险预警信号与波动分析",
    "tags": ["风险控制", "仓位管理", "止损", "波动率", "预警信号"],
    "emoji": "🛡️",
    "default_for_category": False,
    "params": [
        {
            "key": "risk_tolerance",
            "label": "风险承受偏好",
            "type": "select",
            "options": ["保守", "中性", "激进"],
            "default": "中性",
            "description": "风险偏好(影响风险提示的措辞强度)",
        },
        {
            "key": "include_stoploss_suggestions",
            "label": "包含止损位建议",
            "type": "bool",
            "default": True,
            "description": "是否包含止损建议(仅客观提示,不构成操作指令)",
        },
    ],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股风控经验的风险管理专家,擅长从波动率、市场宽度、连板结构与资金流向中客观评估当前市场的风险水平,产出一份**客观、中立、不包含任何买卖或操作建议**的风险控制分析报告。

## 核心红线(务必遵守)

- **绝对不输出**具体个股的买入/卖出建议、具体仓位数值、具体止损点位
- 你的角色是**客观评估**当前市场的风险状态与预警信号,不给出个性化交易决策
- 所有风险判断必须基于提供的数据,不臆测不存在的风险

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. ⚠️ 市场风险评估
- 当前市场整体风险水平(低 / 中 / 高 / 极高)
- 风险评分(0-100 分,分数越高风险越大)
- 风险评估的核心依据(波动率 / 宽度 / 情绪 / 结构)

### 2. 📉 波动率分析
- 主要指数当前波动率(近 5 日 / 20 日 / 60 日)
- 波动率与历史百分位的对比
- 波动率趋势(上升 / 下降 / 稳定)

### 3. 🔴 风险预警信号
- 市场宽度恶化信号(上涨占比下降 / 跌停家数增加)
- 连板断层风险(最高连板下降 / 炸板率上升)
- 资金面风险(成交额萎缩 / 外资流出 / 两融变化)
- 结构性风险(领涨板块回调 / 个股闪崩)

### 4. 🛡️ 风险控制建议
- 基于当前风险水平的仓位管理原则(结构性调整 / 总量控制)
- 止损位设定的原则与方法(基于波动率 / 均线 / 支撑位)
- 风险分散的维度(行业 / 个股 / 周期)
- 风险承受偏好与市场风险的匹配度

### 5. 📋 风险监控清单
- 需要持续跟踪的关键指标
- 风险升级的触发条件
- 风险缓解的参考策略

## 分析准则(务必遵守)

0. **只输出结论,不输出思考过程**:直接给结论
1. **数据说话**:每个风险判断引用具体的波动率数值、跌停家数等
2. **客观中立**:只陈述风险事实与历史统计,不做预测,不给方向
3. **区分系统性风险与结构性风险**:分别评估不同维度的风险
4. **不输出操作指令**:不写具体个股的买卖建议或止损点位
5. **简明客观**:总字数 800-1500 字,重在风险识别

现在请基于下方数据进行风险控制分析。"""


def _fmt_pct(v: float | None, suffix: str = "%") -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}{suffix}" if suffix else f"{v:.2f}"


def _build_volatility_block(overview: dict) -> str:
    vol = overview.get("volatility") or {}
    if not vol:
        indices = overview.get("indices") or []
        if indices:
            lines = []
            for idx in indices:
                name = idx.get("name") or idx.get("symbol")
                v5 = idx.get("vol_5d")
                v20 = idx.get("vol_20d")
                v60 = idx.get("vol_60d")
                parts = []
                if v5 is not None:
                    parts.append(f"5日 {v5:.2f}%")
                if v20 is not None:
                    parts.append(f"20日 {v20:.2f}%")
                if v60 is not None:
                    parts.append(f"60日 {v60:.2f}%")
                if parts:
                    lines.append(f"- {name} 波动率: {' / '.join(parts)}")
            return "\n".join(lines) if lines else "(无波动率数据)"
        return "(无波动率数据)"

    lines = []
    for name, data in vol.items():
        if isinstance(data, dict):
            v5 = data.get("5d") or data.get("vol_5d")
            v20 = data.get("20d") or data.get("vol_20d")
            v60 = data.get("60d") or data.get("vol_60d")
            parts = []
            if v5 is not None:
                parts.append(f"5日 {v5:.2f}%")
            if v20 is not None:
                parts.append(f"20日 {v20:.2f}%")
            if v60 is not None:
                parts.append(f"60日 {v60:.2f}%")
            pct_rank = data.get("percentile")
            rank_str = f" (历史 {pct_rank:.0f}% 分位)" if pct_rank is not None else ""
            lines.append(f"- {name}: {' / '.join(parts)}{rank_str}")

    return "\n".join(lines) if lines else "(无波动率数据)"


def _build_risk_warning_block(overview: dict) -> str:
    warnings = overview.get("risk_warnings") or {}
    if not warnings:
        b = overview.get("breadth") or {}
        lim = overview.get("limit") or {}
        emo = overview.get("emotion") or {}

        lines = []
        limit_down = lim.get("limit_down", 0)
        broken = lim.get("broken", 0)
        seal_rate = lim.get("seal_rate", 0)
        up_pct = b.get("up_pct", 0)
        down_count = b.get("down", 0)
        total = b.get("up", 0) + b.get("down", 0) + b.get("flat", 0)

        if limit_down > 0:
            lines.append(f"- 跌停家数: {limit_down} 家")
        if broken > 0:
            lines.append(f"- 炸板家数: {broken} 家 (炸板率 {broken / max(lim.get('limit_up', 1), 1) * 100:.0f}%)")
        if seal_rate < 60:
            lines.append(f"- 封板率偏低: {seal_rate:.0f}%")
        if up_pct < 40:
            lines.append(f"- 上涨占比偏低: {up_pct:.1f}%")
        emo_score = emo.get("score", 50)
        if emo_score < 40:
            lines.append(f"- 情绪温度偏低: {emo_score}")

        return "\n".join(lines) if lines else "(暂未检测到明显风险预警信号)"

    lines = []
    for level in ["high", "medium", "low"]:
        items = warnings.get(level) or []
        if items:
            level_label = {"high": "🔴 高风险", "medium": "🟡 中风险", "low": "🟢 低风险"}.get(level, level)
            for item in items:
                desc = item.get("description", str(item))
                lines.append(f"- [{level_label}] {desc}")

    return "\n".join(lines) if lines else "(暂未检测到风险预警信号)"


def _build_risk_score_block(overview: dict) -> str:
    risk = overview.get("risk") or {}
    score = risk.get("score")
    level = risk.get("level")
    factors = risk.get("factors") or []

    if score is None and level is None:
        return "(无风险评分数据)"

    lines = []
    if score is not None:
        lines.append(f"- 风险评分: {score}/100")
    if level is not None:
        level_labels = {"low": "低风险", "medium": "中风险", "high": "高风险", "extreme": "极高风险"}
        lines.append(f"- 风险等级: {level_labels.get(str(level).lower(), str(level))}")
    if factors:
        lines.append("- 风险因子:")
        for f in factors[:5]:
            lines.append(f"  - {f}")

    return "\n".join(lines)


def _build_user_prompt(
    overview: dict,
    risk_tolerance: str,
    include_stoploss: bool,
) -> str:
    as_of = overview.get("as_of") or "今日"

    parts: list[str] = [
        f"分析日期: {as_of}",
        f"风险承受偏好: {risk_tolerance}",
        f"包含止损建议: {'是' if include_stoploss else '否'}",
        "",
        "## 市场风险评估",
        _build_risk_score_block(overview),
        "",
        "## 波动率分析",
        _build_volatility_block(overview),
        "",
        "## 风险预警信号",
        _build_risk_warning_block(overview),
    ]

    if include_stoploss:
        sr = overview.get("support_resistance") or {}
        if sr:
            parts.extend(["", "## 关键支撑/压力位(止损参考)", _fmt_sr_for_risk(sr)])

    return "\n".join(parts)


def _fmt_sr_for_risk(sr: dict) -> str:
    lines = []
    for idx_name, levels in sr.items():
        supports = levels.get("support", [])
        resistances = levels.get("resistance", [])
        if supports:
            sup_str = "、".join(f"{s:.2f}" for s in supports[:3])
            lines.append(f"- {idx_name} 支撑位(止损参考): {sup_str}")
        if resistances:
            res_str = "、".join(f"{r:.2f}" for r in resistances[:3])
            lines.append(f"- {idx_name} 压力位: {res_str}")

    return "\n".join(lines) if lines else "(无支撑压力位数据)"


class MarketRiskControlSkill:
    """大盘风险控制分析 — 风险管理视角。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        overview = context.get("market_overview") or {}
        risk_tolerance = params.get("risk_tolerance", "中性")
        include_stoploss = params.get("include_stoploss_suggestions", True)

        return _build_user_prompt(overview, risk_tolerance, include_stoploss)