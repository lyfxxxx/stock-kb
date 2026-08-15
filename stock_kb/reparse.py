from __future__ import annotations

from typing import Any

from stock_kb import db
from stock_kb.parsers.pdf_parser import extract_statements_from_pages


def reparse_statements(cfg: dict[str, Any], company: str | None = None) -> dict[str, int]:
    conn = db.connect(cfg["db_path"])
    sql = "SELECT id, company, title FROM reports"
    params: list[Any] = []
    if company:
        sql += " WHERE company=?"
        params.append(company)
    reports = conn.execute(sql, params).fetchall()
    updated = 0
    for r in reports:
        page_rows = conn.execute(
            "SELECT page_no, content, content_orig, is_ocr FROM pages WHERE report_id=? ORDER BY page_no",
            (r["id"],),
        ).fetchall()
        pages = [
            {
                "page_no": p["page_no"],
                "content": p["content"] or "",
                "content_orig": p["content_orig"] or p["content"] or "",
                "char_count": len(p["content"] or ""),
                "is_ocr": p["is_ocr"],
                "tables": [],
            }
            for p in page_rows
        ]
        stmt_rows = extract_statements_from_pages(pages, r["company"], r["title"])
        db.replace_statements(conn, r["id"], stmt_rows)
        updated += 1
    conn.close()
    return {"reports": updated}
