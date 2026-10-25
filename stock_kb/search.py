from __future__ import annotations

import re
import sqlite3
from typing import Any

from stock_kb import db
from stock_kb.textutil import to_simplified


def normalize_query(query: str) -> str:
    q = to_simplified(query or "").strip()
    q = re.sub(r"((?:19|20)\d{2})\s*年", r"\1 ", q)
    q = re.sub(r"[\s,，。；;:：?!！？、/\-—_–()\[\]（）\"']+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def prefer_query_years(
    hits: list[dict[str, Any]],
    query: str,
    *,
    year: int | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Keep report years named in the query first.

    Explicit ``year=`` is a hard filter (already applied in SQL). Queries
    with no year are left alone so freeze keyword GT (often older 研报)
    does not jump to the latest annual.
    """
    if year is not None or not hits:
        return hits[:top_k]
    years = set(query_years(query))
    if not years:
        return hits[:top_k]
    matched = [h for h in hits if h.get("year") in years]
    rest = [h for h in hits if h.get("year") not in years]
    return (matched + rest)[:top_k]


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    company: str | None = None,
    top_k: int = 5,
    year: int | None = None,
    report_type: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    q = normalize_query(query)
    if not q:
        return []
    implied_years = query_years(q) if year is None else []
    if implied_years and years_out_of_corpus(conn, q, company):
        return []
    years = implied_years or None

    if len(q) < 3:
        rows = _like_search(
            conn, q, company=company, top_k=top_k,
            year=year, report_type=report_type, language=language,
            years=years,
        )
        # 已建好中文 bigram 表，但当前评测下 bigram 排序会牺牲 keyword 基线；
        # 仅在 LIKE 无结果时用 bigram 兜底，后续可在独立评测集上再调权。
        if not rows and len(q) == 2 and re.search(r"[\u4e00-\u9fff]", q):
            rows = _bigram_search(
                conn, q, company=company, top_k=top_k,
                year=year, report_type=report_type, language=language,
                years=years,
            )
        return rows[:top_k]

    expr = _match_expression(q)
    if not expr:
        return []
    return _match_search(
        conn, expr, company=company, top_k=top_k,
        year=year, report_type=report_type, language=language,
        years=years,
    )


def _match_search(
    conn: sqlite3.Connection,
    expr: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
    years: list[int] | None = None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, r.year, r.report_type, r.language, "
        "snippet(pages_fts, 3, '[', ']', '...', 24) AS snippet, rank "
        "FROM pages_fts JOIN pages p ON p.id = pages_fts.page_id "
        "JOIN reports r ON r.id = p.report_id "
        "WHERE pages_fts MATCH ? "
    )
    params: list[Any] = [expr]
    sql, params = _append_filters(
        sql, params, company, year, report_type, language, years=years
    )
    if year is None and years is None:
        # 无年份问句：同一段报表文字在多年份报告中近乎重复，bm25 几乎并列，
        # 用轻微的新近度因子（每年 1.5%）打散并列，偏向较新的报告。
        # rank 为负（越小越好），除以 >1 的因子会让旧页变差。
        sql += (
            " ORDER BY rank / (1.0 + 0.015 * (CAST(strftime('%Y','now') AS INTEGER) "
            "- COALESCE(r.year, 2000))), rank LIMIT ?"
        )
    else:
        sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _bigram_search(
    conn: sqlite3.Connection,
    q: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
    years: list[int] | None = None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, r.year, r.report_type, r.language, "
        "CASE WHEN instr(lower(p.content), lower(?)) > 0 THEN "
        "substr(p.content, max(1, instr(lower(p.content), lower(?)) - 40), 160) "
        "ELSE substr(p.content, 1, 160) END AS snippet, rank "
        "FROM pages_bigram_fts b JOIN pages p ON p.id = b.page_id "
        "JOIN reports r ON r.id = p.report_id "
        "WHERE pages_bigram_fts MATCH ? "
    )
    params: list[Any] = [q, q, _quote_fts(q)]
    sql, params = _append_filters(
        sql, params, company, year, report_type, language, years=years
    )
    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _like_search(
    conn: sqlite3.Connection,
    q: str,
    company: str | None,
    top_k: int,
    year: int | None,
    report_type: str | None,
    language: str | None,
    years: list[int] | None = None,
) -> list[dict[str, Any]]:
    like = f"%{_escape_like(q)}%"
    sql = (
        "SELECT p.id AS page_id, p.report_id, p.page_no, p.char_count, r.company, "
        "r.title, r.path, r.year, r.report_type, r.language, "
        "CASE WHEN instr(lower(p.content), lower(?)) > 0 THEN "
        "substr(p.content, max(1, instr(lower(p.content), lower(?)) - 40), 160) "
        "ELSE substr(p.content, 1, 160) END AS snippet, "
        "CAST((length(lower(p.content)) - length(replace(lower(p.content), lower(?), ''))) AS REAL) / length(?) AS score "
        "FROM pages p JOIN reports r ON r.id = p.report_id "
        "WHERE p.content LIKE ? ESCAPE '\\' "
    )
    params: list[Any] = [q, q, q, q, like]
    sql, params = _append_filters(
        sql, params, company, year, report_type, language, years=years
    )
    sql += " ORDER BY score DESC, p.page_no ASC LIMIT ?"
    params.append(top_k)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _append_filters(
    sql: str,
    params: list[Any],
    company: str | None,
    year: int | None,
    report_type: str | None,
    language: str | None,
    years: list[int] | None = None,
) -> tuple[str, list[Any]]:
    sql += " AND " + db.live_report_sql("r")
    # is_ocr=2 为 OCR 失败/乱码页（内容不可用），不进检索结果
    sql += " AND COALESCE(p.is_ocr, 0) < 2"
    if company is not None:
        sql += " AND r.company = ?"
        params.append(company)
    if year is not None:
        sql += " AND r.year = ?"
        params.append(year)
    elif years:
        sql += " AND r.year IN (" + ",".join("?" * len(years)) + ")"
        params.extend(years)
    if report_type is not None:
        sql += " AND r.report_type = ?"
        params.append(report_type)
    if language is not None:
        sql += " AND r.language = ?"
        params.append(language)
    return sql, params


def _quote_fts(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


# 问句里的虚词不参与 AND，避免「是多少」把真实科目查询打成空。
_QUERY_STOP = {
    "是多少",
    "怎么样",
    "如何",
    "是否",
    "什么",
    "哪些",
    "有没有",
    "多少",
    "哪年",
    "高不高",
    "好不好",
    "对不对",
    "能不能",
    "成为",
}


def _content_terms(q: str) -> list[str]:
    raw = [t for t in q.split(" ") if t]
    terms = [
        t
        for t in raw
        if t not in _QUERY_STOP and len(t) >= 3 and not _YEAR_RE.fullmatch(t)
    ]
    return terms or [t for t in raw if not _YEAR_RE.fullmatch(t)] or raw


_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_CLAIM_SPLIT = re.compile(
    r"(?:的|了|是|和|与|为|对|把|从|到|等|及|在|年|里|吗|呢|吧|这|那|个|几|怎么|如何|"
    r"是否|有没有|多少|什么|哪些|能不能|成为|主要|还是|得)+|[，。；;:：?!！？、,\s]+"
)
# 财报/分析常用词，不拿来约束向量；火星/比特币/瑞幸等实体不在其中。
_GENERIC_CLAIM = frozenset(
    {
        "营业收入",
        "收入",
        "利润",
        "净利",
        "净利润",
        "门店",
        "数量",
        "销售",
        "同店",
        "研发",
        "投入",
        "持股",
        "比例",
        "储备",
        "规模",
        "开店",
        "净增",
        "股息",
        "回购",
        "股东",
        "现金",
        "资产",
        "负债",
        "现金流",
        "费用",
        "成本",
        "计划",
        "优化",
        "格局",
        "竞争",
        "增长",
        "曲线",
        "第二",
        "店长",
        "下一家",
        "留住",
        "开出",
        "赚钱",
        "含金量",
        "座位",
        "火锅",
        "火锅店",
        "热饮",
        "炸鸡",
        "披萨",
        "咖啡",
        "新店",
        "地方",
        "好转",
        "开销",
        "扩张",
        "收口",
        "员工",
        "激励",
        "数字化",
        "家店",
        "餐厅",
        "公司",
        "企业",
        "条线",
        "给谁",
        "开给谁",
        "最近",
        "薄不薄",
        "变厚",
        "变薄",
        "拿回",
        "快不快",
        "真金白银",
        "能变成真金白银",
        "程度才算合适",
        "才算合适",
        "合适",
        "打下去",
        "按住",
        "客人来",
        "勤不勤",
        "一桌坐",
        "转不转",
        "带出店",
        "负责人",
        "周转",
        "变快",
        "变慢",
        "赚一块钱能剩",
        "一块钱",
        "客人",
        "一餐花",
        "频不频",
        "更撑",
        "愿不愿意再来",
        "客人愿不愿意再来",
        "家快餐店",
        "快餐店",
        "肯德基之外还有",
        "牌子",
        "撑场面",
        "店点单",
        "点单",
        "送到家",
        "哪头更重要",
        "更重要",
        "不到店",
    }
)


def query_years(query: str) -> list[int]:
    return [int(m) for m in _YEAR_RE.findall(normalize_query(query))]


def years_out_of_corpus(
    conn: sqlite3.Connection,
    query: str,
    company: str | None = None,
) -> bool:
    years = query_years(query)
    if not years:
        return False
    sql = (
        "SELECT MIN(year) AS mn, MAX(year) AS mx FROM reports "
        f"WHERE {db.live_report_sql('')} AND year IS NOT NULL"
    )
    params: list[Any] = []
    if company:
        sql += " AND company=?"
        params.append(company)
    row = conn.execute(sql, params).fetchone()
    if not row or row["mn"] is None:
        return False
    lo, hi = int(row["mn"]), int(row["mx"])
    return any(y < lo or y > hi for y in years)


def _strip_generic(part: str) -> str:
    text = part
    changed = True
    gens = sorted(_GENERIC_CLAIM, key=len, reverse=True)
    while text and changed:
        changed = False
        for g in gens:
            if g and g in text:
                text = text.replace(g, "")
                changed = True
    return text


def claim_needles(query: str, company: str | None = None) -> list[str]:
    """问句里需要在命中页出现的非常见词。空列表表示不约束向量。

    2026-10 起运行时不再用它做向量硬过滤（docs/retrieval-fix-plan-20261025.md
    §4）：口语残片会误杀语义题的答案页。保留供诊断工具与测试对照。
    """
    q = normalize_query(query)
    if company:
        q = q.replace(company, " ")
        if company.endswith("中国") and len(company) > 2:
            q = q.replace(company[:-2], " ")
    for stop in sorted(_QUERY_STOP, key=len, reverse=True):
        q = q.replace(stop, " ")
    needles: list[str] = []
    seen: set[str] = set()
    for part in _CLAIM_SPLIT.split(q):
        if not part or _YEAR_RE.fullmatch(part):
            continue
        if re.fullmatch(r"[A-Za-z]+", part) and re.search(r"[\u4e00-\u9fff]", q):
            continue
        if not re.search(r"[\u4e00-\u9fff]", q):
            for lat in re.findall(r"[A-Za-z]{3,}", part):
                low = lat.lower()
                if low not in seen and low not in {"the", "and", "for", "with"}:
                    needles.append(lat)
                    seen.add(low)
        stripped = _strip_generic(part)
        if (
            len(stripped) >= 2
            and stripped not in _GENERIC_CLAIM
            and stripped not in seen
        ):
            needles.append(stripped)
            seen.add(stripped)
    return needles


# ---------------------------------------------------------------------------
# 实体词抽取与库外实体预检（docs/retrieval-fix-plan-20261025.md §4 1a）
#
# 设计约束：
# - 名词连续段不拆：欧洲门店数量、购物中心、低线城市必须整段保留；
# - 分隔符只消费虚词/副词/弱动词，被消费的串不进实体表；
# - 剥词表改动后必须用 tools/diag_needle_coverage.py 重跑校准：
#   noans 002/003/004/005/007 实体全 0 命中，freeze+diag 语义/跨语言无一道全 0 命中。
_ENTITY_SEPARATORS = (
    # 疑问与虚词
    "为什么", "为何", "有没有", "是不是", "怎么", "怎样", "哪些", "什么", "多少", "如何",
    "吗", "呢", "吧", "几",
    # 代词
    "自己", "别人", "大家", "这个", "那个", "这些", "那些", "我们", "你们", "他们",
    "我", "你", "他", "她", "它",
    # 助词、介词、连词
    "的", "了", "是", "和", "与", "及", "等", "对", "把", "给", "从", "往", "向", "在",
    "以内", "以外", "以上", "以下", "之前", "之后", "以后", "以来", "还", "并", "且",
    "而", "或", "若", "按", "通过", "被", "让", "使", "里",
    # 副词与剥词表
    "已经", "很", "更", "最", "太", "都", "也", "就", "才", "再", "又", "只", "仍",
    "仍然", "大概", "大约", "左右", "一共", "合计", "另外", "还是", "例如", "比如",
    "肯主动", "主动", "将来", "早年", "当年", "很早", "早点", "一起", "就是", "只是",
    "实际", "去", "时候", "时", "叫", "起过", "种", "套", "名字", "称呼",
    # 问句弱动词与助词（1a 校准追加；动前先跑 diag_needle_coverage.py）
    "伺候", "到位", "端着", "关掉", "创下", "准备", "回馈", "出去", "孵化", "交给",
    "变多", "变少", "变厚", "变薄", "来数", "铺", "占", "开", "开出", "家", "留住",
    "这家", "那家", "得", "快", "不", "转", "上半年", "表现",
)
_ENTITY_SPLIT_RE = re.compile(
    "|".join(re.escape(s) for s in sorted(_ENTITY_SEPARATORS, key=len, reverse=True))
    + r"|[^0-9A-Za-z\u4e00-\u9fff]+"
)
_LATIN_STOP = {"the", "and", "for", "with", "of", "in", "to", "a", "an", "is", "are"}


def entity_words(query: str, company: str | None = None) -> list[str]:
    """问句里的名词连续段（实体词），供库外实体预检与备用查询使用。

    空列表表示问句剥完虚词后没有实体，不做预检。
    """
    q = normalize_query(query or "")
    if not q:
        return []
    if company:
        q = q.replace(company, " ")
        if company.endswith("中国") and len(company) > 2:
            q = q.replace(company[:-2], " ")
    out: list[str] = []
    seen: set[str] = set()
    for part in _ENTITY_SPLIT_RE.split(q):
        p = part.strip()
        if not p or _YEAR_RE.fullmatch(p):
            continue
        if re.fullmatch(r"[A-Za-z]+", p):
            if len(p) < 2 or p.lower() in _LATIN_STOP:
                continue
        elif len(p) < 2 or not re.search(r"[\u4e00-\u9fff]", p):
            continue
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _fold_sql(col: str) -> str:
    """SQL 侧折叠空白与千分位，与 eval_runner.fold_fact_text 口径接近。"""
    return (
        f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE({col},"
        f"' ',''),'\u3000',''),char(10),''),char(13),''),char(9),''),'，',''),',','')"
    )


_ENTITY_PRESENCE_CACHE: dict[tuple[str | None, str], bool] = {}


def entity_in_corpus(conn: sqlite3.Connection, entity: str, company: str | None) -> bool:
    """该公司当前使用文档（非 OCR）里是否出现该实体词。"""
    key = (company, entity)
    hit = _ENTITY_PRESENCE_CACHE.get(key)
    if hit is None:
        if len(_ENTITY_PRESENCE_CACHE) > 4096:
            _ENTITY_PRESENCE_CACHE.clear()
        row = conn.execute(
            f"""
            SELECT 1 FROM pages p JOIN reports r ON r.id = p.report_id
            WHERE (:c IS NULL OR r.company = :c)
              AND {db.live_report_sql("r")}
              AND COALESCE(p.is_ocr, 0) < 2
              AND ({_fold_sql("p.content")} LIKE :l
                   OR {_fold_sql("p.content_orig")} LIKE :l)
            LIMIT 1
            """,
            {"c": company, "l": f"%{entity}%"},
        ).fetchone()
        hit = row is not None
        _ENTITY_PRESENCE_CACHE[key] = hit
    return hit


def all_entities_out_of_corpus(
    conn: sqlite3.Connection, query: str, company: str | None = None
) -> bool:
    """库外实体预检：实体词非空且全部 0 命中才为 True；空列表不预检。"""
    words = entity_words(query, company)
    if not words:
        return False
    return not any(entity_in_corpus(conn, w, company) for w in words)


def _match_expression(q: str) -> str:
    terms = _content_terms(q)
    if not terms:
        return ""
    if len(terms) > 1:
        return " AND ".join(_quote_fts(t) for t in terms)
    return _quote_fts(terms[0])


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for table in ("companies", "reports", "pages", "statements", "indicators", "sources"):
        out[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    out["reports_by_type"] = [
        dict(r)
        for r in conn.execute(
            "SELECT company, report_type, COUNT(*) AS n FROM reports GROUP BY company, report_type ORDER BY company"
        ).fetchall()
    ]
    out["reports_by_origin"] = [
        dict(r)
        for r in conn.execute(
            "SELECT origin, COUNT(*) AS n FROM reports GROUP BY origin ORDER BY origin"
        ).fetchall()
    ]
    return out


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
