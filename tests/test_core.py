from __future__ import annotations

import os

import pytest

from stock_kb import db, search, vector
from stock_kb.classify import classify_report
from stock_kb.indicators import (
    METRIC_RULES,
    _candidate_score,
    _pick_metric_row,
    compute_indicators,
)
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


def test_indicator_net_profit_prefers_owners_over_total():
    rule = METRIC_RULES["net_profit"]
    owners = _candidate_score("Owners of the Company 本公司拥有人", rule)
    total = _candidate_score("Profit for the year 年内溢利", rule)
    yumc = _candidate_score("NetIncome—YumChinaHoldings,Inc. $", rule)
    assert owners is not None and total is not None and yumc is not None
    assert owners > total
    assert yumc > total
    assert _candidate_score("Share of profit of an associate 应占联营公司溢利", rule) is None
    assert _candidate_score("non-controlling interests", rule) is None


def test_pick_net_profit_closest_owners_to_total():
    items = [
        {"_score": 90, "line_name": "Profit for the year 年内溢利", "value": 4495399.0},
        {"_score": 130, "line_name": "owners of the Company", "value": 4499080.0},
        {"_score": 130, "line_name": "Owners of the Company 本公司拥有人", "value": 4562834.0},
    ]
    picked = _pick_metric_row("net_profit", items)
    assert picked["value"] == 4499080.0


def test_compute_indicators_uses_owners_profit(tmp_path):
    db_path = tmp_path / "ind.db"
    conn = db.connect(db_path)
    conn.execute("INSERT INTO companies(name) VALUES('海底捞')")
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('海底捞','annual',2023,'annual','2023年报','/a.pdf','ok')"
    )
    rid = conn.execute("SELECT id FROM reports").fetchone()["id"]
    for name, value, page in (
        ("Profit for the year 年内溢利", 4495399.0, 278),
        ("owners of the Company", 4499080.0, 279),
        ("Owners of the Company 本公司拥有人", 4562834.0, 279),
    ):
        conn.execute(
            "INSERT INTO statements(report_id, statement_type, line_name_orig, "
            "line_name_norm, value, unit, year, page_no, table_index) "
            "VALUES(?,?,?,?,?,?,?,?,0)",
            (rid, "income", name, name, value, "千元", 2023, page),
        )
    conn.commit()
    conn.close()
    compute_indicators({"db_path": str(db_path)})
    conn = db.connect(db_path)
    row = conn.execute(
        "SELECT value, page_no, line_name FROM indicators WHERE name='net_profit'"
    ).fetchone()
    conn.close()
    assert row["value"] == 4499080.0
    assert row["page_no"] == 279
    assert "owners" in (row["line_name"] or "").lower()


def test_like_search_orders_by_term_frequency(conn):
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
                "content": "股息 " * 40,
                "content_orig": "股息",
                "char_count": 80,
                "is_ocr": 0,
                "company": "测试",
            },
            {
                "page_no": 2,
                "content": ("长文本填充" * 80) + " 股息",
                "content_orig": "股息",
                "char_count": 400,
                "is_ocr": 0,
                "company": "测试",
            },
        ],
    )
    hits = search.fts_search(conn, "股息", company="测试")
    assert hits
    assert hits[0]["page_no"] == 1


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


def test_query_statements_filters_by_keyword(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    conn.execute(
        "INSERT INTO reports(company, report_type, language, year, period_type, title, path, status) "
        "VALUES('测试','annual','zh',2024,'annual','2024年报','/a.pdf','ok')"
    )
    report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
        (report_id, "cashflow", "Dividends paid", "已付股息", -100.0, 2024, 10, 0),
    )
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
        (report_id, "income", "Revenue", "营业收入", 1.0, 2024, 3, 0),
    )
    conn.commit()
    hits = db.query_statements(conn, "测试", keyword="已付股息")
    assert len(hits) == 1
    assert hits[0]["value"] == -100.0
    assert hits[0]["page_no"] == 10
    en = db.query_statements(conn, "测试", keyword="dividends paid")
    assert len(en) == 1
    empty = db.query_statements(conn, "测试", keyword="火星")
    assert empty == []
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
        (
            report_id,
            "cashflow",
            "Purchase of property, plant and equipment",
            "购买物业厂房及设备",
            -50.0,
            2024,
            12,
            0,
        ),
    )
    conn.commit()
    capex = db.query_statements(conn, "测试", keyword="资本开支")
    assert len(capex) == 1
    assert capex[0]["page_no"] == 12


