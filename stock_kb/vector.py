from __future__ import annotations

import hashlib
import os
import re
import sysconfig
import time
from pathlib import Path
from typing import Any

from stock_kb import db, search


MODEL_DIMS: dict[str, int] = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-m3": 1024,
    "jinaai/jina-embeddings-v2-base-zh": 768,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "intfloat/multilingual-e5-large": 1024,
}

CHUNK_SIZE = 800
_EMBEDDER_CACHE: dict[tuple[str, str], object] = {}

_BILINGUAL = (
    ("翻台率", "table turnover"),
    ("同店", "same-store"),
    ("客单价", "average spend"),
    ("减值", "impairment"),
    ("已付股息", "dividends paid"),
    ("资本开支", "capital expenditure"),
    ("师徒", "apprentice"),
    ("外卖", "delivery"),
    ("归母", "attributable to owners"),
)
# 口语改写 → 财报/研报用词。只拼进 embedding 查询，不改 FTS、不改 needles。
_EMBED_ALIASES = (
    ("真金白银", "经营现金流 现金流质量"),
    ("座位周转", "翻台率"),
    ("坐得转", "翻台率"),
    ("转不转", "翻台率"),
    ("来得勤", "翻台率 同店"),
    ("勤不勤", "翻台率"),
    ("来得频", "翻台率 同店"),
    ("频不频", "翻台率"),
    ("一餐花", "客单价"),
    ("打下去", "降本增效 费用"),
    ("按住", "费用管控"),
    ("撑场面", "多品牌"),
    ("送到家", "外卖 delivery"),
    ("不到店", "外卖 外送"),
    ("店点单", "外卖 数字化"),
    ("热饮", "咖啡 KCOFFEE"),
    ("薄不薄", "利润率 经营利润"),
    ("好转", "改善 经营利润"),
    ("赚一块钱能剩", "净利率"),
    ("店铺到", "门店数量 天花板"),
    ("带出店", "师徒制"),
    ("再来", "同店销售"),
    ("快餐店", "同店"),
    ("竞争格局", "市场份额"),
    ("拿回现金", "股息 回购 分红"),
)


def _expand_bilingual(query: str) -> str:
    """Add aliases for embedding only; FTS/needles stay original."""
    extra: list[str] = []
    qlow = query.lower()
    seen = {query, qlow}

    def _add(token: str) -> None:
        tok = token.strip()
        if not tok:
            return
        key = tok.lower()
        if key in seen or tok in seen:
            return
        extra.append(tok)
        seen.add(key)
        seen.add(tok)

    for zh, en in _BILINGUAL:
        en_l = en.lower()
        if zh in query and en_l not in qlow:
            _add(en)
        elif en_l in qlow and zh not in query:
            _add(zh)
    for src, dst in _EMBED_ALIASES:
        if src in query or src.lower() in qlow:
            for tok in dst.split():
                _add(tok)
    if not extra:
        return query
    return query + " " + " ".join(extra)


def _chunk_size(cfg: dict[str, Any] | None = None) -> int:
    if cfg:
        raw = (cfg.get("embedding") or {}).get("chunk_size")
        if raw is not None:
            return int(raw)
    return CHUNK_SIZE


def get_embedder(model: str, cache_dir: str, backend: str = "auto"):
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    if model == "BAAI/bge-m3":
        key = ("m3", model)
        if key not in _EMBEDDER_CACHE:
            _EMBEDDER_CACHE[key] = _M3Embedder(model, cache_dir)
        return _EMBEDDER_CACHE[key]
    if backend == "auto":
        try:
            import torch

            backend = "sentence-transformers" if torch.cuda.is_available() else "fastembed"
        except Exception:
            backend = "fastembed"
    if backend == "sentence-transformers":
        key = ("sentence-transformers", model)
    else:
        key = ("fastembed", model)
    if key not in _EMBEDDER_CACHE:
        if backend == "sentence-transformers":
            _EMBEDDER_CACHE[key] = _STEmbedder(model, cache_dir)
        else:
            _EMBEDDER_CACHE[key] = _FEEmbedder(model, cache_dir)
    return _EMBEDDER_CACHE[key]


