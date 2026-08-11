"""大盘基本面/宏观分析 Skill — 消息与政策视角。

专注于央行动态、行业新闻、经济数据对市场的影响分析。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

META: dict[str, Any] = {
    "id": "market_fundamental",
    "name": "大盘基本面分析",
    "category": "market",
    "description": "基本面/宏观视角:央行政策、行业新闻、经济数据对市场的影响解读",
    "tags": ["基本面", "宏观", "央行政策", "经济数据", "行业新闻"],
    "emoji": "📰",
    "default_for_category": False,
    "params": [
        {
            "key": "news_lookback_days",
            "label": "新闻回溯天数",
            "type": "int",
            "default": 3,
        },
        {
            "key": "include_policy_analysis",
            "label": "包含政策分析",
            "type": "bool",
            "default": True,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股宏观研究经验的市场分析师,擅长从政策导向、经济数据、行业新闻与央行动态中客观解读市场基本面,产出一份**客观、中立、不包含任何买卖或操作建议**的基本面分析报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/超配/低配/看好/看空"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**当前市场面临的基本面环境与信息面,不给出交易决策
- 所有基本面判断必须基于提供的新闻与数据,不臆测未公开的信息

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 🏛️ 宏观政策环境
- 近期央行货币政策动态(公开市场操作 / 利率决议 / 流动性投放)
- 财政政策动向(专项债 / 减税降费 / 产业政策)
- 政策导向的定性判断(宽松 / 中性 / 收紧 / 定向调控)

### 2. 📊 经济数据解读
- 最新公布的关键经济数据(GDP / CPI / PPI / PMI / 社融 / M2)
- 数据对市场的影响路径与力度
- 数据是否超出市场预期

### 3. 🏢 行业新闻与催化
- 近期行业性政策与重大事件
- 行业景气度变化信号
- 潜在的主题性催化事件

### 4. 🌐 外部环境分析
- 外围市场(美股 / 港股)近期表现
- 汇率与大宗商品价格变动
- 地缘政治风险与国际贸易环境

### 5. 📰 基本面总结
- 当前市场基本面的核心矛盾
- 需要持续跟踪的关键信息源
- 信息面的有利与不利因素

## 分析准则(务必遵守)

0. **只输出结论,不输出思考过程**:直接给结论,不要写分析步骤
1. **事实导向**:每个判断基于具体的新闻或数据,引用信息来源
2. **客观中立**:只陈述事实与影响,不做预测,不给方向
3. **区分已兑现与待发酵**:明确哪些信息已被市场消化,哪些可能继续产生影响
4. **不输出操作指令**:不写任何交易建议或配置方向
5. **简明客观**:总字数 800-1500 字,重在信息密度

现在请基于下方数据进行基本面分析。"""


def _build_news_block(news: list[dict], lookback_days: int) -> str:
    if not news:
        return f"(近 {lookback_days} 天无新闻数据)"

    lines = []
    for i, n in enumerate(news[:15], 1):
        title = (n.get("title") or "").strip()
        snippet = (n.get("snippet") or "").strip()
        source = (n.get("source") or "").strip()
        pub = (n.get("published_date") or "").strip()
        cat = (n.get("category") or "").strip()
        meta_str = " / ".join(p for p in (cat, source, pub) if p)
        lines.append(f"{i}. {title}")
        if meta_str:
            lines.append(f"   [{meta_str}]")
        if snippet:
            lines.append(f"   {snippet[:200]}")

    return "\n".join(lines) if lines else f"(近 {lookback_days} 天无相关新闻)"


def _build_macro_block(overview: dict) -> str:
    macro = overview.get("macro") or {}
    if not macro:
        return "(无宏观数据)"

    lines = []

    policy = macro.get("policy") or {}
    if policy:
        lines.append("**货币政策:**")
        for k, v in policy.items():
            lines.append(f"- {k}: {v}")

    data = macro.get("economic_data") or {}
    if data:
        lines.extend(["", "**经济数据:**"])
        for item in data:
            name = item.get("name", "")
            value = item.get("value", "")
            prev = item.get("previous", "")
            exp = item.get("expected", "")
            lines.append(f"- {name}: {value} (前值 {prev}, 预期 {exp})")

    external = macro.get("external") or {}
    if external:
        lines.extend(["", "**外部环境:**"])
        for k, v in external.items():
            lines.append(f"- {k}: {v}")

    return "\n".join(lines) if lines else "(无宏观数据)"


def _build_user_prompt(
    overview: dict,
    news: list[dict],
    lookback_days: int,
    include_policy: bool,
) -> str:
    as_of = overview.get("as_of") or "今日"

    parts: list[str] = [
        f"分析日期: {as_of}",
        f"新闻回溯范围: 近 {lookback_days} 天",
        f"包含政策分析: {'是' if include_policy else '否'}",
    ]

    if include_policy:
        parts.extend(["", "## 宏观政策与经济数据", _build_macro_block(overview)])

    parts.extend(["", f"## 近期新闻(近 {lookback_days} 天)", _build_news_block(news, lookback_days)])

    return "\n".join(parts)


class MarketFundamentalSkill:
    """大盘基本面分析 — 消息与政策视角。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        overview = context.get("market_overview") or {}
        news = context.get("news") or []
        lookback_days = params.get("news_lookback_days", 3)
        include_policy = params.get("include_policy_analysis", True)

        return _build_user_prompt(overview, news, lookback_days, include_policy)