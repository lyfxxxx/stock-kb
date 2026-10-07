# AGENTS.md — stock-kb 项目开发指引

本文件写给后续在本仓库工作的 agent（Codex / Claude 等）。开始改动前先读完本文件，并按需查看 `README.md`、`PLAN.md`、`docs/glossary.md`、`docs/report-system.md` 和 `docs/process-log.md`。读者能看见的中文用词以 `docs/glossary.md` 为准。三层数据流和每层评测见 `docs/report-system.md`。其中 `PLAN.md` 是早期设计方案，**以第 15 节「当前实施状态」为准**；其余章节描述的是设计意图，不一定与代码完全一致。

## 1. 项目是什么

把 NAS（SMB 只读共享）上的财报/研报解析成本地知识库：

```
scan（NAS 与已有 raw_dir）→ stats 看缺口 → stock-collect / fetch 只补缺口 → scan
            → 解析 → SQLite → MCP 只读接口 → stock-note 写稿（带 STOCK_KB_RUN_ID）→ audit-report
```

- 试点公司：海底捞（06862.HK）、百胜中国（YUMC/09987.HK），已在 `config.yaml` 配置。
- 当前规模：64 份文档、8,534 页、8,823 条三表行项目、237 条指标（2026-10-04：60 nas / 4 collect；OCR 分层与折行胶水后。评测体系见 `eval/EVAL_SYSTEM.md`，目标到门槛的映射见 `eval/METRICS_CONTRACT.md`，过程记录见 `eval/EVAL_PLAN.md`，数据缺口清单见 `eval/data_gaps.md`）。
- 核心目标：笔记中的关键数字必须能追溯到「文件 + 页码/表名」，不允许凭记忆编数。

## 2. 环境与安装

- Windows 11 + Python 3.12.5（`pyproject.toml` 要求 `>=3.11`）。
- 开发安装：`pip install -e ".[mcp,ml]"`；GPU 嵌入用 `pip install -e ".[gpu]"`（本机 4070 Ti SUPER）。
- **本项目已纳入 Git 版本管理**（2026-08-15 初始化并完成首次提交；远端：`https://github.com/lyfxxxx/stock-kb`，私有仓库）。`data/`、`models/`、日志与 pid 由 `.gitignore` 排除、不入库；`data/stock_kb.db` 仍不属于源码，破坏性操作前先备份。
- 嵌入模型缓存在 `models/`，索引、查询全程离线；`models/`、`data/` 属于数据，不要当源码修改。
- 语言与文档统一用简体中文；读者用词以 `docs/glossary.md` 为准，新概念先补术语库再写正文。代码注释/标识符现状为中英混合，新代码跟随所在模块风格。

## 3. 常用命令（修改前先确认基线）

别人从零跑通的顺序：安装 `pip install -e ".[mcp,ml]"` → `python -m stock_kb models download --model BAAI/bge-small-zh-v1.5` → 填 `config.yaml` → `scan` → `stats --json` 看缺口 → 按 `skill/stock-collect/SKILL.md` 只 `fetch` 缺口 → `scan` → `index` → `indicators` → `mcp` → 设置 `STOCK_KB_RUN_ID` → 按 `skill/stock-note/SKILL.md` 写稿 → `python -m stock_kb audit-report <路径> --company <公司>`。`data/` 与 `models/` 不入库。公司目录都不存在且没有跳过的旧文件时 `scan` 退出码 2；有未变更跳过则仍为 0。`python tools/run_eval_regression.py` 只在维护者本机、库里已有试点数据时跑。

