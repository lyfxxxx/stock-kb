"""生成人工复核工作底稿 eval/human_review_worksheet.md。

只读访问 DB，不修改任何数据。内容分三部分：
1. 结构化 golden 复核：26 道带 statement 的题，需从 PDF 独立核对；
2. 检索 ground truth 复核：46 道进入检索评分的题，需确认期望页确实相关；
3. 负样本复核：26 道带负样本的检索题，需确认负样本确实应判负。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_kb import eval_runner
from stock_kb.config import load_config


def _md_escape(value: str) -> str:
    return (value or "").replace("|", chr(92) + "|")


def _readonly_conn(cfg: dict[str, Any]) -> sqlite3.Connection:
    db_path = Path(cfg["db_path"])
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _page_meta(conn: sqlite3.Connection, company: str, file: str, page: int | None) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT r.title, r.path, p.page_no, p.content
        FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE r.company=?
        """,
        (company,),
    ).fetchall()
    candidates = [r for r in rows if file and file in (r["title"] or "")]
    if page is not None:
        candidates = [r for r in candidates if r["page_no"] == page]
    if not candidates:
        return None
    r = candidates[0]
    content = (r["content"] or "").strip().replace("\n", " ")
    return {
        "title": r["title"],
        "path": r["path"],
        "page": r["page_no"],
        "excerpt": (content[:140] + "…") if len(content) > 140 else content,
    }


def main() -> int:
    cfg = load_config()
    q_path = Path(cfg["eval"]["questions"])
    questions = yaml.safe_load(q_path.read_text(encoding="utf-8"))["questions"]
    out_path = q_path.parent / "human_review_worksheet.md"
    conn = _readonly_conn(cfg)

    lines: list[str] = []
    lines.append("# 评测方案人工复核工作底稿")
    lines.append("")
    lines.append("> 本文件由 `tools/make_human_review_worksheet.py` 生成，可重复运行。")
    lines.append("> 复核时只填本底稿，不要直接改 DB；确认后再回写 `eval/questions.yaml`。")
    lines.append("")

    # ---------- 结构化 golden ----------
    lines.append("## 一、结构化 golden 复核（26 题）")
    lines.append("")
    lines.append("目标：从 PDF 原文独立读取数值、单位、币种、页码，与 DB 候选对比。")
    lines.append("当前 DB 候选只是「自洽结果」，不能证明解析正确。")
    lines.append("")
    lines.append("判定请填写：`一致` / `不一致（写实际值）`。")
    lines.append("")

    structured = [q for q in questions if q.get("statement")]
    for q in structured:
        norm = eval_runner._normalize_expected(q.get("expected"))
        st = eval_runner._statement_match(conn, q, norm)
        stmt = q["statement"]
        lines.append(f"### {q['id']} {q['question']}")
        lines.append("")
        lines.append(
            f"- 查询条件：{q.get('company')} / {stmt.get('type')} / "
            f"{stmt.get('year')} / period_type={stmt.get('period_type')}"
        )
        lines.append(
            f"- 期望来源："
            + "；".join(
                f"{s.get('file')} 第{s.get('page')}页 {s.get('table') or ''}".strip()
                for s in q.get("expected", {}).get("sources", [])
            )
        )
        if st:
            lines.append(f"- DB 候选命中：{st.get('matched_count')} 条；行级 hit={st.get('hit')}")
            for r in st.get("matched_rows", []):
                mark = "√" if r.get("row_pass") else "×"
                lines.append(
                    f"  - [{mark}] {r.get('line_name_norm') or ''} = {r.get('value')} "
                    f"| p{r.get('page_no')} | {r.get('title')}"
                )
        for s in q.get("expected", {}).get("sources", []):
            meta = _page_meta(conn, q.get("company"), s.get("file"), s.get("page"))
            if meta:
                lines.append(f"  - 打开文件：`{meta['path']}`（第 {meta['page']} 页）")
                lines.append(f"  - 该页开头：{meta['excerpt']}")
                break
        lines.append("")
        lines.append("  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____")
        lines.append("  - [ ] 判定：____；复核人/日期：____")
        lines.append("")

    # ---------- 检索 ground truth ----------
    lines.append("## 二、检索 ground truth 复核（46 题）")
    lines.append("")
    lines.append("范围：keyword 20 + semantic 20 + cross 纯检索 6。")
    lines.append("目标：确认每个期望来源页确实能回答该问题；不能只因为包含关键词就判为相关。")
    lines.append("")
    lines.append("| ID | 问题 | 期望来源 | 该页开头 | 判定 |")
    lines.append("|---|---|---|---|---|")
    retrieval_scored = [
        q
        for q in questions
        if q["type"] in {"keyword", "semantic", "cross"}
        and not q.get("statement")
        and q.get("expected", {}).get("sources")
    ]
    for q in retrieval_scored:
        for s in q.get("expected", {}).get("sources", []):
            meta = _page_meta(conn, q.get("company"), s.get("file"), s.get("page"))
            loc = f"{s.get('file')} p{s.get('page')}"
            excerpt = _md_escape((meta or {}).get("excerpt", "未找到"))
            question = _md_escape(q.get("question") or "")
            lines.append(f"| {q['id']} | {question} | {loc} | {excerpt} | ☐ 相关 / ☐ 需改 |")
    lines.append("")

    # ---------- 负样本 ----------
    lines.append("## 三、负样本复核（26 道检索题）")
    lines.append("")
    lines.append("目标：确认负样本确实是「容易混淆但不应命中」的页，而不是错误标注。")
    lines.append("如果发现负样本其实也能回答问题，应记录为「改为正样本」或「删除负样本」。")
    lines.append("")
    lines.append("| ID | 负样本 | 该页开头 | 判定 |")
    lines.append("|---|---|---|---|")
    neg_questions = [
        q
        for q in questions
        if q["type"] in {"keyword", "semantic", "cross"}
        and not q.get("statement")
        and q.get("expected", {}).get("negatives")
    ]
    for q in neg_questions:
        for s in q.get("expected", {}).get("negatives", []):
            meta = _page_meta(conn, q.get("company"), s.get("file"), s.get("page"))
            loc = f"{s.get('file')} p{s.get('page')}"
            excerpt = _md_escape((meta or {}).get("excerpt", "未找到"))
            lines.append(f"| {q['id']} | {loc} | {excerpt} | ☐ 确为负 / ☐ 需改 |")
    lines.append("")

    lines.append("## 四、端到端人工判定")
    lines.append("")
    lines.append("见 `eval/manual_review.md`，已按 end2end-001 至 008 对齐。")
    lines.append("")
    lines.append("## 五、两篇试点笔记人工审核")
    lines.append("")
    lines.append("见 `eval/manual_review.md` 第二节，对海底捞与百胜中国笔记按 6 项打 1–5 分。")
    lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    out_path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    print(f"已生成：{out_path}")
    print(f"结构化题：{len(structured)}；检索题：{len(retrieval_scored)}；含负样本题：{len(neg_questions)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
