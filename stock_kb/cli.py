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
    p_search.add_argument("--hybrid", action="store_true", help="混合检索（需要已建向量索引）")
    p_search.add_argument("--model", default="BAAI/bge-small-zh-v1.5")

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

    p_index = sub.add_parser("index", help="构建向量索引")
    p_index.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    p_index.add_argument("--limit", type=int, default=None)
    p_index.add_argument("--rebuild", action="store_true")

    p_reclassify = sub.add_parser("reclassify", help="按文件名/目录重新分类已有报告")

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
                result = ingest.scan(
                    cfg,
                    companies=args.company,
                    limit=args.limit,
                    rebuild=args.rebuild,
                    use_ocr=not args.no_ocr,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
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

    conn = db.connect(cfg["db_path"])
    if args.cmd == "search":
        if args.hybrid:
            from stock_kb import vector

            hits = vector.hybrid_search(
                conn,
                args.query,
                model=args.model,
                top_k=args.top_k,
                company=args.company,
                cache_dir=cfg["models_dir"],
                backend=cfg.get("embedding", {}).get("backend", "auto"),
            )
        else:
            hits = search.fts_search(
                conn, args.query, company=args.company, top_k=args.top_k
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
            cfg, top_k=args.top_k, model=args.model, engine=args.engine
        )
        report = eval_runner.save_report(cfg, data)
        print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
        print(f"报告：{report}")
        return 0

    if args.cmd == "index":
        from stock_kb import vector

        result = vector.build_index(
            cfg, model=args.model, limit=args.limit, rebuild=args.rebuild
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "reclassify":
        from stock_kb.classify import classify_report

        rows = conn.execute("SELECT id, path FROM reports").fetchall()
        updated = 0
        for r in rows:
            meta = classify_report(r["path"])
            conn.execute(
                "UPDATE reports SET report_type=?, language=?, year=?, period_type=? WHERE id=?",
                (
                    meta["report_type"],
                    meta["language"],
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
