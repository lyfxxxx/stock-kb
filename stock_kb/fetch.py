"""下载财报到 raw_dir，出处 JSON 写到 collect.meta_dir。SEC / 披露易只编排，解析在 collectors。"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from stock_kb.collectors import hkex as hkex_collector
from stock_kb.collectors import sec as sec_collector
from stock_kb.source_meta import source_meta_path

HttpGet = Callable[..., bytes]
SOFT_KINDS = {"research", "transcript"}
DEFAULT_USER_AGENT = "stock-kb local@localhost"


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_main(cfg: dict[str, Any], args) -> int:
    if args.source and args.url:
        print("fetch: --source 与 --url 不能同时使用")
        return 2
    if not args.company:
        print("fetch: 需要 --company")
        return 2
    if args.source == "sec":
        return fetch_sec(cfg, args.company)
    if args.source == "hkex":
        return fetch_hkex(cfg, args.company)
    if args.url:
        return fetch_url(
            cfg,
            company=args.company,
            url=args.url,
            kind=args.kind,
            optional=bool(args.optional),
        )
    print("fetch: 需要 --url 或 --source sec|hkex")
    return 2


def fetch_many(cfg: dict[str, Any], items: list[dict[str, Any]], *, http_get_fn: HttpGet | None = None) -> int:
    """财报条目失败则整次失败。research / transcript 失败只记 collect_log。"""
    failed = False
    for item in items:
        kind = item.get("kind")
        source = item.get("source")
        company = item.get("company") or ""
        if source == "sec":
            code = fetch_sec(cfg, company, http_get_fn=http_get_fn)
        elif source == "hkex":
            code = fetch_hkex(cfg, company, http_get_fn=http_get_fn)
        else:
            # research / transcript 失败只记日志，不把整次收成失败。
            soft = kind in SOFT_KINDS or bool(item.get("optional"))
            code = fetch_url(
                cfg,
                company=company,
                url=item.get("url") or "",
                kind=kind,
                optional=soft,
                http_get_fn=http_get_fn,
            )
        if code != 0:
            failed = True
    return 1 if failed else 0


def fetch_url(
    cfg: dict[str, Any],
    *,
    company: str,
    url: str,
    kind: str | None = None,
    optional: bool = False,
    http_get_fn: HttpGet | None = None,
) -> int:
    getter = http_get_fn or http_get
    settings = _settings(cfg)
    try:
        if not url:
            raise ValueError("缺少 URL")
        saved = download_to_raw(
            url,
            company=company,
            raw_dir=settings["raw_dir"],
            meta_dir=settings["meta_dir"],
            user_agent=settings["user_agent"],
            http_get_fn=getter,
            kind=kind,
        )
    except Exception as exc:
        if optional:
            _log_failure(settings["data_dir"], company=company, url=url, kind=kind, error=exc)
            print(f"fetch: optional 失败已记录 {company} {url}")
            return 0
        print(f"fetch: 失败 {company} {url}: {exc}")
        return 1
    print(json.dumps(saved, ensure_ascii=False))
    return 0


def fetch_sec(cfg: dict[str, Any], company: str, *, http_get_fn: HttpGet | None = None) -> int:
    getter = http_get_fn or http_get
    settings = _settings(cfg)
    profile = (settings["companies"].get(company) or {}) if company else {}
    cik = str(profile.get("cik") or "").strip()
    if not cik:
        print(f"fetch: {company} 未配置 collect.companies.cik")
        return 1
    url = sec_collector.submissions_url(cik)
    try:
        body = getter(url, sec_collector.sec_headers(settings["user_agent"], json_body=True))
        submissions = json.loads(body.decode("utf-8"))
    except Exception as exc:
        print(f"fetch: {company} 读取 SEC submissions 失败: {exc}")
        return 1
    picked = sec_collector.latest_periodic(submissions)
    annual = picked.get("10-K")
    interim = picked.get("10-Q")
    if annual is None and interim is None:
        print(f"fetch: {company} 未下载到 10-K、10-Q")
        return 1
    saved: list[str] = []
    missing: list[str] = []
    for label, item in (("10-K", annual), ("10-Q", interim)):
        if item is None:
            if label == "10-K":
                missing.append(label)
            continue
        file_url = sec_collector.archive_url(cik, item["accession"], item["primary"])
        try:
            saved.append(
                download_to_raw(
                    file_url,
                    company=company,
                    raw_dir=settings["raw_dir"],
                    meta_dir=settings["meta_dir"],
                    user_agent=settings["user_agent"],
                    http_get_fn=getter,
                    kind=item["kind"],
                    headers=sec_collector.sec_headers(settings["user_agent"], json_body=False),
                )["path"]
            )
        except Exception as exc:
            missing.append(label)
            print(f"fetch: {company} 下载 {label} 失败: {exc}")
    # 没有 10-Q 时只要求 10-K。10-K 没下到，或一份都没下到，都失败。
    if not saved or "10-K" in missing or "10-Q" in missing:
        lack = "、".join(missing or ["10-K", "10-Q"])
        print(f"fetch: {company} 未下载到 {lack}")
        return 1
    print(json.dumps({"company": company, "saved": saved}, ensure_ascii=False))
    return 0


def fetch_hkex(
    cfg: dict[str, Any],
    company: str,
    *,
    http_get_fn: HttpGet | None = None,
    base_url: str | None = None,
) -> int:
    getter = http_get_fn or http_get
    settings = _settings(cfg)
    profile = (settings["companies"].get(company) or {}) if company else {}
    code = str(profile.get("hkex_code") or "").strip()
    if not code:
        print(f"fetch: {company} 未配置 collect.companies.hkex_code")
        return 1
    root = (base_url or hkex_collector.DEFAULT_BASE_URL).rstrip("/")
    headers = {"User-Agent": settings["user_agent"], "Accept": "application/json"}
    try:
        stock_body = getter(hkex_collector.stock_list_url(code, root), headers)
        stock_id = hkex_collector.lookup_stock_id(hkex_collector.parse_json_payload(stock_body), code)
        if not stock_id:
            print(f"fetch: {company} 披露易未解析到 stockId（{code}）")
            return 1
        search_body = getter(hkex_collector.title_search_url(stock_id, root), headers)
        filings = hkex_collector.pick_latest_filings(hkex_collector.parse_json_payload(search_body))
    except Exception as exc:
        print(f"fetch: {company} 披露易查询失败: {exc}")
        return 1
    if not filings:
        print(f"fetch: {company} 未找到年报或中期报告")
        return 1
    saved: list[str] = []
    for kind in ("annual", "interim"):
        item = filings.get(kind)
        if not item:
            continue
        try:
            saved.append(
                download_to_raw(
                    item["file_url"],
                    company=company,
                    raw_dir=settings["raw_dir"],
                    meta_dir=settings["meta_dir"],
                    user_agent=settings["user_agent"],
                    http_get_fn=getter,
                    kind=kind,
                )["path"]
            )
        except Exception as exc:
            print(f"fetch: {company} 下载{kind}失败: {exc}")
    if not saved:
        print(f"fetch: {company} 未下载到年报或中期报告")
        return 1
    print(json.dumps({"company": company, "saved": saved}, ensure_ascii=False))
    return 0


def download_to_raw(
    url: str,
    *,
    company: str,
    raw_dir: Path,
    meta_dir: Path,
    user_agent: str,
    http_get_fn: HttpGet,
    kind: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    req_headers = dict(headers or {"User-Agent": user_agent, "Accept": "*/*"})
    req_headers.setdefault("User-Agent", user_agent)
    try:
        body = http_get_fn(url, req_headers)
    except TypeError:
        body = http_get_fn(url)
    if isinstance(body, str):
        body = body.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    directory = _company_dir(raw_dir, company)
    name = filename_for(url, sha, kind=kind)
    path = directory / name
    path.write_bytes(body)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    side = {
        "origin": "collect",
        "company": company,
        "relative_path": name,
        "source_url": url,
        "retrieved_at": retrieved_at,
        "sha256": sha,
    }
    if kind:
        side["kind"] = kind
    side_path = source_meta_path(Path(meta_dir), "collect", company, name)
    side_path.parent.mkdir(parents=True, exist_ok=True)
    side_path.write_text(json.dumps(side, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "sidecar": str(side_path), "sha256": sha, "source_url": url, "retrieved_at": retrieved_at}


def filename_for(url: str, sha256: str, kind: str | None = None) -> str:
    path = unquote(urlparse(url).path or "")
    name = Path(path.rstrip("/")).name if path else ""
    if not name or name in {".", ".."}:
        name = sha256[:16]
    cleaned = "".join("_" if ch in '<>:"|?*' else ch for ch in name).strip() or sha256[:16]
    # scan 只看文件名。新闻页 URL 往往没有「电话会」，补上前缀才能收成 transcript。
    if kind == "transcript" and not _has_transcript_token(cleaned):
        cleaned = f"transcript-{cleaned}"
    return cleaned


def _has_transcript_token(name: str) -> bool:
    folded = name.lower().replace("_", " ").replace("-", " ")
    return any(token in folded for token in ("电话会", "业绩会", "earnings call", "transcript", "纪要"))


def _company_dir(raw_dir: Path, company: str) -> Path:
    name = str(company or "").strip()
    if not name or name in {".", ".."} or any(part in name for part in ("/", "\\")):
        raise ValueError(f"非法公司名: {company}")
    path = Path(raw_dir) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings(cfg: dict[str, Any]) -> dict[str, Any]:
    data_dir = Path(cfg.get("data_dir") or "data")
    collect = cfg.get("collect") or {}
    if not isinstance(collect, dict):
        collect = {}
    raw = collect.get("raw_dir")
    raw_dir = Path(raw) if raw else data_dir / "raw"
    meta = collect.get("meta_dir")
    meta_dir = Path(meta) if meta else data_dir / "meta"
    if not raw_dir.is_absolute() or not meta_dir.is_absolute():
        root = Path(cfg.get("project_root") or data_dir)
        if not raw_dir.is_absolute():
            raw_dir = root / raw_dir
        if not meta_dir.is_absolute():
            meta_dir = root / meta_dir
    return {
        "data_dir": data_dir,
        "raw_dir": raw_dir,
        "meta_dir": meta_dir,
        "user_agent": collect.get("user_agent") or DEFAULT_USER_AGENT,
        "companies": collect.get("companies") or {},
    }


def _log_failure(data_dir: Path, *, company: str, url: str, kind: str | None, error: Exception) -> None:
    path = Path(data_dir) / "collect_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "company": company,
        "kind": kind,
        "url": url,
        "error": str(error),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
