from __future__ import annotations

import json
from pathlib import Path

from stock_kb.cli import main
from stock_kb.collectors.sec import archive_url
from stock_kb.fetch import fetch_hkex, fetch_many, fetch_sec, fetch_url
from stock_kb.ingest import _process_file, backfill_origins, origin_for, scan
from stock_kb.source_meta import relative_under_origin, source_meta_path
from stock_kb import db


def _cfg(tmp_path) -> dict:
    data = tmp_path / "data"
    data.mkdir()
    return {
        "data_dir": str(data),
        "db_path": str(data / "t.db"),
        "project_root": str(tmp_path),
        "collect": {
            "user_agent": "stock-kb test",
            "raw_dir": str(tmp_path / "raw"),
            "meta_dir": str(tmp_path / "meta"),
            "companies": {
                "百胜中国": {"cik": "0001673358"},
                "海底捞": {"hkex_code": "06862"},
            },
        },
    }


def test_download_writes_sidecar_and_scan_reads_it(tmp_path):
    cfg = _cfg(tmp_path)
    url = "https://broker.example/notes/研报.txt"

    def fake(fetch_url_value, headers=None):
        assert headers["User-Agent"] == "stock-kb test"
        return "研报正文甲".encode("utf-8")

    code = fetch_url(cfg, company="海底捞", url=url, kind="research", http_get_fn=fake)
    assert code == 0
    saved = tmp_path / "raw" / "海底捞" / "研报.txt"
    side_path = tmp_path / "meta" / "collect" / "海底捞" / "研报.txt.source.json"
    side = json.loads(side_path.read_text(encoding="utf-8"))
    assert side["source_url"] == url
    assert side["retrieved_at"]
    assert side["sha256"]
    assert side["origin"] == "collect"
    assert saved.read_bytes()
    assert not (saved.parent / f"{saved.name}.source.json").exists()

    scan_cfg = {
        "nas": {"root": str(tmp_path / "missing-nas"), "companies": ["海底捞"], "exclude_dirs": []},
        "collect": cfg["collect"],
        "db_path": str(tmp_path / "scan.db"),
        "data_dir": str(tmp_path / "scan-data"),
        "ocr": {"enabled": False},
    }
    scan(scan_cfg, companies=["海底捞"], use_ocr=False)
    conn = db.connect(scan_cfg["db_path"])
    row = conn.execute(
        "SELECT source_url, retrieved_at, logical_key, status, origin FROM reports"
    ).fetchone()
    conn.close()
    assert row["status"] == "ok"
    assert row["origin"] == "collect"
    assert row["source_url"] == url
    assert row["retrieved_at"] == side["retrieved_at"]
    assert row["logical_key"].endswith(url)


def test_scan_reads_raw_dir_without_copying_to_nas(tmp_path):
    cfg = _cfg(tmp_path)
    url = "https://ir.example/2024-04-01-transcript.txt"

    def fake(fetch_url_value, headers=None):
        return "电话会正文".encode("utf-8")

    assert fetch_url(
        cfg, company="海底捞", url=url, kind="transcript", http_get_fn=fake
    ) == 0
    scan_cfg = {
        "nas": {
            "root": str(tmp_path / "missing-nas"),
            "companies": ["海底捞"],
            "exclude_dirs": [],
        },
        "collect": cfg["collect"],
        "db_path": str(tmp_path / "raw-scan.db"),
        "data_dir": str(tmp_path / "raw-scan-data"),
        "ocr": {"enabled": False},
    }
    stats = scan(scan_cfg, companies=["海底捞"], use_ocr=False)
    assert stats["parsed"] == 1
    conn = db.connect(scan_cfg["db_path"])
    row = conn.execute(
        "SELECT source_url, report_type, status, origin FROM reports"
    ).fetchone()
    conn.close()
    assert row["status"] == "ok"
    assert row["report_type"] == "transcript"
    assert row["source_url"] == url
    assert row["origin"] == "collect"
    assert not (tmp_path / "missing-nas").exists()


