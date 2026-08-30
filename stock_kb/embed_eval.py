"""Embedding-model selection eval: vector@5/@50 buckets, paired comparison.

Only questions that actually use vectors (semantic / retrieval-cross, query ≥ 6 chars).
Does not replace freeze regression gates.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db, search, vector
from stock_kb.eval_runner import (
    _normalize_expected,
    _source_matches,
    primary_query,
)
from stock_kb.eval_stats import wilson_ci

VEC_K = 50
TOP_K = 5
MISS_RANK = VEC_K + 1
SUITE_TYPES = {"semantic", "cross"}


def is_embedding_question(q: dict[str, Any]) -> bool:
    if q.get("type") not in SUITE_TYPES:
        return False
    if q.get("statement"):
        return False
    sources = (q.get("expected") or {}).get("sources") or []
    if not sources:
        return False
    query = search.normalize_query(primary_query(q))
    return bool(query) and len(query) >= 6


def load_embedding_questions(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(cfg["eval"]["questions"])
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if is_embedding_question(q)]


def bucket(rank: int | None) -> str:
    if rank is None or rank > VEC_K:
        return "miss"
    if rank <= TOP_K:
        return "top5"
    return "mid"


def _target_sources(norm: dict[str, Any]) -> list[dict[str, Any]]:
    sources = norm.get("sources") or []
    required = [s for s in sources if s.get("required")]
    return required or sources


def _best_rank(hits: list[dict[str, Any]], targets: list[dict[str, Any]]) -> int | None:
    ranks = []
    for i, h in enumerate(hits, start=1):
        if any(_source_matches(h, s) for s in targets):
            ranks.append(i)
    return min(ranks) if ranks else None


def indexed_models(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT model FROM embedding_index ORDER BY model"
    ).fetchall()
    return [r["model"] for r in rows]


def model_is_indexed(conn, model: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM embedding_index WHERE model=? LIMIT 1", (model,)
    ).fetchone()
    return row is not None


def _eval_one_question(
    cfg: dict[str, Any],
    conn,
    q: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    query = primary_query(q)
    company = q.get("company")
    norm = _normalize_expected(q.get("expected"))
    targets = _target_sources(norm)
    backend = cfg.get("embedding", {}).get("backend", "auto")
    cache = cfg["models_dir"]
    vec_hits = vector.vector_search(
        conn,
        model,
        query,
        top_k=VEC_K,
        company=company,
        cache_dir=cache,
        backend=backend,
    )
    hyb_hits = vector.hybrid_search(
        conn,
        query,
        model=model,
        top_k=TOP_K,
        company=company,
        cache_dir=cache,
        backend=backend,
    )
    fused = len(search.normalize_query(query)) >= 6
    vrank = _best_rank(vec_hits, targets)
    hrank = _best_rank(hyb_hits, targets)
    return {
        "id": q["id"],
        "type": q["type"],
        "split": q.get("split") or "freeze",
        "company": company,
        "question": q["question"],
        "query": query,
        "vector_rank": vrank,
        "vector_bucket": bucket(vrank),
        "hybrid_rank": hrank,
        "hybrid_hit": hrank is not None and hrank <= TOP_K,
        "hybrid_fused": fused,
        "n_vec_hits": len(vec_hits),
        "top_hit": {
            "title": vec_hits[0].get("title"),
            "page": vec_hits[0].get("page_no"),
        }
        if vec_hits
        else None,
    }


def _summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    top5 = sum(1 for i in items if i["vector_bucket"] == "top5")
    mid = sum(1 for i in items if i["vector_bucket"] == "mid")
    miss = sum(1 for i in items if i["vector_bucket"] == "miss")
    r50 = top5 + mid
    hyb_n = sum(1 for i in items if i.get("hybrid_fused"))
    hyb_hit = sum(1 for i in items if i.get("hybrid_fused") and i.get("hybrid_hit"))
    ranks = [(i["vector_rank"] or MISS_RANK) for i in items]
    mrr = sum(1.0 / r for r in ranks if r <= VEC_K) / n if n else 0.0
    return {
        "n": n,
        "recall_at_5": round(top5 / n, 3) if n else 0.0,
        "recall_at_5_ci": list(wilson_ci(top5, n)),
        "recall_at_50": round(r50 / n, 3) if n else 0.0,
        "recall_at_50_ci": list(wilson_ci(r50, n)),
        "n_top5": top5,
        "n_mid": mid,
        "n_miss": miss,
        "mrr_at_50": round(mrr, 3),
        "hybrid_fused_n": hyb_n,
        "hybrid_recall_at_5": round(hyb_hit / hyb_n, 3) if hyb_n else 0.0,
        "hybrid_recall_at_5_ci": list(wilson_ci(hyb_hit, hyb_n)) if hyb_n else [0.0, 0.0],
    }


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize_items(items)
    summary["by_split"] = {}
    for split in ("freeze", "diag"):
        sub = [i for i in items if i.get("split") == split]
        if sub:
            summary["by_split"][split] = _summarize_items(sub)
    by_type: dict[str, dict[str, Any]] = {}
    for typ in ("semantic", "cross"):
        sub = [i for i in items if i.get("type") == typ]
        if sub:
            by_type[typ] = _summarize_items(sub)
    summary["by_type"] = by_type
    return summary


def run_embed_suite(cfg: dict[str, Any], model: str) -> dict[str, Any]:
    questions = load_embedding_questions(cfg)
    conn = db.connect(cfg["db_path"])
    try:
        if not model_is_indexed(conn, model):
            raise ValueError(
                f"模型未建索引: {model}。先运行 "
                f"python -m stock_kb index --model {model}"
            )
        started = time.time()
        items = [_eval_one_question(cfg, conn, q, model) for q in questions]
        summary = _summarize(items)
        db_path = Path(cfg["db_path"])
        return {
            "meta": {
                "suite": "embedding",
                "engine": "vector",
                "model": model,
                "vec_k": VEC_K,
                "top_k": TOP_K,
                "n": len(items),
                "duration_seconds": round(time.time() - started, 3),
                "db_mtime": (
                    datetime.fromtimestamp(
                        db_path.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                    if db_path.exists()
                    else None
                ),
            },
            "summary": summary,
            "results": items,
        }
    finally:
        conn.close()


def _ci_overlap(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def pair_compare(
    base_run: dict[str, Any],
    chal_run: dict[str, Any],
) -> dict[str, Any]:
    base_map = {r["id"]: r for r in base_run["results"]}
    chal_map = {r["id"]: r for r in chal_run["results"]}
    ids = sorted(set(base_map) & set(chal_map))
    better_50 = worse_50 = better_5 = worse_5 = 0
    rows = []
    for qid in ids:
        a = base_map[qid]
        b = chal_map[qid]
        ra = a["vector_rank"] or MISS_RANK
        rb = b["vector_rank"] or MISS_RANK
        if rb < ra:
            better_50 += 1
        elif rb > ra:
            worse_50 += 1
        a5 = ra <= TOP_K
        b5 = rb <= TOP_K
        if b5 and not a5:
            better_5 += 1
        elif a5 and not b5:
            worse_5 += 1
        rows.append(
            {
                "id": qid,
                "split": a.get("split"),
                "type": a.get("type"),
                "base_rank": a["vector_rank"],
                "chal_rank": b["vector_rank"],
                "base_bucket": a["vector_bucket"],
                "chal_bucket": b["vector_bucket"],
                "delta": None if a["vector_rank"] is None and b["vector_rank"] is None else (ra - rb),
            }
        )
    bs = base_run["summary"]
    cs = chal_run["summary"]
    r5_ov = _ci_overlap(bs["recall_at_5_ci"], cs["recall_at_5_ci"])
    r50_ov = _ci_overlap(bs["recall_at_50_ci"], cs["recall_at_50_ci"])
    net50 = better_50 - worse_50
    if not r50_ov and cs["recall_at_50"] > bs["recall_at_50"]:
        label = "better"
    elif not r50_ov and cs["recall_at_50"] < bs["recall_at_50"]:
        label = "worse"
    elif not r5_ov and cs["recall_at_5"] > bs["recall_at_5"] and cs["n_miss"] <= bs["n_miss"]:
        label = "better_at_5_only"
    elif not r5_ov and cs["recall_at_5"] < bs["recall_at_5"] and cs["n_miss"] >= bs["n_miss"]:
        label = "worse_at_5_only"
    elif abs(net50) <= 1 and r5_ov and r50_ov:
        label = "indistinguishable"
    elif net50 >= 2 and cs["n_miss"] <= bs["n_miss"] and cs["recall_at_5"] >= bs["recall_at_5"]:
        label = "lean_better"
    elif net50 <= -2 and cs["n_miss"] >= bs["n_miss"] and cs["recall_at_5"] <= bs["recall_at_5"]:
        label = "lean_worse"
    else:
        label = "indistinguishable"
    note = (
        "Wilson 区间重叠或只差 1 题时不当作模型胜出。"
        "better 才建议换模；换之前仍须 "
        "`python -m stock_kb eval --engine hybrid --model <候选> --split freeze` "
        "过 hybrid semantic 门槛，并跑 run_eval_regression.py。"
    )
    if label == "better_at_5_only":
        note = "top-5 升了，但 @50 召回与基线分不开。可能只是已进候选的题往前排，不是捞回了召不回的页。"
    return {
        "base": base_run["meta"]["model"],
        "challenger": chal_run["meta"]["model"],
        "n": len(ids),
        "better_at_50": better_50,
        "worse_at_50": worse_50,
        "net_at_50": net50,
        "gained_top5": better_5,
        "lost_top5": worse_5,
        "recall_at_5_ci_overlap": r5_ov,
        "recall_at_50_ci_overlap": r50_ov,
        "label": label,
        "recommend_switch": label == "better",
        "note": note,
        "questions": rows,
    }


def _md_summary_table(tag: str, s: dict[str, Any]) -> list[str]:
    ci5 = s["recall_at_5_ci"]
    ci50 = s["recall_at_50_ci"]
    return [
        f"### {tag}",
        "",
        "| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| {s['n']} | {s['recall_at_5']} | {ci5[0]}–{ci5[1]} | {s['recall_at_50']} | "
        f"{ci50[0]}–{ci50[1]} | {s['n_top5']} | {s['n_mid']} | {s['n_miss']} | "
        f"{s['mrr_at_50']} | {s['hybrid_recall_at_5']} |",
        "",
    ]


def render_report(
    runs: dict[str, dict[str, Any]],
    compares: list[dict[str, Any]] | None = None,
) -> str:
    lines = ["# Embedding 筛选报告", ""]
    lines.append(
        "套件：semantic + 无三表的 cross；问句归一化后 ≥ 6 字（才会走向量）。"
        "主指标是 **vector@5 / vector@50 分桶**，不是 FTS。"
    )
    lines.append("")
    for model, run in runs.items():
        meta = run["meta"]
        lines.append(f"## {model}")
        lines.append("")
        lines.append(
            f"engine=vector，vec_k={meta.get('vec_k')}，耗时 {meta.get('duration_seconds')}s"
        )
        lines.append("")
        lines.extend(_md_summary_table("合计", run["summary"]))
        for split, ss in (run["summary"].get("by_split") or {}).items():
            lines.extend(_md_summary_table(f"split={split}", ss))
        for typ, ss in (run["summary"].get("by_type") or {}).items():
            lines.extend(_md_summary_table(f"type={typ}", ss))
        lines.append("逐题：")
        lines.append("")
        for item in run["results"]:
            rk = item["vector_rank"] if item["vector_rank"] is not None else "—"
            lines.append(
                f"- `{item['id']}` {item['split']}/{item['type']}  "
                f"vector={item['vector_bucket']}@{rk}  hybrid_hit={item['hybrid_hit']}"
            )
        lines.append("")
    if compares:
        lines.append("## 对比")
        lines.append("")
        for c in compares:
            lines.append(f"### {c['challenger']} vs {c['base']}")
            lines.append("")
            lines.append(
                f"- 判定：**{c['label']}**　建议换模：{'是' if c['recommend_switch'] else '否'}"
            )
            lines.append(
                f"- @50 变好 {c['better_at_50']} / 变差 {c['worse_at_50']} "
                f"（net {c['net_at_50']}）"
            )
            lines.append(
                f"- 新进 top-5 {c['gained_top5']} / 掉出 top-5 {c['lost_top5']}"
            )
            lines.append(
                f"- Recall@5 CI 重叠={c['recall_at_5_ci_overlap']}，"
                f"@50 CI 重叠={c['recall_at_50_ci_overlap']}"
            )
            lines.append(f"- {c['note']}")
            lines.append("")
            flips = [
                r
                for r in c["questions"]
                if r["base_bucket"] != r["chal_bucket"] or (r.get("delta") or 0) != 0
            ]
            if flips:
                lines.append("| id | split | base | challenger | Δrank |")
                lines.append("|---|---|---|---|---|")
                for r in flips:
                    lines.append(
                        f"| {r['id']} | {r['split']} | {r['base_bucket']}@{r['base_rank'] or '—'} | "
                        f"{r['chal_bucket']}@{r['chal_rank'] or '—'} | {r['delta']} |"
                    )
                lines.append("")
    lines.append("## 怎么用这个结论")
    lines.append("")
    lines.append("- `indistinguishable` / `lean_*`：不要换默认模型。")
    lines.append("- `better`：候选在本套件上分得开，仍须过 freeze hybrid 门禁才改 `embedding.model`。")
    lines.append("- keyword / 结构化 / 无答案不靠 embedding，不能用来选模型。")
    lines.append("")
    return "\n".join(lines)


def save_embed_report(
    cfg: dict[str, Any],
    payload: dict[str, Any],
    stem: str,
) -> Path:
    report_dir = Path(cfg["project_root"]) / "eval" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"{stem}_{ts}.json"
    md_path = report_dir / f"{stem}_{ts}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(payload["markdown"], encoding="utf-8")
    return md_path


def run_cli(cfg: dict[str, Any], args: Any) -> int:
    base = args.base or cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    challengers: list[str] = list(args.challenger or [])
    if args.models:
        models = [m.strip() for m in str(args.models).split(",") if m.strip()]
        if not models:
            raise SystemExit(" --models 为空")
        base = models[0]
        challengers = models[1:]
    conn = db.connect(cfg["db_path"])
    available = indexed_models(conn)
    conn.close()
    wanted = [base] + challengers
    missing = [m for m in wanted if m not in available]
    if missing:
        print(
            json.dumps(
                {
                    "error": "模型未建索引",
                    "missing": missing,
                    "indexed": available,
                    "hint": "python -m stock_kb index --model <ID>",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    runs: dict[str, dict[str, Any]] = {}
    for model in wanted:
        print(f"eval-embed: {model} …", flush=True)
        runs[model] = run_embed_suite(cfg, model)
    compares = [
        pair_compare(runs[base], runs[ch]) for ch in challengers if ch in runs
    ]
    markdown = render_report(runs, compares or None)
    payload = {
        "base": base,
        "challengers": challengers,
        "runs": {
            m: {"meta": r["meta"], "summary": r["summary"], "results": r["results"]}
            for m, r in runs.items()
        },
        "compares": compares,
        "markdown": markdown,
    }
    safe_base = base.replace("/", "_")
    stem = "embed_" + safe_base
    if challengers:
        stem = "embed_compare_" + safe_base
    report = save_embed_report(cfg, payload, stem)
    out = {
        "base": base,
        "indexed": available,
        "summaries": {m: r["summary"] for m, r in runs.items()},
        "compares": [
            {k: v for k, v in c.items() if k != "questions"} for c in compares
        ],
        "report": str(report),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"报告：{report}")
    return 0
