"""数据质量校验服务 (优化项 9)。

只读扫描日 K Parquet, 检查:
  - 日期连续性与 symbol 覆盖率 (复用 kline_sync.check_daily_integrity)
  - 价格异常: 相邻交易日涨跌幅 > 阈值 (默认 20%, 排除新股首日)
  - 成交量/额非负: volume 或 amount < 0

所有查询走 DuckDB read_parquet, 不修改任何数据 (fail-soft)。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.services.kline_sync import check_daily_integrity
from app.tickflow.repository import KlineRepository

logger = logging.getLogger(__name__)

# 涨跌幅阈值: 超过此比例视为疑似异常 (主板涨停 10%, 创业板/科创板 20%,
# 取 20% 作为"可能数据异常"的宽松下限, 用户可在前端逐条复核)
DEFAULT_PCT_THRESHOLD = 0.20
# 单次扫描最多返回的异常记录数 (避免大库时返回过多)
MAX_ANOMALIES = 200
# 默认只检查最近 N 天的数据 (控制扫描量)
DEFAULT_LOOKBACK_DAYS = 365


def check_price_anomalies(
    repo: KlineRepository,
    start: date | None = None,
    end: date | None = None,
    pct_threshold: float = DEFAULT_PCT_THRESHOLD,
) -> dict:
    """检查日 K 涨跌幅异常 (相邻交易日 close 变化超过阈值)。

    使用 DuckDB 窗口函数 LAG 计算前收盘价, 排除 prev_close 为空 (新股首日) 的情况。
    """
    daily_dir = repo.store.data_dir / "kline_daily"
    if not daily_dir.exists() or not any(daily_dir.glob("**/*.parquet")):
        return {"anomalies": [], "count": 0}

    if start is None:
        # 默认检查最近一年
        start = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    try:
        d = repo.store.data_dir.as_posix()
        sql = f"""
            SELECT symbol, date, close, prev_close,
                   ROUND((close - prev_close) / prev_close * 100, 2) AS pct_change
            FROM (
                SELECT symbol, date, close,
                       LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev_close
                FROM read_parquet('{d}/kline_daily/**/*.parquet', union_by_name=true)
                WHERE date IS NOT NULL AND close IS NOT NULL AND close > 0
                  AND date >= ?
            )
            WHERE prev_close IS NOT NULL AND prev_close > 0
              AND ABS((close - prev_close) / prev_close) > ?
            ORDER BY date DESC, symbol
            LIMIT ?
        """
        params = [start.isoformat(), pct_threshold, MAX_ANOMALIES]
        if end:
            # 在子查询中追加 end 过滤
            sql = sql.replace(
                "AND date >= ?",
                "AND date >= ? AND date <= ?",
            )
            params = [start.isoformat(), end.isoformat(), pct_threshold, MAX_ANOMALIES]

        rows = repo.execute_all(sql, params)
    except Exception as e:  # noqa: BLE001
        logger.warning("check_price_anomalies failed: %s", e)
        return {"error": str(e), "anomalies": [], "count": 0}

    anomalies = []
    for r in rows:
        ddate = r[1] if isinstance(r[1], date) else date.fromisoformat(str(r[1]))
        anomalies.append({
            "symbol": r[0],
            "date": ddate.isoformat(),
            "close": float(r[2]),
            "prev_close": float(r[3]),
            "pct_change": float(r[4]),
        })

    return {"anomalies": anomalies, "count": len(anomalies)}


def check_negative_volume(
    repo: KlineRepository,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """检查成交量/成交额为负的异常记录。"""
    daily_dir = repo.store.data_dir / "kline_daily"
    if not daily_dir.exists() or not any(daily_dir.glob("**/*.parquet")):
        return {"records": [], "count": 0}

    if start is None:
        start = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    try:
        d = repo.store.data_dir.as_posix()
        sql = f"""
            SELECT symbol, date, volume, amount
            FROM read_parquet('{d}/kline_daily/**/*.parquet', union_by_name=true)
            WHERE (volume < 0 OR amount < 0)
        """
        params: list = []
        if start:
            sql += " AND date >= ?"
            params.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            params.append(end.isoformat())
        sql += " ORDER BY date DESC, symbol LIMIT ?"
        params.append(MAX_ANOMALIES)

        rows = repo.execute_all(sql, params)
    except Exception as e:  # noqa: BLE001
        logger.warning("check_negative_volume failed: %s", e)
        return {"error": str(e), "records": [], "count": 0}

    records = []
    for r in rows:
        ddate = r[1] if isinstance(r[1], date) else date.fromisoformat(str(r[1]))
        records.append({
            "symbol": r[0],
            "date": ddate.isoformat(),
            "volume": float(r[2]) if r[2] is not None else None,
            "amount": float(r[3]) if r[3] is not None else None,
        })

    return {"records": records, "count": len(records)}


def check_data_quality(
    repo: KlineRepository,
    start: date | None = None,
    end: date | None = None,
    pct_threshold: float = DEFAULT_PCT_THRESHOLD,
) -> dict:
    """综合数据质量校验, 返回完整报告。

    汇总:
      - integrity: 日期连续性与覆盖率 (from check_daily_integrity)
      - price_anomalies: 涨跌幅异常记录
      - negative_volume: 成交量/额异常记录
      - summary: 汇总统计 (异常总数, 质量等级)
    """
    if start is None:
        start = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    integrity = check_daily_integrity(repo, start=start, end=end)
    price = check_price_anomalies(repo, start=start, end=end, pct_threshold=pct_threshold)
    neg_vol = check_negative_volume(repo, start=start, end=end)

    anomaly_count = price.get("count", 0) + neg_vol.get("count", 0)
    gap_count = integrity.get("missing_gap_count", 0)
    low_cov_count = integrity.get("low_coverage_count", 0)

    # 质量等级: ok / warning / error
    total_issues = anomaly_count + gap_count + low_cov_count
    if total_issues == 0:
        grade = "ok"
    elif total_issues <= 10:
        grade = "warning"
    else:
        grade = "error"

    return {
        "integrity": integrity,
        "price_anomalies": price,
        "negative_volume": neg_vol,
        "summary": {
            "grade": grade,
            "total_issues": total_issues,
            "anomaly_count": anomaly_count,
            "gap_count": gap_count,
            "low_coverage_count": low_cov_count,
            "checked_range_start": start.isoformat(),
            "checked_range_end": (end or date.today()).isoformat(),
        },
    }
