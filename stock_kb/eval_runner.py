from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db, search


RETRIEVAL_TYPES = {"exact", "keyword", "semantic", "cross"}
SEARCH_ENGINES = {"fts", "vector", "hybrid"}
_DASHES = (" ", "\t", "\n", "\r", "\u2014", "\u2013", "-", "\uff0d")


def run_eval(
    cfg: dict[str, Any],
    top_k: int | None = None,
    model: str | None = None,
    engine: str | None = None,
) -> dict[str, Any]:
    top_k = top_k if top_k is not None else int(cfg.get("eval", {}).get("top_k", 5))
    engine = engine or ("hybrid" if model else "fts")
    if engine not in SEARCH_ENGINES:
        raise ValueError(f"不支持的检索引擎: {engine}，可选 {sorted(SEARCH_ENGINES)}")
    if engine != "fts" and not model:
        model = cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    started = time.time()
    q_path = Path(cfg["eval"]["questions"])
    q_text = q_path.read_text(encoding="utf-8")
    data = yaml.safe_load(q_text)
    questions = data["questions"]
    conn = db.connect(cfg["db_path"])
    db_path = Path(cfg["db_path"])

    results: list[dict[str, Any]] = []
    for q in questions:
        hits = _search_hits(cfg, conn, q, top_k, model, engine)
        norm = _normalize_expected(q.get("expected"))
        item: dict[str, Any] = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "company": q.get("company"),
            "retrieval": _retrieval_result(hits, norm, top_k),
        }
        structured = _statement_match(conn, q, norm)
        if structured is not None:
            item["structured"] = structured
        if q.get("type") == "end2end" or q.get("rubric") is not None:
            generation: dict[str, Any] = {"auto_scored": False, "pending_manual": True}
            if q.get("rubric") is not None:
                generation["rubric"] = q["rubric"]
            item["generation"] = generation
        results.append(item)

    summary = _summarize(results)
    conn.close()
    meta = {
        "engine": engine,
        "top_k": top_k,
        "model": model if engine != "fts" else None,
        "questions_sha256": hashlib.sha256(q_text.encode("utf-8")).hexdigest(),
        "questions_count": len(questions),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else None,
        "db_mtime": (
            datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc).isoformat()
            if db_path.exists()
            else None
        ),
        "duration_seconds": round(time.time() - started, 3),
    }
    return {
        "meta": meta,
        "top_k": top_k,
        "model": model if engine != "fts" else None,
        "summary": summary,
        "results": results,
    }

def _search_hits(
    cfg: dict[str, Any],
    conn,
    q: dict[str, Any],
    top_k: int,
    model: str | None,
    engine: str,
) -> list[dict[str, Any]]:
    keywords = q.get("keywords")
    if not keywords and q.get("type") == "keyword":
        company = q.get("company") or ""
        term = q.get("question") or ""
        if company and term.startswith(company):
            term = term[len(company):].strip()
        keywords = [term or q["question"]]
    queries = keywords or [q["question"]]
    fused: dict[int, dict[str, Any]] = {}
    for query in queries:
        hs = _run_search(cfg, conn, query, q.get("company"), top_k, model, engine)
        for pos, h in enumerate(hs, start=1):
            page_id = h["page_id"]
            entry = fused.get(page_id)
            if entry is None:
                entry = dict(h)
                entry["_rrf"] = 0.0
                entry["_min_rank"] = pos
                fused[page_id] = entry
            entry["_rrf"] += 1.0 / (pos + 60)
            if pos < entry["_min_rank"]:
                entry["_min_rank"] = pos
    items = list(fused.values())
    items.sort(key=lambda h: (-h["_rrf"], h["_min_rank"], h["page_id"]))
    out = items[:top_k]
    for h in out:
        h.pop("_rrf", None)
        h.pop("_min_rank", None)
    return out


