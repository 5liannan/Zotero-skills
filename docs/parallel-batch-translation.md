# 多篇并行翻译编排（批量 · 子代理流水线）

单篇流程见 [`SKILL.md`](../skills/translate-import/SKILL.md) 的「单篇」一节。
本文只讲**一次要翻十几到几十篇时**怎么并行、怎么防止"假完成"、怎么收尾记账。

> 实测规模：24 篇按本流程 8 路并行，约 4.5 小时全部交付（单篇 20–90 分钟）；
> 后续 7 篇（含 1 次夜间中断后的接手）同样一次通过。所有产物 `verify ok=true`。

## 1. 为什么不能"一个 Agent 逐篇做"

- 单篇 20–90 分钟，串行 24 篇要十几个小时；并行 8 路后墙钟时间≈最慢那篇。
- 但并行会引入三类只有编排层才能兜住的风险：
  1. **假完成**：子代理报告 "completed"，实际 parts 为空、docx 不存在；
  2. **重复记账**：同一完成消息触发两次记账，计数虚增、PROGRESS 出现重复行；
  3. **中途失联**：会话重启后团队被回收，半成品留在工作目录里。

下面的流程就是围绕这三点设计的。

## 2. 角色与目录约定

```
<work_base>/
├── WORKFLOW.md                 # 唯一流程手册，所有子代理开工前必读（模板见 examples/WORKFLOW.template.md）
├── PROGRESS.md                 # 总台账（人看的）：已完成表 + 待办 + 每篇坑点说明
├── status_oc.json              # 机读台账：{itemID: {status, docx, attachment_key, ...}}
└── work/<item_ITEMID>/
    ├── extract.json            # 提取产物
    ├── figs/ figures/ formulas/
    ├── parts/01.json …         # 译文分片
    ├── <中文标题>.docx          # 交付物
    └── report.json             # 完成凭证（见 §4）
```

- **主控（编排层）**：分派任务、监控、一条命令记账挂接、收尾审计。不直接翻译。
- **子代理**：一人一篇，只负责 extract → parts → build → verify → report.json。
  禁止挂接 Zotero、禁止改 PROGRESS/status（否则并发写坏台账）。

## 3. 分派：让每个子代理"自包含"

子代理看不到主控的对话，提示词必须写全。最小模板：

```text
【任务】把一篇英文论文 PDF 完整翻译为中文 Word（.docx），保留全部图/表/公式/参考文献，直到校验通过。

【第一步】读取流程手册并严格遵守：<work_base>/WORKFLOW.md
（其中"挂接 Zotero"与"更新 PROGRESS.md/status_oc.json"步骤一律跳过，由主控统一处理。）

【本篇信息】
- 任务清单 itemID：<ID>
- PDF：<绝对路径>
- 中文标题：<标题>
- 工作目录：<work_base>/work/item_<ID>/（自建 figs/parts/images/figures/formulas）
- 输出 docx：<工作目录>/<中文标题>.docx
- 生成脚本：<scripts_dir>/gen_<ID>.py（唯一名，勿动他人文件）

【质量要求】全文完整翻译；check_parts / build_docx / verify_docx 全通过
（verify ok=true 且 dangling/unused 为空）；遵守手册"已知坑"。

【约束】不挂接 Zotero；不改 PROGRESS.md / status_oc.json / WORKFLOW.md。
Zotero sqlite 只读查询：复制为 _lk_<ID>.sqlite 再查，用完删除。
完成后写 <工作目录>/report.json（格式见手册末尾）。
【重要】必须产出 docx 和 report.json 并自检存在后才算完成。

【汇报】只需：真实 itemID、docx 路径、页数/字数/图/式/表/文献数、verify 结果、坑（每条一句）。
```

要点：

- **生成脚本用唯一文件名**（`gen_<ID>.py`）。多个子代理共用 `gen.py` 会互相覆盖，
  表现为"构建成功但内容是别人的稿"。
- **临时 sqlite 用唯一名**（`_lk_<ID>.sqlite`），查完即删。
- **标题与 PDF 路径给绝对路径**，子代理不要去任务清单里猜。

## 4. 完成凭证：只认文件，不认"completed"

子代理完成时必须在工作目录写 `report.json`：

```json
{
  "itemID": 11847,
  "title": "基于主梁应变与吊索张力时空相关性的桥梁吊索张力识别方法",
  "docx": "E:/.../work/item_11847/基于主梁应变与吊索张力时空相关性的桥梁吊索张力识别方法.docx",
  "pages": 18, "chars": 8600,
  "figures": 31, "equations": 31, "tables": 1, "refs": 68,
  "zotero_real_itemID": 11847,
  "zotero_sibling_itemIDs": [11256],
  "notes": "同文条目 11256"
}
```

主控收到完成通知后的**唯一动作顺序**：

1. `ls` 工作目录 + 读 `report.json` —— **两者齐全才继续**；
2. 用 `scripts/record_done.py report.json` 记账 + 挂接（§6）；
3. 补位：从待办里再起一篇，保持并行度。

