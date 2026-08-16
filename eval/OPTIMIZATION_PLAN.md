# 评测方案优化计划与执行记录

> 目标：让评测结果从「能跑出分数」升级为「可信、可回归、可支撑模型与解析器决策」。
> 当前方案基础：`stock_kb/eval_runner.py` 三层评分（retrieval / structured / generation）+ `eval/questions.yaml` 80 题 v2。

## 1. 当前基线（优化前，2026-08-15，top_k=5）

### 检索层（纯检索题：keyword 20 / semantic 20 / cross 6）

| 方案 | keyword Recall@5 | keyword Hit@1 | semantic Recall@5 | cross Recall@5 |
|---|---:|---:|---:|---:|
| FTS5 | 0.750 | 0.350 | 0.000 | 0.167 |
| bge-small-zh + FTS | 0.550 | 0.350 | 0.300 | 0.167 |
| BGE-M3 + FTS | 0.550 | 0.350 | 0.250 | 0.167 |

### 结构化层

- 26 道带 `statement` 的 exact/cross 题全部命中。
- 重要限制：`expected_value` 来自 `statements.value`，页码来自同一数据库，属于「自洽校验」，不是独立 PDF golden。

### 生成层

- 8 道 end2end 全部待人工评分，`eval/manual_review.md` 仍是旧 4 题版本，已与题库不同步。

## 2. 诊断出的主要问题

1. Ground truth 不独立：结构化 26/26 无法证明解析器与 PDF 原文一致。
2. 负样本已标注但未参与评分：无法发现误召回、年份/公司混淆。
3. 结构化 `hit` 不要求同一条记录同时满足文件 + 页码 + 数值；`expected_unit/currency/table` 已标注但未使用。
4. cross 纯检索仅 6 题，semantic 20 题且无负样本，缺少置信区间和 hold-out。
5. 评测路径与生产路径不一致：MCP `search_reports` 只有 FTS，而 `eval --model` 测的是 hybrid。
6. 生成层没有自动评分：无数字核对、引用核对、LLM judge。
7. 报告缺少题目集 hash、DB 快照、耗时等可复现信息；失败题在 Markdown 中不可见。
8. 没有向量单独评测入口，也没有 FTS/vector/hybrid 的统一实验矩阵。

## 3. 完整优化方案

### P0：让评测可信（最高优先级）

| 编号 | 措施 | 验收标准 |
|---|---|---|
| P0-1 | 结构化 golden 独立化：从 PDF 独立抽取并双人复核 expected_value/page/unit/currency，标注 annotator、reviewed_at、evidence_snippet | 26 道结构化题的 golden 与 DB 解耦，至少抽样复核覆盖 100% 后再加新题 |
| P0-2 | 负样本纳入评分：新增 Precision@k、Neg@k、Neg@1，并在报告中列失败明细 | 每个检索方案同时报告正命中与负命中 |
| P0-3 | 结构化判定按行对齐：同一行必须同时满足 field/source/page/value | 修复后 26/26 不变，且未来错误页码会被判负 |
| P0-4 | 补 unit/currency/table 校验；当前 DB 未存单位时报告 `0/0` 并提示不可验证 | 先透明化，后续由 reparse 回填后再强制 |
| P0-5 | 检索引擎矩阵化：`eval --engine fts|vector|hybrid`，并默认支持读取 config embedding.model | 三个引擎都可通过 CLI 跑通 |
| P0-6 | 报告可复现：记录题目集 SHA-256、DB size/mtime、耗时、检索引擎；Markdown 增加失败题明细 | 新报告包含 meta 与失败明细 |
| P0-7 | 人工审核表与题库同步，覆盖全部 8 道 end2end | 8 道题均有对应审核行 |
| P0-8 | 建立评测 CI 回归门槛：脚本自动对比基线，劣化即失败 | 可一键跑 FTS 与默认 hybrid 并对比基线 |

### P1：把评测升级为 RAG 评测

