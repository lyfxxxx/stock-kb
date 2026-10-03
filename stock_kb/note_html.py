"""把 stock-note 扫描稿 Markdown 渲染成单文件 HTML。

给人看的终稿是 HTML。Markdown 仍留下，供改稿和 audit-report。
图表沿用 report_html 的 ECharts SVG 壳，点上的出处来自文末注释。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from stock_kb import charts
from stock_kb.report_html import _INIT_JS, _chart_block, _esc

_CITE = re.compile(r"《([^》]+)》\s*第\s*(\d+)\s*页")
_NOTE_NUM = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_ECHARTS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "vendor" / "echarts-5.6.0.min.js"
)

_CSS = """
:root { --ink:#1c1915; --muted:#6b6458; --line:#e6e1d6; --paper:#fbfaf7; --accent:#1f4e79; }
body { margin:0; background:#efece4; color:var(--ink); font:16px/1.65 "Segoe UI","PingFang SC","Noto Sans SC",sans-serif; }
main { max-width:920px; margin:32px auto; background:var(--paper); padding:40px 48px 64px; box-shadow:0 1px 0 #ddd6c8; }
h1 { font-size:28px; font-weight:650; margin:0 0 8px; }
h2 { font-size:20px; border-bottom:1px solid var(--line); padding-bottom:6px; margin:36px 0 12px; }
.meta, figcaption { color:var(--muted); font-size:14px; }
p, li { max-width:72ch; }
table.cite { border-collapse:collapse; width:100%; font-size:14px; margin:12px 0 8px; }
table.cite th, table.cite td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
table.cite th { background:#f3f0e8; }
figure.chart-fig .chart { width:100%; height:280px; }
.judgment { border-left:3px solid var(--accent); padding-left:12px; }
"""


def render_note_html(markdown: str) -> str:
    """扫描稿 Markdown → 单文件 HTML。正文句子保持原样，审计正则仍能读到。"""
    text = markdown.replace("\r\n", "\n").strip()
    lines = text.split("\n")
    notes = _endnotes(lines)
    title = "扫描稿"
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break
    body = _blocks(lines, notes, _note_values(lines))
    echarts_js = _ECHARTS_PATH.read_text(encoding="utf-8")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n<main>\n"
        + body
        + "\n</main>\n<script>\n"
        + echarts_js
        + "\n</script>\n<script>\n"
        + _INIT_JS
        + "\n</script>\n</body>\n</html>\n"
    )


def render_note_file(path: str | Path, out: str | Path | None = None) -> Path:
    source = Path(path)
    target = Path(out) if out else source.with_suffix(".html")
    target.write_text(render_note_html(source.read_text(encoding="utf-8")), encoding="utf-8")
    return target


def _inline(text: str) -> str:
    return _esc(text)


def _index(header: list[str], label: str) -> int | None:
    for i, cell in enumerate(header):
        if label in cell:
            return i
    return None


def _cell_value(cell: str, notes: dict[str, str]) -> tuple[float | None, str]:
    numbers = _NOTE_NUM.findall(cell)
    if not numbers:
        return None, ""
    ref = re.search(r"\[(\d+)\]", cell)
    locator = notes.get(ref.group(1), "") if ref else ""
    return float(numbers[0].replace(",", "")), locator


def _endnotes(lines: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^\[(\d+)\]\s+", line.strip())
        cite = _CITE.search(line)
        if match and cite:
            found[match.group(1)] = f"《{cite.group(1)}》第{cite.group(2)}页"
    return found


def _blocks(
    lines: list[str],
    notes: dict[str, str],
    note_values: dict[str, list[dict[str, Any]]],
) -> str:
    html_parts: list[str] = []
    chart_nodes: list[str] = []
    section = ""
    profit_rows: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("# "):
            html_parts.append(f"<h1>{_inline(stripped[2:].strip())}</h1>")
            i += 1
            continue
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            html_parts.append(f"<h2>{_inline(section)}</h2>")
            i += 1
            continue
        if stripped.startswith("|"):
            table, rows, i = _table(lines, i, notes)
            html_parts.append(table)
            if "利润表" in section and rows:
                profit_rows = rows
            continue
        if stripped.startswith("图："):
            block = _section_chart(section, profit_rows, note_values, chart_nodes)
            if block:
                html_parts.append(block)
            html_parts.append(f"<p>{_inline(stripped)}</p>")
            i += 1
            continue
        if stripped.startswith(">"):
            html_parts.append(f'<p class="meta">{_inline(stripped[1:].strip())}</p>')
            i += 1
            continue
        if re.match(r"^\d+\.\s+", stripped):
            items, i = _list(lines, i, ordered=True)
            html_parts.append(items)
            continue
        if stripped.startswith("- "):
            items, i = _list(lines, i, ordered=False)
            html_parts.append(items)
            continue
        paragraph = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        text = " ".join(paragraph)
        if text.startswith("判断："):
            html_parts.append(f'<p class="judgment">\n{text}\n</p>')
        elif text.startswith("run_id:"):
            html_parts.append(f"<p class=\"meta\">\n{text}\n</p>")
        else:
            html_parts.append(f"<p>{_inline(text)}</p>")
    return "\n".join(html_parts)


def _is_block_start(stripped: str) -> bool:
    return stripped.startswith(("#", "|", ">", "-", "图：")) or bool(
        re.match(r"^\d+\.\s+", stripped)
    )


def _list(lines: list[str], start: int, *, ordered: bool) -> tuple[str, int]:
    items: list[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if ordered:
            match = re.match(r"^\d+\.\s+(.*)$", stripped)
            if not match:
                break
            items.append(f"<li>{_inline(match.group(1))}</li>")
        else:
            if not stripped.startswith("- "):
                break
            items.append(f"<li>{_inline(stripped[2:])}</li>")
        i += 1
    tag = "ol" if ordered else "ul"
    return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>", i


def _table(
    lines: list[str], start: int, notes: dict[str, str]
) -> tuple[str, list[dict[str, Any]], int]:
    raw: list[str] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw.append(lines[i].strip())
        i += 1
    rows_cells = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in raw
        if not re.match(r"^\|?\s*-+", line)
    ]
    if not rows_cells:
        return "", [], i
    header, body = rows_cells[0], rows_cells[1:]
    thead = "".join(f"<th>{_esc(cell)}</th>" for cell in header)
    tbody = []
    series: list[dict[str, Any]] = []
    year_idx = _index(header, "年份")
    for row in body:
        tbody.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
        if year_idx is None or year_idx >= len(row):
            continue
        year = _YEAR.search(row[year_idx])
        if not year:
            continue
        for name, label in (
            ("revenue", "收入"),
            ("net_profit", "归母净利"),
            ("operating_cashflow", "经营现金流"),
        ):
            idx = _index(header, label)
            if idx is None or idx >= len(row):
                continue
            value, locator = _cell_value(row[idx], notes)
            if value is None:
                continue
            series.append(
                {
                    "name": name,
                    "year": int(year.group(0)),
                    "value": value,
                    "unit": "千元",
                    "currency": "CNY",
                    "locator": locator,
                }
            )
    table = (
        '<table class="cite"><thead><tr>'
        + thead
        + "</tr></thead><tbody>"
        + "".join(tbody)
        + "</tbody></table>"
    )
    return table, series, i


def _section_chart(
    section: str,
    profit_rows: list[dict[str, Any]],
    note_values: dict[str, list[dict[str, Any]]],
    chart_nodes: list[str],
) -> str:
    if "利润表" in section and profit_rows:
        return _chart(
            "fig-profit",
            "bar",
            [
                ("revenue", "营业收入", "#1f4e79"),
                ("net_profit", "归母净利", "#c45911"),
                ("operating_cashflow", "经营现金流", "#2e7d4f"),
            ],
            profit_rows,
            chart_nodes,
        )
    if "现金流" in section:
        rows = (
            note_values["operating_cashflow"]
            + note_values["capex"]
            + note_values["dividend"]
        )
        if rows:
            return _chart(
                "fig-cash",
                "bar",
                [
                    ("operating_cashflow", "经营现金流", "#1f4e79"),
                    ("capex", "购买物业", "#6b8f71"),
                    ("dividend", "已付股息", "#c45911"),
                ],
                rows,
                chart_nodes,
            )
    if "资产负债" in section:
        rows = note_values["cash"] + note_values["debt"]
        if rows:
            return _chart(
                "fig-balance",
                "bar",
                [
                    ("cash", "银行结余及现金", "#1f4e79"),
                    ("debt", "银行借款", "#c45911"),
                ],
                rows,
                chart_nodes,
            )
    return ""


def _chart(
    div_id: str,
    kind: str,
    defs: list[tuple[str, str, str]],
    rows: list[dict[str, Any]],
    chart_nodes: list[str],
) -> str:
    years = sorted({int(r["year"]) for r in rows})
    safe_rows = []
    for row in rows:
        item = dict(row)
        # 悬停提示不要写成《》第N页，否则和坐标数字落在同一行，审计会误配。
        item["locator"] = (
            str(row.get("locator") or "")
            .replace("《", "")
            .replace("》", " ")
        )
        safe_rows.append(item)
    series = []
    axis = None
    for name, label, color in defs:
        data, unit = charts.series_data(safe_rows, name, years)
        series.append({"name": label, "color": color, "data": data})
        axis = axis or unit
    spec = charts.chart_spec(kind, [str(y) for y in years], series, axis)
    if not spec.get("series"):
        return ""
    chart_nodes.append(div_id)
    return _chart_block(div_id, spec, "悬停数据点可查看数值与出处。", "")


def _note_values(lines: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "operating_cashflow": [],
        "capex": [],
        "dividend": [],
        "cash": [],
        "debt": [],
    }
    labels = {
        "经营现金流": "operating_cashflow",
        "购买物业": "capex",
        "已付股息": "dividend",
        "银行结余及现金": "cash",
        "银行借款": "debt",
    }
    for line in lines:
        if not line.strip().startswith("["):
            continue
        cite = _CITE.search(line)
        head = line.split("《", 1)[0]
        numbers = _NOTE_NUM.findall(head)
        if line.strip().startswith("["):
            numbers = numbers[1:]
        year = _YEAR.search(cite.group(1) if cite else "")
        if not cite or not numbers or not year:
            continue
        for label, name in labels.items():
            if label in line:
                grouped[name].append(
                    {
                        "name": name,
                        "year": int(year.group(0)),
                        "value": float(numbers[-1].replace(",", "")),
                        "unit": "千元",
                        "currency": "CNY",
                        "locator": f"《{cite.group(1)}》第{cite.group(2)}页",
                    }
                )
                break
    return grouped