class _M3Embedder:
    def __init__(self, model: str, cache_dir: str):
        model_dir = Path(cache_dir) / "models--BAAI--bge-m3"
        if model_dir.exists():
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from FlagEmbedding import BGEM3FlagModel

        import torch

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        snap_dir = model_dir / "snapshots"
        snaps = sorted(snap_dir.iterdir()) if snap_dir.exists() else []
        local_model = str(snaps[0]) if snaps else model
        self.model = BGEM3FlagModel(local_model, use_fp16=True, devices=device)

    def embed(self, texts):
        texts = list(texts)
        for i in range(0, len(texts), 64):
            out = self.model.encode(
                texts[i : i + 64], batch_size=64, max_length=8192
            )
            for v in out["dense_vecs"]:
                yield v


class _STEmbedder:
    def __init__(self, model: str, cache_dir: str):
        model_dir = Path(cache_dir) / f"models--{model.replace('/', '--')}"
        if model_dir.exists():
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer

        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(
            model, cache_folder=cache_dir, device=device
        )

    def embed(self, texts):
        vecs = self.model.encode(
            list(texts),
            normalize_embeddings=True,
            batch_size=256,
            show_progress_bar=False,
        )
        yield from vecs


class _FEEmbedder:
    def __init__(self, model: str, cache_dir: str):
        from fastembed import TextEmbedding

        _add_nvidia_dll_dirs()
        providers = None
        try:
            import onnxruntime as ort

            if "CUDAExecutionProvider" in ort.get_available_providers():
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:
            pass
        self.model = TextEmbedding(
            model_name=model, cache_dir=cache_dir, providers=providers
        )

    def embed(self, texts):
        yield from self.model.embed(texts)


