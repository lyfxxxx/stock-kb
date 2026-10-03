# 报告系统

入门说明在 [从零理解财报知识库与 RAG 评测](knowledge-base-rag-eval-tutorial.md)。这篇按代码里已经能跑的路径，写清三层各自做什么、数据怎么交到下一层、每层用什么门验收。

交互图：

- [三层结构](diagrams/layers.html)
- [从原文到审计稿](diagrams/run.html)

## 三层各回答什么

| 层 | 回答的问题 | 主要产物 | 评测 |
|---|---|---|---|
| 证据层 | 这句话还在不在原文里 | `reports` 目录、`pages`、`statements`、版本链 | 三表 26/26；`fidelity` 抽检 `content_orig` |
| 知识库层 | 问句该查科目、哪一页，还是没有答案 | `indicators`、FTS5、向量、MCP | 路由 24/24；keyword / hybrid semantic 的 Recall@5；分桶只报告、不足 5 题不设门 |
| 报告层 | 稿子里的数能不能回到这次查询 | 扫描稿、`retrieval_log.jsonl` | `audit-report`。无 `run_id` 的旧稿只跳过，不算通过 |

三层之间是交接，不是同一次命令里混做。证据层不负责检索排序，知识库层不改原文，报告层不把判断写进财务表。

## 层级结构

```mermaid
flowchart TB
  subgraph evidence [证据层：原文变成可引用的页，财报再抽出三表行]
    fetch[fetch：SEC、披露易或文件直链<br/>字节落到 data/raw<br/>出处 JSON 落到 data/meta]
    nFetch[财报必须落到<br/>研报和电话会<br/>单条失败只记日志]
    files[原始文件：NAS 目录或 data/raw<br/>扫描不发 HTTP]
    nScan[只读扫描<br/>空目录退出码 2]
    scan[scan：按文件名分类<br/>写入 reports 目录<br/>简体 content 供检索<br/>原文 content_orig 供引用]
    nPages[见下文<br/>三类文件怎么落成页和三表]
    pages[pages 三种文件都有<br/>statements 主要来自<br/>财报里页首像报表的页]
    fetch --> nFetch --> files --> nScan --> scan --> nPages --> pages
  end
  subgraph knowledge [" "]
    kcap[知识库层：不改原文<br/>下面三条并列，汇入 MCP]
    nInd[财报三表行]
    ind[indicators<br/>只从三表行归科目<br/>研报和电话会<br/>通常到不了这里]
    nRev[营业收入等科目]
    nFts[全部页文本]
    fts[FTS5<br/>所有页的简体正文<br/>短术语、翻台率走这里]
    nKeep[默认入口有页就返回<br/>长问句也不融合]
    nVec[全部页文本]
    vec[向量<br/>约 800 字一块<br/>长问句或 FTS 无命中才参与]
    nHy[显式 hybrid<br/>长度达到 6<br/>或短查询 FTS 为空]
    mcp[MCP：SQLite 只读<br/>命中只记标题和页码]
    pages --> kcap
    kcap --> nInd --> ind --> nRev --> mcp
    kcap --> nFts --> fts --> nKeep --> mcp
    kcap --> nVec --> vec --> nHy --> mcp
  end
  subgraph report [" "]
    rcap[报告层：agent 写稿<br/>数字必须回到这次查询]
    nNote[get_indicators、三表<br/>或 search_reports]
    note[stock-note<br/>自己拟查询<br/>科目不先走全文检索]
    nHit[每次读取追加命中]
    qlog[retrieval_log.jsonl<br/>不写入 stock_kb.db]
    nSkip[没有 run_id 的旧稿只跳过]
    nDone[终稿含必备节和文末出处]
    audit[audit-report<br/>注释数字要在<br/>该页或三表行里<br/>出处要属于本次 run_id]
    mcp --> rcap --> nNote --> note
    note --> nHit --> qlog --> nSkip --> audit
    note --> nDone --> audit
  end
```

证据层的活报告条件是 `COALESCE(is_duplicate,0)=0 AND COALESCE(status,'ok')='ok'`。`superseded`、`missing`、`failed` 不进默认检索。MCP `list_reports` 仍返回全部状态。

## 运行流程

