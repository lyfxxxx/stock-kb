"""扫描稿图表 spec：序列 → ECharts 数据点（人读单位 + 每点出处），纯函数。

绘图由 report_html 内嵌的 vendored ECharts（SVG renderer）在浏览器完成，
本模块只产出 JSON-able spec，保持可单测、可审计。数据点的 label 为人读口径
字符串（'432.3 亿元' / '9.4%'），locator 供悬停提示，flag 标记图上直接标注的点。
"""

from __future__ import annotations

from typing import Any

from stock_kb.humanfmt import format_scaled, human_amount


def series_data(
    rows: list[dict[str, Any]],
    name: str,
    years: list[int],
) -> tuple[list[dict[str, Any] | None], str | None]:
    """按 years 取一个指标的 ECharts data 点列。

    返回 (data, unit_label)：data 与 years 等长，缺年/空值为 None；
    unit_label 是该序列的人读单位（'亿元' / '%' / None），供坐标轴命名。
    行需含 name/year/value/unit/currency/locator 字段。
    """
    by_year: dict[int, dict[str, Any]] = {
        int(r["year"]): r
        for r in rows
        if r.get("name") == name
        and r.get("year") is not None
        and r.get("value") is not None
    }
    data: list[dict[str, Any] | None] = []
    unit_label: str | None = None
    for y in years:
        r = by_year.get(y)
        if not r:
            data.append(None)
            continue
        h = human_amount(r.get("value"), r.get("unit"), r.get("currency"))
        if h is None:
            # 未知单位：退回原值展示，不带单位
            try:
                v = float(r["value"])
            except (TypeError, ValueError):
                data.append(None)
                continue
            lab = f"{v:,.0f}"
            ul = None
        else:
            v, ul = h
            lab = format_scaled(v, ul)
        if unit_label is None and ul:
            unit_label = ul
        data.append(
            {
                "value": round(v, 4),
                "label": lab,
                "locator": r.get("locator") or "",
                "flag": False,
            }
        )
    filled = [i for i, p in enumerate(data) if p]
    if filled:
        data[filled[-1]]["flag"] = True  # 末年
        peak = max(filled, key=lambda i: abs(data[i]["value"]))
        data[peak]["flag"] = True  # 峰值（含负值取绝对值最大）
    return data, unit_label


def chart_spec(
    kind: str,
    categories: list[str],
    series: list[dict[str, Any]],
    axis_unit: str | None,
) -> dict[str, Any]:
    """组装 spec；剔除全空序列（图例不出现空系列）。kind: 'bar' | 'line'。"""
    kept = [s for s in series if s and any(p is not None for p in s.get("data") or [])]
    return {
        "kind": kind,
        "categories": categories,
        "unit": axis_unit or "",
        "series": kept,
    }
