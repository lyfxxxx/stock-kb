# 知识库建设与评测过程记录（问题与解决方案）

> 用途：复盘本机试点（海底捞 + 百胜中国）全过程中的问题与解法，供后续过程评估与优化。
> 范围：2026-08，本机 Windows + NAS 只读数据。
> 状态：持续更新。

## 一、环境与访问

### 1. Codex 沙箱访问 NAS 共享被拒

- 现象：`Test-Path \\Dxp4800-1305\财报&研报` 返回 True，但 `Get-ChildItem` 报 Access denied。
- 原因：沙箱文件系统限制，不是共享本身的问题。
- 解决：读取共享的命令统一提权执行；全程只读，不写源目录。
- 教训：涉及 NAS 的命令先 `Test-Path`，再提权；写操作永远只落在本地工作区。

### 2. PowerShell 传中文给 Python 变成 `?`

- 现象：CLI 搜索“翻台率”返回空；DB 内容正常，但查询词变成了 `???`。
- 原因：Windows PowerShell 5.1 管道默认按 ASCII 编码传给子进程，中文被破坏。
- 解决：CLI 启动时 `sys.stdout/stderr.reconfigure(encoding="utf-8")`；测试脚本把中文写进文件而非经管道；文档提示终端使用 UTF-8。
- 教训：中文参数/脚本不要走 stdin 管道；用文件、Unicode 转义或显式编码。

## 二、数据解析

### 3. 财报分类错误（`Annual_Report` 被分成 other）

- 现象：百胜中国美国年报全部被分为 other。
- 原因：文件名用下划线（`Annual_Report`），匹配关键词是空格（`annual report`）；且后台进程加载的是旧分类代码。
- 解决：classify 前把 `_`/`-` 归一化为空格；新增 `reclassify` 命令修正存量；扫描重跑。
- 教训：字符串匹配前先做字符归一化；运行中的进程不会热加载新代码。

### 4. 繁体中文检索不到

- 现象：搜“翻台率”为空，搜繁体“同店銷售”才命中。
- 原因：港股年报是繁体，FTS 精确匹配无繁简转换。
- 解决：用 opencc 做 t2s 归一化，页面文本存 `content`（简体）和 `content_orig`（原文）；FTS 索引简体。
- 教训：中英混排/繁简混合语料必须做文本归一化，且保留原文用于引用。

### 5. FTS5 对中文分词不友好

- 原因：默认 unicode61 tokenizer 对无空格中文按整串切分。
- 解决：FTS5 使用 trigram tokenizer；短于 3 字的查询走 `LIKE` 兜底。
- 教训：中文全文检索先确认 tokenizer，再设计查询。

### 6. 港股年报三表表格结构错乱

- 现象：pdfplumber `extract_tables()` 拆出的表完全错位（表头只有一个单元格、行错列）。
- 原因：中英对照双栏排版，表格线检测不可靠。
- 解决：放弃表格模式，改按页面文本行解析：报表页开头标题定位，行尾数字作为数值，过滤表头/单位噪声，跨页续表靠“页面开头含报表标题”判断。
- 教训：解析前先看文本层结构，再决定用 tables 还是 lines。

### 7. 英文年报报表页标题不在第一行

- 现象：美国年报报表页首行是 `PARTII`，标题在第二行，导致页面被跳过。
- 解决：标题检测放宽到前 10 行；补齐复数关键词（`Statements of Income`、`Balance Sheets` 等）。
- 教训：不要假设标题一定在第一行。

### 8. OCR 子进程编码错误

- 现象：tesseract 子进程报 `UnicodeDecodeError: 'gbk' codec can't decode`。
- 原因：`subprocess.run(text=True)` 默认按 GBK 解码 UTF-8 输出。
- 解决：显式 `encoding="utf-8", errors="replace"`。
- 教训：Windows 下子进程文本必须显式指定编码。

## 三、入库与索引

### 9. SQLite 命名参数缺字段

- 现象：scan 全部报 `You did not supply a value for binding parameter :currency`。
- 原因：`meta` 缺 `currency`/`accounting_standard` 等键。
- 解决：入库前 `setdefault(None)` 统一补齐。
- 教训：SQL 命名参数先统一 schema，避免逐条补洞。

### 10. companies 表为空

- 原因：scan 只写 reports，没写 companies。
- 解决：scan 里 `upsert_company`；存量数据补跑一次性填充。
- 教训：先规划好表间写入顺序。

### 11. `--rebuild` 误删所有模型索引