```powershell
python -m stock_kb stats --json                  # 入库统计，不访问 NAS，改前改后都跑
python -m stock_kb search "翻台率" --top-k 5 --json           # FTS5 检索
python -m stock_kb search "现金流质量" --engine hybrid --json  # 混合检索（需先建向量索引）
python -m stock_kb eval                              # FTS5 基线评测
python -m stock_kb eval --engine vector --model BAAI/bge-small-zh-v1.5   # 向量评测
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5   # 混合检索评测
python -m stock_kb index --model BAAI/bge-small-zh-v1.5       # 增量建向量索引
python -m stock_kb index --model BAAI/bge-small-zh-v1.5 --rebuild-chunks  # 按 chunk_size 重切；清空所有模型向量
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json
python -m stock_kb indicators                       # 重算/写入财务指标
python -m stock_kb reparse-statements --company 海底捞        # 从已存页文本重算三表（不重读 NAS）
python tools/audit_notes.py                         # 审计两篇试点笔记数字与 DB 交叉验证（归母净利）
python tools/run_eval_regression.py                 # freeze + diag + 路由/年份 + audit-report（无终稿则跳过，不是通过）
python tools/run_eval_regression.py --write-baseline
python -m stock_kb eval-embed --base BAAI/bge-small-zh-v1.5 --challenger BAAI/bge-m3
python -m stock_kb eval-generation                  # 按 skill 组稿并审计引用页
python -m stock_kb route "海底捞 2024 年营业收入是多少" --company 海底捞
python -m stock_kb compose-note --company 海底捞   # 材料底稿；不是终稿
python -m stock_kb render-note <扫描.md>            # 终稿默认格式：同名单文件 HTML
python -m stock_kb quote --company 海底捞 --json   # 最新价/市值/TTM PE；失败则非零退出
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json
python tools/check_vec.py                           # 快速检查向量索引健康度
python tools/coverage_matrix.py                     # 公司×年份×指标覆盖矩阵（已接入回归测试）
python tools/audit_formal_notes.py [md...]          # 正式稿程序化审计（已接入回归测试；无参=扫全部样张）
python tools/backfill_ocr_quality.py                # 一次性：回填 OCR 噪声/乱码页 is_ocr=2
python tools/reprocess_reports.py <report_id...>    # 定向重扫指定文档（读 NAS，走 OCR 闸门）
```

MCP 联调：

```powershell
python -m stock_kb mcp --transport http --host 127.0.0.1 --port 8931   # 先启动服务
$env:STOCK_KB_MCP_URL="http://127.0.0.1:8931/mcp"
$env:STOCK_KB_TOKEN="<token>"
python tools/test_mcp_http.py                       # 端到端测试（已内置 30s 超时与 trust_env=False）
```

`scan` 会访问 NAS，较重且沙箱内可能需要提权；除非用户明确要求或确需验证扫描逻辑，不要跑全量 `scan`。全部 CLI 子命令见 `stock_kb/cli.py`。

## 4. 目录与模块职责

| 路径 | 职责 |
|---|---|
| `stock_kb/cli.py` | argparse CLI 入口，所有子命令的调度 |
| `stock_kb/config.py` | `load_config()`：读 YAML、解析相对路径 |
| `stock_kb/db.py` | SQLite schema、连接、迁移、FTS/向量扩展加载、表级 upsert/replace |
| `stock_kb/ingest.py` | `scan`：只读遍历 NAS 与 `collect.raw_dir`、SHA-256 manifest、按类型分发解析；出处 JSON 写 `collect.meta_dir` |
| `stock_kb/fetch.py` | 下载原文到 raw_dir，出处 JSON 写到 `collect.meta_dir` |
| `stock_kb/source_meta.py` | `origin` 判定与 `meta_dir` 读写 |
| `stock_kb/fidelity.py` | 页文本保真抽检 |
| `stock_kb/retrieval_log.py` | 只读查询旁路日志 `retrieval_log.jsonl` |
| `stock_kb/audit_report.py` | 终稿出处、run_id 日志和事实清单 |
| `stock_kb/classify.py` | 按文件名/目录分类文档类型、语言、年份 |
| `stock_kb/parsers/pdf_parser.py` | PDF 页文本提取、OCR 兜底、三表按行解析 |
| `stock_kb/parsers/xls_parser.py` | 旧版 `.xls` 矩阵读取 |
| `stock_kb/textutil.py` | 繁体→简体归一化（opencc t2s，带进程级缓存） |
| `stock_kb/search.py` | FTS5 检索、统计 |
| `stock_kb/vector.py` | 分块、多后端 embedding、sqlite-vec 索引、向量/混合检索 |
| `stock_kb/indicators.py` | 从三表行项目计算基础指标并写 `indicators` 表 |
| `stock_kb/reparse.py` | 从 `pages` 表重新提取三表，无需重新读 PDF |
| `stock_kb/eval_runner.py` | 评测问题集执行、评分、报告输出 |
| `stock_kb/route.py` | skill 规则：问句 → 工具（indicators / statements / search / no_answer） |
| `stock_kb/note_builder.py` | 按 skill 顺序组稿可审计笔记（无 LLM） |
| `stock_kb/charts.py` | 扫描稿图表 spec：序列 → ECharts 数据点（人读单位 + 每点出处），纯函数 |
| `stock_kb/report_html.py` | 单文件扫描 HTML：内嵌 vendored ECharts（SVG renderer）+ 出处表 + 趋势句 |
| `stock_kb/humanfmt.py` | 人读口径（千元→亿元、百万美元→亿美元、ratio→%）、趋势句、摘录清洗 |
| `stock_kb/quotes.py` | 独立行情 CLI（yfinance 优先/akshare 兜底），不落库 |
| `assets/vendor/` | vendored 前端库（echarts-5.6.0.min.js，Apache-2.0，内联进单文件 HTML） |
| `stock_kb/generation_eval.py` | 组稿产出：引用页是否含该数字 + 趋势句口径一致性 |
| `stock_kb/serve/mcp_server.py` | FastMCP 服务：8 个只读工具（含 `route_query`）+ HTTP Bearer 鉴权 |
| `tools/` | 一次性/运维脚本（审计、检查、迁移、下载模型、生成人工复核底稿） |
| `eval/` | `questions.yaml` 评测集、`EVAL_SYSTEM.md` 回归测试门槛、`METRICS_CONTRACT.md` 目标到门槛、`reports/` 历史评测报告、人工审核表 |
| `data/` | SQLite 库、出处 JSON（`meta/`）、下载原文（`raw/`）、日志、pid 文件（运行时产物） |
| `models/` | Hugging Face 模型缓存（运行时产物） |
| `skill/stock-collect/` | 收集 skill：发现财报、电话会、研报直链并调用 `fetch` |
| `skill/stock-note/` | 报告 skill：agent 按框架写扫描稿 |
| `docs/glossary.md` | 读者文档与示意图的中文术语库 |
| `docs/report-system.md` | 三层架构、数据转换、每层评测和 exact-001 实例 |
| `docs/process-log.md` | 历次踩坑记录与解法（现象/原因/解决/教训），改相关模块前必读；简历过程记录指定此文件 |

