# stock-kb 评测记录（2026-08-22 起）

现行体系（分层、GT、打分、门禁、命令）见 **`eval/EVAL_SYSTEM.md`**。本文只记**过程中改掉的问题**和对照实验，不当施工清单。

日常回归：

```powershell
python tools/run_eval_regression.py          # freeze + FTS/hybrid diag（指标/无答案）
python -m stock_kb eval --split freeze
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5 --split freeze
python tools/audit_notes.py
```

---

## 1. 当前门槛（top_k=5）

| 检查 | 门槛 | 最近实测 |
|---|---|---|
| FTS keyword Recall@5 | ≥ 0.75 | 0.80 |
| FTS keyword Neg@5 | ≤ 0.65 | 0.60 |
| hybrid semantic Recall@5 | ≥ 0.10 | 0.15 |
| hybrid semantic Neg@5 | ≤ 0.20 | 0.00 |
| 结构化 hit / parse_hit | 26/26 | 26/26 |
| FTS diag `indicators` | 12/12 | 12/12 |
| FTS diag no_answer empty_rate | ≥ 0.75 | 1.00 |
| hybrid diag no_answer empty_rate | ≥ 0.75 | 1.00 |

题集：`eval/questions.yaml`。结构化 26 题已 `golden_source: pdf`。`split: diag` 的真语义 / 跨语言仍不进 freeze 检索门槛。

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

### 2.8 净利润口径与无答案空结果（产品，2026-08-22 夜）

`indicators.net_profit` 原先吃「年内溢利」合计。损益表续页常有两行都叫 `Owners of the Company`：一行是归母净利，一行是归母综合收益，数值差约 1%。只把 `ownersofthecompany` 提前仍可能抽到综合收益行。

现行规则：归母词优先于合计；有多行归母时，取与「年内溢利」合计最接近的那一行；同年年报正文页加分。海底捞 2023=4,499,080、2024=4,708,084。百胜中国仍走 `Net income — Yum China Holdings`。派生净利率 / ROE 随之用归母。指标题容差 0.01%（`0.0001`），2% 会把合计和归母当成同一个数。

FTS 长句曾用 trigram OR 硬填 top-k，无答案 empty_rate=0。已去掉这条兜底；多词改为 AND（丢掉「是多少」等虚词）。MCP 默认 engine 是 FTS，8 道 no_answer 全部空。hybrid / 向量在 FTS 为空时不再无条件填满：年份超出该公司入库年报区间，或问句里的非常见实体未出现在命中页，则返回空。8 道 no_answer 的 hybrid empty_rate=1.0。

去掉 trigram OR 后 freeze FTS semantic 从 0.10 到 0.00；hybrid semantic 从 0.15 到 0.10，卡在门禁线上。

---

## 3. 评测已经看见、产品还没改的

1. **真语义 / 跨语言**：证据清单之后仍有约 11 道页不在向量 top-50。英文问中文页、附注减值。不要用整句语言 ID 分流。见 `EVAL_SYSTEM.md` §8。
2. 46 道 freeze 检索 GT 没有逐页通读。
3. 三表 `--year` 会同时返回当年正文和次年比较列。
4. hybrid 无答案已按年份/实体约束清空（8/8），见 §2.8。

---

## 4. 不在本次范围

- RRF 权重、reranker、1200 字块：仍未做。400 字块已试过，见 §5.1，未采用。
- 扩到 170 题、dev/test/hold-out、LLM judge：不采用。小样本上切集会把点估计切得更不可读。

结构化 golden 变更清单：`eval/golden_proposals/all26.json`。

---

## 5. diag 18 题对照（2026-08-22 夜）

方法：FTS@5、vector@50、hybrid@5，对照 GT 页文本。脚本：`python tools/diag_retrieval.py`。

先发现 7 道 GT 页不对题，已按库内正文改掉（不进 freeze）：