def test_nas_file_without_sidecar_sets_origin_nas(tmp_path):
    nas_root = tmp_path / "nas"
    company_dir = nas_root / "海底捞"
    company_dir.mkdir(parents=True)
    path = company_dir / "2024年报.txt"
    path.write_text("年报正文", encoding="utf-8")
    raw_dir = tmp_path / "raw"
    scan_cfg = {
        "nas": {"root": str(nas_root), "companies": ["海底捞"], "exclude_dirs": []},
        "collect": {"raw_dir": str(raw_dir)},
        "db_path": str(tmp_path / "nas-scan.db"),
        "data_dir": str(tmp_path / "nas-scan-data"),
        "ocr": {"enabled": False},
    }
    stats = scan(scan_cfg, companies=["海底捞"], use_ocr=False)
    assert stats["parsed"] == 1
    conn = db.connect(scan_cfg["db_path"])
    row = conn.execute("SELECT origin, source_url, path FROM reports").fetchone()
    conn.close()
    assert row["origin"] == "nas"
    assert row["source_url"] is None
    assert not (path.parent / f"{path.name}.source.json").exists()
    assert not raw_dir.exists()
    nas_meta = (
        Path(scan_cfg["data_dir"]) / "meta" / "nas" / "海底捞" / "2024年报.txt.source.json"
    )
    written = json.loads(nas_meta.read_text(encoding="utf-8"))
    assert written["origin"] == "nas"
    assert written["relative_path"] == "2024年报.txt"


def test_skip_backfills_origin_and_sidecar(tmp_path):
    nas_root = tmp_path / "nas"
    path = nas_root / "海底捞" / "2024年报.txt"
    path.parent.mkdir(parents=True)
    path.write_text("年报正文", encoding="utf-8")
    db_path = tmp_path / "skip.db"
    conn = db.connect(db_path)
    assert _process_file(conn, {}, "海底捞", path, False, False) is True
    row = conn.execute(
        "SELECT origin, source_url, retrieved_at FROM reports WHERE path=?",
        (str(path),),
    ).fetchone()
    assert row["origin"] is None
    assert row["source_url"] is None
    conn.close()

    sidecar = path.parent / f"{path.name}.source.json"
    sidecar.write_text(
        json.dumps(
            {
                "source_url": "https://ir.example/annual.pdf",
                "retrieved_at": "2026-01-01T00:00:00",
            }
        ),
        encoding="utf-8",
    )
    scan_cfg = {
        "nas": {"root": str(nas_root), "companies": ["海底捞"], "exclude_dirs": []},
        "db_path": str(db_path),
        "data_dir": str(tmp_path / "skip-data"),
        "ocr": {"enabled": False},
    }
    stats = scan(scan_cfg, companies=["海底捞"], use_ocr=False)
    assert stats["parsed"] == 0
    assert stats["skipped"] == 1
    conn = db.connect(db_path)
    row = conn.execute(
        "SELECT origin, source_url, retrieved_at FROM reports WHERE path=?",
        (str(path),),
    ).fetchone()
    conn.close()
    assert row["origin"] == "nas"
    assert row["source_url"] == "https://ir.example/annual.pdf"
    assert row["retrieved_at"] == "2026-01-01T00:00:00"
    migrated = (
        Path(scan_cfg["data_dir"]) / "meta" / "nas" / "海底捞" / "2024年报.txt.source.json"
    )
    copied = json.loads(migrated.read_text(encoding="utf-8"))
    assert copied["source_url"] == "https://ir.example/annual.pdf"
    assert copied["origin"] == "nas"


