"""交割单 AI 分析 Skill — 威科夫交易行为分析专家。

与 position_analyzer 完全独立的分析 Skill，拥有专属 System Prompt 和用户数据组装逻辑。
专注于：交易风格评估、买卖时机质量、威科夫阶段判断、胜率/盈亏比、仓位管理、费用效率。

参考：TideWatch 项目 settlement-analysis skill 设计。
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# ================================================================
# 专属 System Prompt — 威科夫交易行为分析
# ================================================================
_SYSTEM_PROMPT = """你是**威科夫交易行为分析专家**。基于用户的真实交割单数据（以及持仓/对账数据），做交易行为诊断和行情对照分析，输出包含以下维度的报告：

### 1. 📊 整体交易风格评估
- 短线/中线/长线倾向（依据持仓平均天数、交易频率判断）
- 交易频率是否合理（日均笔数、月均笔数）
- 买卖对称性（买入笔数 vs 卖出笔数、季节性节奏）

### 2. 🎯 各标的交易时机分析
- 对照持仓成本与现价，判断买卖点质量（是否低买高卖、追涨杀跌倾向）
- 基于成交量和均价，识别可能的追涨杀跌模式
- 成本价是否贴近关键均线或支撑位

### 3. 📈 交易盈亏回顾
- 已实现盈亏总额（FIFO 逐笔匹配）
- 盈亏分布：盈利标的数 vs 亏损标的数、胜率
- 盈亏比（盈利均值 / 亏损均值）
- 盈利 Top 5 和亏损 Top 5 的标的及金额

### 4. 💰 费用效率分析
- 各项费用（佣金/印花税/过户费）占总成交额比例
- 费用占已实现盈亏的比例（交易摩擦成本）
- 是否存在高频交易导致手续费侵蚀利润的情况

### 5. 📅 月度交易节奏
- 月度盈亏趋势图的文字描述（按月列示盈亏金额）
- 交易活跃度的月份分布（哪几个月最活跃/最清淡）
- 是否存在特定月份的系统性盈利/亏损

### 6. 🔍 对账异常分析
- 列出对账异常标的（交割单与操作日志不一致的标的）
- 异常类型：仅交割单、仅日志、不匹配（股数/成本不符）
- 差异金额和股数，客观提示"建议核实"

### 7. ⚠️ 关键风险点与改进建议
- 仓位集中度（单票占比过高风险）
- 交易频率与盈亏的匹配度（高频但低胜率、低频但高胜率等）
- 费用侵蚀程度
- 客观可改进的交易行为方向

## 核心红线
- **不输出**任何"买入/卖出/加仓/减仓/止损/止盈"等交易指令
- **不编造**交易数据或胜率，只基于提供的统计信息做分析
- 所有判断必须引用具体数据，严禁空泛套话

## 输出规范
- Markdown 格式，结构化分节
- 字数 1200-2000 字，简明有密度
- 无数据的维度直接说明"数据不足"
- 末尾附："> ⚠️ 本内容由 AI 基于交割单数据生成，仅客观分析交易行为，不构成任何投资建议。"

