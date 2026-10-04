# stock-kb 财报知识库

把 NAS 上的财报/研报解析成本地可检索的知识库，通过 MCP 暴露给
Codex / Hermes Agent，配合 `stock-note` skill 生成股票分析笔记。

三层怎么转换、每层怎么评测、海底捞 2024 年营业收入怎么走完全程，见 [docs/report-system.md](docs/report-system.md)。零基础说明仍在 [docs/knowledge-base-rag-eval-tutorial.md](docs/knowledge-base-rag-eval-tutorial.md)。

## 安装

在仓库根目录：

```powershell
pip install -e ".[mcp,ml]"
```

GPU 嵌入（推荐，本机 4070 Ti SUPER）：

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[gpu]"
```

模型下载加速（可选）：

```powershell
# 多线程下载器
pip install hf_transfer

# 走 hf-mirror 镜像下载（默认）
python -m stock_kb models download --model BAAI/bge-m3

# 自定义镜像 / 关闭加速
python -m stock_kb models download --model BAAI/bge-m3 --mirror https://hf-mirror.com --no-accelerate
```

下载完成后模型缓存在 `models/`，索引和查询全程离线。

## 配置

`config.yaml` 中的关键项：

- `nas.root`：NAS 共享目录（只读）
- `nas.companies`：试点公司（海底捞 / 百胜中国）
- `data_dir` / `db_path`：本地数据与 SQLite 路径
- `models_dir`：嵌入模型缓存目录
- `collect.raw_dir`：网络下载原文（默认 `data/raw`；`scan` 只读）
- `collect.meta_dir`：出处 JSON（默认 `data/meta/{origin}/{公司}/{相对路径}.source.json`）

## 运行顺序

`data/` 和 `models/` 不入库。公司目录（`nas.root` 与 `collect.raw_dir`）都不存在、也没有任何已扫描文件时，`scan` 退出码为 2。已有文件但字节和解析版本都没变、因而被跳过时，退出码仍为 0。黄金回归 `python tools/run_eval_regression.py` 只在维护者本机、库里已经有试点数据时跑，不是别人安装后的完成条件。

```powershell
pip install -e ".[mcp,ml]"
python -m stock_kb models download --model BAAI/bge-small-zh-v1.5
```

按 `config.yaml` 填 NAS、公司、`collect.companies`（百胜中国的 CIK、海底捞的港股代码）。收集顺序见 `skill/stock-collect/SKILL.md`：先 `scan` NAS，用 `stats` 看缺口，再只 `fetch` NAS 没有的类型。财报在两件最近年报和中报都没有时才用 `fetch --source`；电话会和研报只用能直接打开的文件 URL。

```powershell
python -m stock_kb scan
python -m stock_kb stats --json
python -m stock_kb fetch --source sec --company 百胜中国
python -m stock_kb fetch --source hkex --company 海底捞
python -m stock_kb scan
python -m stock_kb index --model BAAI/bge-small-zh-v1.5
python -m stock_kb indicators
python -m stock_kb mcp --transport http --host 127.0.0.1 --port 8931
```

写稿前设置同一次查询共用的运行号，再按 `skill/stock-note/SKILL.md` 写。稿子里要有一行 `run_id:`。

```powershell
$env:STOCK_KB_RUN_ID = "note-001"
python -m stock_kb audit-report <稿子路径> --company 海底捞
```

## 其他命令

```powershell
# 全量重扫（只读 NAS 与 raw_dir；出处 JSON 写 meta_dir；公司目录都不存在时退出码 2）
python -m stock_kb scan --rebuild

# 自动扫描（默认关闭；--watch-interval 秒数开启）
python -m stock_kb scan --watch-interval 21600

# 只处理某公司
python -m stock_kb scan --company 海底捞

# 统计
python -m stock_kb stats --json

# 审计两篇试点笔记的关键数字（与数据库交叉验证）
python tools/audit_notes.py

# 审计正式稿（skill+LLM 产出）：[n] 注释对应、页内数字可追溯、页码残留等
python tools/audit_formal_notes.py            # 无参数时扫描 eval/generated_notes 下全部样张

# 公司×年份×指标覆盖矩阵（静默丢数据当天可见）
python tools/coverage_matrix.py

# 定向重扫指定文档（读 NAS；OCR 乱码页自动走质量闸门）
python tools/reprocess_reports.py 35 36