- 现象：重建 MiniLM 后 bge 索引消失。
- 原因：rebuild 时 `DELETE FROM embedding_index`（全表）+ DROP 所有 `chunks_vec_*`。
- 解决：只删除当前模型记录和当前维度 vec 表。
- 教训：重建逻辑必须按 model 隔离；破坏性操作先审查。

### 12. embedding_index 主键设计错误

- 现象：一个页只能属于一个模型，后建模型覆盖前一个。
- 原因：`page_id INTEGER PRIMARY KEY`。
- 解决：改为 `(model, page_id/chunk_id)` 复合主键，并写迁移脚本从旧 vec 表回填。
- 教训：多模型索引必须用复合主键。

### 13. 向量维度不匹配 / limit=0 陷阱

- 现象：`Expected 1024 dimensions but received 512`；`--limit 0` 反而全量执行。
- 原因：`for dim in MODEL_DIMS.values()` 覆盖外层 `dim`；`if limit:` 对 0 判断为假。
- 解决：循环用独立变量；`if limit is not None`。
- 教训：Python 循环变量泄漏；0 值的真值判断要小心。

### 14. sqlite-vec 语法

- 现象：`Only LIMIT or 'k =?' can be provided, not both`。
- 解决：去掉 LIMIT，用 `k` 参数控制返回数量。
- 教训：先读库文档再写查询。

### 15. 整页嵌入语义检索差 → 分块嵌入

- 现象：整页嵌入时语义问题召回低。
- 原因：整页内容长且杂，向量被稀释。
- 解决：按行合并成约 800 字/块（36,039 块），向量按块命中后聚合到页面。
- 教训：RAG 检索质量与分块粒度强相关，需要实验。

## 四、评测

### 16. 评测全 0 的校准问题

- 现象：最初所有类别 Recall=0。
- 原因：expected 文件名带 `.pdf` 而库里标题无扩展名；自然语言长句被 FTS 整句匹配。
- 解决：扩展名归一；问题加 `keywords`；exact/cross 走结构化 `statement` 判定；keyword 类按命中内容是否包含查询词判定。
- 教训：先校准判定逻辑，再谈模型好坏。

### 17. 样本量与 ground truth 不足

- 现状：28 题（exact 6 / keyword 6 / semantic 6 / cross 6 / end2end 4），18 题有 expected，部分 ground truth 是自动扩充/自标注。
- 影响：单类 1/6 ≈ 16.7 个百分点；n=6 全中的 95% 置信下限约 0.5；结论只能算初步。
- 计划：扩到 60–100 题、独立人工审核、增加负样本、报告置信区间/bootstrap、保留 hold-out。
- 教训：小样本点估计不可靠。

### 18. 混合检索被 FTS 挤掉向量结果

- 现象：语义查询 top-5 全是 FTS 命中，向量结果进不来。
- 原因：`merged = fts[:top_k] + vec 补充` 再截断。
- 解决：FTS 与向量结果交错合并。
- 教训：融合策略直接影响评测，不能简单拼接。

## 五、模型与 GPU

### 19. CPU 嵌入太慢

- 现象：bge-small 全量约 30 分钟/模型；jina-zh 40 分钟未完成。
- 解决：onnxruntime-gpu 尝试失败后，改用 sentence-transformers + torch cu124 + GPU；36,039 块约 6–9 分钟/模型。
- 教训：有 GPU 先确认 CUDA/cuDNN 工具链，再选推理后端。

### 20. onnxruntime-gpu CUDA 依赖地狱

- 现象：`cublasLt64_13.dll missing`、`cudnn64_9.dll missing`、`Invalid handle`。
- 原因：onnxruntime 1.28 要 CUDA 13；cuDNN 不在 PATH；版本匹配繁琐。
- 解决：降级 onnxruntime-gpu 1.23 + nvidia pip 包 + 复制 DLL 仍不稳定 → 弃用，改用 torch（自带 CUDA/cuDNN）。
- 教训：本地 GPU 场景，torch 全家桶比 onnxruntime-gpu 省心。

### 21. Hugging Face 下载慢/缓存不完整

- 现象：直连 huggingface.co 慢；BGE-M3 缓存缺 tokenizer 等文件。
- 解决：新增 `models download` 命令：hf-mirror 镜像 + hf_transfer 多线程 + snapshot_download 断点续传；补全后离线加载。
- 教训：国内大模型下载先上镜像/多线程；下载后要校验文件完整性。

### 22. 模型缓存后仍反复请求 HF

