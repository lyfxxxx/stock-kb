---
name: stock-collect
description: 只查找并下载财报、电话会文字稿和研报直链。不写报告，不替代 stock-note。
---

# stock-collect：收集原文

本技能和 `skill/stock-note` 分开。这里只负责把文件下载到本机；笔记和报告仍由 stock-note 写。

下载落在配置 `collect.raw_dir`（默认 `data/raw/{公司}/`）。出处 JSON 落在 `collect.meta_dir`（默认 `data/meta/collect/{公司}/{相对路径}.source.json`，含 `source_url`、`retrieved_at`、`sha256`）。`scan` 会把 NAS 和网络文件的 metadata 都写进 `meta_dir`；查询目录仍是 `reports`。入库用已经存在的扫描命令，不要另造 prepare：

```powershell
python -m stock_kb scan
```

`scan` 会读 `nas.root/{公司}/`，也会读 `collect.raw_dir/{公司}/`，这两处都只读。下载完成后直接 scan，不必把文件再拷进 NAS。出处只写 `meta_dir`。某一侧原文目录不存在时只跳过该侧。

网页上怎么找到链接，不进入黄金回归。目标年份就是这次命令实际下载到的最近一份年报和最近一份中报，不用另填年份清单。

## 财报

按公司用对应来源，不要混用：

```powershell
python -m stock_kb fetch --source sec --company 百胜中国
python -m stock_kb fetch --source hkex --company 海底捞
```

- SEC 只走 `stock_kb/collectors/sec.py`：最近一份 10-K，有 10-Q 再下一份。没有 10-Q 时不要把 6-K 猜成中报。
- 披露易只走 `stock_kb/collectors/hkex.py`。这个接口会变。失败写入 `{data_dir}/collect_log.jsonl`。一件年报或中期报告都没有时，命令退出码非 0。

财报下载失败则这次收集失败，不要用研报或电话会的失败去掩盖，也不要因为研报失败把已经成功的财报命令改成非 0。

## 电话会

先找公司 IR 上能直接打开的文字稿。IR 只有业绩公告时，再找非官方记录。两类都用下面这条命令。没有可下的文件时，用 `--optional` 把缺口记进 `collect_log.jsonl`，退出码仍为 0。不要编造发言人。

```powershell
python -m stock_kb fetch --url "<直链>" --company 海底捞 --kind transcript --optional
```

非官方记录同时满足下面三条才下载：

1. 不登录就能打开的 pdf、html、txt 或 md 直链。
2. 正文是这场会的记录，或写明到场并引用了发言人的摘录。业绩公告的新闻改写、券商点评不算电话会；那类文件若本身是直链，改用 `--kind research`。
3. 公司必须对上。特海国际（09658.HK / NASDAQ: HDL）的电话会和演示材料不要放进海底捞目录。

查找顺序：

1. 公司 IR。
2. 公开报道里的业绩会摘录。海底捞 2026-03-25 全年业绩会有虎嗅《直击海底捞业绩会》。
3. 投资者自己写的会纪，只在页面本身就是文件直链时下载。雪球帖子通常不是直链。
4. Quartr、MarketScreener、S&P Capital IQ、烽火研报、进门财经、慧博、萝卜投研。公开页没有文件，或要登录、订阅时，只记缺口。不登录，不绕过付费墙。烽火研报上的《海底捞(06862)2022年度业绩投资者发布会纪要》就属于这一档。

`--kind transcript` 在文件名不含「电话会 / 业绩会 / transcript / 纪要」时，保存为 `transcript-` 前缀。`scan` 只看文件名，不读 JSON 里的 `kind`。文件名没有日期时，会议日期记为 `undated`，不同来源仍用 `source_url` 区分。

## 研报

只接受浏览器能直接打开的文件 URL。不登录券商网站，不绕过付费墙。命令必须带 `--kind research --optional`：失败只追加一行日志。

```powershell
python -m stock_kb fetch --url "<文件直链>" --company 百胜中国 --kind research --optional
```
