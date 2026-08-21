# stock-kb 知识库评测方案

> 本文件是 stock-kb 知识库的**系统化评测方案**，覆盖从解析质量到端到端生成的全链路评测。
> 与 `OPTIMIZATION_PLAN.md` 的关系：后者是 2026-08-15~16 的优化执行记录与诊断，
> 本文件在其基础上提出完整、可落地、分阶段的评测体系，作为后续工作的权威指引。
> 最后更新：2026-08-20。

---

## 目录

1. [评测目标与原则](#1-评测目标与原则)
2. [现状基线](#2-现状基线)
3. [六层评测架构](#3-六层评测架构)
4. [评测集设计](#4-评测集设计)
5. [指标体系](#5-指标体系)
6. [引擎矩阵与实验设计](#6-引擎矩阵与实验设计)
7. [生产-评测口径对齐](#7-生产-评测口径对齐)
8. [CI 回归门禁](#8-ci-回归门禁)
9. [落地路线图](#9-落地路线图)
10. [工具与自动化清单](#10-工具与自动化清单)
11. [验收标准总表](#11-验收标准总表)

---

## 1. 评测目标与原则

### 1.1 核心目标

stock-kb 的核心价值主张是：**笔记中的关键数字必须能追溯到「文件 + 页码/表名」，不允许凭记忆编数。**

评测方案要回答六个问题：

| # | 问题 | 对应评测层 |
|---|------|-----------|
| Q1 | 三表行项目提取准不准？解析器有没有取错行、取错数？ | L1 解析质量 |
| Q2 | 检索能不能找到包含答案的那一页？负样本有没有混进来？ | L2 检索质量 |
| Q3 | 结构化查询能不能查到对的数？单位/币种对不对？ | L3 结构化查询 |
| Q4 | 生成的笔记数字对不对？引用准不准？有没有幻觉？ | L4 生成质量 |
| Q5 | 端到端流程（MCP 查数 → 生成笔记）能不能跑通且可信？ | L5 端到端 |
| Q6 | 系统快不快、省不省？延迟和资源消耗可接受吗？ | L6 系统性能 |

### 1.2 五条原则

| 原则 | 含义 | 反例 |
|------|------|------|
| **独立 golden** | 评测基准来自 PDF 独立人工抽取，不来自 DB 自身 | 从 `statements.value` 读期望值来验证 `statements.value`（当前 exact/cross 的自洽校验） |
| **分层解耦** | 各层独立评测，改一层只看该层指标，不混变量 | 把三表命中和页面检索混在同一个 hit 里 |
| **可复现** | 每次评测记录引擎/模型/题集 hash/DB 快照/耗时 | 只报分数不报环境 |
| **可回归** | CI 门禁阻止指标劣化，新代码不通过不准合入 | 评测只手动跑，劣化无人发现 |
| **统计可信** | 小样本给置信区间，模型对比做显著性检验 | n=6 全中就说 Recall=1.0 |

---

## 2. 现状基线

### 2.1 数据规模

| 维度 | 数值 |
|------|------|
| 报告 | 60 份（海底捞 34 + 百胜中国 26） |
| 页面 | 8,128 页 |
| 三表行项目 | 8,718 条 |
| 指标 | 133 条 |
| 分块 | ~36,000 块（800 字/块） |

### 2.2 评测集现状

| 题型 | 题库数 | 进入检索统计 | 进入结构化 | 进入生成 |
|------|-------:|----------:|--------:|--------:|
| exact | 20 | 0 | 20 | 0 |
| keyword | 20 | 20 | 0 | 0 |
| semantic | 20 | 20 | 0 | 0 |
| cross | 12 | 6 | 6 | 0 |
| end2end | 8 | 0 | 0 | 8 |
| **合计** | **80** | **46** | **26** | **8** |

### 2.3 最新基线（2026-08-16，top_k=5）

**检索层**（hybrid，bge-small-zh-v1.5）：

| 类型 | n | Recall@5 | Hit@1 | MRR | nDCG | Prec@5 | Neg@5 | Neg@1 |
|------|--:|--------:|------:|----:|-----:|-------:|------:|------:|
| keyword | 20 | 0.750 | 0.350 | 0.472 | 0.540 | 0.150 | 0.600 | 0.100 |
| semantic | 20 | 0.500 | 0.250 | 0.352 | 0.301 | 0.160 | 0.000 | 0.000 |
| cross | 6 | 0.167 | 0.000 | 0.083 | 0.105 | 0.033 | 0.333 | 0.167 |
| total | 46 | 0.565 | 0.261 | 0.369 | 0.380 | 0.139 | 0.304 | 0.065 |

**结构化层**：26/26 全中（field/value/source/page/unit/currency 均 26/26）。

**生成层**：8 题，auto_scored=0，pending_manual=8。

### 2.4 已落地能力

- ✅ 三层评分架构（retrieval / structured / generation）
- ✅ 三引擎评测（FTS / vector / hybrid），CLI `--engine` 切换
- ✅ 检索指标齐全（Recall@k / Hit@1 / MRR / nDCG / Precision@k / Neg@k / Neg@1）
- ✅ 结构化行级对齐判定（同条记录须同时满足 field+source+page+value）
- ✅ 可复现元数据（题集 SHA-256 / DB size+mtime / 耗时 / engine+model）
- ✅ RRF 多关键词融合 + FTS/向量混合融合
- ✅ 人工复核底稿生成（`make_human_review_worksheet.py`）
- ✅ CI 回归门禁（`run_eval_regression.py`，门槛：FTS keyword≥0.75、hybrid semantic≥0.30、结构化 26/26）
- ✅ 单元测试（`tests/test_core.py`）
- ✅ 失败题与负样本命中明细写入报告

### 2.5 已知缺口

| # | 缺口 | 影响 | 对应阶段 |
|---|------|------|---------|
| G1 | ground truth 非独立：结构化 expected_value 取自 DB `statements.value`，属自洽校验 | 26/26 无法证明解析器与 PDF 一致 | Phase 1 |
| G2 | 生成层零自动化：8 道 end2end 全 pending_manual，无数字核对/引用核对/LLM judge/幻觉率 | 生成质量无法量化 | Phase 3 |
| G3 | 样本量薄弱：cross 纯检索仅 6 题、semantic 20 题无负样本、无无答案/多跳/公司区分/年份混淆题 | 指标点估计不可靠、覆盖面窄 | Phase 2 |
| G4 | 无数据集划分：80 题全用于评测，无 dev/test/hold-out | 调参会过拟合评测集 | Phase 2 |
| G5 | 无置信区间与显著性检验 | 无法判断指标差异是否显著 | Phase 2 |
| G6 | 无查询改写变体、无 passage 级 GT（evidence_snippet） | 无法测鲁棒性、无法精确定位召回质量 | Phase 2 |
| G7 | 无性能指标（延迟/成本/内存/磁盘） | 无法评估生产可用性 | Phase 4 |
| G8 | 生产-评测口径差异：CLI `search` 无纯 vector 模式，LIKE 兜底排序按 char_count 而非词频 | 评测与生产路径不一致 | Phase 1 |
| G9 | 人工审核全空：`human_review_worksheet.md` 和 `manual_review.md` 全部未填 | 独立 golden 未落地 | Phase 1 |
| G10 | 公司覆盖窄：仅 2 家公司，跨报告/中英文一致性题极少 | 泛化能力未知 | Phase 4 |

---

## 3. 六层评测架构

```
┌─────────────────────────────────────────────────────────────┐
│                    L5 端到端评测                              │
│   MCP 工具链 → stock-note skill → 笔记 → 人工/LLM 审核        │
├─────────────────────────────────────────────────────────────┤
│  L4 生成质量        │  L3 结构化查询        │  L2 检索质量     │
│  笔记数字准确率     │  三表直查准确率       │  Recall/MRR/     │
│  引用 P/R/幻觉率    │  指标查询准确率       │  nDCG/Neg@k      │
├─────────────────────┴──────────────────────┴────────────────┤
│                    L1 解析质量                               │
│   三表行项目提取准确率 / 指标计算正确性 / OCR 兜底质量         │
├─────────────────────────────────────────────────────────────┤
│                    L6 系统性能                               │
│   P50/P95 延迟 / 索引耗时 / 内存峰值 / 磁盘占用              │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 L1 解析质量

**评测什么**：三表行项目的提取准确率（行名、数值、单位、币种、年份归属、页码）以及从行项目派生的指标正确性。

**当前状态**：
- 有 26 道结构化题做行级对齐判定，但 expected_value 取自 DB 自身（自洽校验）。
- 无从 PDF 独立抽取的 golden set。
- 已知风险点：百胜中国 Total assets 多数字同行、海底捞 2021 括号亏损正负号、百胜中国 2023/2024 双年报表页年份归属。

**目标**：
- 建立从 PDF 独立人工标注的 golden set（≥50 个行项目，覆盖两家公司 × 三表 × 4 个年份）。
- 指标：行项目提取准确率 = 正确行数 / 总行数；按字段分解（line_name / value / unit / currency / year / page）。
- 派生指标正确率：revenue / net_profit / total_assets / total_equity / operating_cashflow / gross_margin / net_margin / roe，与人工计算值比对。

**怎么做**：
1. 用 `make_human_review_worksheet.py` 生成结构化复核底稿（已有，需填充）。
2. 人工从 PDF 读取每行的原值/单位/币种/页码，填入底稿。
3. 写 `tools/eval_parse_quality.py`：读取已填充的 golden，与 DB `statements` 表逐行比对，输出准确率与错误明细。
4. 指标计算正确性：人工从 PDF 计算指标值，与 `indicators` 表比对。

### 3.2 L2 检索质量

**评测什么**：给定查询，检索系统能否在 top-k 内召回包含答案的页面，同时避免召回负样本。

**当前状态**：
- 三引擎（FTS / vector / hybrid）× 三类型（keyword / semantic / cross）已覆盖。
- 检索指标齐全（Recall / Hit@1 / MRR / nDCG / Precision / Neg@k / Neg@1）。
- 但 semantic 无负样本、cross 仅 6 题、无查询改写变体。

**目标**：
- 扩到 cross≥30、semantic≥30（含负样本）、新增无答案题≥10、多跳题≥10。
- 每题 2-3 个改写变体（同义改写、口语化改写、中英混合改写）。
- passage 级 GT（evidence_snippet）：不只是"哪一页"，而是"哪一段"。
- 数据集划分 dev/test/hold-out。

**怎么做**：
1. 扩充 `questions.yaml`（详见 [§4](#4-评测集设计)）。
2. 为每道检索题标注 evidence_snippet（页内 50-100 字的关键段落）。
3. 评测时额外计算 passage-level Recall（hit 的 chunk 与 evidence_snippet 的重叠率）。
4. 跑三引擎 × 多模型矩阵（详见 [§6](#6-引擎矩阵与实验设计)）。

### 3.3 L3 结构化查询

**评测什么**：通过 MCP `get_financial_statements` / `get_indicators` 工具直接查三表行项目和指标时，返回的数值是否正确、单位/币种是否准确、来源定位是否对。

**当前状态**：
- 26 道结构化题做行级对齐，全中。但自洽校验。
- unit/currency 已回填，26/26。

**目标**：
- 用独立 golden 替换自洽 expected_value。
- 增加指标查询题（查 `indicators` 表的 revenue / net_margin / roe 等）。
- 增加边界题：查不存在的年份/科目、查同名不同年、查跨期对比。

**怎么做**：
1. Phase 1 完成独立 golden 后，结构化题的 expected_value 全部替换。
2. 新增 10 道指标查询题（type=indicator），在 `questions.yaml` 加 `indicator` 字段（`name, year, expected_value, expected_unit`）。
3. `eval_runner.py` 增加 indicator 题型处理：查 `indicators` 表比对。

### 3.4 L4 生成质量

**评测什么**：用 `stock-note` skill 生成笔记后，笔记中的数字是否准确、引用是否可溯源、有无幻觉、事实与观点是否分离。

**当前状态**：8 道 end2end 全 pending_manual，零自动化。

**目标**：
- 自动评分 + 人工抽查（20% 抽样一致性校验）。
- 五个生成指标：
  - **数字准确率**：笔记中出现的数字，是否能在 DB 中找到匹配（容差内）且来源正确。
  - **引用精确率/召回率**：笔记引用的"文件+页码"中，正确的比例（P）vs 应引用的来源中被引用的比例（R）。
  - **幻觉率**：笔记中出现但 DB 中找不到来源的数字占比。
  - **事实/观点分离率**：标注为事实的陈述是否有引用支撑；标注为观点的陈述是否明确区分。
  - **结构完整度**：按 rubric 逐条判定。

**怎么做**：
1. 写 `tools/eval_generation.py`：
   - 输入：stock-note 生成的笔记 + 题目的 expected sources/answer。
   - 数字核对：正则提取笔记中所有数字，逐一在 `statements`/`indicators` 表查匹配（容差内 + 同公司同年）。
   - 引用核对：正则提取笔记中"《xxx》第N页"格式的引用，与 expected sources 比对。
   - 幻觉检测：数字无匹配 + 引用无对应 = 幻觉。
2. LLM judge（可选）：用 LLM 按 rubric 逐条打分，与人工抽查做一致性校验（Cohen's κ ≥ 0.6）。
3. 人工抽查 20%：填 `manual_review.md` 第二节。

### 3.5 L5 端到端

**评测什么**：从自然语言问题出发，经 MCP 工具链查数 → stock-note 生成笔记 → 笔记满足用户需求的完整流程。

**当前状态**：8 道端到端题有 rubric 但无评分。

**目标**：
- 端到端题接真实 stock-note 生成链路。
- 自动评分（L4 指标）+ rubric 评分（LLM judge + 人工）。
- 测量端到端成功率：能否在给定问题下生成一篇数字准确、引用完整、结构合理的笔记。

**怎么做**：
1. 端到端题的 expected 从"文件级 page=null"升级为"文件+页码+关键数字"。
2. 对每道端到端题，调用 stock-note 生成笔记，然后用 L4 自动评分工具评。
3. LLM judge 按 rubric 逐条打分。
4. 人工抽查 20%。

### 3.6 L6 系统性能

**评测什么**：检索延迟、索引构建耗时、内存峰值、磁盘占用。

**当前状态**：无性能评测。

**目标**：
- 检索 P50/P95 延迟（FTS / vector / hybrid 分别测）。
- 索引构建耗时（按模型和块数）。
- 内存峰值（embedding 推理时）。
- 磁盘占用（DB + 向量表）。

**怎么做**：
1. 写 `tools/eval_performance.py`：
   - 延迟：对评测集每题计时（含/不含 embedding 推理），统计 P50/P95/P99。
   - 索引耗时：`index` 命令计时 + 记录块数和模型。
   - 内存：` tracemalloc` 或 `resource` 模块。
   - 磁盘：`os.path.getsize` 统计 DB 和 vec 表。
2. 结果写入 `eval/reports/perf_{ts}.json`。

---

## 4. 评测集设计

### 4.1 题型体系

| 题型 | 评测层 | 当前 | 目标 | 说明 |
|------|--------|-----:|-----:|------|
| exact | L1+L3 | 20 | 30 | 三表行项目精确查值，带 statement 块 |
| keyword | L2 | 20 | 30 | 经营术语检索，含 required source + negative |
| semantic | L2 | 20 | 30 | 语义检索，含 required + optional sources + **新增 negative** |
| cross | L2 | 12 | 30 | 中英跨语言检索，6 带 statement → 扩到 15 带 + 15 纯检索 |
| end2end | L4+L5 | 8 | 15 | 端到端笔记生成，带 rubric |
| indicator | L3 | 0 | 15 | **新增**：指标查询题，查 indicators 表 |
| no_answer | L2 | 0 | 10 | **新增**：查不到的查询，验证"不该返回时返回空" |
| multi_hop | L2+L3 | 0 | 10 | **新增**：需要多步推理的查询（如"海底捞 2024 vs 2023 营收增长率"） |
| **合计** | | **80** | **170** | |

### 4.2 数据集划分

将 170 题按 **3:5:2** 划分：

| 集合 | 比例 | 用途 | 题数 |
|------|------|------|-----:|
| dev | 30% | 调参、调权重、调分块粒度 | ~51 |
| test | 50% | 每次代码变更后的回归评测 | ~85 |
| hold-out | 20% | 模型最终选型、不参与日常调优 | ~34 |

划分原则：
- 每个题型在三个集合中按比例分配。
- 同一公司的题在三个集合中均匀分布。
- 难度均衡（不把难题全放 hold-out）。
- 在 `questions.yaml` 中每题加 `split: dev|test|holdout` 字段。

### 4.3 独立 golden 标注规范

**原则**：所有 expected_value / expected sources 必须从 PDF 原文独立读取，不得从 DB 查得。

**标注流程**：
1. `make_human_review_worksheet.py` 生成底稿（已有，列出每题的查询条件、DB 候选行、PDF 路径、该页原文开头）。
2. 标注人打开 PDF 对应页，人工读取行名、数值、单位、币种、页码。
3. 填入底稿的"人工原值/单位/币种/PDF页码/判定/复核人"列。
4. 回写 `questions.yaml`：在每题 expected.sources 加 `annotator` 和 `evidence_snippet` 字段。

**YAML 字段扩展**：

```yaml
# 结构化题（exact/cross-with-statement）
- id: exact-001
  type: exact
  question: 海底捞 2024 年营业收入是多少？
  company: 海底捞
  statement:
    type: income
    year: 2024
    period_type: annual
    line_contains: ["收入", "Revenue"]
    expected_value: 42754687       # ← 从 PDF 独立读取
    tolerance_ratio: 0.02
    expected_unit: 千元            # ← 从 PDF 表头独立读取
    expected_currency: CNY
  expected:
    answer: "42,754,687 千元"
    sources:
      - file: "2024年报"
        page: 142
        table: "损益表"
        required: true
        relevance: 2
        annotator: "human-001"          # ← 新增
        evidence_snippet: "截至2024年12月31日止年度的收入"  # ← 新增
    negatives:
      - file: "2023年报"
        page: 278
        annotator: "human-001"
  split: test                         # ← 新增
```

**双人复核**：每题由两人独立标注，不一致时第三人仲裁。记录 `reviewed_at` 和 `reviewer`。

### 4.4 查询改写变体

为每道检索题（keyword/semantic/cross）生成 2-3 个改写变体：

| 变体类型 | 示例（原题：海底捞翻台率） |
|---------|------------------------|
| 同义改写 | "海底捞同店销售" / "海底捞 same-store sales" |
| 口语化改写 | "海底捞生意怎么样" / "海底捞客流情况" |
| 中英混合 | "海底捞 turnover rate" |

在 `questions.yaml` 中每题加 `variants` 列表：

```yaml
variants:
  - query: "海底捞同店销售"
    keywords: ["同店销售"]
  - query: "海底捞 same-store sales"
    keywords: ["same-store sales"]
```

评测时对每个变体独立计算指标，取均值作为该题分数，同时报告变体间方差（衡量鲁棒性）。

### 4.5 负样本设计

| 题型 | 负样本现状 | 目标 |
|------|-----------|------|
| keyword | 20 题均有 | 维持 |
| semantic | 0 题有 | **全部加负样本**（20→30 题各 1-2 个） |
| cross | 6 题有 | 全部加 |
| no_answer | 不适用 | 10 题，expected 为空，验证返回空 |

负样本设计原则：
- 负样本是"看起来相关但不包含答案"的页面（如其他年份的同名报表、不同公司的相似段落）。
- 每个负样本标注 `annotator` 和 `evidence_snippet`（说明为什么是负样本）。

### 4.6 evidence_snippet（passage 级 GT）

为每道检索题的每个 required source 标注页内关键段落（50-100 字）：

```yaml
sources:
  - file: "海底捞研报-国信-202502"
    page: 19
    required: true
    relevance: 2
    evidence_snippet: "翻台率达到3.9次/天，同比提升0.3次"
```

评测时额外计算 passage-level 指标：
- **chunk_hit**：返回的 chunk 与 evidence_snippet 有字符重叠（Jaccard ≥ 0.3 或包含关键数字）。
- **passage_recall**：required sources 的 evidence_snippet 被命中的比例。

---

## 5. 指标体系

### 5.1 检索指标（L2）

| 指标 | 定义 | 状态 |
|------|------|------|
| Recall@k | top-k 中命中至少 1 个 required source 的题占比 | ✅ 已有 |
| Hit@1 | top-1 命中 required source 的题占比 | ✅ 已有 |
| MRR | 1/rank 的均值 | ✅ 已有 |
| nDCG@k | 归一化折损累积增益（考虑 relevance 分级） | ✅ 已有 |
| Precision@k | top-k 中命中 source 的比例 | ✅ 已有 |
| Neg@k | top-k 中命中负样本的题占比（越低越好） | ✅ 已有 |
| Neg@1 | top-1 命中负样本的题占比（越低越好） | ✅ 已有 |
| **passage_recall** | required evidence_snippet 被命中的比例 | 待加 |
| **variant_variance** | 改写变体间指标方差（鲁棒性） | 待加 |

### 5.2 结构化指标（L1+L3）

| 指标 | 定义 | 状态 |
|------|------|------|
| field_match | line_name_norm 含期望 token 的行数占比 | ✅ 已有 |
| value_match | value 在容差内的行数占比 | ✅ 已有 |
| source_match | file 匹配的行数占比 | ✅ 已有 |
| page_match | page_no 匹配的行数占比 | ✅ 已有 |
| unit_match | unit 匹配的行数占比 | ✅ 已有 |
| currency_match | currency 匹配的行数占比 | ✅ 已有 |
| **parse_accuracy** | 从 PDF 独立 golden 比对的行项目准确率 | 待加 |
| **indicator_accuracy** | indicators 表与人工计算值的匹配率 | 待加 |

### 5.3 生成指标（L4）

| 指标 | 定义 | 状态 |
|------|------|------|
| **number_accuracy** | 笔记中数字在 DB 找到匹配（容差内+来源正确）的比例 | 待建 |
| **citation_precision** | 笔记引用中正确的比例 | 待建 |
| **citation_recall** | 应引用来源中被引用的比例 | 待建 |
| **hallucination_rate** | 笔记中无来源支撑的数字占比（越低越好） | 待建 |
| **fact_opinion_separation** | 事实陈述有引用支撑的比例 | 待建 |
| **rubric_score** | 按 rubric 逐条判定的通过率 | 待建 |

### 5.4 统计指标（跨层）

| 指标 | 定义 | 状态 |
|------|------|------|
| **Wilson CI** | Recall/Hit@1 的 95% 置信区间 | 待建 |
| **bootstrap CI** | nDCG/MRR 的 bootstrap 95% 置信区间 | 待建 |
| **McNemar 检验** | 两个引擎/模型在同一题集上的差异显著性 | 待建 |

实现：写 `stock_kb/eval_stats.py`，提供 `wilson_ci(successes, n, z=1.96)`、`bootstrap_ci(scores, n_resample=10000)`、`mcnemar_test(correct_a, correct_b)` 三个函数。在 `eval_runner.save_report` 的 summary 中追加 `confidence_intervals` 字段。

### 5.5 性能指标（L6）

| 指标 | 定义 | 目标 |
|------|------|------|
| **latency_p50** | 检索延迟中位数 | FTS <50ms, hybrid <200ms |
| **latency_p95** | 检索延迟 95 分位 | FTS <100ms, hybrid <500ms |
| **index_time** | 向量索引构建耗时 | <60s（36k 块, bge-small, GPU） |
| **memory_peak** | embedding 推理内存峰值 | <4GB（bge-small, batch 256） |
| **disk_usage** | DB + 向量表磁盘占用 | 记录基线，监控增长 |

---

## 6. 引擎矩阵与实验设计

### 6.1 三引擎评测矩阵

每次代码变更后跑完整矩阵：

| 引擎 | 模型 | 命令 |
|------|------|------|
| FTS | — | `python -m stock_kb eval --engine fts` |
| vector | bge-small-zh-v1.5 | `python -m stock_kb eval --engine vector --model BAAI/bge-small-zh-v1.5` |
| hybrid | bge-small-zh-v1.5 | `python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5` |

报告写入 `eval/reports/`，用 `tools/compare_reports.py`（待建）生成对比表。

### 6.2 模型对比矩阵

| 模型 | 维度 | 后端 | 状态 |
|------|------|------|------|
| BAAI/bge-small-zh-v1.5 | 512 | sentence-transformers | ✅ 默认 |
| BAAI/bge-m3 | 1024 | FlagEmbedding | ✅ 已测 |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | sentence-transformers | ✅ 已测 |
| jinaai/jina-embeddings-v2-base-zh | 768 | sentence-transformers | 待测 |
| intfloat/multilingual-e5-large | 1024 | sentence-transformers | 待测 |

每个模型：`index --model <ID>` → `eval --engine vector --model <ID>` + `eval --engine hybrid --model <ID>`。

### 6.3 分块粒度实验

| 块大小 | 命令 | 验证 |
|--------|------|------|
| 400 | 改 `vector.CHUNK_SIZE=400` → 重建索引 → eval hybrid | semantic Recall 是否提升 |
| 800（当前） | 基线 | — |
| 1200 | 改 `vector.CHUNK_SIZE=1200` → 重建索引 → eval hybrid | 是否牺牲精确性 |

每次实验：备份 DB → 清 chunks + embedding_index → `index --rebuild` → `eval --engine hybrid` → 与基线对比。

### 6.4 RRF 权重实验

当前 hybrid_search 用等权（fts_weight=1.0, vec_weight=1.0, rrf_k=60）。

| 实验 | fts_weight | vec_weight | rrf_k |
|------|-----------|-----------|-------|
| 基线 | 1.0 | 1.0 | 60 |
| 偏 FTS | 1.5 | 0.5 | 60 |
| 偏向量 | 0.5 | 1.5 | 60 |
| 小 k | 1.0 | 1.0 | 30 |
| 大 k | 1.0 | 1.0 | 120 |

需要在 `hybrid_search` 暴露参数（当前已有但 CLI/MCP 未传），在 `eval_runner` 中支持实验配置。

### 6.5 reranker 实验（可选）

在召回后加 cross-encoder 精排：

| 模型 | 用途 |
|------|------|
| BAAI/bge-reranker-base | 中文 reranker |
| BAAI/bge-reranker-large | 更大 reranker |

流程：hybrid_search 召回 top-20 → reranker 精排 → 取 top-5 → 与基线对比。

---

## 7. 生产-评测口径对齐

### 7.1 现状差异

| 能力 | 评测 | MCP | CLI |
|------|------|-----|-----|
| 纯 vector | ✅ `--engine vector` | ✅ `engine=vector` | ❌ 只有 fts/hybrid |
| hybrid | ✅ | ✅ | ✅ `--hybrid` |
| year 过滤 | ✅ | ✅ | ✅ |
| report_type 过滤 | ✅ | ✅ | ✅ |
| 多年范围 | ❌ 单值 | ❌ 单值 | ❌ 单值 |
| 翻页 | ❌ | ❌ | ❌ |

### 7.2 对齐方案

1. **CLI `search` 增加 `--engine` 参数**：支持 `fts|vector|hybrid`，替代当前 `--hybrid` 二选一开关（保留 `--hybrid` 向后兼容）。
2. **MCP/CLI/eval 统一过滤器语义**：year/report_type/language 的过滤逻辑统一走 `search._append_filters`。
3. **向量检索过滤器下推**（优化项）：当前 vector filter 是 post-retrieval Python 过滤，candidate_k 放大补偿。优化为 SQL 下推（sqlite-vec 支持 `WHERE embedding MATCH ? AND k = ? AND company = ?`，但需确认 vec0 对非向量列的过滤支持）。
4. **LIKE 兜底排序修正**：当前 `_like_search` 按 `char_count DESC` 排序而非词频 score，应改为按 score 降序。

### 7.3 评测覆盖 MCP 工具

| MCP 工具 | 评测覆盖 | 方式 |
|---------|---------|------|
| `list_companies` | 间接 | stats 命令 |
| `list_reports` | 间接 | 结构化题 |
| `search_reports` | ✅ 直接 | 检索题 |
| `get_financial_statements` | ✅ 直接 | 结构化题 |
| `get_indicators` | 待加 | indicator 题型 |
| `get_report_text` | 间接 | 原文回取 |
| `get_source_excerpt` | 待加 | 引用核对 |

新增 `tools/test_mcp_eval.py`：对 MCP 7 工具跑评测题，验证生产路径与评测路径一致。

---

## 8. CI 回归门禁

### 8.1 现有门禁

`tools/run_eval_regression.py` 当前门槛：

| 引擎 | 检查项 | 门槛 |
|------|--------|------|
| FTS | keyword.recall_at_k | ≥ 0.75 |
| FTS | structured.hit | ≥ 26 |
| hybrid | semantic.recall_at_k | ≥ 0.30 |
| hybrid | structured.hit | ≥ 26 |

### 8.2 升级方案

**阶段 1（Phase 1 完成后）**：用独立 golden 替换后，门禁基于 test 集：

| 引擎 | 检查项 | 门槛 | 说明 |
|------|--------|------|------|
| FTS | keyword.recall_at_k | ≥ 0.70 | 独立 golden 后允许略降 |
| FTS | keyword.neg_at_k | ≤ 0.50 | 负样本污染控制 |
| FTS | structured.parse_accuracy | ≥ 0.90 | 独立 golden 比对 |
| hybrid | semantic.recall_at_k | ≥ 0.40 | 独立 golden 后 |
| hybrid | cross.recall_at_k | ≥ 0.30 | 扩题后 |
| hybrid | structured.hit | ≥ 24/26 | 允许个别行项目争议 |

**阶段 2（Phase 2 完成后）**：增加统计门禁：

| 检查项 | 门槛 |
|--------|------|
| test 集 Recall@5 的 Wilson 95% CI 下限 | ≥ 基线 - 0.05 |
| Neg@5 | ≤ 基线 + 0.05 |
| nDCG 的 bootstrap 95% CI 下限 | ≥ 基线 - 0.03 |

**门禁执行**：
```bash
python tools/run_eval_regression.py          # 快速门禁（FTS + hybrid，~30s）
python tools/run_eval_regression.py --full   # 完整矩阵（3 引擎 × dev+test，~3min）
```

门禁脚本升级要点：
- 加 `--full` 参数：跑 vector 引擎 + dev/test 分集。
- 读 `questions.yaml` 的 `split` 字段，只评 test 集。
- 输出对比表（当前 vs 基线 vs 门槛）。
- 退出码：全过 0，有劣化 1。

---

## 9. 落地路线图

### Phase 1：可信度（预计 2-3 天）

**目标**：让评测分数可信——独立 golden 替换自洽校验，负样本完善，口径对齐，门禁升级。

| # | 任务 | 产出 | 验收 |
|---|------|------|------|
| P1-1 | 填充 `human_review_worksheet.md`：26 道结构化题从 PDF 独立标注 | 标注完成的结构化 golden | 双人复核，不一致≤3 题 |
| P1-2 | 回写 `questions.yaml`：结构化题 expected_value/unit/currency 替换为独立值，加 `annotator`/`evidence_snippet`/`split` 字段 | 更新后的题集 | `eval` 跑通，structured 不再 26/26 自洽 |
| P1-3 | 为 semantic 20 题各加 1-2 个负样本 | 更新后的题集 | Neg@5 非 0 |
| P1-4 | 填充检索 GT 复核（46 题）+ 负样本复核（26 题） | 标注完成 | `human_review_worksheet.md` 二/三节填完 |
| P1-5 | CLI `search` 增加 `--engine fts\|vector\|hybrid` | 代码变更 | 三引擎均可从 CLI 调用 |
| P1-6 | 修正 `_like_search` 排序：`char_count DESC` → `score DESC` | 代码变更 | 短查询排序改善，keyword Recall 不劣化 |
| P1-7 | 升级 `run_eval_regression.py`：加 Neg@k 门禁、test 集过滤 | 代码变更 | 门禁脚本跑通 |
| P1-8 | 跑三引擎评测，记录新基线 | `eval/reports/` 新报告 | 基线文档更新到 `PLAN.md` 第 15 节 |

**Phase 1 验收标准**：
- [ ] 结构化 expected_value 全部来自 PDF 独立标注
- [ ] semantic 题全部有负样本
- [ ] CLI 三引擎可用
- [ ] 回归门禁跑通且门槛合理
- [ ] 新基线记录到文档

### Phase 2：RAG 化（预计 3-5 天）

**目标**：扩题、数据集划分、统计可信、实验矩阵。

| # | 任务 | 产出 | 验收 |
|---|------|------|------|
| P2-1 | 扩题到 170：新增 indicator 15、no_answer 10、multi_hop 10，cross 扩到 30、semantic 扩到 30、end2end 扩到 15 | 更新后的 questions.yaml | 每题型 ≥ 目标数 |
| P2-2 | 数据集划分：每题标 `split: dev\|test\|holdout`（3:5:2） | 字段填充 | 三集比例达标 |
| P2-3 | 独立 golden 标注新增题（同 P1-1 流程） | 标注完成 | 双人复核 |
| P2-4 | 查询改写变体：每道检索题加 2-3 个 variant | 字段填充 | 变体间方差可计算 |
| P2-5 | evidence_snippet 标注：每道检索题每个 required source 标页内关键段落 | 字段填充 | passage_recall 可计算 |
| P2-6 | 写 `stock_kb/eval_stats.py`：Wilson CI / bootstrap CI / McNemar 检验 | 新模块 | 函数单测通过 |
| P2-7 | `eval_runner.py` 集成统计指标 + passage_recall + variant_variance | 代码变更 | 报告含 CI |
| P2-8 | 跑模型对比矩阵（jina + e5-large + 已有 3 个） | 5 份报告 | 对比表生成 |
| P2-9 | 跑分块粒度实验（400/800/1200） | 3 份报告 | 结论记录 |
| P2-10 | 跑 RRF 权重实验 | 对比表 | 结论记录 |

**Phase 2 验收标准**：
- [ ] 题集 ≥ 170，三集划分到位
- [ ] 每道检索题有改写变体和 evidence_snippet
- [ ] 报告含置信区间
- [ ] 模型对比矩阵完成，有选型结论
- [ ] 分块粒度和 RRF 权重有实验结论

### Phase 3：生成层（预计 3-5 天）

**目标**：stock-note 生成评测自动化，端到端可评分。

| # | 任务 | 产出 | 验收 |
|---|------|------|------|
| P3-1 | 端到端题 expected 升级：page=null → 文件+页码+关键数字 | 更新题集 | 15 题全有精确来源 |
| P3-2 | 写 `tools/eval_generation.py`：数字核对 + 引用核对 + 幻觉检测 | 新工具 | 对两篇试点笔记跑通 |
| P3-3 | LLM judge 集成：按 rubric 逐条打分 | 新工具 | 与人工抽查 κ ≥ 0.6 |
| P3-4 | 对 15 道端到端题跑 stock-note 生成 + 自动评分 | 评测报告 | 生成指标有数值 |
| P3-5 | 人工抽查 20%：填 `manual_review.md` | 标注完成 | 与自动评分一致性达标 |
| P3-6 | MCP 对齐评测：写 `tools/test_mcp_eval.py` | 新工具 | MCP 7 工具覆盖 |

**Phase 3 验收标准**：
- [ ] 生成层有 5 个自动指标
- [ ] 端到端题全部自动评分 + 人工抽查
- [ ] LLM judge 与人工一致性 κ ≥ 0.6
- [ ] MCP 7 工具均有评测覆盖

### Phase 4：性能与长期（预计 2-3 天 + 持续）

**目标**：性能基线、跨公司扩展、在线闭环。

| # | 任务 | 产出 | 验收 |
|---|------|------|------|
| P4-1 | 写 `tools/eval_performance.py`：延迟/索引/内存/磁盘 | 新工具 | 性能报告生成 |
| P4-2 | 建立性能基线 | 报告 | P50/P95 有数值 |
| P4-3 | 扩展公司：加入第 3-4 家公司报告 | 新数据 | 评测集跨公司题 ≥ 20 |
| P4-4 | reranker 实验（可选） | 对比表 | 是否提升 semantic |
| P4-5 | 在线评测闭环（长期）：新报告入库 → 自动跑评测 → 报告 | 自动化 | scan + eval 联动 |

**Phase 4 验收标准**：
- [ ] 性能基线建立
- [ ] 跨公司评测覆盖
- [ ] reranker 有结论（做或明确不做）

---

## 10. 工具与自动化清单

### 10.1 已有工具

| 工具 | 路径 | 状态 | 本方案中的作用 |
|------|------|------|---------------|
| 评测执行器 | `stock_kb/eval_runner.py` | ✅ | 三引擎三层评分 |
| 人工复核底稿生成 | `tools/make_human_review_worksheet.py` | ✅ | 生成 golden 标注底稿 |
| CI 回归门禁 | `tools/run_eval_regression.py` | ✅（需升级） | 阻止劣化 |
| 单元测试 | `tests/test_core.py` | ✅ | 解析/检索核心逻辑 |
| 笔记审计 | `tools/audit_notes.py` | ✅ | 两篇试点笔记数字核对 |
| MCP 端到端测试 | `tools/test_mcp_http.py` | ✅ | HTTP 传输验证 |
| 向量索引检查 | `tools/check_vec.py` | ✅ | 向量索引健康度 |

### 10.2 待建工具

| 工具 | 路径 | 优先级 | 职责 |
|------|------|--------|------|
| 解析质量评测 | `tools/eval_parse_quality.py` | Phase 1 | PDF golden vs DB statements 逐行比对 |
| 统计模块 | `stock_kb/eval_stats.py` | Phase 2 | Wilson CI / bootstrap / McNemar |
| 报告对比 | `tools/compare_reports.py` | Phase 2 | 多份评测报告生成对比表 |
| 生成质量评测 | `tools/eval_generation.py` | Phase 3 | 笔记数字/引用/幻觉自动核对 |
| LLM judge | `tools/llm_judge.py` | Phase 3 | 按 rubric 逐条打分 |
| MCP 评测 | `tools/test_mcp_eval.py` | Phase 3 | MCP 7 工具跑评测题 |
| 性能评测 | `tools/eval_performance.py` | Phase 4 | 延迟/内存/磁盘基线 |

### 10.3 评测执行速查

```bash
# 日常回归（快速，~30s）
python tools/run_eval_regression.py

# 完整矩阵（3 引擎，~3min）
python -m stock_kb eval --engine fts
python -m stock_kb eval --engine vector --model BAAI/bge-small-zh-v1.5
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5

# 解析质量（Phase 1 后）
python tools/eval_parse_quality.py

# 生成质量（Phase 3 后）
python tools/eval_generation.py --notes-dir /path/to/notes

# 性能基线（Phase 4 后）
python tools/eval_performance.py

# 人工复核底稿
python tools/make_human_review_worksheet.py

# 报告对比
python tools/compare_reports.py eval/reports/fts_*.json eval/reports/BAAI_*.json
```

---

## 11. 验收标准总表

### 11.1 方案完整性验收

| 维度 | 验收项 | 状态 |
|------|--------|------|
| 层次覆盖 | L1-L6 六层均有评测设计与指标 | ✅ 本文件 |
| 题型覆盖 | 8 种题型（含新增 indicator/no_answer/multi_hop） | ✅ 本文件 |
| 指标覆盖 | 检索 9 项 + 结构化 8 项 + 生成 6 项 + 统计 3 项 + 性能 5 项 | ✅ 本文件 |
| 引擎覆盖 | FTS / vector / hybrid 三引擎 × 多模型 | ✅ 本文件 |
| 实验设计 | 分块粒度 / RRF 权重 / reranker | ✅ 本文件 |
| 口径对齐 | CLI / MCP / eval 统一 | ✅ 本文件 |
| 统计可信 | 置信区间 + 显著性检验 | ✅ 本文件 |
| 落地步骤 | 四阶段 × 任务 × 验收 | ✅ 本文件 |
| 工具清单 | 已有 7 + 待建 7 | ✅ 本文件 |

### 11.2 完成标准（改完必须全部通过）

- [ ] `python -m stock_kb stats --json` 正常
- [ ] `python -m stock_kb search "翻台率" --top-k 5 --json` 返回非空且命中正确
- [ ] `python -m stock_kb eval` 与 `python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5` 跑通
- [ ] `python tools/run_eval_regression.py` 通过
- [ ] `python tools/audit_notes.py` 通过（涉及笔记时）
- [ ] `tools/test_mcp_http.py` 通过（涉及 MCP 时）
- [ ] 新增命令/指标已写进 `README.md`、`AGENTS.md`
- [ ] 踩坑记录追加到 `docs/process-log.md`

### 11.3 与 AGENTS.md 完成标准的对应

本方案的完成标准与 `AGENTS.md` 第 10 节完全对齐：

| AGENTS.md 要求 | 本方案对应 |
|---------------|-----------|
| stats --json 正常 | §10.3 日常回归 |
| search 命中正确 | §7 口径对齐 |
| eval 跑通且不劣化 | §8 CI 门禁 |
| audit_notes 通过 | §3.4 生成质量 |
| test_mcp_http 通过 | §7.3 MCP 评测 |
| 文档同步 | §9 各阶段产出 |

---

## 附录 A：评测集字段规范（完整）

```yaml
version: 3
generated_at: 2026-08-20

# 通用字段（所有题型）
# id: 题目唯一编号
# type: exact|keyword|semantic|cross|end2end|indicator|no_answer|multi_hop
# question: 自然语言问题
# company: 公司名
# keywords: 检索关键词列表（可选）
# split: dev|test|holdout
# variants: 改写变体列表（可选，每项含 query + keywords）

# 结构化题（exact/cross-with-statement）
# statement:
#   type: income|balance|cashflow|equity
#   year: 2024
#   period_type: annual|interim|q3
#   line_contains: [关键词列表]
#   expected_value: 42754687    # 从 PDF 独立读取
#   tolerance_ratio: 0.02
#   expected_unit: 千元
#   expected_currency: CNY

# 指标题（indicator）
# indicator:
#   name: revenue|net_margin|roe|...
#   year: 2024
#   period_type: annual
#   expected_value: 42754687
#   expected_unit: 千元

# expected:
#   answer: "42,754,687 千元"
#   sources:
#     - file: "2024年报"          # 不含扩展名的 title 片段
#       page: 142
#       table: "损益表"            # 可选
#       required: true
#       relevance: 1|2|3
#       annotator: "human-001"    # 标注人
#       evidence_snippet: "..."  # 页内关键段落
#   negatives:
#     - file: "2023年报"
#       page: 278
#       annotator: "human-001"
#       evidence_snippet: "..."

# 端到端题（end2end）
# rubric: 评分标准列表
#   - criterion: "数字准确"
#     weight: 3
#   - criterion: "引用完整"
#     weight: 2
```

## 附录 B：基线对照表模板

每次跑完评测后，在 `PLAN.md` 第 15 节更新此表：

```
| 日期 | 引擎 | 模型 | 题集版本 | 题数 | keyword R@5 | semantic R@5 | cross R@5 | total R@5 | total Neg@5 | 结构化 | 生成 |
|------|------|------|---------|------|------------|------------|----------|-----------|-------------|--------|------|
| 2026-08-16 | hybrid | bge-small | v2(80) | 80 | 0.750 | 0.500 | 0.167 | 0.565 | 0.304 | 26/26 | 0/8 |
```
