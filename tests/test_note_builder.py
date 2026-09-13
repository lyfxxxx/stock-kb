from stock_kb.charts import chart_spec, series_data
from stock_kb.generation_eval import audit_composed_markdown, page_has_number
from stock_kb.humanfmt import (
    clean_snippet,
    fmt_amount,
    fmt_yoy,
    human_amount,
    trend_sentence,
)
from stock_kb.note_builder import (
    INDICATOR_LABELS,
    format_locator,
    format_metric,
    format_value,
    render_note,
)
from stock_kb.report_html import render_html


def test_format_locator_and_value():
    assert format_locator("2025年报", 153) == "《2025年报》第153页"
    assert format_locator("", 1) == ""
    assert format_value(4049824) == "4,049,824"
    assert format_value(929.0) == "929"


def test_page_has_number_strips_commas():
    assert page_has_number("Profit 4,049,824 thousand", 4049824)
    assert page_has_number("4049824", 4049824)
    assert page_has_number("(4,163,175)", -4163175)
    assert not page_has_number("unrelated 12", 4049824)


def test_human_amount_and_fmt():
    assert human_amount(43225355, "千元") == (432.25355, "亿元")
    assert human_amount(929, "百万美元") == (9.29, "亿美元")
    assert human_amount(0.0937, "ratio") == (9.37, "%")
    assert human_amount(5, "未知单位") is None
    assert fmt_amount(43225355, "千元") == "432.3 亿元"
    assert fmt_amount(-4163175, "千元") == "-41.63 亿元"
    assert fmt_amount(0.0937, "ratio") == "9.4%"
    assert fmt_yoy(105.0, 100.0) == "+5.0%"
    assert fmt_yoy(100.0, 0) is None
    assert clean_snippet("a\n  b\r\n c  ") == "a b c"


def _rows(values_by_year, unit="千元", loc="《年报》第1页"):
    return [
        {"name": "x", "year": y, "value": v, "unit": unit, "currency": None, "locator": loc}
        for y, v in sorted(values_by_year.items())
    ]


def test_trend_sentence_shapes():
    plain = trend_sentence(
        "营业收入", _rows({2021: 41111624, 2025: 43225355}, loc="《2025年报》第152页")
    )
    assert plain and "营业收入从 2021 年的 411.1 亿元《2025年报》第152页升至" in plain
    assert plain and "2025 年的 432.3 亿元《2025年报》第152页" in plain
    assert "4 年复合增速约 1.3%（按表内原值计算）" in plain
    peak = trend_sentence(
        "归母净利润", _rows({2021: 1000000, 2024: 4708084, 2025: 4049824}, loc="《年报》第2页")
    )
    assert peak and "2024 年达到 47.08 亿元" in peak and "回落至" in peak
    outflow = trend_sentence(
        "已付股息", _rows({2021: -92781, 2025: -4133303}, loc="《年报》第3页")
    )
    assert outflow and "扩大至" in outflow
    assert trend_sentence("毛利", _rows({2025: 123})) is None  # 单点不出句
    no_loc = trend_sentence(
        "毛利",
        [
            {"name": "x", "year": 2021, "value": 1, "unit": "千元", "currency": None, "locator": ""},
            {"name": "x", "year": 2022, "value": 2, "unit": "千元", "currency": None, "locator": ""},
        ],
    )
    assert no_loc is None  # 无出处不出句


def test_series_data_flags_and_prunes_empty():
    data, unit = series_data(
        _rows({2021: -4163175, 2024: 4708084, 2025: 4049824}),
        "x",
        [2021, 2022, 2023, 2024, 2025],
    )
    assert unit == "亿元"
    assert data[1] is None  # 缺年
    assert data[0]["label"] == "-41.63 亿元" and data[0]["locator"] == "《年报》第1页"
    assert data[3]["flag"] is True  # 峰值（2024，绝对值最大且在年中外）
    assert data[4]["flag"] is True  # 末年必标
    assert data[0]["flag"] is False


def test_chart_spec_prunes_empty_series():
    empty = {"name": "空序列", "color": "#fff", "data": [None, None]}
    spec = chart_spec("bar", ["2021", "2025"], [], None)
    assert spec["series"] == []
    spec = chart_spec(
        "bar",
        ["2021", "2025"],
        [
            empty,
            {"name": "营业收入", "color": "#111", "data": [None, {"value": 1.0, "label": "1 亿元", "locator": "", "flag": True}]},
        ],
        "亿元",
    )
    assert [s["name"] for s in spec["series"]] == ["营业收入"]  # 空序列不进图例


