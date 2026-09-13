"""评测回归门禁：FTS 与默认 hybrid 的核心指标不得低于当前基线。

用法:
    python tools/run_eval_regression.py
    python tools/run_eval_regression.py --write-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_notes as audit_notes_mod
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
    "structured.hit": 26,
    "structured.n": 26,
}
FTS_MAX = {
    "keyword.negative_hit_rate": 0.65,
}
HYBRID_MIN = {
    "semantic.recall_at_k": 0.20,
    "structured.hit": 26,
    "structured.n": 26,
}
HYBRID_MAX = {
    "semantic.negative_hit_rate": 0.20,
}
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
        }
        print(f"[{engine}]")
        for key, value in checks.items():
            minimum = mins.get(key)
            if minimum is not None:
                ok = value is not None and value >= minimum
                print(f"  {key}: {value} (min {minimum}) {'OK' if ok else 'FAIL'}")
                if not ok:
                    failed.append(f"{engine}.{key}")
            maximum = maxes.get(key)
            if maximum is not None:
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

    if not args.skip_notes:
        print("[audit_notes]")
        notes_failed, notes_report = audit_notes_mod.run_audit(cfg)
        acc = (notes_report.get("summary") or {}).get("number_accuracy_mean")
        print(f"  fail_count: {notes_failed} (max 0) {'OK' if notes_failed == 0 else 'FAIL'}")
        print(f"  number_accuracy_mean: {acc}")
        if notes_failed:
            failed.append("audit_notes")
    else:
        print("[audit_notes] skipped")

    if not args.skip_notes:
        print("[generation_compose]")
        from stock_kb.generation_eval import run_generation_eval

        gen = run_generation_eval(cfg)
        gen_fail = (gen.get("summary") or {}).get("fail_count")
        gen_faith = (gen.get("summary") or {}).get("faithful_rate_mean")
        ok_gen = gen_fail == 0
        print(f"  fail_count: {gen_fail} (max 0) {'OK' if ok_gen else 'FAIL'}")
        print(f"  faithful_rate_mean: {gen_faith}")
        if not ok_gen:
            failed.append("generation_compose")


    print("RESULT:", "PASS" if not failed else "FAIL")
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
