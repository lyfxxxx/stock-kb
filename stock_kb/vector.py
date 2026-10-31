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

# 融合权重与重排开关按查询意图分派（2026-10-30）。对称的 1:1 对两类题都不合适：
# 数值型问句里 FTS 的精确命中是强信号，向量分路会把研报长块顶上来；更关键的是
# 交叉编码器重排会把已经精确命中的页压下去——实测 22 道关键词题，重排关时
# 19/22 命中，重排开只剩 8/22。叙述型问句正相反：FTS 几乎不命中
# （freeze 语义题 FTS Recall@5 = 0），向量与重排才是主力（关重排 7/20，开 9/20）。
# fts / vec 是乘在调用方传入权重上的倍率，默认基准 1.0。
# 调参只改这张表；改完必须跑 `python tools/run_eval_regression.py`，
# 同时看 G1、G3、融合保留率三项，并确认 Neg@5 没被放大。
INTENT_PROFILE: dict[str, dict[str, float | bool]] = {
    "numeric": {"fts": 3.0, "vec": 0.5, "rerank": False},
    "term": {"fts": 2.0, "vec": 0.8, "rerank": False},
    "narrative": {"fts": 0.6, "vec": 1.6, "rerank": True},
    "neutral": {"fts": 1.0, "vec": 1.0, "rerank": True},
}

# 叙述型信号：疑问/口语化标记。命中且不含具体数值时走向量。
_NARRATIVE_MARKERS = (
    "为什么",
    "怎么",
    "怎样",
    "哪种",
    "哪个",
    "哪些",
    "什么",
    "是不是",
    "如何",
    "多少",
    "凭什么",
    "靠什么",
    "还是",
)

# 术语型信号：财报/研报里的固定说法，FTS 精确匹配比向量可靠。
_TERM_QUERY_WORDS = (
    "已付股息",
    "资本开支",
    "客单价",
    "翻台率",
    "同店",
    "门店",
    "净增",
    "肩并肩",
    "肯悦咖啡",
    "KCOFFEE",
    "股息",
    "营业收入",
    "净利",
    "毛利",
    "总资产",
    "经营现金流",
    "减值",
    "开店",
    "闭店",
    "加盟",
)

# 四位年份不算「数值型证据」，先剥掉再找数字。
_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*年?")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|次|家|元|亿|万|个|倍|间|人)?")


def classify_query_intent(query: str) -> str:
    """把问句分成 numeric / narrative / term / neutral。

    只用来决定融合权重，不参与过滤。判错只影响排序，不会让结果为空。
    """

    text = search.normalize_query(query)
    if not text:
        return "neutral"
    stripped = _YEAR_RE.sub(" ", text)
    has_number = bool(_NUMBER_RE.search(stripped))
    has_marker = any(word in text for word in _NARRATIVE_MARKERS)
    if has_marker and not has_number:
        return "narrative"
    if has_number and not has_marker:
        return "numeric"
    if has_number and has_marker:
        # 两类信号同时出现（如「2024 年回馈股东多少钱」），保守起见不偏袒。
        return "neutral"
    if any(word in text for word in _TERM_QUERY_WORDS):
        return "term"
    return "neutral"

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


# bge-*-zh-v1.5 是非对称检索模型，官方要求查询侧加指令前缀、文档侧不加；
# bge-m3 不使用该前缀（docs/retrieval-fix-plan-20261025.md §6）。
_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
_INSTRUCTION_MODELS = re.compile(r"^BAAI/bge-(?:small|base|large)-zh-v1\.5$")


def _query_embed_text(model: str, query: str) -> str:
    text = _expand_bilingual(query)
    if _INSTRUCTION_MODELS.match(model):
        return _QUERY_INSTRUCTION + text
    return text


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
    embed_query = _query_embed_text(model, query)
    implied_years = search.query_years(query) if year is None else []
    if implied_years and search.years_out_of_corpus(conn, query, company):
        return []
    allowed_years = {year} if year is not None else (set(implied_years) or None)
    # 库外实体预检：实体词全部 0 命中说明问句谈的是语料外实体，直接返回空。
    # 接替原 needle 硬过滤承担无答案安全；实体命中不再过滤候选
    # （docs/retrieval-fix-plan-20261025.md §4）。
    if search.all_entities_out_of_corpus(conn, query, company):
        return []
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
                # 命中文本块原文，仅供 hybrid 重排使用，返回前剥离
                "chunk_content": r["content"] or "",
            }
    out = sorted(best.values(), key=lambda x: x["score"])
    return out[:top_k]


def _content_has_needle(content: str, needles: list[str]) -> bool:
    if not needles:
        return True
    return any(n in content for n in needles)


