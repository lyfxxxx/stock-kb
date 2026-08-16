import sqlite3

from stock_kb import db, vector
from stock_kb.config import load_config

cfg = load_config()
conn = db.connect(cfg["db_path"])
db.load_vector_extension(conn)
print("models:", [dict(r) for r in conn.execute("SELECT model, vec_table, COUNT(*) n, dim FROM embedding_index GROUP BY model, vec_table, dim").fetchall()])
print("chunks:", conn.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"])
for name in db.vector_table_names(conn):
    print(f"{name}:", conn.execute(f"SELECT COUNT(*) n FROM {name}").fetchone()["n"])
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
