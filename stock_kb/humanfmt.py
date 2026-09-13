"""人读口径工具：库内原值 → 亿/亿美元等展示单位、确定性趋势句、摘录清洗。

库内 statements/indicators 的 value 不做单位换算（unit 记 千元/百万美元/ratio）。
图表、正文趋势句使用这里的人读口径；出处表「数值」列保留原值并另加「单位」列。
纯函数、无 IO，便于单测与 generation_eval 的口径一致性自检复用。
"""

from __future__ import annotations

import re
from typing import Any

# unit 标签 → (人读单位, 原值 → 人读值的除数)。库内现存 千元/CNY 与 百万美元/USD，
# 其余为常见变体兜底；ratio（派生比率）单独处理为百分比。
_UNIT_SCALES: dict[str, tuple[str, float]] = {
    "千元": ("亿元", 100_000.0),
    "万元": ("亿元", 10_000.0),
    "元": ("亿元", 100_000_000.0),
    "百万元": ("亿元", 100.0),
    "百万": ("亿", 100.0),
    "百万美元": ("亿美元", 100.0),
    "百万港元": ("亿港元", 100.0),
}


def human_amount(
    value: Any, unit: str | None, currency: str | None = None
) -> tuple[float, str] | None:
    """原值 → (人读数值, 单位标签)。ratio → (×100, '%')；未知单位返回 None。"""
    if value is None:
        return None
    unit_s = str(unit or "")
    if unit_s == "ratio":
        try:
            return round(float(value) * 100.0, 6), "%"
        except (TypeError, ValueError):
            return None
    rule = _UNIT_SCALES.get(unit_s)
    if not rule:
        return None
    label, div = rule
    try:
        return float(value) / div, label
    except (TypeError, ValueError):
        return None


def fmt_amount(value: Any, unit: str | None = None, currency: str | None = None) -> str:
    """'432.3 亿元' / '9.4%'；无法换算时退回原值（带千分位）。"""
    h = human_amount(value, unit, currency)
    if h is None:
        from stock_kb.note_builder import format_value

        out = format_value(value)
        return f"{out} {unit}" if unit and out else out
    v, label = h
    return format_scaled(v, label)


def fmt_yoy(current: Any, previous: Any) -> str | None:
    """相邻年同比，'+5.4%'；前值为空或 0 时返回 None。"""
    try:
        cur = float(current)
        prev = float(previous)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        return None
    return f"{(cur - prev) / abs(prev) * 100:+.1f}%"


