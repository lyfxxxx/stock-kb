from pathlib import Path

from stock_kb.note_html import render_note_html


def test_render_note_html_keeps_audit_text_and_draws_chart():
    markdown = """
# 示例扫描

run_id: demo-1

## 利润表

| 年份 | 收入 | 归母净利 | 经营现金流 |
|---|---|---|---|
| 2024 | 10 [1] | 2 [2] | 3 [3] |
| 2025 | 11 [4] | 2 [5] | 4 [6] |

图：收入与归母净利，点与文末注释相同，单位千元。

判断：收入略增。

## 附：注释（数据出处）

[1] 收入 10 《2024年报》第1页
[2] 归母净利 2 《2024年报》第2页
[3] 经营现金流 3 《2024年报》第3页
[4] 收入 11 《2025年报》第1页
[5] 归母净利 2 《2025年报》第2页
[6] 经营现金流 4 《2025年报》第3页
"""
    html = render_note_html(markdown)
    assert "<h2>利润表</h2>" in html
    assert "\nrun_id: demo-1\n" in html
    assert 'id="fig-profit"' in html
    assert "《2024年报》第1页" in html
    assert "echarts" in html
    assert Path("assets/vendor/echarts-5.6.0.min.js").stat().st_size > 0
