# Zotero 库内附件与磁盘 storage 管理规范

适用：`$ZOTERO_DATA_DIR/storage/`（如 `E:\Zotero\storage\`）与 `zotero.sqlite` 中 `itemAttachments` 的对齐、去重、拆分与隔离。

目标状态：

| 检查项 | 合格标准 |
|---|---|
| 目录纯净 | 任意 `storage/<key>/` **不同时**含 `*.pdf` 与 `*.docx` |
| 译文唯一 | 同一父条目下 **恰好 1 份** DOCX 译文附件 |
| 内容唯一 | 无 MD5 相同的重复 DOCX |
| path 对齐 | `itemAttachments.path = storage:<目录内实际主文件名>` |
| 类型一致 | contentType 与扩展名一致（pdf ↔ `.pdf`，word ↔ `.docx`） |
| 无孤儿 | 磁盘文件所属 key 必须在 `items` 表中 |
| 无 bak | storage 正式目录内无 `*bak*` / `*.bak` |
| 缺失可解释 | 库有记录但磁盘无文件的条目进入缺失清单，不静默丢弃 |

---

## 1. 目录铁律：一附件一目录

Zotero 原生结构：

```text
storage/<PDF附件key>/论文.pdf       ← 只放该 PDF 附件
storage/<DOCX附件key>/中文译名.docx ← 只放该 DOCX 附件
```

- **禁止**把 PDF 与译文 DOCX 放进同一个 `storage/<key>/`
- 同一文献下的 PDF 与 DOCX 是**两个附件**、两个 key、两个目录
- 目录名 = 附件 key（8 位，字符集 `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`）
- `itemAttachments.path = storage:<文件名>`（不是绝对路径）

混放检测：

```text
某目录下同时存在 *.pdf 与 *.docx  → 违规，必须拆分
```

拆分做法（`scripts/manage_zotero_storage.py split`）：

1. 若目录是 PDF 附件目录，把 DOCX 移出
2. 若库中已有同父 DOCX 附件 → 移到 `storage/<docx-key>/`
3. 若库中没有 → 新建 key 目录，并登记为父条目下的 DOCX 附件（title 建议 `[docx]中文译名` 或 `【xxx】中文译名`）

---

## 2. 附件命名与标题

| 类型 | 文件名建议 | 附件 title 建议 |
|---|---|---|
| PDF 原文 | `姓 等 - 年 - 英文标题.pdf` 或保留原文件名 | 跟随父条目或英文题名 |
| DOCX 译文 | `中文译名.docx` | `[docx]中文译名` / `【xxx】中文译名` |

- 父条目 title 规范（库级）：`【xxx】中文译名`（保留既有【xxx】集合标记）
- 文件名可含空格与中文；**不要**把 PDF/DOCX 塞进对方命名模式
- `fill_existing` 只更新既有 DOCX 的 `path` 与内容，不新建 key
- `create_new` 必须**新附件 key 目录**，不要覆盖 PDF 目录里的文件

---

## 3. 同一文献只保留一份译文

- 同一父条目下多个 DOCX → **只留 1 份**
- 保留优先级：
  1. 正文汉字（CJK）更多者优先（更完整）
  2. 其次更新、文件名更规范者
  3. MD5 完全相同时，文件名非 `translation.docx` 且更长者优先
- 其余**移入隔离区**，不要直接 `rm`

精确重复：MD5 相同只留一份（`dedup-hash`）。

批量登记后必须跑 `dedup-parent`，否则同一文献会挂多份译文。

---

## 4. 隔离区（quarantine）

清理时**先隔离、不硬删**。建议目录（工作区下，**不在** `storage` 内）：

| 目录 | 用途 |
|---|---|
| `quarantine_dup_docx/` | 重复译文、MD5 相同拷贝、同父多余 DOCX |
| `quarantine_docx_not_fulltext/` | 未达标旧译文（已重译后的旧稿） |
| `quarantine_docx_bak/` | 覆盖前的 `*.bak*` |
| `quarantine_orphan_docx/` | 磁盘有、库中无记录的文件 |
| `quarantine_unaligned/` | path 与文件名不一致时的暂存 / 未对齐回收 |

规则：

- 确认无用后可整夹删除（需用户确认）
- 要恢复则拷回对应 `storage/<key>/`，并保证 `path = storage:<文件名>`
- **备份文件 `*bak*` 不要留在 storage 正式目录**，否则干扰附件扫描与同步
- 隔离区是可回收站，不是备份策略；重要数据仍应另有备份

---

## 5. 库与磁盘对齐（align）

对每个 `itemAttachments` 行：

1. `path` 解析出的文件名应等于 `storage/<item.key>/` 下实际主文件名
2. contentType 与扩展名一致（pdf ↔ `.pdf`，word ↔ `.docx`）
3. 不一致则改 `path`，或把文件改名到记录的文件名
4. 库有记录但磁盘无文件 → 记入 `missing` 清单；优先从隔离区按文件名找回（`restore`）
5. 磁盘有文件但目录 key 不在 `items` 表 → 孤儿，移入 `quarantine_orphan_*`（`orphans`）

写 `zotero.sqlite` 前必须：

1. **完全退出 Zotero**（进程不得占用 DB）
2. 先备份 `zotero.sqlite.bak_before_*`
3. 写完后抽查：打开 Zotero 确认附件可双击打开

只读检查可用 `mode=ro` 连接，无需退出 Zotero。

---

## 6. 统一工具用法

脚本位置：`scripts/manage_zotero_storage.py`

环境变量（或 CLI 参数）：

| 变量 | 含义 | 默认 |
|---|---|---|
| `ZOTERO_DATA_DIR` | Zotero 数据目录 | — |
| `ZOTERO_WORK_BASE` | 隔离区/报告输出工作区 | 当前目录 |
| `ZOTERO_SQLITE` | 覆盖 sqlite 路径 | `$ZOTERO_DATA_DIR/zotero.sqlite` |
| `ZOTERO_STORAGE` | 覆盖 storage 路径 | `$ZOTERO_DATA_DIR/storage` |

```bash
export ZOTERO_DATA_DIR=E:/Zotero
export ZOTERO_WORK_BASE=C:/path/to/work

