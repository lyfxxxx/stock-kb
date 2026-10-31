# demo：不用 NAS 也能跑起来

这个小库从真实库里导出了 8 份公开财报（年报 / 中报 / 业绩公告），把页文本、报表行项目、指标和 FTS 索引一起打包，clone 下来就能查、能评测，不需要 NAS、不需要原始 PDF。

| 项 | 值 |
|---|---|
| 文档 | 8 份（海底捞 4、百胜中国 4） |
| 页文本 | 1,016 页 |
| 报表行项目 | 1,985 条 |
| 指标 | 310 条 |
| 题集 | 19 道，均由脚本从主题集里筛出（对照页都落在这 8 份文档里） |
| 体积 | 约 22 MB |

## 30 秒跑起来

```bash
# 1. 看库里有什么
STOCK_KB_CONFIG=demo/config.demo.yaml python -m stock_kb stats --json

# 2. 查一个词
STOCK_KB_CONFIG=demo/config.demo.yaml python -m stock_kb search "翻台率" --top-k 5 --json

# 3. 跑一遍评测（FTS 路径）
STOCK_KB_CONFIG=demo/config.demo.yaml python -m stock_kb eval
```

报告会写到 `demo/eval/reports/`。

## 想跑混合检索（可选）

demo 库里没有向量索引，`hybrid` 会退化成 FTS。要跑混合检索需要两步：

```bash
# 下载嵌入模型（约 100 MB）
python -m stock_kb models download --model BAAI/bge-small-zh-v1.5

# 给 demo 库建索引（60 页/秒左右，本库约 30 秒）
STOCK_KB_CONFIG=demo/config.demo.yaml python -m stock_kb index --model BAAI/bge-small-zh-v1.5

# 然后就可以跑 hybrid 了
STOCK_KB_CONFIG=demo/config.demo.yaml python -m stock_kb eval --engine hybrid --model BAAI/bge-small-zh-v1.5
```

## 这个库不含什么

- **原始 PDF**：只有页文本，没有原文文件。指引里的「文件 + 页码」仍然成立，页码是对原 PDF 的页码。
- **研报与电话会**：demo 只导出年报 / 中报 / 业绩公告。主库里另有 275 份研报和 132 份电话会纪要，未纳入，避免整本转载。
- **向量索引**：需要自己建（见上一节）。
- **出处 JSON**：`data/meta/` 下的 sidecar 未导出。

## 数据来源

8 份文档均为港交所 / 公司官网公开披露的财报，页文本仅用于检索演示。`tools/make_demo_db.py` 可重复生成：

```bash
python tools/make_demo_db.py --docs 8
```

## 已知限制

- 只有 19 道题，`semantic` 只有 3 道，统计意义有限，看趋势而不是看绝对值。
- 主库的 161 道题、15 项门禁在 `eval/EVAL_SYSTEM.md` 里，需要完整库才能跑。