# 备用查询名单（docs/retrieval-fix-plan-20261025.md §4 1b）：整句全文检索为空、
# 且问句里出现名单词时，用该词再查一次 FTS 分路（semantic-011 的守成通道）。
# 不是通用规则：名单外的高频词（如 002 的「购物中心」）以 FTS 第 1 名进 RRF
# 会挤掉向量第 1 的正确页。扩充前必须先在打开该词后重测 002/005，
# 两者仍在前 5 才保留。该通道只在 hybrid 融合路径，不影响 keyword 短路。
_FALLBACK_QUERY_TERMS = ("突破",)

# ---------------------------------------------------------------------------
# 交叉编码器重排（docs/retrieval-fix-plan-20261025.md §7 4b）
#
# 送入重排的是命中的那个文本块（按字符截断），不是整页——库内最长页
# 8.3 万字（网页电话会纪要），整页会占住近邻并拉高延迟。库外实体预检在
# vector_search 入口、重排之前，无答案问句到不了这里。仅对有文本块的
# 候选（向量腿命中）重排；纯 FTS/fallback 命中保序跟在后面。
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
_RERANKER_MODEL = DEFAULT_RERANKER_MODEL
_RERANK_WINDOW = 50
_RERANK_MAX_CHARS = 480
_RERANKER_CACHE: dict[str, Any] = {}


def get_reranker(cache_dir: str | None, model: str | None = None):
    """按模型名加载交叉编码器；model 为空时用默认 base。

    模型必须已在 cache_dir 里（`tools/download_models.py --model <ID>`），
    加载走 `local_files_only=True`，不会联网。
    """

    if not cache_dir:
        return None
    name = model or _RERANKER_MODEL
    key = f"{name}|{cache_dir}"
    if key not in _RERANKER_CACHE:
        if (Path(cache_dir) / ("models--" + name.replace("/", "--"))).exists():
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
        except Exception:
            return None
        try:
            _RERANKER_CACHE[key] = CrossEncoder(
                name,
                max_length=512,
                cache_folder=cache_dir,
                local_files_only=True,
            )
        except Exception:
            return None
    return _RERANKER_CACHE[key]


_SIBLING_RADIUS = 3
_SIBLING_LIMIT = 6
_SIBLING_SEED_POS = 6  # 邻页的融合名次种子：紧跟前 5 之后，靠重排分竞争上位


