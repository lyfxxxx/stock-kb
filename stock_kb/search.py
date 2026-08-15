from __future__ import annotations

import sqlite3
from typing import Any


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    company: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    params: list[Any] = []
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, snippet(pages_fts, 3, '[', ']', '...', 24) AS snippet "
        "FROM pages_fts JOIN pages p ON p.id = pages_fts.page_id "
        "JOIN reports r ON r.id = p.report_id "
    )
    if len(q) < 3:
        sql += " WHERE p.content LIKE ? ESCAPE '\\' "
        params.append(f"%{_escape_like(q)}%")
    else:
        sql += " WHERE pages_fts MATCH ? "
        params.append(f'"{q.replace(chr(34), chr(34) + chr(34))}"')
    if company:
        sql += " AND r.company = ? "
        params.append(company)
    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
            "r.title, r.path, substr(p.content, 1, 120) AS snippet "
            "FROM pages p JOIN reports r ON r.id = p.report_id "
            "WHERE p.content LIKE ? ORDER BY p.char_count DESC LIMIT ?",
            (f"%{_escape_like(q)}%", top_k),
        ).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for table in ("companies", "reports", "pages", "statements", "indicators", "sources"):
        out[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    out["reports_by_type"] = [
        dict(r)
        for r in conn.execute(
            "SELECT company, report_type, COUNT(*) AS n FROM reports GROUP BY company, report_type ORDER BY company"
        ).fetchall()
    ]
    return out


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
