---
name: stock-note
description: 指定公司后用 stock-kb 只读查询写扫描体报告。数字可溯源；判断须标注。与 stock-collect 分开。
---

# stock-note：指定公司 → 扫描稿

输入一个已入库公司名（本阶段：海底捞、百胜中国），由 agent 写一篇扫描体。章节顺序固定；段落措辞可自由发挥。财务数字、页码、市价不可自由发挥。

风格骨架：仓库 `eval/style-canon/LLM_SCAN_TEMPLATE.md`。节骨架见 `skill/stock-note/templates/note_template.md`。事实清单见 `eval/fact_checklist.yaml`。**总判断与估值只出现在总结**。开篇不下结论。

开写前设置 `STOCK_KB_RUN_ID`（CLI 可用 `--run-id` 覆盖）。稿子里写一行：

```text
run_id: <与环境变量相同的值>
```

`search`、`statements`、`indicators` 以及 MCP 的 `search_reports`、`get_financial_statements`、`get_indicators` 会把本次命中追加到 `data/retrieval_log.jsonl`。日志只记标题和页码。没有 `run_id:` 这一行，或文末注释对不上这次日志，`audit-report` 失败。

## 运行时规则

不要另写检索阈值，沿用 `stock_kb/vector.py` 的 `hybrid_search`：问句归一化之后，长度小于 6 的短术语只用 FTS，FTS 已有命中就返回；问句达到这个长度，或 FTS 没有命中，才做 hybrid 融合。

1. 科目数字走 `get_indicators` / `get_financial_statements`（CLI：`indicators` 重算，`statements` 查询）。不要先拿科目去 `search_reports`。
2. 短术语走 FTS：`search_reports(..., engine="fts")` 或 `python -m stock_kb search`。
3. 问句达到上面的融合长度，或 FTS 无命中，走 `engine="hybrid"`。

`eval/fact_checklist.yaml` 里某一项在活报告上查得到，对应节就要写出数字，并在文末给出 `《文件》第N页`。库里没有，该节写「暂无数据」，不要编。

## 硬性纪律

1. **出处采用财报注释式**：正文与表格不出现页码，关键数字带注释号 [n]，全部 `《文件》第N页` 放在文末「附：注释（数据出处）」。
2. 判断（看点、风险、口吻）以 **「判断：」** 起头，有观点才写。开篇（第一个二级标题之前）不写「判断：」「低估」「高估」。
3. 行情走 `python -m stock_kb quote --company <公司> --json`。**失败则整篇失败**，不要用旧价或编 PE。
4. PE = 最新市值 / TTM 归母净利。先按财报币种陈述，再给人民币。港股日线是港元。
5. 股东结构、分产品从带出处的年报页抽取，不写回数据库。算不出净现金就写公式，缺数据写「暂无数据」。
6. 无出处的行业规模、集中度预测：不写，或标成判断并引用研报页。
7. 同比、累计必须在同一行写出算式（`=`、`÷` 或 `/`）。
8. 利润表、资产负债、现金流若出现两个及以上四位年份，该节要有图。图上的点只能来自已经在文末引用过的数字。可以调用 `stock_kb/charts.py` 画，不要手填没有出处的点。

## 工作流

1. 设置 `STOCK_KB_RUN_ID`。
2. `list_reports(company=)` 确认最新年报、中报在库。
3. `python -m stock_kb quote --company <公司> --json`。失败则停止。
4. 按 `eval/fact_checklist.yaml` 取科目：`get_indicators` 与 `get_financial_statements`。
5. 经营叙述按上面三条运行时规则检索，不使用固定检索词清单。
6. 按模板写扫描稿。必备节：利润表、资产负债、现金流、分红、总结。有年度序列的这三节（利润表、资产负债、现金流）要有图。
7. `python -m stock_kb render-note <稿子.md>` 生成默认同名 HTML。
8. `python -m stock_kb audit-report` 对 Markdown 和 HTML 各跑一次。失败就改 Markdown 再渲染，不要把 `compose-note` 的成篇拿来交差。

输出以 HTML 为默认终稿：`<STOCK_KB_NOTES_DIR>/<公司>/<YYYY-MM-DD>-<公司>-扫描.html`。同名 `.md` 留下供改稿。写完 Markdown 后运行：

```powershell
python -m stock_kb render-note <稿子.md>
```

`audit-report` 对这两份都能读。交付和打开时用 HTML。

`python -m stock_kb compose-note --company <公司>` 仍可生成材料底稿。正式稿由 agent 按本技能书写，不把 compose-note 的整篇当作终稿。

## 模板章节

公司简介与股权管理层 → 利润表 → 分业务/分产品 → 资产负债 → 现金流 → 分红 → 行业与同行 → 未来看点 → 总结 → 附：注释（数据出处）。☆节按公司特性取舍并明说。总判断与估值只在总结。

## 人工过关（挡发布，不挡回归）

清单见 `eval/HUMAN_RUBRIC.md`。回归门是 `audit-report`：没有 agent 终稿时跳过，且不算通过。