```mermaid
flowchart TB
  collect[stock-collect<br/>财报找 SEC 或披露易<br/>电话会先找 IR，再找不登录的非官方直链<br/>研报只收能打开的文件 URL] --> fetch[fetch<br/>字节写入 data/raw<br/>出处写入 data/meta<br/>财报一件都没有则失败]
  fetch --> scan[scan<br/>NAS 与 raw 只读<br/>meta_dir 读写出处 JSON<br/>写入 reports 目录]
  scan --> store[写入<br/>财报：页 + 三表行<br/>研报、电话会：页文本<br/>通常无三表]
  store --> fid[fidelity<br/>抽检 content_orig<br/>空清单不算通过]
  store --> index[index 与 indicators<br/>向量和 FTS 用全部页<br/>指标只用三表行]
  index --> mcp[MCP 只读<br/>科目、短术语<br/>长问句分三条]
  mcp --> draft[stock-note<br/>先设 STOCK_KB_RUN_ID<br/>再自己拟查询写稿]
  draft --> qlog[retrieval_log.jsonl<br/>只记标题和页码]
  draft --> audit[audit-report<br/>数字、必备节、事实清单]
  qlog --> audit
```

对应命令：

```powershell
python -m stock_kb models download --model BAAI/bge-small-zh-v1.5
python -m stock_kb fetch --source sec --company 百胜中国
python -m stock_kb fetch --source hkex --company 海底捞
python -m stock_kb fetch --url "<文件直链>" --company 海底捞 --kind research --optional
python -m stock_kb scan
python -m stock_kb index --model BAAI/bge-small-zh-v1.5
python -m stock_kb indicators
python -m stock_kb fidelity
python -m stock_kb mcp --transport http --host 127.0.0.1 --port 8931
```

写稿前设置 `STOCK_KB_RUN_ID`。稿子里写一行 `run_id:`。然后：

```powershell
python -m stock_kb audit-report <稿子路径> --company 海底捞
```

收集规则在 `skill/stock-collect/SKILL.md`，写稿规则在 `skill/stock-note/SKILL.md`。财报用 SEC 或披露易。电话会先用公司 IR 上的文字稿直链；没有时，按该技能再收不登录就能打开的非官方会纪。研报只接受能直接打开的文件 URL，并加 `--kind research --optional`。不登录券商站，不绕过付费墙。披露易适配器在 `stock_kb/collectors/hkex.py`，失败写入 `data/collect_log.jsonl`。

公司目录都不存在、也没有因未变更而跳过的文件时，`scan` 退出码 2。目标年份的财报一件都没落到本机时，`fetch --source` 失败。研报或电话会单条失败只记日志。网页发现过程不进黄金回归。黄金回归只在维护者本机、库里已有试点数据时跑。

## 证据层

这一层把原文变成可引用的页和三表行。数值不在这里换算成人读单位。文件可以待在不同目录；一旦扫过，目录只认 SQLite `reports`。各字段事后做什么，见「文件 metadata 做什么」。

### 原文件怎么落库

原文有两个根目录：NAS `nas.root/{公司}/`，以及 `collect.raw_dir/{公司}/`（默认 `data/raw/{公司}/`）。两边不互拷。`scan` 对这两处都只读，不发 HTTP。出处 JSON 集中在 `collect.meta_dir`（默认 `data/meta`），键是 `{origin}/{公司}/{相对路径}.source.json`。某一侧原文目录不存在时只跳过该侧。公司目录都不存在、也没有因未变更而跳过的文件时，退出码 2。

`fetch` 把网络文件的字节写入 `raw_dir`，把出处 JSON 写入 `meta_dir/collect/{公司}/`。JSON 含 `source_url`、`retrieved_at`、`sha256`、`origin`，以及可选的 `kind`。`--kind transcript` 在文件名没有电话会关键词时加 `transcript-` 前缀，给后面的文件名分类用。`--kind` 本身只写进 JSON，扫描不读它。

```mermaid
flowchart TB
  src[原文待在两个根目录<br/>nas.root 与 collect.raw_dir<br/>scan 对这两处都只读]
  fetch[fetch 把字节写入 raw_dir<br/>出处 JSON 写入 meta_dir<br/>含 source_url、retrieved_at、sha256]
  nas[NAS 原文留在 NAS<br/>scan 不往 NAS 或 raw_dir 写 JSON]
  scan[scan 同时遍历两个公司目录<br/>不发 HTTP<br/>先按已存路径回填 origin]
  side[每个文件先读 meta_dir<br/>没有则读原文旁旧 sidecar<br/>取 source_url 与 retrieved_at]
  origin[origin 按路径前缀判定<br/>在 NAS 上是 nas<br/>在 raw_dir 上是 collect]
  act[按 sha、size、mtime、PARSE_VERSION<br/>以及 manifest 是否 ok<br/>决定 skip、重解析或新版本]
  skip[skip：不读正文<br/>仍回填 origin 和出处]
  parse[重解析或新版本：读正文<br/>先按文件名分类<br/>再写 content 与 content_orig]
  rep[upsert reports 一行目录<br/>path 唯一<br/>写入 origin、logical_key、出处、parse_version]
  disk[NAS 和网络文件都把 JSON<br/>写回 meta_dir<br/>键含 origin 和相对路径]
  body[再写 pages<br/>财报 pdf 与 xls 再写 statements]
  live[同一 logical_key 只留一条 status=ok<br/>相同 sha 标 is_duplicate<br/>目录里消失的标 missing]
  src --> fetch
  src --> nas
  fetch ~~~ nas
  fetch --> scan
  nas --> scan
  scan --> side --> origin --> act
  act --> skip
  act --> parse
  skip ~~~ parse
  skip --> disk
  parse --> rep --> body --> disk
  disk --> live
```

