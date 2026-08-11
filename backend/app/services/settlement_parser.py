"""同花顺交割单 / 投资账本 Excel/CSV 解析器。

支持两种同花顺导出格式（移植自 TideWatch tools/settlement_parser.py）：
  格式 A - 交割单（PC 端）：成交日期, 证券代码, 证券名称, 买卖标志, 成交价格, 成交数量, ...
  格式 B - 投资账本：成交日期, 成交时间, 代码, 名称, 交易类别, 成交数量, ...

输出统一为 6 位裸证券代码（不带 .SH/.SZ 后缀），与本项目持仓口径一致。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

# 格式 A（交割单）原始列名 → 标准字段
FORMAT_A_COLUMNS: dict[str, str] = {
    "成交日期": "trade_date",
    "证券代码": "symbol",
    "证券名称": "name",
    "买卖标志": "direction",
    "成交价格": "price",
    "成交数量": "volume",
    "成交金额": "amount",
    "手续费": "commission",
    "印花税": "stamp_duty",
    "过户费": "transfer_fee",
    "发生金额": "net_amount",
}
FORMAT_A_REQUIRED = {"成交日期", "证券代码", "买卖标志", "成交价格", "成交数量", "成交金额", "发生金额"}

# 格式 B（投资账本）
FORMAT_B_COLUMNS: dict[str, str] = {
    "成交日期": "trade_date",
    "代码": "symbol",
    "名称": "name",
    "交易类别": "direction",
    "成交价格": "price",
    "成交数量": "volume",
    "成交金额": "amount",
    "费用": "commission",
    "发生金额": "net_amount",
}
FORMAT_B_REQUIRED = {"成交日期", "代码", "交易类别", "成交价格", "成交数量", "成交金额", "发生金额"}

TRADE_TYPES = {"买入", "卖出"}

# 格式 B 中非交易流水（银证转账、股息、理财等），过滤并统计
IGNORE_TYPES = {
    # 银证转账（各种表述）
    "银证转帐存", "银证转帐取", "银证转出", "银证转入",
    "银行转证券", "证券转银行", "银证转账", "银行转", "证券转",
    # 股息/分红
    "股息入账", "红利差异税",
    # 理财
    "理财申购", "理财赎回",
    # 融券
    "融券", "融券购回", "融券回购", "融券卖出", "融券买入",
    # 其他
    "收入", "除权除息", "利息入账", "现金分红", "其他",
}


def _detect_format(columns: set[str]) -> str:
    if FORMAT_A_REQUIRED.issubset(columns):
        return "A"
    if FORMAT_B_REQUIRED.issubset(columns):
        return "B"
    raise ValueError(
        f"无法识别交割单格式。当前列: {sorted(columns)}。"
    )


def _try_detect(columns: set[str]) -> str | None:
    if FORMAT_A_REQUIRED.issubset(columns):
        return "A"
    if FORMAT_B_REQUIRED.issubset(columns):
        return "B"
    return None


def _find_trade_sheet(buffer: BytesIO) -> tuple[pl.DataFrame, str]:
    """扫描 Excel 所有 Sheet，找到含交易列的 Sheet。返回 (DataFrame, sheet名)。"""
    # .xlsx 本质是 zip 包，直接解析 workbook.xml 拿 sheet 列表最稳定
    # 不依赖 fastexcel/openpyxl 对内存流的支持
    import zipfile
    import xml.etree.ElementTree as ET

    data_bytes = buffer.getvalue()
    sheet_names: list[str] = []
    try:
        with zipfile.ZipFile(BytesIO(data_bytes)) as zf:
            with zf.open("xl/workbook.xml") as fh:
                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                root = ET.parse(fh).getroot()
                for sheet in root.findall(".//s:sheet", ns):
                    name = sheet.get("name")
                    if name:
                        sheet_names.append(name)
    except Exception:  # noqa: BLE001
        # 回退：用 polars 尝试读第一个 sheet，让 calamine 自己处理
        logger.warning("无法解析 workbook.xml，尝试读取第一个 sheet")
        sheet_names = ["Sheet1"]

    for name in sheet_names:
        df = pl.read_excel(BytesIO(data_bytes), sheet_name=name, engine="calamine")
        cols = {str(c).strip() for c in df.columns}
        if _try_detect(cols):
            logger.info("找到交易数据 Sheet: %s", name)
            return df, name

    sample: dict[str, list[str]] = {}
    for name in sheet_names[:3]:
        try:
            df_tmp = pl.read_excel(BytesIO(data_bytes), sheet_name=name, engine="calamine")
            sample[name] = sorted(str(c).strip() for c in df_tmp.columns)
        except Exception as e:  # noqa: BLE001
            sample[name] = f"<读取失败: {e}>"
    raise ValueError(f"未找到包含交易记录的 Sheet。已扫描: {list(sample.keys())}，列名: {sample}")


def _normalize_code(raw: Any) -> str:
    """证券代码补零到 6 位，去除 .SZ/.SH/.HK 后缀及浮点 .0 尾巴。"""
    if raw is None:
        return ""
    if isinstance(raw, float) and raw == int(raw):
        raw = int(raw)
    s = str(raw).strip().replace("'", "")
    for suffix in (".SZ", ".SH", ".HK", ".US"):
        if s.upper().endswith(suffix):
            s = s[: -len(suffix)]
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.isdigit():
        s = s.zfill(6)
    return s


def _parse_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw is None:
        raise ValueError("日期为空")
    # polars 读 Excel 日期可能是 date/datetime/整数
    if isinstance(raw, (int, float)):
        try:
            return pl.Series([raw], dtype=pl.Date).item()
        except Exception:
            pass
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        d = pl.Series([s]).str.strptime(pl.Date, strict=False).item()
        if d:
            return d
    except Exception:
        pass
    raise ValueError(f"无法解析日期: {raw}")


def _parse_numeric(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "None"):
        return 0.0
    return float(s)


def _safe_str(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def parse_settlement(file_bytes: bytes, filename: str) -> dict:
    """解析交割单 Excel/CSV，返回标准化记录。

    Returns:
        {
          "records": [ {trade_date, symbol, name, direction, price, volume,
                        amount, commission, stamp_duty, transfer_fee, net_amount}, ... ],
          "total_rows": int,
          "parse_errors": [ {"row": int, "error": str}, ... ],   # row 为 Excel 行号(含表头)
          "filtered_stats": { "银证转帐存": n, ... },
          "format": "A" | "B",
        }
    """
    if filename.lower().endswith(".csv"):
        df = pl.read_csv(BytesIO(file_bytes), encoding="utf8-lossy", infer_schema_length=0)
        df = df.with_columns([pl.col(c).cast(pl.Utf8) for c in df.columns])
    else:
        df, _sheet = _find_trade_sheet(BytesIO(file_bytes))

    df.columns = [str(c).strip() for c in df.columns]
    fmt = _detect_format(set(df.columns))
    mapping = FORMAT_A_COLUMNS if fmt == "A" else FORMAT_B_COLUMNS
    # 标准字段 → 原始列名
    col_of = {mapped: orig for orig, mapped in mapping.items()}

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    filtered_stats: dict[str, int] = {}

    for idx, row in enumerate(df.iter_rows(named=True)):
        excel_row = idx + 2  # +1 转 1-based，+1 表头
        try:
            direction = _safe_str(row.get(col_of["direction"]))

            # 格式 B：过滤非交易类型
            if fmt == "B":
                if not direction or direction == "None":
                    errors.append({"row": excel_row, "error": "交易类别为空"})
                    continue
                if direction in IGNORE_TYPES:
                    filtered_stats[direction] = filtered_stats.get(direction, 0) + 1
                    continue
                # 关键词模糊匹配：包含"回购"或"融券"的直接跳过，避免变体（如"回购融券,报价回"）报错
                if "回购" in direction or "融券" in direction:
                    filtered_stats[direction] = filtered_stats.get(direction, 0) + 1
                    continue
                if direction not in TRADE_TYPES:
                    errors.append({"row": excel_row, "error": f"无效的交易类别: {direction}"})
                    continue

            record: dict[str, Any] = {
                "trade_date": str(_parse_date(row.get(col_of["trade_date"]))),
                "symbol": _normalize_code(row.get(col_of["symbol"])),
                "name": _safe_str(row.get(col_of["name"])) or None,
                "direction": direction,
            }

            for field in ("price", "volume", "amount", "commission", "stamp_duty", "transfer_fee", "net_amount"):
                orig = col_of.get(field)
                val = row.get(orig) if orig else 0
                if field == "volume":
                    record[field] = int(_parse_numeric(val))
                else:
                    record[field] = _parse_numeric(val)

            # 格式 A 校验买卖标志
            if fmt == "A" and record["direction"] not in TRADE_TYPES:
                errors.append({"row": excel_row, "error": f"无效的买卖标志: {record['direction']}"})
                continue

            records.append(record)
        except Exception as e:  # noqa: BLE001  坏行不致命
            errors.append({"row": excel_row, "error": str(e)})

    logger.info(
        "交割单解析完成: 格式=%s, 总行数=%d, 成功=%d, 错误=%d, 过滤=%s",
        fmt, df.height, len(records), len(errors), filtered_stats,
    )

    return {
        "records": records,
        "total_rows": df.height,
        "parse_errors": errors,
        "filtered_stats": filtered_stats,
        "format": fmt,
    }
