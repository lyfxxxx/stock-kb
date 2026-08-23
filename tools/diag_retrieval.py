"""对照 diag 真语义/跨语言/无答案：FTS、vector@50、hybrid@5。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_kb import db, search, vector
from stock_kb.config import load_config
from stock_kb.eval_runner import _file_matches, primary_query

VEC_K = 50
TOP_K = 5


def _gt_snippet(conn, company: str | None, file_frag: str, page: int | None) -> dict:
    sql = (
        "SELECT r.title, p.page_no, substr(p.content, 1, 280) AS snippet "
        "FROM pages p JOIN reports r ON r.id = p.report_id "
        "WHERE instr(r.title, ?) > 0 AND COALESCE(r.is_duplicate, 0) = 0"
    )
    params: list = [file_frag]
    if company:
        sql += " AND r.company = ?"
        params.append(company)
    if page is not None:
        sql += " AND p.page_no = ?"
        params.append(page)
    sql += " LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    if not row:
        return {"found": False}
    return {
        "found": True,
        "title": row["title"],
        "page_no": row["page_no"],
        "snippet": row["snippet"],
    }


def _rank_of(hits: list[dict], file_frag: str, page: int | None) -> int | None:
    for i, h in enumerate(hits, start=1):
        if not _file_matches(h.get("title") or "", file_frag):
            continue
        if page is None or h.get("page_no") == page:
            return i
    return None


def _rank_any(hits: list[dict], sources: list[dict]) -> int | None:
    ranks = [_rank_of(hits, s.get("file") or "", s.get("page")) for s in sources]
    ranks = [r for r in ranks if r is not None]
    return min(ranks) if ranks else None


def _filing_sources(sources: list[dict]) -> list[dict]:
    return [
        s
        for s in sources
        if str(s.get("authority") or "").lower() in {"annual", "interim"}
    ]


def _hit_brief(h: dict) -> dict:
    return {
        "title": h.get("title"),
        "page_no": h.get("page_no"),
        "score": h.get("score") or h.get("rank") or h.get("fusion_score"),
        "snippet": (h.get("snippet") or "")[:160],
    }


def main() -> int:
    cfg = load_config()
    q_path = Path(cfg["eval"]["questions"])
    questions = yaml.safe_load(q_path.read_text(encoding="utf-8"))["questions"]
    wanted = [
        q
        for q in questions
        if (q.get("split") or "freeze") == "diag"
        and q["type"] in {"semantic", "cross", "no_answer"}
    ]
    conn = db.connect(cfg["db_path"])
    model = cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    cache = cfg.get("models_dir")
    backend = cfg.get("embedding", {}).get("backend", "auto")

    out = []
    for q in wanted:
        query = primary_query(q)
        company = q.get("company")
        srcs = ((q.get("expected") or {}).get("sources") or [])
        gt = srcs[0] if srcs else None
        item = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "query": query,
            "company": company,
            "gt": gt,
            "sources": srcs,
        }
        if gt:
            item["gt_page"] = _gt_snippet(conn, company, gt.get("file") or "", gt.get("page"))
        fts = search.fts_search(conn, query, company=company, top_k=TOP_K)
        vec = vector.vector_search(
            conn,
            model,
            query,
            top_k=VEC_K,
            company=company,
            cache_dir=cache,
            backend=backend,
        )
        hyb = vector.hybrid_search(
            conn,
            query,
            model=model,
            top_k=TOP_K,
            company=company,
            cache_dir=cache,
            backend=backend,
        )
        item["fts_n"] = len(fts)
        item["hybrid_n"] = len(hyb)
        item["fts_top"] = [_hit_brief(h) for h in fts]
        item["hybrid_top"] = [_hit_brief(h) for h in hyb]
        item["vector_top5"] = [_hit_brief(h) for h in vec[:TOP_K]]
        if srcs:
            item["fts_rank"] = _rank_any(fts, srcs)
            item["vector_rank"] = _rank_any(vec, srcs)
            item["hybrid_rank"] = _rank_any(hyb, srcs)
            filings = _filing_sources(srcs)
            item["annual_eligible"] = bool(filings)
            item["fts_annual_rank"] = _rank_any(fts, filings) if filings else None
            item["vector_annual_rank"] = _rank_any(vec, filings) if filings else None
            item["hybrid_annual_rank"] = _rank_any(hyb, filings) if filings else None
            file_frag = (gt or {}).get("file") or ""
            vec_file_ranks = [
                i
                for i, h in enumerate(vec, start=1)
                if _file_matches(h.get("title") or "", file_frag)
            ]
            item["vector_same_file_ranks"] = vec_file_ranks[:8]
        if q["type"] == "semantic" or q["type"] == "cross":
            vr = item.get("vector_rank")
            hr = item.get("hybrid_rank")
            fr = item.get("fts_rank")
            if vr is not None and vr <= 5 or hr is not None and hr <= 5 or fr is not None and fr <= 5:
                item["bucket"] = "top5"
            elif vr is not None and vr <= VEC_K:
                item["bucket"] = "ranked_out"
            else:
                item["bucket"] = "not_recalled"
        else:
            item["bucket"] = "hybrid_fill" if hyb else "empty"
        out.append(item)
        print(
            f"{q['id']:14} {item['bucket']:12} "
            f"fts={item.get('fts_rank')} vec={item.get('vector_rank')} "
            f"hyb={item.get('hybrid_rank')} "
            f"ann_vec={item.get('vector_annual_rank')} "
            f"fts_n={len(fts)} hyb_n={len(hyb)}",
            flush=True,
        )

    dest = Path(cfg["eval"]["questions"]).parent / "reports" / "diag_retrieval.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
