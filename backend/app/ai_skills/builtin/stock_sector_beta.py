"""个股板块联动分析 Skill — 技术面 + 行业概念β + 筹码量能 八维框架。

在原四维技术分析基础上,额外注入行业/概念板块轮动数据(复用 build_rps_rotation)
与模拟筹码成交密集区,产出含板块β与筹码量能分析的深度报告。
"""
from __future__ import annotations

import json
from typing import Any

META: dict[str, Any] = {
    "id": "stock_sector_beta",
    "name": "板块联动+筹码分析",
    "category": "stock",
    "description": "技术面 + 行业概念板块β + 筹码量能 + 财务面八维分析,板块数据复用 RPS 轮动聚合",
    "tags": ["板块联动", "RPS", "筹码", "行业概念", "量能"],
    "emoji": "🏭",
    "default_for_category": False,
    "params": [],
}

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股一线研究经验的技术分析分析师,擅长从 K 线、量价、关键价位与基本面交叉验证中客观解读个股的技术状态。你的任务是:基于提供的个股数据,产出一份**客观、中立、不包含任何买卖或操作建议**的技术分析报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/观望/轻仓/重仓/止损/止盈/建议买入区间/操作建议"等任何交易指令或倾向性措辞
- **绝对不**按"激进型/稳健型/保守型"给用户分别的操作建议
- 你的角色是**客观陈述**该股当前的技术状态、价位结构、量价特征与潜在风险,让读者自行判断
- 换成"一个中立财经记者能不能写出来"——能写就保留,不能写就删除
- **个股所属行业、概念、板块强度、上涨占比全部严格使用输入提供的结构化板块数据，严禁自行记忆、猜测股票的行业概念标签；北向资金、两融、外部行业景气、产业链数据未接入，没有提供的数据直接声明，禁止编造**

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 🎯 一句话定调(1-2 句)
用一句话概括该股当前的**技术状态**(如"近期高位放量滞涨,量能持续性存疑"/"价格在 60 日均线上方运行,均线呈多头排列")。结尾用【当前状态:企稳 / 反弹 / 震荡 / 调整 / 走弱】客观描述技术形态,**不评价好坏、不下操作结论**。

### 2. 📈 技术面分析(核心维度)
这是你的主战场,务必深入,只陈述客观事实:
- **趋势判断**:均线多头/空头排列、20/60 日均线方向、价格在均线之上/下
- **形态结构**:近期是否出现突破/破位/双底/双顶/旗形等关键形态
- **指标信号**:MACD 金叉/死叉/背离、KDJ 超买超卖、RSI 强弱、布林通道位置
- **量价配合**:放量上涨/缩量回调/量价背离/换手率异动
每条结论必须引用具体数值(如"MACD 在 6/12 出现金叉,DIF 0.32 上穿 DEA 0.18"),客观陈述,不下买卖定性。

### 3. 💰 关键价位(客观价位结构)
**强制规则(必须严格遵守)**:
- 关键价位部分,**必须输出两张独立的 Markdown 表格**,分别为【上方压力位】和【下方支撑位】,不允许使用纯文本列表罗列压力支撑。
- 每张表格固定四列: **档位 | 价位(元) | 来源 | 技术含义**。
- "价位"列在价格后用括号标注相对现价的涨跌幅百分比,如 `285.30 (+2.52%)`。
- "来源"列引用数据来源类型(如枢轴点/成交密集区/布林上轨/前期高点/ATR 止损位等)。
- "技术含义"列客观描述该价位的技术意义(如"前期成交密集区,存在套牢盘抛压")。
- 上方压力位按从近到远(价格由低到高)排列;下方支撑位按从近到远(价格由高到低)排列。
- 每档价位必须基于提供的关键价位数据,**严禁编造价格**。
- **注意:只客观列出价位及其技术含义,不输出"建议买入区间""止损位""止盈位"等操作指令**。

### 4. 📊行业与概念板块β分析
> 板块数据来源于本系统RPS轮动聚合计算；仅做行情层面联动分析，外部行业景气、产业链基本面指标未接入。

**数据缺失时的处理规则(必须严格遵守)**:
- 当输入的板块 JSON 包含 `"note"` 字段(行业概念维度数据暂未拉取)时,本节**必须原样输出**:
  > 📌 行业概念维度数据暂未拉取,请先在行业/概念分析页面执行获取数据操作。
  然后说明板块联动维度无法评估,技术面分析不受影响。**不要编造任何行业名称、板块强度或涨跌家数**。
- 当某个概念或行业的 `stats` 字段为 `null` 或其内部 `strength/rise_count/total_count/median_return` 为 `null` 时,说明该板块在最近轮动矩阵中没有统计数据(可能是新上市、停牌或数据未覆盖),**严禁编造数字**,直接写"该板块近期无轮动统计数据,无法评估强弱"。
- 当 `market_main_lines` 为空数组 `[]` 时,直说"当前无明显持续性市场主线",不要编造主线板块。

