---
name: stock-note
description: 使用 stock-kb 财报知识库生成可发布的中文股票分析笔记（雪球随笔风格，关键数字可溯源）。
---

# stock-note：财报分析笔记生成

## 用途

从本地 `stock-kb` 知识库读取公司财报/研报数据，按固定模板生成 1,500–3,000 字的
中文分析笔记，关键数字必须带来源（文件名 + 页码/表名）。

## 前置条件

- `stock-kb` 已入库目标公司（运行 `python -m stock_kb stats --json` 可确认）；
- 访问方式二选一：
  - MCP：通过环境变量 `STOCK_KB_MCP_URL` 指向服务地址；未设置时尝试本机 stdio；
  - CLI：`python -m stock_kb statements` / `search` / `indicators`。
- 输出目录：环境变量 `STOCK_KB_NOTES_DIR`，默认当前目录下的 `analysis-notes`。

本 skill 目录自包含，可整体复制到其他机器的 `~/.grok/skills/stock-note`
（或 `~/.codex/skills/stock-note`）使用，不依赖任何硬编码绝对路径。

## 工作流

1. **确认公司与报告**：调用 `list_reports`，确认最新年报/中报和研报是否已入库。不确定工具时先 `route_query(question, company)`。
2. **科目数字（禁止先 `search_reports`）**
   - 收入 / 归母净利 / 毛利 / 总资产 / 净资产 / 经营现金流 → `get_indicators`
     （`metrics`：`revenue` `net_profit` `gross_profit` `total_assets` `total_equity` `operating_cashflow`），最近 3–5 年。
   - 已付股息、资本开支、以及指标里没有的行项目 → `get_financial_statements`
     （`keyword` 如「已付股息」「资本开支」，并加 `year`。默认只要当年年报正文，不要次年比较列。资本开支会匹配「购买物业」行）。
   - 减值等多在附注、三表常无此行：先 `keyword=减值` 试三表，空则再 `search_reports`「减值评估」，并写明来自附注。
   - 其它科目三表/指标都没有，再 `search_reports`，并写明这是叙述补充，不是科目权威。
3. **经营叙述**：只用 `search_reports` 查翻台率、同店销售、客单价、师徒制、门店扩张叙事、品牌/咖啡等；英文年报再用英文关键词搜一次。
4. **取原文片段**：对每个关键数字，用 `get_source_excerpt` 拿到原文和定位，
   记录 `文件 + 页码`。指标/三表结果已有 `page_no` 和 `locator` 时优先用。
5. **写笔记**：按模板 `templates/note_template.md` 组织，遵守以下硬性规则：
   - 财务数字只来自三表/指标查询结果，不得凭记忆或推算；
   - 研报预测/观点只写在「研报观点」节，并标注机构、日期、文件名；
   - 同行对比默认开启，取对方 2–3 个关键维度；
   - 估值推演必须写明假设与不确定性。
6. **自查引用**：检查每个数字是否带来源；缺来源的段落删掉或补查。
7. **输出**：保存为 `<notes_dir>/<公司>/<YYYY-MM-DD>-<公司>-笔记.md`；
   如需雪球纯文本版，去掉 Markdown 表格后另存 `.txt`。

CLI 等价：

```powershell
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json
python -m stock_kb indicators
python -m stock_kb search "翻台率" --company 海底捞 --top-k 5 --json
```

## 模板

见 `templates/note_template.md`。生成时保留全部章节；数据不足的章节写「暂无数据」，
不要编造。

## 常见问题

- 查不到简体词时，先试繁体/英文（港股报告常为繁体）；
- 搜索英文年报时用英文关键词（revenue, net income, same-store sales）；
- 一个数字出现在多份报告中时，优先引用年报原文而非研报。
