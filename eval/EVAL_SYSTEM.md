# stock-kb 评测体系

本文描述**现行**评测怎么分层、题怎么标、分怎么打、门禁看哪些数。  
过程里改掉的问题和对照实验见 `eval/EVAL_PLAN.md`。题集是 `eval/questions.yaml`。

产品承诺：笔记里的关键数字必须能追溯到「文件 + 页码/表名」。评测为这件事服务，不追求学术检索榜。

三个产品目标（skill 笔记 / 改动评测 / 过程记录）到这些门的映射、以及换 embedding / 改 skill / 加数据各走哪条测量路径，见 `eval/METRICS_CONTRACT.md`。雪球专栏扫描体（多篇对照）见 `eval/style-canon/TEMPLATE.md`。

---

## 1. 分层，不混成一个 hit

| 层 | 测什么 | 主要题型 | 通道 |
|---|---|---|---|
| 结构化 | 三表行能否对上 PDF 数字 | freeze `exact` / 部分 `cross` | `statements` |
| 指标 | `indicators` 口径（归母净利等） | diag `indicator` | `indicators` 表 |
| 检索 | 问句能否在 top-5 拿到可用出处 | freeze `keyword` / `semantic` / `cross`；diag 真语义 / 跨语言 | FTS / 向量 / hybrid |
| 无答案 | 库里没有时是否空 | diag `no_answer` | 同上，期望 0 条 |
| 生成 | 笔记数字与引用 | freeze `end2end` | 组稿 `eval-generation` + `audit_notes.py` + 材料覆盖 |
| 路由 | 问句该走哪把工具 | freeze `route` | `stock_kb.route`（不检索） |

不要用「总 Recall」概括所有层。keyword 高不代表语义强；结构化 29/29 只说明三表查询和 PDF golden 一致。

当前题集 **161 道**：

| split | type | n | 进回归测试 |
|---|---|---:|---|
| freeze | exact | 23 | 结构化 29/29（与部分 cross 合计） |
| freeze | keyword | 22 | FTS Recall / Neg@5 |
| freeze | semantic | 20 | hybrid Recall / Neg@5 |
| freeze | cross | 12 | 其中检索约 6 道，其余走结构化 |
| freeze | end2end | 8 | 材料覆盖自动分，不卡住回归测试 |
| freeze | route | 24 | accuracy = 1.0（wrong-tool rate = 0） |
| freeze | year_filter | 4 | 命中页 `reports.year` 与问句年份一致 |
| diag | indicator | 12 | 12/12 |
| diag | no_answer | 8 | FTS / hybrid empty_rate |
| diag | semantic | 13 | 否（对照脚本） |
| diag | cross | 15 | 否（对照脚本） |

`split` 缺省视为 freeze。`--split freeze` 才进 `tools/run_eval_regression.py` 的检索/结构化门槛。diag 只把 **指标** 和 **无答案** 纳入回归测试，真语义 / 跨语言只做诊断。回归测试另输出 `recall_soft_at_k`（期望页在 top-k 内仅页码 ±5 的 near-miss 计半分，只展示、不卡住回归测试）与「公司×年份×指标」覆盖矩阵（`tools/coverage_matrix.py`）。题集 2026-09-13 扩至 156 道（+5 英文 cross、+5 中报 semantic，全部 diag）；2026-10-04 再加 freeze exact-021–023（2026 中报），结构化 29 道。

---

## 2. Ground truth（GT）

GT 是 yaml 里「怎样算对」的标注，不是模型输出。

**结构化 / 指标**

- 数字必须 `golden_source: pdf`，禁止从 `statements.value` / `indicators` 抄回 yaml。
- 净利润 = 归母（港股「本公司拥有人应占」，美国 `Net income — Yum China Holdings`），不是年内溢利合计。
- 比较数字优先**当年年报正文页**，不用次年报比较列当正样本。
- 指标与结构化三表题容差均为 `0.0001`（0.01%）。2% 会把合计和归母当成同一个数。

**检索**

