# 知识库构建与查询方案优化建议

> 检查对象：`stock-kb` 当前实施状态（2026-08-16，commit `2a668cd` 附近）。
> 检查范围：`stock_kb/` 全部核心模块（db / ingest / classify / parsers / search / vector / indicators / eval_runner / serve）、`eval/`、`tools/`、`config.yaml`、`pyproject.toml`，并对 `data/stock_kb.db` 做了只读数据体检与一次临时副本上的破坏性实验。
> 本文只提建议，不改动生产库；涉及 `data/stock_kb.db` 的操作均已先在临时副本上验证。

## 0. 结论先行

当前方案已经能跑通「扫描 → 解析 → FTS/向量索引 → MCP → 笔记」闭环，但距离“可信知识库”还有一组必须修复的正确性问题。最重要的问题不是检索模型不够大，而是：

1. **入库链路不可安全重放**：页面表已与向量分块表建立外键，`replace_pages()` 先删 `pages` 会触发 `FOREIGN KEY constraint failed`。也就是说，在已建向量索引的库上执行 `scan --rebuild` 会失败。
2. **三表解析存在系统性误提取**：当前 8,718 条 `statements` 中，按保守口径至少有 898 条（10.3%）来自英文招股书附录的“附注页/会计师报告续页”，不是三大报表。这些噪音已经污染了 `indicators`（例如百胜中国出现了 2001/2006/2014/2015 年“收入”）。
3. **指标计算会取错科目**：`revenue` 的匹配词包含 `sales`，而报表行顺序中 `Company sales` 常先于 `Total revenues` 出现，导致百胜中国历年 `revenue` 指标普遍取成“公司自营收入”，而不是“总收入”。2025 年指标为 11,039，而总收入为 11,797；净利率、ROE 等派生指标随之失真。
4. **两字中文检索基本不可用**：FTS5 trigram 不索引 <3 字的词，当前代码对短查询先走了非法 `ORDER BY rank`，异常后回退为按 `char_count DESC` 排序，等价于“返回最长页”。这解释了“股息、估值”类查询为何会返回 2018 年报的无关长页。
5. **多模型向量表按维度命名，而不是按模型隔离**：`chunks_vec_<dim>` 会让同维度的两个模型互相覆盖。当前 `MODEL_DIMS` 中 BGE-M3 与 multilingual-e5-large 都是 1024 维，一旦后者建索引并 `--rebuild`，会删除前者的向量表，但元数据仍认为索引存在。
6. **评测的 26/26 结构化命中是“自洽”而非“正确”**：`expected_value` 与页码来自同一数据库，所以解析器取错科目、取错年份时，评测仍然可能满分。本次发现的 `indicators` 取错科目问题就没有被现有评测拦截。

除上述 P0 问题外，查询侧还有大量可提升项：查询词未做繁简归一化、混合检索融合过于简单、MCP 只暴露 FTS、引用片段不来自原文、短查询与长尾查询缺乏改写、结果缺乏多样性控制等。详细证据与建议见下文。

---

## 1. 检查基线

### 1.1 数据规模

| 指标 | 当前值 |
|---|---:|
| 公司 | 2（海底捞、百胜中国） |
| 报告 | 60 |
| 页 | 8,128（平均 2,748 字符/页，59 页 OCR，13 页空文本） |
| 三表行项目 | 8,718（unit/currency 全部为空） |
| 指标 | 133 |
| 分块 | 36,039 |
| 向量索引 | 3 个模型 × 36,039 块（384/512/1024 维） |
| 数据库大小 | 约 542 MB |
| sources 表 | 0 行（未填充） |

### 1.2 当前评测基线（top_k=5，摘自 `eval/OPTIMIZATION_PLAN.md`）

| 方案 | keyword Recall@5 | keyword Neg@5 | semantic Recall@5 | cross Recall@5 | 结构化 |
|---|---:|---:|---:|---:|---:|
| FTS | 0.750 | 0.650 | 0.000 | 0.167 | 26/26 |
| bge-small-zh + FTS（hybrid） | 0.550 | 0.450 | 0.300 | 0.167 | 26/26 |
| bge-small-zh（vector） | 0.150 | 0.150 | 0.300 | 0.000 | 26/26 |

> 注意：结构化 26/26 是数据库自洽校验，不是独立 PDF golden。本文第 5 节会给出反例，说明该分数掩盖了解析与指标错误。

### 1.3 数据健康度快照

只读检查结果：`PRAGMA foreign_key_check` 当前为 0；`pages`/`pages_fts`/`chunks`/`embedding_index` 数量一致；`manifest` 与 `reports` 一一对应。但这些检查不能发现下面要讲的“一旦重放就破坏”的问题，也不能发现解析内容错误。

---

## 2. 问题清单（按优先级汇总）

