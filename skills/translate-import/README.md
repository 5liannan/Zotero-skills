# Zotero PDF → 中文 DOCX 翻译 Skill

把 Zotero 库中的英文学术 PDF 翻译为规范中文 DOCX，并挂回对应文献条目。

适用场景：布里渊 / 瑞利散射 / 光纤传感等领域的文献库中英混杂，需要统一中文译文便于阅读与归档。

## 翻译方案（唯一：全文精译 · 逐句对应）

| 项目 | 规定 |
|---|---|
| 方案 | **只保留全文精译** |
| 对应关系 | **与英文原文逐句对应**（按原文顺序逐句翻译） |
| 字数 | **不设上下限**（篇幅由原文决定） |
| 缩写/扩写 | **禁止**（不缩写、不注水、不按模板重写） |
| 编造 | **禁止**（不得添加原文没有的数据、公式、结论） |
| 质量分档 | **无**（取消 A/B/C；不存在「摘要整理」「结构化改写」） |

其余约定：

- 公式用 `$...$`；术语首现可括注英文
- 图表标题译中文；坐标轴/图例数值保持原样
- 参考文献保留英文条目
- 章节跟随原文结构，不合并、不删减论证关系

## 翻译验收标准

**唯一合格判定**：与英文原文**逐句对应** + `verify_docx.py` 返回 `ok=true`。  
**禁止**用最小/最大字数判定是否合格。

### 合格条件

**内容对应**

1. **逐句对应**：按原文顺序逐句翻译，无缩写、无扩写、无重排、无漏译关键句  
2. **不设字数上下限**：篇幅由原文决定；不注水、不因阈值压缩  
3. **不编造**：不添加原文没有的数据、公式、结论或图表信息  
4. **结构**：跟随原文章节，不合并、不删减论证关系  
5. **体例随原文类型**：社论/快讯无编号章节，不硬套「1 引言 / 5 应用与展望」模板  
6. **附注齐全**：致谢、基金、利益冲突、数据可用性、作者贡献若在原文则译；原文没有的节不编造  
7. **数值以原文为准**：摘要与结论不一致处照译，不擅自统一  

**体例**

8. **公式** `$...$`，式号随原文；OCR 散式按量纲自洽还原，不改物理含义  
9. **检查公式（带编号）是否完整**：原文式 (1)–(n) 不得缺号、缺式、缺变量/系数；式号与正文引用一一对应  
10. **检查图像是否完整**：原文图 1–n 不得缺图或缺图注；图序连续，图注与原图对应（坐标轴/图例数值原样）  
11. **引文编号** `[n]` 保留；OCR 误识可按上下文校正（如 `[58]`→`[5–8]`）  
12. **图/表标题**译中文；坐标轴/图例数值保持原样  
13. **参考文献**保留英文条目  
14. **术语**首现可括注英文  

**源文本预处理（译前）**

15. 去掉页眉页脚/页码/水印，不译入正文  
16. 双版本叠印（`FOR PEER REVIEW` + 正式版）先去重再译  
17. PDF 断词（`U+FFFE`、软连字符）先拼合：复合词保留 `-`，词内断开直接拼接  
18. 跨页断句先拼成完整句再译；图注插入句中时，图注独立成 `caption`，正文整句对应  

**技术**

19. 写 DOCX 前剔除非 XML 字符（`U+FFFE`、控制符），否则 `python-docx` 会报错  
20. 长文分 `parts/01.json`… 时切片边界不截断句子；续句只译一次、分片间不重复  
21. 块类型统一：`title` / `subtitle` / `heading` / `para` / `caption`|`figure` / `formula`|`equation` / `table`；首篇才带 `title_cn`  
22. **DOCX** 可解析（`verify_docx.py` 的 `ok=true`，仅查完整性，**不以字数判定**）  
23. 中文标题正确；台账已更新；（若入库）Zotero 条目下可见译文附件  

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

## 能力概览

| 阶段 | 作用 | 脚本 |
|---|---|---|
| 1. 提取 | 从 PDF 抽文本块 + 位图 | `scripts/extract_pdf_text.py` |
| 2. 译文 | 生成 `parts/01.json`（逐句全文精译） | Agent / 人工 / `full_v3_pipeline.py` |
| 3. 构建 | 渲染为 A4 单栏 DOCX（宋体 + Times New Roman 五号） | `scripts/build_docx.py` |
| 4. 校验 | 检查可解析与完整性（**不以字数判定**） | `scripts/verify_docx.py` |
| 5. 入库 | 复制到独立 storage key 并写 `itemAttachments` | `scripts/register_zotero_docx.py` |
| 6. 标题 | 为附件补写 title 字段 | `scripts/fix_zotero_titles.py` |

## 环境依赖

- Python 3.12+（推荐，需 `pymupdf` 或 `pypdf` 与 `python-docx`）
- Windows 上建议：`python -X utf8` 并设 `PYTHONUTF8=1`
- 写 `zotero.sqlite` 前必须 **完全退出 Zotero**
- 修改库前脚本会自动备份 sqlite

```text
# 最小依赖（PDF 文本提取任选其一）
pypdf
# 或 pymupdf
python-docx
```

安装示例：

```bash
"C:\...\Python312\python.exe" -m pip install pypdf python-docx
```

## parts/01.json 格式（译文中间产物）

按英文原文顺序组织 blocks，**逐句对应**，不要求固定总字数：

