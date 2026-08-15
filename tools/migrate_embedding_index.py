import sqlite3
import time

import sqlite_vec

conn = sqlite3.connect(r"D:\workspace\stock-kb\data\stock_kb.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)
conn.execute("DROP TABLE IF EXISTS embedding_index")
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS embedding_index (
        model TEXT NOT NULL,
        page_id INTEGER NOT NULL,
        dim INTEGER NOT NULL,
        indexed_at TEXT,
        PRIMARY KEY(model, page_id)
    )
    """
)
now = time.strftime("%Y-%m-%dT%H:%M:%S")
for table, model, dim in [
    ("chunks_vec_512", "BAAI/bge-small-zh-v1.5", 512),
    ("chunks_vec_384", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384),
]:
    conn.execute(
        f"INSERT OR IGNORE INTO embedding_index(model, page_id, dim, indexed_at) "
        f"SELECT ?, page_id, ?, ? FROM {table}",
        (model, dim, now),
    )
conn.commit()
print(conn.execute("SELECT model, COUNT(*) n FROM embedding_index GROUP BY model").fetchall())
