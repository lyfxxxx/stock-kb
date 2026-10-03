from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else Path(os.environ.get("STOCK_KB_CONFIG", DEFAULT_CONFIG))
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    root = p.resolve().parent
    cfg["project_root"] = str(root)

    for key in ("data_dir", "models_dir"):
        raw = cfg.get(key, key)
        d = Path(raw)
        cfg[key] = str(d if d.is_absolute() else root / d)

    db_raw = Path(cfg.get("db_path", "data/stock_kb.db"))
    cfg["db_path"] = str(db_raw if db_raw.is_absolute() else root / db_raw)

    collect = cfg.get("collect") or {}
    if not isinstance(collect, dict):
        collect = {}
    cfg["collect"] = collect
    collect.setdefault("user_agent", "stock-kb local@localhost")
    collect.setdefault("companies", {})
    raw = collect.get("raw_dir")
    if not raw:
        collect["raw_dir"] = str(Path(cfg["data_dir"]) / "raw")
    else:
        raw_path = Path(str(raw))
        collect["raw_dir"] = str(raw_path if raw_path.is_absolute() else root / raw_path)
    meta = collect.get("meta_dir")
    if not meta:
        collect["meta_dir"] = str(Path(cfg["data_dir"]) / "meta")
    else:
        meta_path = Path(str(meta))
        collect["meta_dir"] = str(meta_path if meta_path.is_absolute() else root / meta_path)

    eval_raw = Path(cfg.get("eval", {}).get("questions", "eval/questions.yaml"))
    cfg.setdefault("eval", {})["questions"] = str(
        eval_raw if eval_raw.is_absolute() else root / eval_raw
    )
    return cfg