# 0) 只读体检（混放 / 多译文 / path / 孤儿 / bak），退出码 0=全部合格
python scripts/manage_zotero_storage.py check

# 1) 拆分 PDF+DOCX 同目录（需退出 Zotero）
python scripts/manage_zotero_storage.py split

# 2) MD5 精确去重（只隔离文件，不改 DB）
python scripts/manage_zotero_storage.py dedup-hash

# 3) 同父多 DOCX 只留 1 份（隔离文件 + 删多余附件记录）
python scripts/manage_zotero_storage.py dedup-parent

# 4) 移出 *bak* 到隔离区
python scripts/manage_zotero_storage.py clean-bak

# 5) path 对齐 + 孤儿回收（需退出 Zotero）
python scripts/manage_zotero_storage.py align

# 6) 从隔离区按文件名恢复缺失附件
python scripts/manage_zotero_storage.py restore

# 一次跑完整备检顺序（除 restore 需人工看缺失清单）
python scripts/manage_zotero_storage.py doctor
```

每步会在 `$ZOTERO_WORK_BASE` 写出 `<step>_result.json` 报告。

---

## 7. 建议巡检顺序

1. **check** 混放 / 多译文 / path / 孤儿 / bak → 看清问题
2. **split** 拆分 pdf+docx 同目录
3. **dedup-hash** MD5 精确去重
4. **dedup-parent** 同父多 DOCX → 每文献留 1
5. **clean-bak** `*bak*` 移出 storage
6. **align** path 对齐 + 孤儿回收
7. **restore** 缺失文件从隔离区恢复；仍缺失则导出清单，等用户补文件或删条目
8. 打开 Zotero 抽查附件可打开、条目下 PDF/DOCX 分列

本库一次完整整理的参考量级（约 1400+ 附件）：

| 步骤 | 典型结果 |
|---|---|
| 混放拆分 | 277 个混合目录 → 0 |
| MD5 去重 | 54 份相同内容隔离 |
| 同父去重 | 992 份多余 DOCX 附件移除（每父留 1） |
| bak/旧稿隔离 | 367+ 份移出 storage |
| path 对齐 | 220 条 path 修正 |
| 隔离区找回 | 21 份恢复 |
| 仍缺失 | 29 份（多为 PDF，磁盘本就没有） |

---

## 8. 与翻译挂接的关系

- 翻译产出 `译文.docx` 后，**登记为新附件 key 目录**，不要覆盖 PDF 目录里的文件
- `fill_existing`：只更新既有 DOCX 附件的 `path` 与内容，仍保持「一附件一目录」
- 批量注册后必跑 `dedup-parent`（历史批量登记会挂出重复 DOCX）
- 验收译文时，以该 DOCX 附件的 `storage/<key>/` 文件为准
- 译文质量标准见 `skills/translate-import/SKILL.md`（全文精译 · 逐句对应 · 公式图像完整）

---

## 9. 禁止事项

- Zotero 运行时写 `zotero.sqlite`
- 不备份就改库 / 不隔离就硬删用户文件
- 把 PDF 与 DOCX 塞进同一 `storage/<key>/`
- 同一文献挂多份译文而不清理
- 把受版权 PDF 上传到公网
- 在 storage 正式目录留下 `*bak*` 中间稿

相关：

- `skills/translate-import/README.md` — 翻译验收
- `docs/zotero-datadir-migration.md` — 数据目录迁移
- `scripts/manage_zotero_storage.py` — 本规范的可执行工具