| 编号 | 问题 | 影响 | 优先级 |
|---|---|---|---|
| B-1 | `replace_pages()` 删除页面前未处理 `chunks`/向量，外键报错 | `scan --rebuild` 在向量化库上无法重解析报告 | P0 |
| B-2 | 三表页定位过宽，附注/续页被当作报表页 | 保守口径至少 898/8,718 条三表行是噪音 | P0 |
| B-3 | 年份列、单位、币种未可靠解析 | 出现 2001/2006/2014/2015 等垃圾年份；全部 unit/currency 为空 | P0 |
| B-4 | `indicators` 关键词匹配无优先级、无报表期过滤、无来源记录 | 百胜中国收入/净利等指标取错；派生指标连带错误 | P0 |
| B-5 | 短于 3 字的中文查询按 `char_count` 排序 | 两字词查询不可用，如“股息、估值” | P0 |
| B-6 | 向量表名只按维度隔离 | 同维度模型互相覆盖/无法区分 | P0 |
| B-7 | 查询词未做繁简/大小写/空白归一化与改写 | 繁体查询全部落空；自然语言长句 FTS 全部落空 | P1 |
| B-8 | hybrid 融合是“FTS 先行 + 向量补位”的简单交错，无分数融合 | semantic 提分有限；向量结果被挤压；排序不稳定 | P1 |
| B-9 | MCP 只暴露 FTS，且引用片段不是原文 | 评测里的 hybrid 收益未上线；笔记引用可能引用简体改写文本 | P1 |
| B-10 | 分类规则优先级错误、语言只按文件名判断 | 研报被分为年报/中报；17 份纯英文报告标为 `zh` | P1 |
| B-11 | 重复/近重复文档无主源标记 | 同一 PDF 重复入库；US/HK 年报同义内容挤占 top-k | P1 |
| B-12 | 页面更新与 chunk/向量/指标之间没有版本同步机制 | 内容变化后向量与指标会静默过期 | P0/P1 |
| B-13 | `scan` 每次全量 SHA-256、失败状态不回写、无并发锁 | NAS 全量扫描慢；失败不可诊断；watch 模式脆弱 | P2 |
| B-14 | 向量以 JSON 文本传参写入、候选数固定 `top_k*5`、公司过滤在召回后 | 写入有序列化开销；召回候选不足；按公司过滤可能空结果 | P1/P2 |
| B-15 | `sources` 表未填充；MCP 结构化结果无 `report_id/source_id` | 审计与引用无法直接落到统一来源记录 | P1 |
| B-16 | 没有单元测试/回归门禁；打包漏了 `stock_kb.serve` | 重构风险高；wheel 安装会缺 MCP 模块 | P2 |

---

## 3. 构建链路：问题证据与优化建议

### 3.1 P0：修复 `replace_pages()` 的 chunk/向量级联（B-1、B-12）

**证据**

在数据库临时副本上复现：选择任意一个已建向量的报告，调用 `db.replace_pages()` 时得到：

```text
IntegrityError: FOREIGN KEY constraint failed
```

原因：`chunks.page_id REFERENCES pages(id)` 没有 `ON DELETE CASCADE`；`replace_pages()` 先 `DELETE FROM pages`，随后才会重建 `pages`。已建向量的页面还关联 `chunks`、`embedding_index` 和 `chunks_vec_*`，因此删除失败。

**建议**

1. 在 `db.py` 增加一个事务化的 `replace_report_content()`（或改造 `replace_pages()`）：
   - 先按 `page_id` 收集要删除的 chunk id；
   - 删除 `embedding_index` 中这些 chunk 的所有模型记录；
   - 删除对应 `chunks_vec_<model_table>` 中的向量（必须按实际模型表名删，而不是按 dim 猜）；
   - 再删 `chunks`、`pages_fts`、`pages`；
   - 最后插入新页面，并在 `pages/chunks` 上打版本号或 `content_hash`。
2. 短期可以同时把 `chunks.page_id` 改为 `ON DELETE CASCADE`，但**不能只靠 CASCADE**：`embedding_index` 与虚拟向量表不会被自动清理，必须显式删除。
3. `scan --rebuild` 改为先自动备份 DB（或至少要求 `--yes`/`--backup`），再执行重解析。
4. 重解析后标记该报告向量失效，提示用户执行 `index`；将来理想状态是 `scan` 直接触发增量索引。

**验收标准**

- 在临时副本上对任意已建向量报告执行重建页面成功，`foreign_key_check` 仍为 0；
- 重建后旧 chunk/向量记录为 0 或已重建，`tools/check_vec.py` 仍一致；
- 原库 `stats` 数字不劣化。

### 3.2 P0：收紧三表页定位，排除附注页（B-2）

**证据**

