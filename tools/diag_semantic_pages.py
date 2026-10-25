# -*- coding: utf-8 -*-
"""P0 诊断尺子：freeze 语义题的四列名次，硬过滤开/关各一份。

列定义（docs/retrieval-fix-plan-20261025.md §3）：
- 全库块序号：期望页最近块在原始 kNN（k=4000，两家公司混排）里的下标；
- 本公司页名次：去掉实体约束后，按公司/年份/当前使用文档过滤、向量距离聚页的排名；
- 含短语页名次：第一张 fact_phrase_hit 为真的页在同一次排序里的名次；
- 含短语页最近块序号：该页最近块的全库下标（P2 用它核对 500 块窗口）。

Part A 复现官方 hybrid 前 5（直接调 hybrid_search，与评测同路径）；
Part B/C 分别输出硬过滤关/开的四列。验收：Part A = 官方 6/20，
且 Part B 中 002 含短语页名次 1、005 为 3、011 约 26。复现失败不开始 P1。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db, search, vector
from stock_kb.config import load_config
from stock_kb.eval_runner import fact_phrase_hit

K = 4000


def load_questions() -> list[dict]:
    qs = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "eval" / "questions.yaml", encoding="utf-8"))
    items = qs.get("questions", qs)
    return [
        q for q in items
        if q.get("type") == "semantic" and (q.get("split") or "freeze") == "freeze"
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    args = ap.parse_args()

    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    sem = load_questions()
    reports = {
        r["id"]: r
        for r in conn.execute("SELECT id, title, company FROM reports").fetchall()
    }

    row = conn.execute(
        "SELECT dim, vec_table FROM embedding_index WHERE model=? LIMIT 1",
        (args.model,),
    ).fetchone()
    if not row:
        print(f"模型 {args.model} 未建索引")
        return 2
    table = row["vec_table"] or f"chunks_vec_{row['dim']}"
    db.load_vector_extension(conn)
    emb = vector.get_embedder(args.model, cfg["models_dir"])

    def gt_pages(q):
        out = set()
        for s in q["expected"].get("sources", []):
            for r in reports.values():
                if s["file"] in r["title"] and r["company"] == q["company"]:
                    p = conn.execute(
                        "SELECT id FROM pages WHERE report_id=? AND page_no=?",
                        (r["id"], s["page"]),
                    ).fetchone()
                    if p:
                        out.add(p["id"])
        return out

    # Part A：官方路径复现
    hits_a = []
    for q in sem:
        phrases = [str(p) for p in q["expected"].get("accept_phrases", [])]
        gts = gt_pages(q)
        hyb = vector.hybrid_search(
            conn, q["question"], model=args.model, top_k=5,
            company=q["company"], cache_dir=cfg["models_dir"],
        )
        page_text = {}
        for h in hyb:
            r = conn.execute(
                "SELECT content, content_orig FROM pages WHERE id=?", (h["page_id"],)
            ).fetchone()
            page_text[h["page_id"]] = (r["content"] or r["content_orig"] or "") if r else ""
        hit = any(h["page_id"] in gts for h in hyb) or any(
            phrases and fact_phrase_hit(page_text.get(h["page_id"], ""), phrases) for h in hyb
        )
        if hit:
            hits_a.append(q["id"])
    print(f"Part A 官方 hybrid 复现：{len(hits_a)}/20 -> {hits_a}")

    # Part B/C：四列，硬过滤开关各一份
    header = (
        f"{'题':<12} {'块序(期望)':>9} {'页名次(期望)':>11} {'页名次(短语)':>11}"
        f" {'块序(短语)':>9}   top5页数"
    )
    for label, use_filter in (("B 硬过滤=关", False), ("C 硬过滤=开", True)):
        print(f"\nPart {label}")
        print(header)
        for q in sem:
            phrases = [str(p) for p in q["expected"].get("accept_phrases", [])]
            gts = gt_pages(q)
            norm = search.normalize_query(q["question"])
            years = search.query_years(norm)
            allowed = set(years) if years else None
            needles = search.claim_needles(q["question"], q["company"]) if use_filter else []
            qv = next(emb.embed([vector._query_embed_text(args.model, norm)]))
            chunk_hits = conn.execute(
                f"SELECT chunk_id, distance FROM {table} "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (vector._serialize_vector(qv), K),
            ).fetchall()
            pages: dict[int, tuple[float, str]] = {}
            chunk_ord_of_page: dict[int, int] = {}
            gt_chunk_ord = None
            for pos, ch in enumerate(chunk_hits, start=1):
                r = conn.execute(
                    f"""
                    SELECT p.id AS pid, p.content AS pc, p.content_orig AS po, c.content AS cc,
                           r.company AS company, r.year AS year
                    FROM chunks c JOIN pages p ON p.id = c.page_id
                    JOIN reports r ON r.id = p.report_id
                    WHERE c.id=? AND {db.live_report_sql("r")}
                      AND COALESCE(p.is_ocr, 0) < 2
                    """,
                    (ch["chunk_id"],),
                ).fetchone()
                if not r or r["company"] != q["company"]:
                    continue
                if allowed is not None and r["year"] not in allowed:
                    continue
                if use_filter and not vector._content_has_needle(r["cc"] or "", needles):
                    continue
                pid = r["pid"]
                text = r["pc"] or r["po"] or ""
                cur = pages.get(pid)
                if cur is None or ch["distance"] < cur[0]:
                    pages[pid] = (ch["distance"], text)
                    chunk_ord_of_page[pid] = pos
                if pid in gts and gt_chunk_ord is None:
                    gt_chunk_ord = pos
            order = sorted(pages.items(), key=lambda kv: kv[1][0])
            gt_rank = next((i for i, (pid, _) in enumerate(order, 1) if pid in gts), None)
            ph = next(
                (
                    (i, pid)
                    for i, (pid, v) in enumerate(order, 1)
                    if phrases and fact_phrase_hit(v[1], phrases)
                ),
                None,
            )
            ph_rank, ph_chunk = (ph[0], chunk_ord_of_page.get(ph[1])) if ph else (None, None)
            print(
                f"{q['id']:<12} {str(gt_chunk_ord):>9} {str(gt_rank):>11}"
                f" {str(ph_rank):>11} {str(ph_chunk):>9}   {len(order)}"
            )

    ok = len(hits_a) == 6
    print(
        f"\n验收：Part A {'6/20 ✓' if ok else '异常'}；"
        "另核对 Part B 中 002 短语页=1、005=3、011≈26"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
