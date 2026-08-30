"""Regression helpers: per-question hit snapshot and flip diff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASELINE_NAME = "regression_baseline.json"


def baseline_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["project_root"]) / "eval" / BASELINE_NAME


def extract_question_hits(eval_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compact per-question outcome used for flip comparison."""
    out: dict[str, dict[str, Any]] = {}
    for item in eval_result.get("results") or []:
        qid = item.get("id")
        if not qid:
            continue
        rec: dict[str, Any] = {"type": item.get("type")}
        qtype = item.get("type")
        if item.get("structured") is not None:
            rec["structured_hit"] = bool(item["structured"].get("hit"))
            rec["parse_hit"] = bool(item["structured"].get("parse_hit"))
        elif qtype == "indicator":
            rec["indicator_hit"] = bool((item.get("indicator") or {}).get("hit"))
        elif qtype == "no_answer":
            n_hits = len((item.get("retrieval") or {}).get("top_hits") or [])
            rec["empty"] = n_hits == 0
        elif qtype == "end2end":
            rec["material_complete"] = not bool(
                (item.get("generation") or {}).get("pending_manual")
            )
        elif qtype == "route":
            rec["route_hit"] = bool((item.get("route") or {}).get("hit"))
        elif qtype == "year_filter":
            rec["year_precision"] = (item.get("year_filter") or {}).get("precision")
            rec["hit"] = bool((item.get("retrieval") or {}).get("hit"))
        else:
            rec["hit"] = bool((item.get("retrieval") or {}).get("hit"))
        out[str(qid)] = rec
    return out


def primary_ok(rec: dict[str, Any] | None) -> bool | None:
    if not rec:
        return None
    for key in (
        "hit",
        "structured_hit",
        "indicator_hit",
        "empty",
        "material_complete",
        "route_hit",
    ):
        if key in rec:
            return bool(rec[key])
    return None


def diff_question_hits(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    lost: list[str] = []
    gained: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    for qid, rec in current.items():
        if qid not in baseline:
            added.append(qid)
            continue
        before = primary_ok(baseline[qid])
        after = primary_ok(rec)
        if before is True and after is False:
            lost.append(qid)
        elif before is False and after is True:
            gained.append(qid)
    for qid in baseline:
        if qid not in current:
            removed.append(qid)
    return {
        "lost": sorted(lost),
        "gained": sorted(gained),
        "added": sorted(added),
        "removed": sorted(removed),
    }


def load_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_baseline(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_baseline(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    sha = None
    for name, data in results.items():
        meta = data.get("meta") or {}
        sha = meta.get("questions_sha256") or sha
        split = meta.get("split") or "freeze"
        engine = meta.get("engine") or name
        key = f"{engine}:{split}"
        if name.endswith("_diag"):
            key = f"{engine}:diag"
        runs[key] = {
            "engine": engine,
            "split": split,
            "questions_sha256": meta.get("questions_sha256"),
            "questions": extract_question_hits(data),
        }
    return {
        "version": 1,
        "questions_sha256": sha,
        "runs": runs,
    }


def format_flips(run_key: str, diff: dict[str, list[str]], sha_note: str = "") -> str:
    lines = [f"[{run_key} flips]{sha_note}"]
    any_flip = False
    for label in ("lost", "gained", "added", "removed"):
        ids = diff.get(label) or []
        if not ids:
            continue
        any_flip = True
        lines.append(f"  {label}: {', '.join(ids)}")
    if not any_flip:
        lines.append("  (none)")
    return "\n".join(lines)
