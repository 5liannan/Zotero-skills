# Zotero-skills — 两大 Skill

面向 Zotero 文献库的两套可独立使用、也可串联的工作流：

| Skill | 目录 | 做什么 |
|---|---|---|
| **① 检索文献与导入 Zotero** | [`skills/search-import/`](skills/search-import/) | Crossref 检索 → 筛选 → 入库 → 挂 PDF → 报告 |
| **② 翻译文献与导入 Zotero** | [`skills/translate-import/`](skills/translate-import/) | 英文 PDF → 中文 DOCX → 挂回 Zotero 条目 |

```text
search-import                    translate-import
    │                                  │
    ▼                                  ▼
 Zotero 库（有 PDF）  ──────────►  中文 DOCX 附件
```

- 只做入库：用 ①  
- 只做中文化：用 ②  
- 全流程：先 ① 后 ②  

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
cp config.example.json config.json   # 或设 ZOTERO_DATA_DIR 等环境变量
python scripts/print_paths.py
# ... 详见 skills/translate-import/README.md
```

技能说明：`skills/translate-import/SKILL.md`

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
      scripts/      # extract/build/verify/register/...
      examples/     # parts 示例
```

## 原则

- 检索入库：**只走 Zotero API**，不直写 `zotero.sqlite`  
- 翻译挂接：写 sqlite 前必须 **退出 Zotero**，并自动备份  
- 两套 skill 的路径均可通过环境变量/配置迁移到其他机器  

## 数据目录迁移

把 Zotero 从 C 盘迁到 E 盘（或其他路径）而不丢附件，见：

- [docs/zotero-datadir-migration.md](docs/zotero-datadir-migration.md)
- 辅助脚本：`scripts/migrate_zotero_datadir.py`

```powershell
python scripts/migrate_zotero_datadir.py --src "C:/Users/You/Zotero" --dst "E:/Zotero" --dry-run
# 确认后去掉 --dry-run；验证 Zotero 正常后再手动删除 --src
```

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
