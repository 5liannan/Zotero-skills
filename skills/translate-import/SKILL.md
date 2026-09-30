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

> **严禁模板化生成**：不得用「摘要 / 1 引言 / 2 方法与装置 / 3 结果与讨论 / 4 结论 /
> 5 应用与展望」这类固定骨架套写，也不得用任何脚本自动拼凑中文段落。
> `full_v3_pipeline.py` 已删除全部模板生成逻辑（原 `build_full_blocks()` 及
> `zh_abs/zh_intro/zh_methods/zh_results/zh_concl`），它现在**只做提取→构建→校验**，
> 绝不代写译文。译文必须由 Agent / 人工读原文逐句写出。

## 图与公式（四项硬规则）

### 图

1. **优先抓取原始图**：优先导出 PDF 里真实存在的嵌入位图（含 Form XObject 内的位图），
   按原始分辨率存为 `images/pNN_bitmapMM.png`。
2. **其次，原文 PDF 裁切插入**：对**无嵌入位图的图区**（矢量图，或被拆散成多个小位图的图），
   按「图注上沿 → 上一文本块下沿」的版面区域整页高 DPI（2.5×）渲染再裁切，
   存为 `figures/figNN_MM.png`。矢量图是论文插图的主流形态，**必须有这条兜底**。

写进译文时，两种来源都用 `figure` 块（`image` 为等价别名）：

```json
{"type": "figure", "file": "figures/fig01_01.png", "caption": "图1 沿光纤的布里渊增益谱。"}
{"type": "figure", "file": "images/p02_bitmap01.png", "caption": "图2 传感系统的实验装置。"}
```

### 公式

1. **数学公式保存为 LaTeX 写法形式**（如 `$$E=mc^2$$`），式号随原文，用 `no` 字段给出。
2. **贴上原文的公式截图**：由 `extract_pdf_text.py` 按公式包围盒高 DPI（4×）裁切，
   存为 `formulas/fmlNN_MM.png`；写进译文时用 `image` 字段引用。

两种产物**并存**：LaTeX 便于检索与再编辑，原文截图用于逐字核对、保真防错。

```json
{"type": "formula", "latex": "$$\\mathrm{SNR} = 10\\,\\lg\\!\\left(\\frac{P_S}{P_N}\\right),$$",
 "image": "formulas/fml01_01.png", "no": "1"}
```

公式区识别采用**字体启发式 + 内容启发式取并集**（`extract_pdf_text.py`）：
前者认数学字体（Cambria Math / XITS / Latin Modern Math / STIX / cmmi-cmsy / MT Extra…），
后者按字符类（`= + − ± ∑ ∫ √ ∂ ≤ ≥ ≈ ∞ α β …`）占比补充，避免正文用 Times 排版时漏检。

## 前置检查

1. 确认 Python 3.12+，已安装 `pymupdf` 或 `pypdf`、`python-docx`
2. Windows：使用 `python -X utf8`，设置 `PYTHONUTF8=1`
3. 若需写 `zotero.sqlite`：**确认 Zotero 已完全退出**
4. 确认路径：
   - Zotero 数据目录（含 `storage/` 与 `zotero.sqlite`）
   - 任务表 `zotero_tasks.json`（可选，用于批量）
   - 台账 `status_oc.json`（可选）

## 工作流

### 单篇（文本层 PDF）

1. `extract_pdf_text.py <pdf> <workdir>/images <workdir>/figures <workdir>/formulas`
   → 产出 `extract.json` + `images/`（原始位图）+ `figures/`（裁切图）+ `formulas/`（公式截图）
2. 读 `extract.json` 的正文块，对照 `figures/`、`formulas/`，
   写出 `parts/01.json`（**逐句全文精译**，对应英文原文；图用 `figure` 块、公式用 `formula` 块）
3. `build_docx.py <workdir>/parts <out.docx>`
4. `verify_docx.py <out.docx>`，要求 `ok=true`（仅校验可解析与基本完整性，**不以字数判定**）
5. **图/公式自检**：译文图序与原文图号一一对应；原文式 (1)–(n) 无缺号；
   每个公式既有 `latex` 又有 `image`
6. 若用户要求入库：运行 `register_zotero_docx.py`（先退出 Zotero）

### 扫描件 PDF（无文本层 / OCR 伪文本）

当 PDF 为扫描影像、或 `extract_pdf_text.py` 得到的 `fulltext.txt` 仅含下载横幅/页眉页脚（`chars` 极少、或整页无正文）时，**不得**把残缺 OCR 当正文翻译，应改走扫描件流程：

