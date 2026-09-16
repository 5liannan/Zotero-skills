---
name: search-import
description: 从 Crossref 等来源检索学术文献，筛选后导入 Zotero，并挂载 PDF 全文。触发词：检索文献、导入 Zotero、文献检索入库、找论文并入库、批量下载文献。
---

# Skill：检索文献与导入 Zotero

## 目标

用户要「按主题找论文并放进 Zotero」时使用。

## 工作流

1. 建 `topics/<主题>.json`（关键词、年份、分类 key、标签）
2. `node src/01_baseline.mjs <主题>` 摸底库内已有
3. `node src/02_search.mjs <主题>` Crossref 抓取
4. `node src/03_filter.mjs <主题>` 筛选 + 去重
5. **人工**写 `outputs/<主题>/approved_dois.txt`
6. `node src/04_finalize.mjs <主题>` 拉全字段
7. `node src/06_import.mjs <主题>` API 入库（或 05 导 RIS）
8. `node src/07_attach_pdfs.mjs <主题>` 挂 OA PDF（串行）
9. `node src/08_report.mjs <主题>` 报告 + BibTeX

可选：本地已有 PDF 用 `09_import_pdfs.mjs`。

## 前置

- Node.js >= 18  
- Zotero 桌面端打开（本地 API 23119）  
- 配置见 `config.example.json`

## 硬性约束

- 不直读/直写 `zotero.sqlite`  
- 07 挂 PDF 必须串行，且等 06 入库完成  
- 03→04 之间必须用户确认 DOI  

详见 `README.md` 与 `AGENT.md`。
