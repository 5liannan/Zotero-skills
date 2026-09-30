# Zotero-skills — 两大 Skill

面向 Zotero 文献库的两套可独立使用、也可串联的工作流：

| Skill | 目录 | 做什么 |
|---|---|---|
| **① 检索文献与导入 Zotero** | [`skills/search-import/`](skills/search-import/) | Crossref 检索 → 筛选 → 入库 → 挂 PDF → 报告 |
| **② 翻译文献与导入 Zotero** | [`skills/translate-import/`](skills/translate-import/) | 英文 PDF → 中文 DOCX（**全文精译 · 与原文逐句对应**）→ **构建即终稿**（公式为 Word 原生公式对象 + 页眉页码 + 图注规范 + 引用可点击跳转 + 参考文献一致性校验）→ 挂回 Zotero 条目 |

```text
search-import                    translate-import
    │                                  │
    ▼                                  ▼
 Zotero 库（有 PDF）  ──────────►  中文 DOCX 附件（公式可编辑）
```

- 只做入库：用 ①
- 只做中文化：用 ②
- 全流程：先 ① 后 ②

> **附：`skills/docx-polish/` — 外部旧 DOCX 的补救工具（按需使用）**
>
> ②的**正常流程已内置终稿规范化**（`translate-import/scripts/finalize.py`，由
> `build_docx.py` 自动调用），所以**自己翻译的文档不需要它**。
> 它现在唯一的不可替代职责，是把**别处给的、公式已退化成纯文本 LaTeX** 的旧 DOCX
> 强制补转成 Word 公式对象（顺带清高亮残留、规范图注、补页眉页码）。
> 详见 [`skills/docx-polish/README.md`](skills/docx-polish/README.md)。

## 快速入口

### ① 检索导入

```bash
cd skills/search-import
# Node >= 18，Zotero 桌面端打开
# 配置 topics/<主题>.json 后：
node src/01_baseline.mjs <主题>
# ... 详见 skills/search-import/README.md
```

技能说明：`skills/search-import/SKILL.md`  
Agent 剧本：`skills/search-import/AGENT.md`

### ② 翻译导入

```bash
cd skills/translate-import
pip install -r requirements.txt
conda install -c conda-forge pandoc    # LaTeX → Word 公式对象的关键
cp config.example.json config.json     # 或设 ZOTERO_DATA_DIR 等环境变量
python scripts/print_paths.py
# ... 详见 skills/translate-import/README.md
```

> **构建产出即终稿**：`build_docx.py` 保存前会自动跑 `scripts/finalize.py`
> 做终稿规范化（图注、标题层级、页眉 + 页脚 PAGE 域、正文引用可点击跳转、
> 参考文献一致性校验）。缺 pandoc、公式转不动、参考文献对不上号时，
> 构建**直接报错退出、不产出文件**——不存在「报成功但公式还是 `$` 源码」的假成功。

技能说明：`skills/translate-import/SKILL.md`  
扫描件 PDF（无文本层）翻译流程：[`docs/scanned-pdf-translation.md`](docs/scanned-pdf-translation.md)


## 环境变量（translate）

| 变量 | 含义 |
|---|---|
| `ZOTERO_DATA_DIR` | Zotero 数据目录（storage + sqlite） |
| `ZOTERO_WORK_BASE` | 翻译工作区 |
| `ZOTERO_PYTHON` | Python 解释器 |

## 目录结构

