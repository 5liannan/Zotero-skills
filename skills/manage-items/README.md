# ③ Zotero条目与附件管理

把 Zotero 库里的**条目**和**附件**整理干净：标题统一中文、附件按规范命名、PDF 与译文分目录、译文补齐并挂载。

## 这套 Skill 解决什么

| 问题 | 表现 | 本 Skill 的处理 |
|---|---|---|
| 标题中英混杂 | 有的中文有的英文，检索割裂 | `retitle_zh.py` 统一为中文译名，英文存 `Original Title:` |
| 附件标题没前缀 | 分不清是 PDF 还是译文 | 统一 `[pdf]` / `[docx]` |
| 文件名乱 | `document(3).pdf`、`Fokoua 等 - n.d. - ...` | 按 `作者等 - 年 - 标题` 重命名 |
| PDF 与 DOCX 同目录 | 违反「一附件一目录」，易误删 | `split_storage.py` 拆到各自目录 |
| 译文没挂上 | 磁盘有 DOCX，Zotero 里看不到 | `link_docx.py` 挂载 |
| 记录与磁盘对不上 | 点了附件打不开 | `verify.py` 校验 |
| 日期只到年份 | Zotero 只显示 2024 | `fix_dates.py` 按 DOI/PDF 补全 |
| 日期格式不统一 | 有的 `2024-04-30`，有的 `2024-04-30 2024-04-30` | `fix_dates.py --normalize` |
| 附件标题是 `[pdf]PDF` | 原标题是占位词 | 脚本自动回退到文件名 |
| 译文要一篇篇补 | 需要可控节奏 | `batch.py` 分批 + 台账 |

## 命名规范

| 类型 | 标题栏 | 文件名 |
|---|---|---|
| PDF | `[pdf]` + 英文标题 | `<姓>等 - <年> - <英文标题>.pdf` |
| DOCX | `[docx]` + 中文标题 | `<姓>等 - <年> - <中文标题>.docx` |

```text
[pdf]Brillouin optical time-domain analysis with deep learning
Zhang 等 - 2023 - Brillouin optical time-domain analysis with deep learning.pdf

[docx]基于深度学习的布里渊光时域分析
Zhang 等 - 2023 - 基于深度学习的布里渊光时域分析.docx
```

## 快速开始

```bash
cd skills/manage-items
cp config.example.json config.json     # 改成你的 Zotero 数据目录

python scripts/audit.py                # 1. 看现状（只读）
python scripts/retitle_zh.py --map zh.json --apply    # 2. 标题中文化
python scripts/split_storage.py --apply                # 3. PDF/DOCX 分目录
python scripts/rename_attachments.py --apply           # 4. 附件改名
python scripts/link_docx.py --dir "E:/翻译稿" --apply   # 5. 挂载译文
python scripts/fix_dates.py --normalize --apply        # 6. 日期补全并统一格式
python scripts/verify.py --expect-docx                 # 7. 校验

# 译文量大时用批次调度
python scripts/batch.py --status
python scripts/batch.py --next 3 --extract
python scripts/batch.py --done <itemID> --docx <docx路径>
```

除 `audit.py` / `verify.py` 外，所有脚本**默认 dry-run**，加 `--apply` 才写库。

## 前置条件

- Python 3.10+，仅标准库，无需第三方依赖
- **Zotero 必须完全退出**（写库时）
- 建议先备份：脚本 `--apply` 时会自动生成 `zotero.sqlite.bak_before_*`

## 在真实库上验证过的效果

一次完整整理（935 条文献 / 1184 个附件）：

| 动作 | 结果 |
|---|---|
| 标题中文化 | 20 条英文标题 → 中文，英文原名存入 `Original Title:` |
| 附件标题统一 | 640 个附件改名，前缀不合规 **241 → 0** |
| 日期补全 | 完整日期 333 → **868**（`YYYY-MM-DD`） |
| 译文挂载 | 单篇 14,312 字，13 图 + 3 个 Word 公式对象 |

## 与 ①② 的关系

```text
① search-import  →  条目入库 + PDF
② translate-import  →  中文 DOCX
③ manage-items  →  统一命名、分目录、补齐挂载、校验
```

## 配置

`config.json`（可被环境变量覆盖）：

| 键 | 含义 | 环境变量 |
|---|---|---|
| `zotero_data_dir` | 数据目录（含 `storage/`） | `ZOTERO_DATA_DIR` |
| `pdf_title_prefix` | PDF 标题前缀，默认 `[pdf]` | `ZOTERO_PDF_PREFIX` |
| `docx_title_prefix` | DOCX 标题前缀，默认 `[docx]` | `ZOTERO_DOCX_PREFIX` |
| `pdf_filename` | PDF 文件名模板 | `ZOTERO_PDF_PATTERN` |
| `docx_filename` | DOCX 文件名模板 | `ZOTERO_DOCX_PATTERN` |

模板占位符：`{author}` `{year}` `{title_en}` `{title_zh}` `{ext}`。
若希望 DOCX 只保留中文标题，把 `docx_filename` 改成 `"{title_zh}.docx"`。
