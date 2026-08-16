# 检索评测报告

- 时间：20260815_193032
- 模型：BAAI/bge-small-zh-v1.5
- top_k：5

## 检索（Retrieval）

| 类型 | 数量 | Recall@k | Hit@1 | MRR | nDCG |
|---|---|---|---|---|---|
| keyword | 20 | 0.55 | 0.35 | 0.41 | 0.444 |
| semantic | 20 | 0.3 | 0.15 | 0.217 | 0.191 |
| cross | 6 | 0.167 | 0.0 | 0.056 | 0.083 |

## 结构化三表（Structured）

| 数量 | Hit | Field match | Value match | Source match |
|---|---|---|---|---|
| 26 | 26 | 26 | 26 | 26 |

## 生成题（Generation）

| 数量 | Auto scored | Pending manual |
|---|---|---|
| 8 | 0 | 8 |
