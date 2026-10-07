from __future__ import annotations

import os

import pytest

from stock_kb import db, search
from stock_kb.classify import classify_report
from stock_kb.ingest import _mark_missing_sources, _process_file, refresh_logical_keys
from stock_kb.versioning import (
    PARSE_VERSION,
    build_logical_key,
    decide_scan_action,
    detect_market,
    event_date_from_filename,
    page_kind_for,
)


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _write(path, text: str, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _rows(conn):
    return conn.execute(
        "SELECT id, path, status, supersedes_id, parse_version, logical_key, sha256 "
        "FROM reports ORDER BY id"
    ).fetchall()


def test_decide_same_sha_stale_parse_version_reparses_not_skip():
    assert (
        decide_scan_action(
            existing_sha="abc",
            new_sha="abc",
            existing_parse_version="1999-01-01.0",
            size_unchanged=True,
            mtime_unchanged=True,
            manifest_status="ok",
            report_status="ok",
        )
        == "reparse"
    )
    assert (
        decide_scan_action(
            existing_sha="abc",
            new_sha="abc",
            existing_parse_version=PARSE_VERSION,
            size_unchanged=True,
            mtime_unchanged=True,
            manifest_status="ok",
            report_status="ok",
        )
        == "skip"
    )
    assert (
        decide_scan_action(
            existing_sha="abc",
            new_sha="def",
            existing_parse_version=PARSE_VERSION,
            size_unchanged=False,
            mtime_unchanged=False,
            manifest_status="ok",
        )
        == "new_version"
    )


def test_same_path_new_sha_archives_old_and_query_sees_only_new(conn, tmp_path):
    path = tmp_path / "2024年报.txt"
    _write(path, "旧版独有营业收入说明", mtime=1_700_000_000)
    assert _process_file(conn, {}, "海底捞", path, False, False) is True
    _write(path, "新版独有营业收入说明", mtime=1_700_000_100)
    assert _process_file(conn, {}, "海底捞", path, False, False) is True

    rows = _rows(conn)
    assert len(rows) == 2
    old = next(r for r in rows if "::superseded::" in r["path"])
    new = next(r for r in rows if r["path"] == str(path))
    assert old["status"] == "superseded"
    assert new["status"] == "ok"
    assert new["supersedes_id"] == old["id"]
    assert new["parse_version"] == PARSE_VERSION
    assert old["path"].startswith(str(path) + "::superseded::")

    for report_id, value in ((old["id"], 1.0), (new["id"], 42754687.0)):
        conn.execute(
            "INSERT INTO statements(report_id, statement_type, line_name_orig, "
            "line_name_norm, value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
            (report_id, "income", "收入", "收入", value, 2024, 142, 0),
        )
    conn.commit()
    found = db.query_statements(conn, "海底捞", year=2024, keyword="收入")
    assert len(found) == 1
    assert found[0]["report_id"] == new["id"]
    assert found[0]["value"] == 42754687.0
    assert search.fts_search(conn, "新版独有", company="海底捞")
    assert search.fts_search(conn, "旧版独有", company="海底捞") == []


def test_transcript_same_locator_new_hash_supersedes(conn, tmp_path):
    url = "https://ir.example/haidilao/2024-05-01"
    old = tmp_path / "电话会_2024-05-01_v1.txt"
    new = tmp_path / "电话会_2024-05-01_v2.txt"
    _write(old, "旧电话会正文甲甲甲", mtime=1_700_000_000)
    _write(new, "新电话会正文乙乙乙", mtime=1_700_000_100)
    _process_file(conn, {}, "海底捞", old, False, False, source_url=url)
    _process_file(conn, {}, "海底捞", new, False, False, source_url=url)
    rows = _rows(conn)
    assert len(rows) == 2
    assert rows[0]["logical_key"] == rows[1]["logical_key"]
    assert rows[0]["status"] == "superseded"
    assert rows[1]["status"] == "ok"
    assert rows[1]["supersedes_id"] == rows[0]["id"]
    assert search.fts_search(conn, "新电话会正文", company="海底捞")
    assert search.fts_search(conn, "旧电话会正文", company="海底捞") == []


def test_research_different_paths_both_stay_ok(conn, tmp_path):
    a = tmp_path / "甲券商_研报.txt"
    b = tmp_path / "乙券商_研报.txt"
    _write(a, "研报甲独立正文", mtime=1_700_000_000)
    _write(b, "研报乙独立正文", mtime=1_700_000_100)
    _process_file(conn, {}, "海底捞", a, False, False)
    _process_file(conn, {}, "海底捞", b, False, False)
    rows = _rows(conn)
    assert len(rows) == 2
    assert rows[0]["logical_key"] != rows[1]["logical_key"]
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["supersedes_id"] is None for r in rows)


