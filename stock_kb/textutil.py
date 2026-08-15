from __future__ import annotations

_CACHE: dict[str, object] = {}


def to_simplified(text: str) -> str:
    """繁体中文转简体；转换库不可用时原样返回。"""
    try:
        from opencc import OpenCC
    except Exception:
        return text
    if "t2s" not in _CACHE:
        _CACHE["t2s"] = OpenCC("t2s")
    return _CACHE["t2s"].convert(text)  # type: ignore[no-any-return]