按代码顺序，metadata 在这些点设立：

| 步骤 | 写入位置 | 设立的字段 |
|---|---|---|
| `fetch` | `meta_dir/collect/{公司}/{相对路径}.source.json` | `source_url`、`retrieved_at`、`sha256`、`origin=collect`、可选 `kind` |
| `scan` 开场 | 已有 `reports` 行 | 按 `path` 相对两个根目录回填 `origin` |
| 每个文件 | 先读 `meta_dir`，没有则读原文旁旧 sidecar | `source_url`、`retrieved_at`；都没有则沿用库里旧值 |
| 判断 skip 之前 | 由路径算出 | `origin`：`nas` 或 `collect` |
| skip | `UPDATE reports`，并写回 `meta_dir` | 回填 `origin` 和出处；不分类、不读正文 |
| 决定解析之后 | `classify_report(path)` | `report_type`、`year`、`period_type`、文件名上的 `language` |
| 读完正文 | 覆盖 `reports.language` | 页内汉字占比 ≥2% 为 `zh`，否则 `en` |
| `upsert_report` | `reports` 一行 | `path`、`sha256`、`size`、`mtime`、`origin`、`source_url`、`retrieved_at`、`logical_key`、`parse_version`、`supersedes_id`、`status` |
| 扫过的 NAS 与网络文件 | `meta_dir/{origin}/{公司}/{相对路径}.source.json` | 与 `reports` 对齐的出处和身份字段 |
| `replace_pages` | `pages` | `content_orig`、`content`、`char_count`、`is_ocr`、`page_kind` |
| 财报 pdf / xls | `statements` | 行名、原值、单位、币种、年份、页码、`is_ocr` |
| 扫完 | `reports` / `manifest` | 同一 `logical_key` 选举 `ok`；相同 sha 标 `is_duplicate`；源文件消失标 `missing` |

分类看文件名和父目录。电话会关键词（电话会、业绩会、earnings call、transcript、纪要）优先于研报；研报关键词再优先于年报、中报，避免「2023年报费用管控效果显著」被收成年报。

`PARSE_VERSION` 在 `stock_kb/versioning.py`，当前是 `2026-10-02.1`。同一路径、sha、大小、mtime 都没变，且已经按这个版本扫成功，就跳过。sha 相同但 `parse_version` 旧了，就地重解析，不新插一行。sha 变了才新开版本。

`reports.path` 仍然唯一。同一路径内容变了：旧行路径改成 `{原路径}::superseded::{旧 sha 前 12 位}`，`status` 改为 `superseded`。新行占用原路径，`supersedes_id` 指向旧行。

`logical_key` 不含 sha。

- 年报、中报、三季报、招股：`{company}|{report_type}|{year}|{period_type}|{language}|{market}`
- 电话会：`{company}|transcript|{event_date}|{locator}`
- 研报：`{company}|research|{locator}`
- 其他：`{company}|other|{path}`，不同路径互不取代

研报和电话会的 `locator` 优先用 `source_url`，没有 URL 时用路径。同一键下，`(retrieved_at` 或空串, `mtime` 或 0, `id`) 最大的一条保持 `ok`。更旧的文件再扫进来，不会把更新的版本打回 ok。相同 sha 仍按 `is_duplicate` 标记。源文件从本次扫描的公司目录消失时，报告和 `manifest` 标 `missing`，不删行。

`manifest` 是扫描清单（路径、sha、大小、mtime、状态），用来判断这次读不读文件。给人查询用的目录是 `reports`。

### 三类文件怎么落成页和三表

每份支持的文件都先成为一行 `reports`（公司、类型、年份、语言、路径、`origin`、sha256、`logical_key`）。页和三表在这之后才分叉。