- `expected.sources[]`：`file` 为 `reports.title` 不含扩展名的片段，`page` 为页码。
- freeze 语义 / 关键词：通常一页；难负样本写在 `negatives`。
- diag 分析 / 跨语言：证据清单，多条均可 `required: true`，**命中任一即算**。`authority` 为 `annual` / `interim` / `research` / `prospectus`。有年报或中报时另报 **年报/中报证据@5**。
- 文件匹配是 `title` 包含 `file` 片段。美股 `2022_Annual_Report` 与港股年报不是同一文件。港股英文年报的当前使用文档标题是 `百胜中国_2022年报` 至 `百胜中国_2025年报`。
- 关键词题写 `accept_phrases`。问句带四位年份时，检索仍按文档的 `reports.year` 过滤。前 5 页里，标出的页算命中；另一页在去掉空白和千分位后含有其中一条短语，也算同一个事实。纯数字短语按整段数字比对。

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

`empty_rate` = 返回 0 条的比例（分母扣除 engine_error）。评测前先跑**哨兵查询**（公司名，必命中）：哨兵也为空说明引擎故障，该题记 `engine_error` 而非 empty，避免检索 bug 伪装成正确拒答。FTS 与 hybrid 分列。向量距离不能当门槛（2026E 预测比「师徒制」更近）。

### 3.5 生成

`end2end` 看检索材料是否覆盖要点。

组稿路径（无 LLM）：`python -m stock_kb compose-note` / `eval-generation` 按扫描体顺序调 indicators → 三表 → 检索，填模板，每条数字带 `《文件》第N页`。同时写出 HTML（内嵌 SVG 图）。审计看「引用明细」表：数字须出现在引用页的 `pages.content` / `content_orig`。手写试点笔记仍用 `python tools/audit_notes.py`。二者都进 `run_eval_regression.py`。组稿不写无市价的 PE、不摘无出处行业预测。

### 3.6 工具路由

`type: route` 不跑检索。`stock_kb.route.route(question, company)` 对照 `expected.tool`：

| tool | 何时 |
|---|---|
| `get_indicators` | 收入 / 归母净利 / 毛利 / 总资产 / 净资产 / 经营现金流 |
| `get_financial_statements` | 已付股息、资本开支、减值（减值可 fallback 到 search） |
| `search_reports` | 翻台率、同店、师徒、客单价等经营叙述 |
| `no_answer` | 库外实体、公司错配、年份超出入库区间 |

wrong-tool rate = 1 − accuracy。MCP 工具 `route_query` 与 CLI `python -m stock_kb route` 用同一函数。

---

## 4. 检索引擎（与产品同一条路径）

| engine | 行为 |
|---|---|
| fts | FTS5 trigram；短于 3 字走 LIKE（按词频）；多词 AND，丢掉「是多少」等虚词；无 trigram OR 硬填。问句里的年份不参与 MATCH：超出该公司入库年则空，否则 **硬过滤** `reports.year`。无年份的问句不按新近排序（freeze keyword 多为旧研报） |
| vector | sqlite-vec；问句年份超出该公司 `reports.year` 区间则空，否则同样按报告年过滤；剥掉财报常用词后的实体必须出现在命中页 |
| hybrid | query 短于 6 字 → 只 FTS；否则 RRF。FTS 为空且向量也被年份/实体约束清空 → 空 |

默认嵌入：`BAAI/bge-small-zh-v1.5`，分块约 **800 字**（`embedding.chunk_size`）。命中聚合成**页**（引用单位）。

`index --rebuild` 只删当前模型向量，**不重切** chunks。改粒度必须 `index --rebuild-chunks`（清空所有模型）。

---

## 5. 日常命令与门禁

```powershell
python tools/run_eval_regression.py
python tools/run_eval_regression.py --write-baseline   # 门槛通过后更新每题 hit 快照
python -m stock_kb eval --split freeze
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5 --split freeze
python -m stock_kb eval-generation
python -m stock_kb route "海底捞 2024 年营业收入是多少" --company 海底捞
python -m stock_kb compose-note --company 海底捞
python tools/diag_retrieval.py
python tools/audit_notes.py
```

回归测试脚本现测：freeze FTS、freeze hybrid、FTS diag、hybrid diag（无答案）、路由、年份过滤、组稿生成、`audit_notes.py`。  
对照 `eval/regression_baseline.json` 打印每题翻红/翻绿（lost/gained）；翻题默认只打印，不单独当失败。改 GT 或题集后门槛通过再用 `--write-baseline`。

