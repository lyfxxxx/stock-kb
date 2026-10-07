from stock_kb.route import (
    TOOL_INDICATORS,
    TOOL_NO_ANSWER,
    TOOL_SEARCH,
    TOOL_STATEMENTS,
    route,
)


def test_route_indicators():
    d = route("海底捞 2024 年营业收入是多少？", company="海底捞")
    assert d["tool"] == TOOL_INDICATORS
    assert d["name"] == "revenue"
    assert d["year"] == 2024
    assert route("海底捞 2024 年归母净利润", "海底捞")["name"] == "net_profit"
    assert route("百胜中国 2025 年 Total revenues", "百胜中国")["name"] == "revenue"
    assert (
        route("海底捞 2024 年经营活动所得现金净额", "海底捞")["name"]
        == "operating_cashflow"
    )
    assert route("百胜中国 2024 年 Total Assets", "百胜中国")["name"] == "total_assets"
    assert route("海底捞 2024 年净资产", "海底捞")["name"] == "total_equity"
    assert route("海底捞 2024 年毛利", "海底捞")["name"] == "gross_profit"


def test_route_statements_not_search():
    d = route("海底捞 2024 年已付股息", "海底捞")
    assert d["tool"] == TOOL_STATEMENTS
    assert d["keyword"] == "已付股息"
    assert route("海底捞 资本开支", "海底捞")["keyword"] == "资本开支"
    assert route("海底捞 购买物业", "海底捞")["keyword"] == "资本开支"
    imp = route("海底捞 2022 年减值", "海底捞")
    assert imp["tool"] == TOOL_STATEMENTS
    assert imp["fallback"] == TOOL_SEARCH
    assert route("百胜中国 dividends paid", "百胜中国")["tool"] == TOOL_STATEMENTS
    assert route("海底捞 股息", "海底捞")["tool"] == TOOL_STATEMENTS


def test_route_search_operating():
    assert route("海底捞 翻台率", "海底捞")["tool"] == TOOL_SEARCH
    assert route("海底捞 同店销售", "海底捞")["tool"] == TOOL_SEARCH
    assert route("海底捞 师徒制", "海底捞")["tool"] == TOOL_SEARCH
    assert route("Yum China same-store sales trend", "百胜中国")["tool"] == TOOL_SEARCH


def test_route_no_answer():
    # 未传入目录上界时，不把 2026 一律当成库外。
    assert route("海底捞 2026 年营业收入是多少？", "海底捞")["tool"] == TOOL_INDICATORS
    assert route("海底捞在火星开了多少家店？", "海底捞")["tool"] == TOOL_NO_ANSWER
    assert route("百胜中国比特币储备规模", "百胜中国")["tool"] == TOOL_NO_ANSWER
    assert route("瑞幸咖啡 2024 年营业收入", "百胜中国")["tool"] == TOOL_NO_ANSWER
    old = route("海底捞 1998 年营业收入", "海底捞")
    assert old["tool"] == TOOL_NO_ANSWER
    assert old["reason"] == "year_out_of_corpus"


def test_route_corpus_max_year():
    question_2026 = "海底捞 2026 年营业收入是多少？"
    question_2027 = "海底捞 2027 年营业收入是多少？"
    inside = route(question_2026, "海底捞", corpus_max_year=2026)
    assert inside["tool"] == TOOL_INDICATORS
    assert inside["name"] == "revenue"
    assert inside["year"] == 2026
    outside = route(question_2027, "海底捞", corpus_max_year=2026)
    assert outside["tool"] == TOOL_NO_ANSWER
    assert outside["reason"] == "year_out_of_corpus"
    still_out = route(question_2026, "海底捞", corpus_max_year=2025)
    assert still_out["tool"] == TOOL_NO_ANSWER
    assert still_out["reason"] == "year_out_of_corpus"
    early = route("海底捞 1998 年营业收入", "海底捞", corpus_max_year=2026)
    assert early["tool"] == TOOL_NO_ANSWER
    assert early["reason"] == "year_out_of_corpus"


def test_route_same_store_not_revenue():
    d = route("百胜中国 2023 年同店销售", "百胜中国")
    assert d["tool"] == TOOL_SEARCH