当前 `detect_statement_pages()` 只要页面正文任意位置出现 `cash flow(s)` 等关键词就加入候选，随后 `_is_statement_title_page()` 又把“前 10 行内出现 `(continued)`”当作续页标志。结果：

- 全库产生了 1,099 个候选“报表页”，其中 448 个通过标题判断；
- 通过标题判断的页面里有 260 个首行是 `Notes to the Consolidated Financial Statements` 或 `APPENDIX I ACCOUNTANTS’ REPORT`；按“第二行是否为真正的报表标题”复核，其中 255 个是附注/会计师报告续页，只有 5 个是嵌套在附录里的真报表页；
- 这 255 个误判页面贡献了 **至少 898 条 statement 行**（占总行数 10.3%），例如：

```text
statement_type=balance, line_name="For executives who were hired or re-hire", value=2001, year=2001
statement_type=cashflow, line_name="(Topic 606) (ASU 2014 -9)", value=-15, year=2014
statement_type=cashflow, line_name="Total $5,688$2,111 $115 $517 $", value=-38, year=2015
```

**建议**

1. 报表页判定改为“白名单优先”：
   - 仅在每页前 1–3 个有效文本行中做报表标题精确/前缀匹配（`Consolidated Statements of Income/Cash Flows/Financial Position/Changes in Equity`、`综合损益表/财务状况表/现金流量表/权益变动表` 等）；
   - `(continued)` 只有在同一页前几行同时再次出现报表标题时才视为续表；
   - 首行是 `Note(s)`、`APPENDIX`、`Company Guide`、`Management Discussion` 等直接排除。
2. 对续页引入状态机：一个报表区块从明确标题页开始，到下一个章节标题（`Notes`、`Independent Auditor's Report` 等）结束；不要在每页独立猜标题。
3. 对招股书附录中嵌套的“ACCOUNTANTS’ REPORT”内嵌报表，单独识别真正的报表首页与结束页，而不是把其后续附注全部纳入。

**验收标准**

- 误提取的 `Notes/APPENDIX` 页行为 0；
- 重跑 `reparse-statements --company 百胜中国` 后，2001/2006/2014/2015 等垃圾年份消失；
- 三表行数变化有明确 diff 报告，且结构化评测不劣化。

### 3.3 P0：可靠解析年份列、单位与币种（B-3）

**证据**

`_detect_year_columns()` 只在前 20 行里收集年份，遇到附注中的 “2006 to 2015” 就会取到 2006/2015；`_extract_currency()` 已经实现但从未被调用；`statements.unit/currency` 当前 8,718 行全部为 NULL。单位缺失意味着“千元 vs 百万元”无法区分，跨公司比较和派生指标都不可靠。

**建议**

1. 年份只在“表头行”中识别：表头行通常同时出现 2 个相邻年份（如 `2025 2024`）、且数值列与该表头对齐；再用 `report.year` 约束（当前年 ±1，招股书允许多年但需显式规则）。
2. 从报表标题附近解析单位/币种：`RMB'000`、`人民币千元`、`US$ million`、`$ million` 等；写入 `statements.unit/currency`，并增加一个 `scale_to_unit` 规则表，便于后续换算。
3. 至少保存 `value_raw` 与解析后的 `value` 两种值，便于人工复核和回归。

**验收标准**

- 全部报表行的 `unit/currency` 至少覆盖年报三大表 100%，研报可继续为空；
- 解析出单位后，评测 P0-4 的 unit/currency 校验从 `0/0` 变为可验证；
- 与 `audit_notes.py` 交叉验证仍然通过。

### 3.4 P0：修复 `indicators` 的科目匹配与口径（B-4）

**证据**

`indicators.py` 的 `LINE_RULES["revenue"]` 包含关键词 `"sales"`，而 SQL 行序里 `Company sales` 通常先于 `Total revenues`；`buckets` 对同一 `(company, year)` 采用“第一个匹配行生效”，后续行被忽略。结果：

| 公司/年份 | indicators 当前值 | 正确的总收入（同库可查） | 问题 |
|---|---:|---:|---|
| 百胜中国 2025 | 11,039 | 11,797 | 取成 Company sales |
| 百胜中国 2024 | 10,651 | 11,303 | 取成 Company sales |
| 百胜中国 2023 | 2,023 | 10,978 | 甚至取到“年份数字”当收入 |
| 百胜中国 2006/2014/2015 | 38 / 606 / -38 | 不存在 | 来自误提取行 |
| 百胜中国 2025 net_profit | 901 | 929（归母）或 1,004（含少数股东） | 取成含少数股东且年份错位 |

派生指标（net_margin、ROE）由这些错误值计算，因此同样不可信。

**建议**

