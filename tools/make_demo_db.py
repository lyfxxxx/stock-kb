# -*- coding: utf-8 -*-
"""从本地库导出一个可公开的小库，让别人不用 NAS 也能跑起来。

只挑年报 / 中报 / 业绩公告（不含研报与电话会，避免整本转载），
再按「题目所有对照页都落在这批文档里」筛出配套题集。

用法：
    python tools/make_demo_db.py --docs 8
    python tools/make_demo_db.py --docs 8 --out data/demo_stock_kb.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db
from stock_kb.config import load_config

ROOT = Path(__file__).resolve().parents[1]
# 只导出这三类：公开披露文件，页文本可引用；研报与电话会不整本转载。
ALLOWED_TYPES = ("annual", "interim", "other")


def pick_reports(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, company, title, report_type, year, period_type "
        "FROM reports WHERE status = 'ok' AND COALESCE(is_duplicate, 0) = 0 "
        f"AND report_type IN ({','.join('?' * len(ALLOWED_TYPES))}) "
        "ORDER BY company, year DESC, report_type",
        ALLOWED_TYPES,
    ).fetchall()
    by_company: dict[str, list[dict]] = {}
    for r in rows:
        by_company.setdefault(r["company"], []).append(dict(r))
    picked: list[dict] = []
    # 每家公司轮流取，保证 demo 里两家都在
    while len(picked) < limit and any(by_company.values()):
        for company in list(by_company):
            if not by_company[company]:
                continue
            picked.append(by_company[company].pop(0))
            if len(picked) >= limit:
                break
    return picked


def build(src_path: str, out_path: Path, docs: list[dict]) -> None:
    if out_path.exists():
        out_path.unlink()
    conn = db.connect(str(out_path))
    conn.execute("ATTACH DATABASE ? AS src", (src_path,))
    ids = [d["id"] for d in docs]
    marks = ",".join("?" * len(ids))

    def copy(table: str, where: str = "", params: tuple = ()) -> None:
        """按列名复制，不用 SELECT *。

        主库经过多次 ALTER TABLE 迁移，列顺序与新建的空库不同（origin 在后加
        的表里位置不一致），`INSERT ... SELECT *` 会整体错位——实测把
        logical_key 写进了 supersedes_id。只复制两边都有的列。
        """
        dst_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        src_cols = {r[1] for r in conn.execute(f"PRAGMA src.table_info({table})")}
        cols = [c for c in dst_cols if c in src_cols]
        collist = ",".join(f'"{c}"' for c in cols)
        conn.execute(f"INSERT INTO {table} ({collist}) SELECT {collist} FROM src.{table} {where}", params)

    copy("companies")
    copy("reports", f"WHERE id IN ({marks})", ids)
    copy("pages", f"WHERE report_id IN ({marks})", ids)
    copy("statements", f"WHERE report_id IN ({marks})", ids)
    copy("chunks", "WHERE page_id IN (SELECT id FROM pages)")
    copy("indicators")
    conn.execute(
        "INSERT INTO pages_fts(page_id, company, report_id, content) "
        "SELECT p.id, r.company, p.report_id, p.content FROM pages p "
        "JOIN reports r ON r.id = p.report_id"
    )
    # 脱敏：reports.path 原本是 `\\NAS主机\共享\...` 或本机绝对路径，
    # demo 库要入库，只留「公司/文种/文件名」，不暴露内网拓扑与本机目录。
    # logical_key 的末段有时直接是完整路径（`公司|文种|\\NAS\...pdf`），同样处理。
    for row in conn.execute("SELECT id, company, report_type, path, logical_key FROM reports").fetchall():
        name = PureWindowsPath(str(row["path"] or "")).name or f'{row["id"]}.pdf'
        conn.execute(
            "UPDATE reports SET path=? WHERE id=?",
            (f'{row["company"]}/{row["report_type"]}/{name}', row["id"]),
        )
        lk = row["logical_key"]
        if lk and "|" in str(lk):
            parts = [
                PureWindowsPath(seg).name if ("\\" in seg or "/" in seg) else seg
                for seg in str(lk).split("|")
            ]
            conn.execute(
                "UPDATE reports SET logical_key=? WHERE id=?", ("|".join(parts), row["id"])
            )
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.execute("VACUUM")
    conn.close()


def filter_questions(docs: list[dict], out: Path) -> int:
    titles = [d["title"] for d in docs]

    def covered(sources: list[dict]) -> bool:
        if not sources:
            return False
        return all(any(s["file"] in title for title in titles) for s in sources)

    data = yaml.safe_load(open(ROOT / "eval" / "questions.yaml", encoding="utf-8"))
    keep = []
    for q in data["questions"]:
        if covered((q.get("expected") or {}).get("sources") or []):
            keep.append(q)
    by_type: dict[str, int] = {}
    for q in keep:
        by_type[q["type"]] = by_type.get(q["type"], 0) + 1
    payload = {
        "meta": {
            "note": "demo 题集：由 tools/make_demo_db.py 从 eval/questions.yaml 自动筛出，"
            "只保留对照页都落在 demo 库里的题。",
            "source_questions": "eval/questions.yaml",
            "types": by_type,
        },
        "questions": keep,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return len(keep)


def main() -> int:
    ap = argparse.ArgumentParser(description="导出可公开的 demo 小库")
    ap.add_argument("--docs", type=int, default=8, help="导出文档数（默认 8，两家轮流取）")
    ap.add_argument("--out", default=str(ROOT / "demo" / "demo_stock_kb.db"))
    ap.add_argument("--questions", default=str(ROOT / "demo" / "questions_demo.yaml"))
    args = ap.parse_args()

    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    docs = pick_reports(conn, args.docs)
    conn.close()
    if not docs:
        print("没有可导出的文档")
        return 2
    print(f"选中 {len(docs)} 份：")
    for d in docs:
        print(f"  [{d['report_type']}] {d['company']} {d['title']}")

    out = Path(args.out)
    build(cfg["db_path"], out, docs)
    n = filter_questions(docs, Path(args.questions))
    size = out.stat().st_size / 1024 / 1024
    print(f"\n已生成 {out}（{size:.1f} MB）")
    print(f"配套题集 {args.questions}（{n} 道）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
