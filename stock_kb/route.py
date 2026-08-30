"""Query router: skill rules in code.

Maps a natural-language question to one read-only tool. Numbers go to
indicators or statements; operating narrative goes to search; known-absent
topics return no_answer so the agent does not fill with near neighbours.
"""

from __future__ import annotations

import re
from typing import Any

from stock_kb import search

TOOL_INDICATORS = "get_indicators"
TOOL_STATEMENTS = "get_financial_statements"
TOOL_SEARCH = "search_reports"
TOOL_NO_ANSWER = "no_answer"

TOOLS = (TOOL_INDICATORS, TOOL_STATEMENTS, TOOL_SEARCH, TOOL_NO_ANSWER)

_ABSURD = (
    "火星",
    "比特币",
    "量子计算",
    "核电站",
    "欧洲门店",
)
_FOREIGN_COMPANY = ("瑞幸",)

# Longer / more specific first.
_INDICATOR_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"经营(活动)?(所得|产生的)?现金|operating cash",
            re.I,
        ),
        "operating_cashflow",
    ),
    (
        re.compile(
            r"归母|净利|净利润|年内溢利|年内亏损|net income|net profit",
            re.I,
        ),
        "net_profit",
    ),
    (re.compile(r"总资产|total assets", re.I), "total_assets"),
    (
        re.compile(r"净资产|股东权益|net assets|total equity", re.I),
        "total_equity",
    ),
    (re.compile(r"毛利(?!率)|gross profit", re.I), "gross_profit"),
    (
        re.compile(
            r"营业收入|总收入|营收|total revenues?|(?<![同店客单])收入",
            re.I,
        ),
        "revenue",
    ),
]

_STATEMENT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"已付股息|dividends paid|派息", re.I), "已付股息"),
    (
        re.compile(r"资本开支|资本支出|购置物业|购买物业|capex", re.I),
        "资本开支",
    ),
    (re.compile(r"(?<![已付])股息|dividend", re.I), "已付股息"),
    (re.compile(r"减值|impairment", re.I), "减值"),
]

_SEARCH_RE = re.compile(
    r"翻台率|同店|客单价|师徒|阿米巴|门店净增|外卖|员工激励|"
    r"same-store|k-?coffee|肯悦|啄木鸟|table turnover|"
    r"store count|store openings|digital",
    re.I,
)

_IMPAIRMENT_RE = re.compile(r"减值|impairment", re.I)


def route(question: str, company: str | None = None) -> dict[str, Any]:
    """Return {tool, reason, company, year, name|keyword, fallback}."""
    q = search.normalize_query(question or "")
    years = search.query_years(q)
    year = years[0] if years else None
    base: dict[str, Any] = {
        "company": company,
        "year": year,
        "query": q,
        "fallback": None,
        "name": None,
        "keyword": None,
    }
    if not q:
        return {**base, "tool": TOOL_SEARCH, "reason": "empty_query"}

    if any(term in q for term in _ABSURD):
        return {**base, "tool": TOOL_NO_ANSWER, "reason": "out_of_corpus_entity"}

    if company:
        for other in _FOREIGN_COMPANY:
            if other in q and other not in company:
                return {
                    **base,
                    "tool": TOOL_NO_ANSWER,
                    "reason": "company_mismatch",
                }

    if years and (max(years) >= 2026 or min(years) <= 1999):
        return {**base, "tool": TOOL_NO_ANSWER, "reason": "year_out_of_corpus"}

    if _SEARCH_RE.search(q) and not _looks_like_line_item(q):
        return {**base, "tool": TOOL_SEARCH, "reason": "operating_narrative"}

    for pat, keyword in _STATEMENT_RULES:
        if pat.search(q):
            fallback = TOOL_SEARCH if _IMPAIRMENT_RE.search(keyword) or _IMPAIRMENT_RE.search(q) else None
            return {
                **base,
                "tool": TOOL_STATEMENTS,
                "keyword": keyword,
                "fallback": fallback,
                "reason": "statement_line",
            }

    for pat, name in _INDICATOR_RULES:
        if pat.search(q):
            return {
                **base,
                "tool": TOOL_INDICATORS,
                "name": name,
                "reason": "indicator_metric",
            }

    return {**base, "tool": TOOL_SEARCH, "reason": "default_search"}


def _looks_like_line_item(q: str) -> bool:
    return any(pat.search(q) for pat, _ in _STATEMENT_RULES)


def route_hit(decision: dict[str, Any], expected_tool: str | None) -> bool:
    if not expected_tool:
        return False
    return decision.get("tool") == expected_tool
