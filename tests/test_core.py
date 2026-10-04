from __future__ import annotations

import os

import pytest

from stock_kb import db, search, vector
from stock_kb.classify import classify_report
from stock_kb.indicators import (
    METRIC_RULES,
    _candidate_score,
    _pick_by_source_tier,
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


def test_statement_page_detection_condensed_and_combined():
    # 中报标题：Condensed/简明 前缀剥离后命中词典
    assert (
        _statement_type_from_page(
            {
                "content": (
                    "Condensed Consolidated Statement of Profit or Loss and "
                    "Other Comprehensive Income\nfor the six months\n2025"
                )
            }
        )
        == "income"
    )
    assert (
        _statement_type_from_page({"content": "Condensed Consolidated Statement of Cash Flows"})
        == "cashflow"
    )
    assert _statement_type_from_page({"content": "簡明綜合財務狀況表"}) == "balance"
    assert (
        _statement_type_from_page({"content": "簡明綜合損益及其他全面收益表（未經審核）"})
        == "income"
    )
    # 百胜早期 10-K：Consolidated and Combined 变体 + (Loss) 后缀
    assert (
        _statement_type_from_page(
            {"content": "Consolidated and Combined Statements of Income (Loss)"}
        )
        == "income"
    )
    assert (
        _statement_type_from_page(
            {"content": "Consolidated and Combined Statements of Cash Flows"}
        )
        == "cashflow"
    )
    assert (
        _statement_type_from_page({"content": "Consolidated and Combined Balance Sheets"})
        == "balance"
    )
    # 中报财务摘要页的中英混排标题不是报表正文页，仍应拒绝
    assert (
        _statement_type_from_page(
            {
                "content": (
                    "CONDENSED CONSOLIDATED STATEMENT OF PROFIT OR 簡明綜合損益及其他全面收益表\n"
                    "人民币千元 2025 2024\n"
                    "收入 40,561,900"
                )
            }
        )
        is None
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


def test_extract_statements_subtotal_and_wrapped_label():
    page = {
        "page_no": 1,
        "content": "\n".join(
            [
                "Consolidated Statement of Financial Position",
                "As at December 31, 2024",
                "Notes 2024 2023",
                "RMB’000 RMB’000",
                "Non-current Assets 非流動資產",
                "Property, plant and equipment 物業、廠房及設備 16 3,000 2,900",
                "999 900",
                "Current Assets 流動資產",
                "Inventories 存貨 23 1,000 900",
                "Financial assets at fair value through 按公允值計入其他全面收益的",
                "other comprehensive income 金融資產 22 324 150",
                "1,500 1,400",
            ]
        ),
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "测试", "r", report_year=2024)
    by = {(r["line_name_norm"], r["year"]): r for r in rows}
    # 无标签小计行挂最近的小节标题（norm 列已转简体），line_no 参与唯一键
    assert ("Non-current Assets 非流动资产", 2024) in by
    assert by[("Non-current Assets 非流动资产", 2024)]["is_subtotal"] == 1
    assert by[("Non-current Assets 非流动资产", 2024)]["value"] == 999.0
    assert ("Current Assets 流动资产", 2024) in by
    assert by[("Current Assets 流动资产", 2024)]["value"] == 1500.0
    # 折行标签拼接：上半行 + 下半行
    stitched = [
        r
        for r in rows
        if "fairvaluethrough" in _norm(r["line_name_norm"])
        and not r["is_subtotal"]
    ]
    assert stitched and all(
        "金融資產" in r["line_name_orig"] and "other" in r["line_name_orig"].lower()
        for r in stitched
    )


def test_extract_statements_fvtpl_wrap_keeps_current_liabilities_subtotal():
    """2026 中报：FVTPL 折在「…的金融」/「負債」，不得顶掉「流动负债」小节标题。"""
    page = {
        "page_no": 53,
        "content": "\n".join(
            [
                "Condensed Consolidated Statement of Financial Position",
                "As at June 30, 2026",
                "Notes 2026 2025",
                "RMB’000 RMB’000",
                "Current Liabilities 流動負債",
                "Trade payables 貿易應付款項 18 1,668,363 1,910,661",
                "Financial liabilities at FVTPL 按公允值計入損益的金融",
                "負債 21 98,004 121,152",
                "Contract liabilities 合約負債 22 867,460 895,767",
                "8,816,002 9,266,374",
                "Total Assets less Current Liabilities 資產總額減流動負債 12,330,706 12,766,240",
            ]
        ),
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "测试", "r", report_year=2026)
    by = {(r["line_name_norm"], r["year"]): r for r in rows}
    assert by[("Current Liabilities 流动负债", 2026)]["is_subtotal"] == 1
    assert by[("Current Liabilities 流动负债", 2026)]["value"] == 8816002.0
    assert by[("Current Liabilities 流动负债", 2025)]["value"] == 9266374.0
    stitched = [
        r
        for r in rows
        if "fvtpl" in _norm(r["line_name_norm"]) and not r["is_subtotal"]
    ]
    assert stitched
    assert all("負債" in r["line_name_orig"] for r in stitched)
    assert all(
        by[("Total Assets less Current Liabilities 资产总额减流动负债", y)]["value"] == val
        for y, val in ((2026, 12330706.0), (2025, 12766240.0))
    )


def test_extract_statements_prepayment_wrap_and_june_header():
    page = {
        "page_no": 52,
        "content": "\n".join(
            [
                "Condensed Consolidated Statement of Financial Position",
                "As at June 30, 2026",
                "Notes 2026 2025",
                "RMB’000 RMB’000",
                "Current Assets 流動資產",
                "June 30, December 31,",
                "Trade and other receivables and prepayments 貿易及其他應收款項及預",
                "付款項 17 1,339,741 1,503,657",
                "Financial assets at FVTPL 按公允值計入損",
                "益的金融資產 126,638 182,671",
                "loss (“FVTPL”) 允值計入損益」）的金融",
                "資產 41,171 57,451",
                "Purchase of other financial assets 購買其他金融資",
                "產 57 -819,368 -296,787",
                "10,775,998 12,290,803",
            ]
        ),
        "is_ocr": 0,
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "测试", "r", report_year=2026)
    names = {r["line_name_orig"] for r in rows}
    assert not any(n.strip() in {"June", "付款項", "益的金融資產", "產"} for n in names)
    assert not any(n.lstrip().startswith("loss") for n in names)
    recv = [
        r
        for r in rows
        if "prepayments" in r["line_name_orig"].lower() and not r["is_subtotal"]
    ]
    assert recv
    assert any("付款項" in r["line_name_orig"] for r in recv)
    assert {(r["year"], r["value"]) for r in recv} == {
        (2026, 1339741.0),
        (2025, 1503657.0),
    }
    fvtpl = [r for r in rows if "fvtpl" in _norm(r["line_name_norm"]) and not r["is_subtotal"]]
    assert fvtpl
    assert all("益的金融資產" in r["line_name_orig"] for r in fvtpl)
    assert {(r["year"], r["value"]) for r in fvtpl} == {
        (2026, 126638.0),
        (2025, 182671.0),
    }
    sub = [r for r in rows if r["is_subtotal"] and r["year"] == 2026]
    assert sub and sub[0]["value"] == 10775998.0


def test_extract_statements_ocr_pairs_label_and_number_blocks():
    page = {
        "page_no": 174,
        "is_ocr": 1,
        "content": """
Consolidated Balance Sheets
Yum China Holdings, Inc.
December 31, 2017 and 2016
(in US$ millions, except for number of shares)

ASSETS
Current Assets
Cash and cash equivalents
Short-term investments
Accounts receivable, net
Inventories, net
Prepaid expenses and other current assets
Total Current Assets
Property, plant and equipment, net
Goodwill
Intangible assets, net
Investments in unconsolidated affiliates
Other assets
Deferred income taxes
Total Assets
LIABILITIES, REDEEMABLE NONCONTROLLING INTEREST AND EQUITY
Current Liabilities
Accounts payable and other current liabilities
Income taxes payable
Total Current Liabilities
Capital lease obligations
Other liabilities and deferred credits
Total Liabilities
Redeemable Noncontrolling Interest
Equity
Common stock, $0.01 par value; 1,000,000,000 shares authorized;
388,860,534.42 shares and 383,344,835.42 shares issued at December 31,
2017 and December 31, 2016, respectively; 384,720,152 shares and
383,344,835.42 shares outstanding at December 31, 2017 and December 31,
2016, respectively
Treasury stock
Additional paid-in capital
Retained earnings
Accumulated other comprehensive income
Total Equity - Yum China Holdings, Inc.
Noncontrolling interests
Total Equity
Total Lial
ities, Redeemable Noncontrolling Interest and Equity

2017                         2016

1,059                            885
205                          79
81                           74
297                         268
160                            120
1,802                          1,426
1,691                          1,647
108                              79
101                              88
89                          71
373                         254
99                            162
4,263                      3,727
978                         971
39                          33
1,017                             1,004
28                          28
354                         252
1,399                          1,284
5                                一
4                            4
(148)                            (20)
2,383                      2,352
405                          40
138                                1
2,782                      2,377
77                          66
2,859                      2,443
4,263                      3,727
""",
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "百胜中国", "r", report_year=2017)
    assert all(r["is_ocr"] == 1 for r in rows)
    assets = [
        r
        for r in rows
        if r["year"] == 2017 and "totalassets" in _norm(r["line_name_norm"])
    ]
    assert assets and assets[0]["value"] == 4263.0
    assert not any("Total Lial" == r["line_name_orig"] for r in rows)
    cash = [
        r
        for r in rows
        if r["year"] == 2017 and r["line_name_orig"].startswith("Cash and cash")
    ]
    assert cash and cash[0]["value"] == 1059.0


def test_extract_statements_ocr_fail_page_keeps_is_ocr_2():
    page = {
        "page_no": 171,
        "is_ocr": 2,
        "content": "\n".join(
            [
                "Consolidated and Combined Statements of Income",
                "2017 2016",
                "(in US$ millions)",
                "Income Before Income Taxes (cid:3) 810 700",
                "Basic Earnings Per Common Share $ 1.04 0.90",
            ]
        ),
    }
    page["content_orig"] = page["content"]
    rows = extract_statements_from_pages([page], "百胜中国", "r", report_year=2017)
    assert rows
    assert all(r["is_ocr"] == 2 for r in rows)
    assert not any("cid" in (r["line_name_orig"] or "").lower() for r in rows)


def _norm(text: str) -> str:
    import re as _re

    return _re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text).casefold())


