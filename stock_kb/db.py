from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,
    name TEXT UNIQUE,
    exchange TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    report_type TEXT NOT NULL,
    language TEXT,
    currency TEXT,
    accounting_standard TEXT,
    year INTEGER,
    period_type TEXT,
    title TEXT,
    path TEXT UNIQUE NOT NULL,
    sha256 TEXT,
    size INTEGER,
    mtime REAL,
    status TEXT DEFAULT 'pending',
    parsed_at TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    page_no INTEGER NOT NULL,
    content TEXT,
    char_count INTEGER DEFAULT 0,
    is_ocr INTEGER DEFAULT 0,
    UNIQUE(report_id, page_no)
);

CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    statement_type TEXT NOT NULL,
    line_name_orig TEXT,
    line_name_norm TEXT,
    value REAL,
    unit TEXT,
    currency TEXT,
    year INTEGER,
    page_no INTEGER,
    table_index INTEGER,
    source_id INTEGER,
    UNIQUE(report_id, statement_type, page_no, table_index, line_name_orig, year)
);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    year INTEGER,
    period_type TEXT,
    name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    source_id INTEGER,
    UNIQUE(company, year, period_type, name)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    company TEXT,
    report_title TEXT,
    page_no INTEGER,
    table_index INTEGER,
    locator TEXT,
    snippet TEXT,
    UNIQUE(report_id, page_no, table_index)
);

CREATE TABLE IF NOT EXISTS manifest (
    path TEXT PRIMARY KEY,
    company TEXT,
    size INTEGER,
    mtime REAL,
    sha256 TEXT,
    status TEXT,
    last_seen TEXT,
    parsed_at TEXT
);

CREATE TABLE IF NOT EXISTS embedding_index (
    model TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    dim INTEGER NOT NULL,
    indexed_at TEXT,
    PRIMARY KEY(model, chunk_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    chunk_no INTEGER NOT NULL,
    content TEXT,
    UNIQUE(page_id, chunk_no)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    _init_fts(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(pages)").fetchall()]
    if "content_orig" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN content_orig TEXT")
    conn.commit()


def load_vector_extension(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise RuntimeError("缺少 sqlite-vec，请先 pip install sqlite-vec") from exc
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _init_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5("
            "page_id UNINDEXED, company UNINDEXED, report_id UNINDEXED, content, tokenize='trigram')"
        )
    except sqlite3.OperationalError:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5("
            "page_id UNINDEXED, company UNINDEXED, report_id UNINDEXED, content)"
        )
    conn.commit()


def upsert_company(conn: sqlite3.Connection, name: str, code: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO companies(name, code) VALUES(?, ?) "
        "ON CONFLICT(name) DO UPDATE SET code=COALESCE(excluded.code, companies.code)",
        (name, code),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
    return int(row["id"])


def upsert_report(conn: sqlite3.Connection, meta: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT INTO reports(company, report_type, language, currency, accounting_standard,
                            year, period_type, title, path, sha256, size, mtime, status)
        VALUES(:company, :report_type, :language, :currency, :accounting_standard,
               :year, :period_type, :title, :path, :sha256, :size, :mtime, :status)
        ON CONFLICT(path) DO UPDATE SET
            company=excluded.company,
            report_type=excluded.report_type,
            language=excluded.language,
            currency=excluded.currency,
            accounting_standard=excluded.accounting_standard,
            year=excluded.year,
            period_type=excluded.period_type,
            title=excluded.title,
            sha256=excluded.sha256,
            size=excluded.size,
            mtime=excluded.mtime,
            status=excluded.status
        """,
        meta,
    )
    conn.commit()
    row = conn.execute("SELECT id FROM reports WHERE path=?", (meta["path"],)).fetchone()
    return int(row["id"])


def replace_pages(conn: sqlite3.Connection, report_id: int, pages: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM pages WHERE report_id=?", (report_id,))
    conn.execute("DELETE FROM pages_fts WHERE report_id=?", (report_id,))
    for p in pages:
        cur = conn.execute(
            "INSERT INTO pages(report_id, page_no, content, content_orig, char_count, is_ocr) "
            "VALUES(?,?,?,?,?,?)",
            (
                report_id,
                p["page_no"],
                p["content"],
                p.get("content_orig"),
                p["char_count"],
                p.get("is_ocr", 0),
            ),
        )
        page_id = cur.lastrowid
        conn.execute(
            "INSERT INTO pages_fts(page_id, company, report_id, content) VALUES(?,?,?,?)",
            (page_id, p.get("company", ""), report_id, p["content"]),
        )
    conn.commit()


def replace_statements(conn: sqlite3.Connection, report_id: int, rows: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM statements WHERE report_id=?", (report_id,))
    for r in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO statements(report_id, statement_type, line_name_orig,
                line_name_norm, value, unit, currency, year, page_no, table_index, source_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                report_id,
                r.get("statement_type"),
                r.get("line_name_orig"),
                r.get("line_name_norm"),
                r.get("value"),
                r.get("unit"),
                r.get("currency"),
                r.get("year"),
                r.get("page_no"),
                r.get("table_index"),
                r.get("source_id"),
            ),
        )
    conn.commit()


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    return dict(row) if row else None
