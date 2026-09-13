"""为 stock-note 正式稿拉取写作用数据（只读）。

用法：python tools/fetch_note_data.py --company 海底捞 [--out eval/reports/skill_data_海底捞.json]

输出 JSON：指标序列、资产负债科目、现金流逐年（own-year 口径，避免比较列重复计）、
归母序列、减值行。全部带 title/page_no 供《文件》第N页引用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_kb.config import load_config


def q(conn, sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    if rows and hasattr(rows[0], "keys"):
        return [dict(r) for r in rows]
    return [dict(zip([c[0] for c in conn.execute(sql, params).description], r)) for r in rows]


def balance_items(conn, company: str, years: list[int], needles: list[tuple[str, str]]):
    out = {}
    for label, needle in needles:
        rows = []
        for y in years:
            r = conn.execute(
                """
                SELECT s.year, s.line_name_orig, s.value, s.unit, s.currency, s.page_no, r.title
                FROM statements s JOIN reports r ON r.id = s.report_id
                WHERE r.company=? AND r.period_type='annual' AND s.year=? AND r.year=?
                  AND (s.line_name_norm LIKE ? OR lower(COALESCE(s.line_name_orig,'')) LIKE ?)
                  AND s.value IS NOT NULL
                ORDER BY s.statement_type, s.id LIMIT 3
                """,
                (company, y, y, f"%{needle}%", f"%{needle.lower()}%"),
            ).fetchall()
            for x in r:
                rows.append(dict(x))
        out[label] = rows
    return out


def cashflow_series(conn, company: str, years: list[int], needles: list[tuple[str, str]]):
    out = {}
    for label, needle in needles:
        rows = {}
        for y in years:
            r = conn.execute(
                """
                SELECT s.year, s.line_name_orig, s.value, s.unit, s.currency, s.page_no, r.title
                FROM statements s JOIN reports r ON r.id = s.report_id
                WHERE r.company=? AND r.period_type='annual' AND s.year=? AND r.year=?
                  AND s.statement_type='cashflow'
                  AND (s.line_name_norm LIKE ? OR lower(COALESCE(s.line_name_orig,'')) LIKE ?)
                  AND s.value IS NOT NULL
                ORDER BY s.id LIMIT 2
                """,
                (company, y, y, f"%{needle}%", f"%{needle.lower()}%"),
            ).fetchall()
            if r:
                rows[y] = dict(r[0])
        out[label] = rows
    return out


def income_attributable(conn, company: str, years: list[int]):
    rows = {}
    needles = ["attributabletoowners", "ownersofthecompany", "本公司拥有人", "拥有人应占", "归属于母公司", "歸屬於母公司", "歸屬於本公司"]
    for y in years:
        for n in needles:
            r = conn.execute(
                """
                SELECT s.year, s.line_name_orig, s.value, s.unit, s.currency, s.page_no, r.title
                FROM statements s JOIN reports r ON r.id = s.report_id
                WHERE r.company=? AND r.period_type='annual' AND s.year=? AND r.year=?
                  AND s.statement_type='income'
                  AND (s.line_name_norm LIKE ? OR lower(COALESCE(s.line_name_orig,'')) LIKE ?)
                  AND s.value IS NOT NULL
                ORDER BY s.id LIMIT 1
                """,
                (company, y, y, f"%{n}%", f"%{n.lower()}%"),
            ).fetchone()
            if r:
                rows[y] = dict(r)
                break
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = load_config()
    import sqlite3

    conn = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    company = args.company
    years = [2025, 2024, 2023, 2022, 2021]
    cf_years = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018]

    if company == "海底捞":
        b_needles = [
            ("货币资金", "bank balances and cash"),
            ("受限存款", "pledged/restricted"),
            ("借款", "borrowings"),
            ("租赁负债", "lease liabilit"),
            ("应收账款", "trade and other receivables"),
            ("关联方应收", "due from related"),
            ("应付账款", "trade and other payables"),
            ("存货", "inventories"),
            ("合同负债", "contract liabilit"),
            ("固定资产", "property, plant and equipment"),
            ("使用权资产", "right-of-use assets"),
            ("在建工程", "construction in progress"),
            ("商誉", "goodwill"),
            ("无形资产", "intangible assets"),
            ("递延税资产", "deferred tax assets"),
            ("净资产", "total equity"),
            ("总资产减流动负债", "total assets less current"),
        ]
        cf_needles = [
            ("经营现金流", "operating activities"),
            ("资本开支", "purchase of property"),
            ("折旧摊销", "depreciation"),
            ("已付股息", "dividends paid"),
            ("借款净增减", "borrowings raised"),
        ]
    elif company == "百胜中国":
        b_needles = [
            ("货币资金", "cash and cash equivalents"),
            ("短期借款", "short-term borrowings"),
            ("长期借款", "long-term debt"),
            ("应收账款", "accounts receivable"),
            ("应付账款", "accounts payable"),
            ("存货", "inventories"),
            ("固定资产", "property, plant and equipment"),
            ("经营租赁资产", "operating lease right-of-use"),
            ("商誉", "goodwill"),
            ("无形资产", "intangible assets"),
            ("递延税资产", "deferred income taxes"),
            ("净资产", "total shareholders"),
        ]
        cf_needles = [
            ("经营现金流", "operating activities"),
            ("资本开支", "capital spending"),
            ("折旧摊销", "depreciation and amortization"),
            ("已付股息", "dividends paid"),
        ]
    else:
        print(f"未知公司 {company}", file=sys.stderr)
        return 1

    data = {
        "company": company,
        "indicators": q(
            conn,
            """SELECT i.name, i.year, i.value, i.unit, i.currency, i.page_no, r.title
               FROM indicators i LEFT JOIN reports r ON r.id=i.report_id
               WHERE i.company=? AND i.period_type='annual' ORDER BY i.year DESC, i.name""",
            (company,),
        ),
        "balance": balance_items(conn, company, years, b_needles),
        "cashflow": cashflow_series(conn, company, cf_years, cf_needles),
        "attributable": income_attributable(conn, company, cf_years),
        "impairment": q(
            conn,
            """SELECT s.year, s.line_name_orig, s.value, s.unit, s.page_no, r.title
               FROM statements s JOIN reports r ON r.id=s.report_id
               WHERE r.company=? AND r.period_type='annual' AND s.year=r.year
                 AND (s.line_name_norm LIKE '%減值%' OR s.line_name_norm LIKE '%减值%'
                      OR lower(s.line_name_orig) LIKE '%impairment%')
                 AND s.value IS NOT NULL AND s.statement_type IN ('income','cashflow')
               ORDER BY s.year DESC LIMIT 12""",
            (company,),
        ),
    }
    conn.close()

    out = Path(args.out) if args.out else Path(f"eval/reports/skill_data_{company}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in data["balance"].values()) + len(data["indicators"])
    print(f"OK {company}: indicators={len(data['indicators'])}, balance_labels={len(data['balance'])}, "
          f"cf_series={sum(len(v) for v in data['cashflow'].values())}, attributable={len(data['attributable'])}, "
          f"impairment={len(data['impairment'])}, total_rows~{n} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
