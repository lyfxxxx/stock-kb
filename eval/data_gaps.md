# 数据缺口诊断清单（2026-09-12 初版；2026-09-13 更新）

> 范围：海底捞、百胜中国两试点公司的扫描报告数据面。诊断方式为只读 SQL +
> 解析器单点复现；修复项随 2026-09-12 / 2026-09-13 两轮落地，遗留项标「待办」。

## 已修复（2026-09-12 轮）

## 已修复（本轮）

| 缺口 | 根因 | 修复 | 验证 |
|---|---|---|---|
| 百胜资本开支五年全缺（图空列） | `db._STATEMENT_ALIASES["资本开支"]` 只配了「购买物业/purchase of property」，命不中美版行名 `Capitalspending` | 别名补 `Capitalspending`（norm 路径，instr 大小写敏感）+ `capital spending`（orig lower 路径） | `statements --keyword 资本开支 --year 2024` 命中 -705 百万美元 |
| 百胜 2021 已付股息缺 | 美版行名无空格（`Cashdividendspaidoncommonstock`），`dividends paid`（带空格）两路都不匹配 | 别名补 `dividendspaid` | 2021 命中 -203 百万美元 |
| 海底捞 2023 已付股息缺 | 港股年报用「–」表示零值列（如 `Dividends paid 已付股息 (553,798) –`），解析器按「行尾数字」找单元格，列数不足整行丢弃 | `pdf_parser.extract_statements_from_pages` 改用 `CELL_RE`（数字或独立短横），短横列不出行、数字列照常按年份对齐 | 2023 股息 -553,798 千元入库；statements 5,570 → 5,809 行；indicators 117 条零漂移 |

## 已修复（2026-09-13 轮）

| 缺口 | 根因 | 修复 | 验证 |
|---|---|---|---|
| 海底捞 7 份中报（2019–2025）三表行全为 0 | 报表页标题精确匹配词典不含 `Condensed Consolidated …`（中报标准标题）；`_normalize_title_line` 现剥 `Condensed/简明` 前缀、`(Loss)/（未经审核）` 后缀 | `pdf_parser._STATEMENT_TITLE_TYPES` 匹配逻辑 + 词典补 `Consolidated and Combined …` 变体 | 中报每份 258–298 行；`reparse-statements` 离线重建 |
| 百胜 2016 年报 0 行、2018 年报仅 balance | 10-K 标题为 `Consolidated and Combined Statements of Income (Loss)` 等，不在词典 | 词典补 `consolidated and combined …` 变体 + `(loss)` 后缀剥离 | 2016=247 行、2018=254 行（income/balance/cashflow 齐全） |
| 海底捞无 total_assets（待办 1） | 港式资产负债表小计行不带行名，被 `_is_junk_name` 丢弃 | ① 无标签纯数字行挂最近小节标题并标 `is_subtotal=1`（statements 新增 `line_no`/`is_subtotal` 列，走 `_migrate` 重建）；② `indicators._haidilao_total_assets` 组合规则：总资产 = 资产总额减流动负债 + 流动负债小计（含持作出售） | 2017–2025 annual + 2018–2025 interim 全覆盖；30 期勾稽恒等式（净资+两负债小计）全过；2024=22,781,257 千元 |
| 折行标签产生「的金融资产」类残缺行名 | 跨行标签只取到本行文本 | `_looks_like_continuation`/`_ends_mid_phrase` 折行拼接（含未闭合括号/连词/小写续行启发式） | `test_extract_statements_subtotal_and_wrapped_label` |
| OCR 触发盲区：cid 乱码页字符数高、永不 OCR | 只看 `char_count < 80` | 触发条件加 `(cid:` 密度 >10%；OCR 输出加质量闸门（≥50 有效字符、有效占比 ≥0.5），失败置 `is_ocr=2` | 百胜 2017 年报重扫：122 页 OCR 成功、19 页标记；`tools/backfill_ocr_quality.py` 回填全库 203 页 |
| OCR 噪声/乱码内容污染检索与指标 | 无 is_ocr=2 语义；OCR 行与干净文本行同权重 | 检索（FTS/LIKE/bigram/向量）排除 is_ocr=2 页；三表行新增 `is_ocr` 列标记 OCR 页来源，**默认不进 indicators 与 query_statements**（`include_ocr=True` 才返回） | indicators 230 条与干净口径完全一致；百胜 2017 net_profit=398（2018 比较列干净文本） |
| 表头日期行泄漏成数据行（「For the six months ended June」「于」） | `_is_header_or_junk_line` 缺日期模式与「于」简化字 | 加 `_DATE_LINE_RE`、`于`/`at june` 等前缀、字符加倍页脚（`AAnnnnuuaall RReeppoorrtt`）去重识别 | 残留表头行 119 → 0 |
| tesseract 找不到语言包（TESSDATA_PREFIX 未设置时 OCR 静默失败） | conda 布局 tessdata 不在默认搜索路径 | `_ocr_page` 从 tesseract 可执行文件位置自动推导 tessdata 目录 | 单页 OCR 0.9s 空输出 → 1.9s 1527 字符 |