注意：`tools/*.py` 里多数脚本硬编码了 `D:\workspace\stock-kb\data\stock_kb.db`，是历史一次性脚本，**新代码不要模仿**。

## 5. 配置

`config.yaml` 关键项：`nas.root`（只读 SMB 路径）、`nas.companies`、`data_dir`、`db_path`、`models_dir`、`ocr.*`、`embedding.*`、`mcp.*`、`eval.*`、`collect.raw_dir`、`collect.meta_dir`。

路径规则（`stock_kb/config.py` 统一处理）：

- 相对路径一律相对 **配置文件所在目录** 解析；
- 可用环境变量 `STOCK_KB_CONFIG` 指定其他配置文件；
- 代码内必须通过 `load_config()` 取路径，禁止在 `stock_kb/` 包内硬编码 `D:\workspace\...`。

其他环境变量：

- `STOCK_KB_TOKEN`：HTTP MCP 的 Bearer token（也可放 `mcp.token`，目前 config 未配置）。
- `STOCK_KB_MCP_URL` / `STOCK_KB_NOTES_DIR`：`stock-note` skill 使用，本仓库代码不读取。
- `HF_ENDPOINT`、`HF_HUB_ENABLE_HF_TRANSFER`：模型下载加速（见 `tools/download_models.py`）。
- `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`：缓存命中时由 `vector.py` 自动设置，且必须在 import transformers/sentence_transformers **之前**设置。

## 6. 数据流