- 现象：模型已缓存，每次加载仍 HEAD 探测并重试。
- 原因：`HF_HUB_OFFLINE` 设置晚于 transformers import。
- 解决：import 前设置 `HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE`；embedder 实例做进程级缓存。
- 教训：环境变量生效时机要在 import 之前。

## 六、MCP 与交付

### 23. mcp 2.0 API 不兼容

- 现象：`mcp.server.fastmcp` 不存在。
- 解决：降级 mcp 1.29，使用稳定的 FastMCP。
- 教训：新大版本先看 changelog 再迁移。

### 24. streamable_http_client 参数差异

- 现象：客户端不接受 `headers` 参数；返回元组个数不一致。
- 解决：用 `httpx.AsyncClient(headers=...)` 传入；按 installed version 解包 3 个返回值。
- 教训：客户端 API 以实际安装版本为准。

### 25. HTTP token 鉴权

- 解决：FastMCP `streamable_http_app()` 外包一层 Starlette middleware，校验 `Authorization: Bearer`；验证无 token 401、有 token 放行。
- 教训：HTTP 暴露前必须鉴权。

### 26. 笔记数字可溯源

- 解决：笔记关键数字全部带“文件 + 页码”；`tools/audit_notes.py` 自动核对笔记文本与数据库三表交叉验证。
- 教训：交付前用脚本审计，别靠肉眼。

### 27. 评测度量增强：负样本入分 + 检索引擎矩阵 + 行级结构化判定

- 现象：旧评测中负样本只展示不计分；结构化 `hit` 可由不同行的 source/value 拼凑满足；`eval` 只能测 FTS 或 hybrid，无法单独测向量；报告缺少可复现信息。
- 解决：
  - `eval_runner.py` 增加 `precision_at_k`、`negative_hit_at_k`、`negative_hit_at_1`、`negative_ranks`，并写入 Markdown 失败明细。
  - 结构化改为同一行必须同时满足 field/source/page/value，单位与币种先透出可验证状态（DB 当前为空，显示 0/0）。
  - `run_eval` 增加 `engine`（fts/vector/hybrid），CLI 增加 `--engine`；报告记录题目集 SHA-256、DB size/mtime、耗时。
  - `eval/manual_review.md` 同步为 8 道 end2end；新增 `eval/OPTIMIZATION_PLAN.md` 记录完整优化计划与本轮结果。
- 新基线暴露的问题：FTS keyword Neg@5=0.65、cross Neg@1=0.50，说明只拿 Recall 会高估检索质量；hybrid 降低了 keyword Recall 但负样本污染也下降。
- 教训：先补度量，再调模型；ground truth 仍不独立，单位/币种校验仍需解析器回填后才能硬化。

## 七、当前已知局限与下一步

> 2026-08-16 自动修复后已更新；详细修复记录见 `docs/fix-record-20260816.md`。

- 题库已扩到 80 题，但 cross 纯检索仅 6 题、semantic 无负样本；ground truth 仍部分自标注，独立 PDF golden 未完成。
- end2end 8 题待人工审核（见 `eval/manual_review.md`）。
- `statements.unit/currency` 已回填，结构化 unit/currency 26/26；研报等单位未知项仍可能为空。
- MCP `search_reports` 已支持 fts/vector/hybrid 与年份/类型/语言过滤。
- 两字查询已建 `pages_bigram_fts`，但 bigram 排序在当前 80 题上会牺牲 keyword 基线，暂仅作空结果兜底；后续需要独立评测集调权。
- reranker / jina 对比未完成（reranker 下载曾被打断，可选）。
- US/HK 年报等“内容不同但语义重复”的 canonical 标记未实现；SHA 完全重复已自动标记并排除。
- Docker 迁移到 DXP-4800 与 Hermes Agent 接入未开始（NAS 阶段）。
- 自动扫描开关已实现（`scan --watch-interval`），但未在真实新增文件上验证。

## 八、可复用经验清单

- 中文/繁体语料：统一归一化后再建索引，并保留原文。
- 报表解析：先看文本层结构，再决定 tables vs lines。
- 向量索引：多模型必须复合主键；`rebuild` 按模型隔离。
- GPU：优先 torch 全家桶，避开 onnxruntime CUDA 依赖问题。
- 下载：国内镜像 + hf_transfer + snapshot_download 续传。
- 评测：先校准判定逻辑；ground truth 独立人工；小样本标注置信区间。
- 交付：数字可溯源 + 自动审计脚本。