### 三种真实故障与处置

| 故障 | 现象 | 处置 |
|---|---|---|
| **空转退出** | 通知 completed，但 parts 为空、无 docx/report（只跑了 extract） | `SendMessage` 明确列出缺失物、要求"不要重做提取裁图，从 parts 继续"；代理会接着干 |
| **忘写 report** | docx 存在且 verify 可过，但没有 report.json | 主控自己跑 `verify_docx.py` 确认 ok 后，代写 report.json（条目统计取 verify 数字），再记账 |
| **中途失联** | 会话重启/团队回收，代理不存在 | `SendMessage` 会报 "Not in a team"；直接新起一个代理，提示词写"接手完成：已有 extract/figs/parts 中间产物，**不要重做提取裁图**"，其余同上 |

> 空转是批量场景最常见的失败模式（本次 30+ 篇里出现 2 次）。判断方法很简单：
> 看工作目录里有没有以标题命名的 `.docx`、有没有 `report.json`。有这个检查，
> 就不会把空稿记进台账。

## 5. 并行度与补位

- 并行上限按机器/额度定，实测 **8 路**稳定；再多收益递减且故障处理会排队。
- **完成一篇立即补一篇**，不要等一批跑完再发下一批（尾部长尾会被摊平）。
- 收尾时按"待办列表耗尽"结束，而不是按"代理空闲"结束。

## 6. 记账与挂接：一条命令

```bash
python scripts/record_done.py work/item_11847/report.json [更多 report.json ...] \
    --work-root /path/to/work_base
```

它做四件事（全部幂等）：

1. 校验 report 里 docx 实际存在（假完成直接拒绝）；
2. 更新 `status_oc.json`（默认 `cfg.status_json`）；
3. 更新 `PROGRESS.md`：计数 +1、追加表格行与说明；**同一 itemID 已存在则跳过**
   （防重复记账，见 §4 表格第三类故障）；
4. 调 `attach_docx.py` 把 docx 挂到主条目 + `zotero_sibling_itemIDs` 全部条目。

### 同文重复条目：一次翻译，多处挂接

Zotero 库里常见同一篇论文有两条（英文条目带 PDF、中文条目标题已译好但无 PDF），
或者干脆 3 条（如 `11860`/`11052`/`11493`）。做法：

1. 用 `audit_collection.py` 的 **DOI 重复聚类**找出同文条目；
2. 选 PDF 所在条目为主条目翻译；
3. report 的 `zotero_sibling_itemIDs` 列出全部同文条目；
4. `record_done.py` 会把同一份 docx 幂等挂到每个条目（各占独立 storage 目录）。

下游再跑 `manage-items` 做去重/隔离时不会误伤。

## 7. 收尾审计：不信任台账

交付后用 `scripts/audit_collection.py` 独立扫库对账：

```bash
python scripts/audit_collection.py --collection "DOFS-信号处理" --out AUDIT.md
```

它按文件名索引 `storage/` 核附件是否真实存在（`itemAttachments.path` 不含子目录，
直接拼路径必然全判缺失），输出：

- 已挂译文 / 有 PDF 未译 / 无 PDF 三类清单；
- 台账一致性（已挂但不在台账、台账有但无附件、附件记录缺文件）；
- DOI 重复聚类（区分"已译/未译"，用来发现"英文条目未译但中文兄弟已译"的假待办）。

审计结论应回写 `PROGRESS.md` 的待办区——台账只反映"发过任务的那些"，不代表全库。

## 8. 编排层的坑（与本流程直接相关）

| 坑 | 现象 | 对策 |
|---|---|---|
| 同 ID 重复记账 | PROGRESS 出现两行同 itemID、计数 +2 | `record_done.py` 按 itemID 去重；发现重复手删一行并把计数改回 |
| 子代理共享脚本名 | 内容串稿 | `gen_<ID>.py` 唯一命名 |
| 子代理忘记附件 key | PROGRESS 表格 key 列是 `?` | 记账后从库回填：按 parent + 文件名查 `itemAttachments` |
| 完成通知与消息各触发一次 | 同一篇被记两次 | 记账脚本幂等；主控对重复通知只做"已处理"确认 |
| 报告标题与 PDF 不符 | 代理按 PDF 内容翻译但 docx 标题用了清单标题 | 分派前核对 PDF 首页标题；不符时以 PDF 为准并在 report.notes 注明 |

## 9. 单篇内部仍需遵守

并行不改变单篇的质量门槛：`check_parts` 0 error → `build_docx` 成功 →
`verify_docx` `ok=true` 且 `dangling`/`unused` 为空。常见翻译坑（区间引用展开、
`[0, 1]` 数组误判引用、表注 `cap()`、跨栏公式全宽渲染、图注不得含 `$` 等）
见 SKILL.md「已知坑」与 `docs/layout-probe-and-figures.md`。
