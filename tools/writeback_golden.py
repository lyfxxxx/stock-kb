"""把已确认的独立 golden 回写到 eval/questions.yaml（尽量保留周围文本）。

确认文件是 JSON 列表，每项至少含:
    id, decision (agree|reject), expected_value, expected_unit,
    expected_currency, page, annotator, reviewed_at, golden_source,
    evidence_snippet

decision=agree 时回写；reject 时只打日志不改题。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_kb.config import load_config

_ID_RE = re.compile(r"^  - id: ([^\s]+)\s*$", re.M)


def _blocks(text: str) -> list[tuple[str, int, int]]:
    matches = list(_ID_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1), start, end))
    return out


def _replace_field(block: str, key: str, value: str, indent: str = "      ") -> str:
    pattern = re.compile(rf"^({re.escape(indent)}{re.escape(key)}:\s*).*$", re.M)
    replacement = rf"\g<1>{value}"
    if pattern.search(block):
        return pattern.sub(replacement, block, count=1)
    # insert after expected_currency if present, else after expected_value
    anchor = re.compile(r"^      expected_currency:.*$", re.M)
    m = anchor.search(block)
    if not m:
        anchor = re.compile(r"^      expected_value:.*$", re.M)
        m = anchor.search(block)
    if not m:
        return block
    insert = f"{m.group(0)}\n{indent}{key}: {value}"
    return block[: m.start()] + insert + block[m.end() :]


def _ensure_source_fields(block: str, evidence: str, annotator: str) -> str:
    if "evidence_snippet:" in block:
        return block
    src = re.search(r'^          required: true\s*$', block, re.M)
    if not src:
        return block
    extra = (
        f"{src.group(0)}\n"
        f"          annotator: {json.dumps(annotator, ensure_ascii=False)}\n"
        f"          evidence_snippet: {json.dumps(evidence, ensure_ascii=False)}"
    )
    return block[: src.start()] + extra + block[src.end() :]


def patch_block(block: str, item: dict) -> str:
    value = item["expected_value"]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    block = _replace_field(block, "expected_value", str(value))
    if item.get("expected_unit"):
        block = _replace_field(
            block, "expected_unit", json.dumps(item["expected_unit"], ensure_ascii=False)
        )
    if item.get("expected_currency"):
        block = _replace_field(
            block,
            "expected_currency",
            json.dumps(item["expected_currency"], ensure_ascii=False),
        )
    block = _replace_field(
        block, "golden_source", json.dumps(item.get("golden_source") or "pdf")
    )
    block = _replace_field(
        block, "annotator", json.dumps(item.get("annotator") or "user", ensure_ascii=False)
    )
    block = _replace_field(
        block,
        "reviewed_at",
        json.dumps(item.get("reviewed_at") or "", ensure_ascii=False),
    )
    if item.get("evidence_snippet"):
        block = _ensure_source_fields(
            block, item["evidence_snippet"], item.get("annotator") or "user"
        )
    return block


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("confirmed", help="已确认的 JSON 列表")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    q_path = Path(cfg["eval"]["questions"])
    items = json.loads(Path(args.confirmed).read_text(encoding="utf-8"))
    text = q_path.read_text(encoding="utf-8")
    blocks = _blocks(text)
    by_id = {qid: (start, end) for qid, start, end in blocks}
    changed = 0
    for item in items:
        qid = item["id"]
        if item.get("decision") != "agree":
            print(f"skip {qid} decision={item.get('decision')}")
            continue
        if qid not in by_id:
            raise SystemExit(f"题库中没有 {qid}")
        start, end = by_id[qid]
        new_block = patch_block(text[start:end], item)
        if new_block != text[start:end]:
            text = text[:start] + new_block + text[end:]
            # refresh offsets after this id by rebuilding at end of loop would be safer
            changed += 1
            print("patched", qid)
        else:
            print("unchanged", qid)
        blocks = _blocks(text)
        by_id = {qid2: (s, e) for qid2, s, e in blocks}
    if args.dry_run:
        print("dry-run, not writing;", "would patch", changed)
        return 0
    q_path.write_text(text, encoding="utf-8")
    print("wrote", q_path, "patched", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
