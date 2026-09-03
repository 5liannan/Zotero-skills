# lit-workflow — 文献检索与 Zotero 导入通用工作流

由早期一次性文献补充脚本（气体瑞利-布里渊散射、BOTDA 布里渊光时域分析两条管线）
沉淀泛化而来的八阶段流水线。
换一个研究方向，只需要新写一个 `topics/<主题>.json` 配置，脚本一行不改。

## 流水线总览

```
01 摸底 ──> 02 抓取 ──> 03 筛选 ──[人工圈定DOI]──> 04 定稿 ──> 05 RIS ──> 06 入库 ──> 07 全文 ──> 08 报告
```

| 脚本 | 干什么 | 输入 | 输出 |
|---|---|---|---|
| `01_baseline.mjs` | 摸底：分页拉取 Zotero 现有库 | Zotero 本地 API | `baseline.json` |
| `02_search.mjs` | 抓取：按关键词查 Crossref + 按 DOI 直取，合并去重 | `config.search` | `candidates_all.json` `candidates_meta.json` |
| `03_filter.mjs` | 筛选：正则规则 + 排除已有（DOI + 标题相似）+ 去重 | 上面两项 | `filtered_main.json` `filtered_secondary.json` `filter_report.json` |
| `04_finalize.mjs` | 定稿：审定 DOI 逐个拉全字段 | `approved_dois.txt`（人工） | `final_items.json` `finalize_errors.json` |
| `05_export_ris.mjs` | 导出 RIS（可直接拖进 Zotero） | `final_items` | `<risFile>` |
| `06_import.mjs` | 入库：逐条 POST + 归类 + 打标签 | `final_items` | `import_results.json` |
| `07_attach_pdfs.mjs` | 全文：Unpaywall OA + 出版社直链兜底，串行挂载 | `import_results` | `pdf_results.json` |
| `08_report.mjs` | 报告：按人工注记分类 + BibTeX 导出 | `final_items`（+`curated.json`） | `report.md` `references.bib` |

## 关键设计（每条都对应旧项目踩过的坑）

- **断点续跑**：02 重跑自动合并旧候选池；06/07 跳过已成功条目，失败修复后重跑只补失败项
- **逐条入库**：06 默认一条一个 session，失败只影响那一条——旧项目里全量 POST 翻车后靠 bisect.js 排查的教训
- **过程留痕**：每组查询的命中数落盘 `candidates_meta.json`，不再有"只往终端打印、跑完就丢"的轮次
- **人工检查点**：03 → 04 之间必须人审；`approved_dois.txt` 每行一个 DOI、`#` 可注释，本身就是版本可控的决策记录
- **库内去重双保险**（源自 BOTDA 管线）：03 先按 DOI 精确排除，再按标题词相似度排除——公共词 ≥5 且占较短标题 80% 以上即判为同一篇，专治"DOI 不同实为同一篇"（预印本/多版本）。`filter.simInLibrary: false` 可关闭
- **导入与挂全文分离**：06 只入库、07 才挂 PDF 且全程串行——BOTDA 项目在导入高峰并发下载附件，Zotero 曾因此连续崩溃
- **出版社直链兜底**（源自 BOTDA 管线）：Unpaywall 覆盖不到的 Optica Optics Express / MDPI 条目，按 DOI + 卷期页直接构造 PDF 直链
- **人工注记驱动报告**：把审阅时的一句话注记写进 `outputs/<主题>/curated.json`（`[{doi, note}]`），08 按注记关键词自动分类生成报告
- **零依赖**：只用 Node 内置模块（fs + 全局 fetch），无 npm install

## 快速开始（新主题三步）

要求 Node >= 18。运行方式统一为 `node src/<脚本>.mjs <主题>`。

