"""数据同步断点状态 — 支持大区间同步中断后续传。

持久化到 `data/user_data/sync_state.json` (临时文件 + rename 原子写)。
当前服务对象: `extend_history` 的「向前扩展」任务 —— 按 symbol 记录已完成拉取,
同范围任务中断后重跑时跳过已完成 symbol, 避免重拉已落盘的部分。

状态结构:
{
  "extend_history": {
    "start": "2020-01-01",
    "end": "2024-06-01",
    "done": ["600000.SH", ...],
    "finished": false,
    "updated_at": "2026-08-13T15:30:00"
  }
}
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()

EXTEND_KEY = "extend_history"


def _path() -> Path:
    p = settings.data_dir / "user_data" / "sync_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_locked() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("sync_state read failed, treating as empty: %s", p)
        return {}


def _save_locked(state: dict) -> None:
    """原子写: 先写 .tmp 再 rename, 避免中断留下半截 JSON。"""
    p = _path()
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:  # noqa: BLE001
        logger.warning("sync_state write failed: %s", e)


def load() -> dict:
    """读取全部同步状态 (外部只读使用)。"""
    with _lock:
        return _load_locked()


def begin_extend(start: date, end: date, symbols: list[str]) -> dict:
    """开始一次向前扩展任务, 返回任务状态 (含可续传的已完成 symbol 集合)。

    若存在「同范围且未完成」的任务, 保留其 done 集合 (过滤掉不在本次标的池的);
    否则新建任务。完成后由 finish_extend 标记 finished。
    """
    start_s, end_s = start.isoformat(), end.isoformat()
    with _lock:
        state = _load_locked()
        prev = state.get(EXTEND_KEY)
        if (
            prev
            and prev.get("start") == start_s
            and prev.get("end") == end_s
            and not prev.get("finished")
        ):
            done = sorted({s for s in prev.get("done", []) if s in symbols})
        else:
            done = []
        task = {
            "start": start_s,
            "end": end_s,
            "done": done,
            "finished": False,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        state[EXTEND_KEY] = task
        _save_locked(state)
        return task


def mark_extend_done(done_symbols: list[str]) -> None:
    """把一批成功拉取的 symbol 合并进任务状态 (chunk 粒度, 高频调用)。"""
    if not done_symbols:
        return
    with _lock:
        state = _load_locked()
        task = state.get(EXTEND_KEY)
        if not task:
            return
        cur = set(task.get("done", []))
        cur.update(done_symbols)
        task["done"] = sorted(cur)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_locked(state)


def finish_extend() -> None:
    """任务完成, 标记 finished=True。之后同范围重跑从头开始 (数据已完整)。"""
    with _lock:
        state = _load_locked()
        task = state.get(EXTEND_KEY)
        if not task:
            return
        task["finished"] = True
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_locked(state)