def _run_search(
    cfg: dict[str, Any],
    conn,
    query: str,
    company: str | None,
    top_k: int,
    model: str | None,
    engine: str,
) -> list[dict[str, Any]]:
    if engine == "fts":
        return search.fts_search(conn, query, company=company, top_k=top_k)
    from stock_kb import vector

    if engine == "vector":
        return vector.vector_search(
            conn,
            model,
            query,
            top_k=top_k,
            company=company,
            cache_dir=cfg["models_dir"],
            backend=cfg.get("embedding", {}).get("backend", "auto"),
        )
    return vector.hybrid_search(
        conn,
        query,
        model=model,
        top_k=top_k,
        company=company,
        cache_dir=cfg["models_dir"],
        backend=cfg.get("embedding", {}).get("backend", "auto"),
    )


def _normalize_expected(expected: Any) -> dict[str, Any]:
    if expected is None:
        return {"answer": None, "sources": [], "negatives": [], "legacy": False}
    if isinstance(expected, dict):
        return {
            "answer": expected.get("answer"),
            "sources": [_normalize_source(s) for s in (expected.get("sources") or [])],
            "negatives": [_normalize_source(s) for s in (expected.get("negatives") or [])],
            "legacy": False,
        }
    if isinstance(expected, list):
        return {
            "answer": None,
            "sources": [_normalize_source(s) for s in expected],
            "negatives": [],
            "legacy": True,
        }
    return {"answer": None, "sources": [], "negatives": [], "legacy": False}


