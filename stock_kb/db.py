from __future__ import annotations

import re
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
    parsed_at TEXT,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_of INTEGER
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
    line_no INTEGER,
    table_index INTEGER,
    source_id INTEGER,
    is_subtotal INTEGER DEFAULT 0,
    is_ocr INTEGER DEFAULT 0,
    UNIQUE(report_id, statement_type, page_no, table_index, line_name_orig, year, line_no)
);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    year INTEGER,
    period_type TEXT,
    name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    currency TEXT,
    report_id INTEGER,
    page_no INTEGER,
    line_name TEXT,
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
    vec_table TEXT,
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

    report_cols = [row[1] for row in conn.execute("PRAGMA table_info(reports)").fetchall()]
    if "is_duplicate" not in report_cols:
        conn.execute("ALTER TABLE reports ADD COLUMN is_duplicate INTEGER DEFAULT 0")
    if "duplicate_of" not in report_cols:
        conn.execute("ALTER TABLE reports ADD COLUMN duplicate_of INTEGER")

    indicator_cols = [row[1] for row in conn.execute("PRAGMA table_info(indicators)").fetchall()]
    for col in ("currency", "report_id", "page_no", "line_name"):
        if col not in indicator_cols:
            conn.execute(f"ALTER TABLE indicators ADD COLUMN {col}")

    # statements 需要把 line_no 纳入唯一键（同页同名小计行多次出现，如含/不含
    # 持作出售的两版小计），SQLite 无法 ALTER 约束，走重建迁移。
    stmt_cols = [row[1] for row in conn.execute("PRAGMA table_info(statements)").fetchall()]
    if stmt_cols and "line_no" not in stmt_cols:
        conn.executescript(
            """
            CREATE TABLE statements_migrate (
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
                line_no INTEGER,
                table_index INTEGER,
                source_id INTEGER,
                is_subtotal INTEGER DEFAULT 0,
                is_ocr INTEGER DEFAULT 0,
                UNIQUE(report_id, statement_type, page_no, table_index,
                       line_name_orig, year, line_no)
            );
            INSERT INTO statements_migrate(id, report_id, statement_type, line_name_orig,
                line_name_norm, value, unit, currency, year, page_no, line_no,
                table_index, source_id, is_subtotal, is_ocr)
            SELECT id, report_id, statement_type, line_name_orig, line_name_norm,
                value, unit, currency, year, page_no, NULL,
                table_index, source_id, 0, 0 FROM statements;
            DROP TABLE statements;
            ALTER TABLE statements_migrate RENAME TO statements;
            """
        )
    if stmt_cols and "is_ocr" not in stmt_cols and "line_no" in stmt_cols:
        # 已做过 line_no 迁移但还没有 is_ocr 的中间态库
        conn.execute("ALTER TABLE statements ADD COLUMN is_ocr INTEGER DEFAULT 0")

    index_cols = [row[1] for row in conn.execute("PRAGMA table_info(embedding_index)").fetchall()]
    if "vec_table" not in index_cols:
        conn.execute("ALTER TABLE embedding_index ADD COLUMN vec_table TEXT")
    conn.execute(
        "UPDATE embedding_index SET vec_table = 'chunks_vec_' || dim WHERE vec_table IS NULL"
    )
    conn.commit()


def load_vector_extension(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise RuntimeError("缺少 sqlite-vec，请先 pip install sqlite-vec") from exc
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def vector_table_names(conn: sqlite3.Connection) -> list[str]:
    """返回当前库中所有 sqlite-vec 主表名（排除 *_chunks/_info/_rowids 等影子表）。"""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'chunks_vec_%'"
        )
    ]
    shadow_suffixes = ("_chunks", "_info", "_rowids")
    return [
        n for n in names
        if not n.endswith(shadow_suffixes) and "_vector_chunks" not in n
    ]


