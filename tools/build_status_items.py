# -*- coding: utf-8 -*-
"""按最近一次评测重建 docs/status/items.js（现状页的逐题判定）。

静态字段（gate / metric / metricLabel / expected / contexts）沿用现有 items.js：
这些是题目与答案页的属性，不随检索结果变化，重生成时保留可避免文案漂移。
动态字段（verdict / group / answer / extra / hits）按最新的 freeze + diag、
FTS + hybrid 四份报告重算。

用法：
    python tools/build_status_items.py
    python tools/build_status_items.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from stock_kb import db
from stock_kb.config import load_config
from stock_kb.eval_runner import fold_fact_text

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "docs" / "status" / "items.js"
REPORTS = ROOT / "eval" / "reports"

# 计入门槛的题型；其余（diag 语义、cross、end2end）只展示。
GATED_TYPES = {"exact", "keyword", "indicator", "no_answer", "route", "year_filter"}


def load_reports() -> dict[tuple[str, str], dict]:
    """每个 (engine, split) 取时间最新的一份 json。"""

    best: dict[tuple[str, str], tuple[str, dict]] = {}
    for path in REPORTS.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta") or {}
        engine, split = meta.get("engine"), meta.get("split")
        if not engine or not split or "results" not in data:
            continue
        key = (engine, split)
        stamp = str(meta.get("timestamp") or path.stem)
        if key not in best or stamp > best[key][0]:
            best[key] = (stamp, data)
    return {k: v[1] for k, v in best.items()}


def index_results(reports: dict) -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    for (engine, split), data in reports.items():
        for row in data["results"]:
            out[(engine, split, row["id"])] = row
    return out


def page_text(conn, conn_cache: dict, title: str, page: int) -> str:
    key = (title, page)
    if key not in conn_cache:
        row = conn.execute(
            "SELECT p.content FROM pages p JOIN reports r ON r.id = p.report_id "
            "WHERE r.title = ? AND p.page_no = ?",
            (title, page),
        ).fetchone()
        conn_cache[key] = (row["content"] or "") if row else ""
    return conn_cache[key]


def excerpt(conn, cache, row: dict, phrases: list[str]) -> str:
    """截取命中页里短语前后各约 36 字，用 [] 标出短语。

    只在原文上按字面找：先用归一化位置去切原文会错位（归一化去掉了换行和逗号，
    下标与原文不一致），宁可退化成页首，也不给出错乱的片段。
    """

    text = page_text(conn, cache, row.get("title", ""), row.get("page", 0))
    if not text:
        return ""
    for phrase in phrases:
        raw = str(phrase)
        at = text.find(raw)
        if at >= 0:
            head = text[max(0, at - 36) : at]
            tail = text[at + len(raw) : at + len(raw) + 36]
            return f"...{head}[{raw}]{tail}..."
    return f"{text[:90]}..."


def fmt_hits(rows: list[dict], limit: int = 5) -> str:
    if not rows:
        return "空"
    parts = []
    for i, row in enumerate(rows[:limit], start=1):
        parts.append(f"{i}. 《{row['title']}》第{row['page']}页")
    return "；".join(parts)


def judge(q: dict, rows: dict, phrases: list[str]) -> dict:
    """返回 {hit, answer, extra, verdict, group, hits}。"""

    t = q.get("type")
    split = q.get("split") or "freeze"
    fts = rows.get(("fts", split, q["id"])) or {}
    hyb = rows.get(("hybrid", split, q["id"])) or {}
    fts_ret = fts.get("retrieval") or {}
    hyb_ret = hyb.get("retrieval") or {}
    fts_tops = fts_ret.get("top_hits") or []
    hyb_tops = hyb_ret.get("top_hits") or []

    if t in ("exact", "cross") and (q.get("statement") or {}):
        st_res = fts.get("structured") or {}
        ok = bool(st_res.get("hit"))
        st_q = q.get("statement") or {}
        val = st_q.get("expected_value")
        if val is None:
            val = (q.get("expected") or {}).get("answer")
        unit = st_q.get("expected_unit") or ""
        srcs = (q.get("expected") or {}).get("sources") or []
        locs = []
        for s in srcs[:2]:
            seg = f"《{s['file']}》第{s['page']}页"
            if s.get("table"):
                seg += f"（{s['table']}）"
            locs.append(seg)
        loc = "；".join(locs) if locs else "对照页缺失"
        if isinstance(val, (int, float)):
            answer = f"{val:,} {unit}，{loc}".replace(" ，", "，")
        else:
            answer = loc
        if not ok:
            answer = f"结构化未匹配到对照行（应为 {val} {unit}）" if isinstance(val, (int, float)) else "结构化未匹配到对照行"
        return {
            "hit": ok,
            "verdict": "相符" if ok else "未命中",
            "answer": answer,
            "extra": "" if ok else "三表行未对上对照页；结构化为准，不按全文召回判这题。",
            "hits": None,
        }

    if t == "cross":
        # 没有 statement 的跨语言题只展示：按检索是否回到对照页判，不按结构化。
        ok = bool(fts_ret.get("hit")) or bool(hyb_ret.get("hit"))
        answer = f"hybrid：{fmt_hits(hyb_tops)}" if hyb_tops else "hybrid：空"
        return {
            "hit": ok,
            "verdict": "命中" if ok else "未命中",
            "answer": answer,
            "extra": f"FTS：{'空' if not fts_tops else fmt_hits(fts_tops)}。跨语言没有单独门槛，只展示。",
            "group": "pass" if ok else "display-miss",
            "hits": {
                "hybrid": {
                    "query": hyb_ret.get("query") or "",
                    "fused": bool(hyb_ret.get("hybrid_fused")),
                    "rows": [
                        {
                            "title": h["title"],
                            "page": h["page"],
                            "expected": bool(h.get("expected")),
                            "negative": bool(h.get("negative")),
                            "kind": h.get("kind") or "page",
                            "excerpt": "",
                            "year": h.get("year"),
                        }
                        for h in hyb_tops[:5]
                    ],
                }
            },
        }

    if t == "keyword":
        ok = bool(fts_ret.get("hit"))
        hyb_ok = bool(hyb_ret.get("hit"))
        rank = fts_ret.get("rank")
        answer = (
            f"FTS：{fmt_hits(fts_tops)}" if ok else "FTS：空"
        )
        extra = f"hybrid {'也命中' if hyb_ok else '未命中'}。hybrid 前5：{fmt_hits(hyb_tops)}。门槛看 FTS。"
        group = "pass" if ok else ("hybrid-drop" if hyb_ok else "gate-miss")
        if not ok and hyb_ok:
            extra = f"FTS 未命中、hybrid 命中。hybrid 前5：{fmt_hits(hyb_tops)}。门槛看 FTS，这一题算未过。"
        return {
            "hit": ok,
            "verdict": f"命中（第{rank}位）" if ok and rank else ("命中" if ok else "未命中"),
            "answer": answer,
            "extra": extra,
            "group": group,
            "hits": {"fts": {"query": fts_ret.get("query") or "", "rows": [
                {
                    "title": h["title"],
                    "page": h["page"],
                    "expected": bool(h.get("expected")),
                    "negative": bool(h.get("negative")),
                    "kind": h.get("kind") or "page",
                    "excerpt": "",
                    "year": h.get("year"),
                }
                for h in fts_tops[:5]
            ]}},
        }

    if t == "semantic":
        ok = bool(hyb_ret.get("hit")) if split == "freeze" else bool(hyb_ret.get("hit"))
        rank = hyb_ret.get("rank")
        fused = "是" if hyb_ret.get("hybrid_fused") else "否"
        answer = f"hybrid：{fmt_hits(hyb_tops)}" if hyb_tops else "hybrid：空"
        extra = (
            f"FTS {'命中' if fts_ret.get('hit') else '未命中'}。FTS 前5：{fmt_hits(fts_tops)}。融合：{fused}。"
        )
        if split == "freeze":
            extra += "这题计入门槛；整组门槛是 0.85。"
            group = "pass" if ok else "gate-miss"
        else:
            extra += "诊断题，不卡住回归测试。"
            group = "pass" if ok else "display-miss"
        return {
            "hit": ok,
            "verdict": f"命中（第{rank}位）" if ok and rank else ("命中" if ok else "未命中"),
            "answer": answer,
            "extra": extra,
            "group": group,
            "hits": {"hybrid": {"query": hyb_ret.get("query") or "", "fused": bool(hyb_ret.get("hybrid_fused")), "rows": [
                {
                    "title": h["title"],
                    "page": h["page"],
                    "expected": bool(h.get("expected")),
                    "negative": bool(h.get("negative")),
                    "kind": h.get("kind") or "page",
                    "excerpt": "",
                    "year": h.get("year"),
                }
                for h in hyb_tops[:5]
            ]}},
        }

    if t == "indicator":
        ind = fts.get("indicator") or hyb.get("indicator") or {}
        ok = bool(ind.get("hit"))
        mr = (ind.get("matched_rows") or [{}])[0]
        answer = (
            f"{mr.get('value'):,} {mr.get('unit') or ''}，第{mr.get('page_no')}页"
            if isinstance(mr.get("value"), (int, float))
            else "未取到指标行"
        )
        return {
            "hit": ok,
            "verdict": "相符" if ok else "未命中",
            "answer": answer,
            "extra": "" if ok else "指标表未取到对照值。",
            "hits": None,
        }

    if t == "no_answer":
        f_empty = not fts_tops
        h_empty = not hyb_tops
        ok = f_empty and h_empty

        def _rows(tops: list[dict]) -> list[dict]:
            return [
                {
                    "title": h["title"],
                    "page": h["page"],
                    "expected": bool(h.get("expected")),
                    "negative": bool(h.get("negative")),
                    "kind": h.get("kind") or "page",
                    "excerpt": "",
                    "year": h.get("year"),
                }
                for h in tops[:5]
            ]

        return {
            "hit": ok,
            "verdict": "应空" if ok else "未空",
            "answer": f"FTS：{'空' if f_empty else fmt_hits(fts_tops)}。hybrid：{'空' if h_empty else fmt_hits(hyb_tops)}。",
            "extra": "" if ok else "库外问句返回了页，这条不算通过（noans-006 瑞幸在库属预期）。",
            "hits": {
                "fts": {"query": fts_ret.get("query") or "", "rows": _rows(fts_tops)},
                "hybrid": {
                    "query": hyb_ret.get("query") or "",
                    "fused": bool(hyb_ret.get("hybrid_fused")),
                    "rows": _rows(hyb_tops),
                },
            },
        }

    if t == "route":
        rt = fts.get("route") or {}
        ok = bool(rt.get("hit"))
        name = (rt.get("decision") or {}).get("name")
        answer = f"分到 {rt.get('predicted')}" + (f"（{name}）" if name else "")
        return {
            "hit": ok,
            "verdict": "相符" if ok else "未命中",
            "answer": answer,
            "extra": f"对照是 {rt.get('expected')}",
            "hits": None,
        }

    if t == "year_filter":
        yf = fts.get("year_filter") or {}
        ok = float(yf.get("precision") or 0) >= 0.6
        answer = (
            f"FTS {yf.get('year_matched')}/{yf.get('n_hits')} 页年份相符。前5：{fmt_hits(fts_tops)}"
        )
        return {
            "hit": ok,
            "verdict": "相符" if ok else "未命中",
            "answer": answer,
            "extra": f"问句年份 {yf.get('query_years')}。",
            "hits": {"fts": {"query": fts_ret.get("query") or "", "rows": [
                {
                    "title": h["title"],
                    "page": h["page"],
                    "expected": bool(h.get("expected")),
                    "negative": bool(h.get("negative")),
                    "kind": h.get("kind") or "page",
                    "excerpt": "",
                    "year": h.get("year"),
                }
                for h in fts_tops[:5]
            ]}},
        }

    if t == "end2end":
        ok = bool(hyb_ret.get("hit"))
        answer = f"hybrid：{fmt_hits(hyb_tops)}" if hyb_tops else "hybrid：空"
        return {
            "hit": ok,
            "verdict": "命中" if ok else "未命中",
            "answer": answer,
            "extra": f"FTS：{'空' if not fts_tops else fmt_hits(fts_tops)}。这题不卡住回归测试。",
            "group": "pass" if ok else "display-miss",
            "hits": {"hybrid": {"query": hyb_ret.get("query") or "", "fused": bool(hyb_ret.get("hybrid_fused")), "rows": [
                {
                    "title": h["title"],
                    "page": h["page"],
                    "expected": bool(h.get("expected")),
                    "negative": bool(h.get("negative")),
                    "kind": h.get("kind") or "page",
                    "excerpt": "",
                    "year": h.get("year"),
                }
                for h in hyb_tops[:5]
            ]}},
        }

    return {"hit": False, "verdict": "未判定", "answer": "", "extra": "", "hits": None}


def main() -> int:
    ap = argparse.ArgumentParser(description="按最新评测重建 docs/status/items.js")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    cache: dict = {}
    questions = {q["id"]: q for q in yaml.safe_load(open(ROOT / "eval" / "questions.yaml", encoding="utf-8"))["questions"]}
    reports = load_reports()
    print("报告:", {f"{k[0]}:{k[1]}": v["meta"].get("timestamp") for k, v in reports.items()})
    rows = index_results(reports)

    raw = ITEMS.read_text(encoding="utf-8")
    old = json.loads(raw[raw.index("["): raw.rindex("]") + 1])

    out = []
    changed = []
    for tpl in old:
        q = questions.get(tpl["id"])
        if not q:
            out.append(tpl)
            continue
        phrases = [str(p) for p in (q.get("expected") or {}).get("accept_phrases") or []]
        res = judge(q, rows, phrases)
        item = dict(tpl)
        item["verdict"] = res["verdict"]
        item["answer"] = res["answer"]
        item["extra"] = res["extra"]
        if res.get("group"):
            item["group"] = res["group"]
        elif res["hit"]:
            item["group"] = "pass"
        else:
            item["group"] = "gate-miss" if q.get("type") in GATED_TYPES else "display-miss"
        if res["hits"]:
            for engine, block in res["hits"].items():
                for row in block["rows"]:
                    row["excerpt"] = excerpt(conn, cache, row, phrases)
            item["hits"] = res["hits"]
        if (item.get("verdict"), item.get("group"), item.get("answer")) != (
            tpl.get("verdict"),
            tpl.get("group"),
            tpl.get("answer"),
        ):
            changed.append(f'{tpl["id"]}: {tpl.get("verdict")}/{tpl.get("group")} -> {item["verdict"]}/{item["group"]}')
        out.append(item)

    conn.close()
    from collections import Counter

    print("group:", dict(Counter(i.get("group") for i in out)))
    print(f"变化 {len(changed)} 条")
    for line in changed[:40]:
        print("  ", line)

    if args.dry_run:
        print("[dry-run] 未写入")
        return 0

    ITEMS.write_text(
        "window.STATUS_ITEMS=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"已写入 {ITEMS}（{len(out)} 条，{ITEMS.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
