# stock-kb 评测体系

本文描述**现行**评测怎么分层、题怎么标、分怎么打、门禁看哪些数。  
过程里改掉的问题和对照实验见 `eval/EVAL_PLAN.md`。题集是 `eval/questions.yaml`。

产品承诺：笔记里的关键数字必须能追溯到「文件 + 页码/表名」。评测为这件事服务，不追求学术检索榜。

---

## 1. 四层，不混成一个 hit

| 层 | 测什么 | 主要题型 | 通道 |
|---|---|---|---|
| 结构化 | 三表行能否对上 PDF 数字 | freeze `exact` / 部分 `cross` | `statements` |
| 指标 | `indicators` 口径（归母净利等） | diag `indicator` | `indicators` 表 |
| 检索 | 问句能否在 top-5 拿到可用出处 | freeze `keyword` / `semantic` / `cross`；diag 真语义 / 跨语言 | FTS / 向量 / hybrid |
| 无答案 | 库里没有时是否空 | diag `no_answer` | 同上，期望 0 条 |
| 生成 | 笔记数字与引用 | freeze `end2end` | `audit_notes.py` + 材料覆盖 |

不要用「总 Recall」概括所有层。keyword 高不代表语义强；结构化 26/26 只说明三表查询和 PDF golden 一致。

当前题集 **118 道**：

| split | type | n | 进回归门禁 |
|---|---|---:|---|
| freeze | exact | 20 | 结构化 26/26（与部分 cross 合计） |
| freeze | keyword | 20 | FTS Recall / Neg@5 |
| freeze | semantic | 20 | hybrid Recall / Neg@5 |
| freeze | cross | 12 | 其中检索约 6 道，其余走结构化 |
| freeze | end2end | 8 | 材料覆盖自动分，不挡回归 |
| diag | indicator | 12 | 12/12 |
| diag | no_answer | 8 | FTS / hybrid empty_rate |
| diag | semantic | 8 | 否（对照脚本） |
| diag | cross | 10 | 否（对照脚本） |

`split` 缺省视为 freeze。`--split freeze` 才进 `tools/run_eval_regression.py` 的检索/结构化门槛。diag 只把 **指标** 和 **无答案** 纳入回归，真语义 / 跨语言只做诊断。

---

## 2. Ground truth（GT）

GT 是 yaml 里「怎样算对」的标注，不是模型输出。

**结构化 / 指标**

- 数字必须 `golden_source: pdf`，禁止从 `statements.value` / `indicators` 抄回 yaml。
- 净利润 = 归母（港股「本公司拥有人应占」，美国 `Net income — Yum China Holdings`），不是年内溢利合计。
- 比较数字优先**当年年报正文页**，不用次年报比较列当正样本。
- 指标容差 `0.0001`（0.01%）。2% 会把合计和归母当成同一个数。

**检索**

- `expected.sources[]`：`file` 为 `reports.title` 不含扩展名的片段，`page` 为页码。
- freeze 语义 / 关键词：通常一页；难负样本写在 `negatives`。
- diag 分析 / 跨语言：证据清单，多条均可 `required: true`，**命中任一即算**。`authority` 为 `annual` / `interim` / `research` / `prospectus`。有年报或中报时另报 **年报/中报证据@5**。
- 文件匹配是 `title` 包含 `file` 片段，美股 `2022_Annual_Report` 与港股 `2022_HK_Annual_Report` 不算同一文件。

**无答案**

- `expected.sources` 为空。对 = 返回 0 条，不是「搜到差不多的预测页」。

改 GT 必须对照页文本（`content` / `content_orig`），不能只看检索是否变绿。

---

## 3. 怎么打分

实现：`stock_kb/eval_runner.py`。默认 `search_path=mcp_compat`（单 query，与 MCP `search_reports` 一致）。旧多关键词 RRF 用 `--search-path eval_rrf_keywords`。

### 3.1 检索（top_k=5）

- **hit / Recall@5**：top-5 是否命中任一目标源（有 `required` 时只看 required，否则看全部 sources）。
- **Hit@1 / MRR / nDCG / Precision@5**：排序参考。
- **Neg@5 / Neg@1**：难负样本是否进入 top-5 / 第 1。
- **annual_hit / annual_recall_at_k**：仅当清单含 `authority: annual|interim`。
- **hybrid_fused**：query 长度 ≥ 6 才真正做向量融合；短术语 hybrid ≈ FTS。keyword 评测会剥掉公司名，20 题里几乎都短路。
- **error_tags**（规则，非 LLM）：`page_near_miss`、`year_mismatch`、`lang_mismatch`、`lexical_overlap`、`negative_at_1`。

diag 对照脚本 `tools/diag_retrieval.py`：同一题跑 FTS@5、vector@50、hybrid@5，按证据清单分桶：

