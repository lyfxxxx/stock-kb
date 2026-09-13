"""定向重建指定报告（重读 NAS + 新解析器 + OCR 乱码闸门）。

与 scan --rebuild 不同：只处理指定 report_id，不动其他文件。
用法：python tools/reprocess_reports.py 35 36
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_kb import db, ingest
from stock_kb.config import load_config


def main(argv: list[str]) -> int:
    ids = [int(a) for a in argv]
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    out = []
    for rid in ids:
        row = conn.execute(
            "SELECT company, path FROM reports WHERE id=?", (rid,)
        ).fetchone()
        if row is None:
            out.append({"report_id": rid, "error": "not found"})
            continue
        path = row["path"]
        t0 = time.time()
        ok = ingest._process_file(
            conn, cfg, row["company"], Path(path), rebuild=True, use_ocr=True
        )
        out.append(
            {
                "report_id": rid,
                "company": row["company"],
                "path": path,
                "ok": bool(ok),
                "seconds": round(time.time() - t0, 1),
            }
        )
    conn.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
