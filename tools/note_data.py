"""从 stock-kb 提取两家试点公司最新年报的经营细节片段（供笔记引用）。"""

import sqlite3

conn = sqlite3.connect(r"D:\workspace\stock-kb\data\stock_kb.db")
conn.row_factory = sqlite3.Row


def show(company: str, title_like: str, terms: list[str], limit: int = 8) -> None:
    print(f"\n######## {company} / {title_like}")
    rows = conn.execute(
        """
        SELECT p.page_no, p.content, r.title FROM pages p
        JOIN reports r ON r.id = p.report_id
        WHERE r.company=? AND r.title LIKE ?
        ORDER BY p.page_no
        """,
        (company, title_like),
    ).fetchall()
    shown = 0
    seen = set()
    for r in rows:
        content = r["content"]
        for term in terms:
            idx = content.find(term)
            key = (r["page_no"], term)
            if idx >= 0 and key not in seen:
                seen.add(key)
                snippet = content[max(0, idx - 80) : idx + 140].replace("\n", " ")
                print(f"p{r['page_no']} [{term}] {snippet}")
                shown += 1
                if shown >= limit:
                    return


show("海底捞", "%2025年报%", ["餐厅数量", "餐厅", "翻台率", "客单价", "同店"])
show("百胜中国", "%2025_Annual_Report%", ["restaurants", "same-store sales", "store count"])
show("百胜中国", "%2025_HK_Annual_Report%", ["同店", "门店", "餐厅"])


def context(company: str, title_like: str, needle: str, before: int = 100, after: int = 220) -> None:
    row = conn.execute(
        """
        SELECT p.page_no, p.content FROM pages p
        JOIN reports r ON r.id = p.report_id
        WHERE r.company=? AND r.title LIKE ? AND p.content LIKE ?
        ORDER BY p.page_no LIMIT 1
        """,
        (company, title_like, f"%{needle}%"),
    ).fetchone()
    if row:
        idx = row["content"].find(needle)
        print(f"\nCTX p{row['page_no']} [{needle}]")
        print(row["content"][max(0, idx - before) : idx + after].replace("\n", " "))


context("海底捞", "%2025年报%", "顾客人均消费")
context("百胜中国", "%2025_Annual_Report%", "same-store sales")
context("百胜中国", "%2025_Annual_Report%", "restaurants as of December 31, 2025")
