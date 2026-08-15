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

from stock_kb import search


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
        sql = "SELECT id, company, report_type, language, year, period_type, title, path FROM reports WHERE company=?"
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
    ) -> list[dict[str, Any]]:
        """全文检索报告内容，返回命中的页与摘要。"""
        conn = _conn()
        try:
            return search.fts_search(conn, query, company=company, top_k=top_k)
        finally:
            conn.close()

    @mcp.tool()
    def get_financial_statements(
        company: str,
        statement_type: str | None = None,
        year: int | None = None,
        period_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取三大报表行项目。statement_type: income/balance/cashflow/equity。"""
        sql = """
            SELECT s.statement_type, s.line_name_orig, s.line_name_norm, s.value,
                   s.unit, s.currency, s.year, s.page_no, r.title, r.path
            FROM statements s JOIN reports r ON r.id = s.report_id
            WHERE r.company=?
        """
        params: list[Any] = [company]
        if statement_type:
            sql += " AND s.statement_type=?"
            params.append(statement_type)
        if year:
            sql += " AND s.year=?"
            params.append(year)
        if period_type:
            sql += " AND r.period_type=?"
            params.append(period_type)
        sql += " ORDER BY r.year DESC, s.page_no, s.line_name_norm LIMIT ?"
        params.append(limit)
        conn = _conn()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @mcp.tool()
    def get_indicators(
        company: str,
        years: list[int] | None = None,
        metrics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """获取财务指标；当前来自 indicators 表，后续由三表自动计算补充。"""
        sql = "SELECT * FROM indicators WHERE company=?"
        params: list[Any] = [company]
        if years:
            marks = ",".join("?" * len(years))
            sql += f" AND year IN ({marks})"
            params.extend(years)
        if metrics:
            marks = ",".join("?" * len(metrics))
            sql += f" AND name IN ({marks})"
            params.extend(metrics)
        sql += " ORDER BY year, name"
        conn = _conn()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @mcp.tool()
    def get_report_text(
        company: str,
        title: str | None = None,
        page: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取报告某页/某几页的文本。"""
        sql = """
            SELECT p.page_no, p.char_count, p.is_ocr, p.content, r.title, r.path
            FROM pages p JOIN reports r ON r.id = p.report_id
            WHERE r.company=?
        """
        params: list[Any] = [company]
        if title:
            sql += " AND r.title LIKE ?"
            params.append(f"%{title}%")
        if page:
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
        context_chars: int = 200,
    ) -> list[dict[str, Any]]:
        """取带来源定位的原文片段，供笔记引用。"""
        rows = get_report_text(company, title, page, limit=5)
        out = []
        for r in rows:
            content = r.get("content") or ""
            out.append(
                {
                    "company": company,
                    "title": r["title"],
                    "page": r["page_no"],
                    "locator": f"{r['title']} 第{r['page_no']}页",
                    "excerpt": content[:context_chars],
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