def test_compute_indicators_haidilao_total_assets(tmp_path):
    db_path = tmp_path / "ta.db"
    conn = db.connect(db_path)
    conn.execute("INSERT INTO companies(name) VALUES('海底捞')")
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('海底捞','annual',2024,'annual','2024年报','/h.pdf','ok')"
    )
    rid = conn.execute("SELECT id FROM reports").fetchone()["id"]
    for name, value, page, line_no, subtotal in (
        ("Total Assets less Current Liabilities 資產總額減流動負債", 15677436.0, 145, 27, 0),
        ("Current Liabilities 流動負債", 7021037.0, 145, 22, 1),
        ("Current Liabilities 流動負債", 7103821.0, 145, 25, 1),
    ):
        conn.execute(
            "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
            "value, unit, currency, year, page_no, line_no, is_subtotal) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (rid, "balance", name, name, value, "千元", "CNY", 2024, page, line_no, subtotal),
        )
    conn.commit()
    from stock_kb.indicators import compute_indicators

    compute_indicators({"db_path": str(db_path)})
    row = conn.execute(
        "SELECT value, unit, page_no FROM indicators "
        "WHERE company='海底捞' AND name='total_assets' AND period_type='annual'"
    ).fetchone()
    assert row is not None
    assert row["value"] == 15677436.0 + 7103821.0
    assert row["page_no"] == 145
    conn.close()


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


