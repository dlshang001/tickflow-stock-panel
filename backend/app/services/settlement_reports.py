"""AI 交割单分析报告持久化存储。

与 position_reports / market_recap_reports 完全独立 ——
单独文件、字段、上限,互不影响。存储委托共享 JsonReportStore。

存储位置: data/user_data/ai_settlement_recaps.json (数组, 按 created_at 降序)
保留最近 MAX_REPORTS 条;超出自动裁剪最旧的。

每条报告结构:
{
  "id": "set_xxx",            # 唯一 id
  "as_of": "2026-08-11",      # 分析日期
  "focus": "",                # 用户追加关注点
  "content": "# ...markdown", # 报告正文
  "summary": {                # 交割单摘要快照
    "total_trades": 2800,
    "buy_count": 1500,
    "sell_count": 1300,
    "total_realized_pnl": 12345.67,
    "records_count": 3297
  },
  "count": 3297,              # 记录数(兼容历史列表 count 字段)
  "created_at": "2026-08-11T15:35:00"
}
"""
from __future__ import annotations

from app.services.json_report_store import JsonReportStore

MAX_REPORTS = 30

_store = JsonReportStore(
    "ai_settlement_recaps.json", MAX_REPORTS,
    id_prefix="set", id_with_symbol=False,
)


def list_reports() -> list[dict]:
    """返回全部报告(按 created_at 降序)。"""
    return _store.list_reports()


def save_report(report: dict) -> dict:
    """新增一条报告并持久化。返回保存后的报告(含 id / created_at)。"""
    return _store.save_report(report)


def delete_report(report_id: str) -> bool:
    """删除指定报告。返回是否删除成功。"""
    return _store.delete_report(report_id)
