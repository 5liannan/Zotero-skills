# lit-workflow — 文献检索与 Zotero 导入通用工作流

配置驱动的八阶段文献流水线：从摸底现有库、抓取候选、规则筛选，到人工圈定、入库、挂全文、出报告。
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

05 和 06 是两条并行的入库路线：想手动确认就走 05 导 RIS 拖进 Zotero，想全自动就走 06 走 API。
07 和 08 都可选。

## 关键设计（每条都是实战踩坑换来的）

- **断点续跑**：02 重跑自动合并旧候选池；06/07 跳过已成功条目，失败修复后重跑只补失败项
- **逐条入库**：06 默认一条一个 session，失败只影响那一条——全量 POST 一旦翻车，排查成本极高
- **过程留痕**：每组查询的命中数落盘 `candidates_meta.json`，不再有"只往终端打印、跑完就丢"的轮次
- **人工检查点**：03 → 04 之间必须人审；`approved_dois.txt` 每行一个 DOI、`#` 可注释，本身就是版本可控的决策记录
- **库内去重双保险**：03 先按 DOI 精确排除，再按标题词相似度排除，专治"DOI 不同实为同一篇"（预印本 / 多版本）。默认阈值 0.9 偏保守，被排除的明细写进 `filter_report.json` 的 `simExcluded` 供复查；`filter.simInLibrary: false` 可关闭
- **导入与挂全文分离**：06 只入库、07 才挂 PDF 且全程串行——在入库高峰并发下载附件会把 Zotero 拖崩，有数据库损坏风险
- **只走 Zotero API，绝不直读 `zotero.sqlite`**：直接读写库文件（哪怕只是复制出来读）都可能触发锁冲突和数据库损坏
- **出版社直链兜底**：Unpaywall 覆盖不到的 Optica Optics Express / MDPI 条目，按 DOI + 卷期页直接构造 PDF 直链
- **人工注记驱动报告**：把审阅时的一句话注记写进 `outputs/<主题>/curated.json`（`[{doi, note}]`），08 按注记关键词自动分类生成报告
- **零依赖**：只用 Node 内置模块（fs + 全局 fetch），无 npm install

## 快速开始（新主题三步）

要求 Node >= 18，且 Zotero 桌面端处于打开状态。运行方式统一为 `node src/<脚本>.mjs <主题>`。

1. 复制 `config.example.json` 为 `topics/<主题>.json`，填关键词与筛选规则
2. 依次跑 `01` → `02` → `03`，审阅 `filtered_main.json`，把选中的 DOI 写进 `outputs/<主题>/approved_dois.txt`（顺手写一句话注记到 `curated.json` 更好）
3. 跑 `04` → `05`（导 RIS 手动拖 Zotero），或 `06`（API 直接入库）→ `07`（挂 PDF）→ `08`（出报告 + BibTeX）

```bash
node src/01_baseline.mjs mytopic
node src/02_search.mjs   mytopic
node src/03_filter.mjs   mytopic
# ... 人工审阅，写 outputs/mytopic/approved_dois.txt ...
node src/04_finalize.mjs mytopic
node src/06_import.mjs   mytopic      # 或 05_export_ris.mjs 走手动路线
node src/07_attach_pdfs.mjs mytopic
node src/08_report.mjs   mytopic
```

## 目录结构

```
src/                 八个阶段脚本 + lib.mjs（共享工具：Zotero/Crossref 客户端、相似度、BibTeX）
topics/<主题>.json    每个研究方向一份配置，脚本本身不含任何主题知识
outputs/<主题>/       该主题的全部中间产物与成果（脚本自动创建）
config.example.json  配置模板，复制改名即用
AGENT.md             Agent 执行剧本（含两个人工检查点的处理方式）
```

`outputs/` 与 `topics/` 默认只保留占位文件——主题配置和数据都属于使用者，不随模板分发。

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
    "simInLibrary": true,                  // 标题相似度排除库内已有（默认 true）
    "simThreshold": 0.9,                   // 相似度阈值，调低更激进（0.8 容易误伤同主题不同论文）
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
  { "doi": "10.1000/example.001", "note": "首次提出该方法，奠基性经典" },
  { "doi": "10.1000/example.002", "note": "近五年综述，覆盖主流技术路线" }
]
```

## Agent 执行剧本

见 [AGENT.md](AGENT.md)。Agent 按剧本自动跑 01–03、04–08，在两个检查点停下来等用户确认。

## 已知限制

- Zotero 必须处于打开状态，否则本地 API（23119）无响应
- PDF 挂载依赖 Unpaywall 覆盖率 + 内置出版社直链（Optica OE / MDPI），都没有的条目记为 `no-oa`（不是失败）；建议 Zotero 里全选条目右键「查找可用的PDF」兜底
- 标题相似度判定偏保守（公共词 ≥5 且占短标题 90%+），短标题、译名差异大的重复可能漏过——最终以人工审阅为准
- Crossref 对高频请求会限流，`pauseMs` 不要调太小
- 检索源目前只有 Crossref，不覆盖无 DOI 的会议论文、学位论文与部分中文期刊
