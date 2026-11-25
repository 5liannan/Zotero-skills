# manage-items（③）实测复盘：该优化的 12 处

> 实测场景：2026-11-25 对【2-1-3】BOTDA（collectionID=232）跑完整治理——
> **98 条目 / 197 附件（98 PDF + 99 DOCX）**，改前「标题前缀不合规 76」→ 改后 `verify` 全 0 PASS。
> 下列每条都对应真实踩到的问题，附复现与建议，不是设想。

---

## 0. 一句话结论

③ 的**流程设计是对的**（audit → retitle → split → rename → link → verify，dry-run 默认、写库先备份），
但**「生成文件名」与「校验文件名」两套逻辑各自实现**，加上**搬目录不留尾**，
导致一次 apply 跑不干净、还会留下孤儿目录。修好这三点，其余都是打磨。

---

## 1. 已修（本地增强，建议上游采纳）

### 1.1 缺 `--collection` 过滤 —— 只能整库跑

原版所有脚本 `db.items()` 取全库。真实库里 928 条目、789 PDF，而用户只想治理某一个分类；
要么波及 800 多条，要么自己写 SQL。

**改法**：`DB.items(..., collection=None)` 追加
`AND itemID IN (SELECT itemID FROM collectionItems WHERE collectionID=?)`，
各脚本加 `--collection <id>`。

### 1.2 分类标签被写进文件名

条目标题带 `【BOTDA】【SR提高算法】` 这类标签（用户的检索习惯），而 `{title_zh}` 取的就是条目标题：

```
改前  Shen 等 - 2021 - 【BOTDA】【SR提高算法】用反卷积算法提高BOTDA传感器的空间分辨率.docx
改后  Shen 等 - 2021 - 用反卷积算法提高BOTDA传感器的空间分辨率.docx
```

**改法**：新增 `zoterodb.clean_title()`（配置 `strip_title_tags` + `title_tag_pattern`），
**只影响文件名与附件标题，不动条目标题**。

### 1.3 文件名被叠成两层前缀

名字来源（旧文件名 / 旧标题）本身已带 `作者 等 - 年 -`，模板又加一次：

```
Li 等 - 2019 - Li 等 - 2019 - 【BOTDA】单光纤上高度集成的BOTDAXFG传感器….pdf
```

**改法**：渲染前先 `strip_name_prefix()` 循环剥掉 `^.*?\s*等\s*-\s*(?:\d{4}|n\.d\.)\s*-\s*`。
本次仅 BOTDA 分类内就命中 23 个。

### 1.4 `verify` 与 `rename` 的期望文件名算得不一样

`verify.py` 自己拼 `want`（含标签），`rename_attachments.py` 用另一套（去标签），
于是 rename 跑完 verify 仍报 `文件名不合规 124`——**校验器给假警报，会让人不敢 apply**。

**改法**：把 `clean_title()` 提到 `zoterodb.py`，两边共用；判据只有一份。

---

## 2. 建议改（按优先级）

### P0-a `audit.py` 的 `filename_bad` 是死计数

```python
stat = {..., "filename_bad": 0, ...}   # ← 只初始化，全文件再无累加
```

实测 `audit: filename_bad 0`，同时 `verify: 文件名不合规 124`。
审计算法与校验算法必须同源（共用 `want_name()`），否则审计报告是安慰剂。

### P0-b 拆目录后留下孤儿目录

`move_attachment_to_own_dir()` 把附件搬到新 key 目录，**旧目录只剩缓存文件**
（`.zotero-ft-cache` / `jasminum-outline.json`）就地留下。本次一次 apply 制造了 **78 个**这种孤儿目录，
`audit` 的「未登记目录」从 1 跳到 79。

**改法**：搬迁成功后清理旧目录（或按仓库铁律移入 `quarantine_orphan_*`）；
并把「仅剩缓存文件的目录」识别为可清理，而不是普通孤儿。

### P0-c 缺「父条目已删」检测

`itemAttachments` 里有 3 行（11697/11699/11703）的 `parentItemID` 指向已删除条目，
文件还在磁盘上。Zotero 界面不显示，`verify` 也报 PASS，只有
`PRAGMA foreign_key_check` 能查出来。

**改法**：`verify` / `audit` 跑一次 `PRAGMA foreign_key_check`，
把这类行列入「孤儿附件行」清单；清理走隔离区，别硬删。

