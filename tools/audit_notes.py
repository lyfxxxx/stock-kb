"""审计试点笔记：数字是否出现、引用是否可溯源，并与 stock-kb / PDF golden 交叉验证。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_kb.config import load_config

ROOT = Path(__file__).resolve().parent.parent

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

DB_CHECKS = [
    ("海底捞", "income", 2025, ["收入", "revenue"], 43225355.0),
    ("海底捞", "income", 2025, ["年内溢利", "profit for the year"], 4041885.0),
    ("海底捞", "cashflow", 2025, ["经营活动所得现金", "operating activities"], 5664189.0),
    ("百胜中国", "income", 2025, ["totalrevenues", "总收入"], 11797.0),
    ("百胜中国", "income", 2025, ["netincome—yumchina", "归母净利润"], 929.0),
    ("百胜中国", "cashflow", 2025, ["netcashprovidedbyoperating"], 1466.0),
]

_NUM = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d+|-?\d{4,})(?![\w.])"
)
_CITE = re.compile(
    r"《([^》]+)》\s*第\s*(\d+)\s*页|([^《\n]{2,40})第(\d+)页"
)


def _notes_dir() -> Path:
    env = os.environ.get("STOCK_KB_NOTES_DIR")
    if env:
        return Path(env)
    return ROOT.parent / "analysis-notes"


def _note_paths() -> dict[str, Path]:
    base = _notes_dir()
    paths = {
        "海底捞": base / "海底捞" / "2026-08-09-海底捞-笔记.md",
        "百胜中国": base / "百胜中国" / "2026-08-09-百胜中国-笔记.md",
        "海底捞-抽查": base / "海底捞" / "2026-08-22-海底捞-抽查笔记.md",
    }
    return paths


def _parse_number(token: str) -> float | None:
    raw = token.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    seen: set[float] = set()
    for m in _NUM.finditer(text):
        value = _parse_number(m.group(1))
        if value is None:
            continue
        if value in seen:
            continue
        # skip years and lone page-like small ints used as enumerations
        if 1900 <= value <= 2100 and value == int(value):
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_citations(text: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for m in _CITE.finditer(text):
        if m.group(1) and m.group(2):
            found.append((m.group(1).strip(), int(m.group(2))))
        elif m.group(3) and m.group(4):
            title = m.group(3).strip(" ：:，,")
            if len(title) >= 2:
                found.append((title, int(m.group(4))))
    return found


def number_in_db(conn: sqlite3.Connection, company: str, value: float) -> bool:
    rows = conn.execute(
        """
        SELECT s.value FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE r.company=? AND s.value IS NOT NULL
        UNION ALL
        SELECT value FROM indicators WHERE company=? AND value IS NOT NULL
        """,
        (company, company),
    ).fetchall()
    for r in rows:
        dbv = float(r[0])
        if dbv == 0:
            if abs(value) < 0.05:
                return True
            continue
        if abs(value - dbv) / abs(dbv) <= 0.02:
            return True
        # 千元 vs 百万元 / 亿元 常见换算
        for scale in (0.001, 0.0001, 1000, 10000):
            if abs(value - dbv * scale) / max(abs(dbv * scale), 1e-9) <= 0.02:
                return True
    return False


def citation_in_db(conn: sqlite3.Connection, company: str, file_frag: str, page: int) -> bool:
    del company  # 同行对比引用可能跨公司
    row = conn.execute(
        """
        SELECT 1 FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE instr(r.title, ?) > 0 AND p.page_no=?
        LIMIT 1
        """,
        (file_frag, page),
    ).fetchone()
    return row is not None


def audit_one(conn: sqlite3.Connection, company: str, text: str) -> dict:
    numbers = extract_numbers(text)
    cites = extract_citations(text)
    matched_n = sum(1 for v in numbers if number_in_db(conn, company, v))
    orphan_n = len(numbers) - matched_n
    cite_ok = sum(1 for f, p in cites if citation_in_db(conn, company, f, p))
    return {
        "n_numbers": len(numbers),
        "number_matched": matched_n,
        "number_accuracy": round(matched_n / len(numbers), 3) if numbers else None,
        "orphan_number_rate": round(orphan_n / len(numbers), 3) if numbers else None,
        "n_citations": len(cites),
        "citation_matched": cite_ok,
        "citation_precision": round(cite_ok / len(cites), 3) if cites else None,
    }


def main() -> int:
    cfg = load_config()
    failed = 0
    report: dict = {"notes": {}}
    notes = _note_paths()
    conn = sqlite3.connect(f"file:{Path(cfg['db_path']).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    for company, path in notes.items():
        print(f"===== {company} =====")
        if not path.exists():
            print(f"[FAIL] 笔记不存在: {path}")
            failed += 1
            continue
        text = path.read_text(encoding="utf-8")
        for pat in EXPECTED_TEXT.get(company) or []:
            ok = pat in text
            print(f"  {'OK ' if ok else 'FAIL'} 笔记包含: {pat}")
            if not ok:
                failed += 1
        db_company = company.split("-")[0]
        stats = audit_one(conn, db_company, text)
        report["notes"][company] = {"path": str(path), **stats}
        print(
            f"  numbers={stats['n_numbers']} accuracy={stats['number_accuracy']} "
            f"orphan={stats['orphan_number_rate']} citations={stats['n_citations']} "
            f"cite_p={stats['citation_precision']}"
        )

    print("===== 数据库交叉验证 =====")
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

    accs = [
        n["number_accuracy"]
        for n in report["notes"].values()
        if n.get("number_accuracy") is not None
    ]
    report["summary"] = {
        "number_accuracy_mean": round(sum(accs) / len(accs), 3) if accs else None,
        "hardcoded_failed": failed,
    }
    out_dir = ROOT / "eval" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"generation_{ts}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", out)
    print("=====")
    print("结果:", "通过" if failed == 0 else f"{failed} 项未通过")
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
