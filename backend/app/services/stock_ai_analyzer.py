"""个股 AI 技术分析流式服务 — 技术面 + 板块联动。

与 stock_analyzer.py 的区别:
  - 本模块额外注入行业/概念板块数据(所属板块、板块强度、市场主线),
    让 AI 从"个股技术面 + 板块轮动环境"两个维度交叉分析。
  - 板块统计全部复用 build_rps_rotation 的 120s 缓存, 禁止自行聚合。
  - 行业统一取二级(level=2), 与前端行业分析页口径一致。

数据流:
  DuckDB ext_data 视图 → symbol 的行业/概念字符串 → split/filter
  build_rps_rotation(repo, 12, "industry"/"concept") → 轮动矩阵
  extract_block_meta() / get_current_main_line() → 结构化板块 JSON
  _load_kline() + compute_levels() → 技术指标 + 关键价位
  → 拼装 prompt → stream_ai_text() → NDJSON 流式输出
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.indicators.levels import compute_levels, summarize_levels

logger = logging.getLogger(__name__)

# 注入最近多少根日 K
_KLINE_WINDOW = 90

# 概念黑名单: 这些是宽基/交易属性标签, 不具板块分析价值, 后端直接过滤
_CONCEPT_BLACKLIST = {
    "融资融券", "沪股通", "深股通", "MSCI", "机构重仓", "上证科创板50成份",
}

# 轮动矩阵天数
_ROTATION_DAYS = 12


# ================================================================
# 1. 行业 / 概念成分查询(DuckDB 视图, 不新建 parquet)
# ================================================================

def _query_ext_dimension(repo, symbol: str, view_name: str, dim_column: str,
                         config_id: str) -> str | None:
    """从 DuckDB ext_data 视图查询某只股票的维度原始字符串。

    优先查询 DuckDB 视图(ext_ext_gn_ths / ext_ext_hy_ths,由 ext_data 写入后
    自动注册);若视图不存在(如独立测试环境或刚启动未拉取过 ext 数据),
    回退到直接读取 parquet 文件,保证可用性。

    Args:
        repo: KlineRepository (含 db DuckDB 连接)。
        symbol: 标的代码, 如 "300666.SZ"。
        view_name: DuckDB 视图名, 如 "ext_ext_gn_ths"。
        dim_column: 维度列名, 如 "所属概念" / "所属同花顺行业"。
        config_id: ext_data 配置 ID, 用于回退读 parquet。

    Returns:
        原始维度字符串 (分号/横杠拼接), 查询不到返回 None。
    """
    # 优先走 DuckDB 视图
    try:
        row = repo.execute_one(
            f'SELECT "{dim_column}" FROM {view_name} WHERE upper(symbol) = upper(?) LIMIT 1',
            [symbol],
        )
        if row and row[0]:
            return str(row[0])
    except Exception:
        # 视图未注册, 降级读 parquet
        logger.debug("view %s not available, fallback to parquet", view_name, exc_info=True)

    # 回退: 直接读 ext_data parquet 文件(与 ext_data._refresh_views 注册逻辑同源)
    try:
        parquet_path = repo.store.data_dir / "ext_data" / config_id / "part.parquet"
        if not parquet_path.exists():
            return None
        df = pl.read_parquet(str(parquet_path))
        if df.is_empty() or dim_column not in df.columns or "symbol" not in df.columns:
            return None
        hit = df.filter(pl.col("symbol").str.to_uppercase() == symbol.upper())
        if hit.is_empty():
            return None
        val = hit[dim_column][0]
        return str(val) if val else None
    except Exception:
        logger.debug("read parquet for %s failed", config_id, exc_info=True)
        return None


def _load_symbol_dimensions(repo, symbol: str) -> dict[str, Any]:
    """加载个股的行业(三级→二级)和概念(过滤黑名单)。

    Returns:
        {
          "industry_raw": "银行-银行-股份制银行" | None,
          "industry_level2": "银行" | None,
          "concepts_raw": "人工智能;芯片" | None,
          "concepts": ["人工智能", "芯片"] | None,   # 已过滤黑名单
          "has_ext_data": bool,  # 是否成功拉取到行业/概念数据
        }
    """
    industry_raw = _query_ext_dimension(repo, symbol, "ext_ext_hy_ths", "所属同花顺行业", "ext_hy_ths")
    concepts_raw = _query_ext_dimension(repo, symbol, "ext_ext_gn_ths", "所属概念", "ext_gn_ths")

    industry_level2 = None
    if industry_raw:
        parts = industry_raw.split("-")
        # level=2 取第二段; 不足两段时取最后一段兜底
        industry_level2 = parts[1] if len(parts) >= 2 else parts[-1]

    concepts: list[str] | None = None
    if concepts_raw:
        concepts = [
            c.strip()
            for c in concepts_raw.split(";")
            if c.strip() and c.strip() not in _CONCEPT_BLACKLIST
        ]

    has_ext_data = bool(industry_raw or concepts_raw)
    return {
        "industry_raw": industry_raw,
        "industry_level2": industry_level2,
        "concepts_raw": concepts_raw,
        "concepts": concepts,
        "has_ext_data": has_ext_data,
    }


# ================================================================
# 2. 板块元数据提取(从 build_rps_rotation 结果中提取)
# ================================================================

def extract_block_meta(rotation_matrix: dict, block_name: str) -> dict[str, Any]:
    """从轮动矩阵中提取指定板块的强度、涨跌统计、涨跌幅中位数。

    复用 build_rps_rotation 输出, 不自行聚合。

    Args:
        rotation_matrix: build_rps_rotation() 返回值。
            结构: {dates: [...], columns: {date: [[block, avg_pct], ...]}, concept_count}
        block_name: 板块名称(行业二级名或概念名)。

    Returns:
        {
          "name": 板块名,
          "strength": 最新日涨幅小数 | None,   # 板块强度(最新日 avg_pct)
          "rise_count": int | None,           # 矩阵中有数据的天数(上涨天数)
          "total_count": int | None,          # 矩阵总天数(该板块出现的总天数)
          "median_return": float | None,      # 区间涨跌幅中位数
        }
        板块不在矩阵中时, 数值字段全部为 None, 不编造数据。
    """
    columns = rotation_matrix.get("columns") or {}
    dates = rotation_matrix.get("dates") or []

    pcts: list[float] = []
    for d in dates:
        col = columns.get(d) or []
        for name, pct in col:
            if name == block_name:
                try:
                    pcts.append(float(pct))
                except (TypeError, ValueError):
                    pass
                break

    if not pcts:
        return {
            "name": block_name,
            "strength": None,
            "rise_count": None,
            "total_count": None,
            "median_return": None,
        }

    sorted_pcts = sorted(pcts)
    n = len(sorted_pcts)
    median = sorted_pcts[n // 2] if n % 2 == 1 else (sorted_pcts[n // 2 - 1] + sorted_pcts[n // 2]) / 2

    return {
        "name": block_name,
        "strength": round(pcts[0], 4),  # dates[0] 是最新日
        "rise_count": sum(1 for p in pcts if p > 0),
        "total_count": n,
        "median_return": round(median, 4),
    }


# ================================================================
# 3. 市场主线提取(复用 concept_rotation_analyzer 的信号计算)
# ================================================================

def get_current_main_line(rotation_matrix: dict, top_n: int = 5) -> list[dict]:
    """从轮动矩阵提取当前市场主线板块列表。

    复用 concept_rotation_analyzer._compute_rotation_signals 的 persistent_leaders
    逻辑(连续多日稳居前列的板块), 提取主线名称 + 近 3 日平均排名。

    Args:
        rotation_matrix: build_rps_rotation() 返回值。
        top_n: 最多返回多少个主线板块。

    Returns:
        [{"name": "板块名", "avg_rank": 3.2, "latest_rank": 1, "recent_pcts": [0.05, ...]}]
        无数据时返回空列表。
    """
    from app.services.concept_rotation_analyzer import _compute_rotation_signals

    dates = rotation_matrix.get("dates") or []
    columns = rotation_matrix.get("columns") or []

    if not dates or not columns:
        return []

    signals = _compute_rotation_signals(dates, columns)
    leaders = signals.get("persistent_leaders", []) or []

    result = []
    for leader in leaders[:top_n]:
        ranks = leader.get("ranks") or []
        pcts = leader.get("pcts") or []
        # ranks 是按 dates_asc (旧→新) 排列, 最新在末尾
        latest_rank = ranks[-1] if ranks else None
        recent_pcts = pcts[-3:] if len(pcts) >= 3 else pcts
        result.append({
            "name": leader.get("concept", ""),
            "avg_rank": leader.get("avg_rank"),
            "latest_rank": latest_rank,
            "recent_pcts": recent_pcts,
        })
    return result


# ================================================================
# 4. K 线 + 技术指标加载(复用 stock_analyzer 逻辑)
# ================================================================

def _load_kline(repo, symbol: str) -> pl.DataFrame:
    """读取该标的最近 N 根日 K(已含技术指标 / 信号)。"""
    end = date.today()
    start = end - timedelta(days=_KLINE_WINDOW * 2)
    df = repo.get_daily_asset(repo.resolve_asset_type(symbol), symbol, start, end)
    if df.is_empty():
        return df
    return df.tail(_KLINE_WINDOW)


def _clean_rows(df: pl.DataFrame, keep_cols: list[str]) -> list[dict]:
    """DataFrame → JSON 安全 dict 列表(清洗 NaN/Inf + date→ISO 字符串)。"""
    import datetime
    import math

    cols = [c for c in keep_cols if c in df.columns]
    sub = df.select(cols)
    rows = []
    for rec in sub.to_dicts():
        clean = {}
        for k, v in rec.items():
            if isinstance(v, float):
                clean[k] = None if not math.isfinite(v) else round(v, 4)
            elif isinstance(v, (datetime.date, datetime.datetime)):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        rows.append(clean)
    return rows


_KLINE_KEEP_COLS = [
    "date", "open", "high", "low", "close", "volume", "change_pct",
    "ma5", "ma10", "ma20", "ma60",
    "macd_dif", "macd_dea", "macd_hist",
    "kdj_k", "kdj_d", "kdj_j",
    "rsi_6", "rsi_14", "rsi_24",
    "boll_upper", "boll_mid", "boll_lower",
    "atr_14", "vol_ratio_5d", "turnover_rate",
    "consecutive_limit_ups",
    "signal_limit_up", "signal_macd_golden", "signal_macd_death",
    "signal_ma_golden_5_20", "signal_volume_surge",
    "signal_boll_breakout_upper", "signal_boll_breakout_lower",
]


# ================================================================
# 5. System Prompt (完整定义, 不修改规则/章节/红线)
# ================================================================

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股一线研究经验的技术分析分析师,擅长从 K 线、量价、关键价位与板块轮动环境的交叉验证中客观解读个股的技术状态。你的任务是:基于提供的个股技术数据与板块联动数据,产出一份**客观、中立、不包含任何买卖或操作建议**的技术分析报告。

## 核心红线(务必遵守)

- **绝对不输出**"买入/卖出/加仓/减仓/观望/轻仓/重仓/止损/止盈/建议买入区间/操作建议"等任何交易指令或倾向性措辞
- **绝对不**按"激进型/稳健型/保守型"给用户分别的操作建议
- 你的角色是**客观陈述**该股当前的技术状态、价位结构、量价特征、板块环境与潜在风险,让读者自行判断
- 换成"一个中立财经记者能不能写出来"——能写就保留,不能写就删除

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 🎯 一句话定调(1-2 句)
用一句话概括该股当前的**技术状态**(如"近期高位放量滞涨,所属半导体板块同步走强,量价共振但持续性存疑"/"价格在 60 日均线上方运行,均线呈多头排列,所属银行板块偏弱").结尾用【当前状态:企稳 / 反弹 / 震荡 / 调整 / 走弱】客观描述技术形态,**不评价好坏、不下操作结论**。

### 2. 📈 技术面分析(核心维度)
这是你的主战场,务必深入,只陈述客观事实:
- **趋势判断**:均线多头/空头排列、20/60 日均线方向、价格在均线之上/下
- **形态结构**:近期是否出现突破/破位/双底/双顶/旗形等关键形态
- **指标信号**:MACD 金叉/死叉/背离、KDJ 超买超卖、RSI 强弱、布林通道位置
- **量价配合**:放量上涨/缩量回调/量价背离/换手率异动
每条结论必须引用具体数值(如"MACD 在 6/12 出现金叉,DIF 0.32 上穿 DEA 0.18"),客观陈述,不下买卖定性。

### 3. 🏭 板块联动分析(基于提供的板块数据)
基于提供的行业/概念板块数据,客观分析:
- **所属行业**:行业名称 + 当前板块强度(引用 strength/median_return 具体数值)
- **所属概念**:列出核心概念,逐个引用其板块强度数据
- **市场主线**:该股所属概念是否出现在当前市场主线列表中;若在,客观描述主线对个股的带动效应;若不在,客观说明个股独立于主线运行
- **板块强弱对比**:该股近期涨跌幅与所属板块中位数对比,客观判断是板块带动还是个股独立行情
- **当板块数据字段为 null 时**,直说"板块数据暂未拉取,本维度无法评估",**不要编造数字**

### 4. 💰 关键价位(客观价位结构)
基于提供的关键价位数据,客观列出价位结构:
- **上方压力位**(逐档列出,标注来源):第一压力、第二压力
- **下方支撑位**(逐档列出,标注来源):第一支撑、第二支撑
- 用数据说话,引用提供的压力/支撑(成交密集区)/枢轴点数值
- **注意:只客观列出价位及其技术含义(如"此处为前期成交密集区"),不输出"建议买入区间""止损位""止盈位"等操作指令**

### 5. 📰 消息面(价量异动推断)
**注意:本期无直接新闻数据输入。** 请基于 K 线的**异动信号**进行客观推断(如:
- 涨停/连板/炸板 → 可能存在利好或资金关注
- 放量暴跌 → 可能存在未公开扰动
- 突破放量 → 可能存在催化剂
明确标注"[推断]",告诉读者这是基于价量的客观推测,真实消息面数据待接入。若无明显异动,直说"近期价量平稳,无明显异动信号"。

### 6. ⚖️ 综合研判与风险提示
2-3 段,只做客观描述,不下操作结论:
- 客观描述该股当前所处的技术阶段(底部企稳 / 上升途中 / 高位震荡 / 下跌趋势)
- 结合板块环境客观评估"板块共振 vs 独立行情"
- 客观评估当前价位的"空间不对称性"(距上方压力位与下方支撑位的距离),不评价好坏
- 客观列出后续值得关注的量价信号(如量能能否维持、某均线得失、是否放量突破压力位),**不附任何操作结论**

## 分析准则(务必遵守)

1. **技术面优先,板块为辅**:技术面和量价是主要分析对象,板块联动是交叉验证手段,主次分明
2. **数据说话**:每个判断引用具体数值,严禁空泛套话("走势良好"必须改成"连续 3 日站稳 20 日均线且放量")
3. **客观中立**:看多就客观陈述多头特征,看空就客观陈述空头特征,不下"该买/该卖"结论;数据不支持时直言无法判断
4. **价位精确**:压力位/支撑位必须落到具体价格,基于提供的关键价位数据陈述
5. **不输出操作指令**:不写"买入/卖出/止损/加仓/减仓/仓位建议/操作建议"等任何交易指令;提示潜在风险但不下操作结论
6. **板块数据不编造**:板块字段为 null 时直说数据未拉取,不要虚构板块名称或强度数字
7. **简明客观**:用读者能扫读的密度输出,总字数 1000-1800 字,重在客观信息密度

## 重要免责
报告末尾附一行:"> ⚠️ 本内容由 AI 基于公开行情与板块数据生成,仅客观陈述技术状态,不构成任何投资建议或买卖指令。交易有风险,入市需谨慎。"

现在请基于下方数据进行分析。"""


