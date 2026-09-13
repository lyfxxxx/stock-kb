"""Self-contained HTML scan report: vendored ECharts (SVG renderer) + locators.

单文件 HTML：图表数据以 JSON spec 内嵌，由仓库 assets/vendor/ 的 ECharts 在
浏览器渲染（SVG renderer，DOM 中仍是 <svg>）。出处明细只保留在各节的 cite
表格一处；图表悬停提示展示「数值 + 单位 + 《文件》第N页」。
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

from stock_kb import charts, humanfmt

FormatValue = Callable[[Any], str]
FormatMetric = Callable[[str, Any], str]

_ECHARTS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "vendor" / "echarts-5.6.0.min.js"
)

_INIT_JS = """
(function () {
  "use strict";
  function specToOption(spec) {
    return {
      animation: false,
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: function (p) {
          var d = p.data || {};
          var loc = d.locator ? "\\uff08" + d.locator + "\\uff09" : "\\uff08\\u6d3e\\u751f\\u503c\\uff0c\\u65e0\\u51fa\\u5904\\uff09";
          return p.seriesName + " " + p.name + "\\uff1a" + (d.label || p.value) + loc;
        }
      },
      legend: { top: 0, textStyle: { color: "#3f3a32", fontSize: 12 } },
      xAxis: {
        type: "category",
        data: spec.categories,
        axisTick: { alignWithLabel: true },
        axisLine: { lineStyle: { color: "#b9b1a3" } },
        axisLabel: { color: "#3f3a32" }
      },
      yAxis: {
        type: "value",
        name: spec.unit || "",
        nameTextStyle: { color: "#6b6458" },
        splitLine: { lineStyle: { color: "#e6e1d6" } },
        axisLabel: { color: "#6b6458" }
      },
      series: spec.series.map(function (s) {
        return {
          type: spec.kind,
          name: s.name,
          data: s.data,
          itemStyle: { color: s.color },
          barMaxWidth: 36,
          connectNulls: false,
          symbolSize: 6,
          lineStyle: { width: 2 },
          label: {
            show: true,
            position: "top",
            color: "#3f3a32",
            fontSize: 10,
            textBorderColor: "#fbfaf7",
            textBorderWidth: 2,
            formatter: function (p) {
              return p.data && p.data.flag ? p.data.label : "";
            }
          },
          labelLayout: { hideOverlap: true }
        };
      })
    };
  }
  document
    .querySelectorAll("script[type='application/json'][data-chart]")
    .forEach(function (node) {
      var el = document.getElementById(node.getAttribute("data-chart"));
      if (!el) return;
      try {
        var spec = JSON.parse(node.textContent);
        echarts.init(el, null, { renderer: "svg" }).setOption(specToOption(spec));
      } catch (e) {
        el.textContent = "\\u56fe\\u8868\\u6570\\u636e\\u89e3\\u6790\\u5931\\u8d25";
      }
    });
})();
"""


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _years_union(*rows_lists: list[dict[str, Any]]) -> list[int]:
    years: set[int] = set()
    for rows in rows_lists:
        for r in rows:
            y = r.get("year")
            if y is not None:
                years.add(int(y))
    return sorted(years)


def _chart_block(div_id: str, spec: dict[str, Any] | None, caption: str, fallback: str) -> str:
    if not spec or not spec.get("series"):
        return f"<p>{_esc(fallback)}</p>"
    data = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    return (
        f'<figure class="chart-fig">'
        f'<div id="{div_id}" class="chart"></div>'
        f'<script type="application/json" data-chart="{div_id}">{data}</script>'
        f"<figcaption>{_esc(caption)}</figcaption>"
        f"</figure>"
    )


def _trend_para(*sentences: str | None) -> str:
    text = "；".join(s for s in sentences if s)
    if not text:
        return ""
    return f'<p class="trend">{_esc(text)}</p>'


def render_html(
    company: str,
    *,
    as_of_year: int | None,
    code: str | None,
    peers: list[str],
    indicators: list[dict[str, Any]],
    statements: list[dict[str, Any]],
    operating: list[dict[str, Any]],
    shareholders: list[dict[str, Any]],
    format_value: FormatValue,
    format_metric: FormatMetric,
    indicator_labels: dict[str, str],
    industry: list[dict[str, Any]] | None = None,
) -> str:
    period = f"{as_of_year}年报" if as_of_year else "未知期间"
    tags = [f"${_esc(company)}" + (f"({_esc(code)})" if code else "") + "$"]
    tags.extend(f"${_esc(p)}$" for p in peers if p and p != company)
    years = _years_union(indicators, statements)
    labeled = []
    for r in indicators:
        item = dict(r)
        item["label"] = indicator_labels.get(r.get("name"), r.get("name"))
        labeled.append(item)
    for s in statements:
        item = dict(s)
        item["name"] = s.get("keyword")
        item["label"] = s.get("keyword")
        labeled.append(item)

    rev_years = years or ([as_of_year] if as_of_year else [])
    cats = [str(y) for y in rev_years]
    fig_profit = fig_margin = fig_bs = fig_cf = None
    caption_hover = "数据出处见文末注释；悬停数据点可查看数值与出处。"

    def build_chart(kind: str, defs: list[tuple[str, str, str, list[dict[str, Any]]]]) -> dict[str, Any] | None:
        series = []
        axis_unit = None
        for name, label, color, rows in defs:
            data, unit = charts.series_data(rows, name, rev_years)
            series.append({"name": label, "color": color, "data": data})
            axis_unit = axis_unit or unit
        return charts.chart_spec(kind, cats, series, axis_unit)

    if rev_years:
        fig_profit = build_chart(
            "bar",
            [
                ("revenue", "营业收入", "#1f4e79", indicators),
                ("net_profit", "归母净利润", "#c45911", indicators),
            ],
        )
        fig_margin = build_chart(
            "line",
            [
                ("gross_margin", "毛利率", "#2e7d4f", indicators),
                ("net_margin", "净利率", "#7a3e9d", indicators),
            ],
        )
        fig_bs = build_chart(
            "bar",
            [
                ("total_assets", "总资产", "#5b7c99", indicators),
                ("total_equity", "净资产", "#1f4e79", indicators),
            ],
        )
        fig_cf = build_chart(
            "bar",
            [
                ("operating_cashflow", "经营现金流", "#1f4e79", indicators),
                ("已付股息", "已付股息", "#c45911", labeled),
                ("资本开支", "资本开支", "#6b8f71", labeled),
            ],
        )

    def _t(rows: list[dict[str, Any]], name: str, label: str) -> str | None:
        return humanfmt.trend_sentence(label, [r for r in rows if r.get("name") == name])

    trend_profit = _t(indicators, "revenue", "营业收入") or _t(
        labeled, "revenue", "营业收入"
    )
    profit_np = _t(indicators, "net_profit", "归母净利润")
    trend_bs = _t(indicators, "total_equity", "净资产") or _t(
        indicators, "total_assets", "总资产"
    )
    trend_cf = _t(indicators, "operating_cashflow", "经营现金流")
    trend_div = _t(labeled, "已付股息", "已付股息")
    recap = humanfmt.summary_quality(indicators, labeled)
    risk = humanfmt.summary_risk(labeled)

    profit_rows = [
        r
        for r in labeled
        if r.get("name") in {"revenue", "net_profit", "gross_profit", "gross_margin", "net_margin"}
    ]
    bs_rows = [r for r in labeled if r.get("name") in {"total_assets", "total_equity"}]
    cf_rows = [
        r for r in labeled if r.get("name") in {"operating_cashflow", "已付股息", "资本开支"}
    ]

    def hits_html(items: list[dict[str, Any]] | None, empty_text: str) -> str:
        if not items:
            return f"<p class='empty'>{_esc(empty_text)}</p>"
        lis = []
        for h in items:
            loc = h.get("locator") or "（无页码，不作为数字依据）"
            term = _esc(h.get("term") or "")
            snip = _esc(humanfmt.clean_snippet(h.get("snippet"), 160))
            lis.append(f"<li><strong>{term}</strong> {_esc(loc)} {snip}</li>")
        return "<ul>" + "".join(lis) + "</ul>"

    def table_html(rows: list[dict[str, Any]]) -> str:
        rows = [
            r
            for r in rows
            if r.get("value") is not None and (r.get("locator") or "") and r.get("name")
        ]
        if not rows:
            return "<p>暂无数据</p>"
        order: list[str] = []
        for r in rows:
            if r["name"] not in order:
                order.append(r["name"])
        rows = sorted(rows, key=lambda r: (order.index(r["name"]), -int(r["year"])))
        raw = {(r["name"], int(r["year"])): float(r["value"]) for r in rows}
        body = []
        for r in rows:
            prev = raw.get((r["name"], int(r["year"]) - 1))
            yoy = humanfmt.fmt_yoy(r["value"], prev) or ""
            body.append(
                "<tr>"
                f"<td>{_esc(r.get('label'))}</td>"
                f"<td>{_esc(r.get('year'))}</td>"
                f"<td>{_esc(format_metric(r.get('name') or '', r.get('value')))}</td>"
                f"<td>{_esc(r.get('unit') or '')}</td>"
                f"<td>{_esc(yoy)}</td>"
                f"<td>{_esc(r.get('locator'))}</td>"
                "</tr>"
            )
        return (
            '<table class="cite"><thead><tr>'
            "<th>指标</th><th>年份</th><th>数值</th><th>单位</th><th>同比</th><th>来源</th>"
            "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
        )

    css = """
