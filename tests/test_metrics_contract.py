"""Structural checks: eval/METRICS_CONTRACT.md stays aligned with EVAL_SYSTEM §5."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "eval" / "METRICS_CONTRACT.md"
EVAL_SYSTEM = ROOT / "eval" / "EVAL_SYSTEM.md"
PROCESS_LOG = ROOT / "docs" / "process-log.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _eval_system_gate_table(text: str) -> str:
    marker = "| 检查 | 门槛 | 最近实测（2026-08-30） |"
    start = text.find(marker)
    assert start >= 0, "EVAL_SYSTEM.md §5 gate table missing"
    rest = text[start:]
    end = rest.find("\nWilson")
    assert end > 0, "EVAL_SYSTEM.md §5 table terminator missing"
    return rest[:end]


def test_contract_exists_and_maps_three_objectives():
    text = _read(CONTRACT)
    assert "门槛合同" in text
    assert "stock-note" in text
    assert "MCP" in text
    assert "embedding" in text.lower()
    assert "docs/process-log.md" in text


def test_contract_gate_table_matches_eval_system_20260830():
    contract = _read(CONTRACT)
    eval_sys = _eval_system_gate_table(_read(EVAL_SYSTEM))

    required = [
        ("FTS keyword Recall@5", "≥ 0.75", "0.80"),
        ("FTS keyword Neg@5", "≤ 0.65", "0.55"),
        ("hybrid semantic Recall@5", "≥ 0.20", "0.15"),
        ("hybrid semantic Neg@5", "≤ 0.20", "0.00"),
        ("结构化 hit / parse_hit", "29/29", "29/29"),
        ("FTS diag indicators", "12/12", "12/12"),
        ("no_answer empty_rate", "1.00", "1.00"),
        ("route accuracy", "1.0", "1.00"),
        ("year_filter precision_mean", "1.00", "1.00"),
        ("generation_compose", "1.00 faithful", "1.00 faithful"),
    ]
    for name, threshold, measured in required:
        assert name in contract, f"contract missing gate {name}"
        assert measured in contract, f"contract missing measured {measured} for {name}"
        assert name in eval_sys or name.split()[0] in eval_sys
        assert threshold in eval_sys or measured in eval_sys

    assert re.search(r"FTS keyword Recall@5.*0\.80", contract)
    assert re.search(r"FTS keyword Neg@5.*0\.55", contract)
    assert re.search(r"hybrid semantic Recall@5.*0\.15", contract)
    assert re.search(r"hybrid semantic Neg@5.*0\.00", contract)
    assert "29/29" in contract and "12/12" in contract
    assert "1.00 faithful" in contract


def test_three_measurement_subsections():
    text = _read(CONTRACT)
    for heading in (
        "Embedding-change measurement",
        "Skill-change measurement",
        "Data-add measurement",
    ):
        idx = text.find(heading)
        assert idx >= 0, f"missing subsection {heading}"
        # subsection body is non-empty before the next heading
        after = text[idx + len(heading) :]
        next_h = re.search(r"\n### ", after)
        body = after[: next_h.start()] if next_h else after[:800]
        assert len(body.strip()) > 80, f"empty subsection {heading}"

    embed_start = text.find("Embedding-change measurement")
    embed_end = text.find("Skill-change measurement")
    embed = text[embed_start:embed_end]
    assert "eval-embed" in embed
    assert "vector@5" in embed and "vector@50" in embed
    assert "不用 FTS keyword 当选模分数" in embed or "不用 FTS keyword" in embed


def test_remaining_gaps_include_required_blockers():
    text = _read(CONTRACT)
    assert "miss@50" in text
    assert "semantic" in text.lower() and "cross" in text.lower()
    assert "6" in text and ("短路" in text or "FTS" in text)
    assert "LLM" in text
    assert "skill" in text.lower()
    assert "engine=fts" in text or 'engine="fts"' in text or "默认 `engine=fts`" in text


def test_questions_section_includes_xueqiu_waf_and_three_plus():
    text = _read(CONTRACT)
    assert "https://xueqiu.com/7305934056/407721579" in text
    assert "WAF" in text or "Playwright" in text
    assert "安井食品扫描" in text
    assert "style-canon" in text
    assert "TEMPLATE.md" in text or "扫描体" in text
    assert "一句话结论" in text and "总结" in text
    questions = re.findall(r"^\d+\. \*\*", text, flags=re.M)
    if len(questions) < 3:
        questions = re.findall(r"^\d+\. ", text, flags=re.M)
    assert len(questions) >= 3, f"need ≥3 numbered questions, got {len(questions)}"
    assert "hybrid semantic" in text
    assert "批量" in text


def test_human_rubric_blocks_publish_not_regression():
    text = _read(ROOT / "eval" / "HUMAN_RUBRIC.md")
    assert "挡发布" in text
    assert "不挡" in text
    assert "run_eval_regression" in text
    # 2026-09-12 模版切换后 R1 骨架为首节「公司简介/股权管理层」
    assert "公司简介/股权管理层" in text
    assert "累计五件套" in text
    assert "判断" in text
    assert "PE" in text
    contract = _read(CONTRACT)
    assert "HUMAN_RUBRIC.md" in contract


def test_process_log_is_designated_resume_record():
    header = _read(PROCESS_LOG).splitlines()[:6]
    blob = "\n".join(header)
    assert "问题与解法" in blob
    contract = _read(CONTRACT)
    assert "docs/process-log.md" in contract
    assert "现象" in contract and "原因" in contract and "解决" in contract and "教训" in contract