1. 复制 `config.example.json` 为 `topics/<主题>.json`，填关键词与筛选规则
2. 依次跑 `01` → `02` → `03`，审阅 `filtered_main.json`，把选中的 DOI 写进 `outputs/<主题>/approved_dois.txt`（顺手写一句话注记到 `curated.json` 更好）
3. 跑 `04` → `05`（导 RIS 手动拖 Zotero），或 `06`（API 直接入库）→ `07`（挂 PDF）→ `08`（出报告 + BibTeX）

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
    "queries": [ "关键词", { "q": "关键词", "filter": "from-pub-date:2024-01-01" } ],
    "dois": [ "10.xxxx/经典文献" ]          // 可选：经典文献按 DOI 直取，标题搜索漏不掉
  },
  "filter": {
    "requireAny":          ["主词"],        // 标题必须命中其一
    "requireContextAny":   ["场景词", "强信号词"],  // 且须命中其一（可选；不配则不设上下文门槛）
    "excludeAny":          ["要排除的方向"],
    "rescueAny":           ["例外词"],      // 命中排除词但同时命中它 -> 保留
    "simInLibrary": true,                  // 标题相似度排除库内已有（默认 true，false 关闭）
    "secondary": { ... }                   // 第二梯队，规则同构，独立去重、默认不排除
  },
  "finalize": { "excludeDois": ["10.x/..."] },   // 定稿里再剔除的 DOI
  "export":   { "risFile": "文献补充.ris", "extraRis": ["manual_extra.ris"] },  // 手工补录老文献
  "report":   {                                  // 08 报告：注记关键词分类（顺序即优先级）
    "title": "XX 文献报告",
    "defaultCategory": "关键技术里程碑",
    "categories": [
      { "name": "综述与评述", "noteAny": ["综述"] },
      { "name": "奠基性经典", "noteAny": ["首", "首创", "前身"] }
    ]
  }
}
```

人工注记文件 `outputs/<主题>/curated.json`（可选，08 的输入之一）：

```json
[
  { "doi": "10.1364/OL.15.001038", "note": "BOTDA 首创实验，奠基性经典" },
  { "doi": "10.1364/OE.21.031347", "note": "暗脉冲 BOTDA 综述" }
]
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

## 从 BOTDA_literature 迁移对照表

| 旧（Python 一次性管线） | 新（配置驱动） |
|---|---|
| `botda_collect.py` 的 `sim()` / `in_library()`（直读 zotero.sqlite 比对） | `lib.mjs` 的 `titleSim()` + `03_filter.mjs` 的标题相似排除（走 Zotero API，不再碰 sqlite——直读库文件曾引发崩溃） |
| `pdf_boost.py` 的 Optica OE / MDPI 直链构造 | `lib.mjs` 的 `directPdfCandidates()`，内置于 `07_attach_pdfs.mjs` |
| `botda_collect.py` 的 `to_bibtex()` / `make_key()` | `lib.mjs` 的 `toBibtex()` / `bibKey()`，`08_report.mjs` 输出 `references.bib` |
| `finalize.py` 的注记分类 + report.md | `08_report.mjs` + `config.report.categories` + `outputs/<主题>/curated.json` |
| `botda_collect.py` 的 PROBE_DOIS 直取 | `config.search.dois`（02 阶段按 DOI 直取） |
| 36 条人工圈定成果 | `outputs/botda/approved_dois.txt`（由 `tools/migrate_botda.mjs` 机械迁移） |

迁移命令：`node tools/migrate_botda.mjs`（默认读 `C:\Users\Administrator\Desktop\BOTDA_literature`，可传参覆盖）。

## 已知限制

- Zotero 必须处于打开状态，否则本地 API（23119）无响应
- PDF 挂载依赖 Unpaywall 覆盖率 + 内置出版社直链（Optica OE / MDPI），都没有的条目记为 `no-oa`（不是失败）；建议 Zotero 里全选条目右键「查找可用的PDF」兜底
- 标题相似度判定偏保守（公共词 ≥5 且占短标题 80%+），短标题、译名差异大的重复可能漏过——最终以人工审阅为准
- Crossref 对高频请求会限流，`pauseMs` 不要调太小
