"""终稿审计：注释能对上页或三表，且本次 run_id 的日志覆盖出处。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db

# 与 generation_eval._CITE 相同。
_CITE = re.compile(r"《([^》]+)》\s*第\s*(\d+)\s*页")
_H2 = re.compile(r"(?m)^##\s+(.+?)\s*$")
_H2_HTML = re.compile(r"(?is)<h2[^>]*>(.*?)</h2>")
_NUM = re.compile(r"\d[\d,，]*(?:\.\d+)?")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_RUN_ID = re.compile(r"(?m)^\s*run_id:\s*(\S+)\s*$")
_REQUIRED_SECTIONS = ("利润表", "资产负债", "现金流", "分红", "总结")
_CHART_SECTIONS = ("利润表", "资产负债", "现金流")


def default_checklist_path() -> Path:
    return Path(__file__).resolve().parent.parent / "eval" / "fact_checklist.yaml"


def load_fact_checklist(path: str | Path | None = None) -> list[dict[str, Any]]:
    file = Path(path) if path else default_checklist_path()
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return list(data.get("items") or [])


def audit_report(
    conn,
    markdown: str,
    log_lines: list[dict[str, Any]],
    company: str,
    checklist: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = markdown or ""
    issues: list[str] = []
    run_match = _RUN_ID.search(text)
    run_id = run_match.group(1) if run_match else None
    if not run_id:
        issues.append("缺少 run_id")

    opening, sections = _split_sections(text)
    for bad in ("判断：", "低估", "高估"):
        if bad in opening:
            issues.append(f"开篇出现{bad}")
    found = {name: _section_text(sections, name) for name in _REQUIRED_SECTIONS}
    for name, body in found.items():
        if body is None:
            issues.append(f"缺少节：{name}")

    for index, line in enumerate(text.splitlines(), start=1):
        if "判断" in line and not re.match(r"^\s*判断：", line):
            issues.append(f"第{index}行出现「判断」但不是以「判断：」开头")
        if ("同比" in line or "累计" in line) and not any(op in line for op in ("=", "÷", "/")):
            issues.append(f"第{index}行有同比或累计但没有算式")

    cites = _citations(text)
    cited_numbers = { _plain(num) for _title, _page, num in cites }
    for title, page, number in cites:
        if not _number_on_page(conn, company, title, page, number):
            issues.append(f"注释数字不在页面或三表：《{title}》第{page}页 {number}")

    if run_id:
        hits = _hits_for_run(log_lines, run_id)
        for title, page, _number in cites:
            if not _hit_covers(hits, title, page):
                issues.append(f"出处不在本次日志：《{title}》第{page}页")

    items = checklist if checklist is not None else load_fact_checklist()
    for item in items:
        section_name = item.get("section") or ""
        body = _section_text(sections, section_name)
        has_data = _item_has_data(conn, company, item)
        label = item.get("id") or section_name
        if body is None:
            continue
        if has_data:
            # 同一节可以另有科目写「暂无数据」。库里有数时，不能整节只有这句、又没有任何注释。
            if not cites:
                if "暂无数据" in body:
                    issues.append(f"{label} 库里有数却在{section_name}写暂无数据")
                issues.append(f"{label} 库里有数但漏写注释")
        elif "暂无数据" not in body:
            issues.append(f"{label} 库里没有且{section_name}未写暂无数据")

    for name in _CHART_SECTIONS:
        body = found.get(name)
        if not body:
            continue
        years = set(_YEAR.findall(body))
        if len(years) < 2:
            continue
        if "图" not in body:
            issues.append(f"{name}有多个年份但没有图")
            continue
        for number in _chart_numbers(body):
            if _plain(number) not in cited_numbers:
                issues.append(f"{name}图附近的数字未引用：{number}")

    return {"ok": not issues, "issues": issues, "run_id": run_id}


def audit_report_main(cfg: dict[str, Any], path: str, company: str) -> int:
    from stock_kb.retrieval_log import log_path, read_log

    conn = db.connect(cfg["db_path"])
    try:
        text = Path(path).read_text(encoding="utf-8")
        result = audit_report(conn, text, read_log(log_path(cfg)), company)
    finally:
        conn.close()
    if result["ok"]:
        print("audit-report: ok")
        return 0
    for issue in result["issues"]:
        print(f"audit-report: {issue}")
    return 1


def _split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    marks = [(m.start(), m.end(), _tag_text(m.group(1))) for m in _H2.finditer(text)]
    if not marks:
        marks = [
            (m.start(), m.end(), _tag_text(m.group(1))) for m in _H2_HTML.finditer(text)
        ]
    if not marks:
        return text, []
    opening = text[: marks[0][0]]
    sections: list[tuple[str, str]] = []
    for index, (start, end, title) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        sections.append((title, text[end:stop]))
    return opening, sections


def _tag_text(raw: str) -> str:
    return re.sub(r"<[^>]+>", "", raw).strip()


def _section_text(sections: list[tuple[str, str]], name: str) -> str | None:
    for title, body in sections:
        if name in title:
            return body
    return None


def _citations(text: str) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for line in text.splitlines():
        matches = list(_CITE.finditer(line))
        if not matches:
            continue
        # 每个注释只核对它前面那一段里的数字，避免一行里多个出处交叉配对。
        for index, match in enumerate(matches):
            start = matches[index - 1].end() if index else 0
            segment = re.sub(r"\[\d+\]", " ", line[start:match.start()])
            numbers = _NUM.findall(segment) or [""]
            for number in numbers:
                found.append((match.group(1), int(match.group(2)), number))
    return found


def _plain(number: str) -> str:
    return str(number).replace(",", "").replace("，", "")


def _number_on_page(conn, company: str, title: str, page: int, number: str) -> bool:
    if not number:
        return False
    plain = _plain(number)
    rows = conn.execute(
        f"""
        SELECT p.content, p.content_orig
        FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE {db.live_report_sql('r')} AND r.company=? AND p.page_no=?
          AND (instr(r.title, ?) > 0 OR instr(?, r.title) > 0)
        """,
        (company, page, title, title),
    ).fetchall()
    for row in rows:
        for field in ("content", "content_orig"):
            text = row[field] or ""
            if number in text or plain in text.replace(",", "").replace("，", ""):
                return True
    values = conn.execute(
        f"""
        SELECT s.value FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE {db.live_report_sql('r')} AND r.company=? AND s.page_no=?
          AND (instr(r.title, ?) > 0 OR instr(?, r.title) > 0)
        """,
        (company, page, title, title),
    ).fetchall()
    for row in values:
        if row["value"] is None:
            continue
        if plain in _value_forms(row["value"]):
            return True
    return False


def _value_forms(value: Any) -> set[str]:
    number = float(value)
    forms = {str(number), _plain(str(number))}
    if number.is_integer():
        forms.add(str(int(number)))
    return forms


def _hits_for_run(log_lines: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in log_lines:
        if str(row.get("run_id") or "") != run_id:
            continue
        for hit in row.get("hits") or []:
            hits.append(hit)
    return hits


def _hit_covers(hits: list[dict[str, Any]], title: str, page: int) -> bool:
    for hit in hits:
        try:
            hit_page = int(hit.get("page"))
        except (TypeError, ValueError):
            continue
        hit_title = str(hit.get("title") or "")
        if hit_page == int(page) and (title in hit_title or hit_title in title):
            return True
    return False


def _item_has_data(conn, company: str, item: dict[str, Any]) -> bool:
    indicator = item.get("indicator")
    if indicator:
        row = conn.execute(
            f"""
            SELECT 1 FROM indicators i
            JOIN reports r ON r.id = i.report_id
            WHERE i.company=? AND i.name=? AND i.value IS NOT NULL
              AND {db.live_report_sql('r')}
            LIMIT 1
            """,
            (company, indicator),
        ).fetchone()
        if row:
            return True
    for keyword in item.get("statement_keywords") or []:
        if db.query_statements(conn, company, keyword=str(keyword), limit=1):
            return True
    return False


def _chart_numbers(section: str) -> list[str]:
    lines = section.splitlines()
    numbers: list[str] = []
    for index, line in enumerate(lines):
        if "图" not in line:
            continue
        blob = line
        if index + 1 < len(lines):
            blob += "\n" + lines[index + 1]
        numbers.extend(_NUM.findall(blob))
    return numbers
