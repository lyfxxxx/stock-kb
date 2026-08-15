from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from stock_kb import db
from stock_kb.classify import classify_report
from stock_kb.parsers.pdf_parser import extract_pdf, extract_statements_from_pages
from stock_kb.parsers.xls_parser import read_xls_matrix
from stock_kb.textutil import to_simplified


SUPPORTED_EXTS = {".pdf", ".xls", ".html", ".htm", ".csv", ".txt", ".md"}


def scan(
    cfg: dict[str, Any],
    companies: list[str] | None = None,
    limit: int | None = None,
    rebuild: bool = False,
    use_ocr: bool = True,
) -> dict[str, int]:
    nas = cfg["nas"]
    root = Path(nas["root"])
    companies = companies or nas.get("companies", [])
    exclude = set(nas.get("exclude_dirs", []))
    conn = db.connect(cfg["db_path"])

    stats = {"scanned": 0, "parsed": 0, "skipped": 0, "failed": 0, "pages": 0, "statements": 0}

    for company in companies:
        company_dir = root / company
        if not company_dir.exists():
            print(f"[warn] 目录不存在: {company_dir}")
            continue
        db.upsert_company(conn, company)
        for p in _iter_files(company_dir, exclude):
            if limit is not None and stats["parsed"] >= limit:
                break
            stats["scanned"] += 1
            try:
                ok = _process_file(conn, cfg, company, p, rebuild, use_ocr)
                if ok:
                    stats["parsed"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                stats["failed"] += 1
                print(f"[error] {p}: {exc}")

    row = conn.execute(
        "SELECT COUNT(*) AS n FROM pages"
    ).fetchone()
    stats["pages"] = int(row["n"])
    row = conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()
    stats["statements"] = int(row["n"])
    conn.close()
    return stats


def _iter_files(root: Path, exclude: set[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in SUPPORTED_EXTS:
                yield Path(dirpath) / name


def _process_file(
    conn,
    cfg: dict[str, Any],
    company: str,
    path: Path,
    rebuild: bool,
    use_ocr: bool,
) -> bool:
    st = path.stat()
    sha = _sha256(path)

    existing = conn.execute(
        "SELECT status, sha256 FROM manifest WHERE path=?", (str(path),)
    ).fetchone()
    if existing and existing["sha256"] == sha and existing["status"] == "ok" and not rebuild:
        return False

    meta = classify_report(path)
    meta.setdefault("currency", None)
    meta.setdefault("accounting_standard", None)
    meta.update(
        {
            "company": company,
            "path": str(path),
            "sha256": sha,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "status": "parsing",
        }
    )
    report_id = db.upsert_report(conn, meta)

    if path.suffix.lower() == ".pdf":
        ocr_cfg = cfg.get("ocr", {})
        pages = extract_pdf(
            path,
            ocr_langs=ocr_cfg.get("langs", "chi_sim+eng"),
            ocr_min_chars=ocr_cfg.get("min_chars", 80),
            use_ocr=use_ocr and ocr_cfg.get("enabled", True),
        )
        for p in pages:
            p["company"] = company
            p["content_orig"] = p["content"]
            p["content"] = to_simplified(p["content"])
        db.replace_pages(conn, report_id, pages)
        stmt_rows = extract_statements_from_pages(pages, company, meta["title"])
        db.replace_statements(conn, report_id, stmt_rows)
    elif path.suffix.lower() == ".xls":
        rows = read_xls_matrix(path)
        _store_xls(conn, report_id, company, meta, rows)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        db.replace_pages(
            conn,
            report_id,
            [
                {
                    "page_no": 1,
                    "content": to_simplified(text),
                    "content_orig": text,
                    "char_count": len(text),
                    "is_ocr": 0,
                }
            ],
        )

    conn.execute(
        "UPDATE reports SET status='ok', parsed_at=? WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), report_id),
    )
    conn.execute(
        "INSERT INTO manifest(path, company, size, mtime, sha256, status, last_seen, parsed_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, "
        "sha256=excluded.sha256, status=excluded.status, last_seen=excluded.last_seen, "
        "parsed_at=excluded.parsed_at",
        (
            str(path),
            company,
            st.st_size,
            st.st_mtime,
            sha,
            "ok",
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )
    conn.commit()
    return True


def _store_xls(conn, report_id: int, company: str, meta: dict, rows: list[list[Any]]) -> None:
    if not rows:
        return
    name = meta["title"].lower()
    if "benefit" in name or "profit" in name:
        stmt = "income"
    elif "cash" in name:
        stmt = "cashflow"
    elif "debt" in name or "balance" in name:
        stmt = "balance"
    else:
        stmt = "other"

    header = rows[0] if rows else []
    stmt_rows: list[dict[str, Any]] = []
    for r in rows[1:]:
        line_name = str(r[0] or "").strip()
        if not line_name:
            continue
        for ci, cell in enumerate(r[1:], start=1):
            try:
                value = float(cell) if cell not in ("", None) else None
            except (TypeError, ValueError):
                value = None
            if value is None:
                continue
            header_cell = str(header[ci]) if ci < len(header) else ""
            year = None
            for token in str(header_cell).replace(",", " ").split():
                if token.isdigit() and len(token) == 4:
                    year = int(token)
                    break
            stmt_rows.append(
                {
                    "statement_type": stmt,
                    "line_name_orig": line_name,
                    "line_name_norm": to_simplified(line_name),
                    "value": value,
                    "unit": None,
                    "currency": None,
                    "year": year,
                    "page_no": 1,
                    "table_index": 0,
                    "source_id": None,
                }
            )
    db.replace_statements(conn, report_id, stmt_rows)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
