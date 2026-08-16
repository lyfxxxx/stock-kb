from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber

from stock_kb.textutil import to_simplified


STATEMENT_KEYWORDS = {
    "income": [
        "利润表",
        "损益表",
        "综合收益表",
        "statement of profit",
        "statement of income",
        "statements of income",
        "income statement",
        "statement of comprehensive income",
        "statements of comprehensive income",
    ],
    "balance": [
        "资产负债表",
        "财务状况表",
        "statement of financial position",
        "statements of financial position",
        "balance sheet",
        "balance sheets",
    ],
    "cashflow": [
        "现金流量表",
        "cash flow statement",
        "statements of cash flows",
        "cash flows",
    ],
    "equity": [
        "权益变动表",
        "statement of changes in equity",
        "statements of equity",
    ],
}

NUMBER_RE = re.compile(r"\(?\s*-?\s*[\d,]+(?:\.\d+)?\s*\)?")
YEAR_RE = re.compile(r"(19|20)\d{2}")
JUNK_NAMES = {
    "rmb'000",
    "rmb000",
    "人民币千元",
    "人民幣千元",
    "人民币百万元",
    "人民幣百萬元",
    "人民币元",
    "人民幣元",
    "notes",
    "note",
    "附註",
    "附注",
    "項目",
    "项目",
    "item",
    "单位",
    "單位",
}

# 只有整行与这些标题精确匹配（允许标题末尾的 continued/未经审核 等后缀）
# 才认为该页是三大报表页；附注、管理层讨论、财务摘要中的“提到报表标题”不算。
_STATEMENT_TITLE_TYPES = {
    "consolidated statement of profit or loss and other comprehensive income": "income",
    "consolidated statement of comprehensive income": "income",
    "consolidated statements of income": "income",
    "consolidated income statement": "income",
    "statement of comprehensive income": "income",
    "statements of comprehensive income": "income",
    "statement of income": "income",
    "statements of income": "income",
    "income statement": "income",
    "综合损益及其他全面收益表": "income",
    "综合全面收益表": "income",
    "综合收益表": "income",
    "综合损益表": "income",
    "损益表": "income",
    "利润表": "income",
    "合并损益表": "income",
    "合并利润表": "income",
    "consolidated statement of financial position": "balance",
    "statement of financial position": "balance",
    "statements of financial position": "balance",
    "consolidated balance sheet": "balance",
    "consolidated balance sheets": "balance",
    "balance sheet": "balance",
    "balance sheets": "balance",
    "综合财务状况表": "balance",
    "财务状况表": "balance",
    "资产负债表": "balance",
    "合并资产负债表": "balance",
    "consolidated statement of cash flows": "cashflow",
    "consolidated statements of cash flows": "cashflow",
    "statement of cash flows": "cashflow",
    "statements of cash flows": "cashflow",
    "cash flow statement": "cashflow",
    "综合现金流量表": "cashflow",
    "现金流量表": "cashflow",
    "合并现金流量表": "cashflow",
    "consolidated statement of changes in equity": "equity",
    "consolidated statement of changes in shareholders' equity": "equity",
    "consolidated statement of changes in stockholders' equity": "equity",
    "statement of changes in equity": "equity",
    "statements of changes in equity": "equity",
    "statement of changes in shareholders' equity": "equity",
    "statement of stockholders' equity": "equity",
    "综合权益变动表": "equity",
    "权益变动表": "equity",
    "股东权益变动表": "equity",
    "合并权益变动表": "equity",
}

_TITLE_SUFFIXES = (
    "(continued)",
    "(cont'd)",
    "(cont’d)",
    "(unaudited)",
    "（续）",
    "（續）",
)


