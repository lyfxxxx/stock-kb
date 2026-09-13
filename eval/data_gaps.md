# 数据缺口诊断清单（2026-09-12）

> 范围：海底捞、百胜中国两试点公司的扫描报告数据面。诊断方式为只读 SQL +
> 解析器单点复现；修复项已随 2026-09-12 轮次落地，遗留项标「待办」。

## 已修复（本轮）

| 缺口 | 根因 | 修复 | 验证 |
|---|---|---|---|
| 百胜资本开支五年全缺（图空列） | `db._STATEMENT_ALIASES["资本开支"]` 只配了「购买物业/purchase of property」，命不中美版行名 `Capitalspending` | 别名补 `Capitalspending`（norm 路径，instr 大小写敏感）+ `capital spending`（orig lower 路径） | `statements --keyword 资本开支 --year 2024` 命中 -705 百万美元 |
| 百胜 2021 已付股息缺 | 美版行名无空格（`Cashdividendspaidoncommonstock`），`dividends paid`（带空格）两路都不匹配 | 别名补 `dividendspaid` | 2021 命中 -203 百万美元 |
| 海底捞 2023 已付股息缺 | 港股年报用「–」表示零值列（如 `Dividends paid 已付股息 (553,798) –`），解析器按「行尾数字」找单元格，列数不足整行丢弃 | `pdf_parser.extract_statements_from_pages` 改用 `CELL_RE`（数字或独立短横），短横列不出行、数字列照常按年份对齐 | 2023 股息 -553,798 千元入库；statements 5,570 → 5,809 行；indicators 117 条零漂移 |

## 确认为报表格式、按「不编」处理（非 bug）

| 缺口 | 根因 | 处理 |
|---|---|---|
| 两家公司均无 `gross_profit` / `gross_margin` | 海底捞损益表按性质列支（原材料/员工/租金等），无「毛利」行；百胜 US GAAP 损益表同样无 Gross profit 行 | 图表不画毛利率序列（空序列不进图例）；**不要**用「收入−原材料」自造毛利率口径，餐饮人工/租金归属不清 |
| 海底捞无 `total_assets` | 港股英式资产负债表只有「Total Assets less Current Liabilities 資產總額減流動負債」与「Net Assets 資產淨額」，无「资产总额」行；`indicators.METRIC_RULES` 的 negative `current` 也排除了前者 | 图表只画净资产；如需总资产须做「资产总额减流动负债 + 流动资产合计」行组合，见下待办 |

## 待办

1. **海底捞总资产**：确认 2022–2025 年报资产负债表页是否解析出「Total current assets 流動資產總額」小计行（本轮查询未见到，疑似该行在页面上被跳过）；若能稳定提取，可在 `indicators.compute_indicators` 加一条白名单组合规则（总资产 = 资产总额减流动负债 + 流动资产合计），两行同页可共用 locator。
2. **海底捞 2022 已付股息为真零值**：2022 年报该格是「–」（当年未派息），属真实空缺，图表留洞是诚实表现；如需表达可在趋势句注明「2022 年未派息」（需另行取证）。
3. **股东检索命中质量**：`股东` 一词常命中组织章程/股东权利条款示例页（2018 年报第 68 页），噪声大；可考虑把 `SHAREHOLDER_TERMS` 的 `股东` 换成 `控股股东`/`持股比例` 并人工核对两公司的 top1。
4. **分产品/分地区收入拆分**：库内研报页有市占率、单店模型等表格，但无标准化的分部收入表；如需结构化，需扩展三表解析到「分部信息」附注页（工作量大，未启动）。

## 关键口径（供报告与行情换算）

- 海底捞 statements/indicators：`unit=千元, currency=CNY` → 人读 **亿元**（÷100,000）。
- 百胜中国：`unit=百万美元, currency=USD` → 人读 **亿美元**（÷100）。
- 派生比率 `unit=ratio` → 百分比（×100）。
- 换算统一在 `stock_kb/humanfmt.py`；出处表「数值」列保留原值 + 单位列。
