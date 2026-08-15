# stock-note skill

用于生成中文股票分析笔记的可移植 Codex skill。

## 安装

把整个 `stock-note` 目录复制到：

- Windows：`C:\Users\<用户名>\.codex\skills\stock-note`
- macOS/Linux：`~/.codex/skills/stock-note`

## 依赖

目标机器需要能访问 `stock-kb`（MCP 服务或 CLI），详见 `SKILL.md`。

## 环境变量

- `STOCK_KB_MCP_URL`：MCP 服务地址（HTTP 传输时使用）
- `STOCK_KB_NOTES_DIR`：笔记输出目录，默认 `./analysis-notes`

## 目录结构

```text
stock-note/
├── SKILL.md
├── README.md
└── templates/
    └── note_template.md
```