def test_origin_for_roots(tmp_path):
    nas = tmp_path / "nas"
    raw = tmp_path / "raw"
    nas.mkdir()
    raw.mkdir()
    nas_file = nas / "海底捞" / "a.txt"
    raw_file = raw / "海底捞" / "b.txt"
    nas_file.parent.mkdir()
    raw_file.parent.mkdir()
    nas_file.write_text("a", encoding="utf-8")
    raw_file.write_text("b", encoding="utf-8")
    cfg = {"nas": {"root": str(nas)}, "collect": {"raw_dir": str(raw)}}
    assert origin_for(cfg, nas_file) == "nas"
    assert origin_for(cfg, raw_file) == "collect"
    assert origin_for({}, nas_file) is None
    outside = tmp_path / "other.txt"
    outside.write_text("z", encoding="utf-8")
    assert origin_for(cfg, outside) is None

    nested = nas / "inbox"
    nested.mkdir()
    nested_file = nested / "c.txt"
    nested_file.write_text("c", encoding="utf-8")
    both = {"nas": {"root": str(nas)}, "collect": {"raw_dir": str(nested)}}
    assert origin_for(both, nested_file) == "collect"

    unc_root = r"\\Dxp4800-1305\财报&研报"
    unc_file = Path(unc_root) / "海底捞" / "2018年报.pdf"
    unc_cfg = {"nas": {"root": unc_root}, "collect": {"raw_dir": str(raw)}}
    assert origin_for(unc_cfg, unc_file) == "nas"
    assert relative_under_origin(unc_cfg, unc_file, "nas", "海底捞") == "2018年报.pdf"

    nested_pdf = nas / "海底捞" / "folder" / "a.pdf"
    nested_pdf.parent.mkdir(parents=True, exist_ok=True)
    nested_pdf.write_bytes(b"x")
    assert relative_under_origin(cfg, nested_pdf, "nas", "海底捞") == "folder/a.pdf"
    dest = source_meta_path(tmp_path / "meta", "nas", "海底捞", "folder/a.pdf")
    assert dest == tmp_path / "meta" / "nas" / "海底捞" / "folder" / "a.pdf.source.json"


def test_backfill_origins_from_path_without_file(tmp_path):
    nas = tmp_path / "nas"
    raw = tmp_path / "raw"
    cfg = {"nas": {"root": str(nas)}, "collect": {"raw_dir": str(raw)}}
    conn = db.connect(tmp_path / "backfill.db")
    nas_path = str(nas / "海底捞" / "gone.pdf::superseded::abc")
    raw_path = str(raw / "海底捞" / "x.pdf")
    db.upsert_report(
        conn,
        {
            "company": "海底捞",
            "report_type": "annual",
            "title": "old",
            "path": nas_path,
            "status": "superseded",
        },
    )
    db.upsert_report(
        conn,
        {
            "company": "海底捞",
            "report_type": "research",
            "title": "note",
            "path": raw_path,
            "status": "ok",
        },
    )
    assert backfill_origins(conn, cfg) == 2
    by_path = {
        r["path"]: r["origin"]
        for r in conn.execute("SELECT path, origin FROM reports")
    }
    conn.close()
    assert by_path[nas_path] == "nas"
    assert by_path[raw_path] == "collect"


def test_upsert_origin_none_does_not_clear_existing(tmp_path):
    conn = db.connect(tmp_path / "upsert.db")
    meta = {
        "company": "海底捞",
        "report_type": "other",
        "title": "t",
        "path": str(tmp_path / "a.txt"),
        "status": "ok",
        "origin": "nas",
    }
    db.upsert_report(conn, meta)
    again = dict(meta)
    again["origin"] = None
    db.upsert_report(conn, again)
    row = conn.execute("SELECT origin FROM reports WHERE path=?", (meta["path"],)).fetchone()
    conn.close()
    assert row["origin"] == "nas"


