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

    eval_raw = Path(cfg.get("eval", {}).get("questions", "eval/questions.yaml"))
    cfg.setdefault("eval", {})["questions"] = str(
        eval_raw if eval_raw.is_absolute() else root / eval_raw
    )
    return cfg