1. 把指标定义改成显式规则表，而不是关键词列表：
   - 每个指标绑定 `statement_type`；
   - 给每个候选科目设置优先级与负向词（例如 revenue 优先 `Total revenues`、`收入`、`營業收入`；排除 `Company sales`、`Other revenues`、`Other income`、`Inter-segment`）；
   - net_profit 区分“归母/含少数股东”并明确指标口径，建议拆成 `net_profit` 与 `net_profit_incl_nci`。
2. `buckets` 键增加 `period_type`、`report_id`（或 canonical source），同一年度优先取年报，而不是取 SQL 自然顺序的第一行。
3. 结果必须带 `source_id`（或 report_id + page_no + line_id），写入 `indicators`；`compute_indicators` 先删除或 upsert 本规则版本的全部派生指标，避免旧值残留。
4. 单位不统一时禁止直接相除/相加；先换算到统一单位或标记 `unit_mismatch`。

**验收标准**

- 百胜中国 2025 `revenue=11,797`、`net_profit` 口径明确（929 或 1,004 二选一并写清定义）；
- 海底捞与百胜中国近 3 年指标与 `audit_notes.py` 及独立 PDF 复核一致；
- `get_indicators` 返回 `source` 信息，垃圾年份消失。

### 3.5 P1：修正分类与语言识别（B-10）

**证据**

- `classify_report()` 的顺序是 `prospectus → annual → interim → q3 → research`。文件名含“年报/中报”的券商研报会被判为年报/中报。当前库至少有 4 份误分类：
  - `研报-华创证券-2021-2020年报解读...` → annual
  - `研报-平安证券-2022-中报业绩点评...` → interim
  - `国信证券_百胜中国_2023年报费用管控效果显著` → annual
- `language` 仅凭文件名是否有 CJK 判断；当前 17 份正文几乎纯英文的报告被标为 `zh`（百胜中国 US 年报、英文招股书、DBS 英文研报、海底捞英文招股书等）。

**建议**

1. 在解析出首页文本后回填 `language`（按 CJK 字符占比阈值），文件名语言只作为初始值；`reclassify` 同时基于正文重算。
2. 分类优先级改为“研报特征优先于报告期词”，例如文件名/目录含 `证券|研报|点评|HK|DBS|维持|买入|评级` 时判为 `research`；无法确定时用首页文本再确认。
3. 扩展 `period_type`：H1/Q1/Q2/Q3/FY，并新增 `publication_date`、`fiscal_period_end` 字段；年份从标题和首页联合解析，避免第一组 4 位数字即年份。

**验收标准**

- 上述 4 份文件分类正确；17 份英文报告语言为 `en`；
- `stats` 的 `reports_by_type` 与人工清单一致。

### 3.6 P1：重复文档去重与主源标记（B-11）

**证据**

- 两份不同路径的报告 SHA-256 完全相同：`海底捞研报-国信-202502` 与 `研报-国信证券-2025-火锅主业热辣滚烫`。
- 百胜中国 2022–2025 同时存在 `_Annual_Report`（US）与 `_HK_Annual_Report`（HK）两套年报；中文/英文招股书也成对存在。
- 搜索结果中这些重复文档会同时占据 top-k，例如“翻台率”前 5 里同一 PDF 的两个副本占 4 个位置。

**建议**

1. `manifest` 增加 `content_group`（按 SHA 分组）；入库时同一 SHA 只建一份可检索副本，其余路径只作别名记录；或者保留但 FTS 命中后做结果去重。
2. `reports` 增加 `source_priority`/`is_canonical`，例如同一年度优先 `US 10-K/Annual Report` 或人工指定的主年报，HK 版本作为备选；结构化查询默认只返回 canonical，或显式标注 duplicate_of。
3. 检索结果增加文档级 diversity（见 4.4），避免同文档多页挤占 top-k。

**验收标准**

- SHA 重复组数为 0 或重复文档不再重复进入检索；
- `search "翻台率" --top-k 5` 返回至少 3 个不同文档。

### 3.7 P2：扫描效率、失败状态与并发控制（B-13）

**证据/问题**

- `_process_file()` 每次扫描都对所有文件重新计算 SHA-256，即使 `manifest` 已有同路径、同 size、同 mtime 记录，导致每次 `scan` 都全量读取 NAS。
- 解析失败的文件只打印 `[error]`，`reports.status` 停留在 `parsing`，`manifest` 没有 error/attempts/next_retry。
- `scan --watch-interval` 是裸 `while True`，数据库错误会终止循环；没有 pid/lock，手工扫描与 watch 可能并发。
- `.xls` 只读第一个 sheet 且不写 `pages`，因此 xls 内容无法全文检索；`.html/.htm` 原文含标签直接入库。

**建议**

