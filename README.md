# Zotero-skills

> 面向 Zotero 文献库的两套可独立使用、也可串联的 AI 工作流：
> **检索文献与导入 Zotero**、**翻译文献与导入 Zotero**。

把「找论文 → 入库 → 挂全文 → 中文化 → 挂回译文」做成可重复执行的流水线，  
并且把公式、图注、交叉引用、参考文献一致性等交付质量门槛**写进构建**，避免「报成功但产物不可用」。

| Skill | 目录 | 做什么 |
|---|---|---|
| **① 检索文献与导入 Zotero** | [`skills/search-import/`](skills/search-import/) | Crossref 检索 → 筛选 → 入库 → 挂 PDF → 报告 |
| **② 翻译文献与导入 Zotero** | [`skills/translate-import/`](skills/translate-import/) | 英文 PDF → 中文 DOCX（**全文精译 · 与原文逐句对应**）→ **构建即终稿**（Word 原生公式对象 + 页眉页码 + 图注规范 + 引用可点击跳转 + 参考文献一致性校验）→ 挂回 Zotero；内置外部旧 DOCX 公式补转（`docx-polish/`） |

```text
search-import                    translate-import
    │                                  │
    ▼                                  ▼
 Zotero 库（有 PDF）  ──────────►  中文 DOCX 附件（公式可编辑）
```

- 只做入库：用 ①  
- 只做中文化：用 ②  
- 全流程：先 ① 后 ②  

② 的正常流程已内置终稿规范化，自己翻译的文档**不需要**再跑修复工具。  
若拿到的是外部旧 DOCX（公式退化成纯文本 LaTeX），走 ② 内置的补救分支  
[`skills/translate-import/docx-polish/`](skills/translate-import/docx-polish/)。

## 快速入口

### ① 检索导入

```bash
cd skills/search-import
# Node >= 18，Zotero 桌面端打开
# 配置 topics/<主题>.json 后：
node src/01_baseline.mjs <主题>
# ... 详见 skills/search-import/README.md
```

技能说明：[`skills/search-import/SKILL.md`](skills/search-import/SKILL.md)  
Agent 剧本：[`skills/search-import/AGENT.md`](skills/search-import/AGENT.md)

### ② 翻译导入

```bash
cd skills/translate-import
pip install -r requirements.txt
# 安装 pandoc（LaTeX → Word 公式对象的关键）：
#   conda install -c conda-forge pandoc
#   或从 https://pandoc.org/installing.html 安装
cp config.example.json config.json     # 或设 ZOTERO_DATA_DIR 等环境变量
python scripts/print_paths.py
# ... 详见 skills/translate-import/README.md
```

> **构建产出即终稿**：`build_docx.py` 保存前会自动跑 `scripts/finalize.py`  
> 做终稿规范化。缺 pandoc、公式转不动、参考文献对不上号时，  
> 构建**直接报错退出、不产出文件**——不存在「报成功但公式还是 `$` 源码」的假成功。

技能说明：[`skills/translate-import/SKILL.md`](skills/translate-import/SKILL.md)  
扫描件 PDF（无文本层）翻译流程：[`docs/scanned-pdf-translation.md`](docs/scanned-pdf-translation.md)

## 环境变量

| 变量 | 含义 |
|---|---|
| `ZOTERO_DATA_DIR` | Zotero 数据目录（storage + sqlite） |
| `ZOTERO_WORK_BASE` | 翻译 / 治理工作区 |
| `ZOTERO_PYTHON` | Python 解释器 |
| `DOCX_POLISH_CONFIG` | 补救分支配置文件路径（可选） |

## 目录结构

```text
Zotero-skills/
  README.md
  .github/workflows/translate-ci.yml   # 翻译流水线（需要 pandoc）
  .github/workflows/storage-ci.yml     # storage 治理与质量审计
  .github/workflows/repo-ci.yml        # 仓库卫生 + 配置转发 + 规则一致性（零依赖）
  docs/
    zotero-storage-management.md
    zotero-datadir-migration.md
    scanned-pdf-translation.md
  scripts/
    manage_zotero_storage.py   # 结构对齐（check/split/align…）+ 译文质量治理（quality-*）
    docx_quality.py            # 译文质量判定内核（可单独运行）
    migrate_zotero_datadir.py
    requirements.txt
  tests/
    test_storage_quality.py    # 质量审计回归测试（合成 fixture）
    test_repo_hygiene.py       # BOM / 硬编码个人路径 / 死链 / 示例配置
    test_polish_config.py      # 补救分支配置加载与参数转发
    test_rule_parity.py        # 终稿规则两份实现的一致性守卫
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
      docx-polish/  # 内置补救：外部旧 DOCX 公式事后补转 OMML
      examples/     # parts 示例（含公式、图、正文引用与文末文献）
```

## 原则

- 检索入库：**只走 Zotero API**，不直写 `zotero.sqlite`
- 翻译挂接：写 sqlite 前必须 **退出 Zotero**，并自动备份
- 构建失败不产出文件；结构对齐 ≠ 内容合格，内容另做质量审计
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
export ZOTERO_DATA_DIR=/path/to/Zotero
export ZOTERO_WORK_BASE=/path/to/work

python scripts/manage_zotero_storage.py check    # 只读体检（结构）
python scripts/manage_zotero_storage.py doctor   # 完整巡检（写库步骤前请退出 Zotero）

# 译文质量：判定「挂的是不是真译文」，并治理
python scripts/manage_zotero_storage.py quality            # 只读审计，出报告+清单
python scripts/manage_zotero_storage.py quality-relink     # 把条目指向合格译文（先 --dry-run）
python scripts/manage_zotero_storage.py quality-remove     # 不合格译文送回收站（先 --dry-run）
python scripts/manage_zotero_storage.py quality-normalize  # 批量终稿规范化（页眉页码/交叉引用等）
```

> **为什么需要 quality**：旧模板流水线产出过大量假译文（模板套话 / 图注重复 / 裸 LaTeX），  
> 而**正确的那份译文常常就在同一个目录里没被登记**。  
> 判定只看客观结构信号，不靠主观阅读。见规范文档第 8 节。  
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
```

迁移后在 Zotero 里验证附件可打开，再手动删除旧目录。

## 守卫测试

`python tests/<file>`，随 CI 每次推送都跑：

| 测试 | 依赖 | 盯住什么 |
|---|---|---|
| `tests/test_repo_hygiene.py` | 无 | UTF-8 BOM、硬编码个人绝对路径、Markdown 相对死链、示例配置不是合法 JSON、技能缺 `SKILL.md` |
| `tests/test_polish_config.py` | 无 | 补救分支配置**确实被读取**、参数确实转发给 `optimize.py`、`--dry-run` 不动源文件 |
| `tests/test_rule_parity.py` | python-docx | 终稿规则在 `finalize.py` 与 `optimize.py` 两份实现间不漂移 |
| `tests/test_storage_quality.py` | 无 | 质量审计判定与治理逻辑 |

## License

见仓库未另附许可证时，按作者约定使用；对外分发前请自行确认。
