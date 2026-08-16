# 评测方案人工复核工作底稿

> 本文件由 `tools/make_human_review_worksheet.py` 生成，可重复运行。
> 复核时只填本底稿，不要直接改 DB；确认后再回写 `eval/questions.yaml`。

## 一、结构化 golden 复核（26 题）

目标：从 PDF 原文独立读取数值、单位、币种、页码，与 DB 候选对比。
当前 DB 候选只是「自洽结果」，不能证明解析正确。

判定请填写：`一致` / `不一致（写实际值）`。

### exact-001 海底捞 2024 年营业收入是多少？

- 查询条件：海底捞 / income / 2024 / period_type=annual
- 期望来源：2024年报 第142页 损益表
- DB 候选命中：4 条；行级 hit=True
  - [√] Revenue 收入 = 42754687.0 | p142 | 2024年报
  - [×] Other income 其他收入 = 635651.0 | p142 | 2024年报
  - [×] Revenue 收入 = 42754687.0 | p152 | 2025年报
  - [×] Other income 其他收入 = 635651.0 | p152 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2024年报.pdf`（第 142 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2024 截至2024年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-002 海底捞 2024 年净利润（年内溢利）是多少？

- 查询条件：海底捞 / income / 2024 / period_type=annual
- 期望来源：2024年报 第142页 损益表
- DB 候选命中：2 条；行级 hit=True
  - [√] Profit for the year 年内溢利 = 4700278.0 | p142 | 2024年报
  - [×] Profit for the year 年内溢利 = 4700278.0 | p152 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2024年报.pdf`（第 142 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2024 截至2024年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-003 海底捞 2023 年营业收入是多少？

- 查询条件：海底捞 / income / 2023 / period_type=annual
- 期望来源：2023年报 第278页 损益表
- DB 候选命中：4 条；行级 hit=True
  - [√] Revenue 收入 = 41453348.0 | p278 | 2023年报
  - [×] Other income 其他收入 = 940781.0 | p278 | 2023年报
  - [×] Revenue 收入 = 41453348.0 | p142 | 2024年报
  - [×] Other income 其他收入 = 940781.0 | p142 | 2024年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2023年报.pdf`（第 278 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2023 截至2023年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-004 海底捞 2023 年净利润（年内溢利）是多少？

- 查询条件：海底捞 / income / 2023 / period_type=annual
- 期望来源：2023年报 第278页 损益表
- DB 候选命中：3 条；行级 hit=True
  - [√] Profit for the year from continuing operations 来自持续经营业务的年内溢利 = 4495399.0 | p278 | 2023年报
  - [√] Profit for the year 年内溢利 = 4495399.0 | p278 | 2023年报
  - [×] Profit for the year 年内溢利 = 4495399.0 | p142 | 2024年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2023年报.pdf`（第 278 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2023 截至2023年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-005 海底捞 2021 年年内亏损是多少？

- 查询条件：海底捞 / income / 2021 / period_type=annual
- 期望来源：2021年报 第225页 损益表
- DB 候选命中：10 条；行级 hit=True
  - [×] Share of profits of associates 应占联营公司溢利 = 91731.0 | p225 | 2021年报
  - [×] Share of losses of a joint venture 应占合营企业亏损 = -10621.0 | p225 | 2021年报
  - [×] Other gains and losses 其他收益及亏损 = -3707365.0 | p225 | 2021年报
  - [×] (Loss) profit before tax 除税前（亏损）溢利 = -3976019.0 | p225 | 2021年报
  - [√] (Loss) profit for the year 年内（亏损）溢利 = -4161206.0 | p225 | 2021年报
  - [×] Other gains and losses 其他收益及亏损 = -3234753.0 | p243 | 2022年报
  - [×] Profit (loss) before tax 除税前溢利（亏损） = -3070144.0 | p243 | 2022年报
  - [×] operations 年内溢利（亏损） = -3247846.0 | p243 | 2022年报
  - [×] operations 年内亏损 = -913360.0 | p243 | 2022年报
  - [×] Profit (loss) for the year 年内溢利（亏损） = -4161206.0 | p243 | 2022年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2021年报.pdf`（第 225 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2021 截至2021年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-006 海底捞 2020 年营业收入是多少？

- 查询条件：海底捞 / income / 2020 / period_type=annual
- 期望来源：2020年报 第213页 损益表
- DB 候选命中：4 条；行级 hit=True
  - [√] Revenue 收入 = 28614255.0 | p213 | 2020年报
  - [×] Other income 其他收入 = 360867.0 | p213 | 2020年报
  - [×] Revenue 收入 = 28614255.0 | p225 | 2021年报
  - [×] Other income 其他收入 = 360867.0 | p225 | 2021年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2020年报.pdf`（第 213 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2020 截至2020年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-007 海底捞 2024 年经营活动所得现金净额是多少？

- 查询条件：海底捞 / cashflow / 2024 / period_type=annual
- 期望来源：2024年报 第149页 现金流量表
- DB 候选命中：2 条；行级 hit=True
  - [√] Net cash from operating activities 经营活动所得现金净额 = 7634465.0 | p149 | 2024年报
  - [×] Net cash from operating activities 经营活动所得现金净额 = 7634465.0 | p159 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2024年报.pdf`（第 149 页）
  - 该页开头：Consolidated Statement of Cash Flows 综合现金流量表 For the year ended December 31, 2024 截至2024年12月31日止年度 For the year ended December 31, 截至12月31日止…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-008 海底捞 2023 年经营活动所得现金净额是多少？

- 查询条件：海底捞 / cashflow / 2023 / period_type=annual
- 期望来源：2024年报 第149页 现金流量表
- DB 候选命中：2 条；行级 hit=True
  - [×] Net cash from operating activities 经营活动所得现金净额 = 9000350.0 | p285 | 2023年报
  - [√] Net cash from operating activities 经营活动所得现金净额 = 9000350.0 | p149 | 2024年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2024年报.pdf`（第 149 页）
  - 该页开头：Consolidated Statement of Cash Flows 综合现金流量表 For the year ended December 31, 2024 截至2024年12月31日止年度 For the year ended December 31, 截至12月31日止…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-009 海底捞 2024 年资产净值（Net Assets）是多少？

- 查询条件：海底捞 / balance / 2024 / period_type=annual
- 期望来源：2024年报 第145页 综合财务状况表
- DB 候选命中：4 条；行级 hit=True
  - [×] Net Current Assets 流动资产净值 = 5920337.0 | p145 | 2024年报
  - [√] Net Assets 资产净值 = 10417496.0 | p145 | 2024年报
  - [×] Net Current Assets 流动资产净值 = 5920337.0 | p155 | 2025年报
  - [×] Net Assets 资产净值 = 10417496.0 | p155 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2024年报.pdf`（第 145 页）
  - 该页开头：Consolidated Statement of Financial Position 综合财务状况表 As at December 31, 2024 于2024年12月31日 As at December 31, 于12月31日 Notes 2024 2023 附注 2024…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-010 海底捞 2025 年营业收入是多少？

- 查询条件：海底捞 / income / 2025 / period_type=annual
- 期望来源：2025年报 第152页 损益表
- DB 候选命中：2 条；行级 hit=True
  - [√] Revenue 收入 = 43225355.0 | p152 | 2025年报
  - [×] Other income 其他收入 = 580505.0 | p152 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2025年报.pdf`（第 152 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2025 截至2025年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-011 百胜中国 2025 年 Total revenues 是多少？

