"""披露易标题搜索。接口不稳定：base_url 和 http_get 都可以注入。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode

DEFAULT_BASE_URL = "https://www1.hkexnews.hk"
FILE_HOST = "https://www1.hkexnews.hk"

HttpGet = Callable[..., bytes]

_CODE_KEYS = ("code", "stockCode", "stock_code", "c", "SC")
_ID_KEYS = ("stockId", "stock_id", "id", "i", "ID")
_LINK_KEYS = ("FILE_LINK", "file_url", "fileUrl", "FILE_URL")
_TITLE_KEYS = ("TITLE", "title", "NEWS_TITLE", "ltxt", "SHORT_TEXT")
_DATE_KEYS = ("DATE_TIME", "date_time", "date", "RELEASE_TIME", "DATE")


def stock_list_url(code: str, base_url: str = DEFAULT_BASE_URL) -> str:
    # 不带 callback 时 prefix.do 只回一个空行，JSON 解析会失败。
    query = urlencode(
        {"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"}
    )
    return f"{base_url.rstrip('/')}/search/prefix.do?{query}"


def title_search_url(stock_id: str, base_url: str = DEFAULT_BASE_URL) -> str:
    query = urlencode(
        {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": str(stock_id),
            "documentType": "-1",
            "searchType": "1",
            "rowRange": "100",
            "lang": "E",
        }
    )
    return f"{base_url.rstrip('/')}/search/titleSearchServlet.do?{query}"


def norm_code(code: str) -> str:
    digits = re.sub(r"\D", "", str(code or ""))
    return digits.lstrip("0") or "0"


def parse_json_payload(body: bytes | str) -> Any:
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    match = re.search(r"\((\{.*\}|\[.*\])\)\s*;?\s*$", text, re.S)
    if match:
        return json.loads(match.group(1))
    return json.loads(text)


def stock_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("stockInfo", "data", "result", "rows"):
            value = payload.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = None
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                return stock_rows(value)
    return []


def lookup_stock_id(payload: Any, code: str) -> str | None:
    want = norm_code(code)
    for row in stock_rows(payload):
        raw = _first(row, _CODE_KEYS)
        if raw is None:
            continue
        if str(raw).strip() == str(code).strip() or norm_code(str(raw)) == want:
            stock_id = _first(row, _ID_KEYS)
            if stock_id is not None and str(stock_id).strip():
                return str(stock_id).strip()
    return None


def search_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("result", "newsInfoLst", "resultList", "data"):
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    continue
            rows = search_rows(value)
            if rows:
                return rows
    return []


def filing_kind(title: str) -> str | None:
    text = str(title or "")
    lowered = text.lower()
    if "interim" in lowered or "中期" in text:
        return "interim"
    if "annual report" in lowered or "年报" in text or "年報" in text:
        return "annual"
    return None


def absolute_file_url(link: str) -> str:
    text = str(link or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if not text.startswith("/"):
        text = "/" + text
    return FILE_HOST + text


def pick_latest_filings(payload: Any) -> dict[str, dict[str, Any]]:
    """最近一份年报和最近一份中期报告。标题不匹配的行忽略。"""
    chosen: dict[str, tuple[datetime | None, int, dict[str, Any]]] = {}
    for index, row in enumerate(search_rows(payload)):
        title = str(_first(row, _TITLE_KEYS) or "")
        kind = filing_kind(title)
        link = _first(row, _LINK_KEYS)
        if kind is None or not link:
            continue
        when = _parse_date(_first(row, _DATE_KEYS))
        item = {
            "kind": kind,
            "title": title,
            "file_url": absolute_file_url(str(link)),
        }
        current = chosen.get(kind)
        rank = (when or datetime.min, -index)
        if current is None or rank > (current[0] or datetime.min, -current[1]):
            chosen[kind] = (when, index, item)
    return {kind: value[2] for kind, value in chosen.items()}


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 3], fmt)
        except ValueError:
            continue
    match = re.search(r"(20\d{2})[-/](\d{2})[-/](\d{2})", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None
