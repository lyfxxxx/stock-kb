"""把 stock-note 正式稿 Markdown 装配为单文件扫描 HTML。

用法：python tools/assemble_note_html.py --md <正式稿.md> --ref-html <组稿.html> --out <正式稿.html>

规则：复用组稿 HTML 的 <style>、ECharts 图块（按 {{FIG:fig-xxx}} 标记）与页尾脚本；
MD 解析仅支持本 skill 用到的子集：h1/h2/h3、meta 引用行、tags 行、段落、判断段
（「判断：」起头）、markdown 表、编号/无序列表、**加粗**。
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path


def esc(v: str) -> str:
    return html.escape(v, quote=True)


def inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(text))
    # 注释号 [n] → 可点击上标，跳到文末注释区对应行
    text = re.sub(
        r"\[(\d+)\]",
        r'<sup class="nref"><a href="#note-\1">\1</a></sup>',
        text,
    )
    return text


def md_to_body(md: str, company: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    tags_done = False
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("# ") and not tags_done:
            i += 1
            continue
        if line.startswith("> ") and not tags_done:
            out.append(f'<p class="meta">{inline(line[2:].strip())}</p>')
            i += 1
            continue
        if line.startswith("$") and not tags_done:
            # 雪球 $公司(代码)$ 标签行：独立 HTML 里渲染成去 $ 的标签，避免「未渲染模板」观感
            chips = re.findall(r"\$([^$]+)\$", line)
            out.append(
                '<p class="tags">'
                + "  ".join(f'<span class="tag">{inline(c.strip())}</span>' for c in chips)
                + "</p>"
            )
            tags_done = True
            i += 1
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:].strip())}</h3>")
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("{{FIG:"):
            marker = line.strip()
            out.append(marker)
            i += 1
            continue
        if line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head = rows[0]
            is_note_table = head and head[0] == "注"
            body_rows = []
            for r in rows[1:]:
                rid = f' id="note-{esc(r[0])}"' if is_note_table and r and r[0].isdigit() else ""
                body_rows.append(f"<tr{rid}>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append(
                f'<table class="{"cite notes" if is_note_table else "cite"}"><thead><tr>'
                + "".join(f"<th>{inline(c)}</th>" for c in head)
                + "</tr></thead><tbody>"
                + "".join(body_rows)
                + "</tbody></table>"
            )
            continue
        m = re.match(r"^(\d+)\.\s+(.*)", line)
        if m:
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i]).strip())
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ol>")
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:].strip())
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        text = line.strip()
        if text.startswith("判断："):
            out.append(f'<p class="judge"><strong>判断：</strong>{inline(text[3:])}</p>')
        else:
            out.append(f"<p>{inline(text)}</p>")
        i += 1
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--ref-html", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    md = Path(args.md).read_text(encoding="utf-8")
    ref = Path(args.ref_html).read_text(encoding="utf-8")

    company_m = re.search(r"^# (.+)$", md.splitlines()[0]) if md.startswith("# ") else None
    company = company_m.group(1).strip() if company_m else "公司"
    company = re.sub(r"扫描$", "", company)

    css_m = re.search(r"<style>(.*?)</style>", ref, re.S)
    css = css_m.group(1) if css_m else ""
    css += (
        "\nh3 { font-size:16px; margin:20px 0 8px; }"
        "\n.judge strong { color:#c45911; }"
        "\n.tag { margin-right:12px; }"
        # 组稿样式无 .judge（组稿不写判断）；正式稿判断段在此补齐
        "\n.judge { background:#f3f0e8; border-left:3px solid #c45911; padding:8px 12px; max-width:72ch; }"
        # 正文出处表固定列宽（指标|年份|数值|单位|同比），避免自动布局把窄列压成竖排
        "\ntable.cite:not(.notes) { table-layout:fixed; }"
        "\ntable.cite:not(.notes) th:nth-child(1), table.cite:not(.notes) td:nth-child(1) { width:28%; }"
        "\ntable.cite:not(.notes) th:nth-child(2), table.cite:not(.notes) td:nth-child(2) { width:13%; }"
        "\ntable.cite:not(.notes) th:nth-child(3), table.cite:not(.notes) td:nth-child(3) { width:27%; }"
        "\ntable.cite:not(.notes) th:nth-child(4), table.cite:not(.notes) td:nth-child(4) { width:14%; }"
        "\ntable.cite:not(.notes) th:nth-child(5), table.cite:not(.notes) td:nth-child(5) { width:18%; }"
        # 注释号上标与文末注释区锚点；相邻上标由相邻 nw span 补逗号分隔
        "\nsup.nref { font-size:11px; line-height:0; }"
        "\nsup.nref a { color:#1f4e79; text-decoration:none; }"
        "\nspan.nw { white-space:nowrap; }"
        "\nspan.nw + span.nw sup.nref::before { content:',\\00a0'; color:#6b6458; font-size:11px; }"
        "\ntr[id^='note-']:target { background:#f3f0e8; }"
        # 注释表：固定列宽、出处列可换行不溢出
        "\ntable.notes { table-layout:fixed; }"
        "\ntable.notes th, table.notes td { overflow-wrap:anywhere; }"
        "\ntable.notes th:nth-child(1), table.notes td:nth-child(1) { width:5%; }"
        "\ntable.notes th:nth-child(2), table.notes td:nth-child(2) { width:18%; }"
        "\ntable.notes th:nth-child(3), table.notes td:nth-child(3) { width:37%; }"
        "\ntable.notes th:nth-child(4), table.notes td:nth-child(4) { width:40%; }"
    )

    figs = {}
    for m in re.finditer(r'<figure class="chart-fig">\s*<div id="(fig-[a-z]+)".*?</figure>', ref, re.S):
        figs[m.group(1)] = m.group(0)
    scripts = re.findall(r"<script>.*?</script>", ref, re.S)
    tail = "\n".join(scripts)

    body = md_to_body(md, company)
    # 上标孤行修复：逐个上标包装（前文字 + 上标 + 紧随标点 → nowrap）。
    # 注意不能用 <sup>.*?</sup> 的贪婪回溯匹配——会跨上标把大段正文裹进 nowrap。
    sup_re = re.compile(
        r"([^<>]{0,2})(<sup class=\"nref\"><a href=\"#note-\d+\">\d+</a></sup>)([。，；、）」』]?)"
    )
    wrapped: list[str] = []
    last_end = 0
    prev_sup = False
    for m in sup_re.finditer(body):
        prev, sup, punct = m.group(1), m.group(2), m.group(3)
        wrapped.append(body[last_end:m.start()])
        comma = ",\u00a0" if prev_sup and not prev.strip() else ""
        wrapped.append(f'<span class="nw">{prev}{comma}{sup}{punct}</span>')
        last_end = m.end()
        prev_sup = True
    wrapped.append(body[last_end:])
    body = "".join(wrapped)
    for fig_id in set(re.findall(r"\{\{FIG:(fig-[a-z]+)\}\}", body)):
        block = figs.get(fig_id)
        if block is None:
            raise SystemExit(f"figure {fig_id} not found in ref html")
        body = body.replace("{{FIG:" + fig_id + "}}", block)

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(company)}扫描</title>
<style>{css}</style>
</head>
<body>
<main>
{body}
</main>
<noscript>图表需启用 JavaScript 查看；各节数字出处见对应表格与文末引用明细。</noscript>
{tail}
</body>
</html>
"""
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"OK -> {args.out} ({len(doc)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
