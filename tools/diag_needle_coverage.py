# -*- coding: utf-8 -*-
"""1a 校准：问句实体词在该公司当前使用文档（非 OCR）的命中页数。

验收线（docs/retrieval-fix-plan-20261025.md §4 1a）：
- noans-002/003/004/005/007 实体全 0 命中（预检可判空）；
- noans-006 不全 0 命中（瑞幸在库，会返回页，是 ≥7/8 用掉的那 1 题）；
- freeze 语义 20 + diag 语义 13 + diag 跨语言 15 无一道全 0 命中（误空 = 0）；
- 抽词规格样例：noans-003 的实体列表只含「欧洲门店数量」。

剥词表改动后必须重跑本脚本，全绿才允许把预检合并进 hybrid_search。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db, search
from stock_kb.config import load_config

MUST_EMPTY = {"noans-002", "noans-003", "noans-004", "noans-005", "noans-007"}
MUST_NOT_EMPTY = {"noans-006"}


def count_pages(conn, entity: str, company: str | None) -> int:
    return conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM pages p JOIN reports r ON r.id = p.report_id
        WHERE (:c IS NULL OR r.company = :c)
          AND {db.live_report_sql("r")}
          AND COALESCE(p.is_ocr, 0) < 2
          AND ({search._fold_sql("p.content")} LIKE :l
               OR {search._fold_sql("p.content_orig")} LIKE :l)
        """,
        {"c": company, "l": f"%{entity}%"},
    ).fetchone()["n"]


def main() -> int:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    qs = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "eval" / "questions.yaml", encoding="utf-8"))
    items = qs.get("questions", qs)

    groups = [
        ("no_answer", [q for q in items if q.get("type") == "no_answer"]),
        ("freeze 语义", [q for q in items if q.get("type") == "semantic" and (q.get("split") or "freeze") == "freeze"]),
        ("diag 语义", [q for q in items if q.get("type") == "semantic" and q.get("split") == "diag"]),
        ("diag 跨语言", [q for q in items if q.get("type") == "cross" and q.get("split") == "diag"]),
    ]

    violations: list[str] = []
    for gname, group in groups:
        print(f"\n== {gname}（{len(group)} 题） ==")
        for q in group:
            words = search.entity_words(q["question"], q.get("company"))
            cov = []
            for w in words:
                cov.append((w, count_pages(conn, w, q.get("company"))))
            all_absent = bool(words) and all(c == 0 for _, c in cov)
            mark = ""
            if q["id"] in MUST_EMPTY and not all_absent:
                mark = "  << 应可判空而不可"
                violations.append(f"{q['id']}: 应全 0 命中，实际 {cov}")
            if q["id"] in MUST_NOT_EMPTY and all_absent:
                mark = "  << 误空风险"
                violations.append(f"{q['id']}: 会误空，实体 {cov}")
            if gname != "no_answer" and all_absent:
                mark = "  << 误空"
                violations.append(f"{q['id']}: 语义/跨语言题被预检判空，实体 {cov}")
            detail = " ".join(f"{w}:{c}" for w, c in cov) if cov else "(无实体)"
            print(f"{q['id']:<13} 全缺席={str(all_absent):<5} {detail}{mark}")

    print("\n== 抽词规格样例 ==")
    spec = search.entity_words("百胜中国欧洲门店数量", "百胜中国")
    ok = spec == ["欧洲门店数量"]
    print(f"noans-003 实体列表 = {spec}  {'✓' if ok else '✗（含「欧洲」则预检规则不得合并）'}")
    if not ok:
        violations.append(f"抽词规格样例不符：{spec}")

    print(f"\n==== 校准结果：{'通过' if not violations else f'{len(violations)} 处违规'} ====")
    for v in violations:
        print(" -", v)
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
