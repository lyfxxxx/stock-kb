from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db, search


def run_eval(
    cfg: dict[str, Any],
    top_k: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    top_k = top_k or int(cfg.get("eval", {}).get("top_k", 5))
    q_path = Path(cfg["eval"]["questions"])
    data = yaml.safe_load(q_path.read_text(encoding="utf-8"))
    questions = data["questions"]
    conn = db.connect(cfg["db_path"])

    results: list[dict[str, Any]] = []
    stats_by_type: dict[str, dict[str, float]] = {}

    for q in questions:
        hits = _search_hits(cfg, conn, q, top_k, model)
        stmt_hit = _statement_hit(conn, q)
        hit = stmt_hit or _match_expected(hits, q.get("expected")) or _keyword_hit(conn, q, hits)
        rank = 1 if stmt_hit else (
            _rank_of_first_match(hits, q.get("expected")) or _keyword_rank(conn, q, hits)
        )
        results.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "company": q.get("company"),
                "expected": q.get("expected"),
                "statement_hit": stmt_hit,
                "hit": hit,
                "rank": rank,
                "top_hits": [
                    {"company": h["company"], "title": h["title"], "page": h["page_no"]}
                    for h in hits
                ],
            }
        )

    for q in results:
        s = stats_by_type.setdefault(
            q["type"], {"n": 0, "hit": 0, "rr_sum": 0.0, "top1": 0}
        )
        s["n"] += 1
        if q["hit"]:
            s["hit"] += 1
        if q["rank"] is not None:
            s["rr_sum"] += 1.0 / q["rank"]
            if q["rank"] == 1:
                s["top1"] += 1

    summary = {}
    for typ, s in stats_by_type.items():
        n = s["n"]
        summary[typ] = {
            "n": n,
            "recall_at_k": round(s["hit"] / n, 3) if n else 0.0,
            "hit_at_1": round(s["top1"] / n, 3) if n else 0.0,
            "mrr": round(s["rr_sum"] / n, 3) if n else 0.0,
        }
    conn.close()
    return {"top_k": top_k, "model": model, "summary": summary, "results": results}


def _search_hits(
    cfg: dict[str, Any],
    conn,
    q: dict[str, Any],
    top_k: int,
    model: str | None,
) -> list[dict[str, Any]]:
    keywords = q.get("keywords")
    if not keywords and q.get("type") == "keyword":
        keywords = [q["question"]]
    queries = keywords or [q["question"]]
    merged: dict[int, dict[str, Any]] = {}
    for query in queries:
        if model:
            from stock_kb import vector

            hs = vector.hybrid_search(
                conn,
                query,
                model=model,
                top_k=top_k,
                company=q.get("company"),
                cache_dir=cfg["models_dir"],
                backend=cfg.get("embedding", {}).get("backend", "auto"),
            )
        else:
            hs = search.fts_search(
                conn, query, company=q.get("company"), top_k=top_k
            )
        for h in hs:
            merged[h["page_id"]] = h
    return list(merged.values())[:top_k]


def _match_expected(hits: list[dict[str, Any]], expected: list[dict[str, Any]] | None) -> bool:
    if not expected:
        return False
    for h in hits:
        for exp in expected:
            exp_file = (exp.get("file") or "").rsplit(".", 1)[0]
            if exp_file and exp_file not in h.get("title", ""):
                continue
            if exp.get("page") and h.get("page_no") != exp.get("page"):
                continue
            if exp.get("file") or exp.get("page"):
                return True
    return False


def _rank_of_first_match(
    hits: list[dict[str, Any]], expected: list[dict[str, Any]] | None
) -> int | None:
    if not expected:
        return None
    for i, h in enumerate(hits, start=1):
        for exp in expected:
            exp_file = (exp.get("file") or "").rsplit(".", 1)[0]
            file_ok = (not exp_file) or exp_file in h.get("title", "")
            page_ok = (not exp.get("page")) or h.get("page_no") == exp.get("page")
            if file_ok and page_ok and (exp.get("file") or exp.get("page")):
                return i
    return None


def _keyword_hit(conn, q: dict[str, Any], hits: list[dict[str, Any]]) -> bool:
    if q.get("type") != "keyword":
        return False
    term = q["question"]
    return any(_page_contains(conn, h["page_id"], term) for h in hits)


def _keyword_rank(conn, q: dict[str, Any], hits: list[dict[str, Any]]) -> int | None:
    if q.get("type") != "keyword":
        return None
    term = q["question"]
    for i, h in enumerate(hits, start=1):
        if _page_contains(conn, h["page_id"], term):
            return i
    return None


def _page_contains(conn, page_id: int, term: str) -> bool:
    row = conn.execute("SELECT content FROM pages WHERE id=?", (page_id,)).fetchone()
    return bool(row and term in (row["content"] or ""))


def _statement_hit(conn, q: dict[str, Any]) -> bool:
    stmt = q.get("statement")
    if not stmt:
        return False
    sql = """
        SELECT s.id, s.line_name_norm, r.title
        FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE r.company=? AND s.statement_type=? AND s.year=?
    """
    params: list[Any] = [q.get("company"), stmt["type"], stmt["year"]]
    rows = conn.execute(sql, params).fetchall()
    lines = [str(t).casefold() for t in stmt.get("line_contains", [])]
    for r in rows:
        name = (r["line_name_norm"] or "").casefold()
        name_flat = name.replace(" ", "").replace("—", "").replace("-", "")
        if any(tok.replace(" ", "").replace("—", "").replace("-", "") in name_flat for tok in lines if tok):
            expected = q.get("expected") or []
            if expected and expected[0].get("file"):
                stem = expected[0]["file"].rsplit(".", 1)[0]
                if stem not in r["title"]:
                    continue
            return True
    return False


def save_report(cfg: dict[str, Any], data: dict[str, Any]) -> Path:
    report_dir = Path(cfg["project_root"]) / "eval" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = (data.get("model") or "fts").replace("/", "_")
    json_path = report_dir / f"{tag}_{ts}.json"
    md_path = report_dir / f"{tag}_{ts}.md"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# 检索评测报告", "", f"- 时间：{ts}", f"- top_k：{data['top_k']}", ""]
    if data.get("model"):
        lines.insert(3, f"- 模型：{data['model']}")
    lines.append("| 类型 | 数量 | Recall@k | Hit@1 | MRR |")
    lines.append("|---|---|---|---|---|")
    for typ, s in data["summary"].items():
        lines.append(
            f"| {typ} | {s['n']} | {s['recall_at_k']} | {s['hit_at_1']} | {s['mrr']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path
