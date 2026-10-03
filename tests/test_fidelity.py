from __future__ import annotations

import pytest

from stock_kb import db
from stock_kb.cli import main
from stock_kb.fidelity import SKIPPED_LINE, fidelity_main, run_fidelity


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _report(conn, title: str, path: str, status: str, text: str, report_type: str = "annual"):
    conn.execute(
        "INSERT INTO reports(company, report_type, title, path, status, is_duplicate) "
        "VALUES(?,?,?,?,?,0)",
        ("海底捞", report_type, title, path, status),
    )
    report_id = conn.execute("SELECT id FROM reports WHERE path=?", (path,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO pages(report_id, page_no, content, content_orig, char_count, is_ocr) "
        "VALUES(?,?,?,?,?,0)",
        (report_id, 142, text, text, len(text)),
    )
    conn.commit()


def test_fidelity_missing_sentence_fails_and_ignores_superseded(conn):
    _report(conn, "2024年报", "/old.txt", "superseded", "原文里有这句营业收入")
    _report(conn, "2024年报", "/live.txt", "ok", "这一页没有目标原句")
    result = run_fidelity(
        conn,
        [
            {
                "company": "海底捞",
                "title_contains": "2024年报",
                "page_no": 142,
                "report_type": "annual",
                "is_ocr": 0,
                "needles": ["原文里有这句营业收入"],
            }
        ],
    )
    assert result["passed"] is False
    assert result["items"][0]["ok"] is False
    assert result["items"][0]["missing_needles"] == ["原文里有这句营业收入"]
    assert result["groups"] == [{"report_type": "annual", "is_ocr": 0, "hit": 0, "total": 1}]


def test_fidelity_hit_and_ocr_miss_does_not_fail(conn):
    _report(conn, "2024年报", "/live.txt", "ok", "原文里有这句营业收入")
    _report(conn, "电话会纪要", "/call.txt", "ok", "没有那句", report_type="transcript")
    result = run_fidelity(
        conn,
        [
            {
                "company": "海底捞",
                "title_contains": "2024年报",
                "page_no": 142,
                "report_type": "annual",
                "is_ocr": 0,
                "needles": ["原文里有这句营业收入"],
            },
            {
                "company": "海底捞",
                "title_contains": "电话会",
                "page_no": 142,
                "report_type": "transcript",
                "is_ocr": 1,
                "needles": ["必须出现的 OCR 句"],
            },
        ],
    )
    assert result["passed"] is True
    assert result["non_ocr_miss"] == 0
    assert result["ocr_miss"] == 1
    groups = {(g["report_type"], g["is_ocr"]): g for g in result["groups"]}
    assert groups[("annual", 0)]["hit"] == 1
    assert groups[("transcript", 1)]["hit"] == 0


def test_fidelity_empty_spec_exits_zero_and_says_skipped(tmp_path, capsys):
    pages = tmp_path / "empty.yaml"
    pages.write_text("pages: []\n", encoding="utf-8")
    cfg = {"db_path": str(tmp_path / "missing.db"), "project_root": str(tmp_path), "data_dir": str(tmp_path)}
    code = fidelity_main(cfg, pages=str(pages), as_json=False)
    assert code == 0
    assert capsys.readouterr().out.strip() == SKIPPED_LINE

    code = fidelity_main(cfg, pages=str(tmp_path / "no-such.yaml"), as_json=True)
    captured = capsys.readouterr().out
    assert code == 0
    assert "skipped" in captured
    assert "not a pass" in captured


def test_fidelity_cli_default_missing_file_skips(tmp_path, capsys):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("data_dir: data\ndb_path: data/none.db\n", encoding="utf-8")
    code = main(["--config", str(cfg_path), "fidelity"])
    assert code == 0
    assert "skipped" in capsys.readouterr().out
