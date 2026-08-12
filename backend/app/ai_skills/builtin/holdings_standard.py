"""持仓 AI 分析 Skill — 标准组合复盘（默认技能）。

复刻 position_analyzer.py 的 _SYSTEM_PROMPT 与 _build_user_prompt 行为,
提供 15 年 A 股研究分析师视角的 7 维度持仓组合客观复盘。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

META: dict[str, Any] = {
    "id": "holdings_standard",
    "name": "持仓组合标准复盘",
    "category": "holdings",
    "description": "基于 15 年 A 股研究经验的 7 维度持仓组合复盘:账户概览、大盘对照、逐只状态、交割回顾、板块集中度、风险点、客观信号",
    "tags": ["持仓", "组合复盘", "账户视角", "多维度"],
    "emoji": "📊",
    "default_for_category": True,
    "params": [
        {
            "key": "max_holdings_detail",
            "label": "逐只明细上限",
            "type": "int",
            "default": 10,
            "description": "单只持仓明细展示数量上限",
            "min": 1,
            "max": 30,
        },
    ],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股研究经验的组合复盘分析师。你的任务是:基于用户提供的**当前持仓数据**与**大盘环境**,产出一份客观、中立、不包含任何买卖或操作建议的账户持仓复盘报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/调仓/换仓/止损/止盈/清仓/观望/建议持有/目标价"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**账户的盈亏结构、板块/风格暴露、每只持仓的技术状态与潜在风险,让读者自行判断
- 只描述"现在是什么状态",不描述"应该怎么做"

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构,不要输出 JSON 或代码块。

### 1. 📊 账户概览(2-4 句)
基于提供的账户汇总数据,客观描述:总市值、总浮盈亏(额与比例)、今日涨跌只数对比、盈利/亏损只数、整体仓位的盈亏分布。数据说话,不评价操作好坏。

### 2. 🌡️ 大盘环境与持仓对照(2-4 句)
基于提供的"大盘环境"数据,客观描述今日盘面:
- 主要指数涨跌(上证/深成/创业板/科创等)与全市场情绪(emotion)
- 涨跌家数与赚钱效应(上涨占比、平均涨幅、强势/弱势股数量)
- 成交额与量能、涨跌停/连板高度、领涨与领跌的行业/概念
- 据此客观陈述:持仓整体今日是强于还是弱于大盘(用持仓上涨只数占比 vs 全市场上涨占比、持仓平均涨幅 vs 全市场平均涨幅对比)
只做客观对照,不臆测后市、不给操作建议。若大盘环境数据为空(如非交易日/未同步),直接说明"暂无大盘数据",不要编造指数涨跌。

### 3. 📈 持仓逐只状态
对每一只持仓,用 1-2 句客观描述其:浮动盈亏(额/比例)、持仓天数、趋势标签、距当前价最近的支撑/压力位、RSI/量能等指标状态。
- 用**简洁的 Markdown 表格**呈现(列:代码、名称、浮盈亏、今日、趋势、技术状态)
- 表格之后,对浮盈亏较大或技术状态值得注意的标的用 2-4 句客观补充
- 每条只陈述事实,不写操作建议

### 4. 💰 交割单盈亏回顾
基于提供的"交割单数据"（含真实成交记录的已实现盈亏、费用、月度表现），客观描述：
- 历史已实现盈亏总额（盈利/亏损）
- 费用合计（佣金/印花税/过户费）及占成交额比例
- 盈利最多的前几只标的与亏损最多的标的（金额/名称）
- 最近几个月的月度盈亏趋势（是持续盈利还是波动较大）
- 若存在"对账异常"（交割单推导持仓与操作日志不符的标的），列出并客观说明差异类型与股数/成本偏差
若交割单数据为空（未导入），直接说明"暂无交割单数据，无法回顾已实现盈亏"。

### 5. 🧩 行业/概念集中度与板块强弱
基于提供的"板块归因"和"持仓板块全市场强弱对照"数据,客观描述:
- 持仓主要集中在哪些行业(列出占比靠前的行业及其占比)
- 概念暴露(若有,列出占比较高的概念)
- 是否存在单一行业/概念占比过高(如某行业占比超过 40%),客观提示集中度
- **持仓板块当日在全市场的强弱**:对照"持仓板块全市场强弱"中的 rank/market_avg_pct/is_leading/is_lagging,
  客观说明持仓主要押在当日强势板块还是弱势板块(如"持仓占比 40% 的医药行业今日平均+2.1%,在全市场 X 个行业中排第 Y,处于领涨前列")
- 可引用板块龙头(leader_name/leader_pct)佐证板块强度
本节是第 5 节"风险点"中结构维度的数据支撑;**不下"应该分散/换仓/追涨"等操作结论**。
若板块归因或强弱数据为空,直接说明"行业/概念数据未同步,暂无法评估",不要编造排名。

### 6. ⚠️ 风险点
客观列出(不超过 5 条):
- 盈亏分布是否分化(单只贡献过大/拖后腿)
- 行业/概念是否过度集中(引用第 5 节数据)
- 哪些标的跌破关键均线或距支撑位较近
- 哪些标的 RSI 超买/超卖或量能异常
- 若有对账异常(第 4 节交割单数据)且同时存在持仓浮亏,客观提示"该标的操作日志与交割单记录存在差异,建议核实"
只做客观提示,不下"应该减仓"等结论。

### 7. 🔍 值得关注的客观信号
列出后续可观察的客观量价信号(如某均线得失、某压力位能否放量突破、量能变化),**不附任何操作结论**。

## 准则

1. 数据说话:每个判断引用具体数值,严禁空泛套话
2. 客观中立:只陈述状态与风险,不输出任何交易指令
3. 简明有密度:总字数 1000-1800 字,便于扫读
4. 无数据的维度直接说明"数据不足",不要编造

## 免责声明
报告末尾附一行:"> ⚠️ 本内容由 AI 基于公开行情数据生成,仅客观陈述持仓状态,不构成任何投资建议或买卖指令。交易有风险,入市需谨慎。"

现在请基于下方数据进行复盘。"""