def cjk_bigrams(text: str) -> str:
    """生成中文二元组（空格分隔），供两字查询使用。"""
    out: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return " ".join(out)


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
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS pages_bigram_fts USING fts5("
            "page_id UNINDEXED, company UNINDEXED, report_id UNINDEXED, bigrams)"
        )
    except sqlite3.OperationalError:
        pass
    if _table_exists(conn, "pages_bigram_fts"):
        count = conn.execute("SELECT COUNT(*) FROM pages_bigram_fts").fetchone()[0]
        page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        if count < page_count:
            for row in conn.execute(
                "SELECT p.id, p.report_id, p.content FROM pages p ORDER BY p.id"
            ).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO pages_bigram_fts(page_id, report_id, bigrams) "
                    "VALUES(?,?,?)",
                    (row["id"], row["report_id"], cjk_bigrams(row["content"])),
                )
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def upsert_company(conn: sqlite3.Connection, name: str, code: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO companies(name, code) VALUES(?, ?) "
        "ON CONFLICT(name) DO UPDATE SET code=COALESCE(excluded.code, companies.code)",
        (name, code),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
    return int(row["id"])


# 笔记/MCP 常用说法 → 三表行名片段（简体或原文）。
# 注意大小写：needle 'Capitalspending' 命中 line_name_norm（instr 区分大小写），
# 'capital spending' 命中 lower(line_name_orig)，两者各覆盖一条路径。
_STATEMENT_ALIASES = {
    "资本开支": [
        "购买物业",
        "購買物業",
        "purchase of property",
        "Capitalspending",
        "capital spending",
    ],
    "资本支出": [
        "购买物业",
        "購買物業",
        "purchase of property",
        "Capitalspending",
        "capital spending",
    ],
    "capex": [
        "purchase of property",
        "购买物业",
        "Capitalspending",
        "capital spending",
    ],
    # 美版年报行名常无空格（Cashdividendspaidoncommonstock），
    # 'dividends paid' 只能命中港版有空格原文，'dividendspaid' 补 norm 路径。
    "已付股息": ["dividends paid", "dividendspaid", "已付股息"],
    "股息": ["dividends paid", "dividendspaid", "已付股息"],
}


def query_statements(
    conn: sqlite3.Connection,
    company: str,
    statement_type: str | None = None,
    year: int | None = None,
    period_type: str | None = None,
    keyword: str | None = None,
    limit: int | None = 100,
    include_comparatives: bool = False,
    include_ocr: bool = False,
) -> list[dict[str, Any]]:
    """按公司查三表行项目。keyword 匹配 line_name_norm / line_name_orig。

    year 默认同时约束科目年 ``s.year`` 和报告年 ``r.year``，只要当年年报正文，
    不要次年报比较列。比较列需显式 ``include_comparatives=True``。
    未指定 ``period_type`` 时默认只取年报（r.period_type='annual'），中报/招股书
    行项目需显式传 ``period_type``，避免与年报正文混排。
    OCR 页提取的行（s.is_ocr=1）数字可靠性有限，默认排除，需 ``include_ocr=True``。
    """
    sql = """
        SELECT s.id AS statement_id, r.id AS report_id, s.statement_type,
               s.line_name_orig, s.line_name_norm, s.value,
               s.unit, s.currency, s.year, s.page_no, s.line_no, s.is_subtotal,
               r.title, r.path, r.year AS report_year
        FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE r.company=?
    """
    params: list[Any] = [company]
    if not include_ocr:
        sql += " AND COALESCE(s.is_ocr, 0) = 0"
    if statement_type is not None:
        sql += " AND s.statement_type=?"
        params.append(statement_type)
    if year is not None:
        sql += " AND s.year=?"
        params.append(year)
        if not include_comparatives:
            sql += " AND r.year=?"
            params.append(year)
    if period_type is not None:
        sql += " AND r.period_type=?"
        params.append(period_type)
    else:
        sql += " AND r.period_type='annual'"
    if keyword is not None and str(keyword).strip():
        kw = str(keyword).strip()
        needles = [kw]
        for extra in _STATEMENT_ALIASES.get(kw, []) + _STATEMENT_ALIASES.get(kw.lower(), []):
            if extra not in needles:
                needles.append(extra)
        clauses = []
        for n in needles:
            clauses.append(
                "(instr(s.line_name_norm, ?) > 0 "
                "OR instr(lower(COALESCE(s.line_name_orig, '')), lower(?)) > 0)"
            )
            params.extend([n, n])
        sql += " AND (" + " OR ".join(clauses) + ")"
    sql += (
        " ORDER BY CASE WHEN r.year = s.year THEN 0 ELSE 1 END, "
        "r.year DESC, s.page_no, s.line_name_norm"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


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


def mark_duplicate_reports(conn: sqlite3.Connection) -> int:
    """按 SHA-256 标记完全重复的报告，保留每组 id 最小者作为 canonical。"""
    conn.execute("UPDATE reports SET is_duplicate=0, duplicate_of=NULL")
    groups = conn.execute(
        "SELECT sha256 FROM reports WHERE sha256 IS NOT NULL "
        "GROUP BY sha256 HAVING COUNT(*) > 1"
    ).fetchall()
    marked = 0
    for group in groups:
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM reports WHERE sha256=? ORDER BY id", (group["sha256"],)
            ).fetchall()
        ]
        canonical = ids[0]
        for dup_id in ids[1:]:
            conn.execute(
                "UPDATE reports SET is_duplicate=1, duplicate_of=? WHERE id=?",
                (canonical, dup_id),
            )
            marked += 1
    conn.commit()
    return marked