### P1-d `link_docx.py` 的匹配太脆

按**中文标题**匹配父条目，找不到再做「目录名包含关系」的模糊匹配——
同名/近名论文容易配错，而且配错是静默的。另外它没有 `--collection`。

**改法**：优先 `--map itemID=path`（确定性），`--dir` 模式只做候选清单 + 人工确认；
补 `--collection`。

### P1-e `rename --titles-only` 的 dry-run 输出有误导

它答应了 `xxx.docx -> yyy.docx` 的文件名计划，但 `--titles-only` 根本不改文件。
批量时容易让人以为文件已被改名。

**改法**：`--titles-only` 只打印标题变更；文件名变更单独标注 `[files]`。

### P1-f 幂等要跑到不动点

本次 `--apply` 跑了**两次**才收敛（第一次 177 个，第二次又抓出 23 个双前缀/带标签的）。
原因：第一次渲染把旧名当来源，产生了新的违规名。

**改法**：`--apply` 内部循环到「0 变更」（最多 3 轮），
或提供 `--fixpoint`；并在结束时输出「本次几轮收敛」。

### P2-g `fix_dates` 的年份冲突只「跳过」

```
跳过 287  年份冲突 2016→2015
跳过 294  年份冲突 2012→2011
跳过 3538 无可靠日期
```

一条都没落盘，事后无法追溯。

**改法**：输出 `outputs/date_conflicts.json`（条目、条目年、外部源年、来源），
给用户一张可裁决的表；`--apply --accept-source-year` 才动。

### P2-h 没有 manage-items 自身的测试

`tests/` 只覆盖 storage-quality / repo-hygiene / polish-config / rule-parity，
③ 的 7 个脚本零测试。而本次三个 bug（死计数、双前缀、两套判据）都是**合成 fixture 一行就能测**的。

建议最小集：`test_manage_items.py`
（双前缀渲染、标签剥离、verify↔rename 判据一致、孤儿目录清理、`--collection` 过滤）。

### P2-i `audit` 的「未登记目录」噪音

`.obsidian`、`.zotero-ft-cache` 这类都被算成未登记目录。
按「8 位 key 字符集 `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`」正则过滤，再单独列「非附件目录」。

### P2-j 命名模板默认值与历史命名不一致

默认模板 `{author}等 - {year} - …`（无空格），而库里既有文件是 `Zhou 等 - 2022 - …`（有空格）。
新用户一跑 rename 就把**所有已规范文件**改一遍，纯属制造 churn。

**改法**：默认改成 `{author} 等`，或渲染时对 `等` 两侧空白归一后再比较
（不一致才改名）。

### P2-k 校验与审计口径要写进文档

`verify` 的「文件名不合规」= 与模板渲染结果**完全相等**；
`audit` 的 `filename_bad` = 未实现。
SKILL.md 里写清这两个指标的语义，避免把 PASS 当成「命名美观」。

### P2-l 与根目录 `scripts/manage_zotero_storage.py` 职责重叠

README 同时推荐 `skills/manage-items/*` 与 `scripts/manage_zotero_storage.py`
（结构对齐 + quality 治理），两者都管 storage 一致性。
建议在 SKILL.md 开头写一句分工：**③ = 单机治理流程；根脚本 = CI/批量体检**，
或者把 ③ 的 `audit/verify` 直接调用根脚本同一份实现。

---

## 3. 顺序建议

1. 先做 **P0-a + P1-d 的判据同源**（`want_name()` 只有一份）——这是所有误报的根。
2. 再做 **P0-b 孤儿目录收尾** 与 **P0-c 外键检测**——写库类操作的卫生底线。
3. 然后 **P1-f fixpoint** 与 **P2-h 测试**，把本次踩到的三类问题固化成回归。
4. 其余（e/g/i/j/k/l）随用随改。

---

## 4. 本次实测结果（作为基线）

| 指标 | 改前 | 改后 |
|---|---|---|
| 标题前缀不合规 | 76 | **0** |
| verify 文件名不合规 | 124 | **0** |
| 磁盘缺文件 / 共用目录 / 有 PDF 无译文 | 0 | 0 |
| 未登记目录 | 1 →（apply 后）79 | **1**（`.obsidian`） |
| 孤儿附件行（FK） | 3 | 3（待人工决定） |
| 收敛轮数 | 2 轮 apply | — |
