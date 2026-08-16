from __future__ import annotations

import re
import sqlite3
from typing import Any

from stock_kb.textutil import to_simplified


def normalize_query(query: str) -> str:
    q = to_simplified(query or "").strip()
    q = re.sub(r"[\s,，。；;:：?!！？、/\-—_–()\[\]（）\"']+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    company: str | None = None,
    top_k: int = 5,
    year: int | None = None,
    report_type: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    q = normalize_query(query)
    if not q:
        return []

    if len(q) < 3:
        rows = _like_search(
            conn, q, company=company, top_k=top_k,
            year=year, report_type=report_type, language=language,
        )
        # 已建好中文 bigram 表，但当前评测下 bigram 排序会牺牲 keyword 基线；
        # 仅在 LIKE 无结果时用 bigram 兜底，后续可在独立评测集上再调权。
        if not rows and len(q) == 2 and re.search(r"[\u4e00-\u9fff]", q):
            rows = _bigram_search(
                conn, q, company=company, top_k=top_k,
                year=year, report_type=report_type, language=language,
            )
        return rows

    expr = _match_expression(q)
    rows = _match_search(
        conn, expr, company=company, top_k=top_k,
        year=year, report_type=report_type, language=language,
    )
    if not rows and len(q) >= 6 and re.search(r"[\u4e00-\u9fff]", q):
        expr = _trigram_or_expression(q)
        if expr:
            rows = _match_search(
                conn, expr, company=company, top_k=top_k,
                year=year, report_type=report_type, language=language,
            )
    return rows


def _match_search(
    conn: sqlite3.Connection,
    expr: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, snippet(pages_fts, 3, '[', ']', '...', 24) AS snippet, rank "
        "FROM pages_fts JOIN pages p ON p.id = pages_fts.page_id "
        "JOIN reports r ON r.id = p.report_id "
        "WHERE pages_fts MATCH ? "
    )
    params: list[Any] = [expr]
    sql, params = _append_filters(sql, params, company, year, report_type, language)
    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _bigram_search(
    conn: sqlite3.Connection,
    q: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, "
        "CASE WHEN instr(lower(p.content), lower(?)) > 0 THEN "
        "substr(p.content, max(1, instr(lower(p.content), lower(?)) - 40), 160) "
        "ELSE substr(p.content, 1, 160) END AS snippet, rank "
        "FROM pages_bigram_fts b JOIN pages p ON p.id = b.page_id "
        "JOIN reports r ON r.id = p.report_id "
        "WHERE pages_bigram_fts MATCH ? "
    )
    params: list[Any] = [q, q, _quote_fts(q)]
    sql, params = _append_filters(sql, params, company, year, report_type, language)
    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _like_search(
    conn: sqlite3.Connection,
    q: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    like = f"%{_escape_like(q)}%"
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, "
        "CASE WHEN instr(lower(p.content), lower(?)) > 0 THEN "
        "substr(p.content, max(1, instr(lower(p.content), lower(?)) - 40), 160) "
        "ELSE substr(p.content, 1, 160) END AS snippet, "
        "CAST((length(lower(p.content)) - length(replace(lower(p.content), lower(?), ''))) AS REAL) / length(?) AS score "
        "FROM pages p JOIN reports r ON r.id = p.report_id "
        "WHERE p.content LIKE ? ESCAPE '\\' "
    )
    params: list[Any] = [q, q, q, q, like]
    sql, params = _append_filters(sql, params, company, year, report_type, language)
    sql += " ORDER BY p.char_count DESC LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _append_filters(
    sql: str,
    params: list[Any],
    company: str | None,
    year: int | None,
    report_type: str | None,
    language: str | None,
) -> tuple[str, list[Any]]:
    sql += " AND COALESCE(r.is_duplicate, 0) = 0"
    if company is not None:
        sql += " AND r.company = ?"
        params.append(company)
    if year is not None:
        sql += " AND r.year = ?"
        params.append(year)
    if report_type is not None:
        sql += " AND r.report_type = ?"
        params.append(report_type)
    if language is not None:
        sql += " AND r.language = ?"
        params.append(language)
    return sql, params


def _quote_fts(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _match_expression(q: str) -> str:
    terms = [t for t in q.split(" ") if t]
    if len(terms) > 1:
        return " OR ".join(_quote_fts(t) for t in terms)
    return _quote_fts(q)


def _trigram_or_expression(q: str) -> str:
    grams: list[str] = []
    compact = re.sub(r"\s+", "", q)
    for i in range(len(compact) - 2):
        gram = compact[i : i + 3]
        if gram not in grams:
            grams.append(gram)
    return " OR ".join(_quote_fts(g) for g in grams[:12])


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