| 桶 | 含义 |
|---|---|
| top5 | 任一证据在 FTS/hybrid top-5 或向量 top-5 |
| 排不上 | 向量 6–50 |
| 召不回 | 向量 50 名内没有 |
| empty / hybrid_fill | 无答案：空，或 hybrid 仍填满 |

### 3.2 结构化（L1 / L3）

- **parse_hit（L1）**：GT 那一页的 `statements` 里有这个数。
- **hit（L3）**：按科目词查出的行，值/来源/页与 GT 一致（可含 unit/currency）。
- 两列都要报。L3 绿而页码来自次年报，仍算来源错。

### 3.3 指标

查 `indicators` 表，值在容差内。`net_profit` 必须是归母。

### 3.4 无答案

`empty_rate` = 返回 0 条的比例。FTS 与 hybrid 分列。向量距离不能当门槛（2026E 预测比「师徒制」更近）。

### 3.5 生成

`end2end` 看检索材料是否覆盖要点；笔记成品用 `python tools/audit_notes.py`（数字准确率、引用精度、孤儿数字）。不挡 `run_eval_regression.py`。

---

## 4. 检索引擎（与产品同一条路径）

| engine | 行为 |
|---|---|
| fts | FTS5 trigram；短于 3 字走 LIKE（按词频）；多词 AND，丢掉「是多少」等虚词；无 trigram OR 硬填 |
| vector | sqlite-vec；问句年份超出该公司 `reports.year` 区间则空；剥掉财报常用词后的实体必须出现在命中页 |
| hybrid | query 短于 6 字 → 只 FTS；否则 RRF。FTS 为空且向量也被年份/实体约束清空 → 空 |

默认嵌入：`BAAI/bge-small-zh-v1.5`，分块约 **800 字**（`embedding.chunk_size`）。命中聚合成**页**（引用单位）。

`index --rebuild` 只删当前模型向量，**不重切** chunks。改粒度必须 `index --rebuild-chunks`（清空所有模型）。

---

## 5. 日常命令与门禁

```powershell
python tools/run_eval_regression.py
python -m stock_kb eval --split freeze
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5 --split freeze
python tools/diag_retrieval.py
python tools/audit_notes.py
```

回归脚本现测：freeze FTS、freeze hybrid、FTS diag、hybrid diag（无答案）。

| 检查 | 门槛 | 最近实测（2026-08-23） |
|---|---|---|
| FTS keyword Recall@5 | ≥ 0.75 | 0.80 |
| FTS keyword Neg@5 | ≤ 0.65 | 0.60 |
| hybrid semantic Recall@5 | ≥ 0.10 | 0.15 |
| hybrid semantic Neg@5 | ≤ 0.20 | 0.00 |
| 结构化 hit / parse_hit | 26/26 | 26/26 |
| FTS diag indicators | 12/12 | 12/12 |
| FTS diag no_answer empty_rate | ≥ 0.75 | 1.00 |
| hybrid diag no_answer empty_rate | ≥ 0.75 | 1.00 |

Wilson 区间会打在报告里。n=20 时点估计很跳，门禁钉的是下限，不是「再抬到 0.9」。

报告目录：`eval/reports/`。`diag_retrieval.json` 为最近一次对照；`diag_retrieval_chunk800.json` / `chunk400.json` 为分块实验。

---

## 6. 明确不采用

- 170 题、dev/test/hold-out、LLM judge。
- 用 Coverage / Source Diversity 当优化目标（会奖励五篇点评封面）。
- 权威加权公式；权威写进 GT 清单（年报能答就列入年报）。
- 评测默认路径与 MCP 分叉（禁止再把多 keywords RRF 当默认）。

---

## 7. 产品调用（评测以外）

笔记 / agent 取**科目数字**时：

1. 收入、归母净利、毛利、总资产、净资产、经营现金流 → `get_indicators`
2. 已付股息、资本开支等行项目 → `get_financial_statements(keyword=, year=)`（「资本开支」匹配购置物业行）
3. 减值等多在附注、三表常空 → 再 `search_reports`
4. 翻台率、同店、师徒、品牌 → `search_reports`

CLI：`python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json`。  
`--year 2024` 仍可能带出次年报比较列，引用优先 `reports.year` 与科目年份相同的当年正文。

---

## 8. 还没测完 / 不要先做的

**评测债**

- freeze 46 道检索 GT 未逐页通读。
- diag 真语义 / 跨语言：证据清单后仍有约 11 道向量 50 名内没有；英文问中文页、附注减值仍是检索问题。
- 三表 `year` 过滤不区分当年正文与次年比较列。

**不要当下一刀**

- 再改分块（400 已试：diag 抬一题，freeze hybrid semantic 0.10→0.05，已回滚）。
- 先上 reranker（页不在 top-50 时无用）。
- 用整句语言 ID 在中/英引擎间切换；财务问句默认中英混排，按片段扩词表，不要判整句语言。
