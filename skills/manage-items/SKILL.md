---
name: zotero-manage-items
description: 管理 Zotero 条目与附件——把条目标题统一为中文译名，按 [pdf]/[docx] 前缀与「作者等 - 年 - 标题」规范重命名附件，PDF 与译文 DOCX 分目录存放（一附件一目录），并把磁盘上的译文 DOCX 补齐挂在对应条目下、校验库内记录与 storage 一致。触发词：条目标题中文化、附件重命名、storage 整理、PDF 与 DOCX 分目录、补齐译文、附件对齐、查缺附件。
---

# Zotero条目与附件管理（Skill ③）

## 目标

当用户提出以下任一需求时使用本技能：

- 把条目**标题统一为中文译名**
- 规范**附件标题栏与文件名**（`[pdf]` / `[docx]` 前缀）
- **PDF 与译文 DOCX 分目录**存放，符合 Zotero「一附件一目录」
- 把磁盘上已有的**译文 DOCX 补齐并挂到条目下**
- 核对**库内附件记录**与 `storage/` 磁盘文件是否一致

## 命名规范

| 类型 | 标题栏（Zotero title 字段） | 文件名（磁盘） |
|---|---|---|
| PDF | `[pdf]` + 英文标题 | `<第一作者姓>等 - <年> - <英文标题>.pdf` |
| DOCX | `[docx]` + 中文标题 | `<第一作者姓>等 - <年> - <中文标题>.docx` |

示例：

```text
PDF  标题栏: [pdf]Brillouin optical time-domain analysis with deep learning
PDF  文件名: Zhang 等 - 2023 - Brillouin optical time-domain analysis with deep learning.pdf
DOCX 标题栏: [docx]基于深度学习的布里渊光时域分析
DOCX 文件名: Zhang 等 - 2023 - 基于深度学习的布里渊光时域分析.docx
```

> 用户原始需求里 PDF 那一行的示例写成了 `[docx]…` 和 `.docx`，属于笔误；**以表格为准**。
> 模板可在 `config.json` 改：`pdf_filename` / `docx_filename`，占位符 `{author} {year} {title_en} {title_zh} {ext}`；
> 若希望 DOCX 只保留中文标题，把模板改成 `{title_zh}.docx` 即可。

## 数据结构

Zotero 里是**父条目 + 子附件**两级：

```text
父条目（journalArticle / conferencePaper …）
├── 附件 A：PDF      linkMode=0  path=storage:<文件名>  → storage/<附件A的key>/<文件名>.pdf
└── 附件 B：译文 DOCX linkMode=0  path=storage:<文件名>  → storage/<附件B的key>/<文件名>.docx
```

关键点：

- **一个附件一个目录**，目录名是**附件自己的 key**（8 位），不是父条目的 key。
- PDF 与 DOCX 是两个附件、两个目录，**不放在一起**。
- `itemAttachments.path` 用 `storage:<文件名>`；解析时拼 `storage/<附件key>/`。
- 迁移目录后必须同时改 `items.key`（附件行）与 `itemAttachments.path`。

## 作用范围与命名取舍

- **所有脚本都支持 `--collection <collectionID>`**：只治理指定分类，不碰库内其它条目
  （不加则整库处理，条目多时务必先试 `audit.py --collection <id>`）。
- 配置 `strip_title_tags`（默认 false）开启后，生成**文件名 / 附件标题**时剥掉
  `title_tag_pattern` 匹配的分类标签（如 `【BOTDA】【SR提高算法】`），
  **条目标题本身不动**——分类标签属于检索习惯，不属于标题。

## 工作流

### 0. 前置（写库前必做）

1. **完全退出 Zotero**（托盘也退出），否则 `zotero.sqlite` 写入会被锁或损坏。
2. 备份：`zotero.sqlite` → `zotero.sqlite.bak_before_<tag>_<时间戳>`。
3. 所有脚本默认 **dry-run**，确认输出无误后再加 `--apply`。
4. 写完跑 `PRAGMA foreign_key_check` 与 `PRAGMA integrity_check`。

