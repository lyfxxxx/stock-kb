"""审计两篇试点笔记：关键数字是否出现在笔记中，并与 stock-kb 数据库交叉验证。"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = {
    "海底捞": ROOT.parent / "analysis-notes" / "海底捞" / "2026-08-09-海底捞-笔记.md",
    "百胜中国": ROOT.parent / "analysis-notes" / "百胜中国" / "2026-08-09-百胜中国-笔记.md",
}

# (标签, 笔记中应出现的文本片段)
EXPECTED_TEXT = {
    "海底捞": [
        "43,225,355", "432.3", "4,041,885", "40.4", "5,664,189",
        "1,383", "3.9", "95.7", "0.75", "6,602,348", "10,005,135",
        "2,028,881", "4,133,303",
    ],
    "百胜中国": [
        "11,797", "117.97", "929", "1,004", "2.52", "1,466", "14.66",
        "18,101", "1,706", "10,783", "353", "1,144", "506",
    ],
}

# (公司, 报表类型, 年份, 科目关键字, 期望值) —— 与数据库交叉验证
DB_CHECKS = [
    ("海底捞", "income", 2025, ["收入", "revenue"], 43225355.0),
    ("海底捞", "income", 2025, ["年内溢利", "profit for the year"], 4041885.0),
    ("海底捞", "cashflow", 2025, ["经营活动所得现金", "operating activities"], 5664189.0),
    ("百胜中国", "income", 2025, ["totalrevenues", "总收入"], 11797.0),
    ("百胜中国", "income", 2025, ["netincome—yumchina", "归母净利润"], 929.0),
    ("百胜中国", "cashflow", 2025, ["netcashprovidedbyoperating"], 1466.0),
]


def main() -> int:
    failed = 0
    for company, path in NOTES.items():
        if not path.exists():
            print(f"[FAIL] 笔记不存在: {path}")
            failed += 1
            continue
        text = path.read_text(encoding="utf-8")
        print(f"===== {company} =====")
        for pat in EXPECTED_TEXT[company]:
            ok = pat in text
            print(f"  {'OK ' if ok else 'FAIL'} 笔记包含: {pat}")
            if not ok:
                failed += 1

    print("===== 数据库交叉验证 =====")
    conn = sqlite3.connect(str(ROOT / "data" / "stock_kb.db"))
    conn.row_factory = sqlite3.Row
    for company, stmt, year, keywords, expected in DB_CHECKS:
        rows = conn.execute(
            """
            SELECT s.line_name_norm, s.value, s.page_no, r.title
            FROM statements s JOIN reports r ON r.id = s.report_id
            WHERE r.company=? AND s.statement_type=? AND s.year=? AND s.value IS NOT NULL
            """,
            (company, stmt, year),
        ).fetchall()
        match = None
        for r in rows:
            name = (r["line_name_norm"] or "").casefold().replace(" ", "").replace("—", "")
            if any(k.casefold().replace(" ", "").replace("—", "") in name for k in keywords):
                if abs(r["value"] - expected) < 0.01:
                    match = r
                    break
        if match:
            print(
                f"  OK  {company} {stmt} {year}: {match['line_name_norm'][:40]} = "
                f"{match['value']} (p{match['page_no']} {match['title']})"
            )
        else:
            print(f"  FAIL {company} {stmt} {year}: 未找到期望值 {expected}")
            failed += 1

    print("=====")
    print("结果:", "通过" if failed == 0 else f"{failed} 项未通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
