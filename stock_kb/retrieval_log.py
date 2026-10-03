"""查询日志。知识库连接保持只读，日志写到 data_dir/retrieval_log.jsonl。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("data_dir") or "data") / "retrieval_log.jsonl"


def resolve_run_id(override: str | None = None) -> str | None:
    if override:
        return override
    return os.environ.get("STOCK_KB_RUN_ID") or None


def hit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留 title 和整数 page，不写正文。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        title = row.get("title")
        page = row.get("page", row.get("page_no"))
        if title is None or page is None:
            continue
        try:
            page_i = int(page)
        except (TypeError, ValueError):
            continue
        out.append({"title": str(title), "page": page_i})
    return out


def append_retrieval(
    cfg: dict[str, Any],
    *,
    tool: str,
    query: str | None,
    company: str | None,
    year: int | None,
    engine: str | None,
    params: dict[str, Any] | None,
    hits: list[dict[str, Any]],
    run_id: str | None = None,
) -> None:
    record = {
        "run_id": resolve_run_id(run_id),
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tool": tool,
        "query": query,
        "company": company,
        "year": year,
        "engine": engine,
        "params": params or {},
        "hits": hit_rows(hits),
    }
    path = log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows
