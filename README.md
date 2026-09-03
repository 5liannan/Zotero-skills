# lit-workflow — 文献检索与 Zotero 导入通用工作流

从 `rbs_task`（气体瑞利-布里渊散射文献补充）泛化而来的七阶段流水线。
换一个研究方向，只需要新写一个 `topics/<主题>.json` 配置，脚本一行不改。

## 流水线总览

```
01 摸底 ──> 02 抓取 ──> 03 筛选 ──[人工圈定DOI]──> 04 定稿 ──> 05 RIS ──> 06 入库 ──> 07 全文
```

| 脚本 | 干什么 | 输入 | 输出 |
|---|---|---|---|
| `01_baseline.mjs` | 摸底：分页拉取 Zotero 现有库 | Zotero 本地 API | `baseline.json` |
| `02_search.mjs` | 抓取：按关键词查 Crossref，合并去重 | `config.search` | `candidates_all.json` `candidates_meta.json` |
| `03_filter.mjs` | 筛选：正则规则 + 排除已有 + 去重 | 上面两项 | `filtered_main.json` `filtered_secondary.json` `filter_report.json` |
| `04_finalize.mjs` | 定稿：审定 DOI 逐个拉全字段 | `approved_dois.txt`（人工） | `final_items.json` `finalize_errors.json` |
| `05_export_ris.mjs` | 导出 RIS（可直接拖进 Zotero） | `final_items` | `<risFile>` |
| `06_import.mjs` | 入库：逐条 POST + 归类 + 打标签 | `final_items` | `import_results.json` |
| `07_attach_pdfs.mjs` | 全文：查 Unpaywall 找 OA PDF 并挂载 | `import_results` | `pdf_results.json` |

## 关键设计（每条都对应旧项目踩过的坑）

- **断点续跑**：02 重跑自动合并旧候选池；06/07 跳过已成功条目，失败修复后重跑只补失败项
- **逐条入库**：06 默认一条一个 session，失败只影响那一条——旧项目里全量 POST 翻车后靠 bisect.js 排查的教训
- **过程留痕**：每组查询的命中数落盘 `candidates_meta.json`，不再有"只往终端打印、跑完就丢"的轮次
- **人工检查点**：03 → 04 之间必须人审；`approved_dois.txt` 每行一个 DOI、`#` 可注释，本身就是版本可控的决策记录
- **零依赖**：只用 Node 内置模块（fs + 全局 fetch），无 npm install

## 快速开始（新主题三步）

要求 Node >= 18。运行方式统一为 `node src/<脚本>.mjs <主题>`。

1. 复制 `config.example.json` 为 `topics/<主题>.json`，填关键词与筛选规则
2. 依次跑 `01` → `02` → `03`，审阅 `filtered_main.json`，把选中的 DOI 写进 `outputs/<主题>/approved_dois.txt`
3. 跑 `04` → `05`（导 RIS 手动拖 Zotero），或 `06`（API 直接入库）→ `07`（挂 PDF）

## 配置字段说明

```jsonc
{
  "zotero": {
    "apiBase": "http://localhost:23119",   // Zotero 本地 API，需 Zotero 处于打开状态
    "collectionKey": "C33",                // 入库后归档到的分类 key（留空则只入库不归档）
    "tags": ["..."]                        // updateSession 统一打的标签
  },
  "search": {
    "mailto": "you@example.com",           // Crossref 礼貌池要求真实邮箱
    "rows": 100, "pagesPerQuery": 2,       // 每组查询抓多少页
    "queries": [ "关键词", { "q": "关键词", "filter": "from-pub-date:2024-01-01" } ]
  },
  "filter": {
    "requireAny":          ["主词"],        // 标题必须命中其一
    "requireContextAny":   ["场景词", "强信号词"],  // 且须命中其一（场景 OR 强信号）
    "excludeAny":          ["要排除的方向"],
    "rescueAny":           ["例外词"],      // 命中排除词但同时命中它 -> 保留
    "secondary": { ... }                   // 第二梯队，规则同构，独立去重、默认不排除
  },
  "finalize": { "excludeDois": ["10.x/..."] },   // 定稿里再剔除的 DOI
  "export":   { "risFile": "文献补充.ris", "extraRis": ["manual_extra.ris"] }  // 手工补录老文献
}
```

## Agent 执行剧本

见 [AGENT.md](AGENT.md)。Agent 按剧本自动跑 01–03、04–07，在两个检查点停下来等用户确认。

## 从 rbs_task 迁移对照表

| 旧（一次性脚本） | 新（配置驱动） |
|---|---|
| `dump_lib.js` | `01_baseline.mjs` |
| `search_crossref.js` + `round2.js` + `round3.js` | `02_search.mjs`（多轮关键词统一进 config） |
| `filter.js` | `03_filter.mjs`（四条正则进 config） |
| `finalize.js` 硬编码 84 个 DOI | `outputs/rbs/approved_dois.txt`（由 `tools/migrate_rbs.mjs` 机械提取） |
| `build_ris.js` | `05_export_ris.mjs`（Landau-Placzek 1934 → `manual_extra.ris`） |
| `import.js` 全量失败 + `bisect.js` 排查 | `06_import.mjs` 默认逐条、失败隔离 |
| `finalize_import.js` 收尾归档 | `06` 内置 updateSession 批量归档 |
| `pdfs.js` + `pdfs2.js` | `07_attach_pdfs.mjs`（浏览器 UA 重试逻辑内置） |

**回归验证**：用 rbs_task 的真实数据回放，筛选结果 181 / 66 条与旧版逐字节一致，RIS 导出 59320 字节 MD5 相同。

## 已知限制

- Zotero 必须处于打开状态，否则本地 API（23119）无响应
- PDF 挂载依赖 Unpaywall 覆盖率，无 OA 的条目记为 `no-oa`（不是失败）
- Crossref 对高频请求会限流，`pauseMs` 不要调太小