1. 快速路径：`manifest` 中 size + mtime 未变时默认跳过 SHA 计算；提供 `--verify-hash` 强制校验。注意 NAS 文件 mtime 可能不可靠，可把“快速路径”做成配置项。
2. 失败时写 `reports.status='failed'` 与 `manifest.error`；watch 循环捕获异常、写结构化日志、保留运行 pid；增加 `--once` 和文件锁。
3. `.xls` 至少把每个 sheet 的关键区域文本写入 `pages` 供检索；HTML 先用文本抽取（如 BeautifulSoup/lxml）去标签；非 UTF-8 文件显式记录失败而不是静默 `errors="ignore"`。
4. 增加 `scan --backup` 或破坏性操作前自动备份。

### 3.8 P0/P1：向量索引的模型隔离、版本同步与存储（B-6、B-12、B-14）

**证据/问题**

- 向量表命名 `chunks_vec_{dim}`，`embedding_index` 不记录表名。`MODEL_DIMS` 中 BGE-M3 和 multilingual-e5-large 均为 1024 维；一旦后者建索引并 `--rebuild`，会 `DROP TABLE chunks_vec_1024`，把 BGE-M3 的向量删除，而 `embedding_index` 仍保留 BGE-M3 的 chunk 记录，造成元数据与向量不一致。
- `replace_pages()` 的页面更新与 `chunks/embedding_index/vec` 没有同步；即使修好外键，旧向量也会静默过期。
- 向量以 `json.dumps(vec.tolist())` 文本传参写入。实测 `chunks_vec_*` 表中每行长度分别是 1,536/2,048/4,096 字节，等于 `dim × 4`，说明 sqlite-vec 内部已转成 float32 存储；三模型向量合计约 276.8 MB，约占当前 542 MB 库的一半。因此优化点不是“再省一半空间”，而是避免 JSON 序列化/反序列化开销、避免文本精度歧义。
- `vector_search()` 固定召回 `top_k*5` 个 chunk 再聚合到页面，候选数偏少；`company` 过滤发生在召回之后，可能返回不足 top_k；片段取 chunk 前 160 字，不是命中片段。
- chunk 为 800 字硬切、无重叠、无标题/年份/公司元数据，跨年、跨公司容易混淆。

**建议**

1. 将 `embedding_index` 增加 `vec_table TEXT`（或建 `models` 表），`chunks_vec_<model_slug>` 按模型隔离；`rebuild` 只 drop 该模型的表；查询用元数据中的表名。
2. `chunks` 增加 `content_hash`、`model_version`（或 `index_version`）；页面变化后 chunk 失效重建，向量按 hash 增量更新。
3. 向量写入直接传 float32 blob（`np.asarray(vec, dtype=np.float32).tobytes()`），查询同样传 blob；在新库上做一次写入耗时与 QPS 基准。预期收益主要是写入吞吐，不是存储体积。
4. 召回候选数可配置（如 `top_k * 20`，封顶 500）；公司过滤下推到 SQL 的 chunk→page→report 连接，或先取足量候选再截断，保证返回 top_k。
5. 分块加 50–100 字重叠，并给每块前置元数据行（公司、报告类型、年份、标题、章节/页码），嵌入时使用；注意元数据只进索引、不进原文引用。
6. 研究 reranker（bge-reranker）与 MMR 多样性，作为后续实验而非默认路径。

**验收标准**

- 建两个同维度模型后互不覆盖，`check_vec` 两者均可查询；
- 页面重建后 `chunks/embedding_index/vec` 三者一致；
- blob 写入与查询速度不劣于 JSON 方案；`check_vec` 三者模型均可查询且结果一致。

### 3.9 P1：填充 `sources` 并贯通引用链（B-15）

**建议**

1. 解析阶段写入 `sources(report_id, company, report_title, page_no, table_index, locator, snippet)`，并给 `statements.source_id`、`indicators.source_id` 回填。
2. `locator` 统一为 `公司 | 报告标题 | 页码 | 报表名 | 行项目`，MCP 直接返回该字段。
3. `tools/audit_notes.py` 与 skill 自查优先核对 `source_id`，减少“现场拼 locator”的不一致。

### 3.10 P2：数据库迁移、测试与打包（B-16）

- `_migrate()` 目前只补 `content_orig`，没有 schema version 表。建议增加 `schema_version` + 顺序迁移脚本，并把一次性工具从生产库迁移改为受 CLI 管理。
- 全仓库没有 `tests/`。至少为 `classify`、`db.replace_pages`、`fts_search`、`_split_chunks`、`indicators` 建 pytest 回归，使用临时 SQLite 文件。
- `pyproject.toml` 的 `packages` 缺 `stock_kb.serve`，wheel 安装会缺 MCP 模块；补齐并考虑把 `tools` 中常用运维脚本纳入安装或移到 `stock_kb` 子命令。

---

## 4. 查询链路：问题证据与优化建议

### 4.1 P0：修复 <3 字查询（B-5）

**证据**

`search.fts_search()` 对 `len(q) < 3` 生成：