| 编号 | 措施 | 验收标准 |
|---|---|---|
| P1-1 | 扩题到 150 题以上，cross 至少 30 题，semantic 至少 30 题，并加入无答案题、公司区分题、年份混淆题、多跳题 | 题型分布满足下限 |
| P1-2 | 每题增加 2 至 3 个改写变体，覆盖中英混说、缩写、口语化 | 报告可按 query variant 聚合 |
| P1-3 | 引入 passage/chunk 级 ground truth：expected 增加 evidence_snippet 或 chunk 范围 | 能区分「页对但段落错」 |
| P1-4 | 增加置信区间与显著性检验：Wilson/bootstrap、成对置换检验 | 报告含 95% CI，小样本结论受限 |
| P1-5 | 划分 dev/test/hold-out，模型选择只允许用 dev，最终结果在 hold-out 报告 | 避免在 80 题上反复过拟合 |
| P1-6 | 检索实验矩阵：chunk 400/800/1200、RRF 权重、FTS/vector 截断数、reranker、多语言模型 | 每次实验有 JSON + Markdown 对比 |
| P1-7 | MCP 对齐：给 `search_reports` 增加向量/混合检索能力，或明确评测口径为「线上 FTS + 离线 hybrid」 | 评测能力与线上能力一致 |
| P1-8 | 生成层自动化：跑 stock-note 生成笔记，提取数字与引用，与 DB 交叉核对；LLM judge 按 rubric 打分，人工抽查 20% 算一致性 | 生成层不再全部 pending_manual |
| P1-9 | 增加生成指标：数字准确率、引用精确率/召回率、幻觉率、事实/观点分离率 | 生成层报告出现自动分数 |
| P1-10 | 增加延迟与成本指标：P50/P95 查询耗时、索引耗时、模型内存、磁盘 | 支撑 NAS 部署选型 |

### P2：长期演进

| 编号 | 措施 | 说明 |
|---|---|---|
| P2-1 | 在线评测闭环 | MCP 记录真实查询，定期把真实问题人工标注后加入题库 |
| P2-2 | 错误分类仪表盘 | 失败题自动归类：年份混淆 / 公司混淆 / 语言不匹配 / 分块过粗 / 排序失败 |
| P2-3 | 跨公司扩展 | 扩展到更多公司后增加跨报告、中英文交叉一致性题 |
| P2-4 | CI 门禁 | 解析器、分块、融合、MCP 改动必须通过 eval 回归 |
| P2-5 | 模型生命周期自动化 | `下载候选模型 -> 建索引 -> eval -> 决策 -> 记录结论` 固化为一条命令 |

## 4. 本轮已执行的优化（2026-08-16）

### 4.1 代码改动

1. `stock_kb/eval_runner.py`
   - `run_eval` 增加 `engine` 参数与 `meta` 输出：题目集 SHA-256、题目数、DB size/mtime、耗时、检索引擎。
   - `_run_search` 支持 `fts / vector / hybrid` 三种引擎。
   - `_retrieval_result` 增加 `precision_at_k`、`negative_hit_at_k`、`negative_hit_at_1`、`negative_ranks`。
   - `_summarize` 聚合新增指标，并增加 retrieval `total` 汇总。
   - `_statement_match` 改为行级对齐判定：同一条记录必须同时满足 field、value、source、page；未满足时 `hit=False`。
   - `_statement_match` 读取并透出 `unit/currency` 校验状态；因 DB 当前 `statements.unit/currency` 全为空，报告中显示 `0/0`（尚不可验证）。
   - `save_report` 输出 meta、新指标列、失败题与负样本命中明细。
   - 删除遗留的 `weak_keyword_hit` 自校验逻辑，避免旧版「命中内容包含查询词即得分」口径回流。
2. `stock_kb/cli.py`
   - `eval` 子命令增加 `--engine {fts,vector,hybrid}`；不指定 `--engine` 时保持原行为（无 `--model` 为 FTS，有 `--model` 为 hybrid）。
   - vector/hybrid 未指定 `--model` 时读取 `config.yaml` 的 `embedding.model`。

### 4.2 评测集与人工审核表

- 本轮未改题面与 golden 值，避免混入两个变量。
- `eval/manual_review.md` 已同步为 8 道 end2end 题。

## 5. 本轮执行结果（top_k=5，题目集 80 题）

### 5.1 FTS（`python -m stock_kb eval --top-k 5`）

| 指标 | keyword | semantic | cross | total |
|---|---:|---:|---:|---:|
| n | 20 | 20 | 6 | 46 |
| Recall@5 | 0.750 | 0.000 | 0.167 | 0.348 |
| Hit@1 | 0.350 | 0.000 | 0.000 | 0.152 |
| MRR | 0.489 | 0.000 | 0.083 | 0.224 |
| nDCG | 0.554 | 0.000 | 0.105 | 0.254 |
| Precision@5 | 0.150 | 0.000 | 0.033 | 0.070 |
| Neg@5 | 0.650 | 0.000 | 0.667 | 0.370 |
| Neg@1 | 0.150 | 0.000 | 0.500 | 0.130 |

