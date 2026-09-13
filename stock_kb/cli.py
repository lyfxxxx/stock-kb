from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stock_kb import db, eval_runner, ingest, search
from stock_kb.config import load_config


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="stock-kb", description="财报知识库 CLI")
    parser.add_argument("--config", help="配置文件路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="扫描并解析 NAS 财报/研报")
    p_scan.add_argument("--company", action="append", help="只处理指定公司，可重复")
    p_scan.add_argument("--limit", type=int, help="最多解析文件数（调试用）")
    p_scan.add_argument("--rebuild", action="store_true", help="忽略 manifest 强制重建")
    p_scan.add_argument("--no-ocr", action="store_true", help="禁用 OCR")
    p_scan.add_argument("--watch-interval", type=int, default=0, help="自动扫描间隔秒数，0=关闭（默认）")

    p_search = sub.add_parser("search", help="全文检索")
    p_search.add_argument("query")
    p_search.add_argument("--company")
    p_search.add_argument("--top-k", type=int, default=5)
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--hybrid", action="store_true", help="混合检索（需要已建向量索引；等同 --engine hybrid）")
    p_search.add_argument(
        "--engine",
        choices=["fts", "vector", "hybrid"],
        default=None,
        help="检索方式；默认 fts，指定 --hybrid 时为 hybrid",
    )
    p_search.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    p_search.add_argument("--year", type=int, default=None)
    p_search.add_argument("--report-type", default=None)
    p_search.add_argument("--language", default=None)

    p_stats = sub.add_parser("stats", help="统计入库情况")
    p_stats.add_argument("--json", action="store_true")

    p_eval = sub.add_parser("eval", help="运行检索评测")
    p_eval.add_argument("--top-k", type=int, default=None)
    p_eval.add_argument(
        "--engine",
        choices=["fts", "vector", "hybrid"],
        default=None,
        help="检索方式；默认：不指定 --model 时为 fts，指定 --model 时为 hybrid",
    )
    p_eval.add_argument(
        "--model",
        default=None,
        help="向量/混合检索使用的嵌入模型；未指定时读取 config 的 embedding.model",
    )
    p_eval.add_argument(
        "--search-path",
        choices=["mcp_compat", "eval_rrf_keywords"],
        default="mcp_compat",
        help="mcp_compat：单 query，与 MCP search_reports 一致；eval_rrf_keywords：旧多关键词 RRF",
    )
    p_eval.add_argument(
        "--split",
        default=None,
        help="只评 questions.yaml 中 split 字段匹配的题；缺省 split 视为 freeze",
    )

    p_ee = sub.add_parser(
        "eval-embed",
        help="embedding 模型筛选（vector@5/@50 分桶；可对比候选）",
    )
    p_ee.add_argument(
        "--base",
        default=None,
        help="基线模型，默认 config embedding.model",
    )
    p_ee.add_argument(
        "--challenger",
        action="append",
        default=None,
        help="候选模型，可重复",
    )
    p_ee.add_argument(
        "--models",
        default=None,
        help="逗号分隔的模型列表：第一项当基线，其余当候选",
    )

    p_index = sub.add_parser("index", help="构建向量索引")
    p_index.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    p_index.add_argument("--limit", type=int, default=None)
    p_index.add_argument(
        "--rebuild",
        action="store_true",
        help="只重建当前模型的向量，不重切 chunks",
    )
    p_index.add_argument(
        "--rebuild-chunks",
        action="store_true",
        help="按 embedding.chunk_size 重切全部页面；会清空所有模型的向量索引",
    )

    p_reclassify = sub.add_parser("reclassify", help="按文件名/目录重新分类已有报告")
    p_dedupe = sub.add_parser("dedupe", help="按 SHA-256 标记重复报告并保留 canonical 版本")

    p_statements = sub.add_parser("statements", help="查询三表行项目")
    p_statements.add_argument("--company", required=True)
    p_statements.add_argument(
        "--type",
        dest="statement_type",
        help="income / balance / cashflow / equity",
    )
    p_statements.add_argument("--year", type=int, default=None)
    p_statements.add_argument("--period-type", default=None)
    p_statements.add_argument("--keyword", help="科目名片段，如 已付股息 / 减值 / 资本开支")
    p_statements.add_argument("--limit", type=int, default=20)
    p_statements.add_argument("--json", action="store_true")
    p_statements.add_argument(
        "--include-comparatives",
        action="store_true",
        help="包含次年报比较列（默认只要当年年报正文）",
    )

    p_quote = sub.add_parser(
        "quote",
        help="最新收盘价/市值与 TTM PE（yfinance 优先，akshare 兜底；失败则非零退出）",
    )
    p_quote.add_argument("--company", required=True)
    p_quote.add_argument("--json", action="store_true")

    p_route = sub.add_parser("route", help="按 skill 规则判断该走哪把工具")
    p_route.add_argument("question")
    p_route.add_argument("--company")
    p_route.add_argument("--json", action="store_true")

    p_compose = sub.add_parser(
        "compose-note",
        help="按 skill 工具顺序组稿一篇可审计笔记（不含模型判断）",
    )
    p_compose.add_argument("--company", required=True)
    p_compose.add_argument("--out-dir", default=None)

    p_egen = sub.add_parser(
        "eval-generation",
        help="组稿试点公司笔记并审计引用是否落在页文本上",
    )

    p_indicators = sub.add_parser("indicators", help="从三表计算常用财务指标")

    p_reparse = sub.add_parser("reparse-statements", help="从已存页面文本重算三表（不重读 NAS）")
    p_reparse.add_argument("--company")

    p_mcp = sub.add_parser("mcp", help="启动 MCP 服务")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_mcp.add_argument("--host", default="127.0.0.1")
    p_mcp.add_argument("--port", type=int, default=8931)

    p_models = sub.add_parser("models", help="模型下载与管理")
    p_models_sub = p_models.add_subparsers(dest="models_cmd", required=True)
    p_dl = p_models_sub.add_parser("download", help="下载模型（支持镜像/加速/续传）")
    p_dl.add_argument("--model", required=True)
    p_dl.add_argument("--cache-dir", default=None)
    p_dl.add_argument("--mirror", default=None)
    p_dl.add_argument("--no-accelerate", action="store_true")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "scan":
        if args.watch_interval and args.watch_interval > 0:
            import time

            while True:
                try:
                    result = ingest.scan(
                        cfg,
                        companies=args.company,
                        limit=args.limit,
                        rebuild=args.rebuild,
                        use_ocr=not args.no_ocr,
                    )
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                except Exception as exc:
                    print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
                time.sleep(args.watch_interval)
        else:
            result = ingest.scan(
                cfg,
                companies=args.company,
                limit=args.limit,
                rebuild=args.rebuild,
                use_ocr=not args.no_ocr,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "eval-embed":
        from stock_kb.embed_eval import run_cli as run_embed_cli

        return run_embed_cli(cfg, args)

    if args.cmd == "eval-generation":
        from stock_kb.generation_eval import run_generation_eval

        report = run_generation_eval(cfg)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return 0 if report["summary"]["fail_count"] == 0 else 1

    if args.cmd == "quote":
        from stock_kb import quotes

        conn = db.connect(cfg["db_path"])
        try:
            q = quotes.fetch_quote(args.company, cfg)
            ttm = quotes.ttm_net_profit(conn, args.company)
            pe = quotes.pe_ttm(q, ttm["ttm_profit"], ttm["currency"])
            payload = {**q, "ttm": ttm, "valuation": pe}
        except quotes.QuoteError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        finally:
            conn.close()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "route":
        from stock_kb.route import route

        decision = route(args.question, company=args.company)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "compose-note":
        from stock_kb.note_builder import compose_note

        out_dir = Path(args.out_dir) if args.out_dir else None
        meta = compose_note(cfg, args.company, out_dir=out_dir)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    conn = db.connect(cfg["db_path"])
    if args.cmd == "search":
        engine = args.engine or ("hybrid" if args.hybrid else "fts")
        if engine == "fts":
            hits = search.fts_search(
                conn, args.query, company=args.company, top_k=args.top_k,
                year=args.year,
                report_type=args.report_type,
                language=args.language,
            )
        else:
            from stock_kb import vector

            if engine == "vector":
                hits = vector.vector_search(
                    conn,
                    args.model,
                    args.query,
                    top_k=args.top_k,
                    company=args.company,
                    cache_dir=cfg["models_dir"],
                    backend=cfg.get("embedding", {}).get("backend", "auto"),
                    year=args.year,
                    report_type=args.report_type,
                    language=args.language,
                )
            else:
                hits = vector.hybrid_search(
                    conn,
                    args.query,
                    model=args.model,
                    top_k=args.top_k,
                    company=args.company,
                    cache_dir=cfg["models_dir"],
                    backend=cfg.get("embedding", {}).get("backend", "auto"),
                    year=args.year,
                    report_type=args.report_type,
                    language=args.language,
                )
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        else:
            for h in hits:
                print(f"{h['company']} | {h['title']} | 第{h['page_no']}页")
                print(f"  {h['snippet']}")
        conn.close()
        return 0

    if args.cmd == "stats":
        data = search.stats(conn)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for k, v in data.items():
                if k != "reports_by_type":
                    print(f"{k}: {v}")
            print("reports_by_type:")
            for r in data["reports_by_type"]:
                print(f"  {r['company']} / {r['report_type']}: {r['n']}")
        conn.close()
        return 0

    if args.cmd == "eval":
        data = eval_runner.run_eval(
            cfg,
            top_k=args.top_k,
            model=args.model,
            engine=args.engine,
            search_path=args.search_path,
            split=args.split,
        )
        report = eval_runner.save_report(cfg, data)
        print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
        print(f"报告：{report}")
        return 0

    if args.cmd == "index":
        from stock_kb import vector

        result = vector.build_index(
            cfg,
            model=args.model,
            limit=args.limit,
            rebuild=args.rebuild,
            rebuild_chunks=args.rebuild_chunks,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "reclassify":
        from stock_kb.classify import classify_report

        rows = conn.execute("SELECT id, path FROM reports").fetchall()
        updated = 0
        for r in rows:
            meta = classify_report(r["path"])
            cjk = 0
            total_chars = 0
            for page in conn.execute(
                "SELECT content, char_count FROM pages WHERE report_id=?", (r["id"],)
            ):
                text = page["content"] or ""
                cjk += sum("一" <= ch <= "鿿" for ch in text)
                total_chars += max(page["char_count"] or 0, len(text))
            if total_chars:
                language = "zh" if cjk / total_chars >= 0.02 else "en"
            else:
                language = meta["language"]
            conn.execute(
                "UPDATE reports SET report_type=?, language=?, year=?, period_type=? WHERE id=?",
                (
                    meta["report_type"],
                    language,
                    meta["year"],
                    meta["period_type"],
                    r["id"],
                ),
            )
            updated += 1
        conn.commit()
        conn.close()
        print(json.dumps({"updated": updated}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "dedupe":
        marked = db.mark_duplicate_reports(conn)
        conn.close()
        print(json.dumps({"duplicates_marked": marked}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "statements":
        from stock_kb.textutil import to_simplified

        kw = to_simplified(args.keyword).strip() if args.keyword else None
        rows = db.query_statements(
            conn,
            args.company,
            statement_type=args.statement_type,
            year=args.year,
            period_type=args.period_type,
            keyword=kw or None,
            limit=args.limit,
            include_comparatives=args.include_comparatives,
        )
        conn.close()
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "indicators":
        from stock_kb import indicators

        result = indicators.compute_indicators(cfg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "reparse-statements":
        from stock_kb import reparse

        result = reparse.reparse_statements(cfg, company=args.company)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "mcp":
        from stock_kb.serve import run_mcp

        run_mcp(cfg, transport=args.transport, host=args.host, port=args.port)
        return 0

    if args.cmd == "models":
        import subprocess
        import sys

        tool = str(Path(__file__).resolve().parent.parent / "tools" / "download_models.py")
        cmd = [sys.executable, tool, "--model", args.model]
        if getattr(args, "cache_dir", None):
            cmd += ["--cache-dir", args.cache_dir]
        if getattr(args, "mirror", None):
            cmd += ["--mirror", args.mirror]
        if getattr(args, "no_accelerate", False):
            cmd += ["--no-accelerate"]
        return subprocess.call(cmd)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
