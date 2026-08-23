# AGENTS.md — stock-kb 项目开发指引

本文件写给后续在本仓库工作的 agent（Codex / Claude 等）。开始改动前先读完本文件，并按需查看 `README.md`、`PLAN.md` 和 `docs/process-log.md`。其中 `PLAN.md` 是早期设计方案，**以第 15 节「当前实施状态」为准**；其余章节描述的是设计意图，不一定与代码完全一致。

## 1. 项目是什么

把 NAS（SMB 只读共享）上的财报/研报解析成本地知识库：

```
NAS 财报/研报 → 解析（pdfplumber/xlrd/OCR 兜底）→ SQLite（页文本 + 三表 + 指标 + FTS5 + sqlite-vec 向量）
            → MCP 只读接口（stdio + HTTP）→ Codex / Hermes Agent → stock-note skill → Markdown 笔记
```

- 试点公司：海底捞（06862.HK）、百胜中国（YUMC/09987.HK），已在 `config.yaml` 配置。
- 当前规模：60 份报告、8,128 页、5,570 条三表行项目、117 条指标（2026-08-16 解析器收紧后；评测体系见 `eval/EVAL_SYSTEM.md`，过程记录见 `eval/EVAL_PLAN.md`）。
- 核心目标：笔记中的关键数字必须能追溯到「文件 + 页码/表名」，不允许凭记忆编数。

## 2. 环境与安装

- Windows 11 + Python 3.12.5（`pyproject.toml` 要求 `>=3.11`）。
- 开发安装：`pip install -e ".[mcp,ml]"`；GPU 嵌入用 `pip install -e ".[gpu]"`（本机 4070 Ti SUPER）。
- **本项目已纳入 Git 版本管理**（2026-08-15 初始化并完成首次提交；远端：`https://github.com/lyfxxxx/stock-kb`，私有仓库）。`data/`、`models/`、日志与 pid 由 `.gitignore` 排除、不入库；`data/stock_kb.db` 仍不属于源码，破坏性操作前先备份。
- 嵌入模型缓存在 `models/`，索引、查询全程离线；`models/`、`data/` 属于数据，不要当源码修改。
- 语言与文档统一用中文；代码注释/标识符现状为中英混合，新代码跟随所在模块风格。

