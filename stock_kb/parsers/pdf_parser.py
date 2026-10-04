from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
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

# 港股/双语年报用独立短横「–」表示零值列（如「Dividends paid 已付股息 – (92,781)」）。
# 只按数字找单元格会让这类整行因列数不足被丢弃，把短横当作空值单元格参与对齐。
_DASH_CHARS = "–—‒―−-"
CELL_RE = re.compile(
    r"\(?\s*-?\s*[\d,]+(?:\.\d+)?\s*\)?"
    rf"|(?<![\w.,])[{_DASH_CHARS}](?![\w.,])"
)
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
    # 百胜早期 10-K（2016-2018）标题用 "Consolidated and Combined ..."
    "consolidated and combined statements of income": "income",
    "consolidated and combined statement of income": "income",
    "consolidated and combined statements of comprehensive income": "income",
    "consolidated and combined statements of cash flows": "cashflow",
    "consolidated and combined statement of cash flows": "cashflow",
    "consolidated and combined balance sheets": "balance",
    "consolidated and combined balance sheet": "balance",
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
    "(loss)",
    "（续）",
    "（續）",
    "（未经审核）",
    "（未經審核）",
)

# 中报标题常带 Condensed/简明 前缀（如 "Condensed Consolidated Statement of ..."），
# 剥掉后再精确匹配词典，保持「整行命中」语义以排除附注/摘要页误判。
_TITLE_PREFIXES = ("condensed", "简明")


_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")
# OCR 输出的有效性闸门：低于该长度或有效字符占比过低的输出视为噪声，不采用。
_OCR_MIN_VALID_CHARS = 50
_OCR_MIN_VALID_RATIO = 0.5
# 页面 (cid:xx) token 字符占比超过该阈值视为字体缺 ToUnicode 的乱码页。
_CID_GARBLED_RATIO = 0.1


def _cid_ratio(text: str) -> float:
    if not text:
        return 0.0
    cid_len = sum(len(m.group(0)) for m in _CID_TOKEN_RE.finditer(text))
    return cid_len / len(text)