:root { --ink:#1c1915; --muted:#6b6458; --line:#e6e1d6; --paper:#fbfaf7; --accent:#1f4e79; }
body { margin:0; background:#efece4; color:var(--ink); font:16px/1.6 "Segoe UI","PingFang SC","Noto Sans SC",sans-serif; }
main { max-width:920px; margin:32px auto; background:var(--paper); padding:40px 48px 64px; box-shadow:0 1px 0 #ddd6c8; }
h1 { font-size:28px; font-weight:650; margin:0 0 8px; }
.meta { color:var(--muted); font-size:14px; margin-bottom:24px; }
.tags { font-size:15px; margin:0 0 28px; color:var(--accent); }
h2 { font-size:20px; border-bottom:1px solid var(--line); padding-bottom:6px; margin:36px 0 12px; }
p, li { max-width:72ch; }
table.cite { border-collapse:collapse; width:100%; font-size:14px; margin:12px 0 8px; }
table.cite th, table.cite td { border:1px solid var(--line); padding:6px 8px; text-align:left; }
table.cite th { background:#f3f0e8; }
figure { margin:12px 0 20px; }
figure.chart-fig .chart { width:100%; height:280px; }
figcaption { font-size:12px; color:var(--muted); margin-top:8px; }
.formula { font-size:13px; color:var(--muted); }
.empty { color:var(--muted); }
.trend { border-left:3px solid var(--line); padding-left:12px; }
"""
    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(company)}扫描</title>
<style>{css}</style>
</head>
<body>
<main>
<h1>{_esc(company)}扫描</h1>
<p class="meta">数据截至：{_esc(period)}｜来源：stock-kb 财报/研报库（组稿底稿，无模型判断；关键数字均标注《文件》页码）</p>
<p class="tags">{" ".join(tags)}</p>

<h2>股东及高管</h2>
{hits_html(shareholders, "暂无带出处的股东/高管信息。")}

<h2>利润表</h2>
{_trend_para(trend_profit, profit_np)}
{_chart_block("fig-profit", fig_profit, caption_hover, "暂无收入/净利序列，不绘制。")}
{_chart_block("fig-margin", fig_margin, "利润率由收入与毛利/归母净利计算，为派生值（不设注释号）；原值见下表。", "暂无利润率序列，不绘制。")}
{table_html([r for r in profit_rows if r.get("name") not in {"gross_margin", "net_margin"}])}

<h2>分产品或分地区</h2>
{hits_html(operating, "暂无带出处的分产品/分地区或经营数据。")}

<h2>资产负债</h2>
<p class="formula">净现金公式（华域扫描同口径，库内无借款明细时不计算）：货币资金 − 短期借款 − 一年内到期非流动负债 − 长期借款。</p>
{_trend_para(trend_bs)}
{_chart_block("fig-bs", fig_bs, caption_hover, "暂无资产负债序列，不绘制。")}
{table_html(bs_rows)}

<h2>现金流与分红</h2>
{_trend_para(trend_cf, trend_div)}
{_chart_block("fig-cf", fig_cf, caption_hover, "暂无现金流/股息/资本开支序列，不绘制。")}
{table_html(cf_rows)}

<h2>行业与同行</h2>
{hits_html(industry, "暂无带出处的行业规模/集中度数据（组稿路径不摘录无出处预测）。")}

<h2>未来看点</h2>
<p class="empty">暂无数据</p>

<h2>总结</h2>
<ol>
<li>生意质量：{_esc(recap or "暂无带出处的年度事实。")}</li>
<li>估值：库内无市价，不计算 PE / 股息率。派息见「已付股息」行（须有出处）。</li>
<li>风险：{_esc(risk or "暂无带出处的减值/借款明细。")}</li>
</ol>
</main>
<noscript>图表需启用 JavaScript 查看；各节数字出处见对应表格。</noscript>
"""
    echarts_js = _ECHARTS_PATH.read_text(encoding="utf-8")
    return (
        body
        + "<script>\n"
        + echarts_js
        + "\n</script>\n<script>\n"
        + _INIT_JS
        + "\n</script>\n</body>\n</html>\n"
    )