```mermaid
flowchart TB
  subgraph filing [财报：年报、中报、三季报、招股]
    fIn[PDF 逐页提取；字少的页走 OCR<br/>xls 把整张矩阵当成第 1 页]
    fRep[reports 一行<br/>类型、年份、期间、语言、市场<br/>同一逻辑键只留最新一份<br/>为活报告]
    fPage[pages：content 简体，content_orig 原文<br/>对上报表标题的页 page_kind=statement<br/>其余是封面、目录或正文]
    fStmt[statements：<br/>行名、原值、单位、币种、年份、页码<br/>页首 8 行要像四表标题<br/>短横只对齐<br/>OCR 行默认不进指标查询]
    fInd[indicators 从这些行归收入、归母净利等<br/>exact-001 的 42754687 千元走这条]
    fIn --> fRep --> fPage --> fStmt --> fInd
  end
  subgraph research [研报：点评、评级、深度、跟踪]
    rIn[PDF 同样逐页<br/>txt、md、html 整篇算第 1 页]
    rRep[reports：report_type=research<br/>不同研报互不取代<br/>只有同一 URL 的新文件<br/>才替换旧的]
    rPage[pages 标成封面、目录或正文<br/>简体正文进入 FTS 和向量<br/>翻台率命中研报页<br/>就是在查这些页]
    rStmt[页首通常对不上报表标题<br/>statements 为空，indicators 不新增科目<br/>数字只能带着页码从检索引用]
    rIn --> rRep --> rPage --> rStmt
  end
  subgraph calls [电话会：电话会、业绩会、transcript、纪要]
    cIn[这些词优先于研报<br/>避免业绩会点评被收成研报]
    cRep[reports：transcript<br/>会议日期取自文件名，写进 logical_key<br/>不另做发言人表]
    cPage[每一页 page_kind=transcript<br/>文字稿整篇是第 1 页<br/>说话人只保留原文里已有的]
    cStmt[不写三表行，也不进 indicators<br/>只能 search_reports<br/>引用到页]
    cIn --> cRep --> cPage --> cStmt
  end
  fInd ~~~ rIn
  rStmt ~~~ cIn
```

页文本三种扩展名不一样：

| 扩展名 | 页怎么来 | 三表 |
|---|---|---|
| `.pdf` | pdfplumber 一页一行。字数低于 `ocr.min_chars` 的页走 OCR。成功页 `is_ocr=1`，质量不合格 `is_ocr=2` | 只处理页首 8 行能对上报表标题的页。见下文 |
| `.xls` | 整张矩阵拼成第 1 页文本 | 文件名含 profit / benefit 归利润表，cash 归现金流量表，debt / balance 归资产负债表。表头里的四位年份写入行的 `year` |
| `.txt` `.md` `.html` `.htm` `.csv` | 整个文件是第 1 页，`is_ocr=0` | 不抽取。`statements` 为空 |

每一页都写两份文本：`content_orig` 是原文，供引用和保真抽检；`content` 是简体，供 FTS 和向量。`page_kind` 在写入前定好。

财报 PDF 是三表的主要来源。某一页要同时满足：

1. 页首 8 行里有一行，去掉「Consolidated」「Condensed」这类前后缀之后，能对上利润表、资产负债表、现金流量表或权益变动表的标题。附注页（行首是 Notes / APPENDIX，且后面没有独立报表标题）整页跳过。
2. 标题之下按行读取。行尾要有足够的数字列，和该页识别出的年份列对齐。行名进 `line_name_orig`，简体进 `line_name_norm`。数字原样进 `value`，不换成亿元或亿美元。单位和币种从页首约 30 行识别，海底捞常见千元、人民币，百胜常见百万美元。
3. 独立短横「–」占一个零值列，用来对齐，但不生成行项目。真没有数字的年份就留空。
4. 行名折行会拼回上一行。没有行名、整行只有数字的小计，挂最近的小节标题，并标 `is_subtotal=1`。标题之后若出现 `notes:`，后面的数字不再当报表行。
5. OCR 页上抽出的行 `statements.is_ocr=1`。这些行默认不进 `indicators`，`get_financial_statements` 默认也不返回，除非显式 `include_ocr=True`。

所以一份年报会同时有：封面、目录、正文页（`page_kind` 为 cover / toc / body），以及若干 `statement` 页和对应的三表行。后面的 `indicators` 只从这些三表行归收入、归母净利、资产、经营现金流。`exact-001` 就是这条路径：第 142 页损益表上的 42,754,687 千元写成一行 `statements`，再归到 `indicators.revenue`。

研报几乎总是只有页、没有三表。PDF 仍会逐页抽取，也会试报表标题；券商正文的页首通常对不上那套标题，于是 `statements` 为空，`indicators` 也不会因此多出一条收入。页的 `page_kind` 按封面、目录、正文来标。这些页的简体文本随后进入 FTS 和向量，所以「翻台率」能命中研报页，但不能靠 `get_indicators` 查到。`.txt` 研报则是单页正文，同样没有三表行。

电话会也是页文本，不进三表。文件名或父目录命中电话会关键词后，`report_type=transcript`，`period_type=other`。每一页的 `page_kind` 都是 `transcript`，不再标成报表页，即使某页碰巧有数字。PDF 仍会尝试三表标题匹配，对不上就不写行；文字稿（txt / md / html）整篇是第 1 页，抽取直接跳过。原文里已有的说话人保留，扫描不补「问：」「答：」。会议日期来自文件名里的第一个日期，写进 `logical_key`，不单独做一张发言表。因此电话会只能被 `search_reports` 引用到页，不能提供营业收入这类科目数字。

