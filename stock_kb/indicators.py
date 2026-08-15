from __future__ import annotations

from typing import Any

from stock_kb import db


LINE_RULES = {
    "revenue": ["收入", "revenue", "sales"],
    "net_profit": ["净利润", "净利潤", "net income", "profit for the year"],
    "total_assets": ["资产合计", "資產合計", "total assets"],
    "total_equity": ["权益合计", "權益合計", "total equity", "total shareholders"],
    "operating_cashflow": ["经营活动所得现金", "經營活動所得現金", "net cash provided by operating"],
    "gross_profit": ["毛利", "gross profit"],
}


def compute_indicators(cfg: dict[str, Any]) -> dict[str, int]:
    conn = db.connect(cfg["db_path"])
    rows = conn.execute(
        """
        SELECT r.company, s.statement_type, s.year, s.line_name_norm, s.value, s.page_no, r.title
        FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE s.year IS NOT NULL AND s.value IS NOT NULL
        """
    ).fetchall()

    buckets: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for r in rows:
        key = (r["company"], r["year"])
        b = buckets.setdefault(key, {})
        name = (r["line_name_norm"] or "").casefold()
        for indicator, keywords in LINE_RULES.items():
            if any(k in name for k in keywords):
                if indicator not in b:
                    b[indicator] = {
                        "value": r["value"],
                        "page_no": r["page_no"],
                        "title": r["title"],
                    }
                break

    inserted = 0
    for (company, year), b in buckets.items():
        revenue = b.get("revenue", {}).get("value")
        net_profit = b.get("net_profit", {}).get("value")
        equity = b.get("total_equity", {}).get("value")
        gross_profit = b.get("gross_profit", {}).get("value")

        derived: dict[str, float] = {}
        if revenue and gross_profit is not None:
            derived["gross_margin"] = gross_profit / revenue
        if revenue and net_profit is not None:
            derived["net_margin"] = net_profit / revenue
        if equity and net_profit is not None and equity != 0:
            derived["roe"] = net_profit / equity

        for name, value in {**{k: v["value"] for k, v in b.items()}, **derived}.items():
            conn.execute(
                """
                INSERT INTO indicators(company, year, period_type, name, value, unit, source_id)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(company, year, period_type, name) DO UPDATE SET value=excluded.value
                """,
                (company, year, "annual", name, value, None, None),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return {"indicators": inserted}
