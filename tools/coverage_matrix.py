"""覆盖矩阵：公司 × 年份 × 关键指标（年报口径），把「静默丢数据」当天可见。

来源是 indicators/statements 表（annual 口径）。run_eval_regression.py 会调用
print_coverage_matrix() 输出该矩阵作为信息项（不设门禁）。

用法：python tools/coverage_matrix.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_kb import db
from stock_kb.config import load_config

CORE_METRICS = ("revenue", "net_profit", "operating_cashflow", "total_assets", "total_equity")
_HEAD = ("revenue", "net_profit", "op_cf", "total_assets", "total_equity")


def coverage_matrix(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.company, r.year, r.report_type, r.id AS report_id,
               (SELECT COUNT(*) FROM statements s WHERE s.report_id=r.id) AS n_stmt
        FROM reports r
        WHERE r.report_type IN ('annual','interim') AND COALESCE(r.is_duplicate,0)=0
        ORDER BY r.company, r.report_type, r.year
        """
    ).fetchall()
    ind = {
        (x["company"], x["year"], x["period_type"], x["name"]): 1
        for x in conn.execute(
            "SELECT company, year, period_type, name FROM indicators WHERE value IS NOT NULL"
        ).fetchall()
    }
    out = []
    for r in rows:
        pt = r["report_type"]
        metrics = {m: 1 if ind.get((r["company"], r["year"], pt, m)) else 0 for m in CORE_METRICS}
        out.append(
            {
                "company": r["company"],
                "report_type": pt,
                "year": r["year"],
                "statements_rows": r["n_stmt"],
                "metrics": metrics,
            }
        )
    return out


def print_coverage_matrix(conn) -> None:
    data = coverage_matrix(conn)
    print("[coverage_matrix]  (1=有, .=缺; 年报/中报口径)")
    cur = None
    for d in data:
        key = (d["company"], d["report_type"])
        if key != cur:
            cur = key
            print(f"  -- {d['company']} {d['report_type']} --")
        marks = " ".join(
            ("1" if d["metrics"][m] else ".") for m in CORE_METRICS
        )
        print(f"    {d['year']!s:>6}  {marks}   stmt={d['statements_rows']}")
    print(f"  列: {' | '.join(_HEAD)}")


def main() -> int:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    print_coverage_matrix(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
