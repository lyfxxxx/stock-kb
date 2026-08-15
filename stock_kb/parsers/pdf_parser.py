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
    hits: list[tuple[int, str]] = []
    for p in pages:
        low = p["content"].lower()
        for stmt, keys in STATEMENT_KEYWORDS.items():
            if any(k in low for k in keys):
                hits.append((p["page_no"], stmt))
    return hits


def extract_statements_from_pages(
    pages: list[dict[str, Any]],
    company: str,
    report_title: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_by_no = {p["page_no"]: p for p in pages}
    for page_no, stmt in detect_statement_pages(pages):
        page = page_by_no.get(page_no)
        if not page or not _is_statement_title_page(page):
            continue
        text = page.get("content_orig") or page["content"]
        years = _detect_year_columns(text)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
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
                        "unit": None,
                        "currency": None,
                        "year": year,
                        "page_no": page_no,
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


def _detect_year_columns(text: str) -> list[int]:
    years: list[int] = []
    for line in text.splitlines()[:20]:
        for m in YEAR_RE.finditer(line):
            y = int(m.group(0))
            if y not in years:
                years.append(y)
        if len(years) >= 2:
            break
    return years


def _is_statement_title_page(page: dict[str, Any]) -> bool:
    text = page.get("content_orig") or page["content"]
    for line in text.splitlines()[:10]:
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("consolidated statement") or low.startswith("consolidated statements"):
            return True
        if low.startswith("consolidated balance sheet") or low.startswith("balance sheet"):
            return True
        if line.startswith("綜合") or line.startswith("综合"):
            return True
        if "（續）" in line or "（续）" in line or "(continued)" in low:
            return True
        if low.startswith("statement of financial position") or low.startswith("statement of cash flows"):
            return True
    return False


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