### 1. 审计现状

```bash
python scripts/audit.py
```

输出：标题非中文数、附件总数、前缀不合规数、磁盘缺文件数、共用目录条目数、有 PDF 无 DOCX 数，并落 `outputs/audit.json` 与 `outputs/audit.csv`。

### 2. 标题中文化

```bash
python scripts/retitle_zh.py --map zh.json          # dry-run
python scripts/retitle_zh.py --map zh.json --apply
```

`zh.json` 由 agent 产出：`{"itemID": "中文译名"}`。已是中文的标题默认跳过，`--force` 强制覆盖。
英文原名应在条目「其他 / Extra」字段保留 `Original Title: <英文>`，供 PDF 命名与回溯。

### 3. 拆分共用目录

```bash
python scripts/split_storage.py --apply
```

把同一 `storage/<key>/` 里的多个文件按附件逐个迁到各自新目录，并改写 key 与 path。

### 4. 重命名附件

```bash
python scripts/rename_attachments.py --titles-only   # 只改标题栏（推荐先做）
python scripts/rename_attachments.py --apply         # 标题栏 + 磁盘文件名
```

`--titles-only` 只动 Zotero 的 title 字段，不碰磁盘文件——批量大、只想让列表好看时先跑这一步。

标题来源的**回退链**（找不到就往下走，绝不臆造）：

| 类型 | 优先 | 回退 1 | 回退 2 |
|---|---|---|---|
| PDF | `Original Title:`（英文原名） | 现有附件标题 | 原文件名（去掉 `storage:` 与扩展名） |
| DOCX | 条目中文标题 | 英文原名 | 现有附件标题 / 原文件名 |

占位标题（`PDF`、`Full Text`、`untitled`、`全文` 等）一律视为空，按上面回退。

### 5. 补齐译文 DOCX

```bash
python scripts/link_docx.py --dir "E:/翻译稿" --apply
```

按中文标题匹配父条目，复制进该附件独占的新目录，标题栏写 `[docx]中文标题`。
若译文尚未生成，先用 ② `translate-import` 生成 DOCX，再回到本步骤挂载。

### 5.5 分批调度（译文量大时）

```bash
python scripts/batch.py --status        # 还有多少篇缺译文
python scripts/batch.py --next 3 --extract   # 取下一批并抽取正文
python scripts/batch.py --done 10642 --docx <路径>   # 记为已挂载
```

台账落在 `outputs/ledger.csv`。会自动跳过中文原版（PDF 文件名含中文且无 `Original Title`）。

### 5.6 补全日期

```bash
python scripts/fix_dates.py            # 预览
python scripts/fix_dates.py --apply
```

**日期统一写单段 ISO：`YYYY-MM-DD`（如 `2001-03-05`），不写 Zotero 的双段格式。**

来源优先级：OpenAlex `publication_date` → Crossref（补到日）→ PDF 前两页的 Published / Accepted / 期号。
只到月时写 `YYYY-MM`，只到年时写 `YYYY`；新年份与已有年份不一致则跳过，避免错配。
`--normalize` 会把历史上 `2024-04-30 2024-04-30`、`2019-00-00 2019` 这类写法统一成单段。

### 6. 校验

```bash
python scripts/verify.py --expect-docx
```

全部通过输出 `PASS`，退出码 0；否则列出问题条目并返回 1。

## 脚本清单

| 脚本 | 作用 | 写库 |
|---|---|---|
| `scripts/audit.py` | 只读审计，出 JSON/CSV 报告 | 否 |
| `scripts/retitle_zh.py` | 标题改中文（按映射表） | 是 |
| `scripts/split_storage.py` | 共用目录拆分 | 是 |
| `scripts/rename_attachments.py` | 附件标题栏 + 文件名规范化 | 是 |
| `scripts/link_docx.py` | 译文 DOCX 挂载 | 是 |
| `scripts/verify.py` | 规范与一致性校验 | 否 |
| `scripts/batch.py` | 分批调度：挑下一批待译、记台账、标完成 | 否 |
| `scripts/fix_dates.py` | 补全日期：DOI→OpenAlex，无 DOI 回退解析 PDF 首页 | 是 |
| `scripts/zoterodb.py` | 公共库（字段/类型按名解析、key 生成、附件搬迁） | — |
| `scripts/config.py` | 路径与命名模板配置 | — |

