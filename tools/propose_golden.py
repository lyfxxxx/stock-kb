"""从 NAS PDF（优先）或 pages.content_orig 抽出结构化题的独立 golden 候选。

用法:
    python tools/propose_golden.py --ids exact-004,exact-005
    python tools/propose_golden.py --ids exact-004 --no-pdf
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_kb.config import load_config

_NUM = re.compile(r"\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+\.\d+\)?|\(?-?\d+\)?")


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def _parse_number(token: str) -> float | None:
    raw = token.strip()
    if not raw:
        return None
    neg = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    raw = raw.replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return -abs(value) if neg else value


def _page_text(conn: sqlite3.Connection, company: str, file_frag: str, page: int) -> tuple[str, str, str]:
    row = conn.execute(
        """
        SELECT r.title, r.path, p.content_orig, p.content
        FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE r.company=? AND instr(r.title, ?)>0 AND p.page_no=?
        LIMIT 1
        """,
        (company, file_frag, page),
    ).fetchone()
    if not row:
        raise SystemExit(f"找不到页面: {company} {file_frag} p{page}")
    return row["title"], row["path"], (row["content_orig"] or row["content"] or "")


def _pdf_text(path: str, page: int) -> str | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    pdf_path = Path(path)
    if not pdf_path.exists():
        return None
    with pdfplumber.open(path) as pdf:
        if page < 1 or page > len(pdf.pages):
            return None
        return pdf.pages[page - 1].extract_text() or ""


def _matching_lines(text: str, tokens: list[str]) -> list[str]:
    norms = [_norm(t) for t in tokens if _norm(t)]
    out: list[str] = []
    for line in text.splitlines():
        nln = _norm(line)
        if any(tok and tok in nln for tok in norms):
            out.append(line.strip())
    return out


def propose_one(conn: sqlite3.Connection, q: dict[str, Any], use_pdf: bool) -> dict[str, Any]:
    stmt = q["statement"]
    source = (q.get("expected") or {}).get("sources") or [{}]
    src = source[0]
    file_frag = src.get("file") or ""
    page = src.get("page")
    title, path, db_text = _page_text(conn, q.get("company") or "", file_frag, page)
    pdf_text = _pdf_text(path, page) if use_pdf else None
    text = pdf_text if pdf_text else db_text
    origin = "pdf" if pdf_text else "content_orig"
    tokens = list(stmt.get("line_contains") or [])
    lines = _matching_lines(text, tokens)
    numbers: list[float] = []
    for line in lines:
        for tok in _NUM.findall(line):
            parsed = _parse_number(tok)
            if parsed is not None:
                numbers.append(parsed)
    expected = stmt.get("expected_value")
    match_expected = any(
        expected is not None and abs(n - float(expected)) <= abs(float(expected)) * 0.02 + 1e-6
        for n in numbers
    )
    return {
        "id": q["id"],
        "question": q["question"],
        "company": q.get("company"),
        "statement_type": stmt.get("type"),
        "year": stmt.get("year"),
        "period_type": stmt.get("period_type"),
        "yaml_expected_value": expected,
        "yaml_unit": stmt.get("expected_unit"),
        "yaml_currency": stmt.get("expected_currency"),
        "file": file_frag,
        "page": page,
        "title": title,
        "path": path,
        "text_origin": origin,
        "matching_lines": lines[:12],
        "parsed_numbers": numbers[:20],
        "yaml_value_on_page": match_expected,
        "proposal": {
            "expected_value": expected if match_expected else (numbers[0] if numbers else None),
            "expected_unit": stmt.get("expected_unit"),
            "expected_currency": stmt.get("expected_currency"),
            "page": page,
            "golden_source": "pdf" if origin == "pdf" else "content_orig",
            "evidence_snippet": (lines[0][:180] if lines else ""),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True, help="逗号分隔的题目 id")
    parser.add_argument("--no-pdf", action="store_true", help="不读 NAS PDF，只用 content_orig")
    parser.add_argument(
        "--out",
        default=None,
        help="写出 JSON 路径，默认 eval/golden_proposals/proposals.json",
    )
    args = parser.parse_args()
    cfg = load_config()
    q_path = Path(cfg["eval"]["questions"])
    questions = {q["id"]: q for q in __import__("yaml").safe_load(q_path.read_text(encoding="utf-8"))["questions"]}
    conn = sqlite3.connect(f"file:{Path(cfg['db_path']).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    proposals = []
    for qid in ids:
        q = questions.get(qid)
        if not q or not q.get("statement"):
            raise SystemExit(f"不是结构化题或不存在: {qid}")
        item = propose_one(conn, q, use_pdf=not args.no_pdf)
        proposals.append(item)
        print("=" * 72)
        print(f"{item['id']}  {item['question']}")
        print(f"  来源: {item['title']} p{item['page']} ({item['text_origin']})")
        print(f"  yaml: {item['yaml_expected_value']} {item['yaml_unit']} {item['yaml_currency']}")
        print(f"  页上找到 yaml 值: {item['yaml_value_on_page']}")
        for line in item["matching_lines"][:6]:
            print(f"  | {line}")
    conn.close()
    out = Path(args.out) if args.out else Path(cfg["project_root"]) / "eval" / "golden_proposals" / "proposals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