def clean_snippet(text: Any, limit: int = 160) -> str:
    """检索摘录清洗：合并断行与连续空白、去首尾，再截断。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _plain(v: float) -> str:
    a = abs(v)
    dec = 1 if a >= 100 else (2 if a >= 1 else 3)
    s = f"{v:,.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def format_scaled(v: float, unit_label: str) -> str:
    """人读数值 + 单位标签 → 展示串（'432.3 亿元' / '9.4%' / '90 亿元'）。"""
    if unit_label == "%":
        return f"{v:.1f}%"
    return f"{_plain(v)} {unit_label}"


def latest_fact(rows: list[dict[str, Any]], name: str, label: str) -> str | None:
    """取某指标最新年度的带出处事实句（'2025 年营业收入 432.3 亿元《…》'）。"""
    cands = [
        r
        for r in rows
        if r.get("name") == name
        and r.get("year") is not None
        and r.get("value") is not None
        and (r.get("locator") or "")
    ]
    if not cands:
        return None
    r = max(cands, key=lambda r: int(r["year"]))
    h = human_amount(r.get("value"), r.get("unit"), r.get("currency"))
    if not h:
        return None
    return f"{int(r['year'])} 年{label} {format_scaled(*h)}{r['locator']}"


def summary_quality(
    indicators: list[dict[str, Any]], named_stmts: list[dict[str, Any]]
) -> str | None:
    """总结·生意质量：只复述已引用的末年事实（收入/归母/经营现金流）。"""
    parts = [
        p
        for p in (
            latest_fact(indicators, "revenue", "营业收入"),
            latest_fact(indicators, "net_profit", "归母净利润"),
            latest_fact(indicators, "operating_cashflow", "经营现金流"),
            latest_fact(named_stmts, "资本开支", "资本开支"),
        )
        if p
    ]
    return "；".join(parts) if parts else None


def summary_risk(named_stmts: list[dict[str, Any]]) -> str | None:
    """总结·风险：取最新年度的带出处减值行；无则 None。"""
    impair = [
        r
        for r in named_stmts
        if r.get("name") == "减值"
        and r.get("value") is not None
        and (r.get("locator") or "")
    ]
    if not impair:
        return None
    r = max(impair, key=lambda r: int(r["year"] or 0))
    h = human_amount(r.get("value"), r.get("unit"), r.get("currency"))
    if not h:
        return None
    year = f"{int(r['year'])} 年" if r.get("year") is not None else ""
    return f"{year}减值支出 {format_scaled(*h)}{r['locator']}"


def trend_sentence(label: str, rows: list[dict[str, Any]]) -> str | None:
    """由带出处的年度序列生成一句事实性趋势句；数据不足返回 None。

    rows: 含 year/value/unit/currency/locator 的行（指标或三表关键词行）。
    只使用同时具备数值与 locator 的年度点，句中每个数字都能对上出处。
    """
    pts: list[tuple[int, float, str, str]] = []
    for r in rows:
        if r.get("year") is None or r.get("value") is None:
            continue
        loc = r.get("locator") or ""
        if not loc:
            continue
        h = human_amount(r.get("value"), r.get("unit"), r.get("currency"))
        if h is None:
            continue
        v, unit_label = h
        pts.append((int(r["year"]), v, format_scaled(v, unit_label), loc))
    pts.sort(key=lambda p: p[0])
    if len(pts) < 2:
        return None
    first, last = pts[0], pts[-1]

    def cite(p: tuple[int, float, str, str]) -> str:
        # p[3] 已是完整 locator（含《》），直接拼接
        return str(p[3])

    span = last[0] - first[0]
    cagr = ""
    if span >= 3 and first[1] > 0 and last[1] > 0:
        rate = (last[1] / first[1]) ** (1 / span) - 1
        cagr = f"，{span} 年复合增速约 {rate * 100:.1f}%（按表内原值计算）"

    peak = max(pts, key=lambda p: p[1])
    trough = min(pts, key=lambda p: p[1])

    if first[1] < 0 and last[1] < 0:
        # 两端为负（支出类）：按支出规模说扩大/收窄，避免「升至 -41 亿」这类别扭表述。
        verb = "扩大至" if abs(last[1]) > abs(first[1]) else "收窄至"
        return (
            f"{label}由 {first[0]} 年的 {first[2]}{cite(first)}{verb} "
            f"{last[0]} 年的 {last[2]}{cite(last)}"
        )
    if peak[0] not in (first[0], last[0]) and last[1] < peak[1] * 0.98:
        return (
            f"{label}在 {peak[0]} 年达到 {peak[2]}{cite(peak)}，"
            f"{last[0]} 年回落至 {last[2]}{cite(last)}"
        )
    if trough[0] not in (first[0], last[0]) and last[1] > trough[1] * 1.02:
        return (
            f"{label}在 {trough[0]} 年触底 {trough[2]}{cite(trough)}，"
            f"{last[0]} 年回升至 {last[2]}{cite(last)}"
        )
    if last[1] > first[1] * 1.02:
        verb = "升至"
    elif last[1] < first[1] * 0.98:
        verb = "降至"
    else:
        verb = "基本持平于"
    return (
        f"{label}从 {first[0]} 年的 {first[2]}{cite(first)}{verb} "
        f"{last[0]} 年的 {last[2]}{cite(last)}{cagr}"
    )
