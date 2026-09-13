from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from stock_kb import db, search
from stock_kb.eval_stats import wilson_ci
from stock_kb.route import route as route_query


RETRIEVAL_TYPES = {"exact", "keyword", "semantic", "cross"}
NO_ANSWER_TYPE = "no_answer"
INDICATOR_TYPE = "indicator"
ROUTE_TYPE = "route"
YEAR_FILTER_TYPE = "year_filter"
SEARCH_ENGINES = {"fts", "vector", "hybrid"}
SEARCH_PATHS = {"mcp_compat", "eval_rrf_keywords"}
_DASHES = (" ", "\t", "\n", "\r", "\u2014", "\u2013", "-", "\uff0d")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]{4,}")


def run_eval(
    cfg: dict[str, Any],
    top_k: int | None = None,
    model: str | None = None,
    engine: str | None = None,
    search_path: str = "mcp_compat",
    split: str | None = None,
) -> dict[str, Any]:
    top_k = top_k if top_k is not None else int(cfg.get("eval", {}).get("top_k", 5))
    engine = engine or ("hybrid" if model else "fts")
    if engine not in SEARCH_ENGINES:
        raise ValueError(f"不支持的检索引擎: {engine}，可选 {sorted(SEARCH_ENGINES)}")
    if search_path not in SEARCH_PATHS:
        raise ValueError(
            f"不支持的 search_path: {search_path}，可选 {sorted(SEARCH_PATHS)}"
        )
    if engine != "fts" and not model:
        model = cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    started = time.time()
    q_path = Path(cfg["eval"]["questions"])
    q_text = q_path.read_text(encoding="utf-8")
    data = yaml.safe_load(q_text)
    questions = data["questions"]
    if split:
        questions = [q for q in questions if (q.get("split") or "freeze") == split]
    conn = db.connect(cfg["db_path"])
    db_path = Path(cfg["db_path"])

    # no_answer 哨兵：先确认引擎本身健康（公司名必命中），
    # 避免「检索 bug 空结果」伪装成「正确拒答」抬高 empty_rate。
    engine_alive: bool | None = None
    if any((q.get("type") or "") == NO_ANSWER_TYPE for q in questions):
        try:
            sentinel = _run_search(
                cfg, conn, "海底捞", None, 1, model, engine
            )
            engine_alive = bool(sentinel)
        except Exception:
            engine_alive = False

    results: list[dict[str, Any]] = []
    for q in questions:
        qtype = q.get("type") or ""
        if qtype == ROUTE_TYPE:
            expected = q.get("expected") or {}
            decision = route_query(q.get("question") or "", company=q.get("company"))
            predicted = decision.get("tool")
            want = expected.get("tool")
            results.append(
                {
                    "id": q["id"],
                    "type": ROUTE_TYPE,
                    "question": q["question"],
                    "company": q.get("company"),
                    "split": q.get("split") or "freeze",
                    "route": {
                        "predicted": predicted,
                        "expected": want,
                        "hit": predicted == want,
                        "decision": decision,
                    },
                }
            )
            continue
        hits, query, hybrid_fused = _search_hits(
            cfg, conn, q, top_k, model, engine, search_path
        )
        norm = _normalize_expected(q.get("expected"))
        retrieval = _retrieval_result(hits, norm, top_k)
        retrieval["query"] = query
        retrieval["hybrid_fused"] = hybrid_fused
        retrieval["error_tags"] = classify_retrieval_errors(
            query=query,
            qtype=qtype,
            hits=hits,
            norm=norm,
        )
        item: dict[str, Any] = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "company": q.get("company"),
            "split": q.get("split") or "freeze",
            "retrieval": retrieval,
        }
        if qtype == NO_ANSWER_TYPE:
            item["engine_alive"] = engine_alive
        if qtype == YEAR_FILTER_TYPE:
            expected_year = (q.get("expected") or {}).get("year")
            q_years = set(search.query_years(query))
            if expected_year is not None:
                q_years.add(int(expected_year))
            n_hits = len(hits)
            matched = sum(1 for h in hits if h.get("year") in q_years)
            item["year_filter"] = {
                "query_years": sorted(q_years),
                "n_hits": n_hits,
                "year_matched": matched,
                "precision": round(matched / n_hits, 3) if n_hits else None,
            }
        structured = _statement_match(conn, q, norm)
        if structured is not None:
            item["structured"] = structured
        indicator = _indicator_match(conn, q)
        if indicator is not None:
            item["indicator"] = indicator
        if qtype == "end2end" or q.get("rubric") is not None:
            item["generation"] = _material_coverage(conn, q, norm)
        results.append(item)

    summary = _summarize(results)
    conn.close()
    meta = {
        "engine": engine,
        "top_k": top_k,
        "model": model if engine != "fts" else None,
        "search_path": search_path,
        "split": split,
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

def primary_query(q: dict[str, Any]) -> str:
    """Single query aligned with MCP search_reports (one string + company filter)."""
    if q.get("type") == "keyword":
        company = q.get("company") or ""
        term = q.get("question") or ""
        if company and term.startswith(company):
            term = term[len(company) :].strip()
        keywords = q.get("keywords")
        if keywords:
            return str(keywords[0])
        return term or q["question"]
    return q["question"]


def _search_queries(q: dict[str, Any], search_path: str) -> list[str]:
    if search_path == "mcp_compat":
        return [primary_query(q)]
    keywords = q.get("keywords")
    if not keywords and q.get("type") == "keyword":
        company = q.get("company") or ""
        term = q.get("question") or ""
        if company and term.startswith(company):
            term = term[len(company) :].strip()
        keywords = [term or q["question"]]
    return list(keywords) if keywords else [q["question"]]


def _search_hits(
    cfg: dict[str, Any],
    conn,
    q: dict[str, Any],
    top_k: int,
    model: str | None,
    engine: str,
    search_path: str,
) -> tuple[list[dict[str, Any]], str, bool]:
    queries = _search_queries(q, search_path)
    fused: dict[int, dict[str, Any]] = {}
    for query in queries:
        hs = _run_search(
            cfg,
            conn,
            query,
            q.get("company"),
            top_k,
            model,
            engine,
            year=q.get("year"),
            report_type=q.get("report_type"),
            language=q.get("language"),
        )
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
    # 以检索器返回的融合标志为准，避免评测口径与实现漂移
    hybrid_fused = engine == "hybrid" and any(h.get("hybrid_fused") for h in out)
    return out, queries[0] if queries else "", hybrid_fused


def _run_search(
    cfg: dict[str, Any],
    conn,
    query: str,
    company: str | None,
    top_k: int,
    model: str | None,
    engine: str,
    year: int | None = None,
    report_type: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    if engine == "fts":
        return search.fts_search(
            conn,
            query,
            company=company,
            top_k=top_k,
            year=year,
            report_type=report_type,
            language=language,
        )
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
            year=year,
            report_type=report_type,
            language=language,
        )
    return vector.hybrid_search(
        conn,
        query,
        model=model,
        top_k=top_k,
        company=company,
        cache_dir=cfg["models_dir"],
        backend=cfg.get("embedding", {}).get("backend", "auto"),
        year=year,
        report_type=report_type,
        language=language,
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
    authority = str(source.get("authority") or "").strip().lower()
    if authority not in {"annual", "interim", "research", "prospectus"}:
        authority = ""
    return {
        "file": str(source.get("file") or ""),
        "page": page,
        "table": source.get("table"),
        "required": bool(source.get("required", False)),
        "relevance": relevance,
        "authority": authority,
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


def _years_in(text: Any) -> set[int]:
    return {int(m) for m in _YEAR_RE.findall(str(text or ""))}


def _cjk_bigrams(text: str) -> set[str]:
    chars = _CJK_RE.findall(text or "")
    return {"".join(chars[i : i + 2]) for i in range(len(chars) - 1)}


def classify_retrieval_errors(
    *,
    query: str,
    qtype: str,
    hits: list[dict[str, Any]],
    norm: dict[str, Any],
) -> list[str]:
    """Rule-based tags for retrieval misses and pollution. Order is stable."""
    tags: list[str] = []
    sources = norm.get("sources") or []
    required = [s for s in sources if s.get("required")] or sources
    negatives = norm.get("negatives") or []

    if hits and any(_source_matches(hits[0], s) for s in negatives):
        tags.append("negative_at_1")

    expected_years: set[int] = set()
    for s in required:
        expected_years |= _years_in(s.get("file"))

    near_miss = False
    year_mismatch = False
    for h in hits:
        if any(_source_matches(h, s) for s in required):
            continue
        title = h.get("title") or ""
        page = h.get("page_no")
        for s in required:
            if not _file_matches(title, s.get("file") or ""):
                continue
            src_page = s.get("page")
            if src_page is not None and page is not None:
                try:
                    if abs(int(page) - int(src_page)) <= 5:
                        near_miss = True
                except (TypeError, ValueError):
                    pass
        hit_years = _years_in(title)
        if h.get("year") is not None:
            try:
                hit_years.add(int(h["year"]))
            except (TypeError, ValueError):
                pass
        if expected_years and hit_years and hit_years.isdisjoint(expected_years):
            year_mismatch = True
    if near_miss:
        tags.append("page_near_miss")
    if year_mismatch:
        tags.append("year_mismatch")

    q_cjk = bool(_CJK_RE.search(query or ""))
    q_latin = bool(_LATIN_RE.search(query or ""))
    langs = [h.get("language") for h in hits if h.get("language")]
    if langs:
        if q_cjk and not q_latin and all(lang == "en" for lang in langs):
            tags.append("lang_mismatch")
        elif q_latin and not q_cjk and all(lang == "zh" for lang in langs):
            tags.append("lang_mismatch")

    if qtype == "semantic":
        qgrams = _cjk_bigrams(query)
        hit_text = "".join(str(h.get("snippet") or "") for h in hits)
        hgrams = _cjk_bigrams(hit_text)
        if qgrams and hgrams and len(qgrams & hgrams) / len(qgrams) >= 0.3:
            tags.append("lexical_overlap")

    return tags


def _merge_tag_counts(tag_maps) -> dict[str, int]:
    out: dict[str, int] = {}
    for tags in tag_maps:
        for tag, count in (tags or {}).items():
            out[tag] = out.get(tag, 0) + count
    return out


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
    filing = [s for s in sources if s.get("authority") in {"annual", "interim"}]
    filing_ranks: list[int] = []
    for i, h in enumerate(hits, start=1):
        if any(_source_matches(h, s) for s in filing):
            filing_ranks.append(i)
    result: dict[str, Any] = {
        "hit": hit,
        "rank": rank,
        "mrr": round(1.0 / rank, 5) if rank else 0.0,
        "ndcg": round(_ndcg_at_k(rel, [s["relevance"] for s in sources], top_k), 5),
        "precision_at_k": round(sum(1 for r in rel if r > 0) / top_k, 5),
        "negative_hit_at_k": bool(negative_ranks),
        "negative_hit_at_1": bool(negative_ranks and negative_ranks[0] == 1),
        "negative_ranks": negative_ranks,
        "annual_eligible": bool(filing),
        "annual_hit": bool(filing_ranks),
        "annual_rank": filing_ranks[0] if filing_ranks else None,
        "top_hits": [
            {
                "page_id": h.get("page_id"),
                "company": h.get("company"),
                "title": h.get("title"),
                "page": h.get("page_no"),
                "year": h.get("year"),
                "language": h.get("language"),
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
    tolerance = float(stmt.get("tolerance_ratio", 0.0001))

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
    parse_hit = _parse_hit(
        conn,
        company=q.get("company"),
        year=year,
        expected_value=expected_value,
        tolerance=tolerance,
        allowed_sources=allowed_sources,
    )

    unit_checks = [r["unit_ok"] for r in field_rows if r["unit_ok"] is not None]
    currency_checks = [
        r["currency_ok"] for r in field_rows if r["currency_ok"] is not None
    ]
    unit_match = any(unit_checks) if unit_checks else None
    currency_match = any(currency_checks) if currency_checks else None

    return {
        "hit": hit,
        "parse_hit": parse_hit,
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


def _parse_hit(
    conn,
    *,
    company: Any,
    year: Any,
    expected_value: Any,
    tolerance: float,
    allowed_sources: list[dict[str, Any]] | None,
) -> bool | None:
    """L1: golden value exists on the cited page, ignoring line_contains."""
    if expected_value is None or not allowed_sources:
        return None
    rows = conn.execute(
        "SELECT s.value, s.page_no, r.title FROM statements s "
        "JOIN reports r ON r.id = s.report_id "
        "WHERE r.company=? AND s.year=? AND s.value IS NOT NULL",
        (company, year),
    ).fetchall()
    for r in rows:
        if not _value_within(r["value"], expected_value, tolerance):
            continue
        for source in allowed_sources:
            file_ok, page_ok = _statement_source_matches(
                title=r["title"] or "",
                stmt_page=r["page_no"],
                source=source,
            )
            if file_ok and page_ok:
                return True
    return False


def _indicator_match(conn, q: dict[str, Any]) -> dict[str, Any] | None:
    spec = q.get("indicator")
    if not spec:
        return None
    name = spec.get("name")
    year = spec.get("year")
    period_type = spec.get("period_type") or "annual"
    expected = spec.get("expected_value")
    tolerance = float(spec.get("tolerance_ratio", 0.0001))
    sql = (
        "SELECT name, value, unit, currency, year, period_type, page_no "
        "FROM indicators WHERE company=? AND name=? AND year=?"
    )
    params: list[Any] = [q.get("company"), name, year]
    if period_type is not None:
        sql += " AND period_type=?"
        params.append(period_type)
    rows = conn.execute(sql, params).fetchall()
    value_ok = False
    unit_ok = None
    matched = []
    for r in rows:
        vok = expected is None or _value_within(r["value"], expected, tolerance)
        uok = _expected_text_matches(r["unit"], spec.get("expected_unit"))
        if vok:
            value_ok = True
        if uok is not None:
            unit_ok = bool(unit_ok) or uok
        matched.append(
            {
                "name": r["name"],
                "value": r["value"],
                "unit": r["unit"],
                "year": r["year"],
                "page_no": r["page_no"],
                "value_ok": vok,
            }
        )
    return {
        "hit": value_ok and bool(rows),
        "value_match": value_ok if expected is not None else None,
        "unit_match": unit_ok,
        "n_rows": len(rows),
        "matched_rows": matched[:10],
        "expected_value": expected,
        "expected_unit": spec.get("expected_unit"),
    }


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


def _material_coverage(conn, q: dict[str, Any], norm: dict[str, Any]) -> dict[str, Any]:
    sources = [s for s in norm["sources"] if s.get("required")] or norm["sources"]
    found = 0
    missing: list[str] = []
    for s in sources:
        file_frag = s.get("file") or ""
        if not file_frag:
            continue
        row = conn.execute(
            "SELECT 1 FROM reports WHERE instr(title, ?) > 0 LIMIT 1",
            (file_frag,),
        ).fetchone()
        if row:
            found += 1
        else:
            missing.append(file_frag)
    n = len([s for s in sources if s.get("file")])
    complete = n > 0 and found == n
    out: dict[str, Any] = {
        "auto_scored": True,
        "pending_manual": not complete,
        "material_hit": found,
        "material_n": n,
        "missing": missing,
    }
    if q.get("rubric") is not None:
        out["rubric"] = q["rubric"]
    return out


def _blank_ret_bucket() -> dict[str, Any]:
    return {
        "n": 0,
        "hit": 0,
        "hit1": 0,
        "rr_sum": 0.0,
        "ndcg_sum": 0.0,
        "prec_sum": 0.0,
        "neg_hit": 0,
        "neg_at_1": 0,
        "fused_n": 0,
        "near_miss": 0,
        "error_tags": {},
        "annual_n": 0,
        "annual_hit": 0,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ret_stats: dict[str, dict[str, Any]] = {}
    ret_diag: dict[str, dict[str, Any]] = {}
    no_answer = {"n": 0, "empty": 0, "nonempty": 0, "engine_error": 0}
    for item in results:
        split = item.get("split") or "freeze"
        if item["type"] == NO_ANSWER_TYPE:
            no_answer["n"] += 1
            n_hits = len((item.get("retrieval") or {}).get("top_hits") or [])
            if n_hits == 0:
                if item.get("engine_alive") is False:
                    # 哨兵查询也为空：引擎故障，不能算「正确拒答」
                    no_answer["engine_error"] += 1
                else:
                    no_answer["empty"] += 1
            else:
                no_answer["nonempty"] += 1
            continue
        if item["type"] not in RETRIEVAL_TYPES:
            continue
        if item["type"] in {"exact", "cross"} and item.get("structured") is not None:
            continue
        if not item["retrieval"]["expected_sources"]:
            continue
        target = ret_diag if split == "diag" else ret_stats
        s = target.setdefault(item["type"], _blank_ret_bucket())
        s["n"] += 1
        r = item["retrieval"]
        if r["hit"]:
            s["hit"] += 1
        elif "page_near_miss" in (r.get("error_tags") or []):
            # 软分：期望页在 top-k 内仅页码略偏（±5），未命中但近乎可用
            s["near_miss"] += 1
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
        if r.get("hybrid_fused"):
            s["fused_n"] += 1
        if r.get("annual_eligible"):
            s["annual_n"] += 1
            if r.get("annual_hit"):
                s["annual_hit"] += 1
        for tag in r.get("error_tags") or []:
            s["error_tags"][tag] = s["error_tags"].get(tag, 0) + 1

    retrieval = _finalize_retrieval(ret_stats)
    retrieval_diag = _finalize_retrieval(ret_diag)

    structured = {
        "n": 0,
        "hit": 0,
        "parse_hit": 0,
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
        "parse_total": 0,
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
        if st.get("parse_hit") is True:
            structured["parse_hit"] += 1
        if st.get("parse_hit") is not None:
            structured["parse_total"] += 1

    indicator = {"n": 0, "hit": 0, "value_match": 0, "value_total": 0}
    for item in results:
        ind = item.get("indicator")
        if ind is None:
            continue
        indicator["n"] += 1
        if ind.get("hit"):
            indicator["hit"] += 1
        if ind.get("value_match") is True:
            indicator["value_match"] += 1
        if ind.get("value_match") is not None:
            indicator["value_total"] += 1

    if no_answer["n"]:
        effective = no_answer["n"] - no_answer["engine_error"]
        no_answer["empty_rate"] = (
            round(no_answer["empty"] / effective, 3) if effective > 0 else None
        )

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
    generation["material_complete"] = sum(
        1
        for item in results
        if item.get("generation")
        and item["generation"].get("material_n")
        and item["generation"].get("material_hit")
        == item["generation"].get("material_n")
    )

    route = {"n": 0, "hit": 0}
    for item in results:
        rt = item.get("route")
        if rt is None:
            continue
        route["n"] += 1
        if rt.get("hit"):
            route["hit"] += 1
    if route["n"]:
        route["accuracy"] = round(route["hit"] / route["n"], 3)
        route["wrong_tool_rate"] = round(1.0 - route["hit"] / route["n"], 3)

    year_filter = {"n": 0, "precision_sum": 0.0, "empty": 0}
    for item in results:
        yf = item.get("year_filter")
        if yf is None:
            continue
        year_filter["n"] += 1
        prec = yf.get("precision")
        if prec is None:
            year_filter["empty"] += 1
        else:
            year_filter["precision_sum"] += float(prec)
    if year_filter["n"]:
        scored = year_filter["n"] - year_filter["empty"]
        year_filter["precision_mean"] = (
            round(year_filter["precision_sum"] / scored, 3) if scored else None
        )

    return {
        "retrieval": retrieval,
        "retrieval_diag": retrieval_diag,
        "structured": structured,
        "indicator": indicator,
        "no_answer": no_answer,
        "generation": generation,
        "route": route,
        "year_filter": year_filter,
    }


def _finalize_retrieval(ret_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    retrieval: dict[str, Any] = {}
    for typ, s in ret_stats.items():
        n = s["n"]
        retrieval[typ] = {
            "n": n,
            "recall_at_k": round(s["hit"] / n, 3) if n else 0.0,
            "recall_at_k_ci": wilson_ci(s["hit"], n),
            "recall_soft_at_k": (
                round((s["hit"] + 0.5 * s["near_miss"]) / n, 3) if n else 0.0
            ),
            "near_miss_n": s["near_miss"],
            "hit_at_1": round(s["hit1"] / n, 3) if n else 0.0,
            "mrr": round(s["rr_sum"] / n, 3) if n else 0.0,
            "ndcg": round(s["ndcg_sum"] / n, 3) if n else 0.0,
            "precision_at_k": round(s["prec_sum"] / n, 3) if n else 0.0,
            "negative_hit_rate": round(s["neg_hit"] / n, 3) if n else 0.0,
            "negative_at_1_rate": round(s["neg_at_1"] / n, 3) if n else 0.0,
            "hybrid_fused_n": s["fused_n"],
            "error_tags": s["error_tags"],
        }
        if s.get("annual_n"):
            retrieval[typ]["annual_n"] = s["annual_n"]
            retrieval[typ]["annual_recall_at_k"] = round(
                s["annual_hit"] / s["annual_n"], 3
            )
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
            "recall_at_k_ci": wilson_ci(
                sum(s["hit"] for s in ret_stats.values()), n
            ),
            "hybrid_fused_n": sum(s["fused_n"] for s in ret_stats.values()),
            "error_tags": _merge_tag_counts(
                s["error_tags"] for s in ret_stats.values()
            ),
        }
        annual_n = sum(s.get("annual_n", 0) for s in ret_stats.values())
        if annual_n:
            retrieval["total"]["annual_n"] = annual_n
            retrieval["total"]["annual_recall_at_k"] = round(
                sum(s.get("annual_hit", 0) for s in ret_stats.values()) / annual_n, 3
            )
    return retrieval


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
    lines.append(f"- search_path：{meta.get('search_path', '-')}")
    if meta.get("split"):
        lines.append(f"- split：{meta['split']}")
    lines.append(f"- 耗时：{meta.get('duration_seconds', '-')} 秒")
    if meta.get("db_size_bytes"):
        lines.append(f"- DB 大小：{meta['db_size_bytes']} bytes")
    if meta.get("db_mtime"):
        lines.append(f"- DB mtime：{meta['db_mtime']}")
    lines.append("")
    lines.append("## 检索（Retrieval）")
    lines.append("")
    lines.append(
        "| 类型 | 数量 | Recall@k | Recall CI | Hit@1 | MRR | nDCG | Precision@k | Neg@k | Neg@1 | fused |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for typ, s in data["summary"].get("retrieval", {}).items():
        ci = s.get("recall_at_k_ci") or ["-", "-"]
        ci_cell = f"{ci[0]}–{ci[1]}" if isinstance(ci, (list, tuple)) and len(ci) == 2 else "-"
        lines.append(
            f"| {typ} | {s['n']} | {s['recall_at_k']} | {ci_cell} | {s['hit_at_1']} | "
            f"{s['mrr']} | {s['ndcg']} | {s['precision_at_k']} | "
            f"{s['negative_hit_rate']} | {s['negative_at_1_rate']} | "
            f"{s.get('hybrid_fused_n', 0)} |"
        )
    lines.append("")
    lines.append(
        "> Neg@k：前 k 条中出现任一负样本的题目比例；Neg@1：第 1 条命中负样本的题目比例。"
        "fused：该题 hybrid 实际走了向量融合的题数（短术语会短路回 FTS）。"
        "Recall CI 为 Wilson 95% 区间，仅展示，不当门禁。"
    )
    error_rows = []
    for typ, s in data["summary"].get("retrieval", {}).items():
        tags = s.get("error_tags") or {}
        if tags and typ != "total":
            error_rows.append(f"- {typ}：" + "，".join(f"{k}={v}" for k, v in sorted(tags.items())))
    if error_rows:
        lines.append("")
        lines.append("错误分类计数（一题可多标签）：")
        lines.extend(error_rows)
    lines.append("")
    lines.append("## 结构化三表（Structured）")
    lines.append("")
    lines.append("| 数量 | Hit | Parse | Field | Value | Source | Page | Unit | Currency |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
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
    parse_cell = (
        f"{st.get('parse_hit', 0)}/{st.get('parse_total', 0)}"
        if st.get("parse_total")
        else "0/0"
    )
    lines.append(
        f"| {st.get('n', 0)} | {st.get('hit', 0)} | {parse_cell} | "
        f"{st.get('field_match', 0)} | "
        f"{st.get('value_match', 0)} | {st.get('source_match', 0)} | "
        f"{st.get('page_match', 0)} | {unit_cell} | {currency_cell} |"
    )
    lines.append("")
    lines.append(
        "> Parse 为 L1（golden 值出现在指定页的 statements）；Hit 为 L3（科目词+值+来源查询命中）。"
    )
    lines.append("")
    ind = data["summary"].get("indicator") or {}
    if ind.get("n"):
        lines.append("## 指标（Indicators）")
        lines.append("")
        lines.append(
            f"- n={ind.get('n')} hit={ind.get('hit')} "
            f"value={ind.get('value_match')}/{ind.get('value_total')}"
        )
        lines.append("")
    na = data["summary"].get("no_answer") or {}
    if na.get("n"):
        lines.append("## 无答案（no_answer）")
        lines.append("")
        lines.append(
            f"- n={na.get('n')} empty={na.get('empty')} nonempty={na.get('nonempty')} "
            f"empty_rate={na.get('empty_rate')}"
        )
        lines.append("")
    route = data["summary"].get("route") or {}
    if route.get("n"):
        lines.append("## 工具路由（route）")
        lines.append("")
        lines.append(
            f"- n={route.get('n')} hit={route.get('hit')} "
            f"accuracy={route.get('accuracy')} "
            f"wrong_tool_rate={route.get('wrong_tool_rate')}"
        )
        lines.append("")
    yf = data["summary"].get("year_filter") or {}
    if yf.get("n"):
        lines.append("## 年份过滤（year_filter）")
        lines.append("")
        lines.append(
            f"- n={yf.get('n')} precision_mean={yf.get('precision_mean')} "
            f"empty={yf.get('empty')}"
        )
        lines.append("")
    diag = data["summary"].get("retrieval_diag") or {}
    if diag:
        lines.append("## 诊断集检索（split=diag）")
        lines.append("")
        lines.append("| 类型 | 数量 | Recall@k | Neg@k |")
        lines.append("|---|---|---|---|")
        for typ, s in diag.items():
            lines.append(
                f"| {typ} | {s['n']} | {s['recall_at_k']} | {s['negative_hit_rate']} |"
            )
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
            tags = ",".join(r.get("error_tags") or []) or "-"
            fused = r.get("hybrid_fused")
            lines.append(
                f"- **{item['id']}** {item.get('question')}（命中={r.get('hit')}，"
                f"负样本命中={r.get('negative_hit_at_k')}，负样本位次={r.get('negative_ranks')}，"
                f"fused={fused}，tags={tags}）"
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