# ================================================================
# 6. 用户消息构建
# ================================================================

def _build_user_prompt(
    symbol: str,
    kline_tail: list[dict],
    levels: dict[str, list[dict]],
    close: float | None,
    dims: dict,
    industry_meta: dict | None,
    concept_metas: list[dict],
    main_lines: list[dict],
    focus: str,
) -> str:
    """组装 user prompt: 标的 + 技术指标 JSON + 板块结构化 JSON + 关注点。"""
    parts: list[str] = [
        f"标的标准代码: {symbol}",
        f"关键价位概览: {summarize_levels(levels, close)}",
        "",
    ]

    # 板块联动数据(结构化 JSON)
    sector_block: dict[str, Any] = {}
    if dims["has_ext_data"]:
        sector_block["industry"] = {
            "name": dims["industry_level2"],
            "raw": dims["industry_raw"],
            "stats": industry_meta,
        }
        sector_block["concepts"] = [
            {"name": c, "stats": next((m for m in concept_metas if m["name"] == c), None)}
            for c in (dims["concepts"] or [])
        ]
        sector_block["market_main_lines"] = main_lines
    else:
        sector_block["note"] = (
            "行业概念维度数据暂未拉取,请在行业/概念分析页面执行获取数据操作。"
            "板块联动维度无法评估,技术面分析不受影响。"
        )

    parts.extend([
        "## 板块联动数据",
        "```json",
        json.dumps(sector_block, ensure_ascii=False, default=str),
        "```",
        "",
        "## 技术指标数据",
        f"以下是该标的最近 {_KLINE_WINDOW} 个交易日日 K 数据(JSON,含 OHLCV 与已计算的技术指标,升序):",
        "```json",
        json.dumps(kline_tail, ensure_ascii=False, default=str),
        "```",
    ])

    from app.services.ai_provider import sanitize_focus
    safe_focus = sanitize_focus(focus)
    if safe_focus:
        parts.extend(["", f"本次分析请特别关注: {safe_focus}"])

    return "\n".join(parts)