def test_compute_indicators_skips_superseded_report(tmp_path):
    db_path = tmp_path / "live.db"
    conn = db.connect(db_path)
    conn.execute("INSERT INTO companies(name) VALUES('海底捞')")
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('海底捞','annual',2024,'annual','旧2024年报','/old.pdf','superseded')"
    )
    old_id = conn.execute("SELECT id FROM reports WHERE title='旧2024年报'").fetchone()["id"]
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('海底捞','annual',2024,'annual','2024年报','/new.pdf','ok')"
    )
    new_id = conn.execute("SELECT id FROM reports WHERE title='2024年报'").fetchone()["id"]
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, unit, currency, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?,?,0)",
        (old_id, "income", "Revenue 收入", "Revenue 收入", 111.0, "千元", "CNY", 2024, 1),
    )
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, unit, currency, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?,?,0)",
        (new_id, "income", "Revenue 收入", "Revenue 收入", 42754687.0, "千元", "CNY", 2024, 142),
    )
    conn.commit()
    conn.close()
    compute_indicators({"db_path": str(db_path)})
    conn = db.connect(db_path)
    row = conn.execute(
        "SELECT value, report_id, page_no FROM indicators WHERE name='revenue'"
    ).fetchone()
    conn.close()
    assert row["value"] == 42754687.0
    assert row["report_id"] == new_id
    assert row["page_no"] == 142


