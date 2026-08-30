import pytest

from stock_kb import db, search


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()



def test_prefer_query_years_only_when_query_has_year():
    hits = [
        {"year": 2019, "title": "2019年报"},
        {"year": 2024, "title": "2024年报"},
        {"year": 2022, "title": "2022年报"},
    ]
    out = search.prefer_query_years(hits, "海底捞 2022 年减值", year=None, top_k=2)
    assert [h["year"] for h in out] == [2022, 2019]
    unchanged = search.prefer_query_years(hits, "海底捞 减值", year=None, top_k=3)
    assert [h["year"] for h in unchanged] == [2019, 2024, 2022]
    hard = search.prefer_query_years(hits, "海底捞 2022 年减值", year=2022, top_k=2)
    assert [h["year"] for h in hard] == [2019, 2024]


def test_query_statements_excludes_next_year_comparative(conn):
    conn.execute("INSERT INTO companies(name) VALUES('测试')")
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('测试','annual',2024,'annual','2024年报','/2024.pdf','ok')"
    )
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('测试','annual',2025,'annual','2025年报','/2025.pdf','ok')"
    )
    y2024 = conn.execute("SELECT id FROM reports WHERE year=2024").fetchone()["id"]
    y2025 = conn.execute("SELECT id FROM reports WHERE year=2025").fetchone()["id"]
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
        (y2024, "income", "收入", "收入", 100.0, 2024, 10, 0),
    )
    conn.execute(
        "INSERT INTO statements(report_id, statement_type, line_name_orig, line_name_norm, "
        "value, year, page_no, table_index) VALUES(?,?,?,?,?,?,?,?)",
        (y2025, "income", "收入", "收入", 100.0, 2024, 12, 0),
    )
    conn.commit()
    body = db.query_statements(conn, "测试", year=2024, keyword="收入")
    assert len(body) == 1
    assert body[0]["report_year"] == 2024
    assert body[0]["page_no"] == 10
    both = db.query_statements(
        conn, "测试", year=2024, keyword="收入", include_comparatives=True
    )
    assert len(both) == 2
    assert both[0]["report_year"] == 2024