1. `scan` 遍历 `nas.root/<company>` 和 `collect.raw_dir/<company>`，仅处理 `.pdf/.xls/.html/.htm/.csv/.txt/.md`，跳过 `nas.exclude_dirs`。文件留在原处，不互拷。`scan` 对 NAS 和 `raw_dir` 都只读。出处 JSON 在 `collect.meta_dir`（默认 `data/meta/{origin}/{公司}/{相对路径}.source.json`）：`fetch` 写网络文件，`scan` 给 NAS 和网络文件都更新。先读 `meta_dir`，没有则读原文旁旧 sidecar。`source_url` 与 `retrieved_at` 写入 `reports`，`origin` 为 `nas` 或 `collect`。查询目录是 `reports`。
2. `manifest` 按路径 + SHA-256 判断是否已处理；未变化则跳过，`--rebuild` 强制重解析。
3. PDF：pdfplumber 逐页提文本；文本量低于 `ocr.min_chars` 的页走 tesseract OCR 兜底；随后繁体转简体存 `pages.content`，原文存 `pages.content_orig`。
4. 三表：按报表页标题定位（前 10 行内），按「行标签 + 行尾数字」解析（独立短横「–」视为零值列参与对齐，不产生行项目），不依赖 `extract_tables()`（港股双栏表格会错位）。
5. 页文本同步写入 `pages_fts`（FTS5 trigram 分词，短于 3 字的查询走 `LIKE` 兜底）。
6. 向量：`pages.content` 按行合并成约 800 字/块写入 `chunks`（`embedding.chunk_size`）；`index` 用指定模型嵌入未索引块。`--rebuild` 只删当前模型向量；`--rebuild-chunks` 重切页面并清空**所有**模型索引（chunk_id 会变）。400 字块已在 diag 试过，freeze hybrid semantic 从 0.10 掉到 0.05，未采用。
7. `indicators` 从 `statements` 行项目关键词匹配提取收入/净利/资产等，再派生毛利率、净利率、ROE。`net_profit` 是归母（港股「本公司拥有人应占」，美国 `Net income — Yum China Holdings`），不是年内溢利合计。挑选顺序：当年干净页 → 干净比较列 → 当年 OCR=1 且与比较列一致（无比较列则用 OCR）。`source_kind` 为 `own_year` / `comparative` / `ocr_own` / `derived`。OCR=2 永不入选。
8. MCP 以 `mode=ro` 打开 SQLite，只暴露只读工具（含 `route_query`）；HTTP 传输外包 Starlette 中间件做 Bearer 鉴权。`get_financial_statements(year=)` 默认当年年报正文。
9. `stock-collect` 先 `scan` NAS，用 `stats` 看缺口，再找直链并 `fetch`，然后 `scan` 收进新文件。`stock-note` 在设置 `STOCK_KB_RUN_ID` 后查数写稿，再 `audit-report`。查询日志不进 SQLite。

## 7. 数据库约定

核心表（完整定义在 `stock_kb/db.py` 的 `SCHEMA`）：

| 表 | 内容 |
|---|---|
| `companies` | 公司名、代码、交易所 |
| `reports` | 文档元数据，`path` 唯一，`origin` 为 `nas`/`collect`，`status` 生命周期 pending/parsing/ok |
| `pages` | 每页文本；`content` 为简体索引用，`content_orig` 为原文引用用 |
| `pages_fts` | FTS5 虚拟表，与 `pages` 一对一镜像 |
| `statements` | 三表行项目；数值未换算（海底捞 `千元/CNY`，百胜 `百万美元/USD`） |
| `indicators` | 指标值，`(company, year, period_type, name)` 唯一；`source_kind` 为 own_year / comparative / ocr_own / derived |
| `sources` | 统一来源引用表，**目前未填充**（MCP 现场拼 locator） |
| `manifest` | 扫描清单：路径 + SHA-256 + 状态 |
| `chunks` / `embedding_index` / `chunks_vec_*` | 分块与向量索引；`embedding_index` 主键是 `(model, chunk_id)` |

必须遵守：

- 读写走 `db.connect()`（开启 WAL、外键、自动建 schema）；MCP 侧用 `file:...?mode=ro` 只读连接。
- 删除/替换页面必须同步处理 `pages_fts`（`db.replace_pages()` 已封装，不要手写旁路）。
- **多模型向量索引用复合主键隔离**；`index --rebuild` 只允许删除当前模型的数据，不得清空其他模型（历史上踩过坑，见 process-log 第 11/12 条）。
- 改 schema 必须走 `db._migrate()` 增量迁移，不要改动已有表的既有字段语义，也不要让 `tools/migrate_*.py` 这类一次性脚本直接在生产库上裸跑。
- `data/stock_kb.db` 是唯一事实库；手工排查用只读 SQL，写操作优先封装成 `db.py` 函数或 CLI 命令。

## 8. 开发约定（Do / Don't）