```sql
... WHERE p.content LIKE ? ESCAPE '\' ORDER BY rank LIMIT ?
```

但此时 SELECT 列表没有 `rank`，SQLite 抛 `OperationalError` 后进入 fallback：

```sql
... WHERE p.content LIKE ? ORDER BY p.char_count DESC LIMIT ?
```

实测：

```text
search "股息" top-5
#1 海底捞 2018年报 p16  (2,365 字符)
#2 海底捞 2018年报 p60
#3 海底捞 2018年报 p61
#4 海底捞 2018年报 p62
#5 海底捞 2018年报 p71
```

而评测期望来源是 `2024年报 p151`。大量金融术语正好是两字词（股息、估值、毛利、负债、减值、回购），这是 keyword Recall 掉点的主要原因之一。

**建议**

1. 短查询不再尝试 trigram MATCH，直接走 LIKE，但排序改为“命中次数”评分：

   ```sql
   ORDER BY ((length(p.content) - length(replace(p.content, :q, ''))) / length(:q)) DESC,
            p.char_count ASC
   ```

   或先按 report 年份降序、同文档取最高命中页，再排。
2. 用 `snippet()` 不可行时，自己定位首次命中位置，返回以命中点为中心的 80–160 字片段，而不是全文开头。
3. 长期方案：为 2 字词建一张辅助 bigram 表，或入库时对中文做 jieba 分词后写 unicode61 FTS 表；引入分词前先跑评测确认不劣化。

**验收标准**

- `search "股息"` 命中 `2024年报` 相关页且排名进入前 5；
- `search "估值"` 不再返回纯长度排序的 2018 年报页。

### 4.2 P1：查询归一化与查询改写（B-7）

**证据**

索引文本是简体，但 `fts_search()`/`vector_search()` 没有对查询调用 `to_simplified()`。实测：

```text
search "現金流量"      -> []
search "現金流"        -> []
search "現金流量表"    -> []
```

自然语言长句（“海底捞的现金流质量怎么样”）在 FTS 中按整句 phrase 匹配，几乎必然为空；目前语义题 FTS Recall=0 与此直接相关。

**建议**

1. 所有查询入口统一 `query_pipeline()`：繁转简、全半角/空白/破折号归一化、英文小写、数字格式统一（`11,797` 与 `11797`）。
2. FTS 查询从“整句 phrase”改为“多词 OR/AND + 短语加权”：
   - 先抽关键术语（翻台率、现金流、资本开支、公司名）；
   - 对公司名用 `company` 过滤，不放进 MATCH；
   - 多关键词在 eval 已有 RRF，把该能力下沉到 `search` 供 MCP 复用。
3. 对中英混合题做轻量查询翻译/扩展：`同店销售 → same-store sales`、`资本开支 → capex/capital expenditure`；先用离线词典或规则，重模型方案留到 reranker/多语言模型实验。

### 4.3 P1：增加过滤、字段加权与结果多样性（B-8/B-11）

- `fts_search` 目前只支持 `company` 过滤。建议增加 `year`、`report_type`、`period_type`、`language`、`exclude_types`（例如查询经营数据时排除招股书/目录）。
- FTS 建表已有 `company`、`report_id` 列，但未用于过滤；可直接用 FTS 外部列过滤减少回表。
- 对同一文档返回多页的情况做 diversity（文档级 max 2 页或 MMR），对 SHA 重复文档去重。
- 排序考虑“来源权重”：年报 > 中报 > 招股书 > 研报；公司名/年份/报表术语命中加权。

### 4.4 P1：向量检索与混合检索升级（B-8、B-14）

**当前实现问题**

- `hybrid_search` 先拿 FTS top_k，再拿“未在 FTS 中出现的向量页”，按 `FTS[0], VEC[0], FTS[1], VEC[1], ...` 交错截断。它没有归一化分数，也不支持 RRF 权重；向量只作补位。
- `vector_search` 先取 25 个 chunk，按页面聚合并以最小距离排序，一个页面可以靠多个相关 chunk 挤占候选，其他相关页面可能拿不到机会。
- 向量查询同样没有查询归一化；公司过滤在召回后。

**建议**

1. 实现标准 RRF：
   - 分别取 FTS 和向量候选 `candidate_k`（建议 3–5 倍 top_k）；
   - 分数归一化后 `score = α*fts_norm + β*vec_norm`，默认 α/β 通过 dev 集网格搜索；
   - 支持 `rrf_k`、权重、截断数配置化，输出每个 hit 的 `fts_rank/vec_rank/fusion_score` 便于评测归因。
2. 向量候选从 `top_k*5` 提到可配置的 `top_k*20`（封顶数百），并增加页面级多样性；公司过滤下推。
3. 先做 reranker 实验（BGE-reranker 或同类），在召回后对候选 20–50 条重排；不通过前不要替换默认。
4. 研究 BGE-M3 的稀疏/多向量能力，但只在基线评测达标后启用。