def test_render_note_table_has_citations():
    md = render_note(
        "海底捞",
        as_of_year=2025,
        indicators=[
            {
                "name": "revenue",
                "year": 2025,
                "value": 43225355,
                "unit": "千元",
                "locator": "《2025年报》第142页",
            },
            {
                "name": "net_profit",
                "year": 2025,
                "value": 4049824,
                "unit": "千元",
                "locator": "《2025年报》第153页",
            },
        ],
        statements=[
            {
                "keyword": "已付股息",
                "year": 2025,
                "value": 1000,
                "unit": "千元",
                "locator": "《2025年报》第151页",
            }
        ],
        operating=[
            {
                "term": "翻台率",
                "locator": "《海底捞研报-国信-202502》第19页",
                "snippet": "翻台率 3.9",
            }
        ],
        shareholders=[
            {
                "term": "实际控制人",
                "locator": "《2025年报》第80页",
                "snippet": "张勇",
            }
        ],
        code="06862.HK",
        peers=["百胜中国"],
    )
    assert md.startswith("# 海底捞扫描")
    assert "一句话结论" not in md
    assert "## 股东及高管" in md
    assert "## 利润表" in md
    assert "## 资产负债" in md
    assert "## 现金流与分红" in md
    assert "## 行业与同行" in md
    assert "## 总结" in md
    assert "| 营业收入 | 2025 | 43,225,355 | 千元 | 《2025年报》第142页 |" in md
    assert "归母净利润" in md
    assert "已付股息" in md
    assert "翻台率" in md
    assert "不计算 PE" in md
    assert "关键数字须带来源" not in md  # 指令原文不得泄漏进成品
    assert "stock-note" not in md  # 过程性文字不得出现在正文
    assert "$海底捞(06862.HK)$" in md
    # 总结是公司级事实（末年复述），不是模板套话
    assert "1. 生意质量：2025 年营业收入 432.3 亿元《2025年报》第142页" in md
    assert "## 未来看点" in md and "暂无数据" in md


def test_render_note_trend_line_with_citation():
    md = render_note(
        "海底捞",
        as_of_year=2025,
        indicators=[
            {
                "name": "revenue",
                "year": y,
                "value": v,
                "unit": "千元",
                "locator": f"《{y}年报》第10页",
            }
            for y, v in ((2021, 41111624), (2025, 43225355))
        ],
        statements=[],
        operating=[],
        shareholders=[],
    )
    assert "趋势：营业收入从 2021 年的 411.1 亿元《2021年报》第10页" in md


def test_format_metric_percent():
    assert format_metric("gross_margin", 0.215).endswith("%")
    assert format_metric("revenue", 1000) == "1,000"


def test_html_report_has_charts_and_locators():
    html = render_html(
        "海底捞",
        as_of_year=2025,
        code="06862.HK",
        peers=["百胜中国"],
        indicators=[
            {
                "name": "revenue",
                "year": 2024,
                "value": 40000000,
                "unit": "千元",
                "locator": "《2024年报》第10页",
            },
            {
                "name": "revenue",
                "year": 2025,
                "value": 43225355,
                "unit": "千元",
                "locator": "《2025年报》第142页",
            },
            {
                "name": "net_profit",
                "year": 2025,
                "value": 4049824,
                "unit": "千元",
                "locator": "《2025年报》第153页",
            },
            {
                "name": "net_margin",
                "year": 2025,
                "value": 0.0937,
                "unit": "ratio",
                "locator": "",
            },
        ],
        statements=[
            {
                "keyword": "已付股息",
                "year": 2025,
                "value": 1000,
                "unit": "千元",
                "locator": "《2025年报》第151页",
            }
        ],
        operating=[{"term": "翻台率", "locator": "《研报》第19页", "snippet": "3.9\n断行"}],
        shareholders=[{"term": "股东", "locator": "《2025年报》第80页", "snippet": "张勇"}],
        format_value=format_value,
        format_metric=format_metric,
        indicator_labels=INDICATOR_LABELS,
    )
    assert "data-chart=" in html  # ECharts 图表数据内嵌
    assert "echarts.init" in html and "renderer" in html
    assert "432.3 亿元" in html  # 图表/趋势句使用人读单位
    assert "43,225,355" in html and "千元" in html  # 表格保留原值+单位列
    assert "<th>同比</th>" in html
    assert "《2025年报》第142页" in html
    assert "《2025年报》第153页" in html
    assert "股东及高管" in html
    assert "利润表" in html
    assert "不计算 PE" in html
    assert "一句话结论" not in html
    assert "关键数字须带来源" not in html  # 指令泄漏修复
    assert "stock-note" not in html  # 过程性文字不得出现在正文
    assert "生意质量：2025 年营业收入 432.3 亿元" in html  # 总结为公司级事实
    assert "3.9 断行" in html  # 摘录断行已合并


def test_audit_unit_column_and_trend_check():
    class _FakeCur:
        def fetchone(self):
            return None  # 页不存在 → page_exists False

    class FakeConn:
        def execute(self, sql, params):
            return _FakeCur()

    text = "\n".join(
        [
            "# 测试扫描",
            "## 引用明细",
            "| 指标 | 年份 | 数值 | 单位 | 来源 |",
            "|---|---|---|---|---|",
            "| 营业收入 | 2025 | 43,225,355 | 千元 | 《2025年报》第142页 |",
        ]
    )
    result = audit_composed_markdown(FakeConn(), "测试", text)
    assert result["n_rows"] == 1
    assert result["rows"][0]["unit"] == "千元"
    assert result["unit_consistency"]["trend_numbers"] == 0