- ✅ 统一从 `load_config()` 取配置；新增文件输出位置也要可配置或相对项目根。
- ✅ 所有文件读写显式 UTF-8；Windows 下 `subprocess.run(..., text=True)` 必须带 `encoding="utf-8", errors="replace"`。
- ✅ 索引用简体文本（`to_simplified`），引用用原文（`content_orig`）；新增解析逻辑不得破坏这对关系。
- ✅ 可空/0 值判断用 `if x is not None`，不要用 `if x`（`--limit 0` 历史坑）。
- ✅ sqlite-vec 检索用 `MATCH ? AND k = ?`，不能同时给 `LIMIT`。
- ✅ 模型重建按 model 隔离；embedder 实例进程级缓存（`vector._EMBEDDER_CACHE`）。
- ✅ CLI 面向脚本输出 JSON 时用 `--json` 并 `ensure_ascii=False`；终端乱码时以 `--json` 结果为准。
- ✅ MCP 保持只读，新工具不得接受任何写操作；新增工具后 stdio 与 HTTP 都要验证。
- ❌ 不要在 `stock_kb/` 内硬编码绝对路径或机器相关用户名。
- ❌ 不要通过 PowerShell 5.1 管道把中文传给 Python 子进程（编码会被破坏）；用参数、文件或 JSON。
- ❌ 不要升级/降级 `mcp` 主版本：项目锁定 `mcp>=1.0,<2`，导入路径是 `mcp.server.fastmcp`（2.0 不兼容）。
- ❌ 不要写 NAS 源目录；扫描/解析只读。
- ❌ 不要把 `data/`、`models/`、`__pycache__/` 当源代码修改或重写。

## 9. 常见任务怎么做

### 新增/修改 CLI 子命令

在 `stock_kb/cli.py`：加 `add_parser` → `main()` 里加分支 → 返回 int。命令结果用 JSON 输出时与现有风格一致（`json.dumps(..., ensure_ascii=False, indent=2)`）。记得同步更新 README 的「常用命令」和本文件第 3 节。

### 新增 MCP 工具

在 `stock_kb/serve/mcp_server.py` 的 `create_server()` 内用 `@mcp.tool()` 定义；用内部 `_conn()` 只读连接，函数内 `finally: conn.close()`。加完后跑 stdio（直接调用工具函数/`mcp run`）与 HTTP（`tools/test_mcp_http.py`）两种验证。科目数字走 `get_indicators` / `get_financial_statements(keyword=)`，不要先 `search_reports`。

### 修改解析器或分块逻辑

1. 用 `python -m stock_kb reparse-statements --company <公司>` 验证三表提取（不重读 NAS）；
2. 页面文本变化时跑 `scan --company <公司> --limit 1` 或单文件脚本验证；
3. 分块逻辑变化时：备份 DB → 改 `embedding.chunk_size` → `index --rebuild-chunks`（会清空所有模型）→ `python tools/run_eval_regression.py`；不劣化才能留下。`--rebuild` 不会重切 chunks。
4. 对比 `eval/reports/` 历史基线与当前差异，不劣化才能收尾。

### 换/新增 embedding 模型

在 `stock_kb/vector.py` 的 `MODEL_DIMS` 登记维度；确认模型已下载到 `models/`；`index --model <ID>`。筛选用 embedding 套件（vector@5/@50 分桶），不要用 FTS keyword 或 FTS semantic：

```powershell
python -m stock_kb eval-embed --base BAAI/bge-small-zh-v1.5 --challenger <新模型>
```

只有判定 `better`（Recall@50 Wilson 区间与基线分开）才考虑换默认模型；`indistinguishable` / `lean_better` 不够。换之前仍须 `python -m stock_kb eval --engine hybrid --model <新模型> --split freeze` 过 hybrid semantic 门槛，并跑 `run_eval_regression.py`。结论记在 `PLAN.md` 第 15 节。细则见 `eval/EVAL_SYSTEM.md` §5.1。

### 新增评测题

在 `eval/questions.yaml` 追加。`type`：exact / keyword / semantic / cross / end2end / indicator / no_answer / route / year_filter。`split` 缺省为 freeze（进回归测试）；诊断题写 `split: diag`。`expected[].file` 为不含扩展名的 `reports.title` 片段。结构化题必须 `golden_source: pdf`，禁止从 DB 抄 `expected_value`。diag 分析/跨语言题可列多条 `sources`（均 `required: true`，命中任一即算）；`authority` 为 `annual` / `interim` / `research` / `prospectus`，评测另报年报/中报召回。回归测试：`python tools/run_eval_regression.py`（freeze 检索/结构化 + diag 指标/无答案 + `audit_notes.py`）。翻题对照 `eval/regression_baseline.json`。体系见 `eval/EVAL_SYSTEM.md`，目标到门槛见 `eval/METRICS_CONTRACT.md`，过程见 `eval/EVAL_PLAN.md`。

