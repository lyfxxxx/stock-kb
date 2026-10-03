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
from stock_kb.source_meta import origin_for, read_source_meta, write_source_meta
from stock_kb.textutil import to_simplified
from stock_kb.versioning import (
    PARSE_VERSION,
    build_logical_key,
    decide_scan_action,
    page_kind_for,
)


SUPPORTED_EXTS = {".pdf", ".xls", ".html", ".htm", ".csv", ".txt", ".md"}
_SUPERSEDED_MARK = "::superseded::"


def scan(
    cfg: dict[str, Any],
    companies: list[str] | None = None,
    limit: int | None = None,
    rebuild: bool = False,
    use_ocr: bool = True,
) -> dict[str, int]:
    lock_path = Path(cfg.get("data_dir", "data")) / "scan.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"pid={os.getpid()} time={time.strftime('%Y-%m-%dT%H:%M:%S')}".encode())
        os.close(fd)
    except FileExistsError:
        raise RuntimeError(f"已有扫描任务在运行（{lock_path}），请勿并发执行 scan")

    try:
        return _scan_locked(cfg, companies=companies, limit=limit, rebuild=rebuild, use_ocr=use_ocr)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _scan_locked(
    cfg: dict[str, Any],
    companies: list[str] | None = None,
    limit: int | None = None,
    rebuild: bool = False,
    use_ocr: bool = True,
) -> dict[str, int]:
    nas = cfg["nas"]
    companies = companies or nas.get("companies", [])
    exclude = set(nas.get("exclude_dirs", []))
    conn = db.connect(cfg["db_path"])
    backfill_origins(conn, cfg)

    stats = {
        "scanned": 0,
        "parsed": 0,
        "skipped": 0,
        "failed": 0,
        "pages": 0,
        "statements": 0,
        "missing": 0,
    }

    for company in companies:
        company_dirs = _company_scan_dirs(cfg, company)
        if not company_dirs:
            print(f"[warn] 目录不存在: {_company_scan_hint(cfg, company)}")
            continue
        db.upsert_company(conn, company)
        for company_dir in company_dirs:
            for p in _iter_files(company_dir, exclude):
                if limit is not None and stats["parsed"] >= limit:
                    break
                stats["scanned"] += 1
                try:
                    side_url, side_at = read_source_meta(cfg, p, company)
                    ok = _process_file(
                        conn, cfg, company, p, rebuild, use_ocr,
                        source_url=side_url, retrieved_at=side_at,
                    )
                    if ok:
                        stats["parsed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as exc:
                    stats["failed"] += 1
                    print(f"[error] {p}: {exc}")
            stats["missing"] += _mark_missing_sources(conn, company_dir, company)

    stats["duplicates_marked"] = db.mark_duplicate_reports(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM pages"
    ).fetchone()
    stats["pages"] = int(row["n"])
    row = conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()
    stats["statements"] = int(row["n"])
    conn.close()
    return stats


def backfill_origins(conn, cfg: dict[str, Any]) -> int:
    """按 reports.path 相对两个根目录回填 origin，不读原文。"""
    marked = 0
    rows = conn.execute("SELECT id, path, origin FROM reports").fetchall()
    for row in rows:
        origin = origin_for(cfg, Path(row["path"]))
        if origin is None or origin == row["origin"]:
            continue
        conn.execute("UPDATE reports SET origin=? WHERE id=?", (origin, row["id"]))
        marked += 1
    if marked:
        conn.commit()
    return marked


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
    source_url: str | None = None,
    retrieved_at: str | None = None,
    origin: str | None = None,
) -> bool:
    st = path.stat()
    path_s = str(path)
    if origin is None:
        origin = origin_for(cfg, path)
    manifest = conn.execute(
        "SELECT status, sha256, size, mtime FROM manifest WHERE path=?", (path_s,)
    ).fetchone()
    existing = conn.execute("SELECT * FROM reports WHERE path=?", (path_s,)).fetchone()
    size_unchanged = manifest is not None and manifest["size"] == st.st_size
    mtime_unchanged = manifest is not None and manifest["mtime"] == st.st_mtime
    manifest_status = manifest["status"] if manifest is not None else None
    existing_sha = existing["sha256"] if existing is not None else None
    existing_version = existing["parse_version"] if existing is not None else None

    # 字节与解析版本都没变时不读文件。版本过期则继续，以便同 sha 就地重解析。
    if (
        not rebuild
        and manifest is not None
        and manifest_status == "ok"
        and size_unchanged
        and mtime_unchanged
        and existing is not None
        and existing_version == PARSE_VERSION
    ):
        _touch_catalog(conn, path_s, origin, source_url, retrieved_at)
        write_source_meta(
            cfg,
            path,
            company,
            origin=origin,
            source_url=source_url,
            retrieved_at=retrieved_at,
            sha256=existing_sha,
        )
        return False

    sha = _sha256(path)
    action = decide_scan_action(
        existing_sha=existing_sha,
        new_sha=sha,
        existing_parse_version=existing_version,
        size_unchanged=size_unchanged,
        mtime_unchanged=mtime_unchanged,
        rebuild=rebuild,
        manifest_status=manifest_status,
        report_status=existing["status"] if existing is not None else None,
    )
    if action == "skip":
        _touch_catalog(conn, path_s, origin, source_url, retrieved_at)
        write_source_meta(
            cfg,
            path,
            company,
            origin=origin,
            source_url=source_url,
            retrieved_at=retrieved_at,
            sha256=existing_sha or sha,
        )
        return False

    if source_url is None and existing is not None:
        source_url = existing["source_url"]
    if retrieved_at is None and existing is not None:
        retrieved_at = existing["retrieved_at"]

    meta = classify_report(path)
    meta.setdefault("currency", None)
    meta.setdefault("accounting_standard", None)
    try:
        pages, stmt_rows, content_lang = _read_document(
            path, cfg, company, meta, use_ocr
        )
    except Exception as exc:
        _fail_parse(
            conn, path, company, meta, existing, exc, st, sha, source_url, retrieved_at, origin
        )
        write_source_meta(
            cfg,
            path,
            company,
            origin=origin,
            source_url=source_url,
            retrieved_at=retrieved_at,
            sha256=sha,
        )
        raise

    if content_lang:
        meta["language"] = content_lang
    logical_key = build_logical_key(
        company=company,
        report_type=meta["report_type"],
        year=meta.get("year"),
        period_type=meta.get("period_type"),
        language=meta.get("language"),
        path=path_s,
        title=meta.get("title") or "",
        source_url=source_url,
    )
    replaced_id = None
    supersedes_id = existing["supersedes_id"] if existing is not None else None
    if action == "new_version" and existing is not None:
        replaced_id = int(existing["id"])
        _archive_report(conn, existing)
        supersedes_id = replaced_id

    meta.update(
        {
            "company": company,
            "path": path_s,
            "sha256": sha,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "status": "parsing",
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "origin": origin,
            "parse_version": PARSE_VERSION,
            "supersedes_id": supersedes_id,
            "logical_key": logical_key,
        }
    )
    report_id = db.upsert_report(conn, meta)
    for page in pages:
        page["page_kind"] = page_kind_for(page, meta["report_type"])
    db.replace_pages(conn, report_id, pages)
    if path.suffix.lower() in {".pdf", ".xls"}:
        db.replace_statements(conn, report_id, stmt_rows)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if meta["report_type"] == "other":
        # other 的 logical_key 含路径，不把不同文件串成一条版本链。
        conn.execute(
            "UPDATE reports SET status='ok', parsed_at=?, parse_version=? WHERE id=?",
            (now, PARSE_VERSION, report_id),
        )
    else:
        elect_logical_key(
            conn,
            logical_key,
            incoming_id=report_id,
            replaced_id=replaced_id,
        )
        conn.execute(
            "UPDATE reports SET parsed_at=?, parse_version=? WHERE id=?",
            (now, PARSE_VERSION, report_id),
        )
    conn.execute(
        "INSERT INTO manifest(path, company, size, mtime, sha256, status, last_seen, parsed_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, "
        "sha256=excluded.sha256, status=excluded.status, last_seen=excluded.last_seen, "
        "parsed_at=excluded.parsed_at",
        (
            path_s,
            company,
            st.st_size,
            st.st_mtime,
            sha,
            "ok",
            now,
            now,
        ),
    )
    conn.commit()
    write_source_meta(
        cfg,
        path,
        company,
        origin=origin,
        source_url=source_url,
        retrieved_at=retrieved_at,
        sha256=sha,
    )
    return True


