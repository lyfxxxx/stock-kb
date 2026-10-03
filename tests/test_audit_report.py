import pytest

from stock_kb import db
from stock_kb.audit_report import audit_report


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _report(conn, text: str = "营业收入 42754687") -> int:
    conn.execute(
        "INSERT INTO reports(company, report_type, year, period_type, title, path, status) "
        "VALUES('海底捞','annual',2024,'annual','2024年报','/2024.txt','ok')"
    )
    report_id = conn.execute("SELECT id FROM reports").fetchone()["id"]
    conn.execute(
        "INSERT INTO pages(report_id, page_no, content, content_orig, char_count) "
        "VALUES(?,?,?,?,?)",
        (report_id, 142, text, text, len(text)),
    )
    conn.commit()
    return report_id


def _indicator(conn, report_id: int, name: str) -> None:
    conn.execute(
        "INSERT INTO indicators(company, year, period_type, name, value, report_id, page_no) "
        "VALUES('海底捞',2024,'annual',?,?,?,142)",
        (name, 42754687.0, report_id),
    )
    conn.commit()


_EMPTY = """run_id: r1

只说明这篇覆盖哪些年份。

## 利润表
暂无数据

## 资产负债
暂无数据

## 现金流
暂无数据

## 分红
暂无数据

## 总结
复述上文，不下新结论。
"""

_WITH_CITE = """run_id: r1

只说明范围。

## 利润表
收入见文末注释。

## 资产负债
暂无数据

## 现金流
暂无数据

## 分红
暂无数据

## 总结
复述。

## 附：注释（数据出处）
[1] 42754687 《2024年报》第142页
"""


def test_missing_run_id_fails(conn):
    result = audit_report(conn, _EMPTY.replace("run_id: r1\n\n", ""), [], "海底捞")
    assert result["ok"] is False
    assert any("run_id" in issue for issue in result["issues"])


def test_no_db_fact_with_placeholder_passes(conn):
    result = audit_report(conn, _EMPTY, [], "海底捞")
    assert result["ok"] is True
    assert result["issues"] == []


def test_revenue_present_but_section_says_missing_fails(conn):
    report_id = _report(conn)
    _indicator(conn, report_id, "revenue")
    result = audit_report(conn, _EMPTY, [], "海底捞")
    assert result["ok"] is False
    assert any("暂无数据" in issue and "revenue_series" in issue for issue in result["issues"])


def test_cite_not_in_this_run_fails(conn):
    report_id = _report(conn)
    _indicator(conn, report_id, "revenue")
    _indicator(conn, report_id, "net_profit")
    missed = [{"run_id": "r1", "hits": [{"title": "2024年报", "page": 1}]}]
    result = audit_report(conn, _WITH_CITE, missed, "海底捞")
    assert result["ok"] is False
    assert any("出处不在本次日志" in issue for issue in result["issues"])
    covered = [{"run_id": "r1", "hits": [{"title": "2024年报", "page": 142}]}]
    ok = audit_report(conn, _WITH_CITE, covered, "海底捞")
    assert ok["ok"] is True


def test_other_missing_fact_in_same_section_does_not_void_a_citation(conn):
    report_id = _report(conn)
    _indicator(conn, report_id, "revenue")
    _indicator(conn, report_id, "net_profit")
    text = _WITH_CITE.replace("收入见文末注释。", "收入见文末注释。毛利率暂无数据。")
    covered = [{"run_id": "r1", "hits": [{"title": "2024年报", "page": 142}]}]
    result = audit_report(conn, text, covered, "海底捞")
    assert result["ok"] is True