### 改扫描报告输出（note_builder / report_html / charts / note_template / SKILL）

1. `python -m pytest tests/ -q` 全绿；
2. `python -m stock_kb compose-note --company 海底捞` 与 `百胜中国` 重出底稿；
3. `python -m stock_kb eval-generation`：faithful_rate=1.0 且趋势句口径一致性 0 mismatch 才算过；
4. 浏览器打开（或 Playwright 截图）核对：图例与序列一致、y 轴单位、数据标签、出处表六列；
5. 按 `eval/HUMAN_RUBRIC.md`（R1–R11）人工过一遍；改了 skill 模板时正式稿要重写样张。

### 更新文档

改动影响命令、schema、流程、已知限制时，同步更新 `README.md`、`AGENTS.md`；踩坑记录追加到 `docs/process-log.md`。读者中文用词必须在 `docs/glossary.md`；新术语先补术语库，再写正文和示意图。

## 10. 完成标准（改完必须全部通过）

- [ ] `python -m stock_kb stats --json` 正常，数字与改动前一致（除非本意就是改数据）；
- [ ] `python -m stock_kb search "翻台率" --top-k 5 --json` 返回非空且命中正确；
- [ ] `python tools/run_eval_regression.py` 跑通（门槛见 `eval/EVAL_SYSTEM.md` §5；含 `audit_notes.py`）；
- [ ] 涉及 MCP 时 `tools/test_mcp_http.py` 通过（stdio 与 HTTP 至少各验证一次）；
- [ ] 输出路径、环境变量、新增命令已写进文档。

## 11. 已知陷阱速查（详见 docs/process-log.md）

- NAS 在沙箱内可能需要提权才能枚举/读取；先 `Test-Path`，再只读操作。
- 出处 JSON 写在 `collect.meta_dir`，不要贴在原文旁。遗留 sidecar 只作 fallback。`origin_for` 对 UNC 用字符串前缀比较，剥 pathlib 尾斜杠，不要 `resolve()`。
- 港股繁体、中英混排：先归一化再索引，引用用原文。
- FTS5 默认分词器对中文无效，必须 trigram；<3 字查询走 LIKE。
- `index --rebuild` 曾误删所有模型索引——回归测试时重点检查「按 model 隔离」。
- 整页嵌入语义效果差，当前是 800 字分块。400 已试：diag 上 027 进 top-5，但 freeze hybrid semantic 0.10→0.05，已回滚。改粒度必须 `--rebuild-chunks` 并跑回归测试。
- CUDA/onnxruntime 依赖脆弱，当前推理走 sentence-transformers + torch；非必要不要切回 onnxruntime-gpu。
- 模型缓存后仍可能联网：离线环境变量必须在相关库 import 之前设置。
- `mcp` 锁定 1.x；`streamable_http_app()` 路径默认 `/mcp`；客户端 header 通过 `httpx.AsyncClient` 传。
- `data/*.pid` 与 `*.log` 是历史后台任务产物，不要据 pid 文件假设进程状态。
- 三表英文行名两套形态：美版常无空格（`Cashdividendspaidoncommonstock`/`Capitalspending`），港版有空格；`db._STATEMENT_ALIASES` 的 needle 要同时覆盖 `line_name_norm`（instr 区分大小写）与 `lower(line_name_orig)` 两条路径。
- 港股年报用独立短横「–」表示零值列：解析器按 `CELL_RE` 对齐，短横列不产生行项目；真零值年份在图上留洞是诚实表现，不要补数。
- 指标缺口的根因要先查三表行名再改规则：两家公司无「毛利」行属报表格式（详见 `eval/data_gaps.md`），不要自造口径硬算；海底捞总资产已用「资产总额减流动负债 + 流动负债小计」组合口径修复（`indicators._haidilao_total_assets`），改报表页识别或小计逻辑时必须重跑 30 期勾稽。
- 中报标题 `Condensed …`、百胜早期 10-K `Consolidated and Combined …`：报表页识别先剥前缀/后缀再整行精确匹配，新报告类型标题先查 `_STATEMENT_TITLE_TYPES` 是否覆盖。
- OCR 有两道闸门：触发看 `(cid:` 密度（不只 char_count），输出要过质量校验（长度+有效占比），失败置 `is_ocr=2`。`statements.is_ocr` 与页一致（0/1/2）。`query_statements` 默认排除 OCR（`include_ocr=True` 才返回）。指标按当年干净页 → 比较列 → 当年 OCR=1 质量门提升，OCR=2 永不入选；不要把过滤整档关掉。OCR=1 页若标签块和数字块上下分离，解析器按行序配对。tesseract 报「找不到 traineddata」时解析器会自动推导 tessdata 目录（见 `pdf_parser._tessdata_env`）。
- 港股双语表折行发生在 pdfplumber 视觉行，不是向量 `chunk_size`。小节标题只允许资产负债表白名单；`June 30, December 31,` 当表头 junk；行尾「的/及/金融/預/資/負」与下半句拼接，拼不回的短残片丢弃。改胶水后用 `reparse-statements`，不必重扫 NAS。
- 检索行为约定：见 `docs/report-system.md`「混合检索」。`hybrid_search` 在归一化后长度小于 6 且 FTS 有命中时不融合；长度达到 6，或短查询 FTS 为空，才按页做 RRF。CLI 默认只做 FTS；MCP `search_reports` 默认 FTS，零命中才升级。FTS 无年份问句有 1.5%/年的新近度软排序（打散跨年份重复页并列，改动幅度前先跑 G1/G2）；检索引用格式与 MCP locator 统一为 `《title》第N页`，审计正则只认此格式。标题含「清单」或「清單」的目录文件不进当前使用文档。
- 市场只看文件名和标题，不看父目录。文件名含年报、年度报告、中报、中期报告 → HK；文件名含 Annual Report 且还没有港股标记 → US。不要用 `reclassify` 改语言。扫描结束会 `refresh_logical_keys`，不重读 PDF。路由年份上界是该公司当前使用文档的最大年；`route()` 未传入上界时只拒绝 1999 及更早。
- `tools/test_mcp_http.py` 已内置 30s 超时与 `trust_env=False`：系统代理会劫持 127.0.0.1、httpx 默认 5s 超时扛不住冷启动加载 sqlite-vec。

