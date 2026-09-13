"""抓取雪球用户 modest_（uid 7305934056）专栏的扫描/笔记全文，供风格归纳。

一次性运维脚本（不进回归）。用法：
    python tools/fetch_xueqiu_column.py --min-count 20 [--max-posts 30]

要点（见 docs/process-log.md 雪球条目）：
- 无头 HTTP / jina / 雪球 JSON API 都被 Aliyun WAF 挡；有头真 Chrome 可读。
- 用持久化 profile（data/xueqiu-profile，gitignore 内），验证通过一次后复用 cookie。
- 「滑动验证页面」是阿里云盾 NoCaptcha：找到滑块拖到轨道最右即可；自动拖失败时
  留窗口 120 秒供人工拖动，脚本轮询验证状态后继续。
- 时间线优先页面内同源 fetch 翻页；若仍返回 HTML，则回退为滚动 DOM 收集链接。
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

USER_ID = "7305934056"
BASE = "https://xueqiu.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
PROFILE_DIR = Path("data/xueqiu-profile")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def is_captcha(page) -> bool:
    title = page.title() or ""
    return "验证" in title or "滑动" in title


def _drag_slider(page, handle, track_width: float) -> None:
    box = handle.bounding_box()
    if not box:
        raise RuntimeError("滑块无位置信息")
    sx = box["x"] + box["width"] / 2
    sy = box["y"] + box["height"] / 2
    distance = max(track_width - box["width"] - 6, 100)
    page.mouse.move(sx, sy)
    page.mouse.down()
    steps = random.randint(28, 40)
    moved = 0.0
    for i in range(steps):
        # 拟人轨迹：先慢后快再放缓，带 ±2px 纵向抖动
        ratio = (i + 1) / steps
        ease = ratio ** 0.8
        target = distance * ease
        dx = max(target - moved, 0) + random.uniform(-1.5, 1.5)
        moved += dx
        page.mouse.move(sx + moved, sy + random.uniform(-2, 2))
        time.sleep(random.uniform(0.01, 0.03))
    page.mouse.move(sx + distance + 4, sy)
    time.sleep(random.uniform(0.1, 0.25))
    page.mouse.up()


def solve_slider(page, attempts: int = 4, manual_wait_s: int = 120) -> bool:
    """尝试自动拖阿里云盾滑块；失败则留给人工，轮询标题变化。"""
    for attempt in range(1, attempts + 1):
        frames = [page] + list(page.frames)
        for fr in frames:
            try:
                handle = fr.query_selector("#nc_1_n1z, .btn_slide, [data-role='slider']")
            except Exception:  # noqa: BLE001
                continue
            if not handle:
                continue
            try:
                track = handle.evaluate(
                    "el => el.parentElement ? el.parentElement.clientWidth : 0"
                )
                log(f"自动拖动滑块（第 {attempt} 次，frame={getattr(fr, 'url', '')[:40]}，轨道 {track}px）")
                _drag_slider(page if fr is page else fr, handle, float(track))
            except Exception as e:  # noqa: BLE001
                log(f"  拖动异常：{type(e).__name__} {str(e)[:80]}")
                continue
            page.wait_for_timeout(2500)
            if not is_captcha(page):
                log("验证通过")
                return True
        if attempt < attempts:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
    log(f"自动拖动未通过，浏览器窗口保留 {manual_wait_s}s 供人工滑动…")
    deadline = time.time() + manual_wait_s
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if not is_captcha(page):
            log("检测到验证已通过（人工）")
            return True
    return not is_captcha(page)


def collect_links_dom(page, want: int) -> list[dict]:
    """回退方案：滚动用户页，从 DOM 收集文章链接。"""
    seen: dict[int, dict] = {}
    stagnant = 0
    for _ in range(60):
        links = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({href: a.getAttribute('href') || '', text: (a.innerText || '').trim()}))
                .filter(x => new RegExp('^/7305934056/\\\\d+$').test(x.href))
            """
        )
        for x in links:
            sid = int(x["href"].rsplit("/", 1)[-1])
            if sid not in seen and x["text"]:
                seen[sid] = {"id": sid, "title": x["text"][:80]}
        if len(seen) >= want:
            break
        before = len(seen)
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(1500)
        stagnant = stagnant + 1 if len(seen) == before else 0
        if stagnant >= 6:
            break
    log(f"DOM 收集到 {len(seen)} 个链接")
    return sorted(seen.values(), key=lambda x: x["id"], reverse=True)


