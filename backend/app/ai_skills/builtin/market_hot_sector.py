"""大盘热点板块分析 Skill — 板块轮动视角。

专注于涨停统计、连板梯队、板块可持续性分析。
"""
from __future__ import annotations

from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "market_hot_sector",
    "name": "大盘热点板块分析",
    "category": "market",
    "description": "热点板块轮动分析:涨停统计、连板梯队、板块可持续性与投机情绪",
    "tags": ["热点板块", "涨停", "连板", "板块轮动", "投机情绪"],
    "emoji": "🔥",
    "default_for_category": False,
    "params": [
        {
            "key": "max_boards_analysis",
            "label": "连板分析层数",
            "type": "int",
            "default": 5,
        },
        {
            "key": "include_sector_sustainability",
            "label": "包含板块可持续性分析",
            "type": "bool",
            "default": True,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股游资研究经验的市场分析师,擅长从涨停统计、连板梯队、板块轮动与投机情绪中客观识别市场热点与主线,产出一份**客观、中立、不包含任何买卖或操作建议**的热点板块分析报告。

## 核心红线(务必遵守)

- **绝对不输出**"打板/低吸/追高/接力/龙头/买它/干它"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**当前市场的热点结构与投机特征,不给出交易决策
- 所有判断基于提供的统计数据,不臆测个股走势

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 📊 涨停统计概览
- 涨停家数 / 跌停家数 / 炸板家数 / 封板率
- 涨停家数与近 5 日 / 20 日均值的对比
- 市场投机情绪的定性判断(冰点 / 回暖 / 亢奋 / 过热)

### 2. 🏗️ 连板梯队分析
- 当日最高连板高度
- 各连板层级的家数分布(1板 / 2板 / 3板 ...)
- 连板梯队的健康度(断层 / 流畅 / 拥挤)
- 连板高度与封板率的配合度

### 3. 🔥 热点板块识别
- 领涨板块排名与涨幅
- 各板块内涨停个股数量与集中度
- 板块内连板股的层级分布
- 板块之间的关联性与传导路径

### 4. 🔄 板块轮动特征
- 主线板块的持续性判断(连续天数 / 涨停家数趋势)
- 支线板块的轮动与补涨信号
- 板块切换的流畅度(有序轮动 / 混乱切换)
- 从主线到支线的资金传导路径

### 5. ⏱️ 板块可持续性评估
- 热点板块的生命周期位置(启动 / 加速 / 高潮 / 衰退)
- 封板率与涨停家数的趋势性变化
- 连板高度的扩展空间判断
- 可能的轮动方向与潜在热点

## 分析准则(务必遵守)

0. **只输出结论,不输出思考过程**:直接给结论
1. **数据说话**:每个判断引用具体的涨停家数、封板率、连板高度等数值
2. **客观中立**:只陈述事实与结构,不做预测,不给方向
3. **结构优先**:先看涨停总量,再看连板梯队,最后看板块结构
4. **不输出操作指令**:不写任何交易建议或个股推荐
5. **简明客观**:总字数 800-1500 字,重在结构分析

现在请基于下方数据进行热点板块分析。"""


def _build_limit_stats_block(overview: dict) -> str:
    lim = overview.get("limit") or {}
    b = overview.get("breadth") or {}

    limit_up = lim.get("limit_up", 0)
    limit_down = lim.get("limit_down", 0)
    broken = lim.get("broken", 0)
    seal_rate = lim.get("seal_rate", 0)
    max_boards = lim.get("max_boards", 0)

    lines = [
        f"- 涨停: {limit_up} 家",
        f"- 跌停: {limit_down} 家",
        f"- 炸板: {broken} 家",
        f"- 封板率: {seal_rate:.0f}%",
        f"- 最高连板: {max_boards} 板",
        f"- 上涨/下跌比: {b.get('up',0)} / {b.get('down',0)}",
    ]

    avg_limit_up_5d = lim.get("avg_limit_up_5d")
    avg_limit_up_20d = lim.get("avg_limit_up_20d")
    if avg_limit_up_5d:
        lines.append(f"- 5日均涨停: {avg_limit_up_5d:.0f} 家")
    if avg_limit_up_20d:
        lines.append(f"- 20日均涨停: {avg_limit_up_20d:.0f} 家")

    return "\n".join(lines)


def _build_tiers_block(overview: dict, max_boards: int) -> str:
    lim = overview.get("limit") or {}
    tiers = lim.get("tiers") or []

    if not tiers:
        return "(无连板梯队数据)"

    lines = ["**连板梯队:**"]
    for t in tiers[:max_boards]:
        boards = t.get("boards", "?")
        count = t.get("count", 0)
        lines.append(f"- {boards}板: {count} 家")

    if len(tiers) > max_boards:
        lines.append(f"- (共 {len(tiers)} 层,仅展示前 {max_boards} 层)")

    return "\n".join(lines)


def _build_sector_hot_block(overview: dict, top_n: int = 5) -> str:
    concept = overview.get("concept_rank") or {}
    industry = overview.get("industry_rank") or {}

    lines = []
    for label, rank in [("概念板块", concept), ("行业板块", industry)]:
        leading = rank.get("leading") or []
        if leading:
            lines.append(f"**领涨{label}:**")
            for item in leading[:top_n]:
                name = item.get("name", "—")
                pct = (item.get("avg_pct") or 0) * 100
                limit_up_count = item.get("limit_up_count", 0)
                lines.append(f"- {name}: {pct:+.2f}% (涨停 {limit_up_count} 家)")

    return "\n".join(lines) if lines else "(无板块排名数据)"


def _build_sector_sustainability_block(overview: dict) -> str:
    sustain = overview.get("sector_sustainability") or {}
    if not sustain:
        return "(无板块可持续性数据)"

    lines = []
    for sector in sustain.get("sectors", [])[:5]:
        name = sector.get("name", "—")
        days = sector.get("consecutive_days", 0)
        limit_trend = sector.get("limit_up_trend", "")
        lines.append(f"- {name}: 连续 {days} 天,涨停趋势 {limit_trend}")

    return "\n".join(lines) if lines else "(无板块可持续性数据)"


def _build_user_prompt(
    overview: dict,
    max_boards: int,
    include_sustainability: bool,
) -> str:
    as_of = overview.get("as_of") or "今日"

    parts: list[str] = [
        f"分析日期: {as_of}",
        f"连板分析层数: {max_boards}",
        "",
        "## 涨停统计概览",
        _build_limit_stats_block(overview),
        "",
        "## 连板梯队",
        _build_tiers_block(overview, max_boards),
        "",
        "## 热点板块排名",
        _build_sector_hot_block(overview),
    ]

    if include_sustainability:
        parts.extend(["", "## 板块可持续性", _build_sector_sustainability_block(overview)])

    return "\n".join(parts)


class MarketHotSectorSkill:
    """大盘热点板块分析 — 板块轮动视角。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        overview = context.get("market_overview") or {}
        max_boards = params.get("max_boards_analysis", 5)
        include_sustainability = params.get("include_sector_sustainability", True)

        return _build_user_prompt(overview, max_boards, include_sustainability)