---
name: stock-note
description: 指定公司后用 stock-kb MCP + 独立行情工具生成扫描体 HTML 报告（数字可溯源；判断须标注）。
---

# stock-note：指定公司 → 扫描稿

输入一个已入库公司名（本阶段：海底捞、百胜中国），直接产出一篇扫描体 HTML。章节顺序固定；段落措辞可自由发挥。财务数字、页码、市价不可自由发挥。

风格骨架：仓库 `eval/style-canon/LLM_SCAN_TEMPLATE.md`（modest_ 专栏 28 篇归纳）。stock-kb 纪律叠加与章节骨架见 `skill/stock-note/templates/note_template.md`。写法规则：趋势句、科目金额做小标题、累计现金流五件套、现场心算、会计口径还原、判断直给但留余地；**总判断与估值只出现在总结**。

## 硬性纪律

1. 科目数字只来自 MCP `get_indicators` / `get_financial_statements`。**出处采用财报注释式**：正文与表格不出现页码，关键数字带注释号 [n]，全部 `《文件》第N页` 统一放文末「附：注释（数据出处）」。
2. 判断（看点、风险、口吻）以 **「判断：」** 起头写在节内，有观点才写、一节 0–2 处；不得写入财务表或当作出处。
3. 检索默认 **FTS**。只有问句明显是改写/跨语言、且 FTS 空或文不对题时，再 `search_reports(..., engine="hybrid")` 或 `engine="vector"`。
4. 行情走 CLI `python -m stock_kb quote --company <公司> --json`（yfinance 优先，akshare 兜底）。**失败则整篇失败**，不要用旧价或编 PE。
5. PE = 最新市值 / TTM 归母净利；市值用最新；利润用 TTM（quote 命令已按库内年报/中报拼接并换算到元）。先按财报币种陈述，再给人民币（实时汇率）。港股 akshare 日线是 **港元**。
6. 股东结构、分产品：从带出处的年报页抽取，不写回数据库。净现金/总资产/股息用三表；算不出净现金就写公式+「暂无借款明细」。
7. 无出处的行业规模、集中度预测：不写，或标成判断并引用研报页。
8. 数字与单位：图表、正文趋势句用亿/亿美元等人读口径（与组稿底稿一致）；出处表保留原值并注明单位。同一数字不在正文、图 caption、表格重复罗列出处——出处明细只看出处表。

## 工作流（指定公司后一次做完）

1. `list_reports(company=)` 确认最新年报/中报在库。
2. `python -m stock_kb quote --company <公司> --json`  
   失败 → 停止，向用户报告错误，不写半成品。
3. `get_indicators` 最近 3–5 年：revenue、net_profit、gross_profit、total_assets、total_equity、operating_cashflow。
4. `get_financial_statements`（科目数字按 keyword 取，英文名公司用英文行名关键词）：
   - 三表关键词：已付股息、资本开支、减值（多年，供分红序列与累计五件套）；
   - 资产负债科目（新模版逐科目节用）：货币资金/银行结余、短期借款、长期借款、应收、应付、存货、固定资产、在建工程、合同负债、商誉；
   - 空则 search 附注，取不到写「暂无数据」。
5. FTS `search_reports`：实际控制人、股权激励、股东，翻台率/同店销售额/客单价/门店数等经营词，市场规模/市占率/市场集中度等行业词。
6. 需要语义时再 hybrid/vector，并在稿里注明检索用了哪台引擎。
7. 按模板写 **HTML**。图表**整块复用** `compose-note` 已生成的 `<figure class="chart-fig">…</figure>`（含 `data-chart` JSON 与页尾 ECharts/初始化脚本），不要手绘 SVG、不要改 spec 里的数值；需要新序列时按出处表数据自配 option（仍用 ECharts，SVG renderer）。
8. 自查（发布前逐条过）：
   - 每个关键数字带 [n]，文末注释区逐条可查 `《文件》第N页`；正文与表格无页码残留；
   - 判断句带「判断：」且自然分布；
   - 行情块含价格日期、币种、汇率来源、PE_TTM；
   - 资产负债节逐科目小标题、净现金公式与打折检查齐备；
   - 现金流节含累计五件套（注明「按表内原值累计」）与 FCF/净利润比值；
   - 总结含「当前 PE × 派息率 → 股息率 + 情景」收束；
   - 图例与序列一致、单位统一（亿/亿美元/%）；
   - 正文无写作指令或过程性文字（「须带来源」「由 skill 补写」等不得出现）。

输出：`<STOCK_KB_NOTES_DIR>/<公司>/<YYYY-MM-DD>-<公司>-扫描.html`

可用 `python -m stock_kb compose-note --company <公司>` 当材料底稿（Markdown 扫描稿 + `扫描-组稿.html` 图）。正式稿写 `YYYY-MM-DD-<公司>-扫描.html`；**不能**只交底稿交差。

## 模板章节

公司简介与股权管理层 → 利润表（图+出处表）→ 分业务/分产品 → 资产负债（逐科目小标题，金额进标题）→ 现金流（累计五件套）→ 分红 → 行业与同行 → 未来看点 → 总结（生意质量 / PE×派息率→股息率 / 风险）→ 附：引用明细。☆节按公司特性取舍并明说；总判断与估值只在总结。

CLI：

```powershell
python -m stock_kb quote --company 海底捞 --json
python -m stock_kb compose-note --company 海底捞
python -m stock_kb statements --company 海底捞 --keyword 已付股息 --year 2024 --json
```

## 人工过关（挡发布，不挡回归）

清单见仓库 `eval/HUMAN_RUBRIC.md`（含 R8–R11 风格项）。审核人评两家样张：八节都在；判断已标注且自然分布；财务表无判断；无表外无出处数字；HTML 有图且图例与序列一致；单位统一；估值收束可复核；行情失败则不应有成稿。