`pages.page_kind` 取 `cover`、`toc`、`statement`、`body`、`transcript`。电话会的页都是 `transcript`。报表页用 `is_statement_page()`，和三表同一套标题。电话会里已经写了说话人的行原样保留，扫描不编造「问：」「答：」。

评测：

- 三表 L1 / L3 维持 26/26，容差 0.0001，`golden_source: pdf`。命令是 `python -m stock_kb eval`。
- `python -m stock_kb fidelity` 读 `eval/page_fidelity.yaml`。非 OCR 页的 needle 必须出现在 `content_orig`，缺了退出码 1。OCR 缺句只列入报告。清单为空时打印 `page_fidelity: skipped (no labeled pages); not a pass`，退出码 0。这不是通过。当前清单是空的。

## 文件 metadata 做什么

扫过之后，一份原文对应 `reports` 里的一行。磁盘位置可以是 NAS 或 `data/raw`。查询、版本选举、写稿引用都读这行。NAS 和网络文件的出处 JSON 都在 `collect.meta_dir`（默认 `data/meta`）。`fetch` 先给网络文件写一份；`scan` 把两边都更新成与 `reports` 对齐的字段。

`manifest` 只服务扫描：记住某条路径上次的 sha、大小、mtime。查询和写稿读 `reports`。`sources` 表存三表页的引用定位（`《title》第N页`）。

### 目录字段

| 字段 | 作用 |
|---|---|
| `path` | 这份文件现在的位置。表内唯一。内容变了，旧路径改成带 `::superseded::` 的归档名，新行占用原路径 |
| `sha256` / `size` / `mtime` | 认是不是同一份字节。扫描用来决定 skip、重解析还是新开版本；相同 sha 的另一份标 `is_duplicate` |
| `origin` | 文件在 NAS 还是 `collect.raw_dir`。`stats` 的 `reports_by_origin` 用它。检索、MCP `list_reports`、写稿目前不读这一列 |
| `source_url` | 下载地址。编进研报和电话会的 `logical_key`，让不同 URL 互不取代。笔记引用仍写 `《title》第N页`，不写 URL |
| `retrieved_at` | 取回时间。同一 `logical_key` 选举活报告时，先比这一列，再比 `mtime` 和 `id` |
| `report_type` / `year` / `period_type` / `language` | 分类。检索可按类型、年份、语言过滤；三表默认当年年报正文；指标按公司、年、期间归集 |
| `logical_key` | 同一份文档的版本链，不含 sha。年报按公司+类型+年+期间+语言+市场；研报、电话会把 `source_url`（没有则用路径）编进去 |
| `parse_version` | 解析规则版本。字节没变但版本旧了，就地重解析 |
| `status` / `supersedes_id` / `is_duplicate` | 活文档闸门。默认检索和指标只要非重复且 `status=ok`。`superseded`、`missing`、`failed` 不进默认检索。MCP `list_reports` 仍返回全部状态 |
| `title` | 给人看的文件名，也是引用里的书名号 |

`meta_dir` 里的 `kind` 会写上，扫描不读。分类只看文件名和父目录。`--kind transcript` 的实际作用是给文件名加前缀。原文旁若还有旧的 `.source.json`，`scan` 在 `meta_dir` 没有对应文件时仍会读它，并写回 `meta_dir`。

### 页和三表上的字段

这些字段跟着正文走，不写回原文旁边。

| 字段 | 作用 |
|---|---|
| `pages.content_orig` | 原文。引用和 `fidelity` 抽检读这一列 |
| `pages.content` | 简体。FTS 和向量索引读这一列 |
| `pages.page_kind` | `cover` / `toc` / `statement` / `body` / `transcript`。电话会每一页都是 `transcript` |
| `pages.is_ocr` | `1` 是 OCR 成功页；`2` 是质量不合格，默认检索排除 |
| `statements` 的行名、原值、单位、币种、年份、页码 | 科目数字的来源。`indicators` 从这里归收入、归母净利等 |
| `statements.is_ocr` | OCR 行默认不进指标和三表查询 |

### 下游怎么用

扫描用 `sha256`、`parse_version`、`manifest` 决定读不读文件，用 `logical_key` 和 `retrieved_at` 决定哪份保持 `ok`。

查询先过滤活报告（非重复且 `status=ok`），再按公司、`year`、`report_type`、`language` 收窄。科目走 `indicators` / `statements`，短术语走页文本。

写稿里的数字跟 `title` 加页码走。审计核的是这次 `run_id` 日志里的命中，以及该页或三表行里有没有这个数。