| 题 | 原 GT | 问题 | 改成 |
|---|---|---|---|
| semantic-022 / cross-018 | 阿米巴 p25 | 服务 IP 总述，不是师徒开店 | p28 店长考核/开店资格 |
| semantic-025 | 国信 2024Q4 p4 | 必胜客利润率，不是股东回报 | 同文件 p1 |
| semantic-028 | 2024 Annual p3 | 回购/利润，没有咖啡 | 海通 2025Q2 p1 肯悦咖啡 |
| cross-015 | 招股书 p166 | 套餐价格，不是外卖 | p183 数字点餐/外卖 |
| cross-020 | 阿米巴 p39 | 净利率，不是资本开支 | 浦银 2024 p2 |
| cross-021 | 2024 Annual p3 | 同上，没有 K-Coffee | 2022 Annual p120 |

改完后再测（vector@50）：

| 桶 | 题数 | 含义 |
|---|---:|---|
| top5 | 1 | semantic-022：向量本来就排第 1，是 GT 错了 |
| 排不上（6–50） | 4 | 027@7、028@9、025@18、017@22 |
| 召不回（不在 50） | 13 | 真语义改写 + 英文问中文页 |
| hybrid 乱填 | 8/8 no_answer | FTS 空，向量 k 近邻仍返回 5 条 |

召不回里，不少是**对了文件、错了页**（如 024 翻台率、013 减值、014 已付股息）：800 字块把关键行淹没。英文问句打到年报封面/目录，打不到附注表。

结论：**不要先上 reranker**。18 题里只有 4 题进了向量 50 名，只有 027/028 靠近 top-5。

### 5.1 400 字分块（2026-08-23，已回滚）

只改 `embedding.chunk_size` 800→400，`--rebuild-chunks` 后 36,039 → 68,196 块，只重嵌当前模型。对照 `eval/reports/diag_retrieval_chunk800.json` vs `diag_retrieval_chunk400.json`。

| 桶 | 800 | 400 |
|---|---:|---:|
| top5 | 1（022@1） | 2（022@1，027 从 @7 升到 @1） |
| 排不上（6–50） | 4（027@7、028@9、025@18、017@22） | 3（028@10、017@17、025@30） |
| 召不回 | 13 | 13 |
| hybrid 无答案填满 | 8/8 | 8/8 |

同文件、错页：024 的文件排到向量第 1，但 GT 页仍不在 50 名；026 同文件 40→7；013 同文件命中消失。freeze hybrid semantic **0.10 → 0.05**（20 题里只剩 semantic-008「啄木鸟」@3），keyword 仍 0.80、结构化仍 26/26。按回归门禁回滚到 800。

更小块能把个别已进候选的题推上 top-5，**捞不起那 13 道召不回**，还会丢掉 freeze 上那 1 道语义命中。下一步不要再切块；hybrid 无答案做距离门槛，跨语言另处理问句，两者都不要和分块绑在一起。

### 5.2 diag 分析题改为证据清单（2026-08-23）

事实题（结构化 / 指标 / keyword / no_answer）仍用单页或空结果，freeze 门禁不变。

diag 的 semantic / cross 从「唯一文件+唯一页」改成证据清单：`sources` 里每条都 `required: true`，top-5 命中任一即算；`authority` 标明 `annual` / `interim` / `research` / `prospectus`。报告多一列 **年报/中报证据@5**（仅当清单里有年报或中报）。027 利润与 028 咖啡不再共用海通 Q2 封面。Coverage / Diversity 不做成指标。

对照脚本：`python tools/diag_retrieval.py`（`vector_rank` 已按清单任一源）。回归脚本不读这些列。

重测（vector@50 / hybrid@5 / FTS@5，任一证据）：

| 桶 | 原唯一页 | 证据清单后 |
|---|---:|---:|
| top5 | 1 | 5（022 师徒；028 咖啡；017 开店；020 资本开支 FTS；022 翻台率中报） |
| 排不上 | 4 | 2（027@7、025@18） |
| 召不回 | 13 | 11 |

年报/中报进 top-5 的只有 cross-022（2025 中报 p11 翻台率）和 cross-020（年报资本开支，FTS）。024「座位转得快」清单里已有同一页中报，向量仍召不回——那是问句，不是 GT。021 / 023 / 013 等仍是检索问题。
