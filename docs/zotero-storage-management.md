# Zotero 库内附件与磁盘 storage 管理规范

适用：`E:\Zotero\storage\`（或任意 `ZOTERO_DATA_DIR/storage`）与 `zotero.sqlite` 中 `itemAttachments` 的对齐、去重与隔离。

## 1. 目录铁律：一附件一目录

Zotero 原生结构：

```text
storage/<PDF附件key>/论文.pdf      ← 只放该 PDF 附件
storage/<DOCX附件key>/中文译名.docx ← 只放该 DOCX 附件
```

- **禁止**把 PDF 与译文 DOCX 放进同一个 `storage/<key>/`
- 同一文献下的 PDF 与 DOCX 是**两个附件**、两个 key、两个目录
- 目录名 = 附件 key；`itemAttachments.path = storage:<文件名>`

混放检测：

```text
某目录下同时存在 *.pdf 与 *.docx  → 违规，必须拆分
```

拆分做法：

1. 若目录是 PDF 附件目录，把 DOCX 移出  
2. 若库中已有 DOCX 附件 → 移到 `storage/<docx-key>/`  
3. 若库中没有 → 新建 key 目录，并登记为父条目下的 DOCX 附件（title 建议 `[docx]中文译名`）

## 2. 同一文献只保留一份译文

- 同一父条目下多个内容相同/相近的 DOCX → **只留 1 份**
- 保留规则：汉字更多者优先；其次更新、文件名更规范者
- 其余**移入隔离区**，不要直接 rm

精确重复：MD5 相同只留一份。

## 3. 隔离区（quarantine）

清理时**先隔离、不硬删**。建议目录（工作区下，不在 `storage` 内）：

| 目录 | 用途 |
|---|---|
| `quarantine_dup_docx/` | 重复译文、MD5 相同拷贝 |
| `quarantine_docx_not_fulltext/` | 未达标旧译文（已重译后的旧稿） |
| `quarantine_docx_bak/` | 覆盖前的 `*.bak*` |
| `quarantine_orphan_docx/` | 磁盘有、库中无记录的文件 |
| `quarantine_unaligned/` | path 与文件名不一致时的暂存 |

确认无用后可整夹删除；要恢复则拷回对应 `storage/<key>/`。

**备份文件 `*bak*` 不要留在 storage 正式目录**，否则会干扰附件扫描与同步。

## 4. 库与磁盘对齐检查

对每个 `itemAttachments` 行：

1. `path` 解析出的文件名应等于 `storage/<item.key>/` 下实际主文件名  
2. contentType 与扩展名一致（pdf ↔ `.pdf`，word ↔ `.docx`）  
3. 不一致则改 `path`，或把文件改名到记录的文件名  
4. 库有记录但磁盘无文件 → 记入缺失清单；优先从隔离区按文件名找回  
5. 磁盘有文件但目录 key 不在 `items` 表 → 孤儿，移入 `quarantine_orphan_docx/`

写 `zotero.sqlite` 前必须**完全退出 Zotero**，并先备份 `zotero.sqlite.bak_before_*`。

## 5. 建议巡检顺序

1. 混放检测（pdf+docx 同目录）→ 拆分  
2. MD5 精确去重 → 每内容留 1  
3. 同父多 DOCX 去重 → 每文献留 1  
4. `*bak*` 移出 storage  
5. path 对齐 + 孤儿回收  
6. 缺失文件从隔离区恢复  

## 6. 与翻译挂接的关系

- 翻译产出 `译文.docx` 后，**登记为新附件 key 目录**，不要覆盖 PDF 目录里的文件  
- `fill_existing`：只更新既有 DOCX 附件的 `path` 与内容，仍保持「一附件一目录」  
- 验收译文时，以该 DOCX 附件的 `storage/<key>/` 文件为准  

相关：`skills/translate-import/README.md`（翻译验收）、`docs/zotero-datadir-migration.md`（数据目录迁移）。
