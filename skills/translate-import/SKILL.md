---
name: zotero-translate
description: 将 Zotero 库中的英文 PDF 学术论文翻译为规范中文 DOCX 并挂回对应条目。适用于布里渊/瑞利散射/光纤传感等文献库的批量中文化。触发词：翻译 Zotero PDF、中文译文入库、PDF to DOCX 中文、批量翻译文献。
---

# Zotero 文献中文翻译 Skill

## 目标

用户要求把 Zotero 里的英文论文变成中文 DOCX，并在 Zotero 条目下能看到译文附件时使用本技能。

## 翻译方案（唯一标准：全文精译 · 逐句对应）

**只提供全文精译方案。**

- **与英文原文逐句对应**：正文按原文顺序逐句翻译，不缩写、不扩写、不重排论证
- **不设字数上下限**：篇幅由原文决定，禁止为凑字数而注水，也禁止因字数阈值而压缩
- **不编造**：不添加原文没有的数据、公式、结论或图表信息
- 公式用 `$...$` 保留；术语首现可括注英文
- 图表标题译中文；坐标轴/图例数值保持原样
- 参考文献保留英文条目（可按原文顺序列出）
- 章节标题跟随原文结构（如 Abstract / I. Introduction / II. Experimental System / III. Results / IV. Conclusions / References 等），可译为「摘要 / 1 引言 / …」，但不得合并、删减或改写章节内容关系

**禁止**：摘要式短稿、结构化改写、按固定模板扩写、A/B/C 分档、任何最小/最大字数门槛。

## 前置检查

1. 确认 Python 3.12+，已安装 `pymupdf` 或 `pypdf`、`python-docx`
2. Windows：使用 `python -X utf8`，设置 `PYTHONUTF8=1`
3. 若需写 `zotero.sqlite`：**确认 Zotero 已完全退出**
4. 确认路径：
   - Zotero 数据目录（含 `storage/` 与 `zotero.sqlite`）
   - 任务表 `zotero_tasks.json`（可选，用于批量）
   - 台账 `status_oc.json`（可选）

## 工作流

### 单篇

1. `extract_pdf_text.py <pdf> <workdir>/images > extract.json`
2. 读 `fulltext.txt`，写出 `parts/01.json`（**逐句全文精译**，对应英文原文）
3. `build_docx.py <workdir>/parts <out.docx>`
4. `verify_docx.py <out.docx>`，要求 `ok=true`（仅校验可解析与基本完整性，**不以字数判定**）
5. 若用户要求入库：运行 `register_zotero_docx.py`（先退出 Zotero）

### 批量

1. 维护 `zotero_tasks.json`：`itemID / mode / ztitle / pdf / docx / folder`
2. 运行 `full_v3_pipeline.py [N]` 分批处理（按逐句全文精译产出）
3. `update_status.py` 刷新台账（若用户环境有）
4. 全量审计：每个任务的 `docx` 路径存在且校验通过（`ok=true`）

## 译文组织

按原文结构逐句翻译即可。常见组织（跟随原文，非强制模板）：

- 摘要
- 正文各章节（与英文原文一一对应）
- 参考文献（保留英文）

关键约束是**逐句对应英文原文**，不是固定章节字数或固定总字数。

## Zotero 挂接要点

- 原生规则：**一个附件一个 storage 目录**；PDF 与译文 DOCX **不得同目录**
- `create_new`：译文登记为**新的附件 key 目录**，不要塞进 PDF 的 `storage/<pdf-key>/`
- `fill_existing`：只更新既有 DOCX 附件的 `path` 与文件内容
- 登记后需有 `itemAttachments.path = storage:<文件名>` 与 title 字段（建议 `[docx]中文译名`）
- 同一文献只保留 **1 份** 译文 DOCX；重复/旧稿移入隔离区，勿硬删
- 详见 `docs/zotero-storage-management.md` 与 `scripts/manage_zotero_storage.py`（去重、隔离区、path 对齐、孤儿清理、混放拆分）

