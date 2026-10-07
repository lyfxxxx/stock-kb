"""解析版本与文档身份。

PARSE_VERSION 在这里。解析规则变了就改这个常量：字节没变的文件下次扫描就地重解析，不另开一行。
"""

from __future__ import annotations

import re
from pathlib import Path

from stock_kb.parsers.pdf_parser import is_statement_page
from stock_kb.textutil import to_simplified

PARSE_VERSION = "2026-10-02.1"

_FILING_TYPES = frozenset({"annual", "interim", "q3", "prospectus"})
_DATE_DASH = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")
_DATE_COMPACT = re.compile(
    r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)"
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_HK_TOKEN = re.compile(r"(?<![a-z0-9])hk(?![a-z0-9])")
_US_10K = re.compile(r"(?<![a-z0-9])10\s*-?\s*k(?![a-z0-9])")
_US_20F = re.compile(r"(?<![a-z0-9])20\s*-?\s*f(?![a-z0-9])")


def decide_scan_action(
    *,
    existing_sha: str | None,
    new_sha: str | None,
    existing_parse_version: str | None,
    size_unchanged: bool = False,
    mtime_unchanged: bool = False,
    rebuild: bool = False,
    manifest_status: str | None = None,
    report_status: str | None = None,
) -> str:
    """返回 skip、reparse、new_version 或 parse。

    字节（sha）与 PARSE_VERSION 都没变，且 size/mtime 没变、manifest 仍为 ok：skip。
    sha 相同但版本过期：reparse，不新增行。sha 变了：new_version。
    report_status 不参与 skip；调用方用 manifest 状态表达「这份路径已成功扫过」。
    """
    del report_status  # 保留参数，避免调用方把报告状态误当成跳过条件
    if existing_sha and new_sha and existing_sha != new_sha:
        return "new_version"
    if not existing_sha:
        return "parse"
    unchanged = (
        not rebuild
        and size_unchanged
        and mtime_unchanged
        and manifest_status == "ok"
        and existing_parse_version == PARSE_VERSION
        and (new_sha is None or new_sha == existing_sha)
    )
    if unchanged:
        return "skip"
    return "reparse"


# 只认文件名和标题。父目录叫「年报」时，里面的美股 10-K 不能被判成港股。
_HK_FILING_NAME_MARKS = ("年度报告", "中期报告", "中期報告", "年报", "年報", "中报")


def _filing_label(path: str, title: str) -> str:
    stem = Path(str(path)).stem if path else ""
    return f"{stem}\n{title or ''}"


def detect_market(path: str, title: str) -> str:
    """路径或标题含港 / hk → HK。

    文件名（不含父目录）含年报、年度报告、中报、中期报告 → HK。
    10-K、20-F、us annual，或文件名含 annual report 且还不是 HK → US。
    """
    raw = f"{path}\n{title}"
    lowered = raw.lower()
    spaced = re.sub(r"[\s_\-]+", " ", lowered)
    if (
        "港" in raw
        or "hk_annual" in lowered
        or "hk annual" in spaced
        or _HK_TOKEN.search(lowered)
    ):
        return "HK"
    label = _filing_label(path, title)
    if any(mark in label for mark in _HK_FILING_NAME_MARKS):
        return "HK"
    if _US_10K.search(spaced) or _US_20F.search(spaced) or "us annual" in spaced:
        return "US"
    label_spaced = re.sub(r"[\s_\-]+", " ", label.lower())
    if "annual report" in label_spaced:
        return "US"
    return "UNK"


def event_date_from_filename(filename: str) -> str:
    """文件名里第一个 YYYY-MM-DD，否则 YYYYMMDD，否则年份-01-01，否则 undated。"""
    name = Path(filename).name
    dashed = _DATE_DASH.search(name)
    if dashed:
        return f"{dashed.group(1)}-{dashed.group(2)}-{dashed.group(3)}"
    compact = _DATE_COMPACT.search(name)
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    year = _YEAR.search(name)
    if year:
        return f"{year.group(1)}-01-01"
    return "undated"


def locator_for(path: str, source_url: str | None) -> str:
    if source_url and str(source_url).strip():
        return str(source_url).strip()
    return str(path)


def build_logical_key(
    *,
    company: str,
    report_type: str,
    year: int | None,
    period_type: str | None,
    language: str | None,
    path: str,
    title: str,
    source_url: str | None = None,
) -> str:
    """不含 sha。other 用路径，扫描时不把不同路径的 other 互相标 superseded。"""
    if report_type in _FILING_TYPES:
        year_s = "" if year is None else str(year)
        market = detect_market(path, title or "")
        return (
            f"{company}|{report_type}|{year_s}|{period_type or ''}|"
            f"{language or ''}|{market}"
        )
    if report_type == "transcript":
        return (
            f"{company}|transcript|{event_date_from_filename(path)}|"
            f"{locator_for(path, source_url)}"
        )
    if report_type == "research":
        return f"{company}|research|{locator_for(path, source_url)}"
    return f"{company}|other|{path}"


def page_kind_for(page: dict, report_type: str | None) -> str:
    """cover / toc / statement / body / transcript。报表页判断复用 pdf_parser。"""
    if report_type == "transcript":
        return "transcript"
    if is_statement_page(page):
        return "statement"
    orig = page.get("content_orig")
    if orig is None:
        orig = page.get("content") or ""
    orig_s = str(orig)
    head = orig_s[:400]
    head_s = to_simplified(head)
    if "目录" in head_s or "table of contents" in head.lower():
        return "toc"
    page_no = page.get("page_no")
    char_count = page.get("char_count")
    if char_count is None:
        char_count = len(orig_s)
    if page_no == 1 and (int(char_count) < 400 or "封面" in head_s):
        return "cover"
    return "body"
