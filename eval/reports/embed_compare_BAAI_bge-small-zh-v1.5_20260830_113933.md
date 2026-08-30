# Embedding 筛选报告

套件：semantic + 无三表的 cross；问句归一化后 ≥ 6 字（才会走向量）。主指标是 **vector@5 / vector@50 分桶**，不是 FTS。

## BAAI/bge-small-zh-v1.5

engine=vector，vec_k=50，耗时 16.316s

### 合计

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 44 | 0.159 | 0.079–0.294 | 0.364 | 0.238–0.511 | 7 | 9 | 28 | 0.136 | 0.182 |

### split=freeze

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 26 | 0.115 | 0.04–0.29 | 0.308 | 0.165–0.5 | 3 | 5 | 18 | 0.081 | 0.154 |

### split=diag

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 18 | 0.222 | 0.09–0.452 | 0.444 | 0.246–0.663 | 4 | 4 | 10 | 0.216 | 0.222 |

### type=semantic

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 28 | 0.179 | 0.079–0.356 | 0.429 | 0.265–0.609 | 5 | 7 | 16 | 0.138 | 0.179 |

### type=cross

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 16 | 0.125 | 0.035–0.36 | 0.25 | 0.102–0.495 | 2 | 2 | 12 | 0.134 | 0.188 |

逐题：

- `semantic-001` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-002` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-003` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-004` freeze/semantic  vector=top5@3  hybrid_hit=True
- `semantic-005` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-006` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-007` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-008` freeze/semantic  vector=top5@2  hybrid_hit=True
- `semantic-009` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-010` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-011` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-012` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-013` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-014` freeze/semantic  vector=mid@29  hybrid_hit=False
- `semantic-015` freeze/semantic  vector=mid@33  hybrid_hit=False
- `semantic-016` freeze/semantic  vector=top5@1  hybrid_hit=True
- `semantic-017` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-018` freeze/semantic  vector=mid@15  hybrid_hit=False
- `semantic-019` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-020` freeze/semantic  vector=mid@45  hybrid_hit=False
- `cross-007` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-008` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-009` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-010` freeze/cross  vector=mid@9  hybrid_hit=True
- `cross-011` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-012` freeze/cross  vector=miss@—  hybrid_hit=False
- `semantic-021` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-022` diag/semantic  vector=top5@1  hybrid_hit=True
- `semantic-023` diag/semantic  vector=mid@6  hybrid_hit=False
- `semantic-024` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-025` diag/semantic  vector=mid@18  hybrid_hit=False
- `semantic-026` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-027` diag/semantic  vector=mid@7  hybrid_hit=False
- `semantic-028` diag/semantic  vector=top5@2  hybrid_hit=True
- `cross-013` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-014` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-015` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-016` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-017` diag/cross  vector=top5@1  hybrid_hit=True
- `cross-018` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-019` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-020` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-021` diag/cross  vector=mid@36  hybrid_hit=False
- `cross-022` diag/cross  vector=top5@1  hybrid_hit=True

## BAAI/bge-m3

engine=vector，vec_k=50，耗时 114.62s

### 合计

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 44 | 0.114 | 0.05–0.24 | 0.409 | 0.277–0.556 | 5 | 13 | 26 | 0.106 | 0.159 |

### split=freeze

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 26 | 0.038 | 0.007–0.189 | 0.269 | 0.137–0.461 | 1 | 6 | 19 | 0.054 | 0.077 |

### split=diag

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 18 | 0.222 | 0.09–0.452 | 0.611 | 0.386–0.797 | 4 | 7 | 7 | 0.181 | 0.278 |

### type=semantic

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 28 | 0.107 | 0.037–0.272 | 0.464 | 0.295–0.642 | 3 | 10 | 15 | 0.089 | 0.107 |

### type=cross

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 16 | 0.125 | 0.035–0.36 | 0.312 | 0.142–0.556 | 2 | 3 | 11 | 0.135 | 0.25 |

逐题：

- `semantic-001` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-002` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-003` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-004` freeze/semantic  vector=mid@6  hybrid_hit=False
- `semantic-005` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-006` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-007` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-008` freeze/semantic  vector=top5@1  hybrid_hit=True
- `semantic-009` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-010` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-011` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-012` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-013` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-014` freeze/semantic  vector=mid@17  hybrid_hit=False
- `semantic-015` freeze/semantic  vector=mid@47  hybrid_hit=False
- `semantic-016` freeze/semantic  vector=mid@49  hybrid_hit=False
- `semantic-017` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-018` freeze/semantic  vector=mid@19  hybrid_hit=False
- `semantic-019` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-020` freeze/semantic  vector=miss@—  hybrid_hit=False
- `cross-007` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-008` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-009` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-010` freeze/cross  vector=mid@13  hybrid_hit=True
- `cross-011` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-012` freeze/cross  vector=miss@—  hybrid_hit=False
- `semantic-021` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-022` diag/semantic  vector=top5@4  hybrid_hit=True
- `semantic-023` diag/semantic  vector=mid@7  hybrid_hit=False
- `semantic-024` diag/semantic  vector=mid@6  hybrid_hit=False
- `semantic-025` diag/semantic  vector=mid@28  hybrid_hit=False
- `semantic-026` diag/semantic  vector=mid@32  hybrid_hit=False
- `semantic-027` diag/semantic  vector=mid@21  hybrid_hit=False
- `semantic-028` diag/semantic  vector=top5@2  hybrid_hit=True
- `cross-013` diag/cross  vector=mid@33  hybrid_hit=False
- `cross-014` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-015` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-016` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-017` diag/cross  vector=top5@1  hybrid_hit=True
- `cross-018` diag/cross  vector=mid@19  hybrid_hit=False
- `cross-019` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-020` diag/cross  vector=miss@—  hybrid_hit=True
- `cross-021` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-022` diag/cross  vector=top5@1  hybrid_hit=True

## sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

engine=vector，vec_k=50，耗时 13.623s

### 合计

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 44 | 0.136 | 0.064–0.267 | 0.364 | 0.238–0.511 | 6 | 10 | 28 | 0.099 | 0.114 |

### split=freeze

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 26 | 0.077 | 0.021–0.241 | 0.154 | 0.061–0.335 | 2 | 2 | 22 | 0.032 | 0.077 |

### split=diag

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 18 | 0.222 | 0.09–0.452 | 0.667 | 0.437–0.837 | 4 | 8 | 6 | 0.196 | 0.167 |

### type=semantic

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 28 | 0.107 | 0.037–0.272 | 0.321 | 0.179–0.507 | 3 | 6 | 19 | 0.054 | 0.071 |

### type=cross

| n | Recall@5 | @5 CI | Recall@50 | @50 CI | top5 | mid(6–50) | miss | MRR@50 | hybrid@5 |
|---|---|---|---|---|---|---|---|---|---|
| 16 | 0.188 | 0.066–0.43 | 0.438 | 0.231–0.668 | 3 | 4 | 9 | 0.179 | 0.188 |

逐题：

- `semantic-001` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-002` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-003` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-004` freeze/semantic  vector=top5@4  hybrid_hit=True
- `semantic-005` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-006` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-007` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-008` freeze/semantic  vector=top5@2  hybrid_hit=True
- `semantic-009` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-010` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-011` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-012` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-013` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-014` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-015` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-016` freeze/semantic  vector=mid@25  hybrid_hit=False
- `semantic-017` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-018` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-019` freeze/semantic  vector=miss@—  hybrid_hit=False
- `semantic-020` freeze/semantic  vector=miss@—  hybrid_hit=False
- `cross-007` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-008` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-009` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-010` freeze/cross  vector=mid@28  hybrid_hit=False
- `cross-011` freeze/cross  vector=miss@—  hybrid_hit=False
- `cross-012` freeze/cross  vector=miss@—  hybrid_hit=False
- `semantic-021` diag/semantic  vector=mid@7  hybrid_hit=False
- `semantic-022` diag/semantic  vector=mid@17  hybrid_hit=False
- `semantic-023` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-024` diag/semantic  vector=mid@12  hybrid_hit=False
- `semantic-025` diag/semantic  vector=mid@9  hybrid_hit=False
- `semantic-026` diag/semantic  vector=top5@4  hybrid_hit=False
- `semantic-027` diag/semantic  vector=miss@—  hybrid_hit=False
- `semantic-028` diag/semantic  vector=mid@16  hybrid_hit=False
- `cross-013` diag/cross  vector=mid@9  hybrid_hit=False
- `cross-014` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-015` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-016` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-017` diag/cross  vector=top5@2  hybrid_hit=True
- `cross-018` diag/cross  vector=top5@1  hybrid_hit=True
- `cross-019` diag/cross  vector=miss@—  hybrid_hit=False
- `cross-020` diag/cross  vector=top5@1  hybrid_hit=True
- `cross-021` diag/cross  vector=mid@6  hybrid_hit=False
- `cross-022` diag/cross  vector=mid@22  hybrid_hit=False