## 3. 常用命令（修改前先确认基线）

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
python tools/audit_notes.py                         # 审计两篇试点笔记数字与 DB 交叉验证
python tools/check_vec.py                           # 快速检查向量索引健康度
```

MCP 联调：

```powershell
python -m stock_kb mcp --transport http --host 127.0.0.1 --port 8931   # 先启动服务
$env:STOCK_KB_MCP_URL="http://127.0.0.1:8931/mcp"
$env:STOCK_KB_TOKEN="<token>"
python tools/test_mcp_http.py                       # 端到端测试
```

`scan` 会访问 NAS，较重且沙箱内可能需要提权；除非用户明确要求或确需验证扫描逻辑，不要跑全量 `scan`。全部 CLI 子命令见 `stock_kb/cli.py`。

## 4. 目录与模块职责

| 路径 | 职责 |
|---|---|
| `stock_kb/cli.py` | argparse CLI 入口，所有子命令的调度 |
| `stock_kb/config.py` | `load_config()`：读 YAML、解析相对路径 |
| `stock_kb/db.py` | SQLite schema、连接、迁移、FTS/向量扩展加载、表级 upsert/replace |
| `stock_kb/ingest.py` | `scan`：遍历 NAS、SHA-256 manifest、按类型分发解析 |
| `stock_kb/classify.py` | 按文件名/目录分类报告类型、语言、年份 |
| `stock_kb/parsers/pdf_parser.py` | PDF 页文本提取、OCR 兜底、三表按行解析 |
| `stock_kb/parsers/xls_parser.py` | 旧版 `.xls` 矩阵读取 |
| `stock_kb/textutil.py` | 繁体→简体归一化（opencc t2s，带进程级缓存） |
| `stock_kb/search.py` | FTS5 检索、统计 |
| `stock_kb/vector.py` | 分块、多后端 embedding、sqlite-vec 索引、向量/混合检索 |
| `stock_kb/indicators.py` | 从三表行项目计算基础指标并写 `indicators` 表 |
| `stock_kb/reparse.py` | 从 `pages` 表重新提取三表，无需重新读 PDF |
| `stock_kb/eval_runner.py` | 评测问题集执行、评分、报告输出 |
| `stock_kb/serve/mcp_server.py` | FastMCP 服务：7 个只读工具 + HTTP Bearer 鉴权 |
| `tools/` | 一次性/运维脚本（审计、检查、迁移、下载模型、生成人工复核底稿） |
| `eval/` | `questions.yaml` 评测集、`reports/` 历史报告、人工审核表、人工复核工作底稿 |
| `data/` | SQLite 库、日志、pid 文件（运行时产物） |
| `models/` | Hugging Face 模型缓存（运行时产物） |
| `skill/stock-note/` | 可移植的笔记生成 skill |
| `docs/process-log.md` | 历次踩坑记录与解法，改相关模块前必读 |

注意：`tools/*.py` 里多数脚本硬编码了 `D:\workspace\stock-kb\data\stock_kb.db`，是历史一次性脚本，**新代码不要模仿**。

## 5. 配置

`config.yaml` 关键项：`nas.root`（只读 SMB 路径）、`nas.companies`、`data_dir`、`db_path`、`models_dir`、`ocr.*`、`embedding.*`、`mcp.*`、`eval.*`。

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

1. `scan` 遍历 `nas.root/<company>`，仅处理 `.pdf/.xls/.html/.htm/.csv/.txt/.md`，跳过 `nas.exclude_dirs`。
2. `manifest` 按路径 + SHA-256 判断是否已处理；未变化则跳过，`--rebuild` 强制重解析。
3. PDF：pdfplumber 逐页提文本；文本量低于 `ocr.min_chars` 的页走 tesseract OCR 兜底；随后繁体转简体存 `pages.content`，原文存 `pages.content_orig`。
4. 三表：按报表页标题定位（前 10 行内），按「行标签 + 行尾数字」解析，不依赖 `extract_tables()`（港股双栏表格会错位）。
5. 页文本同步写入 `pages_fts`（FTS5 trigram 分词，短于 3 字的查询走 `LIKE` 兜底）。
6. 向量：`pages.content` 按行合并成约 800 字/块写入 `chunks`（`embedding.chunk_size`）；`index` 用指定模型嵌入未索引块。`--rebuild` 只删当前模型向量；`--rebuild-chunks` 重切页面并清空**所有**模型索引（chunk_id 会变）。400 字块已在 diag 试过，freeze hybrid semantic 从 0.10 掉到 0.05，未采用。
7. `indicators` 从 `statements` 行项目关键词匹配提取收入/净利/资产等，再派生毛利率、净利率、ROE。`net_profit` 是归母（港股「本公司拥有人应占」，美国 `Net income — Yum China Holdings`），不是年内溢利合计。
8. MCP 以 `mode=ro` 打开 SQLite，只暴露 7 个只读工具；HTTP 传输外包 Starlette 中间件做 Bearer 鉴权。
9. `stock-note` skill 调 MCP/CLI 查数 → 按模板生成笔记 → 自查引用。

## 7. 数据库约定

核心表（完整定义在 `stock_kb/db.py` 的 `SCHEMA`）：

| 表 | 内容 |
|---|---|
| `companies` | 公司名、代码、交易所 |
| `reports` | 报告元数据，`path` 唯一，`status` 生命周期 pending/parsing/ok |
| `pages` | 每页文本；`content` 为简体索引用，`content_orig` 为原文引用用 |
| `pages_fts` | FTS5 虚拟表，与 `pages` 一对一镜像 |
| `statements` | 三表行项目；数值未换算单位，`unit` 基本为 NULL |
| `indicators` | 指标值，`(company, year, period_type, name)` 唯一 |
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

在 `stock_kb/vector.py` 的 `MODEL_DIMS` 登记维度；确认模型已下载到 `models/`；`index --model <ID>`；用 `python -m stock_kb eval --engine hybrid --model <ID>` 与 bge-small-zh 基线对比；在 `PLAN.md` 第 15 节记录结论。

### 新增评测题

在 `eval/questions.yaml` 追加。`type`：exact / keyword / semantic / cross / end2end / indicator / no_answer。`split` 缺省为 freeze（进回归）；诊断题写 `split: diag`。`expected[].file` 为不含扩展名的 `reports.title` 片段。结构化题必须 `golden_source: pdf`，禁止从 DB 抄 `expected_value`。diag 分析/跨语言题可列多条 `sources`（均 `required: true`，命中任一即算）；`authority` 为 `annual` / `interim` / `research` / `prospectus`，评测另报年报/中报召回。回归：`python tools/run_eval_regression.py`（freeze 检索/结构化 + diag 指标/无答案）。体系见 `eval/EVAL_SYSTEM.md`，过程见 `eval/EVAL_PLAN.md`。

### 更新文档

改动影响命令、schema、流程、已知限制时，同步更新 `README.md`、`AGENTS.md`；踩坑记录追加到 `docs/process-log.md`。

## 10. 完成标准（改完必须全部通过）

- [ ] `python -m stock_kb stats --json` 正常，数字与改动前一致（除非本意就是改数据）；
- [ ] `python -m stock_kb search "翻台率" --top-k 5 --json` 返回非空且命中正确；
- [ ] `python tools/run_eval_regression.py` 跑通（门槛见 `eval/EVAL_SYSTEM.md` §5）；
- [ ] 涉及三表/笔记时 `python tools/audit_notes.py` 通过；
- [ ] 涉及 MCP 时 `tools/test_mcp_http.py` 通过（stdio 与 HTTP 至少各验证一次）；
- [ ] 输出路径、环境变量、新增命令已写进文档。

## 11. 已知陷阱速查（详见 docs/process-log.md）

- NAS 在沙箱内可能需要提权才能枚举/读取；先 `Test-Path`，再只读操作。
- 港股繁体、中英混排：先归一化再索引，引用用原文。
- FTS5 默认分词器对中文无效，必须 trigram；<3 字查询走 LIKE。
- `index --rebuild` 曾误删所有模型索引——回归时重点检查「按 model 隔离」。
- 整页嵌入语义效果差，当前是 800 字分块。400 已试：diag 上 027 进 top-5，但 freeze hybrid semantic 0.10→0.05，已回滚。改粒度必须 `--rebuild-chunks` 并跑回归。
- CUDA/onnxruntime 依赖脆弱，当前推理走 sentence-transformers + torch；非必要不要切回 onnxruntime-gpu。
- 模型缓存后仍可能联网：离线环境变量必须在相关库 import 之前设置。
- `mcp` 锁定 1.x；`streamable_http_app()` 路径默认 `/mcp`；客户端 header 通过 `httpx.AsyncClient` 传。
- `data/*.pid` 与 `*.log` 是历史后台任务产物，不要据 pid 文件假设进程状态。

## 12. 当前已知局限 / 待办

> 2026-08-16 自动修复后的最新状态见 `docs/fix-record-20260816.md`；以下只列仍未完成或需要人工的事项。

- 评测现状见 `eval/EVAL_PLAN.md`。`indicators.net_profit` 已改为归母；FTS 无答案 empty_rate=1.0。hybrid 对短于 6 字的查询仍短路回 FTS；FTS 为空时向量不再无条件填满（年份超出入库区间或实体未落地则空）。真语义 / 跨语言 diag FTS Recall 为 0。400 字分块已试过并回滚。
- 两字查询已建 `pages_bigram_fts`，但 bigram 排序暂未启用（避免牺牲 keyword 基线），需独立评测集调权。
- reranker / jina 对比未完成（可选）。
- US/HK 年报等“内容不同但语义重复”的 canonical 标记未实现；SHA 完全重复已自动标记并排除。
- Docker 迁移到 DXP-4800、Hermes Agent 接入尚未开始。
- `scan --watch-interval` 自动扫描开关已实现但未在真实新增文件上验证。
