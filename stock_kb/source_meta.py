"""原文旁不再放 sidecar。出处 JSON 集中在 collect.meta_dir。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def origin_for(cfg: dict[str, Any], path: Path) -> str | None:
    """nas if under nas.root; collect if under collect.raw_dir; else None.
    If both match, prefer the longer root (more specific).
    Absolute paths compare as strings so UNC NAS roots work while offline.
    """
    matches: list[tuple[int, str]] = []
    candidates: list[tuple[str, Any]] = [
        ("nas", (cfg.get("nas") or {}).get("root")),
        ("collect", (cfg.get("collect") or {}).get("raw_dir")),
    ]
    for label, raw_root in candidates:
        if not raw_root:
            continue
        root = Path(raw_root)
        if not _is_under(path, root):
            continue
        matches.append((len(_norm_path(root)), label))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def meta_dir_from_cfg(cfg: dict[str, Any]) -> Path | None:
    collect = cfg.get("collect") or {}
    raw = collect.get("meta_dir")
    if raw:
        return Path(str(raw))
    data_dir = cfg.get("data_dir")
    if data_dir:
        return Path(str(data_dir)) / "meta"
    return None


def origin_root(cfg: dict[str, Any], origin: str) -> Path | None:
    if origin == "nas":
        raw = (cfg.get("nas") or {}).get("root")
    elif origin == "collect":
        raw = (cfg.get("collect") or {}).get("raw_dir")
    else:
        return None
    if not raw:
        return None
    return Path(str(raw))


def relative_under_origin(
    cfg: dict[str, Any], path: Path, origin: str, company: str
) -> str | None:
    root = origin_root(cfg, origin)
    if root is None:
        return None
    bases: list[Path] = []
    name = str(company or "").strip()
    if name and name not in {".", ".."} and "/" not in name and "\\" not in name:
        bases.append(root / name)
    bases.append(root)
    for base in bases:
        rel = _relative_posix(path, base)
        if rel:
            return rel
    return None


def source_meta_path(meta_root: Path, origin: str, company: str, relative: str) -> Path:
    rel = relative.replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p and p not in {".", ".."}]
    if not parts:
        raise ValueError(f"非法相对路径: {relative}")
    filename = parts[-1] + ".source.json"
    return Path(meta_root).joinpath(origin, company, *parts[:-1], filename)


def read_source_meta(
    cfg: dict[str, Any], path: Path, company: str
) -> tuple[str | None, str | None]:
    """优先读 meta_dir，没有则读原文旁遗留的 sidecar。"""
    data = load_source_meta(cfg, path, company)
    if not data:
        return None, None
    url = data.get("source_url")
    retrieved = data.get("retrieved_at")
    return (str(url) if url else None, str(retrieved) if retrieved else None)


def load_source_meta(cfg: dict[str, Any], path: Path, company: str) -> dict[str, Any] | None:
    origin = origin_for(cfg, path)
    rel = relative_under_origin(cfg, path, origin, company) if origin else None
    meta_root = meta_dir_from_cfg(cfg)
    if origin and rel and meta_root is not None:
        data = _read_json(source_meta_path(meta_root, origin, company, rel))
        if data:
            return data
    return _read_json(path.parent / f"{path.name}.source.json")


def write_source_meta(
    cfg: dict[str, Any],
    path: Path,
    company: str,
    *,
    origin: str | None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
    sha256: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path | None:
    if origin not in {"nas", "collect"}:
        return None
    rel = relative_under_origin(cfg, path, origin, company)
    meta_root = meta_dir_from_cfg(cfg)
    if not rel or meta_root is None:
        return None
    dest = source_meta_path(meta_root, origin, company, rel)
    payload = dict(load_source_meta(cfg, path, company) or {})
    payload["origin"] = origin
    payload["company"] = company
    payload["relative_path"] = rel
    if source_url:
        payload["source_url"] = source_url
    if retrieved_at:
        payload["retrieved_at"] = retrieved_at
    if sha256:
        payload["sha256"] = sha256
    if extra:
        for key, value in extra.items():
            if value is not None:
                payload[key] = value
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def _relative_posix(path: Path, root: Path) -> str | None:
    p_s = _norm_path(path)
    r_s = _norm_path(root)
    if p_s == r_s:
        return None
    prefix = r_s + os.sep
    if not p_s.startswith(prefix):
        return None
    rest = p_s[len(prefix) :]
    return rest.replace("\\", "/")


def _norm_path(path: Path) -> str:
    raw = Path(path)
    if not raw.is_absolute():
        try:
            raw = raw.resolve()
        except OSError:
            raw = Path(os.path.abspath(str(raw)))
    s = os.path.normcase(os.path.normpath(str(raw)))
    if len(s) > 1:
        s = s.rstrip(os.sep)
    return s


def _is_under(path: Path, root: Path) -> bool:
    p_s = _norm_path(path)
    r_s = _norm_path(root)
    return p_s == r_s or p_s.startswith(r_s + os.sep)
