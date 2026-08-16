# stock-kb 财报知识库

把 NAS 上的财报/研报解析成本地可检索的知识库，通过 MCP 暴露给
Codex / Hermes Agent，配合 `stock-note` skill 生成股票分析笔记。

## 安装

```powershell
cd D:\workspace\stock-kb
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

## 常用命令

```powershell
# 全量扫描入库（需能访问 NAS；只读）
python -m stock_kb scan --rebuild

# 自动扫描（默认关闭；--watch-interval 秒数开启）
python -m stock_kb scan --watch-interval 21600

# 只处理某公司
python -m stock_kb scan --company 海底捞

# 统计
python -m stock_kb stats --json

# 审计两篇试点笔记的关键数字（与数据库交叉验证）
python tools/audit_notes.py

# HTTP MCP 端到端测试（需先启动服务并设 STOCK_KB_MCP_URL/STOCK_KB_TOKEN）
python tools/test_mcp_http.py

# 关键词/全文检索
python -m stock_kb search "翻台率" --top-k 5

# 混合检索（需先建向量索引）
python -m stock_kb search "现金流质量" --hybrid

# 构建向量索引（首次会自动下载模型）
python -m stock_kb index --model BAAI/bge-small-zh-v1.5

# 指定后端与设备（默认 sentence-transformers + cuda）
python -m stock_kb index --model BAAI/bge-small-zh-v1.5 --rebuild

# 检索评测（默认 FTS；指定 --engine 可测 vector/hybrid）
python -m stock_kb eval
python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5
python -m stock_kb eval --engine vector --model BAAI/bge-small-zh-v1.5

# 评测优化计划与执行记录
# 见 eval/OPTIMIZATION_PLAN.md

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
│   ├── questions.yaml   # 评测问题集
│   └── reports/         # 评测报告
├── data/                # SQLite 与日志
├── models/              # 嵌入模型缓存
└── skill/stock-note/    # 可移植 agent skill（已复制到个人 skills 目录）
```

## 过程复盘

建库与评测中遇到的问题和解决方案见
[docs/process-log.md](docs/process-log.md)。

## skill

`stock-note` 已安装到 `C:\Users\89462\.codex\skills\stock-note`，也可从
`skill/stock-note` 整体复制到任意机器。

## 说明

- NAS 只读访问；沙箱内访问共享需要提权；
- 港股/繁体年报在入库时已归一化为简体，简体关键词可直接检索；
- 三表解析按「报表页标题 + 文本行数字」方式提取，跨页/续表自动拼接；
- 详细设计与选型见 [PLAN.md](PLAN.md)。
