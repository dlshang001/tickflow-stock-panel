#!/usr/bin/env python3
"""遍历目录下所有 xlsx 文件，输出交割单解析结果摘要。

用法：
    cd backend
    .venv/bin/python scripts/test_settlement_parser.py [目录路径]

不传目录则默认扫描项目根目录（即 backend 的上一级）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保能 import app.services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.settlement_parser import parse_settlement  # noqa: E402


def fmt_money(v: float | int | None) -> str:
    if v is None:
        return "-"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.2f}"


def scan_one(path: Path) -> dict:
    """解析单个文件，返回摘要 dict。"""
    try:
        result = parse_settlement(path.read_bytes(), path.name)
        return {
            "ok": True,
            "format": result.get("format", "?"),
            "total_rows": result.get("total_rows", 0),
            "valid_records": len(result.get("records", [])),
            "parse_errors": len(result.get("parse_errors", [])),
            "filtered_stats": result.get("filtered_stats", {}),
            "first_date": result["records"][0]["trade_date"] if result.get("records") else None,
            "last_date": result["records"][-1]["trade_date"] if result.get("records") else None,
            "symbols": len({r["symbol"] for r in result.get("records", [])}),
            "buy_count": sum(1 for r in result.get("records", []) if r.get("direction") == "买入"),
            "sell_count": sum(1 for r in result.get("records", []) if r.get("direction") == "卖出"),
            "buy_amount": sum(float(r.get("amount") or 0) for r in result.get("records", []) if r.get("direction") == "买入"),
            "sell_amount": sum(float(r.get("amount") or 0) for r in result.get("records", []) if r.get("direction") == "卖出"),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def main() -> None:
    if len(sys.argv) > 1:
        scan_dir = Path(sys.argv[1])
    else:
        scan_dir = Path(__file__).resolve().parent.parent.parent

    xlsx_files = sorted(scan_dir.rglob("*.xlsx"))
    # 排除 Python 包内的临时文件（如 ~$ 开头的 Excel 锁文件）
    xlsx_files = [f for f in xlsx_files if not f.name.startswith("~$")]

    if not xlsx_files:
        print(f"未在 {scan_dir} 下找到任何 .xlsx 文件")
        return

    print(f"扫描目录: {scan_dir}")
    print(f"找到 {len(xlsx_files)} 个 xlsx 文件\n")
    print("=" * 100)

    ok_count = 0
    fail_count = 0

    for path in xlsx_files:
        rel = path.relative_to(scan_dir)
        summary = scan_one(path)

        if summary["ok"]:
            ok_count += 1
            print(f"\n✅ {rel}")
            print(f"   格式: {summary['format']}  |  总行数: {summary['total_rows']}  |  有效交易: {summary['valid_records']}")
            print(f"   日期范围: {summary['first_date']} ~ {summary['last_date']}  |  标的数: {summary['symbols']}")
            print(f"   买入: {summary['buy_count']} 笔 / {fmt_money(summary['buy_amount'])}  |  卖出: {summary['sell_count']} 笔 / {fmt_money(summary['sell_amount'])}")
            print(f"   解析错误: {summary['parse_errors']} 条  |  过滤统计: {summary['filtered_stats'] or '(无)'}")
        else:
            fail_count += 1
            print(f"\n❌ {rel}")
            print(f"   错误: {summary['error']}")

    print("\n" + "=" * 100)
    print(f"汇总: 共 {len(xlsx_files)} 个文件, 成功 {ok_count}, 失败 {fail_count}")


if __name__ == "__main__":
    main()