def extract_pdf(
    path: str | Path,
    ocr_langs: str = "chi_sim+eng",
    ocr_min_chars: int = 80,
    use_ocr: bool = False,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = (page.extract_text() or "").strip()
            char_count = len(text)
            is_ocr = 0
            if use_ocr and char_count < ocr_min_chars:
                ocr_text = _ocr_page(page, ocr_langs)
                if ocr_text:
                    text = ocr_text
                    char_count = len(text)
                    is_ocr = 1
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            pages.append(
                {
                    "page_no": i,
                    "content": text,
                    "char_count": char_count,
                    "is_ocr": is_ocr,
                    "tables": tables,
                }
            )
    return pages


def detect_statement_pages(pages: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """返回“标题行明确是三大报表标题”的页面。为兼容旧接口，逐页判定报表类型。"""
    hits: list[tuple[int, str]] = []
    for p in pages:
        stmt = _statement_type_from_page(p)
        if stmt:
            hits.append((p["page_no"], stmt))
    return hits


def extract_statements_from_pages(
    pages: list[dict[str, Any]],
    company: str,
    report_title: str,
    report_year: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        stmt = _statement_type_from_page(page)
        if stmt is None:
            continue
        text = page.get("content_orig") or page["content"]
        years = _detect_year_columns(text, report_year=report_year)
        unit, currency = _detect_unit_currency(text)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "(cid:" in line.casefold():
                continue
            if re.match(r"^[ivx]+\.\s", line, re.IGNORECASE):
                continue
            if line.casefold().startswith("notes:"):
                # 报表标题之后进入附注说明区，后面的数字不是报表行项目。
                break
            if _is_header_or_junk_line(line):
                continue
            matches = list(NUMBER_RE.finditer(line))
            if not matches:
                continue
            k = len(years) if years else 1
            if len(matches) < k:
                continue
            value_matches = matches[-k:]
            label = line[: value_matches[0].start()].strip()
            label = re.sub(r"\s+\d{1,3}$", "", label).strip()
            if _is_junk_name(label):
                continue
            for idx, m in enumerate(value_matches):
                value = _parse_number(m.group(0))
                if value is None:
                    continue
                year = years[idx] if idx < len(years) else None
                rows.append(
                    {
                        "statement_type": stmt,
                        "line_name_orig": label,
                        "line_name_norm": to_simplified(label),
                        "value": value,
                        "unit": unit,
                        "currency": currency,
                        "year": year,
                        "page_no": page["page_no"],
                        "table_index": 0,
                        "source_id": None,
                    }
                )
    return rows


def _parse_table(table: list[list[Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for r in table:
        rows.append([(c or "").strip() for c in r])
    return rows


def _parse_number(cell: str) -> float | None:
    if not cell:
        return None
    m = NUMBER_RE.search(cell)
    if not m:
        return None
    raw = m.group(0)
    negative = raw.strip().startswith("(")
    raw = raw.replace(",", "").replace("(", "").replace(")", "").strip()
    try:
        value = float(raw)
        return -value if negative else value
    except ValueError:
        return None


def _extract_year(cell: str) -> int | None:
    m = YEAR_RE.search(cell)
    return int(m.group(0)) if m else None


def _extract_currency(cell: str) -> str | None:
    for cur in ("人民币", "RMB", "CNY", "美元", "USD", "港元", "HKD", "港币"):
        if cur in cell:
            return cur
    return None


def _is_junk_name(name: str) -> bool:
    n = name.strip().casefold().replace("’", "'").replace(" ", "")
    if not n:
        return True
    if n in JUNK_NAMES:
        return True
    if not re.search(r"[\u4e00-\u9fff]|[a-z]", n):
        return True
    return False


def _detect_year_columns(text: str, report_year: int | None = None) -> list[int]:
    """从表头行识别年份列。

    只接受“同一行出现至少两个年份”的表头；如果调用方提供 report_year，
    则优先选包含该年份的表头，避免把附注里的 2001/2014/2015 等历史年份当列。
    """
    best: list[int] = []
    for line in text.splitlines()[:30]:
        found = list(dict.fromkeys(int(m.group(0)) for m in YEAR_RE.finditer(line)))
        if len(found) < 2:
            continue
        if report_year is not None and report_year not in found:
            continue
        best = found
        break
    if best:
        return best

    if report_year is not None:
        return [report_year]

    for line in text.splitlines()[:30]:
        m = YEAR_RE.search(line)
        if m:
            return [int(m.group(0))]
    return []


def _normalize_title_line(line: str) -> str:
    n = re.sub(r"\s+", " ", to_simplified(line).strip().casefold()).strip()
    for suffix in _TITLE_SUFFIXES:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
            break
    return n


def _statement_type_from_page(page: dict[str, Any]) -> str | None:
    text = page.get("content_orig") or page["content"]
    for line in text.splitlines()[:8]:
        line = line.strip()
        if not line:
            continue
        # 明确排除附注页：首行是 Notes/APPENDIX 且后面没有独立报表标题时不应返回类型。
        stmt = _STATEMENT_TITLE_TYPES.get(_normalize_title_line(line))
        if stmt:
            return stmt
        low = to_simplified(line).strip().casefold()
        if low.startswith("notes to") or low.startswith("note "):
            return None
    return None


def _is_statement_title_page(page: dict[str, Any]) -> bool:
    return _statement_type_from_page(page) is not None


def _detect_unit_currency(text: str) -> tuple[str | None, str | None]:
    """从报表页头部识别单位与币种，归一化为中文单位名和 ISO 币种代码。"""
    head = to_simplified("\n".join(text.splitlines()[:30])).casefold()
    has_cny = bool(re.search(r"人民币|(?<![a-z])(rmb|cny)(?![a-z])", head))
    has_usd = bool(re.search(r"美元|usd|us\$|\$\s*million", head))
    has_hkd = bool(re.search(r"港元|港币|hkd|hk\$", head))

    if has_cny:
        currency = "CNY"
    elif has_hkd:
        currency = "HKD"
    elif has_usd:
        currency = "USD"
    else:
        currency = None

    unit_by_currency = {
        "CNY": ("百万元", "千元", "元"),
        "USD": ("百万美元", "千美元", "美元"),
        "HKD": ("百万港元", "千港元", "港元"),
    }
    default_units = ("百万元", "千元", "元")
    units = unit_by_currency.get(currency, default_units)

    if "百万" in head or "million" in head:
        unit = units[0]
    elif "千" in head or "thousand" in head or re.search(r"rmb\s*[’']?000", head):
        unit = units[1]
    elif has_cny or has_usd or has_hkd:
        unit = units[2]
    else:
        unit = None
    return unit, currency


def _is_header_or_junk_line(line: str) -> bool:
    n = to_simplified(line).strip().casefold()
    if not n:
        return True
    starts = (
        "notes",
        "附註",
        "附注",
        "項目",
        "项目",
        "rmb",
        "人民幣千元",
        "人民币千元",
        "人民幣百萬元",
        "人民币百万元",
        "截至",
        "for the year",
        "as at",
        "於",
        "at january",
        "at december",
        "consolidated statement",
        "綜合損益",
        "综合损益",
        "綜合財務狀況",
        "综合财务状况",
        "綜合現金流量",
        "综合现金流量",
        "綜合權益",
        "综合权益",
        "本集團",
        "本集团",
        "note",
    )
    if n.startswith(starts):
        return True
    if "rmb’000" in n or "rmb'000" in n or "人民幣千元" in n:
        return True
    if "annual report" in n or re.search(r"form\s*10[\s\-–—]*k", n):
        return True
    if not re.search(r"[\u4e00-\u9fff]|[a-z]", n):
        return True
    return False


def _ocr_page(page: Any, langs: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "page.png")
        try:
            page.to_image(resolution=200).save(png)
            out = subprocess.run(
                ["tesseract", png, "stdout", "-l", langs, "--psm", "3"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            return (out.stdout or "").strip()
        except Exception:
            return ""