| 检查 | 门槛 | 最近实测（2026-08-30） |
|---|---|---|
| FTS keyword Recall@5 | ≥ 0.75 | 0.80 |
| FTS keyword Neg@5 | ≤ 0.65 | 0.55 |
| hybrid semantic Recall@5 | ≥ 0.20 | 0.15 |
| hybrid semantic Neg@5 | ≤ 0.20 | 0.00 |
| 结构化 hit / parse_hit | 29/29 | 29/29 |
| FTS diag indicators | 12/12 | 12/12 |
| FTS diag no_answer empty_rate | ≥ 0.75 | 1.00 |
| hybrid diag no_answer empty_rate | ≥ 0.75 | 1.00 |
| route accuracy | = 1.0（24 题） | 1.00 |
| year_filter precision_mean | ≥ 0.60（4 题） | 1.00 |
| generation_compose | fail_count = 0；引用页含该数 | 1.00 faithful |
| audit_notes | 0 项失败；净利走归母 | 见脚本 |

Wilson 区间会打在报告里。n=20 时点估计很跳，门禁钉的是下限，不是「再抬到 0.9」。2026-09-04 复测 freeze hybrid semantic Recall@5 = 0.30（改写碎片不再当 needles；embedding 查询补领域同义；MCP 默认仍 FTS），见 `eval/reports/BAAI_bge-small-zh-v1.5_20260904_223823.md`。

报告目录：`eval/reports/`。`diag_retrieval.json` 为最近一次对照；`diag_retrieval_chunk800.json` / `chunk400.json` 为分块实验。

### 5.1 embedding 模型筛选（不进 freeze 门禁）

freeze keyword 测不到向量（短句 hybrid 短路回 FTS）。要挑 embedding，用单独套件，只含**会长句、真走向量**的题：

- freeze `semantic` 20 + freeze 无三表 `cross` 6
- diag `semantic` 8 + diag `cross` 10
- 共 44 道；问句归一化后短于 6 字的排除

主指标是 **vector Recall@5 / Recall@50 分桶**（top5 / 6–50 / miss），不是 FTS，也不是「总 Recall」。

```powershell
python -m stock_kb eval-embed --base BAAI/bge-small-zh-v1.5 --challenger BAAI/bge-m3
python -m stock_kb eval-embed --models BAAI/bge-small-zh-v1.5,BAAI/bge-m3,sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

未建索引会报错，先 `python -m stock_kb index --model <ID>`。

判定：

| 标签 | 含义 | 能否改 `embedding.model` |
|---|---|---|
| `better` | Recall@50 的 Wilson 区间与基线分开且更高 | 可以考虑；仍须 hybrid freeze 过门禁 |
| `better_at_5_only` | 只把已进 50 名的题推上 top-5 | 否 |
| `lean_better` / `indistinguishable` | 区间重叠或只差一两题 | 否 |
| `worse` / `lean_worse` | 更差或更差倾向 | 否 |

n=44 时点估计仍跳。差 1 题不当作赢。keyword、结构化、无答案不参与选模。

换模落地顺序：`eval-embed` 得 `better` → `eval --engine hybrid --model <候选> --split freeze` 过 hybrid semantic 门槛 → `run_eval_regression.py` → 改 `config.yaml` 的 `embedding.model`。

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

不确定走哪把工具时先 `route_query`。`get_financial_statements(year=)` 默认只要 **当年年报正文**（`r.year = s.year`）；次年报比较列需 `include_comparatives=True`。

CLI：`python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json`。  
`--year 2024` 默认只要当年年报正文；比较列加 `--include-comparatives`。

---

## 8. 还没测完 / 不要先做的

**评测债**

- freeze 46 道检索 GT 已于 2026-08-30 按 `pages.content` 通读；8 道改了 required 页，另有跨公司/同页负样本替换（见 `EVAL_PLAN.md` §5.3）。keyword 20 道 required 页主题词均在页上，未改。
- diag 真语义 / 跨语言：证据清单后仍有约 11 道向量 50 名内没有；英文问中文页、附注减值仍是检索问题。
- 组稿评测覆盖「工具顺序 + 数字在引用页上」，不覆盖 LLM 是否遵守 skill。无年份的 keyword 题 `year_mismatch` 仍高，那是排序不是过滤。

**不要当下一刀**

- 再改分块（400 已试：diag 抬一题，freeze hybrid semantic 0.10→0.05，已回滚）。
- 先上 reranker（页不在 top-50 时无用）。
- 用整句语言 ID 在中/英引擎间切换；财务问句默认中英混排，按片段扩词表，不要判整句语言。