### 4.5 P1：MCP 与评测口径对齐，并返回原文引用（B-9、B-15）

**问题**

- `search_reports` 只调用 `fts_search`，而评测中 hybrid 的收益没有在 MCP 线上生效。
- `get_report_text` 返回 `pages.content`（简体改写），不是 `content_orig`（原文）；`get_source_excerpt` 取 `content[:200]`，即“页首 200 字”，不一定是查询命中的片段。
- `get_financial_statements` 不返回 `report_id/source_id`，同一公司同一年度存在 US/HK 两份年报时，agent 无法稳定引用。
- `get_indicators` 目前返回的指标存在第 3.4 节的口径错误，且无来源。

**建议**

1. `search_reports` 增加 `engine: fts|vector|hybrid`、`model`、`year`、`report_type`、`language` 参数；默认行为保持 FTS 以免线上行为突变，但 skill 可以显式请求 hybrid。
2. `get_report_text/get_source_excerpt` 默认返回 `content_orig`，同时可选返回简体 `content`；`get_source_excerpt` 增加 `keyword/offset` 参数，围绕命中词截取 ±context_chars，并返回 `is_ocr`。
3. 结构化工具增加 `report_id`、`source_id`、`locator`、`is_canonical`；支持 `canonical_only=true`。
4. 所有返回限制 `limit` 使用 `is not None` 判断，避免 0 值歧义（项目已有一处历史教训）。

---

## 5. 评测系统：最需要补的 5 件事

`eval/OPTIMIZATION_PLAN.md` 已经列了完整的 P0/P1/P2 计划，这里不重复，只强调本次检查新增的证据与优先级调整。

### 5.1 结构化 golden 必须独立化（原 P0-1，优先级上调）

现有 26 道结构化题 `expected_value` 与页码来自 DB 自身。本次发现的百胜中国收入/净利取错问题说明：**自洽评测会给错误解析打 26/26**。必须先从 PDF 独立抽取 golden，并把以下反例加入题库：

- 百胜中国 2025 `Total revenues = 11,797`（当前指标错取 11,039）；
- 百胜中国 2025 归母净利 = 929（当前指标取 901）；
- 单位 `US$ million` vs `RMB'000`；
- 页码必须来自 PDF 而非 DB 回填。

### 5.2 新增解析器回归题

- 英文招股书附注页不得产出 statement 行；
- 垃圾年份 2001/2006/2014/2015 不得出现；
- 续页归属正确（续表进同一报表块）；
- 两字查询“股息/估值”命中期望页；
- 繁体查询“現金流量”命中与简体等价；
- SHA 重复文档不重复占位。

### 5.3 先修系统，再扩题

建议顺序：修复 B-1~B-6 → 跑现有 80 题确认不劣化 → 再按 `OPTIMIZATION_PLAN.md` 扩题到 150+。否则题库扩得越多，越是在为错误基线标注。

### 5.4 增加 CI 回归门禁（原 P0-8）

- `tools/run_eval_regression.py`：跑 FTS + 默认 hybrid，与 `PLAN.md` 第 16.7 节基线比较，任一核心指标下降即退出非 0；
- 增加 `pytest` 单元测试与“临时库构建→查询→重建”冒烟测试；
- 破坏性命令前自动校验 DB 备份存在。

### 5.5 生成层自动评分

保持原 P1-8/P1-9 计划：跑 `stock-note` 真实链路，核对数字/引用/幻觉率，LLM judge 人工抽查 20%。建议先等第 3 节数据修复完成，否则自动评分会把解析错误误判为生成错误。

---

## 6. 建议实施路线

### 阶段 0：数据与索引安全（1–2 天）

| 步骤 | 动作 | 完成标志 |
|---|---|---|
| 0.1 | 备份 DB；在临时副本实现并验证 `replace_pages` 级联删除 | 重建页面成功，FK check=0 |
| 0.2 | 向量表按模型隔离，写入 `vec_table` 元数据 | 同维度双模型可共存 |
| 0.3 | 修短查询排序与查询归一化 | `股息/估值/現金流量` 回归通过 |
| 0.4 | 修报表页白名单 + 年份/单位/币种解析 | 附注行清零，unit/currency 覆盖 |
| 0.5 | 修指标规则与来源回填 | 百胜中国 2025 指标正确 |

### 阶段 1：检索质量（3–5 天）

