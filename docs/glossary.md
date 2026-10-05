# 术语库

写 `docs/`、`skill/`、`AGENTS.md`、`README.md` 和示意图时，读者能看见的中文用本表「用」列。新概念先补进本表，再写正文。

代码、表名、字段、命令、split 名用「代码」列的英文，不要改成中文。`docs/process-log.md` 的历史条目、`eval/reports/` 快照、样稿原文保持当时用词。

## 目录与文件

| 用 | 含义 | 代码 | 不用 |
|---|---|---|---|
| 文档 | 目录里的一条原文：年报、中报、招股、研报、电话会文字稿 | 表 `reports` | 把目录条目统称「报告」 |
| 文档目录 | 扫描后给人查询的那份清单 | `reports` | 活目录 |
| 当前使用文档 | 默认检索、指标、页保真只看这些行：非重复，且 `status` 为空或 `ok` | `live_report_sql` | 活报告、当前使用报告、当前激活报告、活文档 |
| 文档类型 | 年报、中报、招股、研报、电话会等 | `report_type` | |
| 文档年 | 目录行上的年份 | `reports.year` | 报告年（目录语境） |
| 出处 | 文件从哪来、何时取回 | `collect.meta_dir` 的 `.source.json`；`source_url` / `retrieved_at` | 把 sidecar 当成第二份目录 |
| 原文 | 磁盘上的源文件 | NAS 或 `collect.raw_dir` | |
| 页文本 | 一页可引用的正文 | `pages`；检索用 `content`，引用用 `content_orig` | |
| 三表行 | 报表页抽出的科目行，数字保持原单位 | `statements` | |
| 年报 / 中报 / 研报 / 招股 / 电话会文字稿 | 具体文种 | `annual` / `interim` / `research` / `prospectus` / `transcript` | 用「报告」统称这些文种 |

## 验收与评测

| 用 | 含义 | 代码 | 不用 |
|---|---|---|---|
| 对照页 | yaml 里标好、并从 PDF 原文核对过的那一页 | `expected.sources[].page`；`golden_source: pdf` | 黄金页 |
| 对照答案 | 那一题的对照数字、文件、页码 | `expected_value` 等；须 `golden_source: pdf` | 黄金 |
| 期望页 | 检索题希望命中的页 | `expected.sources[]` | 黄金页 |
| 标注 | 题集里「怎样算对」 | GT；`eval/questions.yaml` | 从数据库抄回 yaml |
| 验收 | 对产物做的检查总称 | | 校验门、门 |
| 检查 | 验收里的一项，例如结构化 L1 | EVAL 表「检查」列 | 门（作列名） |
| 门槛 | 这项检查的通过线，例如 29/29、≥ 0.75 | | 把门禁、门槛、设门混成一个「门」 |
| 回归测试 | `run_eval_regression.py` 这一套检查 | `python tools/run_eval_regression.py` | 评测语境里单独写「回归」 |
| 卡住回归测试 | 不达标则回归测试失败 | | 门禁、挡回归、设门、当门、卡住回归 |
| 只展示 | 写出数字，失败也不卡住回归测试 | 覆盖矩阵；题数不足 5 的分桶 | 只报告、不设门 |
| 冻结回归测试 | 维护者本机跑的那套冻结检查 | split `freeze` | 黄金回归、冻结回归 |
| 诊断集 | 对照用，默认不卡住回归测试 | split `diag` | |
| 页保真 | 抽检原句是否还在 `content_orig` | `python -m stock_kb fidelity` | 空清单当成通过 |
| 闸门 | 入库时 OCR 是否触发、输出是否合格 | `is_ocr` 0/1/2 | 用闸门称呼评测验收 |

## 三层与稿件

| 用 | 含义 | 代码 | 不用 |
|---|---|---|---|
| 证据层 | 原文变成可引用的页；财报再抽出三表行 | | |
| 知识库层 | 科目、检索、路由；不改原文 | | |
| 报告层 | agent 写稿，数字回到这次查询 | | 用「报告」称呼目录里的文件 |
| 报告系统 | 三层整体 | 本文 `docs/report-system.md` | |
| 扫描稿 / 扫描报告 | stock-note 按框架写出的稿 | `compose-note` / `render-note` | |
| 评测报告 | `eval/reports/` 里的一次评测记录 | | |
| 终稿 | 带 `run_id`、交给 `audit-report` 的那份 | | 把材料底稿当成终稿 |

## 入库

| 用 | 含义 | 代码 | 不用 |
|---|---|---|---|
| 缺口 | NAS 上还没有的文档类型，才去 `fetch` | `stats` 的 `reports_by_type` / `reports_by_origin` | |
| 版本选举 | 同一 `logical_key` 只留一条当前使用文档 | `elect_logical_key` | |
| 折行 | pdfplumber 视觉行把一个科目拆成两行 | `_ends_mid_phrase` | 说成向量切片 |

## 怎么补词

1. 先在上表加一行：用、含义、代码、不用。
2. 读者文档和示意图改用新词。
3. 标识符、表名、字段名保持英文。