def test_research_same_source_url_new_hash_supersedes(conn, tmp_path):
    url = "https://broker.example/notes/haidilao.pdf"
    a = tmp_path / "甲券商_研报.txt"
    b = tmp_path / "乙券商_研报.txt"
    _write(a, "同一链接旧研报", mtime=1_700_000_000)
    _write(b, "同一链接新研报", mtime=1_700_000_100)
    _process_file(conn, {}, "海底捞", a, False, False, source_url=url)
    _process_file(conn, {}, "海底捞", b, False, False, source_url=url)
    rows = _rows(conn)
    assert rows[0]["logical_key"] == rows[1]["logical_key"]
    assert rows[0]["status"] == "superseded"
    assert rows[1]["status"] == "ok"
    assert rows[1]["supersedes_id"] == rows[0]["id"]


def test_stale_parse_version_same_sha_reparses_in_place(conn, tmp_path):
    path = tmp_path / "点评_研报.txt"
    _write(path, "正文保持不变", mtime=1_700_000_000)
    assert _process_file(conn, {}, "海底捞", path, False, False) is True
    conn.execute("UPDATE reports SET parse_version=? WHERE path=?", ("1999-01-01.0", str(path)))
    conn.commit()
    assert _process_file(conn, {}, "海底捞", path, False, False) is True
    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]["path"] == str(path)
    assert rows[0]["status"] == "ok"
    assert rows[0]["parse_version"] == PARSE_VERSION
    assert "::superseded::" not in rows[0]["path"]


def test_older_mtime_does_not_replace_newer_row(conn, tmp_path):
    url = "https://ir.example/haidilao/2024-06-01"
    newer = tmp_path / "电话会_2024-06-01_新.txt"
    older = tmp_path / "电话会_2024-06-01_旧.txt"
    _write(newer, "较新电话会正文", mtime=1_800_000_000)
    _write(older, "较旧电话会正文", mtime=1_600_000_000)
    _process_file(conn, {}, "海底捞", newer, False, False, source_url=url)
    _process_file(conn, {}, "海底捞", older, False, False, source_url=url)
    rows = {r["path"]: r for r in _rows(conn)}
    assert rows[str(newer)]["status"] == "ok"
    assert rows[str(newer)]["supersedes_id"] is None
    assert rows[str(older)]["status"] == "superseded"
    assert search.fts_search(conn, "较新电话会", company="海底捞")
    assert search.fts_search(conn, "较旧电话会", company="海底捞") == []


def test_page_kind_transcript_and_statement(conn, tmp_path):
    statement = {
        "page_no": 3,
        "content": "Consolidated Statements of Income\nYum China Holdings, Inc.",
        "content_orig": "Consolidated Statements of Income\nYum China Holdings, Inc.",
        "char_count": 60,
    }
    assert page_kind_for(statement, "annual") == "statement"
    assert page_kind_for(statement, "transcript") == "transcript"

    # 临时目录名可能含 transcript，分类会看父目录；样例放在中性子目录下。
    root = tmp_path / "docs"
    call = root / "电话会_2024-05-01.txt"
    text = "主持人：欢迎参加业绩会。\n分析师甲：请看收入。\nConsolidated Statements of Income\n"
    _write(call, text, mtime=1_700_000_000)
    _process_file(conn, {}, "海底捞", call, False, False)
    page = conn.execute(
        "SELECT page_kind, content_orig FROM pages"
    ).fetchone()
    assert page["page_kind"] == "transcript"
    assert page["content_orig"] == text
    assert "问：" not in page["content_orig"]
    assert "答：" not in page["content_orig"]

    annual = root / "2023年报.txt"
    body = "Consolidated Statements of Income\nYum China Holdings, Inc.\n" + ("收入 " * 30)
    _write(annual, body, mtime=1_700_000_000)
    _process_file(conn, {}, "海底捞", annual, False, False)
    kind = conn.execute(
        "SELECT p.page_kind FROM pages p JOIN reports r ON r.id=p.report_id WHERE r.path=?",
        (str(annual),),
    ).fetchone()
    assert kind["page_kind"] == "statement"