def _normalize_source(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        source = {}
    page = source.get("page")
    if page is not None:
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = None
    relevance = source.get("relevance", 1)
    if relevance is None:
        relevance = 1
    try:
        relevance = int(relevance)
    except (TypeError, ValueError):
        relevance = 1
    return {
        "file": str(source.get("file") or ""),
        "page": page,
        "table": source.get("table"),
        "required": bool(source.get("required", False)),
        "relevance": relevance,
    }


def _file_stem(file: str) -> str:
    return file.rsplit(".", 1)[0]


def _file_matches(title: str, file: str) -> bool:
    if not file:
        return True
    candidates = {file, _file_stem(file)}
    return any(c and c in title for c in candidates)


def _source_matches(hit: dict[str, Any], source: dict[str, Any]) -> bool:
    file_ok = _file_matches(hit.get("title") or "", source["file"])
    page_ok = source["page"] is None or hit.get("page_no") == source["page"]
    has_criterion = bool(source["file"]) or source["page"] is not None
    return file_ok and page_ok and has_criterion


def _retrieval_result(
    hits: list[dict[str, Any]], norm: dict[str, Any], top_k: int
) -> dict[str, Any]:
    sources = norm["sources"]
    required = [s for s in sources if s["required"]]
    target = required if required else sources
    rel: list[int] = []
    matched_ranks: list[int] = []
    negative_ranks: list[int] = []
    for i, h in enumerate(hits, start=1):
        rel.append(
            max((s["relevance"] for s in sources if _source_matches(h, s)), default=0)
        )
        if any(_source_matches(h, s) for s in target):
            matched_ranks.append(i)
        if any(_source_matches(h, s) for s in norm["negatives"]):
            negative_ranks.append(i)
    hit = bool(matched_ranks)
    rank = matched_ranks[0] if matched_ranks else None
    result: dict[str, Any] = {
        "hit": hit,
        "rank": rank,
        "mrr": round(1.0 / rank, 5) if rank else 0.0,
        "ndcg": round(_ndcg_at_k(rel, [s["relevance"] for s in sources], top_k), 5),
        "precision_at_k": round(sum(1 for r in rel if r > 0) / top_k, 5),
        "negative_hit_at_k": bool(negative_ranks),
        "negative_hit_at_1": bool(negative_ranks and negative_ranks[0] == 1),
        "negative_ranks": negative_ranks,
        "top_hits": [
            {
                "page_id": h.get("page_id"),
                "company": h.get("company"),
                "title": h.get("title"),
                "page": h.get("page_no"),
            }
            for h in hits
        ],
        "expected_sources": sources,
    }
    if norm["negatives"]:
        result["negatives"] = norm["negatives"]
    return result


def _ndcg_at_k(rel: list[int], source_rel: list[int], top_k: int) -> float:
    dcg = sum(r / math.log2(i + 1) for i, r in enumerate(rel[:top_k], start=1))
    ideal = sorted(source_rel, reverse=True)[:top_k]
    idcg = sum(r / math.log2(i + 1) for i, r in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _statement_match(conn, q: dict[str, Any], norm: dict[str, Any]) -> dict[str, Any] | None:
    stmt = q.get("statement")
    if not stmt:
        return None
    statement_type = stmt.get("type") or stmt.get("statement_type")
    year = stmt.get("year")
    period_type = stmt.get("period_type")
    sql = (
        "SELECT s.id, s.line_name_norm, s.value, s.unit, s.currency, s.year, s.page_no, "
        "r.id AS report_id, r.title "
        "FROM statements s JOIN reports r ON r.id = s.report_id "
        "WHERE r.company=? AND s.statement_type=? AND s.year=?"
    )
    params: list[Any] = [q.get("company"), statement_type, year]
    if period_type is not None:
        sql += " AND r.period_type=?"
        params.append(period_type)
    rows = conn.execute(sql, params).fetchall()

    tokens = [_normalize_token(t) for t in (stmt.get("line_contains") or [])]
    tokens = [t for t in tokens if t]
    allowed_sources = _allowed_sources(norm)
    expected_value = stmt.get("expected_value")
    expected_unit = stmt.get("expected_unit")
    expected_currency = stmt.get("expected_currency")
    tolerance = float(stmt.get("tolerance_ratio", 0.01))

    field_rows: list[dict[str, Any]] = []
    for r in rows:
        name = _normalize_token(r["line_name_norm"])
        if not name:
            continue
        if not any(tok in name for tok in tokens):
            continue
        title = r["title"] or ""
        source_ok = True
        page_ok = None
        source_row_match = True
        if allowed_sources is not None:
            matches = [
                _statement_source_matches(
                    title=title,
                    stmt_page=r["page_no"],
                    source=source,
                )
                for source in allowed_sources
            ]
            source_ok = any(m[0] for m in matches)
            page_ok = any(m[1] for m in matches)
            source_row_match = any(m[0] and m[1] for m in matches)
        value_ok = True
        if expected_value is not None:
            value_ok = _value_within(r["value"], expected_value, tolerance)
        unit_ok = _expected_text_matches(r["unit"], expected_unit)
        currency_ok = _expected_text_matches(r["currency"], expected_currency)
        row_pass = (
            bool(tokens)
            and value_ok
            and (allowed_sources is None or source_row_match)
        )
        field_rows.append(
            {
                "line_name_norm": r["line_name_norm"],
                "value": r["value"],
                "unit": r["unit"],
                "currency": r["currency"],
                "page_no": r["page_no"],
                "title": title,
                "source_ok": source_ok,
                "page_ok": page_ok,
                "source_row_match": source_row_match,
                "value_ok": value_ok,
                "unit_ok": unit_ok,
                "currency_ok": currency_ok,
                "row_pass": row_pass,
            }
        )

    field_match = bool(field_rows)
    source_match = None
    if allowed_sources is not None:
        source_match = any(r["source_row_match"] for r in field_rows)
    page_match = None
    if allowed_sources is not None:
        page_match = any(r["page_ok"] for r in field_rows)
    value_match = None
    if expected_value is not None:
        value_match = any(r["value_ok"] for r in field_rows)
    hit = any(r["row_pass"] for r in field_rows)

    unit_checks = [r["unit_ok"] for r in field_rows if r["unit_ok"] is not None]
    currency_checks = [
        r["currency_ok"] for r in field_rows if r["currency_ok"] is not None
    ]
    unit_match = any(unit_checks) if unit_checks else None
    currency_match = any(currency_checks) if currency_checks else None

    return {
        "hit": hit,
        "field_match": field_match,
        "source_match": source_match,
        "page_match": page_match,
        "value_match": value_match,
        "unit_match": unit_match,
        "currency_match": currency_match,
        "expected_unit": expected_unit,
        "expected_currency": expected_currency,
        "matched_count": len(field_rows),
        "matched_rows": [
            {
                "line_name_norm": r["line_name_norm"],
                "value": r["value"],
                "unit": r["unit"],
                "currency": r["currency"],
                "page_no": r["page_no"],
                "title": r["title"],
                "source_ok": r["source_ok"],
                "page_ok": r["page_ok"],
                "source_row_match": r["source_row_match"],
                "value_ok": r["value_ok"],
                "unit_ok": r["unit_ok"],
                "currency_ok": r["currency_ok"],
                "row_pass": r["row_pass"],
            }
            for r in field_rows[:20]
        ],
    }


def _expected_text_matches(actual: Any, expected: Any) -> bool | None:
    if expected is None or expected == "":
        return None
    if actual is None or actual == "":
        return None
    return _normalize_token(actual) == _normalize_token(expected)


def _allowed_sources(norm: dict[str, Any]) -> list[dict[str, Any]] | None:
    sources = norm["sources"]
    if not sources:
        return None
    if norm["legacy"]:
        first = sources[0]["file"]
        if not first:
            return None
        return [
            {
                "file": _file_stem(first),
                "page": sources[0]["page"],
            }
        ]
    return [
        {
            "file": s["file"],
            "page": s["page"],
        }
        for s in sources
        if s["file"] or s["page"] is not None
    ] or None


def _statement_source_matches(
    *,
    title: str,
    stmt_page: Any,
    source: dict[str, Any],
) -> tuple[bool, bool]:
    file = source["file"]
    page = source.get("page")
    source_ok = (not file) or (file in title)
    page_ok = page is None or stmt_page == page
    return source_ok, page_ok


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).casefold()
    for ch in _DASHES:
        text = text.replace(ch, "")
    return text


def _value_within(value: Any, expected: Any, tolerance_ratio: float) -> bool:
    if value is None or expected is None:
        return False
    try:
        v = float(value)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    if e == 0:
        return abs(v) <= tolerance_ratio
    return abs(v - e) <= tolerance_ratio * abs(e)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ret_stats: dict[str, dict[str, Any]] = {}
    for item in results:
        if item["type"] not in RETRIEVAL_TYPES:
            continue
        if item["type"] in {"exact", "cross"} and item.get("structured") is not None:
            continue
        if not item["retrieval"]["expected_sources"]:
            continue
        s = ret_stats.setdefault(
            item["type"],
            {
                "n": 0,
                "hit": 0,
                "hit1": 0,
                "rr_sum": 0.0,
                "ndcg_sum": 0.0,
                "prec_sum": 0.0,
                "neg_hit": 0,
                "neg_at_1": 0,
            },
        )
        s["n"] += 1
        r = item["retrieval"]
        if r["hit"]:
            s["hit"] += 1
        if r["rank"] == 1:
            s["hit1"] += 1
        if r["rank"]:
            s["rr_sum"] += 1.0 / r["rank"]
        s["ndcg_sum"] += r["ndcg"]
        s["prec_sum"] += r.get("precision_at_k", 0.0)
        if r.get("negative_hit_at_k"):
            s["neg_hit"] += 1
        if r.get("negative_hit_at_1"):
            s["neg_at_1"] += 1

    retrieval: dict[str, Any] = {}
    for typ, s in ret_stats.items():
        n = s["n"]
        retrieval[typ] = {
            "n": n,
            "recall_at_k": round(s["hit"] / n, 3) if n else 0.0,
            "hit_at_1": round(s["hit1"] / n, 3) if n else 0.0,
            "mrr": round(s["rr_sum"] / n, 3) if n else 0.0,
            "ndcg": round(s["ndcg_sum"] / n, 3) if n else 0.0,
            "precision_at_k": round(s["prec_sum"] / n, 3) if n else 0.0,
            "negative_hit_rate": round(s["neg_hit"] / n, 3) if n else 0.0,
            "negative_at_1_rate": round(s["neg_at_1"] / n, 3) if n else 0.0,
        }
    if ret_stats:
        n = sum(s["n"] for s in ret_stats.values())
        retrieval["total"] = {
            "n": n,
            "recall_at_k": round(
                sum(s["hit"] for s in ret_stats.values()) / n, 3
            ),
            "hit_at_1": round(
                sum(s["hit1"] for s in ret_stats.values()) / n, 3
            ),
            "mrr": round(
                sum(s["rr_sum"] for s in ret_stats.values()) / n, 3
            ),
            "ndcg": round(
                sum(s["ndcg_sum"] for s in ret_stats.values()) / n, 3
            ),
            "precision_at_k": round(
                sum(s["prec_sum"] for s in ret_stats.values()) / n, 3
            ),
            "negative_hit_rate": round(
                sum(s["neg_hit"] for s in ret_stats.values()) / n, 3
            ),
            "negative_at_1_rate": round(
                sum(s["neg_at_1"] for s in ret_stats.values()) / n, 3
            ),
        }

    structured = {
        "n": 0,
        "hit": 0,
        "field_match": 0,
        "value_match": 0,
        "source_match": 0,
        "page_match": 0,
        "unit_match": 0,
        "currency_match": 0,
        "value_total": 0,
        "source_total": 0,
        "page_total": 0,
        "unit_total": 0,
        "currency_total": 0,
    }
    for item in results:
        st = item.get("structured")
        if st is None:
            continue
        structured["n"] += 1
        if st["hit"]:
            structured["hit"] += 1
        if st["field_match"]:
            structured["field_match"] += 1
        if st["value_match"] is True:
            structured["value_match"] += 1
        if st["source_match"] is True:
            structured["source_match"] += 1
        if st["page_match"] is True:
            structured["page_match"] += 1
        if st["value_match"] is not None:
            structured["value_total"] += 1
        if st["source_match"] is not None:
            structured["source_total"] += 1
        if st["page_match"] is not None:
            structured["page_total"] += 1
        if st.get("unit_match") is True:
            structured["unit_match"] += 1
        if st.get("currency_match") is True:
            structured["currency_match"] += 1
        if st.get("unit_match") is not None:
            structured["unit_total"] += 1
        if st.get("currency_match") is not None:
            structured["currency_total"] += 1

    generation = {"n": 0, "auto_scored": 0, "pending_manual": 0}
    for item in results:
        gen = item.get("generation")
        if gen is None:
            continue
        generation["n"] += 1
        if gen.get("auto_scored"):
            generation["auto_scored"] += 1
        if gen.get("pending_manual"):
            generation["pending_manual"] += 1

    return {"retrieval": retrieval, "structured": structured, "generation": generation}


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

    meta = data.get("meta") or {}
    lines = ["# 检索评测报告", "", f"- 时间：{ts}"]
    lines.append(f"- 检索引擎：{meta.get('engine') or data.get('engine') or 'fts'}")
    if data.get("model"):
        lines.append(f"- 模型：{data['model']}")
    lines.append(f"- top_k：{data['top_k']}")
    lines.append(f"- 题目数：{meta.get('questions_count', len(data.get('results', [])))}")
    lines.append(f"- 题目集 SHA-256：{meta.get('questions_sha256', '-')}")
    lines.append(f"- 耗时：{meta.get('duration_seconds', '-')} 秒")
    if meta.get("db_size_bytes"):
        lines.append(f"- DB 大小：{meta['db_size_bytes']} bytes")
    if meta.get("db_mtime"):
        lines.append(f"- DB mtime：{meta['db_mtime']}")
    lines.append("")
    lines.append("## 检索（Retrieval）")
    lines.append("")
    lines.append("| 类型 | 数量 | Recall@k | Hit@1 | MRR | nDCG | Precision@k | Neg@k | Neg@1 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for typ, s in data["summary"].get("retrieval", {}).items():
        lines.append(
            f"| {typ} | {s['n']} | {s['recall_at_k']} | {s['hit_at_1']} | "
            f"{s['mrr']} | {s['ndcg']} | {s['precision_at_k']} | "
            f"{s['negative_hit_rate']} | {s['negative_at_1_rate']} |"
        )
    lines.append("")
    lines.append("> Neg@k：前 k 条中出现任一负样本的题目比例；Neg@1：第 1 条命中负样本的题目比例。")
    lines.append("")
    lines.append("## 结构化三表（Structured）")
    lines.append("")
    lines.append("| 数量 | Hit | Field | Value | Source | Page | Unit | Currency |")
    lines.append("|---|---|---|---|---|---|---|---|")
    st = data["summary"].get("structured", {})
    unit_cell = (
        f"{st.get('unit_match', 0)}/{st.get('unit_total', 0)}"
        if st.get("unit_total")
        else "0/0"
    )
    currency_cell = (
        f"{st.get('currency_match', 0)}/{st.get('currency_total', 0)}"
        if st.get("currency_total")
        else "0/0"
    )
    lines.append(
        f"| {st.get('n', 0)} | {st.get('hit', 0)} | {st.get('field_match', 0)} | "
        f"{st.get('value_match', 0)} | {st.get('source_match', 0)} | "
        f"{st.get('page_match', 0)} | {unit_cell} | {currency_cell} |"
    )
    lines.append("")
    lines.append("> Unit/Currency 为 0/0 表示 DB 未存单位/币种，尚不可自动验证。")
    lines.append("")
    lines.append("## 生成题（Generation）")
    lines.append("")
    lines.append("| 数量 | Auto scored | Pending manual |")
    lines.append("|---|---|---|")
    gen = data["summary"].get("generation", {})
    lines.append(
        f"| {gen.get('n', 0)} | {gen.get('auto_scored', 0)} | {gen.get('pending_manual', 0)} |"
    )

    lines.append("")
    lines.append("## 失败与负样本命中明细")
    lines.append("")
    shown = 0
    for item in data.get("results", []):
        r = item.get("retrieval") or {}
        if item["type"] not in RETRIEVAL_TYPES:
            continue
        if item["type"] in {"exact", "cross"} and item.get("structured") is not None:
            continue
        if not r.get("expected_sources"):
            continue
        if not r.get("hit") or r.get("negative_hit_at_k"):
            shown += 1
            expected = "、".join(
                f"{s.get('file')} p{s.get('page')}" for s in r.get("expected_sources", [])
            )
            top = "；".join(
                f"#{i} {h.get('title')} p{h.get('page')}"
                for i, h in enumerate(r.get("top_hits", []), start=1)
            )
            lines.append(
                f"- **{item['id']}** {item.get('question')}（命中={r.get('hit')}，"
                f"负样本命中={r.get('negative_hit_at_k')}，负样本位次={r.get('negative_ranks')}）"
            )
            lines.append(f"  - 期望：{expected or '-'}")
            lines.append(f"  - 实际：{top or '-'}")
    if shown == 0:
        lines.append("- 无")
    st_failures = [i for i in data.get("results", []) if i.get("structured") and not i["structured"].get("hit")]
    if st_failures:
        lines.append("")
        lines.append("## 结构化失败明细")
        lines.append("")
        for item in st_failures:
            st = item["structured"]
            lines.append(
                f"- **{item['id']}** {item.get('question')}：field={st.get('field_match')}，"
                f"value={st.get('value_match')}，source={st.get('source_match')}，"
                f"page={st.get('page_match')}"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path
