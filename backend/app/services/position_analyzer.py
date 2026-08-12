"""AI 持仓复盘服务 — 账户组合视角的客观复盘。

职责:
  组合当前全部持仓(成本/股数/建仓日)+ 每只标的的最新行情指标 +
  近期日 K 趋势 + 大盘环境 → 拼装组合复盘系统提示词 → 流式调用 LLM。

设计要点:
  - 与 stock_analyzer(单只四维深度分析) 区分:本服务是"账户组合视角",
    逐只只给压缩摘要(不把 N 只 × 90 根 K 线全塞进去,控制 token)。
  - 红线与现有 AI 分析一致:客观陈述,不输出任何买卖/仓位/止损止盈建议。
  - 行业/概念集中度取数成本高,v1 以盈亏分布 + 涨跌结构 + 技术状态聚合替代。

不知道: HTTP、前端、配置持久化。
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, timedelta
from typing import AsyncIterator

import polars as pl

from app.indicators.levels import compute_levels

logger = logging.getLogger(__name__)

# 每只持仓注入最近多少根日 K(仅用于趋势/价位,组合复盘比单只分析更精简)
_KLINE_WINDOW = 30


# ================================================================
# 数据装配
# ================================================================

def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _holding_days(opened_at: str | None) -> int | None:
    if not opened_at:
        return None
    try:
        d = date.fromisoformat(opened_at[:10])
        return (date.today() - d).days
    except (ValueError, TypeError):
        return None


def _trend_tag(df: pl.DataFrame) -> str:
    """从近 N 根 K 线提炼一句客观趋势标签。"""
    if df.is_empty() or "close" not in df.columns or df.height < 5:
        return "数据不足"
    close = df["close"].to_list()
    last = _safe_float(close[-1])
    ma5 = _safe_float(df["ma5"][-1]) if "ma5" in df.columns and df.height >= 5 else None
    ma20 = _safe_float(df["ma20"][-1]) if "ma20" in df.columns and df.height >= 20 else None
    if last is None:
        return "数据不足"
    tags = []
    if ma5 and ma20:
        if last > ma5 > ma20:
            tags.append("均线多头")
        elif last < ma5 < ma20:
            tags.append("均线空头")
        elif last > ma20:
            tags.append("站上MA20")
        else:
            tags.append("跌破MA20")
    # 近 5 日涨跌幅
    prev = _safe_float(close[-6]) if len(close) >= 6 else None
    if prev:
        chg5 = (last - prev) / prev * 100
        tags.append(f"近5日{chg5:+.1f}%")
    return "，".join(tags) if tags else "震荡"


def _summarize_holding(repo, pos: dict, enriched_map: dict) -> dict | None:
    """把一只持仓压缩成一个摘要 dict(用于注入 prompt,控制 token)。"""
    symbol = pos.get("symbol")
    if not symbol:
        return None

    shares = _safe_float(pos.get("shares")) or 0.0
    cost = _safe_float(pos.get("cost_price"))
    enr = enriched_map.get(symbol) or {}
    last = _safe_float(enr.get("close"))

    # 持仓自身数值
    market_value = (last * shares) if last is not None else None
    cost_value = (cost * shares) if cost is not None else None
    pnl_amt = ((last - cost) * shares) if (last is not None and cost is not None) else None
    pnl_pct = ((last - cost) / cost) if (last is not None and cost) else None
    day_pct = _safe_float(enr.get("change_pct"))
    days = _holding_days(pos.get("opened_at"))

    # 趋势 + 关键价位(从近 K 线算,失败则降级只用 enriched)
    asset_type = repo.resolve_asset_type(symbol)
    trend = "数据不足"
    nearest_support = None
    nearest_resistance = None
    try:
        start = date.today()
        df = repo.get_daily_asset(asset_type, symbol, start - timedelta(days=_KLINE_WINDOW * 2), start)
        if not df.is_empty():
            df = df.tail(_KLINE_WINDOW)
            trend = _trend_tag(df)
            levels = compute_levels(df)
            # 从 levels 里挑离现价最近的支撑/压力
            if last is not None:
                supports, resistances = [], []
                for group in levels.values():
                    if not isinstance(group, list):
                        continue
                    for item in group:
                        price = item.get("price") if isinstance(item, dict) else None
                        if price is None:
                            continue
                        if price < last:
                            supports.append(price)
                        elif price > last:
                            resistances.append(price)
                nearest_support = max(supports) if supports else None
                nearest_resistance = min(resistances) if resistances else None
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "summarize_holding: kline/levels failed for %s (name=%s, last=%.2f): %s",
            symbol, enr.get("name", "?"), last or 0, e,
        )

    return {
        "symbol": symbol,
        "name": enr.get("name"),
        "shares": shares,
        "cost_price": cost,
        "last_price": last,
        "market_value": round(market_value, 2) if market_value is not None else None,
        "pnl_amount": round(pnl_amt, 2) if pnl_amt is not None else None,
        "pnl_pct": round(pnl_pct * 100, 2) if pnl_pct is not None else None,
        "day_change_pct": round(day_pct, 2) if day_pct is not None else None,
        "holding_days": days,
        "trend": trend,
        "rsi14": _safe_float(enr.get("rsi_14")),
        "vol_ratio": _safe_float(enr.get("vol_ratio_5d")),
        "ma5": _safe_float(enr.get("ma5")),
        "ma20": _safe_float(enr.get("ma20")),
        "nearest_support": round(nearest_support, 2) if nearest_support else None,
        "nearest_resistance": round(nearest_resistance, 2) if nearest_resistance else None,
        "consecutive_limit_ups": enr.get("consecutive_limit_ups"),
        "note": pos.get("note") or "",
    }


def _build_market_snapshot(repo, quote_service) -> dict:
    """大盘环境快照:复用大盘复盘的 build_market_overview,再压缩成精简结构。

    包含:日期/情绪、主要指数涨跌、涨跌家数与强弱分布、成交额、涨跌停/连板、
    领涨/领跌板块(行业+概念)。这是"持仓 vs 大盘"对照的客观依据。
    任何环节失败都降级返回空结构,不阻断复盘。
    """
    empty = {
        "as_of": None, "emotion": None, "radar": [], "indices": [], "breadth": None,
        "distribution": [], "amount": None, "limit": None, "trend": None, "activity": None,
        "boards": [], "top_gainers": [], "top_losers": [],
        "leading_industries": [], "lagging_industries": [],
        "leading_concepts": [], "lagging_concepts": [],
    }
    try:
        from app.services.market_overview_builder import build_market_overview

        ov = build_market_overview(repo, quote_service=quote_service)
        if not ov or not ov.get("as_of"):
            logger.info("market_snapshot: no as_of, return empty")
            return empty

        logger.info(
            "market_snapshot: as_of=%s, emotion=%s, breadth_up=%.1f%%, indices=%d",
            ov.get("as_of"),
            (ov.get("emotion") or {}).get("label", "?"),
            (ov.get("breadth") or {}).get("up_pct", 0),
            len(ov.get("indices") or []),
        )

        def _rank_items(bucket: list[dict], limit: int = 6) -> list[dict]:
            out = []
            for it in (bucket or [])[:limit]:
                leader = it.get("leader") or {}
                out.append({
                    "name": it.get("name"),
                    "avg_pct": _safe_float(it.get("avg_pct")),
                    "count": it.get("count"),
                    "up_count": it.get("up_count"),
                    "down_count": it.get("down_count"),
                    "leader": leader.get("name"),
                    "leader_pct": _safe_float(leader.get("change_pct")),
                })
            return out

        def _top(rows: list[dict], limit: int = 6) -> list[dict]:
            return [
                {
                    "name": r.get("name"),
                    "change_pct": _safe_float(r.get("change_pct")),
                    "amount": _safe_float(r.get("amount")),
                    "turnover_rate": _safe_float(r.get("turnover_rate")),
                }
                for r in (rows or [])[:limit]
            ]

        lim = ov.get("limit") or {}
        return {
            "as_of": ov.get("as_of"),
            "emotion": ov.get("emotion"),
            "radar": ov.get("radar"),
            "indices": [
                {"name": ix.get("name"), "change_pct": _safe_float(ix.get("change_pct"))}
                for ix in (ov.get("indices") or [])[:6]
            ],
            "breadth": ov.get("breadth"),
            "distribution": ov.get("distribution"),
            "amount": ov.get("amount"),
            "limit": {
                "limit_up": lim.get("limit_up"),
                "limit_down": lim.get("limit_down"),
                "broken": lim.get("broken"),
                "max_boards": lim.get("max_boards"),
                "seal_rate": _safe_float(lim.get("seal_rate")),
                "tiers": [
                    {"boards": t.get("boards"), "count": t.get("count"),
                     "stocks": [s.get("name") for s in (t.get("stocks") or [])[:3]]}
                    for t in (lim.get("tiers") or [])[:5]
                ],
            },
            "trend": ov.get("trend"),
            "activity": ov.get("activity"),
            "boards": [
                {"board": b.get("board"), "up_pct": _safe_float(b.get("up_pct")),
                 "count": b.get("count"), "up": b.get("up"), "down": b.get("down")}
                for b in (ov.get("boards") or [])
            ],
            "top_gainers": _top(ov.get("top_gainers")),
            "top_losers": _top(ov.get("top_losers")),
            "leading_industries": _rank_items((ov.get("industry_rank") or {}).get("leading")),
            "lagging_industries": _rank_items((ov.get("industry_rank") or {}).get("lagging")),
            "leading_concepts": _rank_items((ov.get("concept_rank") or {}).get("leading")),
            "lagging_concepts": _rank_items((ov.get("concept_rank") or {}).get("lagging")),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("position analyze market snapshot failed: %s", e)
        return empty


def _build_portfolio_summary(holdings: list[dict]) -> dict:
    """账户级聚合:总市值/总成本/总盈亏/盈亏分布。"""
    total_mv = sum(h["market_value"] for h in holdings if h.get("market_value"))
    total_cost = sum((h.get("cost_price") or 0) * h.get("shares", 0) for h in holdings)
    total_pnl = sum(h["pnl_amount"] for h in holdings if h.get("pnl_amount") is not None)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None

    winners = [h for h in holdings if (h.get("pnl_pct") or 0) > 0]
    losers = [h for h in holdings if (h.get("pnl_pct") or 0) < 0]
    day_up = [h for h in holdings if (h.get("day_change_pct") or 0) > 0]
    day_down = [h for h in holdings if (h.get("day_change_pct") or 0) < 0]

    top = sorted(holdings, key=lambda h: h.get("pnl_amount") or 0, reverse=True)
    return {
        "count": len(holdings),
        "total_market_value": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2) if total_pnl_pct is not None else None,
        "winners": len(winners),
        "losers": len(losers),
        "day_up": len(day_up),
        "day_down": len(day_down),
        "top_contributors": [
            {"symbol": h["symbol"], "name": h.get("name"), "pnl_amount": h["pnl_amount"], "pnl_pct": h["pnl_pct"]}
            for h in top[:3]
        ],
        "bottom_contributors": [
            {"symbol": h["symbol"], "name": h.get("name"), "pnl_amount": h["pnl_amount"], "pnl_pct": h["pnl_pct"]}
            for h in top[-3:][::-1]
        ],
    }


# ================================================================
# 行业 / 概念集中度(从内置 ext_data 映射归因)
# ================================================================

_DIMENSION_SEP = re.compile(r"[、,，;；|/\s]+")


def _load_ext_dimension(data_dir, config_id: str, field: str) -> dict[str, list[str]]:
    """读取内置 ext parquet(概念/行业),返回 symbol -> 维度值列表。

    行业字段是 "一级-二级-三级" 分级,取一级作为行业归因;概念字段是分号分隔的多值。
    读取失败(未同步数据)返回空 dict,不阻断复盘。
    """
    import polars as pl

    path = data_dir / "ext_data" / config_id / "part.parquet"
    if not path.exists():
        logger.debug("load_dim %s: path not found %s", config_id, path)
        return {}
    try:
        df = pl.read_parquet(path)
        if df.is_empty() or field not in df.columns:
            logger.debug("load_dim %s: empty df or missing field %s", config_id, field)
            return {}
        mapping: dict[str, list[str]] = {}
        for rec in df.select(["symbol", field]).to_dicts():
            sym = rec.get("symbol")
            raw = rec.get(field)
            if not sym or raw is None:
                continue
            values = [v.strip() for v in _DIMENSION_SEP.split(str(raw).strip()) if v.strip()]
            if config_id == "ext_hy_ths":
                # 行业分级 "银行-银行-股份制银行" → 取一级行业
                values = [v.split("-")[0].strip() for v in values if v.strip()]
            mapping[str(sym)] = [v for v in values if v]
        logger.debug("load_dim %s: loaded %d symbols from parquet", config_id, len(mapping))
        return mapping
    except Exception as e:  # noqa: BLE001
        logger.debug("load ext dimension %s failed: %s", config_id, e)
        return {}


def _build_concentration(data_dir, holdings: list[dict]) -> dict:
    """按市值占比统计行业/概念集中度。

    返回 {"industry": [...], "concept": [...], "uncovered": [...]}
    每项按市值占比降序:{"name", "symbols", "mv", "pct"}
    """
    total_mv = sum(h.get("market_value") or 0 for h in holdings)
    if total_mv <= 0:
        logger.info("concentration: total_mv <= 0, skip")
        return {"industry": [], "concept": [], "uncovered": []}

    industry_map = _load_ext_dimension(data_dir, "ext_hy_ths", "所属同花顺行业")
    concept_map = _load_ext_dimension(data_dir, "ext_gn_ths", "所属概念")
    logger.info(
        "concentration: dims loaded, industry_symbols=%d, concept_symbols=%d",
        len(industry_map), len(concept_map),
    )
    uncovered: list[str] = []

    def _aggregate(dim_map: dict[str, list[str]], multi: bool) -> list[dict]:
        bucket: dict[str, dict] = {}
        for h in holdings:
            sym = h.get("symbol")
            mv = h.get("market_value") or 0
            dims = dim_map.get(sym, [])
            if not dims:
                continue
            # 概念多值时市值均摊到每个概念,避免重复计总
            weight = mv / len(dims) if multi else mv
            for d in dims:
                b = bucket.setdefault(d, {"name": d, "symbols": [], "mv": 0.0})
                b["symbols"].append(sym)
                b["mv"] += weight
        out = []
        for b in bucket.values():
            out.append({
                "name": b["name"],
                "symbols": b["symbols"],
                "mv": round(b["mv"], 2),
                "pct": round(b["mv"] / total_mv * 100, 1),
            })
        out.sort(key=lambda x: x["mv"], reverse=True)
        return out

    covered = set(industry_map.keys())
    for h in holdings:
        if h.get("symbol") not in covered:
            uncovered.append(h.get("symbol"))

    return {
        "industry": _aggregate(industry_map, multi=False)[:8],
        "concept": _aggregate(concept_map, multi=True)[:8],
        "uncovered": uncovered,
    }


def _build_sector_context(repo, data_dir, holdings: list[dict]) -> dict:
    """把持仓所属行业/概念放到当日全市场板块强弱中做对照。

    返回:
    {
      "industries": [{"name","holding_mv","holding_pct","market_avg_pct","market_count",
                      "rank","total","leader_name","leader_pct","is_leading","is_lagging"}],
      "concepts":   [同上],
    }
    rank/total 为该板块在全市场所有板块中按平均涨幅的排名(1=最强);
    is_leading/is_lagging 标记是否在全市场领涨/领跌前列。
    数据缺失(未同步 ext 或行情)返回空列表,不阻断复盘。
    """
    try:
        from app.services.screener import ScreenerService

        svc = ScreenerService(repo)
        as_of = svc.latest_date()
        if not as_of:
            logger.info("sector_context: no latest date, skip")
            return {"industries": [], "concepts": []}
        df = svc._load_enriched_for_date(as_of)
        if df is None or df.is_empty():
            logger.info("sector_context: no enriched data for %s, skip", as_of)
            return {"industries": [], "concepts": []}
        # 只取聚合需要的列,构造 quote_map(symbol -> change_pct/name)
        cols = [c for c in ("symbol", "name", "change_pct", "amount") if c in df.columns]
        quote_map: dict[str, dict] = {}
        for rec in df.select(cols).to_dicts():
            sym = str(rec.get("symbol") or "")
            if sym:
                quote_map[sym] = rec
    except Exception as e:  # noqa: BLE001
        logger.debug("position sector context load quotes failed: %s", e)
        return {"industries": [], "concepts": []}

    def _rank_dimension(config_id: str, field: str) -> list[dict]:
        dim_map = _load_ext_dimension(data_dir, config_id, field)
        if not dim_map or not quote_map:
            return []

        # 全市场聚合每个板块的平均涨幅
        groups: dict[str, list[dict]] = {}
        for sym, rec in quote_map.items():
            for d in dim_map.get(sym, []):
                groups.setdefault(d, []).append(rec)

        scored: list[dict] = []
        for name, recs in groups.items():
            pcts = [_safe_float(r.get("change_pct")) for r in recs]
            pcts = [p for p in pcts if p is not None]
            if not pcts:
                continue
            leader = max(recs, key=lambda r: _safe_float(r.get("change_pct")) or -999)
            scored.append({
                "name": name,
                "market_avg_pct": round(sum(pcts) / len(pcts), 3),
                "market_count": len(recs),
                "leader_name": leader.get("name"),
                "leader_pct": _safe_float(leader.get("change_pct")),
            })
        # 按平均涨幅排名(1=最强)
        scored.sort(key=lambda x: x["market_avg_pct"], reverse=True)
        total = len(scored)
        for i, item in enumerate(scored):
            item["rank"] = i + 1
            item["total"] = total
            item["is_leading"] = i < 5
            item["is_lagging"] = i >= total - 5 if total >= 5 else False

        rank_by_name = {item["name"]: item for item in scored}

        # 只保留持仓涉及的板块,叠加该板块下持仓的合计市值
        total_mv = sum(h.get("market_value") or 0 for h in holdings) or 1
        out: list[dict] = []
        for name, info in rank_by_name.items():
            members = [h for h in holdings if name in dim_map.get(h.get("symbol") or "", [])]
            if not members:
                continue
            holding_mv = sum(h.get("market_value") or 0 for h in members)
            out.append({
                **info,
                "holding_mv": round(holding_mv, 2),
                "holding_pct": round(holding_mv / total_mv * 100, 1),
                "holding_symbols": [h.get("symbol") for h in members],
            })
        # 按持仓市值降序
        out.sort(key=lambda x: x["holding_mv"], reverse=True)
        return out

    return {
        "industries": _rank_dimension("ext_hy_ths", "所属同花顺行业"),
        "concepts": _rank_dimension("ext_gn_ths", "所属概念"),
    }


def _build_settlement_context() -> dict:
    """获取交割单统计与对账异常，用于 AI 复盘注入。

    返回:
      {
        "available": bool,
        "summary": {...},             # 汇总（笔数/金额/费用）
        "realized_pnl": float,        # 已实现盈亏总额
        "monthly": [...],             # 月度盈亏 Top 6
        "by_symbol_top": [...],       # 单票盈亏 Top 5
        "by_symbol_bottom": [...],    # 单票亏损 Bottom 5
        "fees": {...},                # 费用明细
        "reconcile_anomalies": [...],  # 对账异常标的清单
        "records_count": int,
      }
    数据缺失不阻断复盘，返回 available=False。
    """
    empty = {"available": False}
    try:
        from app.services import settlement, reconcile as reconcile_svc

        stats = settlement.compute_stats()
        records_count = stats.get("records_count", 0)
        logger.info(
            "settlement_ctx: stats fetched, records=%d, pnl_curve_points=%d, monthly=%d, by_symbol=%d",
            records_count,
            len(stats.get("realized_pnl_curve", [])),
            len(stats.get("monthly", [])),
            len(stats.get("by_symbol", [])),
        )
        if records_count == 0:
            logger.info("settlement_ctx: no records, skip")
            return empty

        # 单票盈亏 Top/Bottom 5
        by_symbol = stats.get("by_symbol", [])
        by_symbol_top = [s for s in by_symbol if s.get("pnl", 0) > 0][:5]
        by_symbol_bottom = [s for s in by_symbol if s.get("pnl", 0) < 0][:5]
        by_symbol_bottom.sort(key=lambda s: s.get("pnl", 0))  # 亏损从大到小

        # 月度盈亏 Top 6
        monthly = stats.get("monthly", [])[-6:]

        # 对账异常
        recon_anomalies: list[dict] = []
        try:
            items = reconcile_svc.reconcile()
            for item in items:
                if item.get("diff_type") != "matched":
                    recon_anomalies.append({
                        "symbol": item.get("symbol"),
                        "name": item.get("name"),
                        "diff_type": item.get("diff_type"),
                        "shares_delta": item.get("shares_delta"),
                        "cost_delta": item.get("cost_delta"),
                    })
        except Exception as e:  # noqa: BLE001
            logger.warning("settlement_ctx: reconcile failed: %s", e)

        # 累积盈亏总额
        pnl_curve = stats.get("realized_pnl_curve", [])
        total_realized = pnl_curve[-1]["cumulative"] if pnl_curve else 0.0

        result = {
            "available": True,
            "summary": stats.get("summary", {}),
            "realized_pnl": round(total_realized, 2),
            "monthly": monthly,
            "by_symbol_top": by_symbol_top,
            "by_symbol_bottom": by_symbol_bottom,
            "fees": stats.get("fees", {}),
            "reconcile_anomalies": recon_anomalies,
            "records_count": stats.get("records_count", 0),
        }
        logger.info(
            "settlement_ctx: built, realized_pnl=%.2f, top=%d, bottom=%d, monthly=%d, anomalies=%d, fees=%.2f",
            result["realized_pnl"],
            len(result["by_symbol_top"]),
            len(result["by_symbol_bottom"]),
            len(result["monthly"]),
            len(result["reconcile_anomalies"]),
            result["fees"].get("total", 0),
        )
        return result
    except Exception as e:  # noqa: BLE001
        logger.debug("build settlement context failed: %s", e)
        return empty


# ================================================================
# 系统提示词 —— 账户组合客观复盘框架
# 红线:只做客观状态陈述,不输出任何买卖/仓位/止损止盈建议。
# ================================================================

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


def _build_user_prompt(summary: dict, holdings: list[dict], market: dict, concentration: dict, sector_context: dict, settlement_ctx: dict, focus: str) -> str:
    parts: list[str] = [
        f"复盘日期: {date.today().isoformat()}",
        "",
        "## 账户汇总",
        "```json",
        json.dumps(summary, ensure_ascii=False),
        "```",
        "",
        "## 持仓明细(每只已压缩为摘要,含成本/盈亏/趋势/关键价位/指标)",
        "```json",
        json.dumps(holdings, ensure_ascii=False),
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
    from app.services.ai_provider import sanitize_focus
    safe_focus = sanitize_focus(focus)
    if safe_focus:
        parts.extend(["", f"本次复盘请特别关注: {safe_focus}"])
    return "\n".join(parts)


# ================================================================
# 流式入口
# ================================================================

async def analyze_positions_stream(
    repo,
    quote_service,
    positions_rows: list[dict],
    focus: str = "",
    skill_id: str | None = None,
    skill_params: dict | None = None,
) -> AsyncIterator[str]:
    """流式持仓复盘:yield 出每个 NDJSON 事件。

    协议:
      {"type":"meta","count","summary"}   账户摘要
      {"type":"delta","content":"..."}    逐 chunk 文本
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    if not positions_rows:
        yield json.dumps({"type": "error", "message": "当前没有持仓,无法复盘"}, ensure_ascii=False)
        return

    logger.info(
        "position_analyze: start, positions=%d, focus=%s",
        len(positions_rows), focus[:60] if focus else "(none)",
    )

    # 1. 取 enriched 最新行情(股票 + ETF),构建 symbol -> quote 映射
    enriched_map: dict[str, dict] = {}
    try:
        etf_set = repo.get_etf_symbol_set()
        df_e, _ = repo.get_enriched_latest()
        df_etf, _ = repo.get_enriched_latest_asset("etf")
        for df in (df_e, df_etf):
            if df.is_empty() or "symbol" not in df.columns:
                continue
            for r in df.to_dicts():
                enriched_map[r["symbol"]] = r
        # 名称回填(enriched 可能没有 name)
        name_map = repo.get_name_map([p.get("symbol") for p in positions_rows])
        for sym, nm in name_map.items():
            enriched_map.setdefault(sym, {})["name"] = nm
        _ = etf_set  # 资产分流已由 get_enriched_latest_asset 覆盖
        logger.info(
            "position_analyze: enriched loaded, symbols=%d, stocks=%d, etf=%d",
            len(enriched_map),
            df_e.height if df_e is not None else 0,
            df_etf.height if df_etf is not None else 0,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("load enriched for position analyze failed: %s", e)
        yield json.dumps({"type": "error", "message": f"加载行情数据失败: {e}"}, ensure_ascii=False)
        return

    # 2. 逐只压缩摘要
    holdings: list[dict] = []
    for pos in positions_rows:
        h = _summarize_holding(repo, pos, enriched_map)
        if h:
            holdings.append(h)
    if not holdings:
        yield json.dumps({"type": "error", "message": "持仓数据无法解析"}, ensure_ascii=False)
        return

    logger.info(
        "position_analyze: holdings assembled, valid=%d/%d, skipped=%d",
        len(holdings), len(positions_rows), len(positions_rows) - len(holdings),
    )

    summary = _build_portfolio_summary(holdings)
    logger.info(
        "position_analyze: summary, total_mv=%.2f, total_pnl=%.2f, pnl_pct=%.1f%%, winners=%d/%d, day_up=%d/%d",
        summary.get("total_market_value", 0),
        summary.get("total_pnl", 0),
        summary.get("total_pnl_pct") or 0,
        summary.get("winners", 0),
        summary.get("count", 0),
        summary.get("day_up", 0),
        summary.get("count", 0),
    )

    market = _build_market_snapshot(repo, quote_service)
    logger.info(
        "position_analyze: market snapshot, as_of=%s, emotion=%s",
        market.get("as_of"), (market.get("emotion") or {}).get("label") if market.get("emotion") else "(none)",
    )
    try:
        concentration = _build_concentration(repo.store.data_dir, holdings)
    except Exception as e:  # noqa: BLE001
        logger.debug("build concentration failed: %s", e)
        concentration = {"industry": [], "concept": [], "uncovered": []}
    logger.info(
        "position_analyze: concentration, industries=%d, concepts=%d, uncovered=%d",
        len(concentration.get("industry", [])),
        len(concentration.get("concept", [])),
        len(concentration.get("uncovered", [])),
    )
    try:
        sector_context = _build_sector_context(repo, repo.store.data_dir, holdings)
    except Exception as e:  # noqa: BLE001
        logger.debug("build sector context failed: %s", e)
        sector_context = {"industries": [], "concepts": []}
    logger.info(
        "position_analyze: sector context, industries=%d, concepts=%d",
        len(sector_context.get("industries", [])),
        len(sector_context.get("concepts", [])),
    )
    try:
        settlement_ctx = _build_settlement_context()
    except Exception as e:  # noqa: BLE001
        logger.debug("build settlement context failed: %s", e)
        settlement_ctx = {"available": False}
    logger.info(
        "position_analyze: settlement ctx, available=%s, records=%d, realized_pnl=%.2f, anomalies=%d",
        settlement_ctx.get("available"),
        settlement_ctx.get("records_count", 0),
        settlement_ctx.get("realized_pnl", 0),
        len(settlement_ctx.get("reconcile_anomalies", [])),
    )

    # 3+4. 先解析 Skill 并组装 prompt,再 yield meta(meta 携带 skill 信息)
    system_prompt: str = _SYSTEM_PROMPT
    user_prompt: str = _build_user_prompt(summary, holdings, market, concentration, sector_context, settlement_ctx, focus)
    resolved_skill_id: str | None = None
    resolved_skill_name: str | None = None
    resolved_skill_params: dict = {}
    try:
        from app.services.ai_provider import stream_ai_text

        if skill_id:
            from app.ai_skills import registry
            logger.info("position_analyze: [skill] entry, skill_id=%s, skill_params=%s", skill_id, skill_params)
            try:
                skill = registry.get_skill(skill_id)
                skill_meta = skill.meta
                logger.info(
                    "position_analyze: [skill] lookup ok, id=%s, name=%s, category=%s, params_count=%d",
                    skill_meta.get("id"), skill_meta.get("name"), skill_meta.get("category"), len(skill_meta.get("params", [])),
                )
                params = registry.validate_params(skill_meta, skill_params)
                logger.info("position_analyze: [skill] validate ok, raw=%s, validated=%s", skill_params, params)
                context = {"summary": summary, "holdings": holdings, "market_snapshot": market, "concentration": concentration, "sector_context": sector_context, "settlement_ctx": settlement_ctx, "focus": focus}
                logger.info(
                    "position_analyze: [skill] context assembled, keys=%s, holdings=%d, concentration_industry=%d, focus_len=%d",
                    list(context.keys()), len(holdings),
                    len(concentration.get("industry", [])) if isinstance(concentration, dict) else 0,
                    len(focus),
                )
                system_prompt, user_prompt = skill.run(params, context)
                resolved_skill_id = skill_meta.get("id") or skill_id
                resolved_skill_name = skill_meta.get("name")
                resolved_skill_params = params
                logger.info(
                    "position_analyze: [skill] run ok, sys_len=%d, usr_len=%d",
                    len(system_prompt), len(user_prompt),
                )
            except Exception as e:
                logger.warning(
                    "position_analyze: [skill] failed, skill_id=%s, error_type=%s, error=%s, fallback to default",
                    skill_id, type(e).__name__, e, exc_info=True,
                )
                system_prompt = _SYSTEM_PROMPT
                user_prompt = _build_user_prompt(summary, holdings, market, concentration, sector_context, settlement_ctx, focus)
        else:
            logger.info("position_analyze: [skill] no skill_id provided, using default prompts")

        logger.info("position_analyze: meta yield, count=%d, skill=%s", summary["count"], resolved_skill_id)
        yield json.dumps({
            "type": "meta",
            "count": summary["count"],
            "summary": summary,
            "concentration": concentration,
            "sector_context": sector_context,
            "as_of": date.today().isoformat(),
            "skill_id": resolved_skill_id,
            "skill_name": resolved_skill_name,
            "skill_params": resolved_skill_params,
        }, ensure_ascii=False)

        logger.info(
            "position_analyze: llm start, prompt_len=%d, holdings=%d, focus=%s",
            len(user_prompt), len(holdings), focus[:30] if focus else "(none)",
        )
        chunk_count = 0
        async for delta in stream_ai_text(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=4000,
        ):
            chunk_count += 1
            yield json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)
        logger.info("position_analyze: llm done, chunks=%d", chunk_count)
    except Exception as e:  # noqa: BLE001
        logger.exception("AI position analyze failed: %s", e)
        yield json.dumps({"type": "error", "message": f"AI 复盘失败: {e}"}, ensure_ascii=False)
        return

    yield json.dumps({"type": "done"}, ensure_ascii=False)
    logger.info("position_analyze: done")


async def analyze_positions_once(
    repo,
    quote_service,
    pos_rows: list[dict],
    focus: str = "",
    skill_id: str | None = None,
    skill_params: dict | None = None,
) -> tuple[str | None, dict]:
    """非流式持仓复盘 —— 供定时任务/推送等只需最终文本的调用方。

    返回 (content, meta):content 为完整 Markdown,失败为 None;
    meta 含 count/summary/concentration/as_of。
    """
    content_parts: list[str] = []
    meta: dict = {}
    async for chunk in analyze_positions_stream(
        repo, quote_service, pos_rows, focus,
        skill_id=skill_id, skill_params=skill_params,
    ):
        try:
            evt = json.loads(chunk)
        except Exception:  # noqa: BLE001
            continue
        t = evt.get("type")
        if t == "meta":
            meta = evt
        elif t == "delta":
            content_parts.append(evt.get("content", ""))
        elif t == "error":
            return None, meta
    content = "".join(content_parts).strip()
    return (content or None), meta
