"""评测回归门禁：FTS 与默认 hybrid 的核心指标不得低于当前基线。

用法:
    python tools/run_eval_regression.py
    python tools/run_eval_regression.py --write-baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_notes as audit_notes_mod
from audit_formal_notes import audit_formal_note
from stock_kb import db as db_mod
from stock_kb.config import load_config
from stock_kb.eval_regression import (
    baseline_path,
    build_baseline,
    diff_question_hits,
    format_flips,
    load_baseline,
    save_baseline,
)
from stock_kb.eval_runner import run_eval

FTS_MIN = {
    "keyword.recall_at_k": 0.75,
    "structured.hit": 29,
    "structured.n": 29,
    "structured.parse_hit": 29,
    "structured.page_match": 29,
    "structured.source_match": 29,
}
FTS_MAX = {
    "keyword.negative_hit_rate": 0.65,
}
HYBRID_MIN = {
    "semantic.recall_at_k": 0.85,
    "structured.hit": 29,
    "structured.n": 29,
    "structured.parse_hit": 29,
    "structured.page_match": 29,
    "structured.source_match": 29,
}
HYBRID_MAX = {
    "semantic.negative_hit_rate": 0.20,
    "keyword.negative_hit_rate": 0.20,
}
# 融合保留率：FTS 已命中的关键词题里，hybrid 仍命中的比例。
# 分子分母都取自同一次回归的 fts/hybrid 结果，不是绝对关键词能力门。
# 语义是「融合是加法，不是替换」：FTS 能中的页不应被向量分路挤掉。
FUSION_MIN_PCT = 0.85
# 生成层：手写试点笔记的数字纪律（原来只打印，未设门）。
GEN_NUMBER_ACCURACY_MIN = 0.95
GEN_ORPHAN_RATE_MAX = 0.10
GEN_CITATION_PRECISION_MIN = 0.95
# 短查询短路一致性：题面归一化后 <6 字时 hybrid 必须与 FTS 逐页相同。
# 这些短查询不写进 questions.yaml（短词天然跨文档，定不出单一期望页），
# 因此用一致性断言覆盖，不需要 GT。
SHORT_CIRCUIT_QUERIES = ("翻台率", "客单价", "师徒制", "阿米巴", "肩并肩", "资本开支")
DIAG_FTS_MIN = {
    "indicator.hit": 12,
    "indicator.n": 12,
    "no_answer.empty_rate": 0.75,
}
DIAG_HYBRID_MIN = {
    "no_answer.empty_rate": 0.75,
}
ROUTE_MIN = {
    "route.accuracy": 1.0,
    "route.n": 24,
}
YEAR_MIN = {
    "year_filter.precision_mean": 0.60,
    "year_filter.n": 4,
}


def _run_key(name: str, data: dict) -> str:
    meta = data.get("meta") or {}
    engine = meta.get("engine") or name
    split = meta.get("split") or "freeze"
    if name.endswith("_diag"):
        return f"{engine}:diag"
    return f"{engine}:{split}"


def fusion_retention(fts_res: dict, hyb_res: dict) -> tuple[int, int]:
    """FTS 已命中的关键词题里，hybrid 仍命中多少。

    分母是「FTS 命中集合」，不是全部关键词题。这样这组数回答的是
    「融合把已经精确命中的页挤掉了多少」，与 FTS 的绝对召回无关。
    """

    def hits(data: dict) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for row in data.get("results") or []:
            if (row.get("type") or "").lower() != "keyword":
                continue
            out[row["id"]] = bool((row.get("retrieval") or {}).get("hit"))
        return out

    fts_hits, hyb_hits = hits(fts_res), hits(hyb_res)
    base = [qid for qid, ok in fts_hits.items() if ok]
    kept = [qid for qid in base if hyb_hits.get(qid)]
    return len(kept), len(base)


def check_short_circuit(cfg: dict, model: str) -> list[str]:
    """短查询（归一化后 <6 字）必须短路回 FTS，逐页一致。

    覆盖两条此前没有题目守着的行为：
    1. 短路：FTS 有命中时 hybrid 不得融合，结果须与 FTS 完全相同；
    2. 兜底：FTS 为空时 hybrid 才允许走向量融合兜底。
    """

    from stock_kb import search, vector

    conn = db_mod.connect(cfg["db_path"])
    cache_dir = cfg.get("models_dir")
    embedding = cfg.get("embedding") or {}
    backend = embedding.get("backend") or "auto"
    rerank = bool(embedding.get("rerank"))
    problems: list[str] = []
    try:
        for query in SHORT_CIRCUIT_QUERIES:
            norm = search.normalize_query(query)
            if len(norm) >= 6:
                problems.append(f"{query}: 归一化后 {len(norm)} 字，无法验证短路")
                continue
            fts = search.fts_search(conn, query, top_k=5)
            hyb = vector.hybrid_search(
                conn,
                query,
                model,
                top_k=5,
                cache_dir=cache_dir,
                backend=backend,
                rerank=rerank,
            )
            fused = any(h.get("hybrid_fused") for h in hyb)
            fts_ids = [h["page_id"] for h in fts]
            hyb_ids = [h["page_id"] for h in hyb]
            if fts_ids:
                if fused:
                    problems.append(
                        f"{query}: FTS 有 {len(fts_ids)} 条命中，hybrid 仍融合（应短路）"
                    )
                elif fts_ids != hyb_ids:
                    problems.append(f"{query}: 已短路但结果与 FTS 不一致")
            elif hyb and not fused:
                problems.append(f"{query}: FTS 为空，hybrid 走了结果却未标 fused")
        return problems
    finally:
        conn.close()


RATIO_HINTS = ("recall_at_k", "empty_rate", "accuracy", "precision_mean")


def iter_ratio_paths(data: dict, prefix: str = "") -> set[str]:
    """收集 summary 里的比率型标量路径，用于「已算但未设门」的覆盖统计。"""

    found: set[str] = set()
    for key, value in data.items():
        if key == "retrieval_diag":
            # diag 检索只做诊断（EVAL_SYSTEM §1），整棵不进覆盖统计。
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            found |= iter_ratio_paths(value, f"{path}.")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if any(hint in key for hint in RATIO_HINTS):
                found.add(path)
    return found


# 明确不设门的核心召回类指标及理由。新增的 recall / empty_rate / accuracy
# 若既不在门禁里、也不在这张表里，会在 [gate_coverage] 的「未分类」一栏露出来。
# 排序类指标（Hit@1 / MRR / nDCG / Precision@k / Neg@1）一律只展示，不进覆盖统计：
# n=20~22 时点估计会跳，产品也只要求 top-5 里有出处。
SKIPPED_METRICS = {
    "retrieval.cross.recall_at_k": "跨语言 n=6，只做诊断",
    "retrieval.total.recall_at_k": "分层不合成总 Recall",
    "retrieval.semantic.recall_at_k": "FTS 不做语义召回（hybrid 侧已设门）",
    "retrieval.keyword.recall_at_k": "hybrid 侧改用融合保留率表达，绝对召回不设门；FTS 侧已设门",
    "retrieval.annual_recall_at_k": "字段当前为空（未标 authority）",
    "no_answer.empty_rate": "freeze 分集无无答案题（n=0），空跑；diag 侧已设门",
    "route.accuracy": "只在 fts freeze 检查一次，hybrid 侧同值重复",
    "year_filter.precision_mean": "只在 fts freeze 检查一次，hybrid 侧同值重复",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="stock-kb 评测回归门禁")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="门槛全部通过后，把本轮每题 hit 写成 eval/regression_baseline.json",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="跳过 audit_notes 与组稿生成评测（默认纳入门禁）",
    )
    args = parser.parse_args()

    cfg = load_config()
    model = cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    results = {
        "fts": run_eval(cfg, top_k=5, model=None, engine="fts", split="freeze"),
        "hybrid": run_eval(
            cfg, top_k=5, model=model, engine="hybrid", split="freeze"
        ),
        "fts_diag": run_eval(cfg, top_k=5, model=None, engine="fts", split="diag"),
        "hybrid_diag": run_eval(
            cfg, top_k=5, model=model, engine="hybrid", split="diag"
        ),
    }
    failed = []
    gated_paths: set[str] = set()

    for engine, data in results.items():
        if engine in {"fts_diag", "hybrid_diag"}:
            continue
        summary = data["summary"]
        retrieval = summary.get("retrieval", {})
        structured = summary.get("structured", {})
        mins = FTS_MIN if engine == "fts" else HYBRID_MIN
        maxes = FTS_MAX if engine == "fts" else HYBRID_MAX
        checks = {
            "keyword.recall_at_k": retrieval.get("keyword", {}).get("recall_at_k"),
            "keyword.negative_hit_rate": retrieval.get("keyword", {}).get(
                "negative_hit_rate"
            ),
            "semantic.recall_at_k": retrieval.get("semantic", {}).get("recall_at_k"),
            "semantic.negative_hit_rate": retrieval.get("semantic", {}).get(
                "negative_hit_rate"
            ),
            "structured.hit": structured.get("hit"),
            "structured.n": structured.get("n"),
            "structured.parse_hit": structured.get("parse_hit"),
            "structured.page_match": structured.get("page_match"),
            "structured.source_match": structured.get("source_match"),
        }
        print(f"[{engine}]")
        for key, value in checks.items():
            minimum = mins.get(key)
            if minimum is not None:
                gated_paths.add(
                    f"{engine}.{key}" if key.startswith("structured.") else f"{engine}.retrieval.{key}"
                )
                ok = value is not None and value >= minimum
                print(f"  {key}: {value} (min {minimum}) {'OK' if ok else 'FAIL'}")
                if not ok:
                    failed.append(f"{engine}.{key}")
            maximum = maxes.get(key)
            if maximum is not None:
                gated_paths.add(
                    f"{engine}.{key}" if key.startswith("structured.") else f"{engine}.retrieval.{key}"
                )
                ok = value is not None and value <= maximum
                print(f"  {key}: {value} (max {maximum}) {'OK' if ok else 'FAIL'}")
                if not ok:
                    failed.append(f"{engine}.{key}.max")

    diag = results["fts_diag"]["summary"]
    diag_checks = {
        "indicator.hit": (diag.get("indicator") or {}).get("hit"),
        "indicator.n": (diag.get("indicator") or {}).get("n"),
        "no_answer.empty_rate": (diag.get("no_answer") or {}).get("empty_rate"),
    }
    print("[fts_diag]")
    for key, value in diag_checks.items():
        minimum = DIAG_FTS_MIN[key]
        ok = value is not None and value >= minimum
        print(f"  {key}: {value} (min {minimum}) {'OK' if ok else 'FAIL'}")
        if not ok:
            failed.append(f"fts_diag.{key}")

    hybrid_diag = results["hybrid_diag"]["summary"]
    hyb_empty = (hybrid_diag.get("no_answer") or {}).get("empty_rate")
    print("[hybrid_diag]")
    ok = hyb_empty is not None and hyb_empty >= DIAG_HYBRID_MIN["no_answer.empty_rate"]
    print(
        f"  no_answer.empty_rate: {hyb_empty} "
        f"(min {DIAG_HYBRID_MIN['no_answer.empty_rate']}) {'OK' if ok else 'FAIL'}"
    )
    if not ok:
        failed.append("hybrid_diag.no_answer.empty_rate")
    gated_paths.add("fts_diag.no_answer.empty_rate")
    gated_paths.add("hybrid_diag.no_answer.empty_rate")

    kept, base = fusion_retention(results["fts"], results["hybrid"])
    print("[fusion_retention]")
    if base:
        ratio = round(kept / base, 3)
        ok_fuse = ratio >= FUSION_MIN_PCT
        print(
            f"  keyword.retention: {ratio} ({kept}/{base}) "
            f"(min {FUSION_MIN_PCT}) {'OK' if ok_fuse else 'FAIL'}"
        )
        print("    分母是 FTS 已命中的关键词题；本项测「融合是否挤掉精确命中」")
        if not ok_fuse:
            failed.append("hybrid.fusion_retention")
    else:
        print("  keyword.retention: 分母 0（FTS 无命中），跳过")

    print("[hybrid_short_circuit]")
    try:
        short_problems = check_short_circuit(cfg, model)
    except Exception as exc:  # noqa: BLE001 - 检查异常本身就该是失败信号
        short_problems = [f"检查异常: {type(exc).__name__}: {exc}"]
    if short_problems:
        for problem in short_problems:
            print(f"  FAIL {problem}")
        failed.append("hybrid_short_circuit")
    else:
        print(
            f"  {len(SHORT_CIRCUIT_QUERIES)} 条短查询（<6 字）：短路与兜底行为符合预期"
        )

    current_baseline = build_baseline(results)
    snap_path = baseline_path(cfg)
    previous = load_baseline(snap_path)
    print("[flips vs baseline]")
    if previous is None:
        print(f"  无基线文件: {snap_path}（本轮只打印，不因翻题失败）")
        if args.write_baseline and not failed:
            print("  --write-baseline 将在门槛通过后写入")
    else:
        prev_sha = previous.get("questions_sha256")
        cur_sha = current_baseline.get("questions_sha256")
        sha_note = ""
        if prev_sha and cur_sha and prev_sha != cur_sha:
            sha_note = f"  questions_sha256 changed {prev_sha[:12]}→{cur_sha[:12]}"
            print(f"  {sha_note.strip()}")
        prev_runs = previous.get("runs") or {}
        cur_runs = current_baseline.get("runs") or {}
        for name, data in results.items():
            key = _run_key(name, data)
            prev_q = (prev_runs.get(key) or {}).get("questions") or {}
            cur_q = (cur_runs.get(key) or {}).get("questions") or {}
            diff = diff_question_hits(prev_q, cur_q)
            print(format_flips(key, diff))

    freeze_summary = results["fts"]["summary"]
    route = freeze_summary.get("route") or {}
    print("[route]")
    route_n = route.get("n")
    route_acc = route.get("accuracy")
    ok_n = route_n is not None and route_n >= ROUTE_MIN["route.n"]
    ok_acc = route_acc is not None and route_acc >= ROUTE_MIN["route.accuracy"]
    print(f"  n: {route_n} (min {ROUTE_MIN['route.n']}) {'OK' if ok_n else 'FAIL'}")
    print(
        f"  accuracy: {route_acc} (min {ROUTE_MIN['route.accuracy']}) "
        f"{'OK' if ok_acc else 'FAIL'}"
    )
    print(f"  wrong_tool_rate: {route.get('wrong_tool_rate')}")
    gated_paths.add("fts.route.accuracy")
    if not ok_n:
        failed.append("route.n")
    if not ok_acc:
        failed.append("route.accuracy")

    yf = freeze_summary.get("year_filter") or {}
    print("[year_filter]")
    yf_n = yf.get("n")
    yf_p = yf.get("precision_mean")
    ok_yn = yf_n is not None and yf_n >= YEAR_MIN["year_filter.n"]
    ok_yp = yf_p is not None and yf_p >= YEAR_MIN["year_filter.precision_mean"]
    print(f"  n: {yf_n} (min {YEAR_MIN['year_filter.n']}) {'OK' if ok_yn else 'FAIL'}")
    print(
        f"  precision_mean: {yf_p} (min {YEAR_MIN['year_filter.precision_mean']}) "
        f"{'OK' if ok_yp else 'FAIL'}"
    )
    if not ok_yn:
        failed.append("year_filter.n")
    if not ok_yp:
        failed.append("year_filter.precision_mean")
    gated_paths.add("fts.year_filter.precision_mean")
    yf_empty = yf.get("empty")
    ok_yempty = yf_empty in (0, None)
    print(
        f"  empty: {yf_empty} (max 0) {'OK' if ok_yempty else 'FAIL'}"
    )
    if not ok_yempty:
        failed.append("year_filter.empty")

    if not args.skip_notes:
        print("[audit_notes]")
        notes_failed, notes_report = audit_notes_mod.run_audit(cfg)
        acc = (notes_report.get("summary") or {}).get("number_accuracy_mean")
        per_note = notes_report.get("notes") or {}
        orphans = [
            v["orphan_number_rate"]
            for v in per_note.values()
            if v.get("orphan_number_rate") is not None
        ]
        cites = [
            v["citation_precision"]
            for v in per_note.values()
            if v.get("citation_precision") is not None
        ]
        orphan_mean = round(sum(orphans) / len(orphans), 3) if orphans else None
        cite_min = min(cites) if cites else None
        print(f"  fail_count: {notes_failed} (max 0) {'OK' if notes_failed == 0 else 'FAIL'}")
        ok_acc = acc is not None and acc >= GEN_NUMBER_ACCURACY_MIN
        print(
            f"  number_accuracy_mean: {acc} "
            f"(min {GEN_NUMBER_ACCURACY_MIN}) {'OK' if ok_acc else 'FAIL'}"
        )
        ok_orphan = orphan_mean is not None and orphan_mean <= GEN_ORPHAN_RATE_MAX
        print(
            f"  orphan_number_rate_mean: {orphan_mean} "
            f"(max {GEN_ORPHAN_RATE_MAX}) {'OK' if ok_orphan else 'FAIL'}"
        )
        ok_cite = cite_min is not None and cite_min >= GEN_CITATION_PRECISION_MIN
        print(
            f"  citation_precision_min: {cite_min} "
            f"(min {GEN_CITATION_PRECISION_MIN}) {'OK' if ok_cite else 'FAIL'}"
        )
        if notes_failed:
            failed.append("audit_notes")
        if not ok_acc:
            failed.append("audit_notes.number_accuracy")
        if not ok_orphan:
            failed.append("audit_notes.orphan_rate")
        if not ok_cite:
            failed.append("audit_notes.citation_precision")
    else:
        print("[audit_notes] skipped")

    print("[retrieval_buckets]")
    for engine, data in results.items():
        buckets = (data.get("summary") or {}).get("retrieval_buckets") or {}
        if not buckets:
            print(f"  {engine}: n=0")
            continue
        for name, stat in buckets.items():
            n = stat.get("n") or 0
            if n < 5:
                print(f"  {engine}.{name}: n={n}")
            else:
                print(f"  {engine}.{name}: n={n} recall_at_5={stat.get('recall_at_5')}")

    audit_unverified = 0
    if not args.skip_notes:
        print("[audit-report]")
        from stock_kb.audit_report import audit_report
        from stock_kb.retrieval_log import log_path, read_log

        root = Path(cfg["project_root"])
        notes = root / "eval" / "generated_notes"
        reports = sorted(notes.glob("**/*扫描*.md")) + sorted(notes.glob("**/*扫描*.html"))
        if not reports:
            audit_unverified += 1
            print("audit-report: skipped (no agent report); not a pass")
        else:
            conn = db_mod.connect(cfg["db_path"])
            log_lines = read_log(log_path(cfg))
            audit_fails = 0
            try:
                for path in reports:
                    company = path.parent.name
                    if company == "generated_notes":
                        company = path.stem.split("-扫描")[0]
                        company = company.split("扫描")[0].strip("-")
                    text = path.read_text(encoding="utf-8")
                    if not re.search(r"(?m)^\s*run_id:\s*\S+", text):
                        audit_unverified += 1
                        print(
                            f"  {path.parent.name}/{path.name}: "
                            "skipped (legacy note without run_id); not a pass"
                        )
                        continue
                    result = audit_report(conn, text, log_lines, company)
                    print(f"  {path.parent.name}/{path.name}: {'OK' if result['ok'] else 'FAIL'}")
                    for issue in result["issues"]:
                        print(f"    {issue}")
                    if not result["ok"]:
                        audit_fails += 1
            finally:
                conn.close()
            if audit_fails:
                failed.append("audit-report")

    if not args.skip_notes:
        print("[coverage_matrix]")
        from coverage_matrix import print_coverage_matrix

        conn = db_mod.connect(cfg["db_path"])
        print_coverage_matrix(conn)
        conn.close()

    if not args.skip_notes:
        # 正式稿样张存在时做程序化审计（R3/R4/R5/R9 可自动部分）
        formal = sorted(Path("eval/generated_notes").glob("*/*-正式稿.md"))
        if formal:
            print("[audit_formal_notes]")
            conn = db_mod.connect(cfg["db_path"])
            formal_fails = 0
            for p in formal:
                res = audit_formal_note(conn, p)
                print(f"  {p.parent.name}/{p.name}: {'OK' if res['ok'] else 'FAIL'}")
                for issue in res["issues"]:
                    print(f"    {issue}")
                if not res["ok"]:
                    formal_fails += 1
            conn.close()
            if formal_fails:
                failed.append("audit_formal_notes")
        else:
            print("[audit_formal_notes] 无正式稿样张，跳过")

    print("[gate_coverage]")
    all_ratio: set[str] = set()
    for engine_name, data in results.items():
        for path in iter_ratio_paths(data.get("summary") or {}):
            all_ratio.add(f"{engine_name}.{path}")
    gated_hits = all_ratio & gated_paths
    skipped_hits: list[tuple[str, str]] = []
    unclassified: list[str] = []
    for path in sorted(all_ratio - gated_paths):
        bare = path.split(".", 1)[1]
        reason = SKIPPED_METRICS.get(bare)
        if reason:
            skipped_hits.append((path, reason))
        else:
            unclassified.append(path)
    print(f"  已设门: {len(gated_hits)} 项")
    print(f"  显式跳过: {len(skipped_hits)} 项")
    for path, reason in skipped_hits:
        print(f"    skip {path}: {reason}")
    print(f"  未分类: {len(unclassified)} 项")
    for path in unclassified:
        print(f"    !! {path}: 已计算但既未设门也未登记理由")
    if unclassified:
        failed.append("gate_coverage.unclassified")

    if not failed and audit_unverified:
        print(f"RESULT: PASS (audit unverified: {audit_unverified} 份稿缺 run_id)")
    else:
        print("RESULT:", "PASS" if not failed else "FAIL")
    if failed:
        print("FAILED:", ", ".join(sorted(set(failed))))
    print(json.dumps(
        {engine: data["summary"] for engine, data in results.items()},
        ensure_ascii=False,
        indent=2,
    ))

    if args.write_baseline:
        if failed:
            print(f"未写入基线：门槛未过 {failed}")
        else:
            save_baseline(snap_path, current_baseline)
            print(f"已写入基线: {snap_path}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