class HoldingsStandardSkill:
    """标准持仓组合复盘 — 复刻 position_analyzer.py 行为。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        summary = context.get("summary", {})
        holdings = context.get("holdings", [])
        market = context.get("market_snapshot", {})
        concentration = context.get("concentration", {})
        sector_context = context.get("sector_context", {})
        settlement_ctx = context.get("settlement_ctx", {})
        focus = context.get("focus", "")

        max_detail = params.get("max_holdings_detail", 10)
        holdings_to_show = holdings[:max_detail]

        parts: list[str] = [
            f"复盘日期: {date.today().isoformat()}",
            "",
            "## 账户汇总",
            "```json",
            json.dumps(summary, ensure_ascii=False),
            "```",
            "",
            f"## 持仓明细(每只已压缩为摘要,含成本/盈亏/趋势/关键价位/指标,共 {len(holdings)} 只,展示前 {len(holdings_to_show)} 只)",
            "```json",
            json.dumps(holdings_to_show, ensure_ascii=False),
            "```",
            "",
            "## 板块归因(行业/概念按持仓市值占比统计,pct 为占总市值百分比)",
            "```json",
            json.dumps(concentration, ensure_ascii=False),
            "```",
            "",
            "## 持仓板块的全市场强弱对照(关键)",
            "下面只列出持仓涉及的行业/概念,并给出其在当日全市场所有板块中的表现:",
            "- market_avg_pct:该板块当日全市场成分股平均涨幅",
            "- rank/total:该板块在全市场所有板块按平均涨幅的排名(1=最强)",
            "- is_leading/is_lagging:是否处于全市场领涨/领跌前列",
            "- leader_name/leader_pct:该板块当日龙头股及其涨幅",
            "- holding_pct:该板块占持仓总市值比例",
            "据此可客观判断:持仓是押在当日强势板块还是弱势板块。",
            "```json",
            json.dumps(sector_context, ensure_ascii=False),
            "```",
            "",
            "## 交割单数据(真实成交记录的已实现盈亏/费用/月度表现/对账异常)",
            "```json",
            json.dumps(settlement_ctx, ensure_ascii=False),
            "```",
            "",
            "## 大盘环境(看板页数据:指数/情绪雷达/涨跌分布/连板梯队/活跃度/领涨领跌板块)",
            "```json",
            json.dumps(market, ensure_ascii=False),
            "```",
        ]

        if focus:
            parts.extend(["", f"本次复盘请特别关注: {focus}"])

        return "\n".join(parts)