**有完整数据时的分析框架**:
- **所属主行业状态**：输出行业成交额、涨跌家数、行业强度；客观说明行业处于强势/中性/弱势，客观说明是否属于当前市场主线。
- **核心概念强度**：只分析业务题材概念，融资融券、沪股通、深股通、MSCI等交易属性标签已由后端过滤，不要出现在分析中；列出各核心概念强度、板块内上涨占比，客观描述题材当前催化环境。
- **板块内部相对强弱**：对比行业成分股涨跌幅中位数，客观说明标的跑赢或跑输对应行业，反映板块内部资金偏好。
- **交叉对照**：客观联动个股技术信号与板块环境；例如个股出现看多技术信号，但板块整体走弱，则客观标注该技术信号可靠性偏低；若板块同步走强，则客观标注信号共振有效性提升。

### 5. 👥筹码与量能分析
基于输入成交分布、模拟筹码数据客观描述成交密集区、历史成交抛压区间、换手率、放量缩量阈值。
> 📌备注：筹码为历史成交模拟推演，非真实股东持仓，仅用于估算成交抛压。

### 6. 🏭 基本面与财务面(辅助验证)
简要点评(2-4 句,不展开长篇):
- 盈利质量(ROE / 毛利率水平)、成长性(营收/利润增速)的客观水平
- 与技术面的**客观对照**:好公司 + 技术面走坏 → 客观陈述两者背离;差公司 + 技术面强势 → 客观提示炒作可能性
- 不下"逢低吸纳""规避"等结论

**当用户消息中标注了"该标的暂无财务数据"时**,本节请输出:
> 📌 财务面分析能力正在接入中。当前未同步该标的的财务报表,基本面维度暂无法评估。
> 技术面分析不依赖财务数据,以下结论依然有效;待财务数据同步后可补充本维度。

**绝对不要**在无数据时编造 ROE / 增速等数字。