## 禁止事项

- Zotero 运行时写 `zotero.sqlite`
- 删除用户数据前不备份
- 把受版权 PDF 上传到公网
- 用字数阈值判定译文是否合格（合格 = 与英文原文逐句对应且 `verify` 通过）

## 翻译验收标准

**唯一合格判定**：与英文原文**逐句对应** + `verify_docx.py` 返回 `ok=true`。  
**禁止**用最小/最大字数判定是否合格。

### 合格

**内容对应**
- [ ] 按原文顺序**逐句翻译**，无缩写、无扩写、无重排论证、无漏译关键句
- [ ] **不设字数上下限**（篇幅由原文决定；不注水、不因阈值压缩）
- [ ] **不编造**数据、公式、结论或图表信息
- [ ] 结构跟随原文章节，不合并、不删减论证关系
- [ ] 体例随原文类型：社论/快讯无编号章节，不硬套「1 引言 / 5 应用与展望」模板
- [ ] 致谢、基金、利益冲突、数据可用性、作者贡献若在原文则译；原文没有的节不编造
- [ ] 数值以原文为准；摘要与结论不一致处照译，不擅自统一

**体例**
- [ ] 公式用 `$...$`，式号随原文；OCR 散式按量纲自洽还原，不改物理含义
- [ ] **检查公式（带编号）是否完整**：原文式 (1)–(n) 不得缺号、缺式、缺变量/系数；式号与正文引用一一对应
- [ ] **检查图像是否完整**：原文图 1–n 不得缺图或缺图注；图序连续，图注内容与原图对应（坐标轴/图例数值原样）
- [ ] 引文编号 `[n]` 保留；OCR 误识可按上下文校正（如 `[58]`→`[5–8]`）
- [ ] 图/表标题译中文；坐标轴/图例数值保持原样
- [ ] 参考文献保留英文条目
- [ ] 术语首现可括注英文

**源文本预处理（译前）**
- [ ] 去掉页眉页脚/页码/水印，不译入正文
- [ ] 双版本叠印（`FOR PEER REVIEW` + 正式版）先去重再译
- [ ] PDF 断词（`U+FFFE`、软连字符）先拼合：复合词保留 `-`，词内断开直接拼接
- [ ] 跨页断句先拼成完整句再译；图注插入句中时，图注独立成 `caption`，正文整句对应

**技术**
- [ ] 写 DOCX 前剔除非 XML 字符（`U+FFFE`、控制符），否则 `python-docx` 会报错
- [ ] 长文分 `parts/01.json`… 时切片边界不截断句子；续句只译一次、分片间不重复
- [ ] 块类型统一：`title` / `subtitle` / `heading` / `para` / `caption`|`figure` / `formula`|`equation` / `table`；首篇才带 `title_cn`
- [ ] DOCX 可解析（`verify_docx.py` 的 `ok=true`，仅查完整性，**不以字数判定**）
- [ ] 中文标题正确
- [ ] 台账 `status_oc.json` 已更新
- [ ] （若入库）Zotero 条目下可见译文附件

### 不合格

- 摘要式短稿或大幅缩写
- 结构化改写、按固定模板扩写（如自造「5 应用与展望」等原文没有的章节）
- 添加原文没有的数据/公式/结论
- 公式（带编号）缺失、式号跳号、或式中变量/系数不完整
- 图像缺失、图序跳号、或图注与原图不对应
- 用最小/最大字数门槛（含「≥3000 字」等）判定或凑稿
- A/B/C 分档产物（摘要整理、结构化精译等）
- 页眉页脚/水印/双版本重复段落进入译文
- 切片边界截断半句、或分片间重复翻译同一句

## 路径配置

优先使用环境变量 `ZOTERO_DATA_DIR` / `ZOTERO_WORK_BASE` / `ZOTERO_PYTHON`，或 `translate/config.json`。
用 `python scripts/print_paths.py` 确认解析结果后再跑写库脚本。

本 skill 位于 `skills/translate-import/`。