现有库可用 `python -m stock_kb stats --json` 看 `reports_by_origin`。写作本文时是 60 份 `nas`、4 份 `collect`。

## 知识库层

这一层决定问句走哪条查询，不改页文本。科目和全文检索是两条路。收入、归母净利、资产、经营现金流走 `get_indicators` / `get_financial_statements`（CLI 是 `indicators` 与 `statements`）。这些数先查表，不先做下面的混合检索。

`indicators` 从三表行名归出上述科目。`net_profit` 是归母：港股取「本公司拥有人应占」，美国取 `Net income — Yum China Holdings`。年内溢利合计不写入这个字段。派生比率没有单独页码时，locator 为 `derived`。

全文检索的实现在 `stock_kb/vector.py` 的 `hybrid_search`，关键词侧在 `stock_kb/search.py` 的 `fts_search`。入口决定会不会走进这个函数。

### 混合检索

三条入口：

1. CLI `python -m stock_kb search` 默认 `engine=fts`。只查整页 FTS。零命中保持空列表，不自动改走向量。要融合时加 `--engine hybrid`。
2. MCP `search_reports` 默认也是 `engine=fts`。先做 FTS。只要有页就返回，问句再长也不融合。零命中才调用 `hybrid_search`。模型或向量扩展加载失败时，这次调用吞掉异常，返回空列表。
3. 显式 `engine=hybrid`（CLI 的 `--engine hybrid`，或 MCP 参数 `engine=hybrid`）直接进入 `hybrid_search`。MCP 在默认 FTS 零命中之后的那次调用，走的是同一个函数。

`stock-note` 按这三条选工具：科目用指标或三表；短术语用 `engine=fts`；问句达到下面的长度，或 FTS 已经空手，再用 `engine=hybrid`。

```mermaid
flowchart TB
  q[问句先做 normalize_query<br/>繁体转简体，标点收成空格<br/>2024年收成 2024<br/>后面的长度按这一串的字符数计算]
  entry{从哪个入口进来}
  cli[CLI search 默认 engine=fts<br/>只查整页 FTS<br/>零命中不自动升级<br/>要融合需 --engine hybrid]
  cliEnd[返回 FTS 页，或空列表<br/>locator 仍是《title》第N页]
  mcp[MCP search_reports 默认 engine=fts<br/>先查 FTS。有页就返回，长问句也不融合<br/>零命中才调用 hybrid_search<br/>向量加载失败则静默返回空列表]
  mcpEnd[有页就返回这批 FTS 页<br/>locator 仍是《title》第N页]
  hy[显式 engine=hybrid<br/>CLI --engine hybrid，或 MCP 传入 hybrid<br/>以及 MCP 零命中后的那次调用<br/>都进入 hybrid_search]
  short{归一化后长度小于 6<br/>并且这次 FTS 已经有页?}
  keep[是<br/>返回这批 FTS 页<br/>source=hybrid，hybrid_fused=false<br/>不嵌入，不做 RRF<br/>翻台率 3 字、现金流质量 5 字，有页时停在这里]
  gate[否<br/>长度达到 6<br/>或短查询的 FTS 为空]
  ftsN[FTS 侧：pages_fts 用 trigram，单位是整页<br/>3 字及以上把内容词用 AND 连起来<br/>是多少、怎么样这类虚词不参加 AND<br/>问句没有年份时，BM25 再除以每年 1.5% 的新近度，用来打散跨年重复页<br/>短于 3 字走整页 LIKE。两字中文 LIKE 为空，才查 pages_bigram_fts<br/>这一侧不拼中英别名]
  vecN[向量侧：默认模型 BAAI/bge-small-zh-v1.5<br/>sqlite-vec，距离是 L2<br/>页按约 800 字、不重叠、按行切块<br/>先在块上找近邻，再每页只留距离最小的一块<br/>嵌入前把中英和口语别名拼进问句，这些别名不进 FTS<br/>非常见词必须出现在块正文里，否则丢掉该页<br/>带了公司或年份等过滤时，块候选大约是页候选的 10 倍，否则约 5 倍]
  rrf[两侧各先取候选页：top_k 的 4 倍和 20 里较大的那个。默认 top_k=5，所以每侧最多 20 页<br/>过滤相同：活报告是非重复且 status=ok，is_ocr 小于 2<br/>可再限公司、报告类型、语言<br/>参数 year 或问句里的年份按 reports.year 硬过滤<br/>问句里任一四位年份超出该公司活报告的年份范围时，两侧都直接空<br/>然后做 RRF。名次从 1 起，默认两侧权重都是 1，k=60<br/>fusion 等于 1 除以 fts_rank 加 60，再加上 1 除以 vec_rank 加 60<br/>只出现在一侧的页只加那一侧。没有另一套分数加权，也没有 reranker<br/>先按 fusion_score 从高到低，再按向量 L2 从小到大<br/>两侧都命中的页没有把 L2 写进 score，并列时这一项按很大的距离处理<br/>截到 top_k 页，hybrid_fused=true]
  out[返回的是页，不是块<br/>locator 仍是《title》第N页<br/>融合结果带 fts_rank、vec_rank、fusion_score]

  q --> entry
  entry --> cli
  entry --> mcp
  entry --> hy
  cli ~~~ mcp
  mcp ~~~ hy
  cli --> cliEnd
  mcp --> mcpEnd
  mcp --> miss[零命中]
  miss --> hy
  hy --> short
  short --> keep
  short --> gate
  keep ~~~ gate
  gate --> ftsN
  gate --> vecN
  ftsN ~~~ vecN
  keep --> out
  ftsN --> rrf
  vecN --> rrf
  rrf --> out
```

