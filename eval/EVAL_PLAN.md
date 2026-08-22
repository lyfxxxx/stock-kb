# stock-kb 评测记录（2026-08-22）

评测基建 A–D 已落地。本文记录**过程中改掉的问题**和当前门槛，不再当施工清单。

日常回归：

```powershell
python tools/run_eval_regression.py          # 只评 freeze
python -m stock_kb eval --split freeze
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5 --split freeze
python tools/audit_notes.py
```

---

## 1. 当前门槛（freeze，top_k=5）

| 检查 | 门槛 | 最近实测 |
|---|---|---|
| FTS keyword Recall@5 | ≥ 0.75 | 0.80 |
| FTS keyword Neg@5 | ≤ 0.65 | 0.60 |
| hybrid semantic Recall@5 | ≥ 0.10 | 0.15 |
| hybrid semantic Neg@5 | ≤ 0.20 | 0.00 |
| 结构化 hit / parse_hit | 26/26 | 26/26 |

题集：`eval/questions.yaml`。结构化 26 题已 `golden_source: pdf`。另有 `split: diag`（真语义 8、跨语言 10、无答案 8、指标 12），**不进回归**。

---

## 2. 过程中改掉的问题

### 2.1 结构化 26/26 是「库查库」，不是「对得上 PDF」

`questions.yaml` 里 `expected_value` 原先从 `statements.value` 抄来。查询命中只能证明解析器写下的数还能被查回来。

从 NAS PDF 独立核对后，改了 8 道：

| 问题 | 原值（自洽） | 改成 |
|---|---|---|
| 净利润用了「年内溢利」合计，不是归母 | 海底捞 2024：4,700,278；2023：4,495,399；2021 亏损 −4,161,206；2019：2,346,962；2022：1,373,216 | 归母：4,708,084 / 4,499,080 / −4,163,175 / 2,344,711 / 1,374,477。行在损益表**续页**（如 2023 年报 p279） |
| 比较期数字取自**次年报**比较列，负样本写成了当年正文 | 2023 经营现金流、百胜 2023 收入/净利来自 2024 年报 | 改回当年年报正文页，负样本对调 |

L1（该页 `statements` 里有这个数）和 L3（按科目词查到）现在分列，目前都是 26/26。解析器把部分归母行名截成 `owners of the Company`，数值在库里，所以查询仍绿。

### 2.2 「hybrid keyword 0.75」几乎不是混合检索

`hybrid_search` 对短于 6 个字符的查询直接走 FTS。评测对 keyword 题会剥掉公司名，搜「翻台率」「减值」。20 题里只有 `KCOFFEE` 真正做了向量融合。

对 keyword 集调 RRF 权重没有意义。评测报告用 `hybrid_fused` 标出这一点。

### 2.3 「semantic 0.50」是问句漏词，不是语义变强

8-16 夜班 FTS semantic 从 0 升到 0.50，是因为：问句里带「现金流 / 翻台率 / 扩张」，长句 phrase 为空时 trigram OR 把这些词拆开搜。20 道题当时全部打上 `lexical_overlap`。

改写 18 道 freeze 问句、去掉答案页关键词之后：

- FTS semantic Recall **0.50 → 0.10**
- hybrid semantic Recall **0.50 → 0.15**

门禁从 0.50 改成 ≥ 0.10。泄漏题上的高分不能当语义能力。

### 2.4 评测检索路径和 MCP 不是同一条

评测曾对多 `keywords` 做 RRF；MCP `search_reports` 只收一条 `query`。默认改为 `search_path=mcp_compat`（单 query）。旧路径 `--search-path eval_rrf_keywords` 仍可对比。

FTS freeze cross 因此从 0.167 升到 0.333（整句检索，不是系统变强）。

### 2.5 语义题没有负样本，Neg@k 一直是 0

freeze 语义 20 题补了难负样本后，Neg@5 从 0 变成 0.10。去泄漏改写之后，这些负样本不再容易被新问句命中，Neg@5 回到 0。回归仍保留 Neg@k 上限，防止以后再把负样本评掉。

### 2.6 两字 LIKE 按页面长度排序

`_like_search` 以前 `ORDER BY char_count DESC`，长页排前面。改成按词频 `score` 后，keyword-007「开店」会掉出 top-5（研报里「开店」出现次数远高于 2024 中报那一页）。

先给「开店 / 阿米巴 / 外卖 / 股息」补了高词频正样本页，再启用 `ORDER BY score DESC`。keyword Recall 保持 0.80。

### 2.7 生成层全是 pending_manual

8 道 end2end 问的是「写笔记需要哪些材料」，`page: null`，自动分一直是 0。改为检查所需 `reports.title` 是否在库：8/8 材料齐全。

笔记侧：`audit_notes.py` 抽出数字和「《文件》第 N 页」，与库对照。试点两篇 + 2026-08-22 抽查稿均已跑过。

---

## 3. 评测已经看见、产品还没改的

1. **海底捞 `indicators.net_profit` 仍是年内溢利合计**，不是归母。指标题 12 道里 10 道过、2 道不过（2023/2024 归母）。容差必须收到约 0.01%，2% 会把两种口径当成同一个数。
2. **无答案查询 empty_rate = 0**。长句走 trigram OR 之后总会填满 top-k，系统不会返回空。
3. **真语义 / 跨语言 diag** FTS Recall 约 0.10–0.13。要靠改检索，不是再加泄漏题。
4. 46 道检索 GT 没有逐页通读，只改了失败明细里能量化的页码。

---

## 4. 不在本次范围

- 分块 400/800/1200、RRF 权重、reranker：等明确要做模型/检索对比再用 diag 集。
- 扩到 170 题、dev/test/hold-out、LLM judge：不采用。小样本上切集会把点估计切得更不可读。

结构化 golden 变更清单：`eval/golden_proposals/all26.json`。
