from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from stock_kb import db, search


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if self.token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self.token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def create_server(cfg: dict[str, Any]) -> FastMCP:
    db_path = Path(cfg["db_path"])
    mcp = FastMCP("stock-kb")

    def _conn() -> sqlite3.Connection:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _with_locator(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """给检索命中补《title》第N页 locator，与组稿/审计的引用格式一致。"""
        for h in hits:
            title = (h.get("title") or "").strip()
            page = h.get("page_no")
            if title and page is not None:
                h["locator"] = f"《{title}》第{int(page)}页"
        return hits

    @mcp.tool()
    def list_companies() -> list[dict[str, Any]]:
        """列出知识库中的公司。"""
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT company FROM reports ORDER BY company"
            ).fetchall()
            return [{"company": r["company"]} for r in rows]
        finally:
            conn.close()

    @mcp.tool()
    def list_reports(
        company: str,
        report_type: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """列出某公司报告；可按类型（annual/interim/q3/prospectus/research/other）和年份过滤。"""
        sql = (
            "SELECT id, company, report_type, language, year, period_type, title, path, "
            "is_duplicate, duplicate_of FROM reports WHERE company=?"
        )
        params: list[Any] = [company]
        if report_type:
            sql += " AND report_type=?"
            params.append(report_type)
        if year:
            sql += " AND year=?"
            params.append(year)
        sql += " ORDER BY year, title"
        conn = _conn()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @mcp.tool()
    def search_reports(
        query: str,
        company: str | None = None,
        top_k: int = 5,
        engine: str = "fts",
        model: str | None = None,
        year: int | None = None,
        report_type: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """检索报告页（经营叙述：翻台率/同店/师徒等）。科目数字请用 get_indicators 或 get_financial_statements(keyword=)。engine: fts/vector/hybrid。返回带 locator（《title》第N页），可直接用作笔记出处。"""
        conn = _conn()
        try:
            if engine == "fts":
                hits = search.fts_search(
                    conn,
                    query,
                    company=company,
                    top_k=top_k,
                    year=year,
                    report_type=report_type,
                    language=language,
                )
                if not hits:
                    # 默认 FTS 不变，但零命中时自动升引擎兜底，
                    # 避免「报告取数」场景空手而归；向量缺失时静默降级。
                    from stock_kb import vector as _vector

                    try:
                        hits = _vector.hybrid_search(
                            conn,
                            query,
                            model=model
                            or cfg.get("embedding", {}).get(
                                "model", "BAAI/bge-small-zh-v1.5"
                            ),
                            top_k=top_k,
                            company=company,
                            cache_dir=cfg.get("models_dir"),
                            backend=cfg.get("embedding", {}).get("backend", "auto"),
                            year=year,
                            report_type=report_type,
                            language=language,
                        )
                    except Exception:
                        hits = []
                return _with_locator(hits)
            from stock_kb import vector

            model = model or cfg.get("embedding", {}).get(
                "model", "BAAI/bge-small-zh-v1.5"
            )
            if engine == "vector":
                hits = vector.vector_search(
                    conn,
                    model,
                    query,
                    top_k=top_k,
                    company=company,
                    cache_dir=cfg.get("models_dir"),
                    backend=cfg.get("embedding", {}).get("backend", "auto"),
                    year=year,
                    report_type=report_type,
                    language=language,
                )
                return _with_locator(hits)
            if engine == "hybrid":
                hits = vector.hybrid_search(
                    conn,
                    query,
                    model=model,
                    top_k=top_k,
                    company=company,
                    cache_dir=cfg.get("models_dir"),
                    backend=cfg.get("embedding", {}).get("backend", "auto"),
                    year=year,
                    report_type=report_type,
                    language=language,
                )
                return _with_locator(hits)
            raise ValueError(f"不支持的检索引擎: {engine}")
        finally:
            conn.close()

    @mcp.tool()
    def route_query(question: str, company: str | None = None) -> dict[str, Any]:
        """按 skill 规则判断该走哪把只读工具。科目数字用 get_indicators / get_financial_statements，经营叙述用 search_reports。"""
        from stock_kb.route import route

        return route(question, company=company)

    @mcp.tool()
    def get_financial_statements(
        company: str,
        statement_type: str | None = None,
        year: int | None = None,
        period_type: str | None = None,
        keyword: str | None = None,
        limit: int = 100,
        include_comparatives: bool = False,
    ) -> list[dict[str, Any]]:
        """获取三大报表行项目。statement_type: income/balance/cashflow/equity。keyword 按科目名过滤（减值/已付股息/资本开支）。默认只要当年年报正文（r.year=s.year）；比较列需 include_comparatives=True。"""
        from stock_kb.textutil import to_simplified

        conn = _conn()
        try:
            kw = to_simplified(keyword).strip() if keyword else None
            rows = db.query_statements(
                conn,
                company,
                statement_type=statement_type,
                year=year,
                period_type=period_type,
                keyword=kw or None,
                limit=limit,
                include_comparatives=include_comparatives,
            )
            for row in rows:
                # 与组稿/审计统一：《title》第N页（generation_eval._CITE 只认此格式）
                row["locator"] = f"《{row['title']}》第{row['page_no']}页"
            return rows
        finally:
            conn.close()

    @mcp.tool()
    def get_indicators(
        company: str,
        years: list[int] | None = None,
        metrics: list[str] | None = None,
        period_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取财务指标。metrics 如 revenue / net_profit / total_assets / total_equity / operating_cashflow / gross_profit / net_margin / roe。period_type=annual/interim，默认全部；locator 为《报告》第N页，派生指标（比率）无页码时为 "derived"。"""
        sql = (
            "SELECT i.*, r.title FROM indicators i "
            "LEFT JOIN reports r ON r.id = i.report_id WHERE i.company=?"
        )
        params: list[Any] = [company]
        if years:
            marks = ",".join("?" * len(years))
            sql += f" AND i.year IN ({marks})"
            params.extend(years)
        if metrics:
            marks = ",".join("?" * len(metrics))
            sql += f" AND i.name IN ({marks})"
            params.extend(metrics)
        if period_type is not None:
            sql += " AND i.period_type=?"
            params.append(period_type)
        sql += " ORDER BY i.year, i.name"
        conn = _conn()
        try:
            out = []
            for r in conn.execute(sql, params).fetchall():
                row = dict(r)
                title = (row.pop("title", None) or "").strip()
                page = row.get("page_no")
                if title and page is not None:
                    row["locator"] = f"《{title}》第{int(page)}页"
                else:
                    row["locator"] = "derived"
                out.append(row)
            return out
        finally:
            conn.close()

    @mcp.tool()
    def get_report_text(
        company: str,
        title: str | None = None,
        page: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取报告某页/某几页的文本；content 为简体索引文本，content_orig 为原文。"""
        sql = """
            SELECT r.id AS report_id, p.page_no, p.char_count, p.is_ocr,
                   p.content, p.content_orig, r.title, r.path
            FROM pages p JOIN reports r ON r.id = p.report_id
            WHERE r.company=?
        """
        params: list[Any] = [company]
        if title is not None:
            sql += " AND r.title LIKE ?"
            params.append(f"%{title}%")
        if page is not None:
            sql += " AND p.page_no=?"
            params.append(page)
        sql += " ORDER BY r.title, p.page_no LIMIT ?"
        params.append(limit)
        conn = _conn()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @mcp.tool()
    def get_source_excerpt(
        company: str,
        title: str | None = None,
        page: int | None = None,
        keyword: str | None = None,
        context_chars: int = 200,
    ) -> list[dict[str, Any]]:
        """取带来源定位的原文片段，供笔记引用；有 keyword 时围绕命中位置截取。"""
        rows = get_report_text(company, title, page, limit=5)
        out = []
        half = max(int(context_chars) // 2, 20)
        for r in rows:
            content = r.get("content_orig") or r.get("content") or ""
            simplified = r.get("content") or content
            needle = (keyword or "").strip()
            start = 0
            if needle:
                pos = simplified.find(needle)
                if pos < 0:
                    pos = content.find(needle)
                if pos >= 0:
                    start = max(0, pos - half)
            out.append(
                {
                    "company": company,
                    "report_id": r["report_id"],
                    "title": r["title"],
                    "page": r["page_no"],
                    "is_ocr": r["is_ocr"],
                    "locator": f"《{r['title']}》第{r['page_no']}页",
                    "excerpt": content[start : start + context_chars],
                }
            )
        return out

    return mcp


def main(
    cfg: dict[str, Any],
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8931,
) -> None:
    mcp = create_server(cfg)
    if transport == "http":
        token = os.environ.get("STOCK_KB_TOKEN") or cfg.get("mcp", {}).get("token", "")
        app = mcp.streamable_http_app()
        if token:
            app = TokenAuthMiddleware(app, token)
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run(transport="stdio")