现在请基于下方数据进行交易行为分析。"""


def _build_settlement_user_prompt(
    stats: dict,
    reconcile_ctx: dict,
    position_summary: dict | None,
    focus: str = "",
) -> str:
    """组装交割单分析的 user prompt。

    与 position_analyzer 的 _build_user_prompt 完全独立，
    专门面向交易行为分析的数据结构。
    """
    import time as _time
    _t0 = _time.monotonic()

    parts: list[str] = [
        f"分析日期: {date.today().isoformat()}",
        "",
        "## 交割单概况",
        f"交易期间: {stats.get('date_range', {}).get('first', '?')} 至 {stats.get('date_range', {}).get('last', '?')}",
        f"总交易 {stats.get('total_trades', 0)} 笔 (买入{stats.get('buy_count', 0)}笔 / 卖出{stats.get('sell_count', 0)}笔)",
        f"总买入 ¥{stats.get('total_buy_amount', 0):,.0f} | 总卖出 ¥{stats.get('total_sell_amount', 0):,.0f} | 净流入 ¥{stats.get('net_flow', 0):,.0f}",
    ]

    # 已实现盈亏
    realized = stats.get("total_realized_pnl", 0)
    sign = "+" if realized >= 0 else ""
    parts.append(f"FIFO 已实现盈亏 ¥{sign}{realized:,.0f}（买入卖出逐笔 FIFO 匹配）")

    # 费用
    fees = stats.get("fees", {})
    total_fee = fees.get("total", 0) or stats.get("total_fee", 0)
    parts.append(
        f"交易费用: 佣金¥{fees.get('commission', 0):,.0f} "
        f"印花税¥{fees.get('stamp_duty', 0):,.0f} "
        f"过户费¥{fees.get('transfer_fee', 0):,.0f} "
        f"合计¥{total_fee:,.0f}"
    )
    avg_size = stats.get("avg_trade_size", 0)
    parts.append(f"均笔规模 ¥{avg_size:,.0f} | 月均 {stats.get('trades_per_month', 0)} 笔")

    by_symbol_count = 0
    # 各标的汇总
    by_symbol = stats.get("by_symbol", [])
    if by_symbol:
        parts.extend(["", "## 各标的交易汇总（FIFO 已实现盈亏 + 持仓状态）"])
        sym_lines = []
        for s in by_symbol[:15]:
            rsign = "+" if s.get("realized_pnl", 0) >= 0 else ""
            line = (
                f"{s.get('symbol')} {s.get('name', '')} | "
                f"买{s.get('buy_count', 0)}笔 ¥{s.get('total_buy', 0):,.0f} | "
                f"卖{s.get('sell_count', 0)}笔 ¥{s.get('total_sell', 0):,.0f} | "
                f"已实现 ¥{rsign}{s.get('realized_pnl', 0):,.0f}"
            )
            if s.get("unsettled_volume", 0) > 0:
                line += f" | 未平{s.get('unsettled_volume', 0)}股"
            sym_lines.append(line)
        parts.append("\n".join(sym_lines))
        by_symbol_count = len(sym_lines)

    monthly_count = 0
    # 月度分布
    monthly = stats.get("monthly", [])
    if monthly:
        parts.extend(["", "## 月度交易分布"])
        m_lines = []
        for m in monthly:
            nf = "+" if m.get("net_flow", 0) >= 0 else ""
            m_lines.append(
                f"{m.get('month', '?')} | 买{m.get('buy_count', 0)}笔 ¥{m.get('buy_amount', 0):,.0f} | "
                f"卖{m.get('sell_count', 0)}笔 ¥{m.get('sell_amount', 0):,.0f} | "
                f"费用¥{m.get('fee', 0):,.0f} | 净流入 ¥{nf}{m.get('net_flow', 0):,.0f}"
            )
        parts.append("\n".join(m_lines))
        monthly_count = len(m_lines)

    # 盈亏曲线关键点
    curve = stats.get("realized_pnl_curve", [])
    curve_points = 0
    if curve:
        peak = max(curve, key=lambda p: p.get("cumulative", 0)) if curve else None
        trough = min(curve, key=lambda p: p.get("cumulative", 0)) if curve else None
        parts.extend(["", "## 盈亏曲线关键点"])
        if peak:
            pn = "+" if peak["cumulative"] >= 0 else ""
            parts.append(f"历史最高已实现盈亏: ¥{pn}{peak['cumulative']:,.0f} ({peak['date']})")
            curve_points += 1
        if trough:
            tn = "+" if trough["cumulative"] >= 0 else ""
            parts.append(f"历史最低已实现盈亏: ¥{tn}{trough['cumulative']:,.0f} ({trough['date']})")
            curve_points += 1

    # 对账异常
    anomalies_count = 0
    if reconcile_ctx.get("anomalies"):
        parts.extend(["", "## 对账异常标的（交割单与操作日志不一致）"])
        for a in reconcile_ctx["anomalies"]:
            parts.append(
                f"- {a.get('symbol')} {a.get('name', '')} | 类型: {a.get('diff_type')} | "
                f"股数差: {a.get('shares_delta', 0)} | 成本差: {a.get('cost_delta', 0)}"
            )
        anomalies_count = len(reconcile_ctx["anomalies"])

    # 当前持仓快照（用于对照）
    position_injected = False
    if position_summary and position_summary.get("count", 0) > 0:
        parts.extend(["", "## 当前持仓快照（用于对照交易行为）"])
        parts.append(f"持仓只数: {position_summary.get('count', 0)} | 总市值: ¥{position_summary.get('total_market_value', 0):,.0f}")
        pnl = position_summary.get("total_pnl", 0)
        pn = "+" if pnl >= 0 else ""
        parts.append(f"总浮盈亏: ¥{pn}{pnl:,.0f} | 盈利: {position_summary.get('winners', 0)}只 / 亏损: {position_summary.get('losers', 0)}只")
        position_injected = True

    # focus
    focus_injected = False
    from app.services.ai_provider import sanitize_focus
    safe_focus = sanitize_focus(focus)
    if safe_focus:
        parts.extend(["", f"本次分析请特别关注: {safe_focus}"])
        focus_injected = True

    result = "\n".join(parts)
    logger.info(
        "[2/3] prompt_build: assembled, len=%d, by_symbol_rows=%d, monthly_rows=%d, curve_pts=%d, anomalies=%d, position=%s, focus=%s (elapsed=%.1fms)",
        len(result), by_symbol_count, monthly_count, curve_points, anomalies_count,
        position_injected, focus_injected, (_time.monotonic() - _t0) * 1000,
    )
    return result


def _build_stats_for_settlement() -> dict:
    """获取交割单统计，补充交易风格分析所需的派生指标。"""
    import time as _time
    _t0 = _time.monotonic()

    from app.services import settlement

    logger.info("[1/3] stats_build: raw stats loading...")
    raw = settlement.compute_stats()
    if not raw.get("summary"):
        logger.info("[1/3] stats_build: empty summary, skip (elapsed=%.1fms)", (_time.monotonic() - _t0) * 1000)
        return {}

    summary = raw["summary"]
    curve = raw.get("realized_pnl_curve", [])
    monthly = raw.get("monthly", [])
    by_symbol = raw.get("by_symbol", [])
    fees = raw.get("fees", {})
    records_count = raw.get("records_count", 0)

    logger.info(
        "[1/3] stats_build: raw loaded, records=%d, symbols=%d, monthly=%d, curve=%d, fees_total=%.2f (elapsed=%.1fms)",
        records_count, len(by_symbol), len(monthly), len(curve),
        fees.get("total", 0), (_time.monotonic() - _t0) * 1000,
    )

    total_buy = summary.get("buy_amount", 0)
    total_sell = summary.get("sell_amount", 0)
    total_fee = fees.get("total", 0)

    # 日期范围
    date_range = {"first": "?", "last": "?"}
    # 从 settlement 模块获取原始记录的日期范围
    try:
        raw_records = settlement.all_records()
        if raw_records:
            dates = [str(r.get("trade_date", "")) for r in raw_records if r.get("trade_date")]
            if dates:
                date_range = {"first": min(dates), "last": max(dates)}
                logger.info("[1/3] stats_build: date_range resolved, %s ~ %s", date_range["first"], date_range["last"])
    except Exception as e:
        logger.warning("[1/3] stats_build: date_range resolve failed: %s", e)

    # 计算派生指标
    total_trades = summary.get("buy_count", 0) + summary.get("sell_count", 0)
    net_flow = total_sell - total_buy  # 卖出回收 - 买入支出

    # 已实现盈亏
    total_realized = curve[-1]["cumulative"] if curve else 0.0

    # 胜率统计
    winners = sum(1 for s in by_symbol if s.get("realized_pnl", 0) > 0)
    losers = sum(1 for s in by_symbol if s.get("realized_pnl", 0) < 0)

    # 盈亏比
    win_pnls = [s["realized_pnl"] for s in by_symbol if s.get("realized_pnl", 0) > 0]
    loss_pnls = [s["realized_pnl"] for s in by_symbol if s.get("realized_pnl", 0) < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    # 月均交易笔数
    months_span = 1
    if date_range["first"] and date_range["last"]:
        try:
            from datetime import datetime
            d1 = datetime.fromisoformat(date_range["first"])
            d2 = datetime.fromisoformat(date_range["last"])
            months_span = max(1, (d2.year - d1.year) * 12 + d2.month - d1.month + 1)
        except Exception:
            pass
    trades_per_month = round(total_trades / months_span, 1) if months_span > 0 else total_trades

    # 均笔规模
    avg_trade_size = round((total_buy + total_sell) / total_trades, 0) if total_trades > 0 else 0

    # 费用占比
    total_volume = total_buy + total_sell
    fee_ratio = round(total_fee / total_volume * 100, 3) if total_volume > 0 else 0

    logger.info(
        "[1/3] stats_build: derived metrics computed, trades=%d, win=%d/loss=%d, pl_ratio=%.2f, fee_ratio=%.3f%%, tpm=%.1f (elapsed=%.1fms)",
        total_trades, winners, losers, profit_loss_ratio, fee_ratio, trades_per_month,
        (_time.monotonic() - _t0) * 1000,
    )

    result = {
        "date_range": date_range,
        "total_trades": total_trades,
        "buy_count": summary.get("buy_count", 0),
        "sell_count": summary.get("sell_count", 0),
        "total_buy_amount": total_buy,
        "total_sell_amount": total_sell,
        "net_flow": round(net_flow, 2),
        "total_realized_pnl": round(total_realized, 2),
        "fees": {
            "commission": round(fees.get("commission", 0), 2),
            "stamp_duty": round(fees.get("stamp_duty", 0), 2),
            "transfer_fee": round(fees.get("transfer_fee", 0), 2),
            "total": round(total_fee, 2),
        },
        "avg_trade_size": avg_trade_size,
        "trades_per_month": trades_per_month,
        "fee_ratio": fee_ratio,
        "win_count": winners,
        "loss_count": losers,
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "monthly": monthly,
        "by_symbol": by_symbol,
        "realized_pnl_curve": curve,
        "records_count": records_count,
    }

    return result


async def analyze_settlement_stream(
    focus: str = "",
    skill_id: str | None = None,
    skill_params: dict | None = None,
) -> AsyncIterator[str]:
    """流式交割单分析 — yield 出 NDJSON 事件。

    协议与 position_analyzer 一致:
      {"type":"meta","summary"}
      {"type":"delta","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    import time as _time
    _t_start = _time.monotonic()
    logger.info(
        "[stream] start, focus_len=%d, focus_preview=%s",
        len(focus), focus[:60] if focus else "(none)",
    )

    # ============ Stage 1/5: 加载交割单统计 ============
    _t1 = _time.monotonic()
    try:
        stats = _build_stats_for_settlement()
    except Exception as e:  # noqa: BLE001
        logger.exception("[stream] stage1/5 stats load FAILED: %s (elapsed=%.1fms)", e, (_time.monotonic() - _t1) * 1000)
        yield json.dumps({"type": "error", "message": f"加载交割单统计失败: {e}"}, ensure_ascii=False)
        return

    if not stats or stats.get("records_count", 0) == 0:
        logger.warning("[stream] stage1/5 empty data, return error (elapsed=%.1fms)", (_time.monotonic() - _t1) * 1000)
        yield json.dumps({"type": "error", "message": "暂无交割单数据，请先导入交割单文件"}, ensure_ascii=False)
        return

    logger.info(
        "[stream] stage1/5 done, records=%d, realized_pnl=%.2f, symbols=%d (elapsed=%.1fms)",
        stats.get("records_count", 0),
        stats.get("total_realized_pnl", 0),
        len(stats.get("by_symbol", [])),
        (_time.monotonic() - _t1) * 1000,
    )

    # ============ Stage 2/5: 加载对账异常 ============
    _t2 = _time.monotonic()
    reconcile_ctx: dict = {"anomalies": []}
    try:
        from app.services import reconcile as reconcile_svc
        items = reconcile_svc.reconcile()
        anomalies = []
        for item in items:
            if item.get("diff_type") != "matched":
                anomalies.append({
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "diff_type": item.get("diff_type"),
                    "shares_delta": item.get("shares_delta", 0),
                    "cost_delta": item.get("cost_delta", 0),
                })
        reconcile_ctx = {"anomalies": anomalies}
        logger.info("[stream] stage2/5 done, reconcile anomalies=%d (elapsed=%.1fms)", len(anomalies), (_time.monotonic() - _t2) * 1000)
    except Exception as e:  # noqa: BLE001
        logger.warning("[stream] stage2/5 reconcile FAILED: %s (elapsed=%.1fms)", e, (_time.monotonic() - _t2) * 1000)

    # ============ Stage 3/5: 加载当前持仓快照 ============
    _t3 = _time.monotonic()
    position_summary: dict | None = None
    try:
        from app.services import positions
        pos_rows = positions.list_positions()
        if pos_rows:
            count = len(pos_rows)
            total_mv = sum(float(p.get("market_value") or 0) for p in pos_rows)
            total_pnl = sum(float(p.get("pnl") or 0) for p in pos_rows)
            winners = sum(1 for p in pos_rows if float(p.get("pnl") or 0) > 0)
            losers = sum(1 for p in pos_rows if float(p.get("pnl") or 0) < 0)
            position_summary = {
                "count": count,
                "total_market_value": round(total_mv, 2),
                "total_pnl": round(total_pnl, 2),
                "winners": winners,
                "losers": losers,
            }
            logger.info("[stream] stage3/5 done, position count=%d, mv=%.2f, pnl=%.2f (elapsed=%.1fms)", count, total_mv, total_pnl, (_time.monotonic() - _t3) * 1000)
        else:
            logger.info("[stream] stage3/5 done, no positions (elapsed=%.1fms)", (_time.monotonic() - _t3) * 1000)
    except Exception as e:  # noqa: BLE001
        logger.warning("[stream] stage3/5 position snapshot FAILED: %s (elapsed=%.1fms)", e, (_time.monotonic() - _t3) * 1000)

    # ============ Stage 4/5: 组装 prompt + 发送 meta ============
    _t4 = _time.monotonic()
    yield json.dumps({
        "type": "meta",
        "summary": {
            "total_trades": stats.get("total_trades", 0),
            "buy_count": stats.get("buy_count", 0),
            "sell_count": stats.get("sell_count", 0),
            "total_realized_pnl": stats.get("total_realized_pnl", 0),
            "records_count": stats.get("records_count", 0),
        },
        "as_of": date.today().isoformat(),
    }, ensure_ascii=False)

    # ============ Stage 4/5: 组装 prompt (Skill 委托 or 硬编码) ============
    if skill_id:
        from app.ai_skills import registry
        logger.info("[stream] stage4/5 [skill] entry, skill_id=%s, skill_params=%s", skill_id, skill_params)
        try:
            skill = registry.get_skill(skill_id)
            meta = skill.meta
            logger.info(
                "[stream] stage4/5 [skill] lookup ok, id=%s, name=%s, category=%s, params_count=%d",
                meta.get("id"), meta.get("name"), meta.get("category"), len(meta.get("params", [])),
            )
            params = registry.validate_params(meta, skill_params)
            logger.info("[stream] stage4/5 [skill] validate ok, raw=%s, validated=%s", skill_params, params)
            context = {"stats": stats, "reconcile": reconcile_ctx, "position_summary": position_summary, "focus": focus}
            logger.info(
                "[stream] stage4/5 [skill] context assembled, keys=%s, by_symbol=%d, anomalies=%d, position=%s, focus_len=%d",
                list(context.keys()),
                len(stats.get("by_symbol", [])),
                len(reconcile_ctx.get("anomalies", [])),
                "yes" if position_summary else "no",
                len(focus),
            )
            system_prompt, user_prompt = skill.run(params, context)
            logger.info(
                "[stream] stage4/5 [skill] run ok, sys_len=%d, usr_len=%d",
                len(system_prompt), len(user_prompt),
            )
        except Exception as e:
            logger.warning(
                "[stream] stage4/5 [skill] failed, skill_id=%s, error_type=%s, error=%s, fallback to default",
                skill_id, type(e).__name__, e, exc_info=True,
            )
            system_prompt, user_prompt = _SYSTEM_PROMPT, _build_settlement_user_prompt(stats, reconcile_ctx, position_summary, focus)
    else:
        logger.info("[stream] stage4/5 [skill] no skill_id provided, using default prompts")
        system_prompt = _SYSTEM_PROMPT
        user_prompt = _build_settlement_user_prompt(stats, reconcile_ctx, position_summary, focus)

    logger.info(
        "[stream] stage4/5 done, prompt_len=%d, symbols=%d, anomalies=%d, position=%s (elapsed=%.1fms)",
        len(user_prompt), len(stats.get("by_symbol", [])),
        len(reconcile_ctx.get("anomalies", [])),
        "yes" if position_summary else "no",
        (_time.monotonic() - _t4) * 1000,
    )

    # ============ Stage 5/5: 流式 LLM 调用 ============
    _t5 = _time.monotonic()
    try:
        from app.services.ai_provider import stream_ai_text

        logger.info(
            "[stream] stage5/5 llm start, system_prompt_len=%d, user_prompt_len=%d, temperature=0.5, max_tokens=4000",
            len(system_prompt), len(user_prompt),
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
            # 每 50 个 chunk 打一次进度
            if chunk_count % 50 == 0:
                logger.info("[stream] stage5/5 llm progress, chunks=%d (elapsed=%.1fms)", chunk_count, (_time.monotonic() - _t5) * 1000)

        _t_llm_end = _time.monotonic()
        logger.info(
            "[stream] stage5/5 llm done, chunks=%d, llm_elapsed=%.1fms (total=%.1fms)",
            chunk_count, (_t_llm_end - _t5) * 1000, (_t_llm_end - _t_start) * 1000,
        )
    except Exception as e:  # noqa: BLE001
        _t_err = _time.monotonic()
        logger.exception("[stream] stage5/5 llm FAILED: %s, chunks=%d, elapsed=%.1fms (total=%.1fms)", e, chunk_count, (_t_err - _t5) * 1000, (_t_err - _t_start) * 1000)
        yield json.dumps({"type": "error", "message": f"AI 分析失败: {e}"}, ensure_ascii=False)
        return

    yield json.dumps({"type": "done"}, ensure_ascii=False)
    _t_end = _time.monotonic()
    logger.info("[stream] completed, total_elapsed=%.1fms, stages=[stats=%.1fms, reconcile=%.1fms, position=%.1fms, prompt=%.1fms, llm=%.1fms]",
        (_t_end - _t_start) * 1000,
        (_t1 - _t_start) * 1000,
        (_t2 - _t1) * 1000,
        (_t3 - _t2) * 1000,
        (_t4 - _t3) * 1000,
        (_t_end - _t4) * 1000,
    )