def test_classify_transcript_before_research():
    meta = classify_report("国信证券_海底捞_业绩会点评.pdf")
    assert meta["report_type"] == "transcript"
    assert meta["period_type"] == "other"
    assert classify_report("研报/公司点评.pdf")["report_type"] == "research"
    assert classify_report("海底捞_earnings_call_transcript.pdf")["report_type"] == "transcript"


def test_other_files_do_not_supersede_each_other(conn, tmp_path):
    a = tmp_path / "备忘一.txt"
    b = tmp_path / "备忘二.txt"
    _write(a, "其他材料甲", mtime=1_700_000_000)
    _write(b, "其他材料乙", mtime=1_800_000_000)
    _process_file(conn, {}, "海底捞", a, False, False)
    _process_file(conn, {}, "海底捞", b, False, False)
    rows = _rows(conn)
    assert [r["status"] for r in rows] == ["ok", "ok"]


def test_missing_file_marked_without_deleting_or_touching_outside(conn, tmp_path):
    company_dir = tmp_path / "海底捞"
    path = company_dir / "备忘.txt"
    _write(path, "待删除", mtime=1_700_000_000)
    _process_file(conn, {}, "海底捞", path, False, False)
    path.unlink()
    conn.execute(
        "INSERT INTO reports(company, report_type, title, path, status) VALUES(?,?,?,?,?)",
        ("海底捞", "other", "外部", str(tmp_path / "outside" / "外部.txt"), "ok"),
    )
    conn.commit()
    marked = _mark_missing_sources(conn, company_dir, "海底捞")
    assert marked == 1
    kept = conn.execute("SELECT id, status FROM reports WHERE title='备忘'").fetchall()
    assert len(kept) == 1
    assert kept[0]["status"] == "missing"
    assert conn.execute("SELECT status FROM reports WHERE title='外部'").fetchone()["status"] == "ok"
    manifest = conn.execute(
        "SELECT status FROM manifest WHERE path=?", (str(path),)
    ).fetchone()
    assert manifest["status"] == "missing"


def test_missing_newer_file_re_elects_older_same_key(conn, tmp_path):
    company_dir = tmp_path / "海底捞"
    older = company_dir / "2025年报.txt"
    newer = company_dir / "2025年报_网络.txt"
    _write(older, "旧年报营业收入甲", mtime=1_700_000_000)
    _write(newer, "新年报营业收入乙", mtime=1_800_000_000)
    _process_file(conn, {}, "海底捞", older, False, False)
    _process_file(
        conn, {}, "海底捞", newer, False, False, retrieved_at="2026-04-24T00:00:00"
    )
    rows = {r["path"]: r for r in _rows(conn)}
    assert rows[str(older)]["logical_key"] == rows[str(newer)]["logical_key"]
    assert rows[str(older)]["status"] == "superseded"
    assert rows[str(newer)]["status"] == "ok"
    newer.unlink()
    marked = _mark_missing_sources(conn, company_dir, "海底捞")
    assert marked == 1
    rows = {r["path"]: r for r in _rows(conn)}
    assert rows[str(newer)]["status"] == "missing"
    assert rows[str(older)]["status"] == "ok"


def test_logical_key_shapes_omit_sha():
    filing = build_logical_key(
        company="海底捞",
        report_type="annual",
        year=2024,
        period_type="annual",
        language="zh",
        path=r"\\nas\海底捞\HK_Annual\2024年报.pdf",
        title="2024年报",
    )
    assert filing == "海底捞|annual|2024|annual|zh|HK"
    us = build_logical_key(
        company="百胜中国",
        report_type="annual",
        year=2024,
        period_type="annual",
        language="en",
        path=r"C:\yumc\2024-10k.pdf",
        title="2024 10-K",
    )
    assert us == "百胜中国|annual|2024|annual|en|US"
    transcript = build_logical_key(
        company="海底捞",
        report_type="transcript",
        year=2024,
        period_type="other",
        language="zh",
        path=r"C:\calls\电话会_20240315.txt",
        title="电话会_20240315",
        source_url="https://ir.example/c",
    )
    assert transcript == "海底捞|transcript|2024-03-15|https://ir.example/c"
    assert event_date_from_filename("电话会2024.txt") == "2024-01-01"
    assert event_date_from_filename("纪要.txt") == "undated"
    research = build_logical_key(
        company="海底捞",
        report_type="research",
        year=None,
        period_type="other",
        language="zh",
        path=r"C:\a\研报.pdf",
        title="研报",
    )
    assert research == r"海底捞|research|C:\a\研报.pdf"
    other = build_logical_key(
        company="海底捞",
        report_type="other",
        year=None,
        period_type="other",
        language="zh",
        path=r"C:\a\备忘.txt",
        title="备忘",
    )
    assert other == r"海底捞|other|C:\a\备忘.txt"
    assert "sha" not in filing


