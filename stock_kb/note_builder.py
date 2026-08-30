"""Deterministic note assembly following the stock-note skill tool order.

No LLM: fill the template from indicators, statements, and search hits so
every number has a file+page locator. Used by generation eval and CLI.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from stock_kb import db, search
from stock_kb.route import TOOL_INDICATORS, TOOL_SEARCH, TOOL_STATEMENTS, route

INDICATOR_ORDER = (
    "revenue",
    "net_profit",
    "gross_profit",
    "total_assets",
    "total_equity",
    "operating_cashflow",
)
INDICATOR_LABELS = {
    "revenue": "营业收入",
    "net_profit": "归母净利润",
    "gross_profit": "毛利",
    "total_assets": "总资产",
    "total_equity": "净资产",
    "operating_cashflow": "经营现金流",
}
STATEMENT_KEYWORDS = ("已付股息", "资本开支")
SEARCH_TERMS = ("翻台率", "同店销售", "客单价")


def format_locator(title: str | None, page: int | None) -> str:
    title = (title or "").strip()
    if not title or page is None:
        return ""
    return f"《{title}》第{int(page)}页"


def format_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def _title_for_report(conn: sqlite3.Connection, report_id: Any) -> str:
    if report_id is None:
        return ""
    row = conn.execute(
        "SELECT title FROM reports WHERE id=?", (report_id,)
    ).fetchone()
    return (row["title"] if row else "") or ""


def latest_annual_year(conn: sqlite3.Connection, company: str) -> int | None:
    row = conn.execute(
        """
        SELECT MAX(year) AS y FROM reports
        WHERE company=? AND report_type='annual'
          AND COALESCE(is_duplicate, 0)=0 AND year IS NOT NULL
        """,
        (company,),
    ).fetchone()
    return int(row["y"]) if row and row["y"] is not None else None


def fetch_indicators(
    conn: sqlite3.Connection,
    company: str,
    years: list[int],
) -> list[dict[str, Any]]:
    if not years:
        return []
    marks = ",".join("?" * len(years))
    name_marks = ",".join("?" * len(INDICATOR_ORDER))
    rows = conn.execute(
        f"""
        SELECT i.name, i.year, i.value, i.unit, i.currency, i.page_no,
               i.report_id, i.line_name, i.period_type, r.title
        FROM indicators i
        LEFT JOIN reports r ON r.id = i.report_id
        WHERE i.company=? AND i.period_type='annual'
          AND i.year IN ({marks}) AND i.name IN ({name_marks})
        ORDER BY i.year DESC, i.name
        """,
        [company, *years, *INDICATOR_ORDER],
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["locator"] = format_locator(item.get("title"), item.get("page_no"))
        item["tool"] = TOOL_INDICATORS
        out.append(item)
    return out


def fetch_statement_lines(
    conn: sqlite3.Connection,
    company: str,
    year: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for keyword in STATEMENT_KEYWORDS:
        rows = db.query_statements(
            conn,
            company,
            year=year,
            period_type="annual",
            keyword=keyword,
            limit=3,
            include_comparatives=False,
        )
        for row in rows:
            item = dict(row)
            item["keyword"] = keyword
            item["locator"] = format_locator(item.get("title"), item.get("page_no"))
            item["tool"] = TOOL_STATEMENTS
            out.append(item)
            break
    return out


def fetch_operating_hits(
    conn: sqlite3.Connection,
    company: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for term in SEARCH_TERMS:
        hits = search.fts_search(conn, term, company=company, top_k=1)
        if not hits:
            continue
        h = hits[0]
        out.append(
            {
                "term": term,
                "title": h.get("title"),
                "page_no": h.get("page_no"),
                "year": h.get("year"),
                "snippet": (h.get("snippet") or "")[:160],
                "locator": format_locator(h.get("title"), h.get("page_no")),
                "tool": TOOL_SEARCH,
            }
        )
    return out


def render_note(
    company: str,
    *,
    as_of_year: int | None,
    indicators: list[dict[str, Any]],
    statements: list[dict[str, Any]],
    operating: list[dict[str, Any]],
) -> str:
    period = f"{as_of_year}年报" if as_of_year else "未知期间"
    lines: list[str] = [
        f"# {company} 笔记",
        "",
        f"> 数据截至：{period}｜来源：stock-kb（财报/研报库；组稿路径，不含模型判断）",
        "",
        "## 一句话结论",
        "",
        "以下关键数字均来自 indicators / 三表 / 检索命中页，不生成估值或观点。",
        "",
        "## 公司概况与最新业绩",
        "",
    ]
    latest = [r for r in indicators if r.get("year") == as_of_year]
    if latest:
        bits = []
        for r in latest:
            label = INDICATOR_LABELS.get(r["name"], r["name"])
            cite = r.get("locator") or ""
            bits.append(f"{label} {format_value(r.get('value'))} {cite}".strip())
        lines.append("；".join(bits) + "。")
    else:
        lines.append("暂无数据")
    lines.extend(["", "## 经营/销售情况", ""])
    if operating:
        for h in operating:
            loc = h.get("locator") or ""
            lines.append(f"- {h['term']}：{loc} {h.get('snippet') or ''}".strip())
    else:
        lines.append("暂无数据")
    lines.extend(
        [
            "",
            "## 利润表情况",
            "",
            "见财务摘要表（归母净利润走 indicators.net_profit）。",
            "",
            "## 财务摘要",
            "",
            "| 指标 | 年份 | 数值 | 来源 |",
            "|---|---|---|---|",
        ]
    )
    by_name = {name: [] for name in INDICATOR_ORDER}
    for r in indicators:
        by_name.setdefault(r["name"], []).append(r)
    for name in INDICATOR_ORDER:
        for r in by_name.get(name) or []:
            label = INDICATOR_LABELS.get(name, name)
            loc = r.get("locator") or ""
            lines.append(
                f"| {label} | {r.get('year')} | {format_value(r.get('value'))} | {loc} |"
            )
    lines.extend(["", "## 资产负债情况", ""])
    asset_rows = [
        r
        for r in latest
        if r["name"] in {"total_assets", "total_equity"}
    ]
    if asset_rows:
        for r in asset_rows:
            label = INDICATOR_LABELS.get(r["name"], r["name"])
            lines.append(
                f"- {label} {format_value(r.get('value'))} {r.get('locator') or ''}".strip()
            )
    else:
        lines.append("暂无数据")
    lines.extend(["", "## 现金流与分红", ""])
    ocf = [r for r in latest if r["name"] == "operating_cashflow"]
    if ocf:
        r = ocf[0]
        lines.append(
            f"- 经营现金流 {format_value(r.get('value'))} {r.get('locator') or ''}".strip()
        )
    if statements:
        for s in statements:
            lines.append(
                f"- {s.get('keyword')} {format_value(s.get('value'))} "
                f"{s.get('locator') or ''}".strip()
            )
    if not ocf and not statements:
        lines.append("暂无数据")
    lines.extend(
        [
            "",
            "## 研报观点",
            "",
            "暂无数据（组稿路径不摘录研报判断）",
            "",
            "## 行业环境",
            "",
            "暂无数据",
            "",
            "## 同行对比",
            "",
            "暂无数据（组稿路径单公司）",
            "",
            "## 估值推演",
            "",
            "暂无数据（组稿路径不生成判断）",
            "",
            "## 风险",
            "",
            "暂无数据",
            "",
            "## 总结",
            "",
            "数字与引用已按 skill 工具顺序从库中取出；观点章节留空，避免无出处判断。",
            "",
        ]
    )
    return "\n".join(lines)


def compose_note(
    cfg: dict[str, Any],
    company: str,
    *,
    out_dir: Path | None = None,
    year_count: int = 5,
) -> dict[str, Any]:
    """Assemble one company note. Writes UTF-8 markdown. Returns metadata."""
    conn = db.connect(cfg["db_path"])
    try:
        as_of = latest_annual_year(conn, company)
        years: list[int] = []
        if as_of is not None:
            years = [as_of - i for i in range(max(year_count, 1))]
        indicators = fetch_indicators(conn, company, years)
        statements = fetch_statement_lines(conn, company, as_of)
        operating = fetch_operating_hits(conn, company)
        markdown = render_note(
            company,
            as_of_year=as_of,
            indicators=indicators,
            statements=statements,
            operating=operating,
        )
    finally:
        conn.close()

    root = Path(cfg["project_root"])
    dest_dir = out_dir or (root / "eval" / "generated_notes" / company)
    dest_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = dest_dir / f"{today}-{company}-笔记.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "company": company,
        "path": str(path),
        "as_of_year": as_of,
        "n_indicators": len(indicators),
        "n_statements": len(statements),
        "n_operating": len(operating),
        "tools_used": [
            TOOL_INDICATORS,
            TOOL_STATEMENTS,
            TOOL_SEARCH,
        ],
        "route_sample": [
            route(f"{company} {INDICATOR_LABELS['net_profit']}", company=company),
            route(f"{company} 已付股息", company=company),
            route(f"{company} 翻台率", company=company),
        ],
    }
