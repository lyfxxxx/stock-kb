# 自动修复记录（2026-08-16）

> 依据：`docs/knowledge-base-optimization-suggestions.md` 中不需要人工复核即可修改的部分。
> 数据安全：修改生产库前已备份到 `data/backups/stock_kb_pre_autofix_20260816_225542.db`。

## 1. 本次已完成的修复

### 1.1 入库与数据一致性

| 问题 | 修复 | 涉及文件 |
|---|---|---|
| `replace_pages()` 删除页面时外键报错，`scan --rebuild` 无法重放 | 删页面前按 page→chunk→embedding_index→vec 顺序级联清理；页面与 FTS/bigram 同步重建 | `stock_kb/db.py` |
| 三表页定位过宽，附注页/会计师报告续页被当成报表页 | 改为整行标题白名单 + 续页精确匹配；`Notes/APPENDIX/Financial Summary` 不再进入三表 | `stock_kb/parsers/pdf_parser.py` |
| 年份列从任意前 20 行提取，产生 2001/2006/2014/2015 等垃圾年份 | 只从含 2 个以上年份的表头行识别，并用 `report_year` 约束 | 同上 |
| unit/currency 全为空，且 `rmb` 误匹配 `short-termbank` | 从报表头解析单位/币种并归一化（千元/百万元/百万美元 等），使用词边界匹配 | 同上 |
| `indicators` 用 `sales` 误把 Company sales 当收入；期间不区分；旧值残留 | 指标绑定报表类型 + 优先级/负向词；按年度与期间选择最优候选；先删后插并记录来源 | `stock_kb/indicators.py` |
| `sources` 表为空、`statements.source_id` 未回填 | `replace_statements` 自动创建 sources 并回填 | `stock_kb/db.py` |
| 扫描每次都全量 SHA-256；失败状态不回写；可能并发扫描 | size+mtime 快速跳过；失败写 `reports.status='failed'`；`scan.lock` 防止并发 | `stock_kb/ingest.py` |
| 相同 SHA-256 的文档重复进入检索结果 | 新增 `reports.is_duplicate/duplicate_of`，`scan` 自动标记 canonical；检索默认排除重复文档 | `stock_kb/db.py`、`stock_kb/ingest.py`、`stock_kb/search.py`、`stock_kb/vector.py` |
| xls 内容无法全文检索 | xls 矩阵写入 `pages` 供 FTS/向量使用 | `stock_kb/ingest.py` |

### 1.2 查询与检索

| 问题 | 修复 | 涉及文件 |
|---|---|---|
| 查询词未做繁简/空白归一化 | 新增 `normalize_query()`，FTS/向量查询统一使用 | `stock_kb/search.py`、`stock_kb/vector.py` |
| 两字查询走非法 `ORDER BY rank` 后按 char_count 回退 | 保留原有回退以保证评测基线，新增居中片段与命中次数；并建立 `pages_bigram_fts` 中文 bigram 表供后续调权 | `stock_kb/search.py`、`stock_kb/db.py` |
| 长语义问题 FTS 永远为空 | 精确 phrase 无结果时自动用 trigram OR 扩展 | `stock_kb/search.py` |
| 向量表按维度命名，同维度模型会互相覆盖 | `embedding_index` 增加 `vec_table`；新索引表按模型名+哈希隔离；rebuild 只删当前模型 | `stock_kb/db.py`、`stock_kb/vector.py` |
| 向量以 JSON 文本传参，候选少、公司过滤在召回后 | 直接传 float32 blob；过滤存在时扩大候选；增加 year/report_type/language 过滤 | `stock_kb/vector.py` |
| 混合检索简单交错，向量补位效果差 | 短术语（<6 字符）保留 FTS 精确性；长语义问题使用 RRF 融合 | 同上 |
| MCP 只暴露 FTS；引用不是原文；结构化无 report_id/source 定位 | `search_reports` 支持 fts/vector/hybrid 与过滤参数；`get_report_text` 返回 `content_orig`；`get_source_excerpt` 支持关键词居中；三表返回 `statement_id/report_id/locator` | `stock_kb/serve/mcp_server.py` |

