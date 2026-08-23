"""评测回归门禁：FTS 与默认 hybrid 的核心指标不得低于当前基线。

用法:
    python tools/run_eval_regression.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_kb.config import load_config
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
    "semantic.recall_at_k": 0.10,
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


def main() -> int:
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

    print("RESULT:", "PASS" if not failed else "FAIL")
    print(json.dumps(
        {engine: data["summary"] for engine, data in results.items()},
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