def test_transcript_kind_prefixes_filename_without_keyword(tmp_path):
    cfg = _cfg(tmp_path)
    url = "https://news.example/article/4845187.html"

    def fake(fetch_url_value, headers=None):
        return "<html>业绩会摘录</html>".encode("utf-8")

    assert fetch_url(
        cfg, company="海底捞", url=url, kind="transcript", http_get_fn=fake
    ) == 0
    saved = tmp_path / "raw" / "海底捞" / "transcript-4845187.html"
    assert saved.is_file()
    scan_cfg = {
        "nas": {
            "root": str(tmp_path / "missing-nas"),
            "companies": ["海底捞"],
            "exclude_dirs": [],
        },
        "collect": cfg["collect"],
        "db_path": str(tmp_path / "article-scan.db"),
        "data_dir": str(tmp_path / "article-scan-data"),
        "ocr": {"enabled": False},
    }
    stats = scan(scan_cfg, companies=["海底捞"], use_ocr=False)
    assert stats["parsed"] == 1
    conn = db.connect(scan_cfg["db_path"])
    row = conn.execute(
        "SELECT report_type, logical_key FROM reports"
    ).fetchone()
    conn.close()
    assert row["report_type"] == "transcript"
    assert "|transcript|undated|" in row["logical_key"]
    assert url in row["logical_key"]


def test_optional_failure_exits_zero_and_appends_one_log_line(tmp_path, capsys):
    cfg = _cfg(tmp_path)

    def boom(url, headers=None):
        raise OSError("network down")

    code = fetch_url(
        cfg,
        company="海底捞",
        url="https://ir.example/call.txt",
        kind="transcript",
        optional=True,
        http_get_fn=boom,
    )
    assert code == 0
    log = Path(cfg["data_dir"]) / "collect_log.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["company"] == "海底捞"
    assert record["url"] == "https://ir.example/call.txt"
    assert "network down" in record["error"]
    assert capsys.readouterr().out


def test_sec_zero_filings_exits_nonzero(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    seen = []

    def fake(url, headers=None):
        seen.append((url, headers))
        assert headers["User-Agent"] == "stock-kb test"
        assert headers["Accept"] == "application/json"
        body = {
            "filings": {
                "recent": {
                    "form": ["8-K"],
                    "accessionNumber": ["0001673358-25-000001"],
                    "primaryDocument": ["x.htm"],
                    "filingDate": ["2025-01-02"],
                }
            }
        }
        return json.dumps(body).encode("utf-8")

    code = fetch_sec(cfg, "百胜中国", http_get_fn=fake)
    err = capsys.readouterr().out
    assert code != 0
    assert "百胜中国" in err
    assert "10-K" in err
    assert seen and "CIK0001673358.json" in seen[0][0]


def test_sec_downloads_latest_10k_and_10q(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    body = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-K", "10-Q"],
                "accessionNumber": [
                    "0001673358-24-000010",
                    "0001673358-25-000020",
                    "0001673358-25-000030",
                ],
                "primaryDocument": ["q1.htm", "k.htm", "q2.htm"],
                "filingDate": ["2024-05-01", "2025-03-01", "2025-08-01"],
            }
        }
    }
    expected = {
        archive_url("0001673358", "0001673358-25-000020", "k.htm"),
        archive_url("0001673358", "0001673358-25-000030", "q2.htm"),
    }
    got = []

    def fake(url, headers=None):
        assert headers["User-Agent"] == "stock-kb test"
        if "submissions" in url:
            assert headers["Accept"] == "application/json"
            return json.dumps(body).encode("utf-8")
        got.append(url)
        return b"filing-bytes"

    code = fetch_sec(cfg, "百胜中国", http_get_fn=fake)
    assert code == 0
    assert set(got) == expected
    saved = list((tmp_path / "raw" / "百胜中国").glob("*.htm"))
    assert {p.name for p in saved} == {"k.htm", "q2.htm"}
    assert capsys.readouterr().out