- 查询条件：百胜中国 / income / 2025 / period_type=annual
- 期望来源：百胜中国_2025_HK_Annual_Report 第153页 Consolidated Statements of Income
- DB 候选命中：3 条；行级 hit=True
  - [×] Totalrevenues = 11797.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Total revenues $ 11,797 $ 11,303 $ = 10978.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [√] Total revenues = 11797.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2025_HK_Annual_Report.pdf`（第 153 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc . Years ended December 31, 2025, 2024 and 2023 (…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-012 百胜中国 2025 年 Net Income（Yum China Holdings, Inc.）是多少？

- 查询条件：百胜中国 / income / 2025 / period_type=annual
- 期望来源：百胜中国_2025_HK_Annual_Report 第153页 Consolidated Statements of Income
- DB 候选命中：11 条；行级 hit=True
  - [×] Netincome—includingnoncontrollinginterests = 1004.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Netincome—noncontrollinginterests = 75.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 929.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 1004.0 | p113 | 百胜中国_2025_Annual_Report
  - [×] Net income — including noncontrolling interests 1,004 = 901.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — noncontrolling interests 75 = 74.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc . 929 = 827.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 1004.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 75.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - [√] Net Income — Yum China Holdings, Inc. $ = 929.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — including noncontrolling interests $ = 1004.0 | p154 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2025_HK_Annual_Report.pdf`（第 153 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc . Years ended December 31, 2025, 2024 and 2023 (…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-013 百胜中国 2024 年 Total revenues 是多少？

- 查询条件：百胜中国 / income / 2024 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第151页 Consolidated Statements of Income
- DB 候选命中：6 条；行级 hit=True
  - [×] Totalrevenues = 11303.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Total revenues $ 11,303 $ 10,978 $ = 9569.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [√] Total revenues = 11303.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [×] Totalrevenues = 11303.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Total revenues $ 11,797 $ 11,303 $ = 9569.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Total revenues = 11303.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 151 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc. Years ended December 31, 2024, 2023 and 2022 (i…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-014 百胜中国 2024 年 Net Income（Yum China Holdings, Inc.）是多少？

- 查询条件：百胜中国 / income / 2024 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第151页 Consolidated Statements of Income
- DB 候选命中：22 条；行级 hit=True
  - [×] Netincome—includingnoncontrollinginterests = 980.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Netincome—noncontrollinginterests = 69.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 911.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 980.0 | p111 | 百胜中国_2024_Annual_Report
  - [×] Net income — including noncontrolling interests 980 = 478.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — noncontrolling interests 69 = 36.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc. 911 = 442.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 980.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 69.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [√] Net Income — Yum China Holdings, Inc. $ = 911.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — including noncontrolling interests $ = 980.0 | p152 | 百胜中国_2024_HK_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests = 980.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Netincome—noncontrollinginterests = 69.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 911.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 980.0 | p113 | 百胜中国_2025_Annual_Report
  - [×] Net income — including noncontrolling interests 1,004 = 478.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — noncontrolling interests 75 = 36.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc . 929 = 442.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 980.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 69.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 151 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc. Years ended December 31, 2024, 2023 and 2022 (i…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-015 百胜中国 2023 年 Total revenues 是多少？

- 查询条件：百胜中国 / income / 2023 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第151页 Consolidated Statements of Income
- DB 候选命中：10 条；行级 hit=True
  - [×] Totalrevenues $ 8,240 $ 7,219 = 20.0 | p89 | 百胜中国_2023_Annual_Report
  - [×] Totalrevenues = 10978.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Total revenues $ 10,978 $ 9,569 $ = 9853.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Total revenues = 10978.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Totalrevenues = 10978.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Total revenues $ 11,303 $ 10,978 $ = 9853.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [√] Total revenues = 10978.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [×] Totalrevenues = 10978.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Total revenues $ 11,797 $ 11,303 $ = 9853.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Total revenues = 10978.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 151 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc. Years ended December 31, 2024, 2023 and 2022 (i…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-016 百胜中国 2023 年 Net Income（Yum China Holdings, Inc.）是多少？

- 查询条件：百胜中国 / income / 2023 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第151页 Consolidated Statements of Income
- DB 候选命中：33 条；行级 hit=True
  - [×] Netincome—includingnoncontrollinginterests = 901.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Netincome—noncontrollinginterests = 74.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 827.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 901.0 | p110 | 百胜中国_2023_Annual_Report
  - [×] Net income — including noncontrolling interests 901 = 1023.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — noncontrolling interests 74 = 33.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc . 827 = 990.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 901.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 74.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc. $ = 827.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — including noncontrolling interests $ = 901.0 | p148 | 百胜中国_2023_HK_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests = 901.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Netincome—noncontrollinginterests = 74.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 827.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 901.0 | p111 | 百胜中国_2024_Annual_Report
  - [×] Net income — including noncontrolling interests 980 = 1023.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — noncontrolling interests 69 = 33.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc. 911 = 990.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 901.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 74.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 151 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc. Years ended December 31, 2024, 2023 and 2022 (i…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-017 百胜中国 2020 年 Total revenues 是多少？

- 查询条件：百胜中国 / income / 2020 / period_type=annual
- 期望来源：百胜中国_2020_Annual_Report 第200页 Consolidated Statements of Income
- DB 候选命中：3 条；行级 hit=True
  - [√] Totalrevenues = 8263.0 | p200 | 百胜中国_2020_Annual_Report
  - [×] Totalrevenues = 8263.0 | p194 | 百胜中国_2021_Annual_Report
  - [×] Totalrevenues = 8263.0 | p217 | 百胜中国_2022_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2020_Annual_Report.pdf`（第 200 页）
  - 该页开头：PARTII Consolidated Statements of Income YumChinaHoldings,Inc. YearsendedDecember31,2020,2019and2018 (inUS$millions,exceptpersharedata) 2020…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-018 百胜中国 2024 年 Total Assets 是多少？

- 查询条件：百胜中国 / balance / 2024 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第154页 Consolidated Balance Sheets
- DB 候选命中：6 条；行级 hit=True
  - [×] TotalAssets = 11121.0 | p113 | 百胜中国_2024_Annual_Report
  - [×] Total Assets 11,121 12,031 = 11826.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [√] Total Assets = 11121.0 | p154 | 百胜中国_2024_HK_Annual_Report
  - [×] TotalAssets = 11121.0 | p115 | 百胜中国_2025_Annual_Report
  - [×] Total Assets 10,783 11,121 = 11826.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [×] Total Assets = 11121.0 | p156 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 154 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Balance Sheets Yum China Holdings, Inc. December 31, 2024 and 2023 (in US$ millions) 2024 202…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-019 百胜中国 2024 年经营活动现金流净额（Net Cash Provided by Operating Activities）是多少？

- 查询条件：百胜中国 / cashflow / 2024 / period_type=annual
- 期望来源：百胜中国_2024_HK_Annual_Report 第153页 Consolidated Statements of Cash Flows
- DB 候选命中：4 条；行级 hit=True
  - [×] NetCashProvidedbyOperatingActivities = 1419.0 | p112 | 百胜中国_2024_Annual_Report
  - [√] Net Cash Provided by Operating Activities = 1419.0 | p153 | 百胜中国_2024_HK_Annual_Report
  - [×] NetCashProvidedbyOperatingActivities = 1419.0 | p114 | 百胜中国_2025_Annual_Report
  - [×] Net Cash Provided by Operating Activities = 1419.0 | p155 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2024_HK_Annual_Report.pdf`（第 153 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Cash Flows Yum China Holdings, Inc. Years ended December 31, 2024, 2023 and 202…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### exact-020 百胜中国 2022 年 Total revenues 是多少？

- 查询条件：百胜中国 / income / 2022 / period_type=annual
- 期望来源：百胜中国_2022_HK_Annual_Report 第150页 Consolidated Statements of Income
- DB 候选命中：8 条；行级 hit=True
  - [×] Totalrevenues = 9569.0 | p217 | 百胜中国_2022_Annual_Report
  - [√] Total revenues = 9569.0 | p150 | 百胜中国_2022_HK_Annual_Report
  - [×] Totalrevenues = 9569.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Total revenues $ 10,978 $ 9,569 $ = 8263.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Total revenues = 9569.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Totalrevenues = 9569.0 | p110 | 百胜中国_2024_Annual_Report
  - [×] Total revenues $ 11,303 $ 10,978 $ = 8263.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Total revenues = 9569.0 | p151 | 百胜中国_2024_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2022_HK_Annual_Report.pdf`（第 150 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc . Years ended December 31, 2022 and 2021 (in US$…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-001 Yum China 2025 operating profit

- 查询条件：百胜中国 / income / 2025 / period_type=annual
- 期望来源：百胜中国_2025_HK_Annual_Report 第153页
- DB 候选命中：3 条；行级 hit=True
  - [×] OperatingProfit = 1290.0 | p112 | 百胜中国_2025_Annual_Report
  - [×] Operating Profit(a) 1,290 1,162 = 1106.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - [√] Operating Profit = 1290.0 | p153 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2025_HK_Annual_Report.pdf`（第 153 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc . Years ended December 31, 2025, 2024 and 2023 (…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-002 Yum China 2022 net income

- 查询条件：百胜中国 / income / 2022 / period_type=annual
- 期望来源：百胜中国_2022_HK_Annual_Report 第150页
- DB 候选命中：30 条；行级 hit=True
  - [×] Netincome—includingnoncontrollinginterests = 478.0 | p217 | 百胜中国_2022_Annual_Report
  - [×] Netincome—noncontrollinginterests = 36.0 | p217 | 百胜中国_2022_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 442.0 | p217 | 百胜中国_2022_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 478.0 | p218 | 百胜中国_2022_Annual_Report
  - [×] Net income — including noncontrolling interests = 478.0 | p150 | 百胜中国_2022_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 36.0 | p150 | 百胜中国_2022_HK_Annual_Report
  - [√] Net Income — Yum China Holdings, Inc. $ = 442.0 | p150 | 百胜中国_2022_HK_Annual_Report
  - [×] Net income — including noncontrolling interests $ = 478.0 | p151 | 百胜中国_2022_HK_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests = 478.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Netincome—noncontrollinginterests = 36.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] NetIncome—YumChinaHoldings,Inc. $ = 442.0 | p109 | 百胜中国_2023_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests $ = 478.0 | p110 | 百胜中国_2023_Annual_Report
  - [×] Net income — including noncontrolling interests 901 = 813.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — noncontrolling interests 74 = 29.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc . 827 = 784.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — including noncontrolling interests = 478.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — noncontrolling interests = 36.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net Income — Yum China Holdings, Inc. $ = 442.0 | p147 | 百胜中国_2023_HK_Annual_Report
  - [×] Net income — including noncontrolling interests $ = 478.0 | p148 | 百胜中国_2023_HK_Annual_Report
  - [×] Netincome—includingnoncontrollinginterests = 478.0 | p110 | 百胜中国_2024_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2022_HK_Annual_Report.pdf`（第 150 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statements of Income Yum China Holdings, Inc . Years ended December 31, 2022 and 2021 (in US$…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-003 Yum China 2023 total assets

- 查询条件：百胜中国 / balance / 2023 / period_type=annual
- 期望来源：百胜中国_2023_HK_Annual_Report 第150页
- DB 候选命中：7 条；行级 hit=True
  - [×] TotalAssets = 12031.0 | p112 | 百胜中国_2023_Annual_Report
  - [×] Total Assets 12,031 11,826 = 13223.0 | p73 | 百胜中国_2023_HK_Annual_Report
  - [√] Total Assets = 12031.0 | p150 | 百胜中国_2023_HK_Annual_Report
  - [×] TotalAssets = 12031.0 | p113 | 百胜中国_2024_Annual_Report
  - [×] Total Assets 11,121 12,031 = 13223.0 | p74 | 百胜中国_2024_HK_Annual_Report
  - [×] Total Assets = 12031.0 | p154 | 百胜中国_2024_HK_Annual_Report
  - [×] Total Assets 10,783 11,121 = 13223.0 | p76 | 百胜中国_2025_HK_Annual_Report
  - 打开文件：`\\Dxp4800-1305\财报&研报\百胜中国\年报\百胜中国_2023_HK_Annual_Report.pdf`（第 150 页）
  - 该页开头：CONSOLIDATED FINANCIAL STATEMENTS Consolidated Balance Sheets Yum China Holdings, Inc . December 31, 2023 and 2022 (in US$ millions) 2023 20…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-004 海底捞 2019 年 net profit

- 查询条件：海底捞 / income / 2019 / period_type=annual
- 期望来源：2019年报 第197页
- DB 候选命中：2 条；行级 hit=True
  - [√] Profit for the year 年内溢利 = 2346962.0 | p197 | 2019年报
  - [×] Profit for the year 年内溢利 = 2346962.0 | p213 | 2020年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2019年报.pdf`（第 197 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2019 截至2019年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-005 海底捞 2022 年 net profit

- 查询条件：海底捞 / income / 2022 / period_type=annual
- 期望来源：2022年报 第243页
- DB 候选命中：6 条；行级 hit=True
  - [×] Profit (loss) before tax 除税前溢利（亏损） = 2117641.0 | p243 | 2022年报
  - [×] operations 年内溢利（亏损） = 1637306.0 | p243 | 2022年报
  - [√] Profit (loss) for the year 年内溢利（亏损） = 1373216.0 | p243 | 2022年报
  - [×] Profit before tax 除税前溢利 = 2117641.0 | p278 | 2023年报
  - [×] Profit for the year from continuing operations 来自持续经营业务的年内溢利 = 1637306.0 | p278 | 2023年报
  - [×] Profit for the year 年内溢利 = 1373216.0 | p278 | 2023年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2022年报.pdf`（第 243 页）
  - 该页开头：Consolidated Statement of Profit or Loss and Other Comprehensive Income 综合损益及其他全面收益表 For the year ended December 31, 2022 截至2022年12月31日止年度 F…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

### cross-006 海底捞 2025 年 operating cash flow

- 查询条件：海底捞 / cashflow / 2025 / period_type=annual
- 期望来源：2025年报 第159页
- DB 候选命中：1 条；行级 hit=True
  - [√] Net cash from operating activities 经营活动所得现金净额 = 5664189.0 | p159 | 2025年报
  - 打开文件：`\\Dxp4800-1305\财报&研报\海底捞\2025年报.pdf`（第 159 页）
  - 该页开头：Consolidated Statement of Cash Flows 综合现金流量表 For the year ended December 31, 2025 截至2025年12月31日止年度 For the year ended December 31, 截至12月31日止…

  - [ ] 人工原值：____；单位：____；币种：____；PDF 页码：____
  - [ ] 判定：____；复核人/日期：____

## 二、检索 ground truth 复核（46 题）

范围：keyword 20 + semantic 20 + cross 纯检索 6。
目标：确认每个期望来源页确实能回答该问题；不能只因为包含关键词就判为相关。

| ID | 问题 | 期望来源 | 该页开头 | 判定 |
|---|---|---|---|---|
| keyword-001 | 海底捞 翻台率 | 海底捞研报-国信-202502 p19 | 看点1-同店复苏：VS历史经营高点，客单价&翻台率仍有回升空间 n 经营回顾：2024年翻台恢复度先扬后抑，客单价主动降低适配消费环境 Ø 2024年翻台回顾：跟我们对公司跟踪，2024年上半年月度翻台恢复率均超2023年同期10-40%，系2023年上半年疫情防控解封后翻台仍阶… | ☐ 相关 / ☐ 需改 |
| keyword-002 | 海底捞 同店销售 | 研报-国信证券HK-2021-餐饮业复苏中 p4 | 公司研究 海底捞（6862.HK）：餐饮业复苏进行中 2020 年新开店数量544 间（关闭餐厅 14 间，全年净新开 530 间），其中上半年新开 173 间， 下半年新开371间，比2019年全年新开店302间，开店速度明显加快。疫情期间，餐饮业大 受打击，部分中小餐饮企业面… | ☐ 相关 / ☐ 需改 |
| keyword-003 | 海底捞 门店净增 | 研报-国信证券-2021-阿米巴模式师徒制 p22 | Page 22 5月6日，海底捞股东SP NP Ltd.及LHY NP Ltd.拟以每股33.2港元的价格合 计配售4700万股股份，占公司已发行股本0.89%，涉及总金额达15.6亿港币。 配售计划于2020年5月11日上午9时完成。配售完成后，张勇舒萍夫妇总持 股由约 57.… | ☐ 相关 / ☐ 需改 |
| keyword-004 | 海底捞 减值 | 2022年报 p285 | Notes to the Consolidated Financial Statements 综合财务报表附注 For the year ended December 31, 2022 截至2022年12月31日止年度 3. BASIS OF PREPARATION OF CON… | ☐ 相关 / ☐ 需改 |
| keyword-005 | 海底捞 客单价 | 研报-国信证券-2021-阿米巴模式师徒制 p24 | Page 24 2015-2019 年，海底捞内地城市餐厅客单价稳定提升，每年同比增长 2-4%， 2019年增长 4%。其中一、二城市 2019年客单价 110.1 和 99.4元，较 2018 年的106.1和94.8元分别提升3.8%和4.9%；三线及以下2019年客单价9… | ☐ 相关 / ☐ 需改 |
| keyword-006 | 海底捞 股息 | 2024年报 p151 | Consolidated Statement of Cash Flows 综合现金流量表 For the year ended December 31, 2024 截至2024年12月31日止年度 For the year ended December 31, 截至12月31日止… | ☐ 相关 / ☐ 需改 |
| keyword-007 | 海底捞 开店 | 2024中报 p12 | 2024 Interim Performance Review 2024年中期业绩回顾 To ensure the effective operation of all Haidilao restaurants, we 为确保整体海底捞餐厅经营效果良好， maintained a… | ☐ 相关 / ☐ 需改 |
| keyword-008 | 海底捞 员工激励 | 研报-国信证券-2021-阿米巴模式师徒制 p25 | Page 25 核心看点：服务 IP 强化格局，阿米巴管理优化质地 完全竞争格局下，另辟蹊径极致服务立IP，打造不一样的海底捞 服务立IP，另辟蹊径大致不一样的海底捞。结合前文分析，国内餐饮行业完全 竞争，且中餐口味多元，消费变迁下不断迭代，导致餐饮品牌生命周期压力。但 是，海底… | ☐ 相关 / ☐ 需改 |
| keyword-009 | 海底捞 师徒制 | 研报-国盛证券-2019-利益分享体系火锅巨头 p11 | 2019年07月24日 善、新门店支持和人力资源服务等。 ⚫ 抱团小组：区域内餐厅与其邻近餐厅形成一个“抱团小组”。这些抱团小组通常包括 5至18 家餐厅（通常以存在师徒关系的门店为主），并以有能力的店长（通常是小 组内各门店店长的师傅）担任“组长”。抱团小组内餐厅互帮互助，拓展… | ☐ 相关 / ☐ 需改 |
| keyword-010 | 海底捞 阿米巴 | 研报-国信证券-2021-阿米巴模式师徒制 p27 | Page 27 图46：海底捞员工晋升通道——管理技术后勤三条路径，成长路径清晰 资料来源: 掌上薪酬、红餐网、《海底捞你学不会》、《海底捞内部讲话(关键时张勇说了什么)》等，国信证券经济研究所整理 因此，海底捞虽然系餐饮劳动密集型行业，但离职率10%却明显低于同行。员 工忠诚度… | ☐ 相关 / ☐ 需改 |
| keyword-011 | 海底捞 现金流 | 研报-国信证券-2025-收入利润再创新高 p5 | 证券研究报告 财务预测与估值 资产负债表（百万元） 2023 2024 2025E 2026E 2027E利润表（百万元） 2023 2024 2025E 2026E 2027E 现金及现金等价物 6476 7475 11168 14328 17601营业收入 41453 427… | ☐ 相关 / ☐ 需改 |
| keyword-012 | 海底捞 资本开支 | 研报-国信证券-2021-阿米巴模式师徒制 p39 | Page 39 财务分析：租金占优助力费用率优化，现金储备良好 盈利能力分析：高速扩张下净利率略有下降，但仍相对高于同行 盈利能力方面，公司 2016年净利率高达 12.5%，自2017年门店加速扩张后， 净利率从 2017 年开始下降，2017/2018/2019 年净利率各 … | ☐ 相关 / ☐ 需改 |
| keyword-013 | 百胜中国 同店销售 | 国信证券_百胜中国_同店销售增速重新转正 p1 | 证券研究报告 \| 2025年08月06日 百胜中国（09987.HK） 优于大市 同店销售增速重新转正，运营效率持续提升 核心观点 公司研究·海外公司财报点评 2025Q2经营利润同增14.3%。2025Q2，公司收入27.87亿美元/+4.0%；经 社会服务·酒店餐饮 营利润3… | ☐ 相关 / ☐ 需改 |
| keyword-014 | 百胜中国 门店净增 | 国信证券_百胜中国_2024Q4同店降幅收窄 p2 | 证券研究报告 2024年第四季度核心经营利润同增35%。2024Q4，公司实现收入25.95亿美元， 同比+4.1%；经营利润1.51亿美元，同比+37.3%，核心经营利润1.50亿美元，同 比+35%；经调整净利润1.15亿美元，同比+11.7%，净利润增速慢于经营利润增速， … | ☐ 相关 / ☐ 需改 |
| keyword-015 | 百胜中国 资本开支 | 华源证券研报 p1 | 证券研究报告 社会服务 \| 酒店餐饮 港股\|公司点评报告 h20y2z5qd年at0e8m月ark11日 百胜中国(09987.HK) 投资评级： 增持（维持） ——同店转正 运营提升 经营利润改善 开店行稳致远 投资要点： 证券分析师  2025年8月5日，公司发布截至202… | ☐ 相关 / ☐ 需改 |
| keyword-016 | 百胜中国 股息 | 国信证券_百胜中国_2024Q4同店降幅收窄 p4 | 证券研究报告 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 图9：必胜客第四季度成本费用率 图10：必胜客第四季度餐厅/经营/净利润率水平 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 新店型规模… | ☐ 相关 / ☐ 需改 |
| keyword-017 | 百胜中国 品牌布局 | 2024_百胜中国_快餐业龙头多品牌布局 p4 | 华福证券 公司深度研究 \| 百胜中国 1 多品牌协同发展，快餐龙头长坡厚雪 快餐业龙头，多品牌布局。百胜中国是中国最大的餐饮公司，截至2024年3月 底，经营餐厅15022家。公司前身为百胜餐饮集团中国事业部，于2016年分拆出来 在纽交所独立上市，于2020年在港交所二次上市，… | ☐ 相关 / ☐ 需改 |
| keyword-018 | 百胜中国 数字化 | 2024_百胜中国_快餐业龙头多品牌布局 p10 | 华福证券 公司深度研究 \| 百胜中国 4 聚焦产业数字化，放大竞争优势 数字化放大竞争优势，消费体验提质。从点餐、支付、会员三方面进行数字化 创新与技术投入，有助于改善顾客体验，同时减少人工成本，实现销售增长。 1）手机点餐，到店即取。肯德基于2016年推出手机自助点餐服务，必胜… | ☐ 相关 / ☐ 需改 |
| keyword-019 | 百胜中国 KCOFFEE | 百胜中国_2024_Annual_Report p3 | On the bottom line, we protected our margins by generating value at scale. Core operating profit surged to $1.2 billion, a 12% increase year… | ☐ 相关 / ☐ 需改 |
| keyword-020 | 百胜中国 外卖 | 百胜中国_招股书_中文版 p166 | 46731 \ (Project Home) 18. 业务_a_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 业 务 的调味品，以具竞争力的价格提供诱人、美味及快捷方便的食品。此外，肯德基计 划… | ☐ 相关 / ☐ 需改 |
| semantic-001 | 海底捞的现金流质量怎么样？ | 研报-国信证券-2021-阿米巴模式师徒制 p41 | Page 41 图76：海底捞现金储备 图77：海底捞经营活动现金流量净额与同行比较 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 海底捞资产负债率上市后明显改善，但近两年因快速扩张又有所提升，叠加疫 情影响，2020H1 进一步上升，在… | ☐ 相关 / ☐ 需改 |
| semantic-001 | 海底捞的现金流质量怎么样？ | 研报-国信证券-2021-阿米巴模式师徒制 p40 | Page 40 机制相关。疫情影响下，海底捞人工成本2020年上半年同比增长11.6%，人工 成本占收入比重也从 2016-2019 年的 27-29%上升至 2020H1 的 41.74%。同 时，海底捞依托强IP的客流引流优势，租金优势显著优于同行（见图54）。具 体来看，海… | ☐ 相关 / ☐ 需改 |
| semantic-001 | 海底捞的现金流质量怎么样？ | 研报-国信证券-2025-收入利润再创新高 p5 | 证券研究报告 财务预测与估值 资产负债表（百万元） 2023 2024 2025E 2026E 2027E利润表（百万元） 2023 2024 2025E 2026E 2027E 现金及现金等价物 6476 7475 11168 14328 17601营业收入 41453 427… | ☐ 相关 / ☐ 需改 |
| semantic-002 | 海底捞的扩张策略是什么？ | 研报-国信证券-2023-降本增效静待新一轮增长 p3 | 证券研究报告 2022财年归母利润扭亏增150%，符合预告指引。2022财年，特海国际于2022年12 月30日联交所独立上市，海底捞（6862.HK）业务仅指代大中华区海底捞餐厅业 务，公司持续经营业务实现收入310.39亿元/-20.6%，归母净利润16.38亿元/ 扭亏+1… | ☐ 相关 / ☐ 需改 |
| semantic-002 | 海底捞的扩张策略是什么？ | 研报-国信证券-2023-降本增效静待新一轮增长 p5 | 证券研究报告 图7：公司毛利率及归母净利率 图8：公司期间费用率 资料来源：公司公告、Wind、国信证券经济研究所整理 资料来源：公司公告、Wind、国信证券经济研究所整理 近期翻台水平延续稳健表现，利润弹性有望持续显现。2023年1-2月公司整体&同店 翻台率基本恢复到2022… | ☐ 相关 / ☐ 需改 |
| semantic-002 | 海底捞的扩张策略是什么？ | 2021年报 p17 | Chairman’s Statement 主席报告 MR. ZHANG YONG 张勇先生 Chairman 主席 I hereby present our annual report for the year ended December 31, 本人谨此向各位股东提呈我们截至… | ☐ 相关 / ☐ 需改 |
| semantic-003 | 海底捞的成本管控措施 | 研报-东方证券-2023-2022年报点评利润改善重启扩张 p1 | 公司研究 \| 年报点评 海底捞 06862.HK 买入（上调） 利润改善明显，重启稳步拓张 股价（2023年04月14日） 19.78港元 目标价格 23.89港元 52周最高价/最低价 24.7/11.54港元 ——海底捞2022年报点评 总股本/流通H股（万股） 557,40… | ☐ 相关 / ☐ 需改 |
| semantic-003 | 海底捞的成本管控措施 | 研报-招银证券-2024-2024H1业绩点评 p1 | 证券研究报告 \| 2024年08月31日 海底捞（06862.HK） 优于大市 核心经营利润率维持稳定，“红石榴”计划加码新品牌孵化 核心观点 公司研究·海外公司财报点评 社会服务·酒店餐饮 2024H1核心经营利润27.99亿元，同增13.0%。2024H1，公司实现营收214… | ☐ 相关 / ☐ 需改 |
| semantic-004 | 海底捞的员工激励方式 | 研报-国信证券-2021-阿米巴模式师徒制 p25 | Page 25 核心看点：服务 IP 强化格局，阿米巴管理优化质地 完全竞争格局下，另辟蹊径极致服务立IP，打造不一样的海底捞 服务立IP，另辟蹊径大致不一样的海底捞。结合前文分析，国内餐饮行业完全 竞争，且中餐口味多元，消费变迁下不断迭代，导致餐饮品牌生命周期压力。但 是，海底… | ☐ 相关 / ☐ 需改 |
| semantic-004 | 海底捞的员工激励方式 | 研报-国信证券-2021-阿米巴模式师徒制 p39 | Page 39 财务分析：租金占优助力费用率优化，现金储备良好 盈利能力分析：高速扩张下净利率略有下降，但仍相对高于同行 盈利能力方面，公司 2016年净利率高达 12.5%，自2017年门店加速扩张后， 净利率从 2017 年开始下降，2017/2018/2019 年净利率各 … | ☐ 相关 / ☐ 需改 |
| semantic-004 | 海底捞的员工激励方式 | 研报-国盛证券-2019-利益分享体系火锅巨头 p11 | 2019年07月24日 善、新门店支持和人力资源服务等。 ⚫ 抱团小组：区域内餐厅与其邻近餐厅形成一个“抱团小组”。这些抱团小组通常包括 5至18 家餐厅（通常以存在师徒关系的门店为主），并以有能力的店长（通常是小 组内各门店店长的师傅）担任“组长”。抱团小组内餐厅互帮互助，拓展… | ☐ 相关 / ☐ 需改 |
| semantic-005 | 海底捞同店销售与翻台率趋势 | 研报-浦银国际-2024-翻台率估值承压 p5 | SPDBI 乐观与悲观情景假设 图表 5：海底捞（6862.HK）市场普遍预期 资料来源：Bloomberg、浦银国际 图表 6：海底捞（6862.HK）SPDBI情景假设 乐观情景：公司收入增长好于预期 悲观情景：公司收入增长不及预期 目标价：28.1港元 目标价：18.0港元… | ☐ 相关 / ☐ 需改 |
| semantic-005 | 海底捞同店销售与翻台率趋势 | 海底捞研报-国信-202502 p19 | 看点1-同店复苏：VS历史经营高点，客单价&翻台率仍有回升空间 n 经营回顾：2024年翻台恢复度先扬后抑，客单价主动降低适配消费环境 Ø 2024年翻台回顾：跟我们对公司跟踪，2024年上半年月度翻台恢复率均超2023年同期10-40%，系2023年上半年疫情防控解封后翻台仍阶… | ☐ 相关 / ☐ 需改 |
| semantic-005 | 海底捞同店销售与翻台率趋势 | 研报-国信证券HK-2021-餐饮业复苏中 p4 | 公司研究 海底捞（6862.HK）：餐饮业复苏进行中 2020 年新开店数量544 间（关闭餐厅 14 间，全年净新开 530 间），其中上半年新开 173 间， 下半年新开371间，比2019年全年新开店302间，开店速度明显加快。疫情期间，餐饮业大 受打击，部分中小餐饮企业面… | ☐ 相关 / ☐ 需改 |
| semantic-006 | 海底捞的师徒制与阿米巴管理模式 | 研报-国信证券-2021-阿米巴模式师徒制 p27 | Page 27 图46：海底捞员工晋升通道——管理技术后勤三条路径，成长路径清晰 资料来源: 掌上薪酬、红餐网、《海底捞你学不会》、《海底捞内部讲话(关键时张勇说了什么)》等，国信证券经济研究所整理 因此，海底捞虽然系餐饮劳动密集型行业，但离职率10%却明显低于同行。员 工忠诚度… | ☐ 相关 / ☐ 需改 |
| semantic-006 | 海底捞的师徒制与阿米巴管理模式 | 研报-国信证券-2021-阿米巴模式师徒制 p20 | Page 20 3）加速扩张期（2017年至今）：海底捞依托多年积累的供应链体系、阿米巴管 理模式下人才积累，以服务创品牌树立的IP效应，加快在一二线城市的门店加 密和在三线及以下城市的布局。同时，2018年 9月海底捞赴港上市获 75.6亿 港元的融资，有效为门店扩展提供资金支… | ☐ 相关 / ☐ 需改 |
| semantic-006 | 海底捞的师徒制与阿米巴管理模式 | 研报-国信证券-2021-阿米巴模式师徒制 p21 | Page 21 妇合计持有海底捞15.95%股权。以杨利娟为首的其他创始团队人员合计持有海 底捞7.2%股权。并且，通过控股创始股东全部持股的静远投资公司和自己直接 持股，张勇本人持股比例超过50%，将公司控制权牢握手中，从而使公司股权 高度集中，统筹决策高效。 图31：海底捞股… | ☐ 相关 / ☐ 需改 |
| semantic-007 | 海底捞翻台率变化趋势 | 研报-国信证券-2023-降本增效静待新一轮增长 p4 | 证券研究报告 图3：公司各线城市门店数量变化 图4：公司各线城市客单价变化 资料来源：公司公告、Wind、国信证券经济研究所整理 资料来源：公司公告、Wind、国信证券经济研究所整理 经营数据显韧性，港澳台强势复苏。翻台率方面，2022财年，公司平均翻台率3.0 次/持平；分城市… | ☐ 相关 / ☐ 需改 |
| semantic-007 | 海底捞翻台率变化趋势 | 研报-东吴证券-2019-管理体系深度解析 p22 | [T公ab司le深_Y度em研ei究] F 4. 单店视角：同店表现亮眼，成本费用领先，试水未来 4.1. 同店高基数稳增长，品牌保障客单 同店增速亮眼。2016-2017年同店销售增速在14%左右，其中二三线城市增速突出， 17年同店增速分别达到了14.5%和16.3%，同店增… | ☐ 相关 / ☐ 需改 |
| semantic-007 | 海底捞翻台率变化趋势 | 海底捞研报-国信-202502 p20 | 看点1-同店复苏：门店保本点降低，经营有望现更强利润弹性 n 经营回顾：硬骨头降本增效举措的推进，海底捞门店保本点 表：海底捞新门店模型保本点已经降至2.0/天左右 由疫情前的3.0次/天降至约2.0次/天 单位：万元 （ 翻 盈 台 亏 率 平 2 衡 .0 ） 翻台率3.0 … | ☐ 相关 / ☐ 需改 |
| semantic-008 | 海底捞的啄木鸟计划与门店优化 | 海底捞研报-国信-202502 p14 | 组织架构变革:“啄木鸟计划”意在固基,“硬骨头计划”重在提效 n 硬骨头计划循序渐进复开调整门店，存量门店薪酬体系调整。2022年中期，海底捞发布公告称，啄木鸟计划降本增效成效显著，后续将 循序渐进地重开符合条件的硬骨头门店（即在啄木鸟计划下暂时关停的门店）。2022财年，公司新… | ☐ 相关 / ☐ 需改 |
| semantic-008 | 海底捞的啄木鸟计划与门店优化 | 研报-平安证券-2022-中报点评疫情关店承压 p1 | 社会服务 行 2022年 08月 31日 业 报 行业点评 告 海底捞发布 2022 年中报，疫情&关店导致短期业绩承压 强于大市（维持） 事项： 海底捞发布 2022 年中报：上半年实现营收 167.64 亿元，同比-16.57%；归母 行情走势图 净利润-2.66亿元，上年同… | ☐ 相关 / ☐ 需改 |
| semantic-008 | 海底捞的啄木鸟计划与门店优化 | 研报-浙商证券-2023-从成长到坚韧餐饮王者 p8 | 海底捞(06862)公司深度 在北京开设第一家智慧餐厅，通过智能机器人针对不同客户用餐偏好提供定制化服务，并 对用餐环境进行升级改造。2020 年，海底捞已全面实现“云上捞”，前端到后端所有核心业 务系统全部上云。 2.2 调整恢复时期（2020-2022年） 2020 年伊始，… | ☐ 相关 / ☐ 需改 |
| semantic-009 | 海底捞利润率变化 | 海底捞研报-国信-202502 p20 | 看点1-同店复苏：门店保本点降低，经营有望现更强利润弹性 n 经营回顾：硬骨头降本增效举措的推进，海底捞门店保本点 表：海底捞新门店模型保本点已经降至2.0/天左右 由疫情前的3.0次/天降至约2.0次/天 单位：万元 （ 翻 盈 台 亏 率 平 2 衡 .0 ） 翻台率3.0 … | ☐ 相关 / ☐ 需改 |
| semantic-009 | 海底捞利润率变化 | 研报-国盛证券-2019-利益分享体系火锅巨头 p23 | 2019年07月24日 图表37：海底捞开店数量预测 餐厅数量 2017 2018 2019E 2020E 2021E 2022E 中国大陆 一线城市 65 106 136 161 181 181 二线城市 120 207 247 277 297 307 三线及以下城市 69 1… | ☐ 相关 / ☐ 需改 |
| semantic-009 | 海底捞利润率变化 | 研报-东吴证券-2019-管理体系深度解析 p27 | [T公ab司le深_Y度em研ei究] F 三线及以下城市 20.90% 20.10% 19.60% 整体中国内地 25.50% 22.30% 21.10% 数据来源：招股说明书，东吴证券研究所 注：按餐厅层面的收入与餐厅层面原材料及易耗品成本、员工成本、物业租金及相关开支、 水… | ☐ 相关 / ☐ 需改 |
| semantic-010 | 海底捞客单价与翻台率的关系 | 海底捞研报-国信-202502 p19 | 看点1-同店复苏：VS历史经营高点，客单价&翻台率仍有回升空间 n 经营回顾：2024年翻台恢复度先扬后抑，客单价主动降低适配消费环境 Ø 2024年翻台回顾：跟我们对公司跟踪，2024年上半年月度翻台恢复率均超2023年同期10-40%，系2023年上半年疫情防控解封后翻台仍阶… | ☐ 相关 / ☐ 需改 |
| semantic-010 | 海底捞客单价与翻台率的关系 | 研报-国信证券-2021-阿米巴模式师徒制 p24 | Page 24 2015-2019 年，海底捞内地城市餐厅客单价稳定提升，每年同比增长 2-4%， 2019年增长 4%。其中一、二城市 2019年客单价 110.1 和 99.4元，较 2018 年的106.1和94.8元分别提升3.8%和4.9%；三线及以下2019年客单价9… | ☐ 相关 / ☐ 需改 |
| semantic-010 | 海底捞客单价与翻台率的关系 | 研报-东吴证券-2019-管理体系深度解析 p32 | [T公ab司le深_Y度em研ei究] F 城市的可行性。并且，低线城市翻台率逐步提升，生活节奏慢带来的拖累不明显，潜力 可期。 1）在客单价上，各线城市客单价均显著提升，一二三线城市 15-18CAGR 分别为 4.42%、3.26%和0.85%。18年三线及以下城市快速扩张，… | ☐ 相关 / ☐ 需改 |
| semantic-011 | 百胜中国同店销售趋势 | 国信证券_百胜中国_同店销售增速重新转正 p1 | 证券研究报告 \| 2025年08月06日 百胜中国（09987.HK） 优于大市 同店销售增速重新转正，运营效率持续提升 核心观点 公司研究·海外公司财报点评 2025Q2经营利润同增14.3%。2025Q2，公司收入27.87亿美元/+4.0%；经 社会服务·酒店餐饮 营利润3… | ☐ 相关 / ☐ 需改 |
| semantic-011 | 百胜中国同店销售趋势 | 国信证券_百胜中国_2024Q4同店降幅收窄 p2 | 证券研究报告 2024年第四季度核心经营利润同增35%。2024Q4，公司实现收入25.95亿美元， 同比+4.1%；经营利润1.51亿美元，同比+37.3%，核心经营利润1.50亿美元，同 比+35%；经调整净利润1.15亿美元，同比+11.7%，净利润增速慢于经营利润增速， … | ☐ 相关 / ☐ 需改 |
| semantic-011 | 百胜中国同店销售趋势 | 百胜中国_2023_HK_Annual_Report p76 | MANAGEMENT’S DISCUSSION AND ANALYSIS From 2020 to 2022, the COVID-19 pandemic closures due to lapping of the impact of the COVID-19 signific… | ☐ 相关 / ☐ 需改 |
| semantic-012 | 百胜中国的成本与费用管控 | 国信证券_百胜中国_2023年报费用管控效果显著 p3 | 证券研究报告 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 肯德基分部 2023年，肯德基品牌实现收入82.40亿美元，同比增长14%；其中餐厅收入为81.16 亿美元，同比+14%，占肯德基总收入的比例为98.5%，同比-0.1pct；… | ☐ 相关 / ☐ 需改 |
| semantic-012 | 百胜中国的成本与费用管控 | 海通国际_百胜中国_2025投资者日_创新与提效双轮驱动 p1 | 研究报告Research Report 18 Nov 2025 百胜中国-S Yum China Holdings (9987 HK) 2025 投资者日：创新与提效双轮驱动，目标 2030 年门店超 3 万家 2025 Investor Day: Driving Growth … | ☐ 相关 / ☐ 需改 |
| semantic-013 | 百胜中国的多品牌布局 | 2024_百胜中国_快餐业龙头多品牌布局 p4 | 华福证券 公司深度研究 \| 百胜中国 1 多品牌协同发展，快餐龙头长坡厚雪 快餐业龙头，多品牌布局。百胜中国是中国最大的餐饮公司，截至2024年3月 底，经营餐厅15022家。公司前身为百胜餐饮集团中国事业部，于2016年分拆出来 在纽交所独立上市，于2020年在港交所二次上市，… | ☐ 相关 / ☐ 需改 |
| semantic-013 | 百胜中国的多品牌布局 | 2024_百胜中国_快餐业龙头多品牌布局 p10 | 华福证券 公司深度研究 \| 百胜中国 4 聚焦产业数字化，放大竞争优势 数字化放大竞争优势，消费体验提质。从点餐、支付、会员三方面进行数字化 创新与技术投入，有助于改善顾客体验，同时减少人工成本，实现销售增长。 1）手机点餐，到店即取。肯德基于2016年推出手机自助点餐服务，必胜… | ☐ 相关 / ☐ 需改 |
| semantic-013 | 百胜中国的多品牌布局 | 2024_百胜中国_快餐业龙头多品牌布局 p11 | 华福证券 公司深度研究 \| 百胜中国 业务运营现代化及快速发展，企业对于数字化建设大力投入，放大竞争优势。 数字化有效控本，员工数管控稳健有效。公司通过数字化设备减少了餐厅经理 和员工的管理和运营负担，例如智能手表与智能眼镜等设备，餐厅经理可以通过这 些设备密切监控餐厅的实时订单… | ☐ 相关 / ☐ 需改 |
| semantic-014 | 百胜中国的竞争格局 | 百胜中国_招股书_中文版 p134 | 46731 \ (Project Home) 15. 行业概览_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 行 业 概 览 年人均仅消耗7.1杯咖啡，而美国及韩国则分别消耗390.7杯及353… | ☐ 相关 / ☐ 需改 |
| semantic-014 | 百胜中国的竞争格局 | 2024_百胜中国_快餐业龙头多品牌布局 p4 | 华福证券 公司深度研究 \| 百胜中国 1 多品牌协同发展，快餐龙头长坡厚雪 快餐业龙头，多品牌布局。百胜中国是中国最大的餐饮公司，截至2024年3月 底，经营餐厅15022家。公司前身为百胜餐饮集团中国事业部，于2016年分拆出来 在纽交所独立上市，于2020年在港交所二次上市，… | ☐ 相关 / ☐ 需改 |
| semantic-015 | 百胜中国的门店增长来自哪里 | 国信证券_百胜中国_2024Q4同店降幅收窄 p2 | 证券研究报告 2024年第四季度核心经营利润同增35%。2024Q4，公司实现收入25.95亿美元， 同比+4.1%；经营利润1.51亿美元，同比+37.3%，核心经营利润1.50亿美元，同 比+35%；经调整净利润1.15亿美元，同比+11.7%，净利润增速慢于经营利润增速， … | ☐ 相关 / ☐ 需改 |
| semantic-015 | 百胜中国的门店增长来自哪里 | 国信证券_百胜中国_2024Q3经营数据改善 p3 | 证券研究报告 2024Q3经调整经营利润同增13.5%，优于市场预期。2024Q3，公司实现收入30.7 亿美元，同比+5.4%，创下历史新高；经营利润3.71亿美元，同比+14.9%；核心 经营利润3.69亿美元，同比+18.3%；归母净利润2.97亿美元，同比+21.7%；经… | ☐ 相关 / ☐ 需改 |
| semantic-015 | 百胜中国的门店增长来自哪里 | 海通国际_百胜中国_2025投资者日_创新与提效双轮驱动 p1 | 研究报告Research Report 18 Nov 2025 百胜中国-S Yum China Holdings (9987 HK) 2025 投资者日：创新与提效双轮驱动，目标 2030 年门店超 3 万家 2025 Investor Day: Driving Growth … | ☐ 相关 / ☐ 需改 |
| semantic-016 | 百胜中国的咖啡业务布局 | 百胜中国_2024_Annual_Report p3 | On the bottom line, we protected our margins by generating value at scale. Core operating profit surged to $1.2 billion, a 12% increase year… | ☐ 相关 / ☐ 需改 |
| semantic-016 | 百胜中国的咖啡业务布局 | 百胜中国_2025_HK_Annual_Report p7 | BUSINESS customer engagement and continue to broaden continuously carrying out nationwide that not only our brand appeal. Each of our restau… | ☐ 相关 / ☐ 需改 |
| semantic-016 | 百胜中国的咖啡业务布局 | 百胜中国_2022_Annual_Report p92 | EXECUTIVECOMPENSATION OUTSTANDING 2022 LAVAZZA ESOP GRANTS AT 2022 YEAR-END ThefollowingtableshowsthenumberofthesharesoftheLavazzaJointVentu… | ☐ 相关 / ☐ 需改 |
| semantic-017 | 百胜中国的数字化与外卖策略 | 2024_百胜中国_快餐业龙头多品牌布局 p10 | 华福证券 公司深度研究 \| 百胜中国 4 聚焦产业数字化，放大竞争优势 数字化放大竞争优势，消费体验提质。从点餐、支付、会员三方面进行数字化 创新与技术投入，有助于改善顾客体验，同时减少人工成本，实现销售增长。 1）手机点餐，到店即取。肯德基于2016年推出手机自助点餐服务，必胜… | ☐ 相关 / ☐ 需改 |
| semantic-017 | 百胜中国的数字化与外卖策略 | 百胜中国_招股书_中文版 p161 | 46731 \ (Project Home) 18. 业务_a_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 业 务 餐（如粥及油条）的西式快餐品牌，而必胜客通过改良现有产品及添加新菜品，菜单于… | ☐ 相关 / ☐ 需改 |
| semantic-017 | 百胜中国的数字化与外卖策略 | 百胜中国_招股书_中文版 p166 | 46731 \ (Project Home) 18. 业务_a_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 业 务 的调味品，以具竞争力的价格提供诱人、美味及快捷方便的食品。此外，肯德基计 划… | ☐ 相关 / ☐ 需改 |
| semantic-018 | 百胜中国利润率变化 | 海通国际_百胜中国_2025Q2经营利润创新高 p1 | 研究报告Research Report 6 Aug 2025 百胜中国-S Yum China Holdings (9987 HK) 点评报告：2Q25 经营利润创第二季度新高，同店销售额实现正增长 Review Report: 2Q25 Operating Profit Hit… | ☐ 相关 / ☐ 需改 |
| semantic-018 | 百胜中国利润率变化 | 国信证券_百胜中国_2024Q4同店降幅收窄 p3 | 证券研究报告 65%。全年外卖收入同增14%，延续过往10年的双位数增速表现，外卖收入占肯 德基/必胜客餐厅收入比重为39%。 图3：百胜中国整体/肯德基/必胜客季度净增门店 图4：百胜中国会员数量以及会员销售餐厅收入占比 资料来源：公司公告、国信证券经济研究所整理 资料来源：公… | ☐ 相关 / ☐ 需改 |
| semantic-018 | 百胜中国利润率变化 | 华源证券研报 p1 | 证券研究报告 社会服务 \| 酒店餐饮 港股\|公司点评报告 h20y2z5qd年at0e8m月ark11日 百胜中国(09987.HK) 投资评级： 增持（维持） ——同店转正 运营提升 经营利润改善 开店行稳致远 投资要点： 证券分析师  2025年8月5日，公司发布截至202… | ☐ 相关 / ☐ 需改 |
| semantic-019 | 百胜中国的股息与股东回报 | 国信证券_百胜中国_2024Q4同店降幅收窄 p4 | 证券研究报告 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 图9：必胜客第四季度成本费用率 图10：必胜客第四季度餐厅/经营/净利润率水平 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 新店型规模… | ☐ 相关 / ☐ 需改 |
| semantic-019 | 百胜中国的股息与股东回报 | 百胜中国_2025_Annual_Report p62 | PARTI cantextentondividendsandotherdistributionsonequity mettherelevantrequirementspursuanttothetaxarrange- paidbyour principaloperatingsubs… | ☐ 相关 / ☐ 需改 |
| semantic-020 | 百胜中国的外卖与配送能力 | 百胜中国_招股书_中文版 p166 | 46731 \ (Project Home) 18. 业务_a_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 业 务 的调味品，以具竞争力的价格提供诱人、美味及快捷方便的食品。此外，肯德基计 划… | ☐ 相关 / ☐ 需改 |
| semantic-020 | 百胜中国的外卖与配送能力 | 百胜中国_2025_HK_Annual_Report p45 | RISK FACTORS requisite bandwidth could also interfere with the speed Major failures to provide timely and reliable and availability of our w… | ☐ 相关 / ☐ 需改 |
| cross-007 | Yum China same-store sales trend | 百胜中国_2023_HK_Annual_Report p76 | MANAGEMENT’S DISCUSSION AND ANALYSIS From 2020 to 2022, the COVID-19 pandemic closures due to lapping of the impact of the COVID-19 signific… | ☐ 相关 / ☐ 需改 |
| cross-008 | Haidilao restaurant count 门店数量 | 研报-国信证券-2021-阿米巴模式师徒制 p22 | Page 22 5月6日，海底捞股东SP NP Ltd.及LHY NP Ltd.拟以每股33.2港元的价格合 计配售4700万股股份，占公司已发行股本0.89%，涉及总金额达15.6亿港币。 配售计划于2020年5月11日上午9时完成。配售完成后，张勇舒萍夫妇总持 股由约 57.… | ☐ 相关 / ☐ 需改 |
| cross-009 | Yum China dividends and buyback 股息与回购 | 国信证券_百胜中国_2024Q4同店降幅收窄 p4 | 证券研究报告 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 图9：必胜客第四季度成本费用率 图10：必胜客第四季度餐厅/经营/净利润率水平 资料来源：公司公告、国信证券经济研究所整理 资料来源：公司公告、国信证券经济研究所整理 新店型规模… | ☐ 相关 / ☐ 需改 |
| cross-010 | 海底捞 same-store sales 同店销售 | 2019年报 p21 | Management Discussion and Analysis 管理层讨论与分析 The following table sets forth details of our same store sales of Haidilao 下表载列于所示期间我们的海底捞餐厅 res… | ☐ 相关 / ☐ 需改 |
| cross-011 | Yum China store count by year | 2024_百胜中国_快餐业龙头多品牌布局 p4 | 华福证券 公司深度研究 \| 百胜中国 1 多品牌协同发展，快餐龙头长坡厚雪 快餐业龙头，多品牌布局。百胜中国是中国最大的餐饮公司，截至2024年3月 底，经营餐厅15022家。公司前身为百胜餐饮集团中国事业部，于2016年分拆出来 在纽交所独立上市，于2020年在港交所二次上市，… | ☐ 相关 / ☐ 需改 |
| cross-012 | Haidilao table turnover rate 翻台率 | 研报-东吴证券-2019-管理体系深度解析 p22 | [T公ab司le深_Y度em研ei究] F 4. 单店视角：同店表现亮眼，成本费用领先，试水未来 4.1. 同店高基数稳增长，品牌保障客单 同店增速亮眼。2016-2017年同店销售增速在14%左右，其中二三线城市增速突出， 17年同店增速分别达到了14.5%和16.3%，同店增… | ☐ 相关 / ☐ 需改 |

## 三、负样本复核（26 道检索题）

目标：确认负样本确实是「容易混淆但不应命中」的页，而不是错误标注。
如果发现负样本其实也能回答问题，应记录为「改为正样本」或「删除负样本」。

| ID | 负样本 | 该页开头 | 判定 |
|---|---|---|---|
| keyword-001 | 研报-国信证券-2021-阿米巴模式师徒制 p23 | Page 23 在加密一二线城市的基础上，积极推动三线及以下城市下沉。海底捞定位中高 端消费客群，早期门店以一二线城市为主。截至2016年底，一二线城市门店数 量占比78.6%，营收贡献高达84.7%。2017年，海底捞不仅加强其一二线扩张， 同时也开始加速三线及以下城市下沉。经… | ☐ 确为负 / ☐ 需改 |
| keyword-002 | 2019年报 p21 | Management Discussion and Analysis 管理层讨论与分析 The following table sets forth details of our same store sales of Haidilao 下表载列于所示期间我们的海底捞餐厅 res… | ☐ 确为负 / ☐ 需改 |
| keyword-003 | 研报-平安证券-2022-中报点评疫情关店承压 p1 | 社会服务 行 2022年 08月 31日 业 报 行业点评 告 海底捞发布 2022 年中报，疫情&关店导致短期业绩承压 强于大市（维持） 事项： 海底捞发布 2022 年中报：上半年实现营收 167.64 亿元，同比-16.57%；归母 行情走势图 净利润-2.66亿元，上年同… | ☐ 确为负 / ☐ 需改 |
| keyword-004 | 2021年报 p264 | Notes to the Consolidated Financial Statements 综合财务报表附注 For the year ended December 31, 2021 截至2021年12月31日止年度 3. BASIS OF PREPARATION OF CON… | ☐ 确为负 / ☐ 需改 |
| keyword-005 | 研报-浙商证券-2023-从成长到坚韧餐饮王者 p12 | 海底捞(06862)公司深度 表4： 调整成效初显，未来趋于明朗 2019 2020 2021 2022H1 2022H2 餐厅数 768 1,298 1,443 1,435 1,371 餐厅数（中国大陆） 716 1,205 1,329 1,310 1,349 其中：一线 19… | ☐ 确为负 / ☐ 需改 |
| keyword-006 | 2019年报 p205 | Consolidated Statement of Cash Flows 综合现金流量表 For the year ended December 31, 2019 截至2019年12月31日止年度 For the year ended December 31, 截至12月31日止… | ☐ 确为负 / ☐ 需改 |
| keyword-007 | 2020年报 p17 | Chairman’s Statement 主席报告 As the outbreak of the COVID-19 epidemic, the Group’s principal 由于新冠肺炎疫情的爆发，本集团在 business was severely affected in… | ☐ 确为负 / ☐ 需改 |
| keyword-008 | 研报-东吴证券-2019-管理体系深度解析 p15 | [T公ab司le深_Y度em研ei究] F 图22：员工授权额度 数据来源：草根调研，东吴证券研究所整理 激励为核心：薪酬与业绩高度挂钩。1）最开始海底捞发现中午时间段送菜工很忙， 但切菜工、洗碗工很闲，因而开创性的尝试了后台员工计件制，最开始通过放置筹码的 方式鼓励空闲员工参与… | ☐ 确为负 / ☐ 需改 |
| keyword-009 | 2018年报 p138 | Environmental, Social and Governance Report 环境、社会及管治报告 每一位员工在加入时均获配一位师傅。在我们的师徒制计划下， 师徒制 海底捞大学 师傅为新加入徒弟提供一周入职培训，并在其职业生涯过程中 计划 定期提供指导及支持。 海底捞大… | ☐ 确为负 / ☐ 需改 |
| keyword-010 | 研报-国盛证券-2019-利益分享体系火锅巨头 p12 | 2019年07月24日 别是3500元和4500元，高级员工无上限。且初级员工8个月内无法拿到中级 认证，中级员工8个月内无法拿到高级认证，将被自然淘汰。 张勇先生在2010年左右接触了阿米巴思想，后逐步开始将阿米巴经营原理应用于所管 理的企业中。目前从海底捞及关联公司的管理体系… | ☐ 确为负 / ☐ 需改 |
| keyword-011 | 研报-国盛证券-2019-利益分享体系火锅巨头 p2 | 2019年07月24日 财务报表和主要财务比率 资产负债表（百万元） 利润表（百万元） 会计年度 2017A 2018A 2019E 2020E 2021E 会计年度 2017A 2018A 2019E 2020E 2021E 流动资产 1,462 5,736 8,510 12,… | ☐ 确为负 / ☐ 需改 |
| keyword-012 | 2024年报 p239 | Notes to the Consolidated Financial Statements 综合财务报表附注 For the year ended December 31, 2024 截至2024年12月31日止年度 38. CAPITAL COMMITMENTS 38. 资本… | ☐ 确为负 / ☐ 需改 |
| keyword-013 | 百胜中国_招股书_中文版 p200 | 46731 \ (Project Home) 19. 财务资料_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 财 务 资 料 与截至2019年6月30日止六个月相比，2020年同期的总收入减少1… | ☐ 确为负 / ☐ 需改 |
| keyword-014 | 国信证券_百胜中国_2024Q3经营数据改善 p3 | 证券研究报告 2024Q3经调整经营利润同增13.5%，优于市场预期。2024Q3，公司实现收入30.7 亿美元，同比+5.4%，创下历史新高；经营利润3.71亿美元，同比+14.9%；核心 经营利润3.69亿美元，同比+18.3%；归母净利润2.97亿美元，同比+21.7%；经… | ☐ 确为负 / ☐ 需改 |
| keyword-015 | 国信证券_百胜中国_2023年报费用管控效果显著 p6 | 证券研究报告 财务预测与估值 资产负债表（百万美 元） 2022 2023 2024E 2025E 2026E利润表（百万美元）2022 2023 2024E 2025E 2026E 现金及现金等价物 1130 1128 2211 1737 2983营业收入 9569 10978… | ☐ 确为负 / ☐ 需改 |
| keyword-016 | 百胜中国_2025_Annual_Report p62 | PARTI cantextentondividendsandotherdistributionsonequity mettherelevantrequirementspursuanttothetaxarrange- paidbyour principaloperatingsubs… | ☐ 确为负 / ☐ 需改 |
| keyword-017 | 研报参考清单_可自行下载 p1 | # 百胜中国(09987.HK) 公开研报参考清单  > 以下研报可在各平台注册登录后下载。文件名注明来源及日期，可直接搜索获取PDF。  ## 一、已下载研报（共8份，来源：东方财富/dfcfw/OSS直链）  1. 国信证券 - 2023年报点评：费用管控效果显著 (2024… | ☐ 确为负 / ☐ 需改 |
| keyword-018 | 百胜中国_招股书_中文版 p161 | 46731 \ (Project Home) 18. 业务_a_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 业 务 餐（如粥及油条）的西式快餐品牌，而必胜客通过改良现有产品及添加新菜品，菜单于… | ☐ 确为负 / ☐ 需改 |
| keyword-019 | 百胜中国_招股书_中文版 p54 | 46731 \ (Project Home) 09. 风险因素_PHIP \ 28/08/2020 \ M07 本文件为草拟本，属不完整并可予更改，有关资料必须与本文件封面「警告」一节一并阅览。 风 险 因 素 外卖服务中断或提供外卖服务出现失误可能妨碍我们的产品及时或顺利送达。… | ☐ 确为负 / ☐ 需改 |
| keyword-020 | 百胜中国_2025_HK_Annual_Report p45 | RISK FACTORS requisite bandwidth could also interfere with the speed Major failures to provide timely and reliable and availability of our w… | ☐ 确为负 / ☐ 需改 |
| cross-007 | 百胜中国_招股书_英文版 p206 | FINANCIAL INFORMATION In 2019, the increase in Company sales and Restaurant profit, excluding the impact of F/X, was mainly driven by same-s… | ☐ 确为负 / ☐ 需改 |
| cross-008 | 2024_百胜中国_快餐业龙头多品牌布局 p4 | 未找到 | ☐ 确为负 / ☐ 需改 |
| cross-009 | 百胜中国_2025_Annual_Report p62 | PARTI cantextentondividendsandotherdistributionsonequity mettherelevantrequirementspursuanttothetaxarrange- paidbyour principaloperatingsubs… | ☐ 确为负 / ☐ 需改 |
| cross-010 | 研报-国信证券HK-2021-餐饮业复苏中 p4 | 公司研究 海底捞（6862.HK）：餐饮业复苏进行中 2020 年新开店数量544 间（关闭餐厅 14 间，全年净新开 530 间），其中上半年新开 173 间， 下半年新开371间，比2019年全年新开店302间，开店速度明显加快。疫情期间，餐饮业大 受打击，部分中小餐饮企业面… | ☐ 确为负 / ☐ 需改 |
| cross-011 | 百胜中国_2025_HK_Annual_Report p122 | REPORT OF THE DIRECTORS PSUs(1) Closing Grant date price on the fair value Unvested day prior to for awards Closing as at the Cancelled/ Unv… | ☐ 确为负 / ☐ 需改 |
| cross-012 | 海底捞研报-国信-202502 p19 | 看点1-同店复苏：VS历史经营高点，客单价&翻台率仍有回升空间 n 经营回顾：2024年翻台恢复度先扬后抑，客单价主动降低适配消费环境 Ø 2024年翻台回顾：跟我们对公司跟踪，2024年上半年月度翻台恢复率均超2023年同期10-40%，系2023年上半年疫情防控解封后翻台仍阶… | ☐ 确为负 / ☐ 需改 |

## 四、端到端人工判定

见 `eval/manual_review.md`，已按 end2end-001 至 008 对齐。

## 五、两篇试点笔记人工审核

见 `eval/manual_review.md` 第二节，对海底捞与百胜中国笔记按 6 项打 1–5 分。
