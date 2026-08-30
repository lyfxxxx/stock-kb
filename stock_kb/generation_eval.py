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
_TABLE_ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(\d{4})\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|$"
)


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


def audit_composed_markdown(
    conn: sqlite3.Connection, company: str, text: str
) -> dict[str, Any]:
    """Audit the 财务摘要 table: every number has a locator whose page holds it."""
    rows_out: list[dict[str, Any]] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| 指标"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table:
            continue
        m = _TABLE_ROW.match(line.strip())
        if not m:
            continue
        label, year_s, num_s, loc = [p.strip() for p in m.groups()]
        value = _parse_number(num_s)
        cite = _CITE.search(loc)
        entry: dict[str, Any] = {
            "company": company,
            "label": label,
            "year": int(year_s),
            "value": value,
            "locator": loc,
            "has_citation": bool(cite),
            "page_exists": False,
            "number_on_page": False,
        }
        if cite and value is not None:
            exists, content = citation_on_page(conn, cite.group(1), int(cite.group(2)))
            entry["page_exists"] = exists
            entry["number_on_page"] = exists and page_has_number(content, value)
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
    failed = (not n) or (not labels_ok) or bool(missing_cite) or bool(unfaithful)
    return {
        "company": company,
        "n_rows": n,
        "citation_precision": round(cite_ok / n, 3) if n else None,
        "faithful_rate": round(faithful / n, 3) if n else None,
        "missing_citation": missing_cite,
        "unfaithful": unfaithful,
        "labels_ok": labels_ok,
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