def test_hkex_fake_http_picks_latest_annual_and_interim(tmp_path):
    cfg = _cfg(tmp_path)

    def fake(url, headers=None):
        assert headers["User-Agent"] == "stock-kb test"
        if "prefix.do" in url:
            assert "callback=callback" in url
            return json.dumps([{"code": "06862", "stockId": 4242}]).encode("utf-8")
        if "titleSearchServlet.do" in url:
            assert "stockId=4242" in url
            rows = [
                {
                    "TITLE": "Annual Report 2023",
                    "FILE_LINK": "/listedco/old.pdf",
                    "DATE_TIME": "2024/03/21 16:00",
                },
                {
                    "TITLE": "2024 Annual Report",
                    "FILE_LINK": "/listedco/annual.pdf",
                    "DATE_TIME": "2025/03/21 16:00",
                },
                {
                    "TITLE": "2024 中期报告",
                    "FILE_LINK": "/listedco/interim.pdf",
                    "DATE_TIME": "2024/09/01 16:00",
                },
            ]
            return json.dumps({"result": json.dumps(rows)}).encode("utf-8")
        if url.endswith("/annual.pdf") or url.endswith("/interim.pdf"):
            assert url.startswith("https://www1.hkexnews.hk/listedco/")
            return b"%PDF-" + url.encode("utf-8")
        raise AssertionError(url)

    code = fetch_hkex(cfg, "海底捞", http_get_fn=fake, base_url="https://example.test")
    assert code == 0
    names = {p.name for p in (tmp_path / "raw" / "海底捞").glob("*.pdf")}
    assert names == {"annual.pdf", "interim.pdf"}


def test_hkex_no_filing_exits_nonzero(tmp_path, capsys):
    cfg = _cfg(tmp_path)

    def fake(url, headers=None):
        if "prefix.do" in url:
            return b'[{"c":"6862","i":7}]'
        if "titleSearch" in url:
            return b'{"result":"[]"}'
        raise AssertionError(url)

    code = fetch_hkex(cfg, "海底捞", http_get_fn=fake, base_url="https://example.test")
    assert code != 0
    assert "海底捞" in capsys.readouterr().out


def test_fetch_many_soft_failure_does_not_override_filings(tmp_path):
    cfg = _cfg(tmp_path)
    good = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0001673358-25-000020"],
                "primaryDocument": ["k.htm"],
                "filingDate": ["2025-03-01"],
            }
        }
    }

    def fake_ok(url, headers=None):
        if "submissions" in url:
            return json.dumps(good).encode("utf-8")
        if "Archives" in url:
            return b"k"
        raise OSError("research blocked")

    code = fetch_many(
        cfg,
        [
            {"source": "sec", "company": "百胜中国"},
            {
                "kind": "research",
                "company": "百胜中国",
                "url": "https://example.com/research.pdf",
            },
        ],
        http_get_fn=fake_ok,
    )
    assert code == 0
    log = Path(cfg["data_dir"]) / "collect_log.jsonl"
    assert "research blocked" in log.read_text(encoding="utf-8")

    def fake_empty(url, headers=None):
        if "submissions" in url:
            return json.dumps({"filings": {"recent": {"form": []}}}).encode("utf-8")
        return b"ok"

    code = fetch_many(
        cfg,
        [
            {"source": "sec", "company": "百胜中国"},
            {
                "kind": "transcript",
                "company": "百胜中国",
                "url": "https://example.com/call.txt",
            },
        ],
        http_get_fn=fake_empty,
    )
    assert code != 0


def test_fetch_cli_source_and_url_are_separate(tmp_path, capsys):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "data_dir: data\ndb_path: data/t.db\ncollect:\n  companies: {}\n",
        encoding="utf-8",
    )
    code = main(
        [
            "--config",
            str(cfg_path),
            "fetch",
            "--source",
            "sec",
            "--url",
            "https://example.com/a.pdf",
            "--company",
            "百胜中国",
        ]
    )
    assert code == 2
    assert "不能同时" in capsys.readouterr().out
