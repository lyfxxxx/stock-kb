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
HYBRID_MIN = {
    "semantic.recall_at_k": 0.30,
    "structured.hit": 26,
    "structured.n": 26,
}


def main() -> int:
    cfg = load_config()
    model = cfg.get("embedding", {}).get("model", "BAAI/bge-small-zh-v1.5")
    results = {
        "fts": run_eval(cfg, top_k=5, model=None, engine="fts"),
        "hybrid": run_eval(cfg, top_k=5, model=model, engine="hybrid"),
    }
    failed = []

    for engine, data in results.items():
        summary = data["summary"]
        retrieval = summary.get("retrieval", {})
        structured = summary.get("structured", {})
        thresholds = FTS_MIN if engine == "fts" else HYBRID_MIN
        checks = {
            "keyword.recall_at_k": retrieval.get("keyword", {}).get("recall_at_k"),
            "semantic.recall_at_k": retrieval.get("semantic", {}).get("recall_at_k"),
            "structured.hit": structured.get("hit"),
            "structured.n": structured.get("n"),
        }
        print(f"[{engine}]")
        for key, value in checks.items():
            minimum = thresholds.get(key)
            if minimum is None:
                continue
            ok = value is not None and value >= minimum
            print(f"  {key}: {value} (min {minimum}) {'OK' if ok else 'FAIL'}")
            if not ok:
                failed.append(f"{engine}.{key}")

    print("RESULT:", "PASS" if not failed else "FAIL")
    print(json.dumps(
        {engine: data["summary"] for engine, data in results.items()},
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