def collect_timeline(page, want: int) -> list[dict]:
    items: dict[int, dict] = {}
    for pg in range(1, 15):
        try:
            res = page.evaluate(
                """async (pg) => {
                    const r = await fetch(`/statuses/original/timeline.json?user_id=7305934056&page=${pg}&size=20`,
                        {headers: {'Accept': 'application/json'}});
                    const text = await r.text();
                    try { return {status: r.status, body: JSON.parse(text)}; }
                    catch (e) { return {status: r.status, html: true}; }
                }""",
                pg,
            )
        except Exception as e:  # noqa: BLE001
            log(f"  timeline page {pg}: evaluate 失败 {type(e).__name__}，改走 DOM")
            return collect_links_dom(page, want)
        if res.get("html") or "body" not in res:
            log(f"  timeline page {pg}: 返回非 JSON（WAF），改走 DOM")
            return collect_links_dom(page, want)
        body = res["body"] or {}
        # original/timeline.json 的列表键是 list；v4/user_timeline.json 是 statuses
        statuses = body.get("list") or body.get("statuses") or []
        if not statuses:
            break
        for st in statuses:
            sid = st.get("id")
            if sid and sid not in items:
                items[int(sid)] = {
                    "id": int(sid),
                    "title": (st.get("title") or "").strip(),
                    "created_at": st.get("created_at"),
                }
        log(f"  timeline page {pg}: 累计 {len(items)} 篇")
        if len(items) >= want:
            break
        time.sleep(1.2)
    if len(items) < want:
        dom = collect_links_dom(page, want)
        for x in dom:
            items.setdefault(x["id"], x)
    return sorted(items.values(), key=lambda x: x["id"], reverse=True)


def fetch_article(page, sid: int) -> tuple[str, str]:
    page.goto(f"{BASE}/{USER_ID}/{sid}", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    if is_captcha(page):
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
    title = page.title()
    art = page.evaluate(
        "() => { const el = document.querySelector('article'); return el ? el.innerText : ''; }"
    )
    when = page.evaluate(
        """() => {
            const el = document.querySelector('.article__bd .date-and-source, .date-and-source');
            return el ? el.innerText.trim().replace(/\\s+/g, ' ') : '';
        }"""
    )
    return art, f"{title}|{when}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="eval/style-canon/column")
    ap.add_argument("--min-count", type=int, default=20)
    ap.add_argument("--max-posts", type=int, default=26)
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", dest="headed", action="store_false")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                channel="chrome",
                headless=not args.headed,
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=not args.headed,
                viewport={"width": 1440, "height": 900},
            )
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        page.set_default_timeout(30000)

        log(f"打开用户主页 {BASE}/u/{USER_ID}")
        page.goto(f"{BASE}/u/{USER_ID}", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if is_captcha(page):
            if not solve_slider(page):
                log("滑动验证未通过，退出（重跑本脚本可复用已通过的会话）")
                ctx.close()
                return 2
        log(f"页面标题：{page.title()}")

        items = collect_timeline(page, want=max(args.min_count, args.max_posts) + 12)
        if len(items) < args.min_count:
            log(f"只拿到 {len(items)} 篇候选，不足 {args.min_count}")
            ctx.close()
            return 1
        picked = [x for x in items if re.search(r"扫描|笔记", x["title"])][: args.max_posts]
        if len(picked) < args.min_count:
            picked = items[: args.max_posts]
        log(f"待抓取 {len(picked)} 篇")

        index: list[dict] = []
        for i, it in enumerate(picked, 1):
            try:
                art, meta = fetch_article(page, it["id"])
                ok = len(art) > 600
                log(
                    f"  {i}/{len(picked)} id={it['id']} 《{(it['title'] or meta.split('|')[0])[:30]}》"
                    f" chars={len(art)}{' OK' if ok else ' (太短，跳过)'}"
                )
                if not ok:
                    if is_captcha(page):
                        solve_slider(page, attempts=2, manual_wait_s=60)
                    continue
                created = ""
                if it.get("created_at"):
                    created = datetime.fromtimestamp(
                        it["created_at"] / 1000, tz=timezone.utc
                    ).astimezone().strftime("%Y-%m-%d")
                title = it["title"] or meta.split("|")[0].replace(" - 雪球", "")
                body = (
                    f"# {title}\n\n"
                    f"- 来源：{BASE}/{USER_ID}/{it['id']}\n"
                    f"- 发布：{created or '未知'}（页面标注：{meta.split('|', 1)[-1]}）\n"
                    f"- 抓取：{datetime.now().isoformat(timespec='seconds')}\n\n"
                    f"{art}"
                )
                fname = f"xueqiu-{it['id']}.md"
                (out_dir / fname).write_text(body, encoding="utf-8")
                index.append(
                    {
                        "id": it["id"],
                        "title": title,
                        "url": f"{BASE}/{USER_ID}/{it['id']}",
                        "created": created,
                        "chars": len(art),
                        "file": fname,
                    }
                )
                time.sleep(random.uniform(2.0, 3.5))
            except Exception as e:  # noqa: BLE001
                log(f"  {i}/{len(picked)} id={it['id']} 抓取失败：{type(e).__name__} {str(e)[:80]}")
        ctx.close()

    (out_dir / "index.md").write_text(
        "# modest_ 专栏抓取清单\n\n"
        "| id | 标题 | 发布 | 字数 | 文件 |\n|---|---|---|---:|---|\n"
        + "\n".join(
            f"| {x['id']} | {x['title']} | {x['created']} | {x['chars']} | [{x['file']}]({x['file']}) |"
            for x in index
        )
        + "\n",
        encoding="utf-8",
    )
    log(f"完成：成功 {len(index)} 篇 → {out_dir}/index.md")
    return 0 if len(index) >= args.min_count else 1


if __name__ == "__main__":
    sys.exit(main())
