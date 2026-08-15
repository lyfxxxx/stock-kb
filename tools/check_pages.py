import sqlite3

conn = sqlite3.connect(r"D:\workspace\stock-kb\data\stock_kb.db")
conn.row_factory = sqlite3.Row


def show(title_like, page, needle, size=260):
    row = conn.execute(
        """
        SELECT p.content, r.title FROM pages p JOIN reports r ON r.id=p.report_id
        WHERE r.title LIKE ? AND p.page_no=? LIMIT 1
        """,
        (f"%{title_like}%", page),
    ).fetchone()
    if not row:
        print("NOT FOUND", title_like, page)
        return
    idx = row["content"].find(needle)
    if idx < 0:
        idx = 0
    print(f"--- {row['title']} p{page} [{needle}]")
    print(row["content"][idx : idx + size].replace("\n", " "))


show("阿米巴", 25, "激励")
show("阿米巴", 26, "激励")
show("快餐业龙头", 2, "门店")
show("快餐业龙头", 4, "门店")
show("2025投资者日", 2, "门店")
show("2025Q2", 2, "门店")