def _add_nvidia_dll_dirs() -> None:
    base = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    if not base.exists():
        return
    for d in base.glob("*/bin"):
        try:
            os.add_dll_directory(str(d))
        except Exception:
            pass
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def _serialize_vector(vec: Any) -> bytes:
    import numpy as np

    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def _vec_table_name(model: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", model).strip("_")[:48] or "model"
    digest = hashlib.sha1(model.encode("utf-8")).hexdigest()[:8]
    return f"chunks_vec_{slug}_{digest}"


def _model_vec_table(conn, model: str, dim: int) -> str:
    row = conn.execute(
        "SELECT vec_table FROM embedding_index WHERE model=? AND vec_table IS NOT NULL LIMIT 1",
        (model,),
    ).fetchone()
    if row:
        return str(row["vec_table"])
    return _vec_table_name(model)


def _split_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    chunks: list[str] = []
    buf = ""
    for line in lines:
        if len(line) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            start = 0
            while start < len(line):
                end = min(start + size, len(line))
                chunks.append(line[start:end])
                start = end
            continue
        if buf and len(buf) + len(line) + 1 > size:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks


def _ensure_chunks(conn, size: int = CHUNK_SIZE) -> None:
    rows = conn.execute(
        """
        SELECT p.id AS page_id, p.content FROM pages p
        LEFT JOIN (SELECT DISTINCT page_id FROM chunks) c ON c.page_id = p.id
        WHERE c.page_id IS NULL ORDER BY p.id
        """
    ).fetchall()
    for r in rows:
        for no, chunk in enumerate(_split_chunks(r["content"] or "", size=size)):
            conn.execute(
                "INSERT OR IGNORE INTO chunks(page_id, chunk_no, content) VALUES(?,?,?)",
                (r["page_id"], no, chunk),
            )
    conn.commit()


def _reset_chunks(conn) -> None:
    """删除全部分块与全部模型的向量。chunk_id 会变，其它模型必须重嵌。"""
    conn.execute("DELETE FROM embedding_index")
    names = db.vector_table_names(conn)
    if names:
        db.load_vector_extension(conn)
        for table in names:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("DELETE FROM chunks")
    conn.commit()


def _index_stats(
    conn,
    *,
    size: int,
    indexed: int,
    total: int,
    cleared_models: list[str] | None = None,
) -> dict[str, Any]:
    n_chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    out: dict[str, Any] = {
        "indexed": indexed,
        "total": total,
        "chunk_size": size,
        "chunks": n_chunks,
    }
    if cleared_models is not None:
        out["cleared_models"] = cleared_models
    return out


def build_index(
    cfg: dict[str, Any],
    model: str,
    limit: int | None = None,
    rebuild: bool = False,
    rebuild_chunks: bool = False,
) -> dict[str, Any]:
    conn = db.connect(cfg["db_path"])
    db.load_vector_extension(conn)
    dim = MODEL_DIMS.get(model)
    if not dim:
        raise ValueError(f"不支持的模型维度映射: {model}")

    size = _chunk_size(cfg)
    existing = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(LENGTH(content)), 0) AS max_len FROM chunks"
    ).fetchone()
    if existing["n"] and existing["max_len"] > size and not rebuild_chunks:
        print(
            f"[index] warning: existing chunks max_len={existing['max_len']} > chunk_size={size}; "
            "pass --rebuild-chunks to re-split (this clears ALL models)",
            flush=True,
        )

    cleared_models: list[str] | None = None
    if rebuild_chunks:
        cleared_models = [
            str(r[0])
            for r in conn.execute("SELECT DISTINCT model FROM embedding_index").fetchall()
        ]
        print(
            f"[index] rebuild_chunks size={size} cleared_models={cleared_models}",
            flush=True,
        )
        _reset_chunks(conn)
    elif rebuild:
        row = conn.execute(
            "SELECT vec_table FROM embedding_index WHERE model=? AND vec_table IS NOT NULL LIMIT 1",
            (model,),
        ).fetchone()
        old_table = str(row["vec_table"]) if row else None
        conn.execute("DELETE FROM embedding_index WHERE model=?", (model,))
        if old_table:
            conn.execute(f"DROP TABLE IF EXISTS {old_table}")
        conn.commit()

    table = _model_vec_table(conn, model, dim)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
    )

    _ensure_chunks(conn, size=size)

    rows = conn.execute(
        """
        SELECT c.id AS chunk_id, c.content, c.page_id FROM chunks c
        LEFT JOIN embedding_index ei ON ei.chunk_id = c.id AND ei.model = ?
        WHERE ei.chunk_id IS NULL
        ORDER BY c.id
        """,
        (model,),
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        stats = _index_stats(
            conn, size=size, indexed=0, total=0, cleared_models=cleared_models
        )
        conn.close()
        return stats

    embedder = get_embedder(
        model, cfg["models_dir"], backend=cfg.get("embedding", {}).get("backend", "auto")
    )
    batch = 64
    indexed = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        texts = [(r["content"] or "")[:4000] for r in chunk]
        vectors = list(embedder.embed(texts))
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for row, vec in zip(chunk, vectors):
            conn.execute(
                f"INSERT OR REPLACE INTO {table}(chunk_id, embedding) VALUES(?, ?)",
                (row["chunk_id"], _serialize_vector(vec)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO embedding_index(model, chunk_id, dim, vec_table, indexed_at) "
                "VALUES(?,?,?,?,?)",
                (model, row["chunk_id"], dim, table, now),
            )
            indexed += 1
        conn.commit()
        print(f"[index] {indexed}/{len(rows)}", flush=True)
    stats = _index_stats(
        conn, size=size, indexed=indexed, total=len(rows), cleared_models=cleared_models
    )
    conn.close()
    return stats


def vector_search(
    conn,
    model: str,
    query: str,
    top_k: int = 5,
    company: str | None = None,
    cache_dir: str | None = None,
    backend: str = "auto",
    year: int | None = None,
    report_type: str | None = None,
    language: str | None = None,
    candidate_k: int | None = None,
) -> list[dict[str, Any]]:
    query = search.normalize_query(query)
    if not query:
        return []
    embed_query = _expand_bilingual(query)
    implied_years = search.query_years(query) if year is None else []
    if implied_years and search.years_out_of_corpus(conn, query, company):
        return []
    allowed_years = {year} if year is not None else (set(implied_years) or None)
    needles = search.claim_needles(query, company)
    row = conn.execute(
        "SELECT dim, vec_table FROM embedding_index WHERE model=? LIMIT 1", (model,)
    ).fetchone()
    if not row:
        return []
    db.load_vector_extension(conn)
    dim = int(row["dim"])
    table = row["vec_table"] or f"chunks_vec_{dim}"
    if not cache_dir:
        return []
    embedder = get_embedder(model, cache_dir, backend=backend)
    vec = next(embedder.embed([embed_query]))
    has_filters = any(
        v is not None for v in (company, year, report_type, language)
    ) or bool(allowed_years)
    chunk_limit = candidate_k or (top_k * 10 if has_filters else top_k * 5)
    hits = conn.execute(
        f"SELECT chunk_id, distance FROM {table} "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (_serialize_vector(vec), chunk_limit),
    ).fetchall()
    best: dict[int, dict[str, Any]] = {}
    for h in hits:
        r = conn.execute(
            f"""
            SELECT p.id AS page_id, p.page_no, p.report_id, r.company, r.title, r.path,
                   r.year, r.report_type, r.language, c.content
            FROM chunks c JOIN pages p ON p.id = c.page_id
            JOIN reports r ON r.id = p.report_id
            WHERE c.id=? AND {db.live_report_sql("r")}
              AND COALESCE(p.is_ocr, 0) < 2
            """,
            (h["chunk_id"],),
        ).fetchone()
        if not r:
            continue
        if company is not None and r["company"] != company:
            continue
        if allowed_years is not None and r["year"] not in allowed_years:
            continue
        if report_type is not None and r["report_type"] != report_type:
            continue
        if language is not None and r["language"] != language:
            continue
        if not _content_has_needle(r["content"] or "", needles):
            continue
        cur = best.get(r["page_id"])
        if cur is None or h["distance"] < cur["score"]:
            best[r["page_id"]] = {
                "page_id": r["page_id"],
                "page_no": r["page_no"],
                "report_id": r["report_id"],
                "company": r["company"],
                "title": r["title"],
                "path": r["path"],
                "year": r["year"],
                "report_type": r["report_type"],
                "language": r["language"],
                "score": float(h["distance"]),
                "source": "vector",
                "snippet": (r["content"] or "")[:160],
            }
    out = sorted(best.values(), key=lambda x: x["score"])
    return out[:top_k]


def _content_has_needle(content: str, needles: list[str]) -> bool:
    if not needles:
        return True
    return any(n in content for n in needles)


def hybrid_search(
    conn,
    query: str,
    model: str,
    top_k: int = 5,
    company: str | None = None,
    cache_dir: str | None = None,
    backend: str = "auto",
    year: int | None = None,
    report_type: str | None = None,
    language: str | None = None,
    fts_weight: float = 1.0,
    vec_weight: float = 1.0,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    query = search.normalize_query(query)
    if not query:
        return []
    # 短术语（<6 个字符）以关键词命中为准，向量容易引入同义噪音；
    # 但 FTS 零命中时仍走向量融合兜底，避免经营叙述类短查询直接空手而归。
    did_fuse = len(query) >= 6
    if not did_fuse:
        hits = search.fts_search(
            conn,
            query,
            company=company,
            top_k=top_k,
            year=year,
            report_type=report_type,
            language=language,
        )
        if hits:
            for h in hits:
                h["source"] = "hybrid"
                h["hybrid_fused"] = False
            return hits

    candidate_k = max(top_k * 4, 20)
    fts = search.fts_search(
        conn,
        query,
        company=company,
        top_k=candidate_k,
        year=year,
        report_type=report_type,
        language=language,
    )
    vec = vector_search(
        conn,
        model,
        query,
        top_k=candidate_k,
        company=company,
        cache_dir=cache_dir,
        backend=backend,
        year=year,
        report_type=report_type,
        language=language,
    )

    fused: dict[int, dict[str, Any]] = {}
    for pos, h in enumerate(fts, start=1):
        page_id = h["page_id"]
        item = fused.setdefault(
            page_id,
            {k: v for k, v in h.items() if k != "rank"},
        )
        item["_rrf"] = item.get("_rrf", 0.0) + fts_weight / (pos + rrf_k)
        item["fts_rank"] = pos
        item["snippet"] = h.get("snippet") or item.get("snippet")
        item["source"] = "hybrid"
    for pos, h in enumerate(vec, start=1):
        page_id = h["page_id"]
        item = fused.setdefault(page_id, dict(h))
        item["_rrf"] = item.get("_rrf", 0.0) + vec_weight / (pos + rrf_k)
        item["vec_rank"] = pos
        item["source"] = "hybrid"

    out = sorted(
        fused.values(),
        key=lambda x: (-x.get("_rrf", 0.0), x.get("score", 1e9)),
    )[:top_k]
    for item in out:
        item["fusion_score"] = round(item.get("_rrf", 0.0), 6)
        item["hybrid_fused"] = True
        item.pop("_rrf", None)
    return out
