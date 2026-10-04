"""页文本保真抽检：标注原句是否还在当前使用文档的 content_orig 里。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db


SKIPPED_LINE = "page_fidelity: skipped (no labeled pages); not a pass"


def default_pages_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("project_root") or ".") / "eval" / "page_fidelity.yaml"


def load_page_spec(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    pages = data.get("pages") if isinstance(data, dict) else None
    if not pages:
        return []
    return list(pages)


def run_fidelity(conn, pages: list[dict[str, Any]]) -> dict[str, Any]:
    """对照当前使用文档检查 needles。空清单是 skipped，不是通过。"""
    if not pages:
        return {"skipped": True, "passed": False, "message": SKIPPED_LINE, "items": []}

    items: list[dict[str, Any]] = []
    for spec in pages:
        items.append(_check_page(conn, spec))
    non_ocr_miss = [item for item in items if int(item["is_ocr"]) == 0 and not item["ok"]]
    return {
        "skipped": False,
        "passed": not non_ocr_miss,
        "items": items,
        "groups": _groups(items),
        "non_ocr_miss": len(non_ocr_miss),
        "ocr_miss": sum(1 for item in items if int(item["is_ocr"]) == 1 and not item["ok"]),
    }


def _check_page(conn, spec: dict[str, Any]) -> dict[str, Any]:
    company = spec.get("company") or ""
    title_contains = spec.get("title_contains") or ""
    page_no = int(spec.get("page_no") or 0)
    report_type = spec.get("report_type") or ""
    is_ocr = int(spec.get("is_ocr") or 0)
    needles = [str(n) for n in (spec.get("needles") or [])]
    base = {
        "company": company,
        "title_contains": title_contains,
        "page_no": page_no,
        "report_type": report_type,
        "is_ocr": is_ocr,
        "needles": needles,
        "found": False,
        "ok": False,
        "missing_needles": needles,
    }
    if not company or not title_contains or page_no <= 0:
        return base

    sql = (
        "SELECT r.id AS report_id, r.title, p.content_orig "
        "FROM pages p JOIN reports r ON r.id = p.report_id "
        f"WHERE {db.live_report_sql('r')} AND r.company=? AND instr(r.title, ?)>0 AND p.page_no=?"
    )
    params: list[Any] = [company, title_contains, page_no]
    if report_type:
        sql += " AND r.report_type=?"
        params.append(report_type)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return base

    missing = needles
    for row in rows:
        text = row["content_orig"] or ""
        missing = [needle for needle in needles if needle not in text]
        if not missing:
            base["found"] = True
            base["ok"] = True
            base["missing_needles"] = []
            base["title"] = row["title"]
            return base
    base["found"] = True
    base["missing_needles"] = missing
    base["title"] = rows[0]["title"]
    return base


def _groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, int], dict[str, Any]] = {}
    for item in items:
        key = (item.get("report_type") or "", int(item.get("is_ocr") or 0))
        bucket = buckets.setdefault(
            key, {"report_type": key[0], "is_ocr": key[1], "hit": 0, "total": 0}
        )
        bucket["total"] += 1
        if item["ok"]:
            bucket["hit"] += 1
    return [buckets[key] for key in sorted(buckets)]


def format_fidelity_text(result: dict[str, Any]) -> str:
    if result.get("skipped"):
        return SKIPPED_LINE
    lines: list[str] = []
    for group in result.get("groups") or []:
        line = (
            f"page_fidelity: {group['report_type'] or '-'} "
            f"is_ocr={group['is_ocr']} hit {group['hit']}/{group['total']}"
        )
        if group["is_ocr"] == 1 and group["hit"] != group["total"]:
            line += " (ocr miss listed, not a gate)"
        lines.append(line)
    for item in result.get("items") or []:
        if item["ok"]:
            continue
        lines.append(
            "page_fidelity: miss "
            f"{item['company']} {item['title_contains']} p{item['page_no']} "
            f"is_ocr={item['is_ocr']} missing={item['missing_needles']}"
        )
    if not lines:
        lines.append("page_fidelity: hit 0/0")
    return "\n".join(lines)


def fidelity_main(cfg: dict[str, Any], pages: str | None = None, as_json: bool = False) -> int:
    path = Path(pages) if pages else default_pages_path(cfg)
    spec = load_page_spec(path)
    if not spec:
        payload = {"skipped": True, "passed": False, "message": SKIPPED_LINE, "items": []}
        if as_json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(SKIPPED_LINE)
        return 0
    conn = db.connect(cfg["db_path"])
    try:
        result = run_fidelity(conn, spec)
    finally:
        conn.close()
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_fidelity_text(result))
    return 0 if result.get("passed") else 1