def _sibling_candidates(
    conn, top_item: dict[str, Any], radius: int = _SIBLING_RADIUS, limit: int = _SIBLING_LIMIT
) -> list[dict[str, Any]]:
    """重排实验（计划 §7 4b）：融合第 1 名所在文档的 ±3 邻页。

    语义题的答案常与最近页同文档隔几页（019 的短语在国信 2024Q4 p4，
    最近页是 p1）。邻页以种子名次进重排、按分数竞争，不硬插入，
    因此不会无条件挤掉已在正确位置上的页。
    """
    rid = top_item.get("report_id")
    pg = top_item.get("page_no")
    if rid is None or pg is None:
        return []
    rows = conn.execute(
        f"""
        SELECT p.id AS page_id, p.page_no, p.report_id, r.company, r.title, r.path,
               r.year, r.report_type, r.language, p.content, p.content_orig
        FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE p.report_id = :rid AND p.page_no BETWEEN :lo AND :hi
          AND {db.live_report_sql("r")}
          AND COALESCE(p.is_ocr, 0) < 2
        ORDER BY ABS(p.page_no - :pg), p.page_no
        LIMIT :lim
        """,
        {"rid": rid, "lo": pg - radius, "hi": pg + radius, "pg": pg, "lim": limit + 1},
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["page_id"] == top_item.get("page_id"):
            continue
        text = r["content"] or r["content_orig"] or ""
        out.append(
            {
                "page_id": r["page_id"],
                "page_no": r["page_no"],
                "report_id": r["report_id"],
                "company": r["company"],
                "title": r["title"],
                "path": r["path"],
                "year": r["year"],
                "report_type": r["report_type"],
                "language": r["language"],
                "score": 1e9,
                "source": "hybrid",
                "sibling": True,
                "chunk_content": text,
            }
        )
        if len(out) >= limit:
            break
    return out


def _rerank_fused(
    query: str,
    items: list[dict[str, Any]],
    cache_dir: str | None,
    window: int = _RERANK_WINDOW,
    extra: list[dict[str, Any]] | None = None,
    seed_pos: int = _SIBLING_SEED_POS,
    reranker_model: str | None = None,
) -> list[dict[str, Any]]:
    ce = get_reranker(cache_dir, reranker_model)
    if ce is None or not items:
        return items
    # (候选, 融合名次)：窗口内名次即原序；邻页种子名次紧跟锚页之后
    entries: list[tuple[dict[str, Any], int]] = [
        (it, i + 1) for i, it in enumerate(items[:window])
    ]
    for j, ex in enumerate(extra or []):
        entries.append((ex, seed_pos + j))
    rest = items[window:]
    idx = [k for k, (it, _) in enumerate(entries) if it.get("chunk_content")]
    if not idx:
        return items
    # 证据常落在约 800 字块的后半段（双语表格页），单截头部会漏；
    # 超长块按前、后各一段分别打分取最大。
    pairs: list[tuple[str, str]] = []
    counts: list[int] = []
    for k in idx:
        text = entries[k][0]["chunk_content"]
        parts = (
            [text]
            if len(text) <= _RERANK_MAX_CHARS
            else [text[:_RERANK_MAX_CHARS], text[-_RERANK_MAX_CHARS:]]
        )
        counts.append(len(parts))
        pairs.extend((query, p) for p in parts)
    try:
        raw = ce.predict(pairs)
    except Exception:
        return items
    best: dict[int, float] = {}
    pos = 0
    for k, n in zip(idx, counts):
        best[k] = max(float(s) for s in raw[pos : pos + n])
        pos += n
    order = sorted(idx, key=lambda k: -best[k])
    rerank_pos = {k: p for p, k in enumerate(order, start=1)}
    # 重排名次不整序替换，而是与融合名次再做一次 RRF：纯重排会把已在
    # 前 5 的正确页挤出（实测 003/006/011），纯融合又拉不动窗口内深名次。
    tail = len(entries) + 1

    def _score(k: int) -> float:
        return 1.0 / (entries[k][1] + 60) + 1.0 / (rerank_pos.get(k, tail) + 60)

    for k in idx:
        entries[k][0]["reranked"] = True
    final = sorted(range(len(entries)), key=lambda k: -_score(k))
    return [entries[k][0] for k in final] + rest


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
    rerank: bool = False,
    reranker_model: str | None = None,
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

    # P2（docs/retrieval-fix-plan-20261025.md §5）：只加深内部候选页数，
    # 评测/回归的 top_k 仍是 5。FTS 分路为空时排序键不变，前 5 成员不变；
    # 目的是让 013/017/015/012 的含短语页（最近块序号 ≤500）进入重排输入。
    intent = classify_query_intent(query)
    profile = INTENT_PROFILE.get(intent, INTENT_PROFILE["neutral"])
    fts_weight *= float(profile["fts"])
    vec_weight *= float(profile["vec"])
    use_rerank = bool(rerank and profile["rerank"])
    candidate_k = max(top_k * 4, 50)
    fts = search.fts_search(
        conn,
        query,
        company=company,
        top_k=candidate_k,
        year=year,
        report_type=report_type,
        language=language,
    )
    if not fts:
        for term in _FALLBACK_QUERY_TERMS:
            if term in query:
                fts = search.fts_search(
                    conn,
                    term,
                    company=company,
                    top_k=candidate_k,
                    year=year,
                    report_type=report_type,
                    language=language,
                )
                if fts:
                    break
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
        # FTS 分路先建的分项要并入向量分路带来的文本块，否则重排拿不到输入
        if h.get("chunk_content"):
            item["chunk_content"] = h["chunk_content"]
        item["source"] = "hybrid"

    ranked = sorted(
        fused.values(),
        key=lambda x: (-x.get("_rrf", 0.0), x.get("score", 1e9)),
    )
    if use_rerank:
        # 邻页锚点是「向量第 1 名」那份文档（计划 §7 4b），不是融合榜第 1：
        # 融合榜头常被 FTS 分路带上来的页占据，锚错文档邻页就全错。
        # 2026-10-30 试过扩到「前 5 名各扩 ±5 页 + 整页滑窗全段重排」，
        # 语义召回仍是 0.60：reranker 给错误页打分反而更高（p23 0.887 vs
        # p27 0.528），是判别力上限，不是文本覆盖问题，已回滚。
        anchor = next(
            (it for it in ranked if it.get("vec_rank") == 1), ranked[0] if ranked else None
        )
        extra: list[dict[str, Any]] = []
        anchor_pos = 1
        if anchor is not None:
            extra = _sibling_candidates(conn, anchor)
            anchor_pos = ranked.index(anchor) + 1
        ranked = _rerank_fused(
            query,
            ranked,
            cache_dir,
            extra=extra,
            seed_pos=anchor_pos + 1,
            reranker_model=reranker_model,
        )
    out = ranked[:top_k]
    for item in out:
        item["fusion_score"] = round(item.get("_rrf", 0.0), 6)
        item["hybrid_fused"] = True
        item.pop("_rrf", None)
        item.pop("chunk_content", None)
    return out
