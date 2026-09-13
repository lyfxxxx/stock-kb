"""一次性回填：把已入库的 OCR 噪声页与 cid 乱码页标记为 is_ocr=2。

is_ocr 语义：0 正常 / 1 OCR 成功 / 2 内容不可用（OCR 输出无效或 cid 乱码），
is_ocr=2 的页保留在 pages/pages_fts 中（保持一对一镜像），但检索侧排除。

用法：python tools/backfill_ocr_quality.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_kb import db
from stock_kb.config import load_config
from stock_kb.parsers.pdf_parser import _cid_ratio, _CID_GARBLED_RATIO, _text_quality_ok


def main() -> int:
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    rows = conn.execute("SELECT id, content, is_ocr FROM pages").fetchall()
    ocr_noise = cid_garbled = 0
    for r in rows:
        content = r["content"] or ""
        if r["is_ocr"] == 1 and not _text_quality_ok(content):
            conn.execute("UPDATE pages SET is_ocr=2 WHERE id=?", (r["id"],))
            ocr_noise += 1
        elif r["is_ocr"] == 0 and _cid_ratio(content) > _CID_GARBLED_RATIO:
            conn.execute("UPDATE pages SET is_ocr=2 WHERE id=?", (r["id"],))
            cid_garbled += 1
    conn.commit()
    conn.close()
    print(json.dumps(
        {"pages_scanned": len(rows), "ocr_noise_marked": ocr_noise,
         "cid_garbled_marked": cid_garbled},
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
