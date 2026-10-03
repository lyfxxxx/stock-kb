"""Deterministic note assembly following the stock-note skill tool order.

No LLM: fill the template from indicators, statements, and search hits so
every number has a file+page locator. Used by generation eval and CLI.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from stock_kb import db, humanfmt, search
from stock_kb.report_html import render_html
from stock_kb.route import TOOL_INDICATORS, TOOL_SEARCH, TOOL_STATEMENTS, route

INDICATOR_ORDER = (
    "revenue",
    "net_profit",
    "gross_profit",
    "gross_margin",
    "net_margin",
    "total_assets",
    "total_equity",
    "operating_cashflow",
)
CITE_TABLE_NAMES = (
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
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "total_assets": "总资产",
    "total_equity": "净资产",
    "operating_cashflow": "经营现金流",
}
STATEMENT_KEYWORDS = ("已付股息", "资本开支", "减值")
# 经营检索词（分产品/分地区节）；行业检索词（行业与同行节）。每词只取 top1。
OPERATING_TERMS = ("翻台率", "同店销售额", "客单价", "门店数", "新开餐厅")
INDUSTRY_TERMS = ("市场规模", "市场集中度", "市占率")
SHAREHOLDER_TERMS = ("实际控制人", "股东", "股权激励")


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


def format_metric(name: str, value: Any) -> str:
    if value is None:
        return ""
    if name in {"gross_margin", "net_margin", "roe"}:
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return str(value)
    return format_value(value)


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
          AND COALESCE(is_duplicate, 0)=0
          AND COALESCE(status, 'ok')='ok'
          AND year IS NOT NULL
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
    years: list[int] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    year_list = years or [None]
    for year in year_list:
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


def _search_hits(
    conn: sqlite3.Connection,
    company: str,
    terms: tuple[str, ...],
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for term in terms:
        hits = search.fts_search(conn, term, company=company, top_k=1)
        if not hits:
            hits = _vector_fallback(conn, company, term, cfg)
        if not hits:
            continue
        h = hits[0]
        out.append(
            {
                "term": term,
                "title": h.get("title"),
                "page_no": h.get("page_no"),
                "year": h.get("year"),
                "snippet": humanfmt.clean_snippet(h.get("snippet"), 160),
                "locator": format_locator(h.get("title"), h.get("page_no")),
                "tool": TOOL_SEARCH,
                "engine": h.get("source", "fts"),
            }
        )
    return out


def _vector_fallback(
    conn: sqlite3.Connection,
    company: str,
    term: str,
    cfg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """FTS 零命中时用混合检索兜底；向量索引缺失时静默降级返回空。"""
    from stock_kb import vector

    emb = (cfg or {}).get("embedding", {})
    try:
        return vector.hybrid_search(
            conn,
            term,
            model=emb.get("model", "BAAI/bge-small-zh-v1.5"),
            top_k=1,
            company=company,
            cache_dir=(cfg or {}).get("models_dir"),
            backend=emb.get("backend", "auto"),
        )
    except Exception:
        return []


def fetch_operating_hits(
    conn: sqlite3.Connection,
    company: str,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _search_hits(conn, company, OPERATING_TERMS, cfg)


def fetch_industry_hits(
    conn: sqlite3.Connection,
    company: str,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _search_hits(conn, company, INDUSTRY_TERMS, cfg)


def fetch_shareholder_hits(
    conn: sqlite3.Connection,
    company: str,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _search_hits(conn, company, SHAREHOLDER_TERMS, cfg)


def company_code(conn: sqlite3.Connection, company: str) -> str | None:
    row = conn.execute(
        "SELECT code FROM companies WHERE name=?", (company,)
    ).fetchone()
    if not row:
        return None
    code = row["code"] if "code" in row.keys() else None
    return str(code) if code else None


def _cite_table_rows(
    indicators: list[dict[str, Any]],
    statements: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = [
        "| 指标 | 年份 | 数值 | 单位 | 来源 |",
        "|---|---|---|---|---|",
    ]
    by_name: dict[str, list[dict[str, Any]]] = {name: [] for name in CITE_TABLE_NAMES}
    for r in indicators:
        if r.get("name") in CITE_TABLE_NAMES:
            by_name[r["name"]].append(r)
    n = 0
    for name in CITE_TABLE_NAMES:
        for r in by_name.get(name) or []:
            loc = r.get("locator") or ""
            if not loc or r.get("value") is None:
                continue
            label = INDICATOR_LABELS.get(name, name)
            lines.append(
                f"| {label} | {r.get('year')} | {format_value(r.get('value'))} "
                f"| {r.get('unit') or ''} | {loc} |"
            )
            n += 1
    for s in statements:
        loc = s.get("locator") or ""
        if not loc or s.get("value") is None:
            continue
        if s.get("keyword") == "减值":
            continue
        lines.append(
            f"| {s.get('keyword')} | {s.get('year')} | {format_value(s.get('value'))} "
            f"| {s.get('unit') or ''} | {loc} |"
        )
        n += 1
    if n == 0:
        return ["暂无数据"]
    return lines


def _bullet_hits(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["暂无数据"]
    out: list[str] = []
    for h in items:
        loc = h.get("locator") or ""
        snip = (h.get("snippet") or "").strip()
        out.append(f"- {h.get('term')}：{loc} {snip}".strip())
    return out


def _trend_line(rows: list[dict[str, Any]], name: str, label: str) -> str | None:
    return humanfmt.trend_sentence(label, [r for r in rows if r.get("name") == name])


def render_note(
    company: str,
    *,
    as_of_year: int | None,
    indicators: list[dict[str, Any]],
    statements: list[dict[str, Any]],
    operating: list[dict[str, Any]],
    shareholders: list[dict[str, Any]] | None = None,
    industry: list[dict[str, Any]] | None = None,
    code: str | None = None,
    peers: list[str] | None = None,
) -> str:
    period = f"{as_of_year}年报" if as_of_year else "未知期间"
    tags = [f"${company}" + (f"({code})" if code else "") + "$"]
    for p in peers or []:
        if p and p != company:
            tags.append(f"${p}$")
    named_stmts = [{**s, "name": s.get("keyword")} for s in statements]
    trend_profit = "；".join(
        filter(
            None,
            [
                _trend_line(indicators, "revenue", "营业收入"),
                _trend_line(indicators, "net_profit", "归母净利润"),
            ],
        )
    )
    trend_bs = "；".join(
        filter(
            None,
            [
                _trend_line(indicators, "total_equity", "净资产"),
                _trend_line(indicators, "total_assets", "总资产"),
            ],
        )
    )
    trend_cf = "；".join(
        filter(
            None,
            [
                _trend_line(indicators, "operating_cashflow", "经营现金流"),
                _trend_line(named_stmts, "已付股息", "已付股息"),
            ],
        )
    )
    recap = humanfmt.summary_quality(indicators, named_stmts)
    risk = humanfmt.summary_risk(named_stmts)
    lines: list[str] = [
        f"# {company}扫描",
        "",
        f"> 数据截至：{period}｜来源：stock-kb 财报/研报库（组稿底稿，无模型判断；关键数字均标注《文件》页码）",
        "",
        " ".join(tags),
        "",
        "## 股东及高管",
        "",
        *_bullet_hits(shareholders or []),
        "",
        "## 利润表",
        "",
        f"趋势：{trend_profit}" if trend_profit else "暂无带出处的收入/净利年度序列。",
        "",
        "图见 HTML 扫描稿；下表为强制出处明细。",
        "",
        *_cite_table_rows(
            [r for r in indicators if r.get("name") in {"revenue", "net_profit", "gross_profit"}],
            [],
        ),
        "",
        "## 分产品或分地区",
        "",
        *_bullet_hits(operating),
        "",
        "## 资产负债",
        "",
        "净现金公式（与华域扫描同口径）：货币资金 − 短期借款 − 一年内到期非流动负债 − 长期借款。库内无借款明细时不计算净现金。",
        "",
        *( [f"趋势：{trend_bs}", ""] if trend_bs else [] ),
        *_cite_table_rows(
            [r for r in indicators if r.get("name") in {"total_assets", "total_equity"}],
            [],
        ),
        "",
        "## 现金流与分红",
        "",
        *( [f"趋势：{trend_cf}", ""] if trend_cf else [] ),
        *_cite_table_rows(
            [r for r in indicators if r.get("name") == "operating_cashflow"],
            [s for s in statements if s.get("keyword") in {"已付股息", "资本开支"}],
        ),
        "",
        "## 行业与同行",
        "",
        *_bullet_hits(industry or []),
        "",
        "## 未来看点",
        "",
        "暂无数据",
        "",
        "## 总结",
        "",
        f"1. 生意质量：{recap or '暂无带出处的年度事实。'}",
        "2. 估值：库内无市价，不计算 PE / 股息率。派息见已付股息行（须有出处）。",
        f"3. 风险：{risk or '暂无带出处的减值/借款明细。'}",
        "",
        "## 引用明细",
        "",
        *_cite_table_rows(indicators, statements),
        "",
    ]
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
        statements = fetch_statement_lines(conn, company, years)
        operating = fetch_operating_hits(conn, company, cfg)
        shareholders = fetch_shareholder_hits(conn, company, cfg)
        industry = fetch_industry_hits(conn, company, cfg)
        code = company_code(conn, company)
        peers = [
            n
            for n in ((cfg.get("nas") or {}).get("companies") or [])
            if n and n != company
        ]
        markdown = render_note(
            company,
            as_of_year=as_of,
            indicators=indicators,
            statements=statements,
            operating=operating,
            shareholders=shareholders,
            industry=industry,
            code=code,
            peers=peers,
        )
        html = render_html(
            company,
            as_of_year=as_of,
            code=code,
            peers=peers,
            indicators=indicators,
            statements=statements,
            operating=operating,
            shareholders=shareholders,
            industry=industry,
            format_value=format_value,
            format_metric=format_metric,
            indicator_labels=INDICATOR_LABELS,
        )
    finally:
        conn.close()

    root = Path(cfg["project_root"])
    dest_dir = out_dir or (root / "eval" / "generated_notes" / company)
    dest_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = dest_dir / f"{today}-{company}-扫描.md"
    # 组稿 HTML 与 skill 正式稿错开：后者是 YYYY-MM-DD-<公司>-扫描.html
    html_path = dest_dir / f"{today}-{company}-扫描-组稿.html"
    path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return {
        "company": company,
        "path": str(path),
        "html_path": str(html_path),
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
