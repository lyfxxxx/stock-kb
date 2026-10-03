import json

from stock_kb.retrieval_log import append_retrieval, read_log


def test_log_keeps_title_and_page_only(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_KB_RUN_ID", "env-1")
    cfg = {"data_dir": str(tmp_path)}
    append_retrieval(
        cfg,
        tool="search",
        query="翻台率",
        company="海底捞",
        year=None,
        engine="fts",
        params={"top_k": 1},
        hits=[{"title": "2024年报", "page_no": 19, "content": "SECRET 正文"}],
    )
    rows = read_log(tmp_path / "retrieval_log.jsonl")
    assert rows[0]["run_id"] == "env-1"
    assert rows[0]["tool"] == "search"
    assert rows[0]["hits"] == [{"title": "2024年报", "page": 19}]
    raw = (tmp_path / "retrieval_log.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in raw
    assert json.loads(raw)


def test_run_id_override_and_null(tmp_path, monkeypatch):
    monkeypatch.delenv("STOCK_KB_RUN_ID", raising=False)
    cfg = {"data_dir": str(tmp_path)}
    append_retrieval(
        cfg,
        tool="statements",
        query="收入",
        company="海底捞",
        year=2024,
        engine=None,
        params={},
        hits=[],
    )
    append_retrieval(
        cfg,
        tool="search",
        query="翻台率",
        company="海底捞",
        year=None,
        engine="fts",
        params={},
        hits=[{"title": "研报", "page": 3}],
        run_id="cli-9",
    )
    rows = read_log(tmp_path / "retrieval_log.jsonl")
    assert rows[0]["run_id"] is None
    assert rows[1]["run_id"] == "cli-9"
    assert rows[1]["hits"] == [{"title": "研报", "page": 3}]