# HTTP MCP 端到端测试（需先启动服务并设 STOCK_KB_MCP_URL/STOCK_KB_TOKEN）
python tools/test_mcp_http.py

# 关键词/全文检索
python -m stock_kb search "翻台率" --top-k 5

# 混合 / 纯向量检索（需先建向量索引；--hybrid 仍可用）
python -m stock_kb search "现金流质量" --engine hybrid
python -m stock_kb search "现金流质量" --engine vector

# 构建向量索引（首次会自动下载模型）
python -m stock_kb index --model BAAI/bge-small-zh-v1.5

# 只重建当前模型的向量，不重切 chunks
python -m stock_kb index --model BAAI/bge-small-zh-v1.5 --rebuild

# 按 config embedding.chunk_size 重切全部页面（会清空所有模型的向量）
python -m stock_kb index --model BAAI/bge-small-zh-v1.5 --rebuild-chunks

# 黄金回归只在维护者本机、库内已有试点数据时跑（组稿不再当门；有 agent 终稿才 audit-report）
python tools/run_eval_regression.py
python tools/run_eval_regression.py --write-baseline

# embedding 模型筛选（vector@5/@50；不进 freeze 门禁）
python -m stock_kb eval-embed --base BAAI/bge-small-zh-v1.5 --challenger BAAI/bge-m3
python -m stock_kb eval --split freeze
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5 --split freeze
python -m stock_kb eval-generation
python -m stock_kb route "海底捞 2024 年营业收入是多少" --company 海底捞
python -m stock_kb compose-note --company 海底捞   # 材料底稿，不是 agent 终稿
python -m stock_kb fidelity                         # 页文本抽检；空清单退出码 0 但不是通过
python -m stock_kb audit-report <稿子路径> --company 海底捞
python -m stock_kb quote --company 海底捞 --json   # 最新价/市值/TTM PE（失败非零退出）

# 评测体系与过程记录
# eval/EVAL_SYSTEM.md      （现行分层、GT、门禁）
# eval/METRICS_CONTRACT.md （三个产品目标到门的映射；换模/改 skill/加数据各走哪条测量路径）
# eval/style-canon/        （雪球样稿《安井食品扫描》全文与结构对照）
# eval/data_gaps.md        （报告数据面缺口诊断清单：根因/修复/待办）
# eval/EVAL_PLAN.md        （过程中改掉的问题）

# 三表行项目（科目数字；不要先全文搜；--year 默认当年年报正文）
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --include-comparatives --json

# 计算常用指标（营收/净利/ROE/现金流等）
python -m stock_kb indicators

# 启动 MCP（stdio 或 HTTP）
python -m stock_kb mcp --transport stdio
python -m stock_kb mcp --transport http --host 127.0.0.1 --port 8931
```

## 目录结构

```text
stock-kb/
├── config.yaml
├── stock_kb/            # 核心代码（ingest/parse/index/serve）
├── eval/
│   ├── questions.yaml         # 评测问题集
│   ├── EVAL_SYSTEM.md         # 现行分层、GT、门禁
│   ├── METRICS_CONTRACT.md    # 三个产品目标到门的映射
│   ├── EVAL_PLAN.md           # 评测记录（过程中改掉的问题）
│   ├── style-canon/           # 雪球样稿《安井食品扫描》
│   └── reports/               # 评测报告
├── data/                # SQLite 与日志
├── models/              # 嵌入模型缓存
├── skill/stock-collect/ # 只下载原文
└── skill/stock-note/    # 只写报告
```

## 过程复盘

建库与评测中遇到的问题和解决方案见
[docs/process-log.md](docs/process-log.md)（简历可讲的现象/原因/解决/教训记录）。
三个产品目标到现行门的映射见
[eval/METRICS_CONTRACT.md](eval/METRICS_CONTRACT.md)。
2026-08-16 的自动修复记录见
[docs/fix-record-20260816.md](docs/fix-record-20260816.md)。


## 说明

- NAS 只读访问；沙箱内访问共享需要提权；
- 港股/繁体年报在入库时已归一化为简体，简体关键词可直接检索；
- 三表解析按「报表页标题 + 文本行数字」方式提取，跨页/续表自动拼接；
- 详细设计与选型见 [PLAN.md](PLAN.md)。