def _build_meta_summary(dims: dict, industry_meta: dict | None, main_lines: list[dict]) -> str:
    """构建 meta 事件的摘要文本(前端立即展示)。"""
    parts = []
    if dims["industry_level2"]:
        strength = industry_meta.get("strength") if industry_meta else None
        if strength is not None:
            parts.append(f"行业: {dims['industry_level2']} ({strength*100:+.2f}%)")
        else:
            parts.append(f"行业: {dims['industry_level2']}")
    if dims["concepts"]:
        parts.append(f"概念: {len(dims['concepts'])} 个")
    if main_lines:
        leader_names = "、".join(ml["name"] for ml in main_lines[:3])
        parts.append(f"主线: {leader_names}")
    if not parts:
        parts.append("技术面分析")
    return " | ".join(parts)


# ================================================================
# 7. 流式主入口
# ================================================================

async def analyze_stock_ai_stream(
    repo,
    symbol: str,
    focus: str = "",
) -> AsyncIterator[str]:
    """流式个股 AI 技术分析(含板块联动): yield 出每个 NDJSON 事件。

    协议(与 /api/rps/rotation-analyze 完全对齐):
      {"type":"meta","symbol","summary"}
      {"type":"delta","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}

    Args:
        repo: KlineRepository(含 db 连接 + enriched 缓存)。
        symbol: 标的代码,如 "300666.SZ"。
        focus: 用户追加的分析关注点。
    """
    from app.services.rps_rotation import build_rps_rotation

    try:
        # 1. 加载 K 线 + 技术指标
        df = _load_kline(repo, symbol)
        if df.is_empty():
            yield json.dumps({
                "type": "error",
                "message": f"标的 {symbol} 暂无日 K 数据,请先同步",
            }, ensure_ascii=False)
            return

        levels = compute_levels(df)
        close = float(df.tail(1)["close"][0]) if "close" in df.columns else None
        kline_tail = _clean_rows(df, _KLINE_KEEP_COLS)

        # 2. 查询行业/概念(DuckDB 视图;查不到则全部 None,不阻断)
        dims = _load_symbol_dimensions(repo, symbol)

        # 3. 获取轮动矩阵(复用 build_rps_rotation 的 120s 缓存)
        #    任何一个矩阵获取失败都降级为空,不阻断整体流程
        try:
            rotation_industry = build_rps_rotation(repo, _ROTATION_DAYS, "industry", 2)
        except Exception:
            logger.warning("build_rps_rotation industry failed for %s", symbol, exc_info=True)
            rotation_industry = {"dates": [], "columns": {}, "concept_count": 0}

        try:
            rotation_concept = build_rps_rotation(repo, _ROTATION_DAYS, "concept")
        except Exception:
            logger.warning("build_rps_rotation concept failed for %s", symbol, exc_info=True)
            rotation_concept = {"dates": [], "columns": {}, "concept_count": 0}

        # 4. 提取板块元数据(板块不在矩阵中 → 全部 null, 不编造)
        industry_meta = None
        if dims["industry_level2"]:
            industry_meta = extract_block_meta(rotation_industry, dims["industry_level2"])

        concept_metas: list[dict] = []
        if dims["concepts"]:
            for concept_name in dims["concepts"][:15]:  # 限制 token, 最多取 15 个概念
                meta = extract_block_meta(rotation_concept, concept_name)
                if meta["strength"] is not None:
                    concept_metas.append(meta)
            # 按最新日强度降序, 优先展示强势概念
            concept_metas.sort(key=lambda x: x["strength"] or -999, reverse=True)

        # 5. 提取市场主线(复用 concept_rotation_analyzer 信号逻辑)
        main_lines: list[dict] = []
        try:
            main_lines = get_current_main_line(rotation_concept, top_n=5)
        except Exception:
            logger.warning("get_current_main_line failed for %s", symbol, exc_info=True)

        # 6. meta 事件
        yield json.dumps({
            "type": "meta",
            "symbol": symbol,
            "summary": _build_meta_summary(dims, industry_meta, main_lines),
        }, ensure_ascii=False)

        # 7. 构建 prompt + 流式调用 LLM
        from app.services.ai_provider import stream_ai_text, ai_configured

        if not ai_configured():
            yield json.dumps({
                "type": "error",
                "message": "AI 未配置,请在「设置」页填写 API Key 与接口地址",
            }, ensure_ascii=False)
            return

        user_prompt = _build_user_prompt(
            symbol, kline_tail, levels, close, dims,
            industry_meta, concept_metas, main_lines, focus,
        )

        async for delta in stream_ai_text(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=8192,
        ):
            yield json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)

    except Exception as e:  # noqa: BLE001
        logger.exception("AI stock technical analysis failed for %s: %s", symbol, e)
        yield json.dumps({"type": "error", "message": f"AI 分析失败: {e}"}, ensure_ascii=False)
        return

    yield json.dumps({"type": "done"}, ensure_ascii=False)
