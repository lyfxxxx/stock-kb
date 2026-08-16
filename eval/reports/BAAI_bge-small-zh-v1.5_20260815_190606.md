# 检索评测报告

- 时间：20260815_190606
- 模型：BAAI/bge-small-zh-v1.5
- top_k：5

## 检索（Retrieval）

| 类型 | 数量 | Recall@k | Hit@1 | MRR | nDCG |
|---|---|---|---|---|---|
| exact | 3 | 0.0 | 0.0 | 0.0 | 0.0 |
| semantic | 6 | 1.0 | 0.333 | 0.639 | 0.688 |
| cross | 6 | 0.333 | 0.0 | 0.139 | 0.188 |

## 结构化三表（Structured）

| 数量 | Hit | Field match | Value match | Source match |
|---|---|---|---|---|
| 10 | 10 | 10 | 0 | 7 |

## 生成题（Generation）

| 数量 | Auto scored | Pending manual |
|---|---|---|
| 4 | 0 | 4 |