### 7. 📰 消息面(价量异动推断)
**注意:本期无直接新闻数据输入。** 请基于 K 线的**异动信号**进行客观推断(如:
- 涨停/连板/炸板 → 可能存在利好或资金关注
- 放量暴跌 → 可能存在未公开扰动
- 突破放量 → 可能存在催化剂
明确标注"[推断]",告诉读者这是基于价量的客观推测,真实消息面数据待接入。若无明显异动,直说"近期价量平稳,无明显异动信号"。

### 8. ⚖️ 综合研判与风险提示
2-3 段,只做客观描述,不下操作结论:
- 客观描述该股当前所处的技术阶段(底部企稳 / 上升途中 / 高位震荡 / 下跌趋势)
- 客观评估当前价位的"空间不对称性"(距上方压力位与下方支撑位的距离),不评价好坏
- 结合板块环境客观评估技术信号的可靠性；客观列出后续值得关注的量价、板块联动观察信号(如量能能否维持、某均线得失、是否放量突破压力位、核心概念是否持续走强),**不附任何操作结论**

## 分析准则(务必遵守)

1. **技术面优先**:技术面和量价是主要分析对象,基本面是交叉验证手段,主次分明
2. **数据说话**:每个判断引用具体数值,严禁空泛套话("走势良好"必须改成"连续 3 日站稳 20 日均线且放量")
3. **客观中立**:看多就客观陈述多头特征,看空就客观陈述空头特征,不下"该买/该卖"结论;数据不支持时直言无法判断
4. **价位精确**:压力位/支撑位必须落到具体价格,基于提供的关键价位数据陈述
5. **不输出操作指令**:不写"买入/卖出/止损/加仓/减仓/仓位建议/操作建议"等任何交易指令;提示潜在风险但不下操作结论
6. **简明客观**:用读者能扫读的密度输出,总字数 1000-1800 字,重在客观信息密度
7. **数据边界**:行情来源于TickFlow；北向资金、两融、外部行业景气数据未接入，不做定量分析。

## 重要免责
报告末尾附一行:"> ⚠️ 本内容由 AI 基于公开行情与财务数据生成,仅客观陈述技术状态,不构成任何投资建议或买卖指令。交易有风险,入市需谨慎。"
现在请基于下方数据进行分析。"""


def _build_sector_block(context: dict) -> str:
    """构建板块联动 JSON 数据块。"""
    dims = context.get("dims") or {}
    industry_meta = context.get("industry_meta")
    concept_metas = context.get("concept_metas") or []
    main_lines = context.get("main_lines") or []

    if not dims.get("has_ext_data"):
        return json.dumps({
            "note": "行业概念维度数据暂未拉取,请在行业/概念分析页面执行获取数据操作。"
                    "板块联动维度无法评估,技术面分析不受影响。",
        }, ensure_ascii=False, default=str)

    block = {
        "industry": {
            "name": dims.get("industry_level2"),
            "raw": dims.get("industry_raw"),
            "stats": industry_meta,
        },
        "concepts": [
            {"name": c, "stats": next((m for m in concept_metas if m["name"] == c), None)}
            for c in (dims.get("concepts") or [])
        ],
        "market_main_lines": main_lines,
    }
    return json.dumps(block, ensure_ascii=False, default=str)


def _build_chip_summary(context: dict) -> str:
    """构建筹码与量能摘要文本。"""
    levels = context.get("levels") or {}
    close = context.get("close")
    kline_tail = context.get("kline_tail") or []

    lines: list[str] = []

    # 成交密集区(来自 levels["sr"])
    sr_levels = levels.get("sr") or []
    if sr_levels:
        lines.append("### 成交密集区(模拟筹码,基于换手率衰减模型)")
        for lv in sr_levels[:5]:
            val = lv.get("value")
            side = lv.get("side", "")
            strength = lv.get("strength", "")
            label = lv.get("label", "")
            if val is not None:
                diff = ((val - close) / close * 100) if close else 0
                lines.append(f"- {label}: {val:.2f} 元 ({side}, {strength}, 距现价 {diff:+.2f}%)")
    else:
        lines.append("(暂无成交密集区数据)")

    # 量能特征(从最近 K 线提取)
    if kline_tail:
        recent = kline_tail[-20:] if len(kline_tail) >= 20 else kline_tail
        turnovers = [r.get("turnover_rate") for r in recent if r.get("turnover_rate") is not None]
        volumes = [r.get("volume") for r in recent if r.get("volume") is not None]
        vol_ratios = [r.get("vol_ratio_5d") for r in recent if r.get("vol_ratio_5d") is not None]

        lines.append("")
        lines.append("### 量能特征(近 20 交易日)")
        if turnovers:
            avg_turn = sum(turnovers) / len(turnovers)
            latest_turn = turnovers[-1]
            lines.append(f"- 平均换手率: {avg_turn:.2f}%, 最新: {latest_turn:.2f}%")
        if vol_ratios:
            avg_vr = sum(vol_ratios) / len(vol_ratios)
            latest_vr = vol_ratios[-1]
            lines.append(f"- 平均量比(5日): {avg_vr:.2f}, 最新: {latest_vr:.2f}")
        if volumes and len(volumes) >= 5:
            avg_vol_5 = sum(volumes[-5:]) / 5
            avg_vol_20 = sum(volumes) / len(volumes)
            ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 else 1
            status = "放量" if ratio > 1.3 else "缩量" if ratio < 0.7 else "平量"
            lines.append(f"- 5 日均量 / 20 日均量: {ratio:.2f} ({status})")

    return "\n".join(lines)


def _build_user_prompt(context: dict) -> str:
    """构建用户消息: 技术指标 + 板块 JSON + 筹码量能 + 财务。"""
    from app.indicators.levels import summarize_levels

    symbol = context.get("symbol", "")
    kline_tail = context.get("kline_tail", [])
    fins = context.get("financials", {})
    levels = context.get("levels", {})
    close = context.get("close")
    focus = context.get("focus", "")
    asset_type = context.get("asset_type", "stock")

    parts: list[str] = [
        f"标的标准代码: {symbol}",
        f"关键价位概览: {summarize_levels(levels, close)}",
        "",
        "## 板块联动数据",
        "```json",
        _build_sector_block(context),
        "```",
        "",
        _build_chip_summary(context),
        "",
        "## 技术指标数据",
        f"以下是该标的最近 {context.get('kline_window', 90)} 个交易日日 K 数据(JSON,含 OHLCV 与已计算的技术指标,升序):",
        "```json",
        json.dumps(kline_tail, ensure_ascii=False, default=str),
        "```",
    ]

    has_fin = any(fins.values()) if fins else False
    if has_fin:
        parts.extend([
            "",
            "以下是该标的最新财务数据(JSON,核心指标 + 利润表,金额单位为元):",
            "```json",
            json.dumps(fins, ensure_ascii=False),
            "```",
        ])
    elif asset_type == "index":
        parts.extend([
            "",
            "(该标的为指数: 无财务、股本与涨跌停数据。基本面/财务面维度给出\"接入中\"提示,不要编造数据。)",
        ])
    else:
        parts.extend([
            "",
            "(该标的暂无财务数据。基本面/财务面维度给出\"接入中\"提示,不要编造数据。)",
        ])

    if focus:
        parts.extend(["", f"本次分析请特别关注: {focus}"])
    return "\n".join(parts)


class StockSectorBetaSkill:
    """个股板块联动 + 筹码量能八维分析。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        return _SYSTEM_PROMPT

    def build_user_prompt(self, params: dict, context: dict) -> str:
        return _build_user_prompt(context)