长度门只存在于 `hybrid_search` 内部。归一化在 `search.normalize_query`：先 `to_simplified`，再把标点和括号收成空格，把 `2024年` 收成 `2024`。`翻台率` 仍是 3 字。`现金流质量` 是 5 字，所以 `search "现金流质量" --engine hybrid` 会进入这个函数，但 FTS 已有页时 `hybrid_fused` 为 false，结果就是那批关键词页。

长度达到 6，或者短查询的 FTS 为空，才同时取两侧。候选池是 `max(top_k * 4, 20)` 页。默认 `top_k=5` 时，每侧最多 20 页，融完再截回 5 页。向量索引还没建时，向量侧返回空列表，融合结果只含 FTS 页，但 `hybrid_fused` 仍是 true。这和长度门提前返回时的 false 不同。

两侧用同一组过滤。活报告条件是 `COALESCE(is_duplicate,0)=0 AND COALESCE(status,'ok')='ok'`。`is_ocr=2` 的乱码页不进结果。`year=` 是硬过滤。未传 `year` 时，问句里的四位年份同样按 `reports.year` 过滤。其中任何一个年份落到该公司活报告的最小年与最大年之外，检索直接返回空。问句没有年份时，FTS 的 BM25 `rank`（越小越好）再除以 `1 + 0.015 * (今年 - 报告年)`，每年大约 1.5%，用来把近乎并列的跨年重复页分开。

FTS 对 3 字及以上的问句把内容词 AND 起来。`是多少`、`怎么样`、`如何`、`是否` 等虚词不进 AND，年份本身也不进 AND。短于 3 字走 `pages.content LIKE`。恰好 2 个汉字且 LIKE 为空时，才查 `pages_bigram_fts`。bigram 不参与有结果时的排序。FTS 查询文本保持原句，不拼别名。

向量默认模型是 `BAAI/bge-small-zh-v1.5`，存在 sqlite-vec，距离是 L2。`pages.content` 按约 800 字、不重叠、按行打包写入 `chunks`（`embedding.chunk_size`，代码默认 `CHUNK_SIZE = 800`）。检索先取若干近邻块，再按 `page_id` 只留距离最小的一块。嵌入前 `_expand_bilingual` 会把表里的中英对和口语别名拼进问句。例如问句里有「真金白银」，嵌入文本会加上「经营现金流 现金流质量」；「翻台率」会加上 `table turnover`。这些词不写回 FTS。问句里的非常见词还要在块正文里出现，否则该页在向量侧被丢掉。

RRF 的名次从 1 开始。默认 `fts_weight = vec_weight = 1`，`rrf_k = 60`：

```text
fusion = 1 / (fts_rank + 60) + 1 / (vec_rank + 60)
```

只出现在一侧的页只加对应那一项。排序键是 `fusion_score` 从高到低，然后是向量距离 `score` 从小到大。页先被 FTS 写入、随后又被向量命中时，现有实现不会把 L2 抄进 `score`，并列时第二键按 `1e9` 处理。返回页带 `fts_rank`、`vec_rank`、`fusion_score`，`source` 为 `hybrid`，`hybrid_fused` 为 true。引用格式仍是 `《title》第N页`。

可以拿三句对照：

| 问句 | 归一化长度 | 显式 `engine=hybrid` 时 |
|---|---|---|
| 翻台率 | 3 | FTS 有页则不融合。写作本文时 CLI `--top-k 1` 命中《海底捞研报-国信-202502》第 19 页 |
| 现金流质量 | 5 | 同样先看 FTS。有页则 `hybrid_fused=false` |
| 海底捞赚到的利润有多少能变成真金白银？ | 大于 6 | 做 RRF。嵌入侧额外拼上「经营现金流 现金流质量」，FTS 仍用原句 |

评测读返回值里的 `hybrid_fused`，不按问句长度自己猜有没有融合。keyword 题里大量短术语因此实际停在 FTS。hybrid semantic 的门衡量的是真正走过融合的那部分。

