"""迁移向量索引到分块模式：清空旧 page 级索引，重建 chunks 与 embedding_index 表。"""

import sqlite3

import sqlite_vec

conn = sqlite3.connect(r"D:\workspace\stock-kb\data\stock_kb.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)

conn.execute("DROP TABLE IF EXISTS embedding_index")
conn.execute("DROP TABLE IF EXISTS chunks_vec_512")
conn.execute("DROP TABLE IF EXISTS chunks_vec_384")
conn.execute("DROP TABLE IF EXISTS chunks_vec_768")
conn.execute("DROP TABLE IF EXISTS chunks")
conn.commit()

conn.execute(
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        page_id INTEGER NOT NULL REFERENCES pages(id),
        chunk_no INTEGER NOT NULL,
        content TEXT,
        UNIQUE(page_id, chunk_no)
    )
    """
)
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS embedding_index (
        model TEXT NOT NULL,
        chunk_id INTEGER NOT NULL,
        dim INTEGER NOT NULL,
        indexed_at TEXT,
        PRIMARY KEY(model, chunk_id)
    )
    """
)
conn.commit()
print("migrated")