结构化：26/26 hit，field/value/source/page 均 26/26；unit/currency 因 DB 未存而无法自动验证（0/0）。

### 5.2 hybrid bge-small-zh（`--engine hybrid --model BAAI/bge-small-zh-v1.5`）

| 指标 | keyword | semantic | cross | total |
|---|---:|---:|---:|---:|
| Recall@5 | 0.550 | 0.300 | 0.167 | 0.391 |
| Hit@1 | 0.350 | 0.150 | 0.000 | 0.217 |
| MRR | 0.410 | 0.217 | 0.056 | 0.280 |
| nDCG | 0.444 | 0.191 | 0.083 | 0.287 |
| Precision@5 | 0.110 | 0.090 | 0.033 | 0.091 |
| Neg@5 | 0.450 | 0.000 | 0.500 | 0.261 |
| Neg@1 | 0.150 | 0.000 | 0.500 | 0.130 |

结构化：26/26 hit，与原基线一致。

### 5.3 vector-only bge-small-zh（新增基线）

| 指标 | keyword | semantic | cross | total |
|---|---:|---:|---:|---:|
| Recall@5 | 0.150 | 0.300 | 0.000 | 0.196 |
| Hit@1 | 0.100 | 0.150 | 0.000 | 0.109 |
| MRR | 0.117 | 0.217 | 0.000 | 0.145 |
| nDCG | 0.125 | 0.191 | 0.000 | 0.137 |
| Precision@5 | 0.030 | 0.090 | 0.000 | 0.052 |
| Neg@5 | 0.150 | 0.000 | 0.000 | 0.065 |
| Neg@1 | 0.050 | 0.000 | 0.000 | 0.022 |

本轮生成的报告（JSON 含逐题明细，MD 含聚合与失败明细）：

- `eval/reports/fts_20260816_203023.{json,md}`
- `eval/reports/BAAI_bge-small-zh-v1.5_20260816_202646.{json,md}`（hybrid）
- `eval/reports/BAAI_bge-small-zh-v1.5_20260816_202712.{json,md}`（vector）

### 5.4 结果解读

- 原有指标与优化前基线一致：FTS keyword 0.75、hybrid semantic 0.30、cross 0.167；结构化 26/26，说明本轮是「度量增强」，没有改变系统行为。
- 新指标暴露了两个关键事实：
  1. FTS keyword 虽然 Recall=0.75，但 65% 的题目 top-5 中混入了已知负样本，cross 的 Neg@1 高达 0.5，说明排序质量比 Recall 显示得更差。
  2. hybrid 相比 FTS 降低了 keyword Recall（0.55 vs 0.75），但负样本污染也从 0.65 降到 0.45，说明当前简单交错融合在「换回部分精确性」的同时牺牲了部分召回，后续需要做 RRF 权重/截断数实验。
- 结构化层仍无法验证单位与币种：`statements.unit/currency` 当前为空，需要后续 reparse 或解析器回填，这是 P0-4 的前置条件。

## 6. 下一步执行清单

0. 人工复核时先运行 `python tools/make_human_review_worksheet.py`，生成并填写 `eval/human_review_worksheet.md`（含 26 道结构化 golden、46 道检索来源、26 道负样本的逐项核对表）。
1. 完成 P0-1：从 PDF 独立抽取 26 道结构化题的 golden 并双人复核。
2. 完成 P0-4：回填 `statements.unit/currency`，随后把 unit/currency 纳入结构化 hit 硬判定。
3. 完成 P0-8：写 `tools/run_eval_regression.py` 或等价的 CI 脚本，自动对比基线。
4. 优先做 P1-7：让 MCP 与评测口径一致，否则 hybrid 的评测收益无法在线上使用。
5. 然后按 P1 顺序扩题、加置信区间、做检索实验矩阵、自动化生成评分。

## 7. 变更对照文件

- `stock_kb/eval_runner.py`
- `stock_kb/cli.py`
- `eval/manual_review.md`
- 本文件：`eval/OPTIMIZATION_PLAN.md`
- 过程记录：`docs/process-log.md`