| 步骤 | 动作 | 完成标志 |
|---|---|---|
| 1.1 | 查询改写、关键词抽取、FTS 过滤 | FTS keyword 基线不降、semantic 部分题目可命中 |
| 1.2 | RRF 融合 + 候选数/权重实验 | hybrid semantic Recall 提升，Neg@5 不恶化 |
| 1.3 | chunk 重叠与元数据、向量 blob、候选下推 | 向量写入/查询延迟改善 |
| 1.4 | MCP 增加 hybrid/filters/原文引用 | `tools/test_mcp_http.py` 与 `eval --engine` 口径一致 |
| 1.5 | 文档级去重/多样性 | 重复 SHA 文档不再占位 |

### 阶段 2：评测与交付（3–5 天）

| 步骤 | 动作 | 完成标志 |
|---|---|---|
| 2.1 | 独立 golden + 新回归题 | 结构化评测能发现已知错误 |
| 2.2 | CI 回归脚本 + pytest | 改动一键回归 |
| 2.3 | 生成层自动评分 | end2end 不再全部 pending_manual |
| 2.4 | 打包修复、日志/锁/备份、文档同步 | wheel 包含 serve；README/AGENTS/process-log 更新 |

### 暂缓/可选

- reranker、jina/BGE-M3 进一步对比：等阶段 1.2 的融合基线稳定后再做；
- Docker 迁移与 Hermes Agent 接入：等本机正确性与评测门禁落地后再启动；
- 更大规模的语义切分/知识图谱：当前 60 份文档不需要，先解决准确率。

---

## 7. 风险与注意事项

1. **禁止直接在 `data/stock_kb.db` 上试破坏性修改**。所有 `rebuild/reparse/replace_pages` 实验先在 `VACUUM INTO` 或 `backup` 出来的副本上做。
2. 修解析器后重跑 `reparse-statements` 会改变 `statements`，必须同时重算 `indicators` 并重新跑 `audit_notes.py`；改分块/向量逻辑后必须重跑三种 `eval --engine`。
3. 单位/币种回填依赖解析质量，第一版允许“只覆盖明确可识别的年报三表”，研报未知单位继续为 NULL，不要为了填满而猜。
4. 查询改写和 reranker 会改变排序，必须用 dev/test 分开评测，防止在 80 题上过拟合。
5. 数据目录 `data/`、模型目录 `models/` 不入库；新增表/字段走 `_migrate()`，不要在迁移脚本里裸改生产库。

---

## 8. 复现本文关键问题的只读检查

```powershell
# 基线统计
python -m stock_kb stats --json

# 两字查询当前异常排序
python -m stock_kb search "股息" --top-k 5 --json
python -m stock_kb search "估值" --top-k 5 --json

# 繁体查询当前为空
python -m stock_kb search "現金流量" --json

# 结构化指标口径反例（应看到 11039，而非总收入的 11797）
python - <<'PY'
import sqlite3
conn = sqlite3.connect("file:data/stock_kb.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
print([dict(r) for r in conn.execute(
    "SELECT * FROM indicators WHERE company='百胜中国' AND year=2025 AND name IN ('revenue','net_profit')"
)])
print([dict(r) for r in conn.execute(
    "SELECT s.line_name_orig, s.value, r.title, s.page_no "
    "FROM statements s JOIN reports r ON r.id=s.report_id "
    "WHERE r.company='百胜中国' AND s.statement_type='income' AND s.year=2025 "
    "AND lower(s.line_name_norm) LIKE '%total%revenue%'"
)])
conn.close()
PY

# 首行 Notes/APPENDIX 的页面对应行数（当前约 1269；若进一步剔除
# 第二行为真正报表标题的页面，非报表页误提取行数至少 898）
python - <<'PY'
import sqlite3
conn = sqlite3.connect("file:data/stock_kb.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
print(conn.execute("""
    SELECT COUNT(*) FROM statements s
    JOIN pages p ON p.report_id=s.report_id AND p.page_no=s.page_no
    WHERE upper(substr(ltrim(p.content_orig),1,12)) LIKE 'APPENDIX%'
       OR lower(substr(ltrim(p.content_orig),1,8)) = 'notes to'
""").fetchone()[0])
conn.close()
PY

# 重复 SHA 文档
python - <<'PY'
import sqlite3
conn = sqlite3.connect("file:data/stock_kb.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
for r in conn.execute(
    "SELECT sha256, COUNT(*) n, group_concat(title,' | ') titles "
    "FROM reports GROUP BY sha256 HAVING n>1"
):
    print(dict(r))
conn.close()
PY
```

> 重建页面外键失败的复现必须在临时副本上进行，不要对生产库执行。

---

## 9. 建议文档后续维护

- 每完成一个阶段，把实际改动、评测前后对比、踩坑记录写入 `docs/process-log.md`；
- 本文与 `eval/OPTIMIZATION_PLAN.md` 互补：本文偏“构建与查询系统”，后者偏“评测体系”；
- 建议在 `AGENTS.md` 第 12 节“当前已知局限/待办”中链接本文，作为下一轮开发的优先级依据。