```json
{
  "title_cn": "中文标题",
  "blocks": [
    {"type": "title", "text": "中文标题"},
    {"type": "subtitle", "text": "English Original Title"},
    {"type": "heading", "level": 1, "text": "摘要"},
    {"type": "para", "text": "……", "noindent": true},
    {"type": "heading", "level": 1, "text": "1 引言"},
    {"type": "para", "text": "与原文逐句对应的中译……"},
    {"type": "para", "text": "$E=mc^2$, \\qquad (1)"},
    {"type": "image", "file": "images/p02_00.png", "caption": "图1 …"},
    {"type": "table", "header": true, "rows": [["A", "B"], ["1", "2"]]}
  ]
}
```

`image.file` 相对 `parts/` 的父目录（即 `work/item_<id>/`）。

## 标准工作流

```bash
PY="python"   # Windows: C:\...\Python312\python.exe
export PYTHONUTF8=1

# 1) PDF → extract.json + images/
$PY -X utf8 scripts/extract_pdf_text.py "<pdf_path>" "<workdir>/images" > "<workdir>/extract.json"

# 2) 编写译文 parts/01.json（与英文原文逐句对应的全文精译）

# 3) 构建 DOCX
$PY -X utf8 scripts/build_docx.py "<workdir>/parts" "<output.docx>"

# 4) 校验（ok 即可，无字数门槛）
$PY -X utf8 scripts/verify_docx.py "<output.docx>"

# 5) 批量挂接到 Zotero（需退出 Zotero）
$PY -X utf8 scripts/register_zotero_docx.py

# 6) 补附件标题（需退出 Zotero）
$PY -X utf8 scripts/fix_zotero_titles.py
```

`register_zotero_docx.py` / `fix_zotero_titles.py` 中的路径（Zotero 数据目录、status 台账）请按本机环境修改后再运行。

## 批量全文精译流水线

`scripts/full_v3_pipeline.py`：

1. 读 `zotero_tasks.json` + `status_oc.json`
2. 对需要翻译的条目：提取 PDF 全文 → **逐句全文精译** → 构建 DOCX → 写回台账
3. **不设字数上下限**；以「与英文原文逐句对应」为唯一质量标准

任务表 `zotero_tasks.json` 条目示例：

```json
{
  "mode": "create_new",
  "itemID": 5742,
  "ztitle": "中文或英文题名",
  "pdf": "C:\\...\\storage\\KEY\\xxx.pdf",
  "docx": "",
  "folder": "C:\\...\\storage\\KEY"
}
```

`mode`：

- `create_new`：译文写到 `folder`（通常与 PDF 同 storage 目录）
- `fill_existing`：覆盖 `docx` 字段指向的既有占位文件（可能在另一 storage 目录）

## Zotero 存储规则（重要）

Zotero 原生是 **一个附件一个 storage 目录**；**PDF 与译文 DOCX 必须分目录**：

```text
storage/<PDF附件key>/paper.pdf
storage/<DOCX附件key>/中文标题.docx   ← 译文应放这里（禁止与 PDF 同目录）
```

`register_zotero_docx.py` 会把译文复制到新 key 目录，并插入 `items` + `itemAttachments`，挂到 PDF 的父条目上。  
**不要**把译文只丢在 PDF 同目录而不登记——界面里看不到；也不要覆盖 PDF 目录里的文件。

管理细则（去重、隔离区、path 对齐、孤儿清理、缺失找回）见仓库文档：

- [`docs/zotero-storage-management.md`](../../docs/zotero-storage-management.md)

## 安全与注意

1. **写 sqlite 前退出 Zotero**，否则数据库锁死或损坏  
2. 脚本会先备份 `zotero.sqlite.bak_before_*`  
3. 删除附件请走 Zotero UI 或带备份的专用脚本，避免孤儿文件  
4. 受版权保护 PDF 仅在本机个人阅读/翻译使用；勿批量上传或分发  

## 目录建议

```text
translate/
  README.md              ← 本文件
  SKILL.md               ← Agent 技能说明
  requirements.txt
  scripts/
    extract_pdf_text.py
    build_docx.py
    verify_docx.py
    register_zotero_docx.py
    fix_zotero_titles.py
    full_v3_pipeline.py
  examples/
    parts_example.json
```

## 可移植配置（环境变量 / config.json）

所有写死路径已改为可覆盖。优先级：**环境变量 > config.json > config.example.json > 内置默认**。

| 环境变量 | 含义 | 默认 |
|---|---|---|
| `ZOTERO_DATA_DIR` | Zotero 数据目录（含 `storage/`、`zotero.sqlite`） | `~/Zotero` |
| `ZOTERO_PYTHON` | Python 解释器 | 当前 `sys.executable` |
| `ZOTERO_WORK_BASE` | 工作区（work/results/status） | `~/.openclaw-autoclaw/workspace/zcode-continuation` |
| `ZOTERO_TASKS_JSON` | 任务表路径 | `<data>/zotero_tasks.json` |
| `ZOTERO_STATUS_JSON` | 状态台账 | `<work>/status_oc.json` |
| `TRANSLATE_CONFIG` | 指定 config.json 路径 | 同目录 `config.json` |

**说明**：已移除 `ZOTERO_MIN_CHARS` / `ZOTERO_VERIFY_MIN_CHARS` 等字数阈值；译文质量只看**与英文原文是否逐句对应**，以及 `verify_docx.py` 是否 `ok=true`。

复制模板：

```bash
cp config.example.json config.json
# 编辑 config.json，或：
export ZOTERO_DATA_DIR="D:/Zotero"
export ZOTERO_WORK_BASE="D:/zwork"
python scripts/print_paths.py
```

## CI

GitHub Actions：`.github/workflows/translate-ci.yml`

- Python 3.11 / 3.12
- 语法检查全部脚本
- config 环境变量冒烟测试
- 用 `examples/parts` 构建并校验示例 DOCX
