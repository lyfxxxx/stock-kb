from __future__ import annotations

import os

import pytest

from stock_kb import db, search, vector
from stock_kb.classify import classify_report
from stock_kb.indicators import _candidate_score, METRIC_RULES
from stock_kb.parsers.pdf_parser import (
    _detect_unit_currency,
    _statement_type_from_page,
    extract_statements_from_pages,
)


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_replace_pages_cascades_chunks_and_vector_metadata(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    conn.execute(
        "INSERT INTO reports(company, report_type, title, path, status) "
        "VALUES('测试','annual','r','/r.pdf','ok')"
    )
    report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
    db.replace_pages(
        conn,
        report_id,
        [
            {
                "page_no": 1,
                "content": "hello",
                "content_orig": "hello",
                "char_count": 5,
                "is_ocr": 0,
                "company": "测试",
            }
        ],
    )
    page_id = conn.execute("SELECT id FROM pages WHERE report_id=?", (report_id,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO chunks(page_id, chunk_no, content) VALUES(?,?,?)",
        (page_id, 1, "hello"),
    )
    chunk_id = conn.execute("SELECT id FROM chunks WHERE page_id=?", (page_id,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO embedding_index(model, chunk_id, dim, vec_table) VALUES(?,?,?,?)",
        ("m", chunk_id, 2, "chunks_vec_2"),
    )
    conn.execute("CREATE TABLE chunks_vec_2 (chunk_id INTEGER PRIMARY KEY, embedding BLOB)")
    conn.execute("INSERT INTO chunks_vec_2 VALUES(?, ?)", (chunk_id, b"\x01\x02"))
    conn.commit()

    db.replace_pages(
        conn,
        report_id,
        [
            {
                "page_no": 1,
                "content": "world",
                "content_orig": "world",
                "char_count": 5,
                "is_ocr": 0,
                "company": "测试",
            }
        ],
    )

    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE page_id=?", (page_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM embedding_index WHERE chunk_id=?", (chunk_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks_vec_2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pages WHERE report_id=?", (report_id,)).fetchone()[0] == 1


def test_statement_page_detection_rejects_notes_and_summary():
    assert _statement_type_from_page(
        {"content": "Notes to the Consolidated Financial Statements\ncash flows"}
    ) is None
    assert _statement_type_from_page(
        {
            "content": (
                "FINANCIAL SUMMARY\n"
                "Consolidated Statements of Income data for the years\n"
                "cash flows 1,000"
            )
        }
    ) is None
    assert (
        _statement_type_from_page(
            {"content": "Consolidated Statements of Income\nYum China Holdings, Inc."}
        )
        == "income"
    )
    assert (
        _statement_type_from_page(
            {
                "content": (
                    "APPENDIX I ACCOUNTANTS’ REPORT\n"
                    "Consolidated Balance Sheets\nYum China Holdings, Inc."
                )
            }
        )
        == "balance"
    )


def test_extract_statements_years_and_units():
    page = {
        "page_no": 1,
        "content": (
            "Consolidated Statements of Income\n"
            "Yum China Holdings, Inc.\n"
            "Years ended December 31, 2025, 2024 and 2023\n"
            "(in US$ millions)\n"
            "2025 2024 2023\n"
            "Company sales $ 11,039 $ 10,651 $ 10,391\n"
            "Total revenues 11,797 11,303 10,978\n"
        ),
        "content_orig": None,
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "测试", "r", report_year=2025)
    total = [r for r in rows if r["line_name_norm"].startswith("Total revenues")]
    assert len(total) == 3
    assert [(r["year"], r["value"]) for r in total] == [
        (2025, 11797.0),
        (2024, 11303.0),
        (2023, 10978.0),
    ]
    assert all(r["unit"] == "百万美元" and r["currency"] == "USD" for r in total)


def test_unit_currency_rejects_embedded_rmb():
    assert _detect_unit_currency("short-termbankdeposits\n(in US$ millions)") == (
        "百万美元",
        "USD",
    )
    assert _detect_unit_currency("RMB’000 RMB’000") == ("千元", "CNY")


def test_classify_research_before_report_period():
    meta = classify_report("国信证券_百胜中国_2023年报费用管控效果显著.pdf")
    assert meta["report_type"] == "research"
    assert classify_report("百胜中国_2025_Annual_Report.pdf")["report_type"] == "annual"


def test_indicator_rules_do_not_take_company_sales_as_revenue():
    rule = METRIC_RULES["revenue"]
    assert _candidate_score("Company sales", rule) is None
    assert _candidate_score("Total revenues", rule) is not None


def test_fts_two_char_query_snippet_and_filter(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    conn.execute(
        "INSERT INTO reports(company, report_type, language, year, title, path, status) "
        "VALUES('测试','annual','zh',2024,'2024年报','/a.pdf','ok')"
    )
    report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
    db.replace_pages(
        conn,
        report_id,
        [
            {
                "page_no": 1,
                "content": "分红政策与股息说明",
                "content_orig": "分紅政策與股息說明",
                "char_count": 9,
                "is_ocr": 0,
                "company": "测试",
            }
        ],
    )
    hits = search.fts_search(conn, "股息", company="测试", year=2024)
    assert hits and hits[0]["page_no"] == 1
    assert "股息" in hits[0]["snippet"]
    assert search.fts_search(conn, "現金流", company="测试") == []


def test_mark_duplicate_reports(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    for i, title in enumerate(("a", "b")):
        conn.execute(
            "INSERT INTO reports(company, report_type, title, path, sha256, status) "
            "VALUES('测试','research',?,?,?, 'ok')",
            (title, f"/{i}.pdf", "same-hash"),
        )
    conn.commit()
    assert db.mark_duplicate_reports(conn) == 1
    rows = conn.execute(
        "SELECT id, title, is_duplicate, duplicate_of FROM reports ORDER BY id"
    ).fetchall()
    assert rows[0]["is_duplicate"] == 0
    assert rows[1]["is_duplicate"] == 1
    assert rows[1]["duplicate_of"] == rows[0]["id"]


def test_vec_table_name_is_model_specific():
    assert vector._vec_table_name("BAAI/bge-m3") != vector._vec_table_name(
        "intfloat/multilingual-e5-large"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__]))