def _read_document(
    path: Path,
    cfg: dict[str, Any],
    company: str,
    meta: dict[str, Any],
    use_ocr: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if path.suffix.lower() == ".pdf":
        ocr_cfg = cfg.get("ocr", {})
        pages = extract_pdf(
            path,
            ocr_langs=ocr_cfg.get("langs", "chi_sim+eng"),
            ocr_min_chars=ocr_cfg.get("min_chars", 80),
            use_ocr=use_ocr and ocr_cfg.get("enabled", True),
        )
        _normalize_pages(pages, company)
        stmt_rows = extract_statements_from_pages(
            pages, company, meta["title"], report_year=meta.get("year")
        )
        return pages, stmt_rows, _detect_content_language(pages)
    if path.suffix.lower() == ".xls":
        rows = read_xls_matrix(path)
        pages, stmt_rows = _xls_pages_and_statements(company, meta, rows)
        return pages, stmt_rows, None
    text = path.read_text(encoding="utf-8", errors="ignore")
    pages = [
        {
            "page_no": 1,
            "content": text,
            "char_count": len(text),
            "is_ocr": 0,
        }
    ]
    _normalize_pages(pages, company)
    return pages, [], None


def _normalize_pages(pages: list[dict[str, Any]], company: str) -> None:
    for page in pages:
        orig = page.get("content_orig")
        if orig is None:
            orig = page.get("content") or ""
        page["content_orig"] = orig
        page["content"] = to_simplified(orig)
        page["company"] = company
        if page.get("char_count") is None:
            page["char_count"] = len(orig)


def _archive_report(conn, row) -> str:
    sha = row["sha256"] or ""
    archived = f"{row['path']}{_SUPERSEDED_MARK}{sha[:12]}"
    clash = conn.execute("SELECT id FROM reports WHERE path=?", (archived,)).fetchone()
    if clash is not None and int(clash["id"]) != int(row["id"]):
        archived = f"{archived}::{row['id']}"
    conn.execute(
        "UPDATE reports SET path=?, status='superseded' WHERE id=?",
        (archived, row["id"]),
    )
    return archived


def _version_rank(row) -> tuple:
    retrieved = row["retrieved_at"] or ""
    mtime = row["mtime"]
    if mtime is None:
        mtime = 0
    return (str(retrieved), float(mtime), int(row["id"]))


def elect_logical_key(
    conn,
    logical_key: str,
    *,
    incoming_id: int,
    replaced_id: int | None = None,
) -> int | None:
    """同一 logical_key 上，(retrieved_at, mtime, id) 最大的一条保持 ok。

    刚被同路径归档的那一行不能在本轮选回 ok。supersedes_id 只写在本轮胜者上，
    指向刚被它取代的那条。sha 相同的另一条活报告是重复文件，不改版本链。
    """
    if not logical_key:
        conn.execute("UPDATE reports SET status='ok' WHERE id=?", (incoming_id,))
        return None
    rows = conn.execute(
        "SELECT id, status, retrieved_at, mtime, sha256 FROM reports WHERE logical_key=?",
        (logical_key,),
    ).fetchall()
    incoming = next((row for row in rows if int(row["id"]) == int(incoming_id)), None)
    active = [row for row in rows if (row["status"] or "") not in ("failed", "missing")]
    if incoming is not None and replaced_id is None:
        incoming_sha = incoming["sha256"]
        twin = [
            row
            for row in active
            if int(row["id"]) != int(incoming_id)
            and incoming_sha
            and row["sha256"] == incoming_sha
            and (row["status"] or "ok") == "ok"
        ]
        if twin:
            conn.execute("UPDATE reports SET status='ok' WHERE id=?", (incoming_id,))
            return int(twin[0]["id"])

    candidates = [
        row
        for row in active
        if replaced_id is None or int(row["id"]) != int(replaced_id)
    ]
    if not candidates:
        conn.execute("UPDATE reports SET status='ok' WHERE id=?", (incoming_id,))
        return incoming_id
    winner = max(candidates, key=_version_rank)
    for row in active:
        if int(row["id"]) == int(winner["id"]):
            continue
        if replaced_id is not None and int(row["id"]) == int(replaced_id):
            continue
        conn.execute("UPDATE reports SET status='superseded' WHERE id=?", (row["id"],))
    conn.execute("UPDATE reports SET status='ok' WHERE id=?", (winner["id"],))
    if int(winner["id"]) == int(incoming_id):
        prev_ok = [
            row
            for row in active
            if int(row["id"]) != int(incoming_id)
            and (replaced_id is None or int(row["id"]) != int(replaced_id))
            and (row["status"] or "ok") == "ok"
        ]
        if prev_ok:
            target = int(max(prev_ok, key=_version_rank)["id"])
        else:
            target = replaced_id
        if target is not None:
            conn.execute(
                "UPDATE reports SET supersedes_id=? WHERE id=?",
                (target, incoming_id),
            )
    return int(winner["id"])


def _company_scan_dirs(cfg: dict[str, Any], company: str) -> list[Path]:
    """NAS 公司目录和 collect.raw_dir 下的同名目录都扫描。同一路径只走一次。"""
    found: list[Path] = []
    seen: set[str] = set()
    candidates: list[Path] = []
    nas_root = (cfg.get("nas") or {}).get("root")
    if nas_root:
        candidates.append(Path(nas_root) / company)
    raw = (cfg.get("collect") or {}).get("raw_dir")
    if raw:
        candidates.append(Path(raw) / company)
    for path in candidates:
        if not path.exists() or not path.is_dir():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


def _company_scan_hint(cfg: dict[str, Any], company: str) -> str:
    parts: list[str] = []
    nas_root = (cfg.get("nas") or {}).get("root")
    if nas_root:
        parts.append(str(Path(nas_root) / company))
    raw = (cfg.get("collect") or {}).get("raw_dir")
    if raw:
        parts.append(str(Path(raw) / company))
    return "、".join(parts) if parts else company


def _mark_missing_sources(conn, company_dir: Path, company: str) -> int:
    """公司目录里已经找不到的源文件标 missing。不删除行，也不动扫描根之外的报告。"""
    root = company_dir.resolve()
    marked = 0
    rows = conn.execute(
        "SELECT id, path, status FROM reports WHERE company=?",
        (company,),
    ).fetchall()
    for row in rows:
        path_s = row["path"] or ""
        if _SUPERSEDED_MARK in path_s or (row["status"] or "") == "superseded":
            continue
        if not _missing_under_root(path_s, root):
            continue
        conn.execute("UPDATE reports SET status='missing' WHERE id=?", (row["id"],))
        conn.execute("UPDATE manifest SET status='missing' WHERE path=?", (path_s,))
        marked += 1
    manifests = conn.execute(
        "SELECT path FROM manifest WHERE company=? AND COALESCE(status, '') != 'missing'",
        (company,),
    ).fetchall()
    for row in manifests:
        path_s = row["path"] or ""
        if _SUPERSEDED_MARK in path_s:
            continue
        if not _missing_under_root(path_s, root):
            continue
        conn.execute("UPDATE manifest SET status='missing' WHERE path=?", (path_s,))
    conn.commit()
    return marked


def _missing_under_root(path_s: str, root: Path) -> bool:
    path = Path(path_s)
    if path.exists():
        return False
    try:
        path.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _touch_catalog(
    conn,
    path_s: str,
    origin: str | None,
    source_url: str | None,
    retrieved_at: str | None,
) -> None:
    """skip 时回填 origin 和出处，不哈希、不重解析。"""
    conn.execute(
        """
        UPDATE reports SET
            origin = COALESCE(?, reports.origin),
            source_url = COALESCE(?, reports.source_url),
            retrieved_at = COALESCE(?, reports.retrieved_at)
        WHERE path=?
        """,
        (origin, source_url, retrieved_at, path_s),
    )
    conn.commit()


def _fail_parse(
    conn,
    path: Path,
    company: str,
    meta: dict[str, Any],
    existing,
    exc: Exception,
    st,
    sha: str,
    source_url: str | None,
    retrieved_at: str | None,
    origin: str | None = None,
) -> None:
    # 解析失败不归档旧行。没有旧行时记一条 failed，避免下次扫描无据可查。
    if existing is None:
        failed = dict(meta)
        failed.update(
            {
                "company": company,
                "path": str(path),
                "sha256": sha,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "status": "failed",
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "origin": origin,
                "parse_version": PARSE_VERSION,
                "supersedes_id": None,
                "logical_key": build_logical_key(
                    company=company,
                    report_type=meta["report_type"],
                    year=meta.get("year"),
                    period_type=meta.get("period_type"),
                    language=meta.get("language"),
                    path=str(path),
                    title=meta.get("title") or "",
                    source_url=source_url,
                ),
            }
        )
        report_id = db.upsert_report(conn, failed)
    else:
        report_id = int(existing["id"])
    _mark_failed(conn, path, report_id, exc)


def _xls_pages_and_statements(
    company: str, meta: dict, rows: list[list[Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        return [], []
    text = "\n".join(" | ".join(str(c or "").strip() for c in r) for r in rows)
    pages = [
        {
            "page_no": 1,
            "content": text,
            "char_count": len(text),
            "is_ocr": 0,
        }
    ]
    _normalize_pages(pages, company)
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
    return pages, stmt_rows


def _detect_content_language(pages: list[dict[str, Any]]) -> str | None:
    cjk = 0
    total = 0
    for p in pages:
        text = p.get("content") or ""
        cjk += sum("\u4e00" <= ch <= "\u9fff" for ch in text)
        total += max(len(text), 1)
    if total == 0:
        return None
    # 中文页 CJK 占比通常明显高于 2%；英文报告中偶有少量中文字符。
    return "zh" if cjk / total >= 0.02 else "en"


def _mark_failed(conn, path: Path, report_id: int, exc: Exception) -> None:
    del path, exc
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "UPDATE reports SET status='failed', parsed_at=? WHERE id=?",
        (now, report_id),
    )
    conn.execute(
        """
        INSERT INTO manifest(path, company, size, mtime, sha256, status, last_seen, parsed_at)
        SELECT path, company, size, mtime, sha256, 'failed', ?, ? FROM reports WHERE id=?
        ON CONFLICT(path) DO UPDATE SET status='failed', last_seen=excluded.last_seen,
            parsed_at=excluded.parsed_at
        """,
        (now, now, report_id),
    )
    conn.commit()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