def _indicator_item(**kwargs):
    base = {
        "_score": 100,
        "company": "百胜中国",
        "year": 2017,
        "period_type": "annual",
        "name": "revenue",
        "value": 7769.0,
        "unit": "百万美元",
        "currency": "USD",
        "report_id": 1,
        "page_no": 170,
        "line_name": "Totalrevenues",
        "_report_year": 2017,
        "_is_ocr": 0,
    }
    base.update(kwargs)
    return base


def test_pick_by_source_tier_own_year_beats_comparative_and_ocr():
    items = [
        _indicator_item(value=7700.0, report_id=1, _report_year=2017, _is_ocr=0),
        _indicator_item(value=7769.0, report_id=2, _report_year=2018, _is_ocr=0),
        _indicator_item(value=7700.0, report_id=3, _report_year=2017, _is_ocr=1),
    ]
    picked = _pick_by_source_tier("revenue", items)
    assert picked["report_id"] == 1
    assert picked["source_kind"] == "own_year"


def test_pick_by_source_tier_ocr_promoted_when_agrees_with_comparative():
    items = [
        _indicator_item(value=7769.0, report_id=2, page_no=170, _report_year=2018, _is_ocr=0),
        _indicator_item(value=7769.0, report_id=1, page_no=171, _report_year=2017, _is_ocr=1),
    ]
    picked = _pick_by_source_tier("revenue", items)
    assert picked["report_id"] == 1
    assert picked["source_kind"] == "ocr_own"


def test_pick_by_source_tier_keeps_comparative_when_ocr_disagrees():
    items = [
        _indicator_item(value=7769.0, report_id=2, _report_year=2018, _is_ocr=0),
        _indicator_item(value=4263.0, report_id=1, _report_year=2017, _is_ocr=1),
    ]
    picked = _pick_by_source_tier("revenue", items)
    assert picked["report_id"] == 2
    assert picked["source_kind"] == "comparative"


def test_pick_by_source_tier_ignores_ocr_quality_fail():
    items = [
        _indicator_item(value=810.0, report_id=1, _report_year=2017, _is_ocr=2),
        _indicator_item(value=7769.0, report_id=2, _report_year=2018, _is_ocr=0),
    ]
    picked = _pick_by_source_tier("revenue", items)
    assert picked["report_id"] == 2
    assert picked["source_kind"] == "comparative"


def test_compute_indicators_writes_source_kind(tmp_path):
    db_path = tmp_path / "kind.db"
    conn = db.connect(db_path)
    conn.execute("INSERT INTO companies(name) VALUES('百胜中国')")
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('百胜中国','annual',2018,'annual','2018年报','/2018.pdf','ok')"
    )
    rid = conn.execute("SELECT id FROM reports").fetchone()["id"]
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, unit, currency, year, page_no, table_index, is_ocr) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (rid, "income", "Total revenues", "Total revenues", 7769.0, "百万美元", "USD", 2017, 170, 0, 0),
    )
    conn.commit()
    conn.close()
    compute_indicators({"db_path": str(db_path)})
    conn = db.connect(db_path)
    row = conn.execute(
        "SELECT value, source_kind, report_id FROM indicators WHERE name='revenue'"
    ).fetchone()
    conn.close()
    assert row["value"] == 7769.0
    assert row["source_kind"] == "comparative"
    assert row["report_id"] == rid


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