def test_detect_market_uses_filename_not_parent_dir():
    assert (
        detect_market(r"D:\年报\百胜中国_2024年报.pdf", "百胜中国_2024年报")
        == "HK"
    )
    assert (
        detect_market(
            r"D:\年报\百胜中国_2024_Annual_Report.pdf",
            "百胜中国_2024_Annual_Report",
        )
        == "US"
    )
    assert (
        detect_market(r"\\nas\海底捞\HK_Annual\2024年报.pdf", "2024年报")
        == "HK"
    )
    assert detect_market(r"C:\yumc\2024-10k.pdf", "2024 10-K") == "US"
    assert (
        detect_market(
            r"D:\年报\百胜中国_2016_Annual_Report.pdf",
            "百胜中国_2016_Annual_Report",
        )
        == "US"
    )
    hk = build_logical_key(
        company="百胜中国",
        report_type="annual",
        year=2024,
        period_type="annual",
        language="en",
        path=r"D:\年报\百胜中国_2024年报.pdf",
        title="百胜中国_2024年报",
    )
    us = build_logical_key(
        company="百胜中国",
        report_type="annual",
        year=2024,
        period_type="annual",
        language="en",
        path=r"D:\年报\百胜中国_2024_Annual_Report.pdf",
        title="百胜中国_2024_Annual_Report",
    )
    assert hk == "百胜中国|annual|2024|annual|en|HK"
    assert us == "百胜中国|annual|2024|annual|en|US"


def test_refresh_splits_hk_annual_from_us_10k(conn):
    conn.execute("INSERT INTO companies(name) VALUES('百胜中国')")
    conn.execute(
        """
        INSERT INTO reports(
            company, report_type, language, year, period_type, title, path,
            status, logical_key, sha256, mtime
        ) VALUES (
            '百胜中国', 'annual', 'en', 2024, 'annual', '百胜中国_2024年报', ?,
            'ok', '百胜中国|annual|2024|annual|en|UNK', 'sha-hk', 200
        )
        """,
        (r"D:\年报\百胜中国_2024年报.pdf",),
    )
    conn.execute(
        """
        INSERT INTO reports(
            company, report_type, language, year, period_type, title, path,
            status, logical_key, sha256, mtime
        ) VALUES (
            '百胜中国', 'annual', 'en', 2024, 'annual', '百胜中国_2024_Annual_Report', ?,
            'superseded', '百胜中国|annual|2024|annual|en|UNK', 'sha-us', 100
        )
        """,
        (r"D:\年报\百胜中国_2024_Annual_Report.pdf",),
    )
    conn.execute(
        """
        INSERT INTO reports(
            company, report_type, language, year, period_type, title, path,
            status, logical_key, sha256, mtime
        ) VALUES (
            '百胜中国', 'annual', 'en', 2024, 'annual', '百胜中国_2024_HK_Annual_Report', ?,
            'missing', '百胜中国|annual|2024|annual|en|HK', 'sha-hk', 50
        )
        """,
        (r"D:\old\百胜中国_2024_HK_Annual_Report.pdf",),
    )
    conn.commit()
    refresh_logical_keys(conn)
    rows = {
        row["title"]: row
        for row in conn.execute(
            "SELECT id, title, status, logical_key, is_duplicate, duplicate_of FROM reports"
        )
    }
    hk = rows["百胜中国_2024年报"]
    us = rows["百胜中国_2024_Annual_Report"]
    old = rows["百胜中国_2024_HK_Annual_Report"]
    assert hk["logical_key"] == "百胜中国|annual|2024|annual|en|HK"
    assert hk["status"] == "ok"
    assert hk["is_duplicate"] == 0
    assert us["logical_key"] == "百胜中国|annual|2024|annual|en|US"
    assert us["status"] == "ok"
    assert us["is_duplicate"] == 0
    assert old["status"] == "missing"
    assert old["is_duplicate"] == 1
    assert old["duplicate_of"] == hk["id"]