def replace_pages(conn: sqlite3.Connection, report_id: int, pages: list[dict[str, Any]]) -> None:
    """原子替换报告的全部页面，并级联清理 chunks / embedding_index / 向量表。

    页面被删除后 page_id 会变化，旧的 chunk 与向量必须先行清理，否则外键会报错，
    且旧向量会静默指向不存在的页面。
    """
    old_page_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM pages WHERE report_id=? ORDER BY id", (report_id,)
        )
    ]
    chunk_ids: list[int] = []
    if old_page_ids:
        for start in range(0, len(old_page_ids), 500):
            marks = ",".join("?" * len(old_page_ids[start : start + 500]))
            chunk_ids.extend(
                row[0]
                for row in conn.execute(
                    f"SELECT id FROM chunks WHERE page_id IN ({marks}) ORDER BY id",
                    old_page_ids[start : start + 500],
                )
            )

    if chunk_ids:
        for start in range(0, len(chunk_ids), 500):
            marks = ",".join("?" * len(chunk_ids[start : start + 500]))
            conn.execute(
                f"DELETE FROM embedding_index WHERE chunk_id IN ({marks})",
                chunk_ids[start : start + 500],
            )
        vec_tables = vector_table_names(conn)
        if vec_tables:
            load_vector_extension(conn)
            for table in vec_tables:
                for start in range(0, len(chunk_ids), 500):
                    marks = ",".join("?" * len(chunk_ids[start : start + 500]))
                    conn.execute(
                        f"DELETE FROM {table} WHERE chunk_id IN ({marks})",
                        chunk_ids[start : start + 500],
                    )
        for start in range(0, len(chunk_ids), 500):
            marks = ",".join("?" * len(chunk_ids[start : start + 500]))
            conn.execute(
                f"DELETE FROM chunks WHERE id IN ({marks})",
                chunk_ids[start : start + 500],
            )

    conn.execute("DELETE FROM pages WHERE report_id=?", (report_id,))
    conn.execute("DELETE FROM pages_fts WHERE report_id=?", (report_id,))
    if _table_exists(conn, "pages_bigram_fts"):
        conn.execute("DELETE FROM pages_bigram_fts WHERE report_id=?", (report_id,))
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
        if _table_exists(conn, "pages_bigram_fts"):
            conn.execute(
                "INSERT INTO pages_bigram_fts(page_id, company, report_id, bigrams) "
                "VALUES(?,?,?,?)",
                (page_id, p.get("company", ""), report_id, cjk_bigrams(p["content"])),
            )
    conn.commit()


def replace_statements(conn: sqlite3.Connection, report_id: int, rows: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM statements WHERE report_id=?", (report_id,))
    for r in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO statements(report_id, statement_type, line_name_orig,
                line_name_norm, value, unit, currency, year, page_no, line_no,
                is_subtotal, is_ocr, table_index, source_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                r.get("line_no"),
                r.get("is_subtotal", 0),
                r.get("is_ocr", 0),
                r.get("table_index"),
                r.get("source_id"),
            ),
        )
    _refresh_sources_for_report(conn, report_id)
    conn.commit()


def _refresh_sources_for_report(conn: sqlite3.Connection, report_id: int) -> None:
    """为三表涉及的页面/表填充统一 sources 记录，并回填 statements.source_id。"""
    conn.execute(
        """
        INSERT OR IGNORE INTO sources(
            report_id, company, report_title, page_no, table_index, locator, snippet
        )
        SELECT s.report_id, r.company, r.title, s.page_no, s.table_index,
               '《' || r.title || '》第' || s.page_no || '页', NULL
        FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE s.report_id=?
        """,
        (report_id,),
    )
    conn.execute(
        """
        UPDATE statements
        SET source_id = (
            SELECT src.id FROM sources src
            WHERE src.report_id = statements.report_id
              AND src.page_no = statements.page_no
              AND src.table_index = statements.table_index
        )
        WHERE report_id=?
        """,
        (report_id,),
    )


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    return dict(row) if row else None