## 对比

### BAAI/bge-m3 vs BAAI/bge-small-zh-v1.5

- 判定：**indistinguishable**　建议换模：否
- @50 变好 6 / 变差 11 （net -5）
- 新进 top-5 0 / 掉出 top-5 2
- Recall@5 CI 重叠=True，@50 CI 重叠=True
- Wilson 区间重叠或只差 1 题时不当作模型胜出。better 才建议换模；换之前仍须 `python -m stock_kb eval --engine hybrid --model <候选> --split freeze` 过 hybrid semantic 门槛，并跑 run_eval_regression.py。

| id | split | base | challenger | Δrank |
|---|---|---|---|---|
| cross-010 | freeze | mid@9 | mid@13 | -4 |
| cross-013 | diag | miss@— | mid@33 | 18 |
| cross-018 | diag | miss@— | mid@19 | 32 |
| cross-021 | diag | mid@36 | miss@— | -15 |
| semantic-004 | freeze | top5@3 | mid@6 | -3 |
| semantic-008 | freeze | top5@2 | top5@1 | 1 |
| semantic-014 | freeze | mid@29 | mid@17 | 12 |
| semantic-015 | freeze | mid@33 | mid@47 | -14 |
| semantic-016 | freeze | top5@1 | mid@49 | -48 |
| semantic-018 | freeze | mid@15 | mid@19 | -4 |
| semantic-020 | freeze | mid@45 | miss@— | -6 |
| semantic-022 | diag | top5@1 | top5@4 | -3 |
| semantic-023 | diag | mid@6 | mid@7 | -1 |
| semantic-024 | diag | miss@— | mid@6 | 45 |
| semantic-025 | diag | mid@18 | mid@28 | -10 |
| semantic-026 | diag | miss@— | mid@32 | 19 |
| semantic-027 | diag | mid@7 | mid@21 | -14 |

### sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 vs BAAI/bge-small-zh-v1.5

- 判定：**lean_worse**　建议换模：否
- @50 变好 8 / 变差 13 （net -5）
- 新进 top-5 3 / 掉出 top-5 4
- Recall@5 CI 重叠=True，@50 CI 重叠=True
- Wilson 区间重叠或只差 1 题时不当作模型胜出。better 才建议换模；换之前仍须 `python -m stock_kb eval --engine hybrid --model <候选> --split freeze` 过 hybrid semantic 门槛，并跑 run_eval_regression.py。

| id | split | base | challenger | Δrank |
|---|---|---|---|---|
| cross-010 | freeze | mid@9 | mid@28 | -19 |
| cross-013 | diag | miss@— | mid@9 | 42 |
| cross-017 | diag | top5@1 | top5@2 | -1 |
| cross-018 | diag | miss@— | top5@1 | 50 |
| cross-020 | diag | miss@— | top5@1 | 50 |
| cross-021 | diag | mid@36 | mid@6 | 30 |
| cross-022 | diag | top5@1 | mid@22 | -21 |
| semantic-004 | freeze | top5@3 | top5@4 | -1 |
| semantic-014 | freeze | mid@29 | miss@— | -22 |
| semantic-015 | freeze | mid@33 | miss@— | -18 |
| semantic-016 | freeze | top5@1 | mid@25 | -24 |
| semantic-018 | freeze | mid@15 | miss@— | -36 |
| semantic-020 | freeze | mid@45 | miss@— | -6 |
| semantic-021 | diag | miss@— | mid@7 | 44 |
| semantic-022 | diag | top5@1 | mid@17 | -16 |
| semantic-023 | diag | mid@6 | miss@— | -45 |
| semantic-024 | diag | miss@— | mid@12 | 39 |
| semantic-025 | diag | mid@18 | mid@9 | 9 |
| semantic-026 | diag | miss@— | top5@4 | 47 |
| semantic-027 | diag | mid@7 | miss@— | -44 |
| semantic-028 | diag | top5@2 | mid@16 | -14 |

## 怎么用这个结论

- `indistinguishable` / `lean_*`：不要换默认模型。
- `better`：候选在本套件上分得开，仍须过 freeze hybrid 门禁才改 `embedding.model`。
- keyword / 结构化 / 无答案不靠 embedding，不能用来选模型。
