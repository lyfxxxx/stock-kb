"""正式稿程序化审计（补齐 HUMAN_RUBRIC 中可自动化的维度）。

审计对象是 skill+LLM 产出的正式稿 Markdown（eval/generated_notes/<公司>/…-正式稿.md），
区别于 audit_notes.py（旧试点笔记）与 generation_eval.py（无 LLM 组稿底稿，G11）。

检查项：
- 结构：正文 [n] 引用与文末「附：注释」表一一对应（无孤儿/缺失）；
- 出处：每条注释含《title》第N页引用且页码在库内存在（支持「第154、155页」合并页码；
  行情等非页面出处单独标记，不判失败）；
- 数字：注释「数值/区间」列中的每个数字能在他引用的页文本中找到（支持组合口径的
  两数之和、以及 亿元→千元 等人读单位换算候选）；
- R9：正文不得残留「第N页」字样（出处只允许出现在文末注释区）；
- R4：同名 HTML 产出至少包含一张 svg 图；
- R5（弱）：正文含行情日期（收盘/汇率日期）或行情注释。

用法：python tools/audit_formal_notes.py <正式稿.md> [更多.md ...]
不传参数时自动审计 eval/generated_notes 下所有 *-正式稿.md。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_kb import db
from stock_kb.config import load_config
from stock_kb.generation_eval import citation_on_page, page_has_number_or_sum

# 注释表行：| n | 指标 | 数值/区间 | 出处 |
_NOTE_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|"
)
_CITE_LIST = re.compile(r"《([^》]+)》\s*第\s*([0-9、,，\s]+?)页")
_NUM_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_YEAR_TOKEN = re.compile(r"^(19|20)\d{2}$")
_QUOTE_DATE = re.compile(r"(收盘|汇率)[^\d]{0,6}(19|20)\d{2}-\d{1,2}-\d{1,2}")
_NOTE_HEADING = re.compile(r"^#{1,3}\s*附[：:]\s*注释")


def _page_candidates(locator: str) -> list[tuple[str, int]]:
    """从出处串解析全部（title, page）。行情等无《》出处返回空表。"""
    out: list[tuple[str, int]] = []
    for m in _CITE_LIST.finditer(locator or ""):
        title = m.group(1).strip()
        for page_s in re.split(r"[、,，\s]+", m.group(2).strip()):
            if page_s.isdigit():
                out.append((title, int(page_s)))
    return out


def _raw_numbers(num_s: str) -> list[float]:
    """数值列里的原始数字（跳过独立年份）。"""
    out: list[float] = []
    for tok in _NUM_TOKEN.findall(num_s or ""):
        t = tok.replace(",", "")
        if _YEAR_TOKEN.match(t):
            continue
        try:
            v = float(t)
        except ValueError:
            continue
        out.append(v)
    return out


def _number_on_pages(num_s: str, v: float, contents: list[str]) -> bool:
    """一个原始数字是否可追溯到页面：原值子串精确匹配；
    亿系人读值再尝试 ×1e2~1e5 换算候选，与页内数字做 2% 容差比对
    （LLM 常把 11,803 百万美元写成 118.0 亿）。"""
    if any(page_has_number_or_sum(c, v) for c in contents):
        return True
    if "亿" not in (num_s or ""):
        return False
    from stock_kb.generation_eval import page_numbers

    for k in (1e2, 1e3, 1e4, 1e5):
        target = v * k
        tol = 0.02 * abs(target)
        for c in contents:
            if any(abs(p - target) <= tol for p in page_numbers(c)):
                return True
    return False


def audit_formal_note(conn, path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    note_start = next(
        (i for i, ln in enumerate(lines) if _NOTE_HEADING.match(ln.strip())), None
    )
    body = "\n".join(lines[:note_start]) if note_start is not None else text

    body_marks = sorted({int(m) for m in re.findall(r"\[(\d+)\]", body)})
    note_ids: list[int] = []
    issues: list[dict] = []
    non_page_sources: list[str] = []
    n_checked = n_number_ok = 0

    for i, ln in enumerate(lines):
        if note_start is None or i <= note_start:
            continue
        m = _NOTE_ROW.match(ln.strip())
        if not m:
            continue
        nid = int(m.group(1))
        note_ids.append(nid)
        values_s, locator_s = m.group(3), m.group(4)
        cites = _page_candidates(locator_s)
        if not cites:
            # 行情/汇率等非页面出处：单独披露，不判失败（skill 允许这类来源）
            non_page_sources.append(f"{nid}: {locator_s.strip()[:40]}")
            continue
        page_cache: dict[tuple[str, int], str] = {}
        missing = []
        for title, page in cites:
            exists, content = citation_on_page(conn, title, page)
            page_cache[(title, page)] = content if exists else ""
            if not exists:
                missing.append(f"《{title}》第{page}页")
        if missing:
            issues.append({"note": nid, "type": "page_missing", "detail": "; ".join(missing)})
            continue
        raws = _raw_numbers(values_s)
        if not raws:
            continue
        n_checked += 1
        contents = list(page_cache.values())
        bad_nums = [v for v in raws if not _number_on_pages(values_s, v, contents)]
        if bad_nums:
            issues.append(
                {"note": nid, "type": "number_not_on_page", "detail": str(bad_nums[:6])}
            )
        else:
            n_number_ok += 1

    orphans = [n for n in body_marks if n not in note_ids]
    missing_notes = [n for n in note_ids if n not in body_marks]
    for n in orphans:
        issues.append({"note": n, "type": "orphan_body_marker", "detail": "正文 [n] 无对应注释"})
    for n in missing_notes:
        issues.append({"note": n, "type": "uncited_note", "detail": "注释未被正文引用"})
    page_residue = re.findall(r"第\d+页", body)
    if page_residue:
        issues.append(
            {"note": None, "type": "page_number_in_body", "detail": page_residue[:5]}
        )

    # R4：同名 HTML 存在且含 ECharts 图表初始化（图是运行时渲染，静态文件无 <svg>）
    html_ok = None
    html_path = path.with_suffix(".html")
    for cand in (html_path, path.parent / (path.stem.replace("-正式稿", "") + ".html")):
        if cand.exists():
            html = cand.read_text(encoding="utf-8", errors="replace").lower()
            html_ok = "echarts" in html and "setoption" in html
            break

    # R5（弱）：行情段带日期
    quote_ok = bool(_QUOTE_DATE.search(body)) or "行情" in body

    failed = bool(issues) or html_ok is False or not quote_ok
    return {
        "path": str(path),
        "n_notes": len(note_ids),
        "n_body_marks": len(body_marks),
        "n_number_rows": n_checked,
        "n_number_rows_ok": n_number_ok,
        "non_page_sources": non_page_sources,
        "html_has_charts": html_ok,
        "quote_dated": quote_ok,
        "issues": issues,
        "ok": not failed,
    }


def main(argv: list[str]) -> int:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    if argv:
        paths = [Path(p) for p in argv]
    else:
        root = Path("eval/generated_notes")
        paths = sorted(root.glob("*/*-正式稿.md"))
    results = [audit_formal_note(conn, p) for p in paths]
    conn.close()
    fail_count = sum(1 for r in results if not r["ok"])
    print(
        json.dumps(
            {"n": len(results), "fail_count": fail_count, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