## 12. 当前已知局限 / 待办

> 2026-08-16 自动修复后的最新状态见 `docs/fix-record-20260816.md`；2026-09-13 数据/审计轮次见 `eval/data_gaps.md` 与 `docs/process-log.md` 45–47 条；以下只列仍未完成或需要人工的事项。

- 评测现状见 `eval/EVAL_PLAN.md`。`indicators.net_profit` 已改为归母；no_answer 带引擎健康哨兵（engine_error 不计入 empty_rate）。问句带年份时检索硬过滤 `reports.year`；三表 `year=` 默认当年正文且默认排除 OCR 行、未指定 `period_type` 时只取年报。路由 24/24；组稿 faithful_rate=1.0（含趋势句口径一致性自检）。freeze hybrid semantic Recall@5 为 0.30（含近失软分 `recall_soft_at_k` 字段）。真语义/跨语言仍是 diag 盲区（已扩英文+中报题；2026-10-04 加 freeze exact-021–023 后题集 159 道；2026-10-07 关键词改为 22 道带年份的单点事实，题集 161 道，其中 48 diag）。行情走 `python -m stock_kb quote`，不入库；TTM 已能用中报拼 `interim_plus_stub`。
- 扫描报告数据面：中报三表、百胜 2016–2018、海底捞总资产、折行残片均已修复；OCR 指标分层已落地（2017 五个核心仍标 comparative）。剩余缺口（两家无毛利率序列、分部收入未结构化、美/港双版本 canonical）见 `eval/data_gaps.md` 待办。
- 正式稿程序化审计已落地（`tools/audit_formal_notes.py`，接入回归测试；样张缺失时自动跳过），但 R1/R2/R11（判断段分布、心算复核）仍靠人工 rubric。
- 两字查询已建 `pages_bigram_fts`，但 bigram 排序暂未启用（避免牺牲 keyword 基线），需独立评测集调权。
- reranker / jina 对比未完成（可选）。
- US/HK 年报等内容不同但语义重复的 canonical 标记未实现。文件名已把港股年报和美股 10-K 分成两把逻辑键，两边都可以是当前使用文档。SHA 完全重复已自动标记并排除。
- Docker 迁移到 DXP-4800、Hermes Agent 接入尚未开始。
- `scan --watch-interval` 自动扫描开关已实现但未在真实新增文件上验证。