```text
Zotero-skills/
  README.md
  .github/workflows/translate-ci.yml
  docs/
    zotero-storage-management.md
    zotero-datadir-migration.md
  scripts/
    manage_zotero_storage.py   # 结构对齐（check/split/align…）+ 译文质量治理（quality-*）
    docx_quality.py            # 译文质量判定内核（可单独运行）
    migrate_zotero_datadir.py
    requirements.txt
  tests/
    test_storage_quality.py    # 质量审计回归测试（合成 fixture）
  skills/
    search-import/
      SKILL.md
      AGENT.md
      README.md
      config.example.json
      src/          # 01–09 流水线 + lib.mjs
      topics/       # 每主题一份配置
      outputs/      # 中间产物
    translate-import/
      SKILL.md
      README.md
      config.example.json
      requirements.txt
      scripts/      # extract / omml / finalize / build / verify / register / ...
      examples/     # parts 示例（含公式、图、正文引用与文末文献）
    docx-polish/    # 附：补救外部旧 DOCX（公式事后补转 OMML）
      SKILL.md
      README.md
      config.example.json
      requirements.txt
      scripts/      # run_polish / diagnose / extract_formulas / optimize / verify_word
```

## 原则

- 检索入库：**只走 Zotero API**，不直写 `zotero.sqlite`  
- 翻译挂接：写 sqlite 前必须 **退出 Zotero**，并自动备份  
- 两套 skill 的路径均可通过环境变量/配置迁移到其他机器  

## 附件与 storage 管理

库内附件（PDF / 中文 DOCX）与磁盘 `storage/` 对齐、去重、拆分的完整规范：

- [docs/zotero-storage-management.md](docs/zotero-storage-management.md)
- 可执行工具：`scripts/manage_zotero_storage.py`
- 译文质量判定内核：`scripts/docx_quality.py`

铁律摘要：

1. **一附件一目录**：PDF 与译文 DOCX 永不同目录  
2. **同一文献只留 1 份译文**  
3. **先隔离、不硬删**（`quarantine_*`）  
4. 写 `zotero.sqlite` 前必须完全退出 Zotero，并先备份  
5. **结构对齐 ≠ 附件没问题**：`path` 对得上，挂的仍可能是假译文

```bash
export ZOTERO_DATA_DIR=E:/Zotero
export ZOTERO_WORK_BASE=C:/path/to/work

python scripts/manage_zotero_storage.py check    # 只读体检（结构）
python scripts/manage_zotero_storage.py doctor   # 完整巡检（写库步骤前请退出 Zotero）

# 译文质量：判定「挂的是不是真译文」，并治理
python scripts/manage_zotero_storage.py quality            # 只读审计，出报告+清单
python scripts/manage_zotero_storage.py quality-relink     # 把条目指向合格译文（先 --dry-run）
python scripts/manage_zotero_storage.py quality-remove     # 不合格译文送回收站（先 --dry-run）
python scripts/manage_zotero_storage.py quality-normalize  # 批量终稿规范化（页眉页码/交叉引用等）
```

> **为什么需要 quality**：旧模板流水线产出过大量假译文——「本文题为《…》」
> 「参考文献保留英文原文…详见原 PDF」+ 图注重复 8 遍 + 裸 LaTeX，
> 而**正确的那份译文常常就在同一个目录里没被登记**。
> 判定只看客观结构信号（模板套话 / 段落重复 / 裸 LaTeX / 高亮 / 中文字数 / 中英混排），
> 不靠主观阅读。见规范文档第 8 节。
>
> 回归测试：`python tests/test_storage_quality.py`（合成 fixture，不需要真 Zotero）

## 数据目录迁移（任意路径）

把 Zotero 数据目录从**任意当前路径**迁到**任意新路径**（换盘、外接盘、NAS 等）而不丢附件：

- [docs/zotero-datadir-migration.md](docs/zotero-datadir-migration.md)
- 辅助脚本：`scripts/migrate_zotero_datadir.py`

```bash
# 先演练（不改任何配置）
python scripts/migrate_zotero_datadir.py --src "<旧路径>" --dst "<新路径>" --dry-run

# 确认后执行；脚本会复制数据并备份/修改 prefs.js 中的 dataDir
python scripts/migrate_zotero_datadir.py --src "<旧路径>" --dst "<新路径>"

# 也可省略 --src，从 prefs 自动读取当前 dataDir
python scripts/migrate_zotero_datadir.py --dst "<新路径>" --dry-run
```

迁移后在 Zotero 里验证附件可打开，再手动删除旧目录。
