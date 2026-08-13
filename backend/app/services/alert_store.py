"""告警触发记录存储 — JSONL 追加写 + 滚动清理。

职责:
  - 把每次触发的 AlertEvent 追加写入 data/user_data/alerts.jsonl
  - 提供查询 (按来源/类型过滤、时间倒序、限量)
  - 滚动清理: 保留近 N 天 + 上限 M 条 (取交集)

设计:
  - JSONL 每行一个 JSON 对象,便于增量追加和流式读取
  - 清理策略: 追加后按需 prune (按 ts 删旧),避免文件无限膨胀
  - 读时全量加载到内存过滤 (记录量受上限约束, 5000 条量级无压力)
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 保留策略
MAX_DAYS = 7
MAX_RECORDS = 5000
# 每隔多少次写入触发一次清理 (避免每次写都 prune)
PRUNE_EVERY = 20

_lock = threading.Lock()
_write_count = 0


def _path(data_dir: Path) -> Path:
    p = data_dir / "user_data" / "alerts.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append(data_dir: Path, event: dict) -> None:
    """追加一条触发记录。event 应含 ts(毫秒)、rule_id、source 等字段。"""
    line = json.dumps(event, ensure_ascii=False)
    with _lock:
        p = _path(data_dir)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        global _write_count
        _write_count += 1
        if _write_count >= PRUNE_EVERY:
            _write_count = 0
            _prune_locked(p)


def append_many(data_dir: Path, events: list[dict]) -> None:
    """批量追加。"""
    if not events:
        return
    with _lock:
        p = _path(data_dir)
        with p.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        global _write_count
        _write_count += len(events)
        if _write_count >= PRUNE_EVERY:
            _write_count = 0
            _prune_locked(p)


def list_recent(
    data_dir: Path,
    days: int = MAX_DAYS,
    limit: int = MAX_RECORDS,
    source: str | None = None,
    type: str | None = None,
) -> list[dict]:
    """读取近 N 天记录,按时间倒序,支持按 source/type 过滤。

    持锁读: prune/delete/clear 会整文件重写, 无锁读可能读到截断内容。
    """
    import time
    cutoff = (time.time() - days * 86400) * 1000  # 毫秒
    out: list[dict] = []
    p = _path(data_dir)
    if not p.exists():
        return []
    try:
        with _lock, p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("ts", 0) < cutoff:
                    continue
                if source and ev.get("source") != source:
                    continue
                if type and ev.get("type") != type:
                    continue
                out.append(ev)
    except Exception as e:
        logger.warning("alert_store read failed: %s", e)
        return []
    # 时间倒序 + 截断
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out[:limit]


def clear(data_dir: Path) -> int:
    """清空全部记录,返回清除的条数。"""
    with _lock:
        p = _path(data_dir)
        if not p.exists():
            return 0
        count = 0
        try:
            with p.open("r", encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
        except Exception:
            pass
        p.write_text("", encoding="utf-8")
        return count


def delete_one(data_dir: Path, ts: int) -> bool:
    """删除指定 ts 的单条记录,返回是否删除成功。

    JSONL 无主键, 用 ts(毫秒时间戳) 作为标识。
    若存在多条同 ts, 只删第一条。
    """
    with _lock:
        p = _path(data_dir)
        if not p.exists():
            return False
        kept: list[dict] = []
        deleted = False
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if not deleted and ev.get("ts") == ts:
                        deleted = True
                        continue
                    kept.append(ev)
        except Exception as e:
            logger.warning("alert_store delete_one read failed: %s", e)
            return False
        if not deleted:
            return False
        try:
            with p.open("w", encoding="utf-8") as f:
                for ev in kept:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("alert_store delete_one write failed: %s", e)
            return False
        return True


def count(data_dir: Path) -> int:
    """返回当前记录总数。持锁读, 防与整文件重写并发。"""
    p = _path(data_dir)
    if not p.exists():
        return 0
    try:
        with _lock, p.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


# ================================================================
# 信号绩效追踪 (Paper Trading)
# ================================================================

# 回填的后续交易日收益视野 (触发后 N 日)
_HORIZONS = (1, 3, 5, 10, 20)


def list_all(data_dir: Path) -> list[dict]:
    """读取全部记录(不按时间截断), 用于绩效回填。持锁读。"""
    p = _path(data_dir)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with _lock, p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                out.append(ev)
    except Exception as e:
        logger.warning("alert_store list_all failed: %s", e)
        return []
    return out


def _forward_returns(bars: list, baseline: float, horizons: tuple) -> dict:
    """由升序日K序列与触发价计算后续 N 日收益(百分比)。

    bars: [(date, close)] 升序, 含触发日。bars[0] 为触发日收盘,
    bars[h] 为触发后第 h 根。数据不足时对应视野为 None。
    """
    out: dict = {}
    n = len(bars)
    for h in horizons:
        if h < n:
            out[f"pnl_{h}d"] = round((bars[h][1] / baseline - 1) * 100, 2)
        else:
            out[f"pnl_{h}d"] = None
    return out


def backfill_performance(data_dir: Path, repo) -> dict:
    """盘后回填监控信号绩效: 为有 symbol 的告警计算触发后 N 日收益并落盘。

    幂等且每次全量重算 —— 随着日K累计, 更长的视野(10/20 日)会逐步被填上;
    已回填的视野也会因最新行情刷新而被更新。无 symbol 的批次事件跳过。
    返回 {"total","updated","skipped"}。
    """
    from datetime import datetime

    events = list_all(data_dir)
    if not events:
        return {"total": 0, "updated": 0, "skipped": 0}

    today = datetime.now().date()
    total = len(events)
    updated = 0
    skipped = 0
    by_symbol: dict[str, list[tuple[dict, object]]] = {}

    for ev in events:
        sym = ev.get("symbol")
        if not sym:
            skipped += 1
            continue
        try:
            td = datetime.fromtimestamp(ev["ts"] / 1000).date()
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        by_symbol.setdefault(sym, []).append((ev, td))

    for sym, items in by_symbol.items():
        min_date = min(td for _, td in items)
        try:
            df = repo.get_daily(sym, min_date, today, columns=["date", "close"])
            bars = sorted(
                ((r["date"], float(r["close"])) for r in df.iter_rows(named=True)),
                key=lambda x: x[0],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("backfill: get_daily %s failed: %s", sym, e)
            bars = []
        for ev, td in items:
            if not bars:
                continue
            baseline = ev.get("price")
            if not baseline:
                skipped += 1
                continue
            sub = [b for b in bars if b[0] >= td]
            if not sub:
                continue
            for key, pct in _forward_returns(sub, float(baseline), _HORIZONS).items():
                ev[key] = pct
            updated += 1

    with _lock:
        _write_all_locked(data_dir, events)
    return {"total": total, "updated": updated, "skipped": skipped}


def performance_stats(
    data_dir: Path,
    days: int = MAX_DAYS,
    source: str | None = None,
    rule_id: str | None = None,
) -> dict:
    """聚合监控信号绩效: 命中率 / 平均收益 / 最大盈亏, 按 1/3/5/10/20 日视野。

    仅统计有 symbol 且已回填的告警。视野数据不足时 count=0。
    """
    events = list_recent(data_dir, days=days, limit=MAX_RECORDS, source=source)
    if rule_id:
        events = [e for e in events if e.get("rule_id") == rule_id]

    tracked = [e for e in events if e.get("symbol")]
    horizons: dict = {}
    for h in _HORIZONS:
        key = f"pnl_{h}d"
        vals = [e[key] for e in tracked if e.get(key) is not None]
        n = len(vals)
        if n == 0:
            horizons[str(h)] = {"count": 0}
            continue
        pos = [v for v in vals if v > 0]
        horizons[str(h)] = {
            "count": n,
            "hit_rate": round(len(pos) / n * 100, 1),
            "avg_pnl": round(sum(vals) / n, 2),
            "max_gain": round(max(vals), 2),
            "max_loss": round(min(vals), 2),
        }
    return {
        "horizons": horizons,
        "tracked": len(tracked),
        "total": len(events),
    }


def _write_all_locked(data_dir: Path, events: list[dict]) -> None:
    """(调用方需持锁) 全量重写 alerts.jsonl。"""
    p = _path(data_dir)
    try:
        with p.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("alert_store write_all failed: %s", e)


def _prune_locked(p: Path) -> None:
    """(调用方需持锁) 保留近 MAX_DAYS 天 + 上限 MAX_RECORDS 条。"""
    import time
    cutoff = (time.time() - MAX_DAYS * 86400) * 1000
    kept: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("ts", 0) >= cutoff:
                    kept.append(ev)
    except FileNotFoundError:
        return
    except Exception as e:
        logger.warning("alert_store prune read failed: %s", e)
        return
    # 上限截断 (保留最新的)
    if len(kept) > MAX_RECORDS:
        kept.sort(key=lambda x: x.get("ts", 0))
        kept = kept[-MAX_RECORDS:]
    # 重写文件
    try:
        with p.open("w", encoding="utf-8") as f:
            for ev in kept:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("alert_store prune write failed: %s", e)