1. **判定扫描件**（满足任一即按扫描件处理）
   - 页数 N 与 `fulltext.txt` 字符数比 < 约 800 字/页，且正文段落断裂
   - `fulltext.txt` 只有出版社水印、下载声明、目录页
   - 渲染页为整页位图（`get_text_bounded` 为空或几乎为空）
2. **渲染页面影像**（不要用嵌入 1×1/小色条伪图）
   ```python
   import pypdfium2 as pdfium
   doc = pdfium.PdfDocument(pdf)
   for i, page in enumerate(doc):
       page.render(scale=1.6~2.0).to_pil().save(f"pages/p{i+1:02d}.png")
   ```
   封面/下载横幅页可标注跳过；正文页按 `p01…pN` 连续编号。
3. **视觉识读（OCR）后再精译**
   - 用具备视觉能力的模型逐页阅读 `pages/pNN.png`，再按「全文精译 · 逐句对应」写 `parts/01.json`
   - 也可用本地 OCR（如 RapidOCR）先出文本，再校对公式与上下标
   - **禁止**跳过识读、按页数编造摘要式译文
4. **公式与图表**
   - 公式 OCR 易碎（`ffiffiffi`→`√`、丢失希腊字母、上下标拆行）：按量纲与文中 `where` 定义还原为 `$...$` 带原文式号
   - 不可辨认处标 `[本页图像无法识别]` 或按上下文保守还原，**不得编造数值**
   - 无嵌入位图时，图注照译为 `caption`；有可裁图元时再 `image`
   - 扫描件同样适用「公式 LaTeX + 原文截图」双产物：把 `page.render()` 的整页影像
     按公式位置二次裁切存进 `formulas/`，供核对
5. **长文**：可 `parts/01.json`、`02.json`… 分片，切片边界不截断句子
6. **构建与入库**：与文本层流程相同（`build_docx.py` → `verify_docx.py` → 挂接）
7. **验收附加项（扫描件）**
   - [ ] 页码覆盖：译文对应全部正文页，不整页空白
   - [ ] 公式：编号连续或与原文式号一致；关键式变量齐全；每式附原文截图
   - [ ] 图表：题注中文且与原文图号一致
   - [ ] 未把出版社水印/下载声明译入正文

详见 `docs/scanned-pdf-translation.md`。

### 批量

1. 维护 `zotero_tasks.json`：`itemID / mode / ztitle / pdf / docx / folder`
2. 先只做提取：`full_v3_pipeline.py <N> --extract-only`
   → 为每篇产出 `extract.json` + `images/` + `figures/` + `formulas/`
3. **由 Agent 逐篇读原文写 `parts/*.json`**（逐句精译；脚本不代写）
4. `full_v3_pipeline.py <N>` 执行 提取 → 构建 → 校验，并刷新台账
   - 缺 `parts/*.json` 的条目报 `SKIP` 并跳过，**绝不自动生成填充内容**
5. 全量审计：每个任务的 `docx` 路径存在且校验通过（`ok=true`），
   且图序、式号与原文一致

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
- [ ] **每个公式两种产物齐全**：`latex`（LaTeX 写法）+ `image`（原文公式截图）
- [ ] **检查公式（带编号）是否完整**：原文式 (1)–(n) 不得缺号、缺式、缺变量/系数；式号与正文引用一一对应
- [ ] **检查图像是否完整**：原文图 1–n 不得缺图或缺图注；图序连续，图注内容与原图对应（坐标轴/图例数值原样）
- [ ] **图的来源合规**：优先原始图（`images/`），无原始图时用 PDF 裁切（`figures/`）
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
- [ ] 块类型统一：`title` / `subtitle` / `heading` / `para` / `caption` / `figure`|`image` / `formula`|`equation` / `table`；首篇才带 `title_cn`
- [ ] `build_docx.py` 未报 `unrendered block types`（所有块类型都有渲染分支）
- [ ] DOCX 可解析（`verify_docx.py` 的 `ok=true`，仅查完整性，**不以字数判定**）
- [ ] 中文标题正确
- [ ] 台账 `status_oc.json` 已更新
- [ ] （若入库）Zotero 条目下可见译文附件

### 不合格

- 摘要式短稿或大幅缩写
- 结构化改写、按固定模板扩写（如自造「5 应用与展望」等原文没有的章节）
- **用脚本模板自动拼凑中文段落**（`full_v3_pipeline.py` 已移除该能力，若出现即为回退）
- 添加原文没有的数据/公式/结论
- **公式只给 LaTeX 不贴原文截图**，或只贴截图无 LaTeX
- **矢量图缺失**（有图注却无图；未走 PDF 裁切兜底）
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