索引和查询日志：`pages.content` 进 FTS5 trigram。向量按上面的 800 字写入 sqlite-vec。MCP 以只读方式打开 SQLite。查询成功后把标题和页码追加到 `data/retrieval_log.jsonl`，不写整页正文，也不写进 `stock_kb.db`。

`route` 把问句分到指标、三表、检索或无答案。带年份的检索按 `reports.year` 过滤。

评测不把各层合成一个总 Recall。现行门：

- FTS keyword Recall@5 ≥ 0.75，Neg@5 ≤ 0.65
- hybrid semantic Recall@5 ≥ 0.20，Neg@5 ≤ 0.20
- 路由 accuracy = 1.0
- 无答案 empty_rate ≥ 0.75
- 指标 12/12

另外按桶打印 Recall@5：关键词、语义、跨语言、附注、无答案。某一桶少于 5 题时只打印 n，不因此让回归失败。`exact`、`indicator`、`route` 不进检索桶。命令是 `python -m stock_kb eval` 和 `python tools/run_eval_regression.py`。

## 报告层

这一层的成品是 agent 按 `skill/stock-note` 写的扫描稿。给人打开的默认格式是同名单文件 HTML，由 `python -m stock_kb render-note` 从 Markdown 生成。Markdown 留下供改稿，`audit-report` 两份都能读。`compose-note` 仍可出材料底稿和 ECharts 图，但不是回归门。`charts.py` 继续把已引用的序列画成图。

写稿前要有 `STOCK_KB_RUN_ID`。终稿要有：

- 一行 `run_id:`
- 必备节：利润表、资产负债、现金流、分红、总结
- 文末 `《标题》第N页`
- 判断句以「判断：」起头，开篇不下结论
- 同比或累计所在行写明算式

事实清单只有一份，`eval/fact_checklist.yaml`：收入序列、归母净利、净现金构成、现金流累计五件套、分红。每一项要么有注释，要么该节写「暂无数据」。库里已经有这个数时，不能整节只有「暂无数据」又没有任何注释。库里没有时，写「暂无数据」才通过。

`audit-report` 还检查：注释里的数字能在该页 `content` / `content_orig` 或三表行里找到；每条出处出现在该 `run_id` 的日志命中，或出现在该次返回的指标、三表行里。有两个及以上四位年份的利润表、资产负债、现金流，节内要有「图」，图旁数字要来自已引用数字。

回归里，`eval/generated_notes` 没有 `*扫描*` 稿时，打印 `audit-report: skipped (no agent report); not a pass`。已有稿但没有 `run_id:`，按旧稿跳过。这两种都不记失败，也不算通过。带 `run_id:` 的稿审计失败才挡住回归。措辞和观点仍按 `eval/HUMAN_RUBRIC.md` 人工看，不挡 `run_eval_regression.py`。

## 实例

问句：海底捞 2024 年营业收入是多少？

`eval/questions.yaml` 的 `exact-001`（`golden_source: pdf`）：

- 库内原值 `42754687` 千元，也就是 42,754,687 千元，币种 CNY，在损益表。
- 正出处是《2024年报》第 142 页。摘录为 `Revenue 收入 5 42,754,687 41,453,348`。
- 难负样本是《2023年报》第 278 页，那是比较列，不能当作 2024 年营业收入的出处。
- 人读：42,754,687 千元 = 427.54687 亿元。1 亿元 = 100,000 千元。稿子若写亿元，文末注释仍要回到这个千元原值和第 142 页。

它穿过三层的方式：

1. 证据层。`scan` 读 2024 年报，先写入一行 `reports`，再把第 142 页写入 `pages.content` 和 `content_orig`。损益表行写入 `statements`，值保持 42754687，不在解析时换成亿元。`indicators.revenue` 带上 `report_id` 和 `page_no`。
2. 知识库层。这是科目。`route` 走到指标或三表，不先做全文检索。MCP 对应 `get_indicators` / `get_financial_statements`。
3. 报告层。终稿注释写《2024年报》第 142 页。这次查询的 `run_id` 日志里要有这一页。`audit-report` 核对页上或三表里有 42754687。

另一条路径是检索。翻台率是 3 字，走 `search_reports` 的默认 FTS，不进 RRF。写作本文时，`python -m stock_kb search "翻台率" --top-k 1 --json` 命中《海底捞研报-国信-202502》第 19 页。更长的经营叙述问句要显式 `engine=hybrid` 才会融合，规则见上面的「混合检索」。

## 后续再做

- RAPTOR / GraphRAG。只有某一检索桶稳定失败，并且报告必备节依赖该桶时，再单独立项。
- 不自动改写查询。日志留给以后整理零命中问句，本期不据此改问句。
