"""Generation eval: compose notes via skill tool order, then audit citations."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_kb.note_builder import compose_note, format_value

_CITE = re.compile(r"《([^》]+)》\s*第\s*(\d+)\s*页")
# 出处表行：4 列（指标|年份|数值|来源）或 5 列（指标|年份|数值|单位|来源）
_TABLE_ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(\d{4})\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$"
)
_TABLE_ROW_4 = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(\d{4})\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|$"
)
# 趋势句中带人读单位的数字（口径一致性自检对象）
_TREND_NUM = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(亿元|亿美元|亿港元|亿)")
_UNIT_DIV = {
    "千元": 100_000.0,
    "万元": 10_000.0,
    "元": 100_000_000.0,
    "百万元": 100.0,
    "百万": 100.0,
    "百万美元": 100.0,
    "百万港元": 100.0,
}


def _parse_number(token: str) -> float | None:
    raw = (token or "").replace(",", "").replace(" ", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def page_has_number(content: str, value: float) -> bool:
    blob = (content or "").replace(",", "").replace(" ", "")
    blob = blob.replace("−", "-").replace("－", "-").replace("(", "").replace(")", "")
    tokens = {format_value(value).replace(",", "").replace("−", "-").replace("－", "-")}
    if abs(value - round(value)) < 1e-6:
        iv = int(round(value))
        tokens.add(str(iv))
        tokens.add(str(abs(iv)))
    return any(tok and tok in blob for tok in tokens)


_PAGE_NUMBER_RE = re.compile(r"\(?\s*-?[\d,]+(?:\.\d+)?\s*\)?")


def page_numbers(content: str) -> list[float]:
    """页面上出现的全部数值（去千分位/括号负号），供组合口径核对。"""
    out: list[float] = []
    blob = (content or "").replace("−", "-").replace("－", "-")
    for m in _PAGE_NUMBER_RE.finditer(blob):
        raw = m.group(0).replace(",", "").replace(" ", "")
        negative = raw.strip().startswith("(")
        raw = raw.replace("(", "").replace(")", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        out.append(-v if negative else v)
    return out


def page_has_number_or_sum(content: str, value: float) -> bool:
    """组合口径（如海底捞总资产 = 页内「资产总额减流动负债」+「流动负债小计」）
    的数字不会以字面形式出现在页面上，允许页内两数之和核对。"""
    if page_has_number(content, value):
        return True
    nums = page_numbers(content)
    if len(nums) < 2 or len(nums) > 400:
        return False
    tol = 1e-6 * max(1.0, abs(value))
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            if abs(a + b - value) <= tol:
                return True
    return False


def citation_on_page(
    conn: sqlite3.Connection, file_frag: str, page: int
) -> tuple[bool, str]:
    row = conn.execute(
        """
        SELECT p.content, p.content_orig FROM pages p
        JOIN reports r ON r.id = p.report_id
        WHERE instr(r.title, ?) > 0 AND p.page_no=?
        LIMIT 1
        """,
        (file_frag, page),
    ).fetchone()
    if not row:
        return False, ""
    return True, (row["content_orig"] or row["content"] or "")


def _match_table_row(line: str) -> tuple[str, str, str, str, str] | None:
    """→ (label, year, value, unit, loc)；4 列行的 unit 为空串。"""
    m = _TABLE_ROW.match(line.strip())
    if m:
        label, year_s, num_s, unit, loc = [p.strip() for p in m.groups()]
        return label, year_s, num_s, unit, loc
    m4 = _TABLE_ROW_4.match(line.strip())
    if m4:
        label, year_s, num_s, loc = [p.strip() for p in m4.groups()]
        return label, year_s, num_s, "", loc
    return None


def _trend_unit_check(
    text: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """趋势句口径一致性：每个「N 亿元/亿美元」应能在同 locator 的出处行
    （原值 × 单位换算）中找到对应，防止正文与表格数字口径漂移。"""
    by_loc: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_loc.setdefault(r.get("locator") or "", []).append(r)
    total = 0
    ok = 0
    bad: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("趋势："):
            continue
        for m in _TREND_NUM.finditer(line):
            total += 1
            num = float(m.group(1).replace(",", ""))
            cite = _CITE.search(line[m.end(): m.end() + 120])
            hit = False
            if cite:
                loc = f"《{cite.group(1)}》第{cite.group(2)}页"
                for r in by_loc.get(loc, []):
                    div = _UNIT_DIV.get(str(r.get("unit") or ""))
                    if div is None or r.get("value") is None:
                        continue
                    v = float(r["value"]) / div
                    if abs(v - num) <= 0.005 + 0.001 * abs(v):
                        hit = True
                        break
            if hit:
                ok += 1
            else:
                bad.append(m.group(0))
    return {"trend_numbers": total, "consistent": ok, "mismatch": bad}


def audit_composed_markdown(
    conn: sqlite3.Connection, company: str, text: str
) -> dict[str, Any]:
    """Audit the 财务摘要 table: every number has a locator whose page holds it."""
    rows_out: list[dict[str, Any]] = []
    in_table = False
    prefer = "## 引用明细" in text
    seen_detail = not prefer
    for line in text.splitlines():
        if prefer and line.startswith("## 引用明细"):
            seen_detail = True
            continue
        if not seen_detail:
            continue
        if line.startswith("| 指标"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table:
            continue
        parsed = _match_table_row(line)
        if not parsed:
            continue
        label, year_s, num_s, unit, loc = parsed
        value = _parse_number(num_s)
        cite = _CITE.search(loc)
        entry: dict[str, Any] = {
            "company": company,
            "label": label,
            "year": int(year_s),
            "value": value,
            "unit": unit,
            "locator": loc,
            "has_citation": bool(cite),
            "page_exists": False,
            "number_on_page": False,
        }
        if cite and value is not None:
            exists, content = citation_on_page(conn, cite.group(1), int(cite.group(2)))
            entry["page_exists"] = exists
            entry["number_on_page"] = exists and page_has_number_or_sum(content, value)
        rows_out.append(entry)

    n = len(rows_out)
    cite_ok = sum(1 for r in rows_out if r["has_citation"] and r["page_exists"])
    faithful = sum(1 for r in rows_out if r["number_on_page"])
    missing_cite = [r["label"] for r in rows_out if not r["has_citation"]]
    unfaithful = [
        r["label"] for r in rows_out if r["has_citation"] and not r["number_on_page"]
    ]
    labels_ok = all(
        any(r["label"] == lab for r in rows_out)
        for lab in ("营业收入", "归母净利润")
    )
    unit_check = _trend_unit_check(text, rows_out)
    unit_ok = unit_check["trend_numbers"] == 0 or (
        unit_check["consistent"] == unit_check["trend_numbers"]
    )
    failed = (
        (not n)
        or (not labels_ok)
        or bool(missing_cite)
        or bool(unfaithful)
        or not unit_ok
    )
    return {
        "company": company,
        "n_rows": n,
        "citation_precision": round(cite_ok / n, 3) if n else None,
        "faithful_rate": round(faithful / n, 3) if n else None,
        "missing_citation": missing_cite,
        "unfaithful": unfaithful,
        "labels_ok": labels_ok,
        "unit_consistency": unit_check,
        "ok": not failed,
        "rows": rows_out,
    }


def run_generation_eval(
    cfg: dict[str, Any],
    companies: list[str] | None = None,
) -> dict[str, Any]:
    companies = companies or ["海底捞", "百胜中国"]
    root = Path(cfg["project_root"])
    out_dir = root / "eval" / "generated_notes"
    started = time.time()
    from stock_kb import db as dbmod

    conn = dbmod.connect(cfg["db_path"])
    notes: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    try:
        for company in companies:
            meta = compose_note(cfg, company, out_dir=out_dir / company)
            text = Path(meta["path"]).read_text(encoding="utf-8")
            audit = audit_composed_markdown(conn, company, text)
            audit["path"] = meta["path"]
            notes.append(meta)
            audits.append(audit)
    finally:
        conn.close()

    fail_count = sum(1 for a in audits if not a.get("ok"))
    report = {
        "meta": {
            "companies": companies,
            "duration_seconds": round(time.time() - started, 3),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "notes": notes,
        "audits": audits,
        "summary": {
            "n": len(audits),
            "fail_count": fail_count,
            "faithful_rate_mean": round(
                sum(a["faithful_rate"] or 0 for a in audits) / len(audits), 3
            )
            if audits
            else None,
        },
    }
    reports_dir = root / "eval" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"generation_compose_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["summary"]["report_path"] = str(path)
    return report
