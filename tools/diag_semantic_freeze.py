# -*- coding: utf-8 -*-
"""诊断 freeze 语义题失败模式：拆解 FTS / 向量原始 kNN / needle 过滤 / 年份过滤。

对每题回答：
- FTS top-5 是否命中目标；
- 向量原始 kNN（chunk 级，未过滤）里目标页的最佳名次；
- needle 过滤后向量还剩几条、目标页是否被 needle 淘汰；
- 最终 hybrid 结果是否为空、是否命中。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db, search, vector
from stock_kb.config import load_config

MODEL = "BAAI/bge-small-zh-v1.5"
TOP_K = 5


def main() -> None:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    qs = yaml.safe_load(open("eval/questions.yaml", encoding="utf-8"))
    items = qs["questions"] if isinstance(qs, dict) and "questions" in qs else qs
    sem = [
        q
        for q in items
        if q.get("type") == "semantic" and q.get("split", "freeze") == "freeze"
    ]

    # 预取 reports title -> id 集合，供 GT 页匹配
    report_rows = conn.execute(
        "SELECT id, title, company, year FROM reports"
    ).fetchall()
    by_title: list[tuple[int, str, str, int]] = [
        (r["id"], r["title"], r["company"], r["year"]) for r in report_rows
    ]

    def find_gt_pages(q):
        """返回 (page_id, page_no, report_title) 列表。"""
        out = []
        company = q.get("company")
        for s in q.get("expected", {}).get("sources", []):
            frag = s["file"]
            for rid, title, comp, _yr in by_title:
                if frag in title and (company is None or comp == company):
                    row = conn.execute(
                        "SELECT id, page_no FROM pages WHERE report_id=? AND page_no=?",
                        (rid, s["page"]),
                    ).fetchone()
                    if row:
                        out.append((row["id"], s["page"], title))
        return out

    counts = {"fts_hit": 0, "vec_hit": 0, "hybrid_hit": 0, "empty": 0,
              "needle_killed_target": 0, "target_not_in_knn": 0,
              "year_filtered": 0, "gt_missing": 0}
    print(f"n={len(sem)}")
    for q in sem:
        question = q["question"]
        company = q.get("company")
        gt = find_gt_pages(q)
        gt_ids = {p[0] for p in gt}
        if not gt:
            counts["gt_missing"] += 1
            print(f"\n### {q['id']} GT 页未找到（title 片段对不上）")
            continue

        needles = search.claim_needles(question, company)
        norm = search.normalize_query(question)
        years = search.query_years(norm)
        out_of_corpus = search.years_out_of_corpus(conn, norm, company) if years else False

        fts = search.fts_search(conn, question, company=company, top_k=TOP_K)
        fts_hit = any(h["page_id"] in gt_ids for h in fts)

        hyb = vector.hybrid_search(
            conn, question, model=MODEL, top_k=TOP_K, company=company,
            cache_dir=cfg["models_dir"],
        )
        hyb_hit = any(h["page_id"] in gt_ids for h in hyb)

        # 向量原始 kNN：复刻 vector_search 但不过滤，拿 chunk->page 名次
        row = conn.execute(
            "SELECT dim, vec_table FROM embedding_index WHERE model=? LIMIT 1",
            (MODEL,),
        ).fetchone()
        table = row["vec_table"] or f"chunks_vec_{row['dim']}"
        db.load_vector_extension(conn)
        embedder = vector.get_embedder(MODEL, cfg["models_dir"])
        qv = next(embedder.embed([vector._expand_bilingual(norm)]))
        chunk_hits = conn.execute(
            f"SELECT chunk_id, distance FROM {table} "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (vector._serialize_vector(qv), 400),
        ).fetchall()
        rank_of_gt = None
        gt_pages_content_ok = None
        allowed = set(years) if years else None
        kept_after_filter = 0
        for pos, ch in enumerate(chunk_hits, start=1):
            r = conn.execute(
                """
                SELECT p.id AS page_id, r.company AS company, r.year AS year, c.content
                FROM chunks c JOIN pages p ON p.id = c.page_id
                JOIN reports r ON r.id = p.report_id
                WHERE c.id=?
                """,
                (ch["chunk_id"],),
            ).fetchone()
            if not r:
                continue
            if company is not None and r["company"] != company:
                continue
            if allowed is not None and r["year"] not in allowed:
                continue
            kept_after_filter += 1
            if r["page_id"] in gt_ids and rank_of_gt is None:
                rank_of_gt = pos
                gt_pages_content_ok = vector._content_has_needle(
                    r["content"] or "", needles
                )

        counts["fts_hit"] += fts_hit
        counts["hybrid_hit"] += hyb_hit
        if not hyb:
            counts["empty"] += 1
        if rank_of_gt is not None:
            counts["vec_hit"] += 1
            if not gt_pages_content_ok:
                counts["needle_killed_target"] += 1
        else:
            counts["target_not_in_knn"] += 1
        if out_of_corpus:
            counts["year_filtered"] += 1

        needles_str = "/".join(needles) if needles else "(无)"
        print(f"\n### {q['id']} {'HIT' if hyb_hit else 'MISS'}")
        print(f"  Q: {question}")
        print(f"  年份: {years or '-'} 超库: {out_of_corpus}")
        print(f"  needles: {needles_str}")
        print(f"  FTS: {'hit' if fts_hit else f'{len(fts)} 条未中'} | "
              f"hybrid: {'hit' if hyb_hit else ('空' if not hyb else f'{len(hyb)} 条未中')} | "
              f"向量kNN400 目标页名次: {rank_of_gt} needle过: {gt_pages_content_ok}")
        if hyb and not hyb_hit:
            for h in hyb[:3]:
                print(f"    -> {h['title']} p{h['page_no']}")

    print("\n==== 汇总 ====")
    for k, v in counts.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
