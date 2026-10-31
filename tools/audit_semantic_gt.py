# -*- coding: utf-8 -*-
"""审计 freeze 语义题的 GT 质量：
1. GT 页是否存在、文档年份与问句年份是否一致（年份硬过滤下不可达即标注缺陷）；
2. accept_phrases 是否出现在 GT 页上（标注自洽性）；
3. 答案事实在该公司语料的分散度（含该短语的页数——衡量 GT 页清单的完备性压力）；
4. GT 页命中短语处的摘录（人工核对问答回应性）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db, search
from stock_kb.config import load_config
from stock_kb.eval_runner import fold_fact_text


def norm_text(s: str) -> str:
    """与评测判定用同一套归一化（去掉空白、千分位、全角空格、╱）。

    历史上这里自己写了 `re.sub(r"[\\s,，]", "", s)`，与 `fold_fact_text`
    差在全角空格和 ╱ 上——短语含这两类字符时，工具会报「短语不在 GT 页」而
    评测认为命中。两套归一化必须只有一套。
    """
    return fold_fact_text(s)


def main() -> None:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    qs = yaml.safe_load(open("eval/questions.yaml", encoding="utf-8"))
    items = qs.get("questions", qs)
    sem = [
        q for q in items
        if q.get("type") == "semantic" and q.get("split", "freeze") == "freeze"
    ]

    reports = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, title, company, year, report_type, language FROM reports"
        ).fetchall()
    }
    title_index = list(reports.values())

    # 预载两家公司页面的归一化文本（page_id -> (report_id, page_no, body)）
    page_bodies: dict[int, tuple[int, int, str]] = {}
    for row in conn.execute(
        """
        SELECT p.id AS pid, p.report_id AS rid, p.page_no AS pg,
               p.content AS c, p.content_orig AS co
        FROM pages p JOIN reports r ON r.id=p.report_id
        WHERE r.company IN ('海底捞', '百胜中国')
        """
    ).fetchall():
        page_bodies[row["pid"]] = (
            row["rid"], row["pg"],
            norm_text(row["c"]) + norm_text(row["co"]),
        )

    problems = []
    for q in sem:
        qid = q["id"]
        question = q["question"]
        company = q.get("company")
        raw_phrases = (q.get("expected", {}) or {}).get("accept_phrases", [])
        phrases = [norm_text(p) for p in raw_phrases]
        qyears = search.query_years(search.normalize_query(question))
        print(f"\n### {qid}  {question}")
        print(f"  问句年份: {qyears or '-'} | accept: {raw_phrases}")

        listed_pages: set[tuple[int, int]] = set()
        for s in q["expected"].get("sources", []):
            frag = s["file"]
            matched = [
                r for r in title_index
                if frag in r["title"] and r["company"] == company
            ]
            if not matched:
                problems.append(f"{qid}: GT 文档未找到 {frag}")
                print(f"  [GT缺文档] {frag} p{s['page']}")
                continue
            for r in matched:
                page = conn.execute(
                    "SELECT id FROM pages WHERE report_id=? AND page_no=?",
                    (r["id"], s["page"]),
                ).fetchone()
                if not page:
                    problems.append(f"{qid}: GT 页不存在 {r['title']} p{s['page']}")
                    print(f"  [GT缺页] {r['title']} p{s['page']}")
                    continue
                listed_pages.add((r["id"], s["page"]))
                year_ok = (not qyears) or (r["year"] in qyears)
                if not year_ok:
                    problems.append(
                        f"{qid}: GT 文档年份 {r['year']} 与问句 {qyears} 不符 → 年份过滤下不可达"
                    )
                body = page_bodies[page["id"]][2]
                hit_ph = [p for p in phrases if p in body]
                flag = "OK" if (not phrases or hit_ph) else "短语不在该页"
                if phrases and not hit_ph:
                    problems.append(f"{qid}: accept 短语不在任一 GT 页（{frag} p{s['page']}）")
                print(
                    f"  - {r['title'][:38]} p{s['page']} year={r['year']} "
                    f"type={r['report_type']} "
                    f"{'年份不符!' if not year_ok else ''} 短语命中 {len(hit_ph)}/{len(phrases)} {flag}"
                )
                if hit_ph:
                    p = hit_ph[0]
                    idx = body.find(p)
                    lo, hi = max(0, idx - 60), min(len(body), idx + len(p) + 60)
                    print(f"      …{body[lo:hi]}…")

        if phrases:
            p0 = phrases[0]
            dispersed = {
                pid for pid, (_rid, _pg, body) in page_bodies.items()
                if p0 in body
            }
            print(
                f"  分散度: 含首条短语「{raw_phrases[0]}」的页 {len(dispersed)} 页 "
                f"(该公司语料 {sum(1 for pid in page_bodies if reports[page_bodies[pid][0]]['company']==company)} 页), "
                f"GT 列出 {len(listed_pages)} 页"
            )

    print("\n==== 标注问题清单 ====")
    for p in problems:
        print(" -", p)
    if not problems:
        print("（无硬性标注错误）")


if __name__ == "__main__":
    main()
