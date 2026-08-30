from stock_kb.generation_eval import page_has_number
from stock_kb.note_builder import format_locator, format_value, render_note


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


def test_render_note_table_has_citations():
    md = render_note(
        "海底捞",
        as_of_year=2025,
        indicators=[
            {
                "name": "revenue",
                "year": 2025,
                "value": 43225355,
                "locator": "《2025年报》第142页",
            },
            {
                "name": "net_profit",
                "year": 2025,
                "value": 4049824,
                "locator": "《2025年报》第153页",
            },
        ],
        statements=[
            {
                "keyword": "已付股息",
                "value": 1000,
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
    )
    assert "| 营业收入 | 2025 | 43,225,355 | 《2025年报》第142页 |" in md
    assert "归母净利润" in md
    assert "已付股息" in md
    assert "翻台率" in md
