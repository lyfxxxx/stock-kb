"""SEC submissions：最近一份 10-K，以及最近一份 10-Q（没有则不猜 6-K）。"""

from __future__ import annotations

import re
from typing import Any, Callable

SUBMISSIONS_ROOT = "https://data.sec.gov/submissions"
ARCHIVES_ROOT = "https://www.sec.gov/Archives/edgar/data"

HttpGet = Callable[..., bytes]


def cik_digits(cik: str) -> str:
    return re.sub(r"\D", "", str(cik or ""))


def cik_10(cik: str) -> str:
    return cik_digits(cik).zfill(10)


def submissions_url(cik: str) -> str:
    return f"{SUBMISSIONS_ROOT}/CIK{cik_10(cik)}.json"


def archive_url(cik: str, accession: str, primary_document: str) -> str:
    acc = str(accession or "").replace("-", "")
    primary = str(primary_document or "").lstrip("/")
    return f"{ARCHIVES_ROOT}/{int(cik_digits(cik))}/{acc}/{primary}"


def sec_headers(user_agent: str, *, json_body: bool) -> dict[str, str]:
    headers = {"User-Agent": user_agent}
    headers["Accept"] = "application/json" if json_body else "*/*"
    return headers


def latest_periodic(submissions: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    """返回最近 10-K 与最近 10-Q。没有 10-Q 时不从 6-K 推断。"""
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    forms = list(recent.get("form") or [])
    accessions = list(recent.get("accessionNumber") or [])
    primaries = list(recent.get("primaryDocument") or [])
    dates = list(recent.get("filingDate") or [])
    picked: dict[str, dict[str, Any] | None] = {"10-K": None, "10-Q": None}
    for index, form in enumerate(forms):
        kind = _periodic_kind(form)
        if kind is None:
            continue
        item = {
            "form": form,
            "kind": "annual" if kind == "10-K" else "interim",
            "form_kind": kind,
            "accession": accessions[index] if index < len(accessions) else "",
            "primary": primaries[index] if index < len(primaries) else "",
            "filing_date": dates[index] if index < len(dates) else "",
            "index": index,
        }
        current = picked[kind]
        if current is None or _newer(item, current):
            picked[kind] = item
    return picked


def _periodic_kind(form: str | None) -> str | None:
    text = str(form or "").upper()
    if text == "10-K" or text.startswith("10-K/"):
        return "10-K"
    if text == "10-Q" or text.startswith("10-Q/"):
        return "10-Q"
    return None


def _newer(item: dict[str, Any], current: dict[str, Any]) -> bool:
    left = str(item.get("filing_date") or "")
    right = str(current.get("filing_date") or "")
    if left != right:
        return left > right
    return int(item["index"]) < int(current["index"])