## 实战要点（按真实库验证过）

- **先标题、后文件名**。标题栏改动只写 DB，可回滚；文件名改动要动磁盘 + 改 `path`，量级大时分开做，别一次梭哈。
- **批量前先看 dry-run 的前 20 条**。`rename_attachments.py` 会打印「现值 → 目标值」，错配一眼能看出来。
- **无英文原名的老文献**（没有 `Original Title:`）占多数时，PDF 标题只能沿用现有标题或文件名——这时不要强行翻译成中文，否则 PDF 标题会变成中文，和「PDF 用英文名」的规范冲突。
- **只读连接遇到 Zotero 正在运行**会拿不到锁，`connect(readonly=True)` 会自动把 `sqlite + wal` 快照到临时目录再读；因此审计类脚本可以边开 Zotero 边跑。
- **字段名大小写**：`zoterodb` 内部已按小写建索引，`get("doi")` 与 `get("DOI")` 等价；外部脚本直接写 SQL 时仍要用 `fields.fieldName = 'DOI'`。
- **年份冲突不要硬改**。补日期时若新数据年份与已有年份不一致，多半是「在线发表年 vs 卷期年」或元数据错误，交人工判断，脚本只跳过。
- **中文原版不算「缺译文」**。统计待译数量时要排除 PDF 文件名含中文且无 `Original Title` 的条目，否则数字会虚高（实测 274 → 148）。

## 验收标准

跑完一轮后，下面几条应全部成立：

```bash
python scripts/verify.py --expect-docx    # 输出 PASS，退出码 0
```

1. 标题缺前缀 = 0
2. 磁盘缺文件 = 0（历史遗留的例外要单独记账）
3. 共用目录 = 0
4. 日期格式统一为 `YYYY-MM-DD`（允许 `YYYY-MM` / `YYYY` 的部分日期）
5. 每条文献至多 1 份译文 DOCX

## 禁止事项

- **Zotero 运行中写库**。写之前必须确认进程已退出。
- 直接 `rm` 附件目录来「整理」——会破坏 `storage` 与 DB 的对应关系，必须走 `split_storage.py`。
- 把 PDF 和 DOCX 塞回同一个 `storage/<key>/`。
- 重命名时只改 DB 不改磁盘（或反之），两边必须同步。

## 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 打开 PDF 提示找不到文件 | 只改了 `path` 没搬文件，或只搬文件没改 `path` | 跑 `verify.py` 定位，再 `rename_attachments.py --apply` 修正 |
| 附件显示「无标题」 | 只写了 `path` 没写 title 字段 | 补 `[pdf]`/`[docx]` 前缀标题 |
| 两个附件串到同一目录 | 历史导入把译文放进了 PDF 目录 | `split_storage.py` |
| 改名后 Zotero 里看不到新名字 | 只改了磁盘文件名 | 必须同时更新 `itemAttachments.path` |
| 中文标题下 PDF 命名成了中文 | 取了 `title` 而非 `Original Title` | 先补 Extra 里的英文原名再重命名 |
| 附件标题变成 `[pdf]PDF` | 原标题是占位词 | 脚本已把 `PDF`/`Full Text` 视为空，按回退链取真名 |
| 日期显示成 `2024-04-30 2024-04-30` | 写了 Zotero 的双段内部格式 | `fix_dates.py --normalize` 归一为单段 |
| 待译数量比实际多一倍 | 把中文原版也算进去了 | 排除「PDF 文件名含中文且无 Original Title」的条目 |