## 确认为报表格式、按「不编」处理（非 bug）

| 缺口 | 根因 | 处理 |
|---|---|---|
| 两家公司均无 `gross_profit` / `gross_margin` | 海底捞损益表按性质列支（原材料/员工/租金等），无「毛利」行；百胜 US GAAP 损益表同样无 Gross profit 行 | 图表不画毛利率序列（空序列不进图例）；**不要**用「收入−原材料」自造毛利率口径，餐饮人工/租金归属不清 |

## 待办

1. ~~**海底捞总资产**~~ **已修复（2026-09-13）**：见上表「2026-09-13 轮」。组合口径 = 资产总额减流动负债 + 流动负债小计（含持作出售），出处锚在「资产总额减流动负债」行。
2. **海底捞 2022 已付股息为真零值**：2022 年报该格是「–」（当年未派息），属真实空缺，图表留洞是诚实表现；如需表达可在趋势句注明「2022 年未派息」（需另行取证）。
3. **股东检索命中质量**：`股东` 一词常命中组织章程/股东权利条款示例页（2018 年报第 68 页），噪声大；可考虑把 `SHAREHOLDER_TERMS` 的 `股东` 换成 `控股股东`/`持股比例` 并人工核对两公司的 top1。
4. **分产品/分地区收入拆分**：库内研报页有市占率、单店模型等表格，但无标准化的分部收入表；如需结构化，需扩展三表解析到「分部信息」附注页（工作量大，未启动）。注意：中报里「按地理区域划分」正文页已可检索命中（2024中报 p21 等），缺的是结构化。
5. **OCR 行的数字复核**（2026-09-13 新增）：百胜 2017 年报等 cid 乱码页经 OCR 后产生的三表行（当前 83 行，`statements.is_ocr=1`）数字可靠性未逐一复核，已默认隔离在 indicators 与 query_statements 之外；如需正式采用，须人工对照原 PDF 或以次年报比较列交叉验证。
6. **美版/港版双版本 canonical 标记**：百胜 2022–2025 美版+港版并存不算 SHA 重复，`query_statements` 同一年份可能返回两套行（`coverage_matrix` 可见）；组稿按 latest_annual_year 取一套，MCP 直查需注意。

## 关键口径（供报告与行情换算）

- 海底捞 statements/indicators：`unit=千元, currency=CNY` → 人读 **亿元**（÷100,000）。
- 百胜中国：`unit=百万美元, currency=USD` → 人读 **亿美元**（÷100）。
- 派生比率 `unit=ratio` → 百分比（×100）。
- 换算统一在 `stock_kb/humanfmt.py`；出处表「数值」列保留原值 + 单位列。