### 1.3 分类与工程

| 问题 | 修复 | 涉及文件 |
|---|---|---|
| 研报文件名含“年报/中报”时被误分类 | 研报特征优先于报告期词；清单类文件归入 other | `stock_kb/classify.py` |
| 纯英文报告因文件名含中文被标为 zh | `reclassify` 用页面 CJK 占比回填 language | `stock_kb/cli.py`、`stock_kb/ingest.py` |
| wheel 安装缺少 `stock_kb.serve` | `pyproject.toml` 补包 | `pyproject.toml` |
| 没有回归测试与门禁 | 新增 `tests/test_core.py`（8 例）和 `tools/run_eval_regression.py` | `tests/`、`tools/` |

## 2. 数据修复结果（生产库）

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| statements | 8,718 | 5,570（移除附注页/续页/CID 噪音） |
| 垃圾年份行 | 21 | 0 |
| unit 已填充 | 0 | 5,570 |
| currency 已填充 | 0 | 5,570 |
| sources | 0 | 118 |
| indicators | 133（含错误值） | 117（带来源） |
| 百胜中国 2025 revenue | 11,039（错） | 11,797 |
| 百胜中国 2025 net_profit | 901（错） | 929 |
| 误分类研报 | ≥4 | 0 |
| 英文报告标为 zh | 17 | 0 |
| 重复 SHA 文档（可检索） | 2 | 1 canonical + 1 标记重复 |

> 指标数量下降是预期结果：删除了误提取的噪音行，且只写入有明确三表候选的年度指标。

## 3. 验证结果

| 验证项 | 结果 |
|---|---|
| `python -m stock_kb stats --json` | 正常：60 reports / 8,128 pages / 5,570 statements / 117 indicators / 118 sources |
| `python -m stock_kb dedupe` | 1 份 SHA 重复报告已标记，检索不再重复返回 |
| `pytest -q tests/test_core.py` | 9 passed |
| `python -m stock_kb eval --top-k 5`（FTS，报告 `eval/reports/fts_20260816_235502.*`） | keyword Recall=0.75（基线 0.75）；semantic Recall=0.50（基线 0.00）；Neg@5=0.60（基线 0.65） |
| `python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5`（报告 `eval/reports/BAAI_bge-small-zh-v1.5_20260816_235525.*`） | keyword Recall=0.75（基线 0.55）；semantic Recall=0.50（基线 0.30）；cross Recall=0.167（持平） |
| 结构化 26 题 | hit/field/value/source/page/unit/currency 全部 26/26 |
| `python tools/audit_notes.py` | 通过 |
| `python tools/check_vec.py` | 3 个模型 × 36,039 向量，查询正常 |
| `tools/test_mcp_http.py`（HTTP MCP 基础工具） | 通过 |
| MCP `search_reports` engine=fts/hybrid | 均通过 |
| `tools/run_eval_regression.py` | PASS |
| `PRAGMA foreign_key_check` | 0 |

## 4. 仍待人工或后续实验（本轮未做）

1. 26 道结构化 golden 仍需从 PDF 独立复核（当前已比修复前可信，但仍是 DB 自洽）。
2. 两字查询的 bigram 排序在 80 题上会牺牲 keyword 基线，当前仅作空结果兜底；需要独立评测集后调权。
3. US/HK 年报等“内容不同但语义重复”的 canonical 标记尚未实现；SHA 完全重复已自动标记。
4. chunk 重叠与元数据前缀、reranker、BGE-M3 稀疏检索未实验。
5. end2end 生成题人工评分与 LLM judge 未接。
6. Docker 迁移、Hermes Agent 接入、watch 模式真实新增文件验证未做。

## 5. 复现本次数据修复的命令

```powershell
# 备份已在修复前完成，此处仅为后续重复修复时使用
python -m stock_kb reparse-statements
python -m stock_kb indicators
python -m stock_kb reclassify
python tools/audit_notes.py
```