def _text_quality_ok(text: str) -> bool:
    if len(text) < _OCR_MIN_VALID_CHARS:
        return False
    valid = sum(1 for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return valid / len(text) >= _OCR_MIN_VALID_RATIO


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
            # 乱码页（字体缺 ToUnicode）字符数可能很高但内容不可用，
            # 也需要走 OCR，不能只用 char_count 判断。
            garbled = _cid_ratio(text) > _CID_GARBLED_RATIO
            if use_ocr and (char_count < ocr_min_chars or garbled):
                ocr_text = _ocr_page(page, ocr_langs)
                if ocr_text and _text_quality_ok(ocr_text):
                    text = ocr_text
                    char_count = len(text)
                    is_ocr = 1
                elif garbled:
                    # 乱码页 OCR 失败/输出无效：保留原文但标记，检索侧排除。
                    is_ocr = 2
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
        page_ocr = int(page.get("is_ocr") or 0)
        page_no = page["page_no"]
        # is_ocr=2 页只保留能对上标签+数字的稀疏行，供审计；不参与无标签小计，
        # 也不做 OCR 标签块/数字块配对。is_ocr=1 在行对齐失败时再试配对。
        page_rows = _extract_aligned_statement_rows(
            text=text,
            stmt=stmt,
            years=years,
            unit=unit,
            currency=currency,
            page_no=page_no,
            is_ocr=page_ocr,
            allow_unlabeled_subtotal=page_ocr == 0,
        )
        if page_ocr == 1:
            paired = _pair_ocr_label_number_columns(
                text=text,
                stmt=stmt,
                years=years,
                unit=unit,
                currency=currency,
                page_no=page_no,
                is_ocr=page_ocr,
            )
            if _prefer_ocr_pairing(paired, page_rows):
                page_rows = paired
        rows.extend(page_rows)
    return rows


def _extract_aligned_statement_rows(
    *,
    text: str,
    stmt: str,
    years: list[int],
    unit: str | None,
    currency: str | None,
    page_no: int,
    is_ocr: int,
    allow_unlabeled_subtotal: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # 无数字的行有两种：小节标题（「Current Assets 流動資產」，持久，用于命名
    # 其后的小计行）与折行标签上半行（一次性，与下一行标签拼接）。
    # 小节标题只允许资产负债表白名单，避免折行残片顶掉小计挂名。
    section_header: str | None = None
    wrap_head: str | None = None
    section_stack: list[str | None] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if "(cid:" in line.casefold():
            continue
        if re.match(r"^[ivx]+\.\s", line, re.IGNORECASE):
            continue
        if line.casefold().startswith("notes:"):
            break
        if _is_header_or_junk_line(line):
            continue
        matches = list(CELL_RE.finditer(line))
        if not matches:
            if _is_junk_name(line) or _is_orphan_fragment(line):
                wrap_head = None
                continue
            wrap_head = line
            if _is_section_header(line):
                section_stack.append(section_header)
                section_header = line
            continue
        k = len(years) if years else 1
        if len(matches) < k:
            continue
        value_matches = matches[-k:]
        label = line[: value_matches[0].start()].strip()
        label = re.sub(r"\s+\d{1,3}$", "", label).strip()
        is_subtotal = 0
        if not label:
            if not allow_unlabeled_subtotal:
                wrap_head = None
                continue
            # 无标签小计行（港式资产负债表小节合计不带行名），挂最近的小节标题。
            # 整行必须是纯数字/括号/短横；小节标题必须在白名单内。
            if (
                not section_header
                or not _is_section_header(section_header)
                or not re.fullmatch(r"[0-9,.\s()\[\]{}–—‒―−%+]+", line)
            ):
                continue
            label = section_header
            is_subtotal = 1
            wrap_head = None
        else:
            if wrap_head and _looks_like_continuation(wrap_head, label):
                label = f"{wrap_head} {label}"
                if section_header == wrap_head and section_stack:
                    section_header = section_stack.pop()
            wrap_head = None
        if (
            _is_junk_name(label)
            or _is_orphan_fragment(label)
            or _starts_as_fragment(label)
        ):
            continue
        rows.extend(
            _emit_value_rows(
                stmt=stmt,
                label=label,
                value_matches=value_matches,
                years=years,
                unit=unit,
                currency=currency,
                page_no=page_no,
                line_no=line_no,
                is_subtotal=is_subtotal,
                is_ocr=is_ocr,
            )
        )
    return rows


_WRAP_ENDINGS = (
    "的",
    "及",
    "與",
    "与",
    "或",
    "和",
    "以",
    "金融",
    "預",
    "预",
    "付",
    "損",
    "损",
    "資",
    "负",
    "負",
    "（",
    "(",
)
_WRAP_STARTS = {
    "的",
    "及",
    "與",
    "与",
    "或",
    "和",
    "以",
    "產",
    "产",
    "債",
    "债",
    "益",
    "付",
    "損",
    "损",
    "款",
}
_ORPHAN_FRAG_RE = re.compile(
    r"^(?:的|及|與|与|或|和|以|益|產|产|債|债|損|损|付款項|付款项|"
    r"金融資產|金融资产|金融負債|金融负债).{0,12}$"
)
_SECTION_HEADER_EXACT = {
    "assets",
    "liabilities",
    "equity",
    "资产",
    "负债",
    "权益",
    "currentassets",
    "currentliabilities",
    "noncurrentassets",
    "noncurrentliabilities",
    "流动资产",
    "流动负债",
    "非流动资产",
    "非流动负债",
}
_SECTION_HEADER_PARTS = (
    "currentassets",
    "currentliabilities",
    "noncurrentassets",
    "noncurrentliabilities",
    "流动资产",
    "流动负债",
    "非流动资产",
    "非流动负债",
)
_MONTH_NAME_RE = re.compile(
    r"january|february|march|april|may|june|july|august|september|"
    r"october|november|december",
    re.IGNORECASE,
)


def _ends_mid_phrase(line: str) -> bool:
    """行尾是未闭合括号或连词，说明该行是折行标签的上半行。"""
    s = (line or "").rstrip()
    if not s:
        return False
    if s.count("（") > s.count("）") or s.count("(") > s.count(")"):
        return True
    # 「金融」：港股把 FVTPL 折成「…的金融」/「負債」。
    # 「預/資/負/損/付」：預付款項、資產、負債、損益在格子里折开。
    return s.endswith(_WRAP_ENDINGS)


def _starts_as_fragment(line: str) -> bool:
    """行首小写字母或连词开头，多为折行标签的中间片段。"""
    head = (line or "").strip()[:1]
    if head.isascii() and head.isalpha() and head.islower():
        return True
    return head in _WRAP_STARTS


def _looks_like_continuation(prev: str, label: str) -> bool:
    """判断上一行（无数字）与当前行标签是否为同一科目折行。"""
    if not prev:
        return False
    if _ends_mid_phrase(prev):
        return True
    return _starts_as_fragment(label)


def _is_section_header(line: str) -> bool:
    """资产负债表白名单小节标题。不含 Total Current Assets 这类合计行。"""
    n = re.sub(r"\s+", " ", to_simplified(line or "").strip().casefold())
    compact = n.replace(" ", "").replace("-", "")
    if not compact or compact.startswith("total"):
        return False
    if compact in _SECTION_HEADER_EXACT:
        return True
    for left in _SECTION_HEADER_PARTS:
        for right in _SECTION_HEADER_PARTS:
            if compact == left + right:
                return True
    return False


def _is_orphan_fragment(name: str) -> bool:
    """折行没拼上时留下的短残片，不当科目入库。"""
    n = (name or "").strip()
    if not n:
        return True
    if re.search(r"[A-Za-z]", n):
        return False
    if _ORPHAN_FRAG_RE.match(n):
        return True
    cjk = re.sub(r"\s+", "", n)
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{1,2}", cjk))


def _is_month_day_header(line: str) -> bool:
    """``June 30, December 31,`` 这类只有月+日、没有科目的表头。"""
    n = to_simplified(line or "").strip()
    months = _MONTH_NAME_RE.findall(n)
    if len(months) < 2:
        return False
    rest = _MONTH_NAME_RE.sub("", n)
    rest = re.sub(r"[\s,./\-–—]", "", rest)
    return bool(rest) and re.fullmatch(r"\d+", rest) is not None


def _emit_value_rows(
    *,
    stmt: str,
    label: str,
    value_matches: list[re.Match[str]],
    years: list[int],
    unit: str | None,
    currency: str | None,
    page_no: int,
    line_no: int,
    is_subtotal: int,
    is_ocr: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, m in enumerate(value_matches):
        cell = m.group(0)
        if not re.search(r"\d", cell):
            continue
        value = _parse_number(cell)
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
                "page_no": page_no,
                "line_no": line_no,
                "is_subtotal": is_subtotal,
                "is_ocr": is_ocr,
                "table_index": 0,
                "source_id": None,
            }
        )
    return rows


def _is_pure_year_header(line: str) -> bool:
    found = list(dict.fromkeys(int(m.group(0)) for m in YEAR_RE.finditer(line)))
    if len(found) < 2:
        return False
    rest = YEAR_RE.sub("", line)
    rest = re.sub(r"[\s,.$]", "", rest)
    return rest == ""


def _is_pure_number_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    tmp = CELL_RE.sub(" ", s)
    tmp = re.sub(rf"[{_DASH_CHARS}一—–$]", " ", tmp)
    tmp = re.sub(r"[\s,]", "", tmp)
    return tmp == "" and bool(
        CELL_RE.search(s) or re.search(rf"[{_DASH_CHARS}一]", s)
    )


def _ocr_label_continues(prev: str, line: str) -> bool:
    if _looks_like_continuation(prev, line):
        return True
    low = (line or "").strip().casefold()
    if low.startswith(("respectively", "shares ", "and ")):
        return True
    if (prev or "").rstrip().endswith((",", ";", "and", "the")):
        return True
    last = re.search(r"([A-Za-z]+)$", (prev or "").strip())
    first = re.search(r"^([a-z]+)", (line or "").strip())
    return bool(last and first and 2 <= len(last.group(1)) <= 8)


def _is_banner_line(line: str) -> bool:
    """全大写横幅（ASSETS / LIABILITIES, REDEEMABLE …）不是科目。"""
    letters = [ch for ch in (line or "") if ch.isalpha()]
    return len(letters) >= 4 and all(ch.isupper() for ch in letters)


def _looks_like_account_label(line: str) -> bool:
    n = (line or "").strip()
    if not n or _is_section_header(n) or _is_orphan_fragment(n) or _is_banner_line(n):
        return False
    if _starts_as_fragment(n) or _is_header_or_junk_line(n):
        return False
    low = n.casefold()
    if low in {"yum china holdings, inc.", "form 10-k", "part ii"}:
        return False
    if _STATEMENT_TITLE_TYPES.get(_normalize_title_line(n)):
        return False
    if low.startswith("(in ") and ("million" in low or "thousand" in low):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", n))


def _collect_ocr_account_labels(lines: list[str]) -> list[str]:
    glued: list[str] = []
    wrap: str | None = None

    def _flush() -> None:
        nonlocal wrap
        if wrap and _looks_like_account_label(wrap):
            glued.append(wrap)
        wrap = None

    for line in lines:
        if _is_section_header(line) or _is_banner_line(line):
            _flush()
            continue
        if _is_header_or_junk_line(line) and not _looks_like_account_label(line):
            _flush()
            continue
        if wrap and _ocr_label_continues(wrap, line):
            wrap = f"{wrap} {line}"
            continue
        if glued and not wrap and _ocr_label_continues(glued[-1], line):
            glued[-1] = f"{glued[-1]} {line}"
            continue
        _flush()
        if _ends_mid_phrase(line) or line.rstrip().endswith((",", ";")):
            wrap = line
            continue
        if _looks_like_account_label(line):
            glued.append(line)
        else:
            wrap = line
    _flush()
    return glued


def _pair_ocr_label_number_columns(
    *,
    text: str,
    stmt: str,
    years: list[int],
    unit: str | None,
    currency: str | None,
    page_no: int,
    is_ocr: int,
) -> list[dict[str, Any]]:
    """OCR 页把标签列和数字列拆成上下两块时，按行序配对。"""
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    year_idx = None
    for i, ln in enumerate(raw_lines):
        if _is_pure_year_header(ln):
            year_idx = i
    if year_idx is None:
        return []
    num_rows: list[tuple[int, str]] = []
    for offset, ln in enumerate(raw_lines[year_idx + 1 :], start=year_idx + 2):
        low = ln.casefold()
        if low.startswith("see accompanying") or low.startswith("notes"):
            break
        if _is_pure_number_line(ln):
            num_rows.append((offset, ln))
            continue
        if num_rows:
            break
    if len(num_rows) < 8:
        return []
    labels = _collect_ocr_account_labels(raw_lines[:year_idx])
    if abs(len(labels) - len(num_rows)) > 3:
        return []
    n = min(len(labels), len(num_rows))
    if n < 8:
        return []
    k = len(years) if years else 1
    rows: list[dict[str, Any]] = []
    for i in range(n):
        label = labels[i]
        line_no, ln = num_rows[i]
        matches = list(CELL_RE.finditer(ln))
        if not matches:
            continue
        value_matches = matches[-k:] if len(matches) >= k else matches
        rows.extend(
            _emit_value_rows(
                stmt=stmt,
                label=label,
                value_matches=value_matches,
                years=years,
                unit=unit,
                currency=currency,
                page_no=page_no,
                line_no=line_no,
                is_subtotal=0,
                is_ocr=is_ocr,
            )
        )
    return rows


def _prefer_ocr_pairing(
    paired: list[dict[str, Any]], fallback: list[dict[str, Any]]
) -> bool:
    if len(paired) < 8:
        return False
    if not fallback:
        return True
    names = [r["line_name_orig"] for r in fallback]
    _common, cnt = Counter(names).most_common(1)[0]
    if cnt >= 8 and cnt / max(len(fallback), 1) >= 0.5:
        return True
    non_sub_p = sum(1 for r in paired if not r["is_subtotal"])
    non_sub_f = sum(1 for r in fallback if not r["is_subtotal"])
    return non_sub_p > non_sub_f + 3


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
    for prefix in _TITLE_PREFIXES:
        if n.startswith(prefix):
            n = re.sub(rf"^{re.escape(prefix)}\s*", "", n).strip()
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


def is_statement_page(page: dict[str, Any]) -> bool:
    """该页是否为三大报表页。标题表只维护在 _STATEMENT_TITLE_TYPES。"""
    return _statement_type_from_page(page) is not None


def _is_statement_title_page(page: dict[str, Any]) -> bool:
    return is_statement_page(page)


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
        "for the six",
        "for the three",
        "for the nine",
        "six months ended",
        "three months ended",
        "nine months ended",
        "as at",
        "於",
        "于",
        "at january",
        "at june",
        "at july",
        "at august",
        "at september",
        "at march",
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
    # 部分 PDF 页脚每个字符被提取两次（「AAnnnnuuaall RReeppoorrtt」），
    # 连续字符去重后再识别 annual report / 年度报告 / Form 10-K。
    dedup = re.sub(r"(.)\1+", r"\1", n)
    if "annual report" in dedup or "年度报告" in dedup or re.search(
        r"form\s*10[\s\-–—]*k", dedup
    ):
        return True
    if _DATE_LINE_RE.search(n):
        # 「于2019年6月30日及2020年…」「August 27, 2020」等表头日期行，
        # 其中的年份数字不是行项目数值。
        return True
    if _is_month_day_header(line):
        return True
    if not re.search(r"[\u4e00-\u9fff]|[a-z]", n):
        # 无字母/CJK 的行通常是页脚页码等噪声；但纯数字行（港式小计
        # 「12,874,180 14,907,039」）要放行给小计逻辑处理。
        return not re.search(r"\d", n)
    return False


# 表头日期行：「于2019年6月30日…」「August 27, 2020」等；月名后跟数字才判定，
# 避免误伤含 may/June 等词的正文行。
_DATE_LINE_RE = re.compile(
    r"[零一二三四五六七八九]*\d{4}年[01]?\d月"
    r"|[01]?\d月[一二三四五六七八九十零\d]{1,3}日"
    r"|(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december)\s+\d{1,2},?\s*\d{2,4}",
    re.IGNORECASE,
)


def _tessdata_env() -> dict[str, str]:
    """tesseract 找不到语言包时（TESSDATA_PREFIX 未设置），从可执行文件位置推导
    tessdata 目录。兼容 conda 两种布局：<env>/Library/bin/tesseract 对应
    <env>/share/tessdata 与 <env>/Library/share/tessdata。"""
    env = os.environ.copy()
    if env.get("TESSDATA_PREFIX"):
        return env
    exe = shutil.which("tesseract")
    if not exe:
        return env
    bin_dir = Path(exe).resolve().parent
    for candidate in (
        bin_dir.parent / "share" / "tessdata",
        bin_dir.parent.parent / "share" / "tessdata",
    ):
        if (candidate / "eng.traineddata").exists():
            env["TESSDATA_PREFIX"] = str(candidate)
            break
    return env


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
                env=_tessdata_env(),
            )
            return (out.stdout or "").strip()
        except Exception:
            return ""