def test_claim_needles_keep_entities_drop_paraphrase():
    assert search.query_years("海底捞 2026 年营业收入是多少？") == [2026]
    assert search.query_years("百胜中国 1998 年同店销售") == [1998]
    assert search.claim_needles("海底捞 2026 年营业收入是多少？", "海底捞") == []
    assert "火星开" in search.claim_needles("海底捞在火星开了多少家店？", "海底捞")
    assert search.claim_needles("百胜中国欧洲门店数量", "百胜中国") == ["欧洲"]
    assert search.claim_needles("百胜中国比特币储备规模", "百胜中国") == ["比特币"]
    assert "量子计算" in search.claim_needles("海底捞量子计算研发投入", "海底捞")
    assert "瑞幸" in search.claim_needles("瑞幸咖啡 2024 年营业收入", "百胜中国")
    assert "核电站" in search.claim_needles("海底捞核电站持股比例", "海底捞")
    assert search.claim_needles("百胜中国 1998 年同店销售", "百胜中国") == []
    assert search.claim_needles("海底捞的啄木鸟计划与门店优化", "海底捞") == ["啄木鸟"]
    assert search.claim_needles("除了炸鸡和披萨，热饮这条线怎么走？", "百胜中国") == []
    assert search.claim_needles("咖啡能不能成为百胜的第二增长曲线？", "百胜中国") == []
    assert search.claim_needles("海底捞靠什么把店长留住并开出下一家？", "海底捞") == []
    assert search.claim_needles("百胜中国 store openings 门店净增", "百胜中国") == []
    assert search.claim_needles("百胜中国的利润是变厚还是变薄？", "百胜中国") == []
    assert search.claim_needles("百胜中国股东能拿回多少现金？", "百胜中国") == []
    assert search.claim_needles("客人来得勤不勤、一桌坐得转不转？", "海底捞") == []
    assert search.claim_needles("座位周转是在变快还是变慢？", "海底捞") == []
    assert search.claim_needles("海底捞赚到的利润有多少能变成真金白银？", "海底捞") == []
    assert search.claim_needles("利润薄不薄，最近是在好转吗？", "百胜中国") == []


def test_embed_query_expands_paraphrase_only():
    from stock_kb.vector import _expand_bilingual

    expanded = _expand_bilingual("座位周转是在变快还是变慢？")
    assert "翻台率" in expanded
    cash = _expand_bilingual("海底捞赚到的利润有多少能变成真金白银？")
    assert "经营现金流" in cash or "现金流" in cash


def test_year_out_of_corpus_and_needle_grounding(conn):
    conn.execute("INSERT INTO companies(name) VALUES('海底捞')")
    conn.execute(
        "INSERT INTO reports(company, report_type, language, year, title, path, status) "
        "VALUES('海底捞','annual','zh',2024,'2024年报','/a.pdf','ok')"
    )
    conn.commit()
    assert search.years_out_of_corpus(conn, "海底捞 2026 年营业收入", "海底捞") is True
    assert search.years_out_of_corpus(conn, "海底捞 2024 年营业收入", "海底捞") is False
    assert search.years_out_of_corpus(conn, "海底捞在火星开了多少家店", "海底捞") is False
    assert vector._content_has_needle("火星基地规划", ["火星开"]) is False
    assert vector._content_has_needle("啄木鸟计划关店", ["啄木鸟"]) is True
    assert vector._content_has_needle("任意正文", []) is True


def test_fts_does_not_fill_top_k_with_trigram_or(conn):
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
                "content": "开店计划与门店数量 营业收入 持股比例 研发投入",
                "content_orig": "开店计划与门店数量 营业收入 持股比例 研发投入",
                "char_count": 28,
                "is_ocr": 0,
                "company": "测试",
            },
            {
                "page_no": 2,
                "content": "经营活动现金流量净额 1,000",
                "content_orig": "经营活动现金流量净额 1,000",
                "char_count": 18,
                "is_ocr": 0,
                "company": "测试",
            },
        ],
    )
    assert search.fts_search(conn, "海底捞在火星开了多少家店", company="测试") == []
    assert search.fts_search(conn, "火星 开店", company="测试") == []
    assert search.fts_search(conn, "2026 年营业收入是多少", company="测试") == []
    assert search.fts_search(conn, "开店", company="测试")
    both = search.fts_search(conn, "开店 营业收入", company="测试")
    assert both and both[0]["page_no"] == 1
    phrase = search.fts_search(conn, "经营活动现金流量净额", company="测试")
    assert phrase and phrase[0]["page_no"] == 2


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


def test_split_chunks_respects_size():
    text = "\n".join(["翻台率提升一二三四"] * 80)
    c400 = vector._split_chunks(text, size=400)
    c800 = vector._split_chunks(text, size=800)
    assert c400
    assert all(len(c) <= 400 for c in c400)
    assert all(len(c) <= 800 for c in c800)
    assert len(c400) > len(c800)


def test_ensure_chunks_resplit_after_reset(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    conn.execute(
        "INSERT INTO reports(company, report_type, title, path, status) "
        "VALUES('测试','annual','r','/r.pdf','ok')"
    )
    report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
    content = "\n".join(["abcdefghij"] * 100)
    conn.execute(
        "INSERT INTO pages(report_id, page_no, content, content_orig, char_count, is_ocr) "
        "VALUES(?,?,?,?,?,?)",
        (report_id, 1, content, content, len(content), 0),
    )
    conn.commit()
    vector._ensure_chunks(conn, size=800)
    n800 = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    vector._reset_chunks(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM embedding_index").fetchone()["n"] == 0
    vector._ensure_chunks(conn, size=400)
    n400 = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    assert n400 > n800
    assert conn.execute("SELECT MAX(LENGTH(content)) AS m FROM chunks").fetchone()["m"] <= 400


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__]))
