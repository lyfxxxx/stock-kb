import sqlite3

from stock_kb import db, vector
from stock_kb.config import load_config

cfg = load_config()
conn = db.connect(cfg["db_path"])
db.load_vector_extension(conn)
print("models:", [dict(r) for r in conn.execute("SELECT model, COUNT(*) n, dim FROM embedding_index GROUP BY model, dim").fetchall()])
print("chunks:", conn.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"])
print("vec512:", conn.execute("SELECT COUNT(*) n FROM chunks_vec_512").fetchone()["n"])
print("vec384:", conn.execute("SELECT COUNT(*) n FROM chunks_vec_384").fetchone()["n"])
try:
    hits = vector.vector_search(
        conn,
        "BAAI/bge-small-zh-v1.5",
        "海底捞的现金流质量怎么样？",
        top_k=5,
        cache_dir=cfg["models_dir"],
        backend="sentence-transformers",
    )
    print("hits:", len(hits))
    for h in hits[:5]:
        print("  ", h["company"], h["title"][:40], "p", h["page_no"], "score", h["score"])
except Exception as e:
    print("ERR", type(e).__name__, e)
