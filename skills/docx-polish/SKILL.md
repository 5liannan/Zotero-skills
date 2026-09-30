---
name: docx-polish
description: 【补救工具】把**别处给的、外部来源的**旧译文/学术 DOCX 里「未转换的 LaTeX 源码」批量转成 Word 原生公式对象（OMML），并顺带清理高亮残留、规范图注、统一行距缩进、补页眉页码。自己用 translate-import 翻译的文档不需要本技能（构建时已自动规范化）。当用户要求「优化别处给的 docx」「旧译文公式没渲染」「LaTeX 显示成源码」「$...$ 一堆乱码」时使用。触发词：修复旧 docx、外部 docx 优化、公式没显示、LaTeX 转 Word 公式、OMML、$ 乱码。
---

# DOCX 公式与排版优化（LaTeX → OMML）

把「LaTeX 源码当纯文本排」的译文 DOCX，转成带**真·Word 公式对象**的规范文档。

> **定位（2026-09-30 起）：本技能是「外部来源旧 DOCX」的补救工具。**
>
> `translate-import` 的**正常流程已内置终稿规范化**（`scripts/finalize.py`，由
> `build_docx.py` 自动调用）：翻译产出的 DOCX 一落地就是终稿——公式已是 Word 原生
> 公式对象、带页眉页码、图注规范、正文引用可点击跳转、参考文献一致性已校验。
> **自己翻译的文档不需要再跑本技能。**
>
> 只在下面这种情况才用它：拿到的是**别处给的、公式已退化成纯文本 LaTeX** 的旧 DOCX
> （打开一看满屏 `$...$` 和反斜杠）。此时本技能做「LaTeX → OMML 的强制事后补转」——
> 这是它现在唯一的不可替代职责。
>
> 若只是要补页眉页码 / 规范图注 / 加交叉引用，直接跑
> `translate-import/scripts/finalize.py "<docx>"` 更省事：那是同一套规则的正式实现，
> 且已验证幂等。

## 什么时候用它

| 情况 | 用哪个 |
|---|---|
| 自己按「全文精译」翻译新文献 | `translate-import`（构建时自动完成全部规范化，**产物即终稿**） |
| 拿到外部旧 DOCX，公式是纯文本 LaTeX | **本技能**（`run_polish.py` 一键补转） |
| 只需补页眉页码 / 规范图注 / 加交叉引用 | `translate-import/scripts/finalize.py` |

## 快速开始

```bash
pip install -r requirements.txt
# pandoc 必须单独装：conda install -c conda-forge pandoc

# 一键（原地覆盖，自动备份）
python scripts/run_polish.py "译文.docx" --title "文章短标题"

# 先试跑，不动源文件
python scripts/run_polish.py "译文.docx" --dry-run
```

逐步跑（便于排查）：

```bash
python scripts/diagnose.py        "译文.docx"              # 1. 看现状
python scripts/extract_formulas.py "译文.docx" formulas.json   # 2. 抽公式转 OMML
python scripts/optimize.py        "译文.docx" optimized.docx formulas.json  # 3. 重建
python scripts/diagnose.py        optimized.docx           # 4. 验收
python scripts/verify_word.py     optimized.docx --expect-omath 153 --pdf out.pdf  # 5. Word 权威校验
```

### 用配置文件固定排版（不再每次敲一堆旗标）

`run_polish.py` 会读配置：

```bash
cp config.example.json config.json   # 改字体/字号/页眉等
python scripts/run_polish.py "译文.docx"        # 自动用上
python scripts/run_polish.py "译文.docx" --config ~/my.json   # 或临时指定
```

优先级：`--config` > `$DOCX_POLISH_CONFIG` > `<技能根>/config.json` >
`<技能根>/config.example.json`；**命令行参数仍然高于配置文件**。
`_` 开头的键是说明文字，不参与转发。

| 配置键 | 转发给 `optimize.py` |
|---|---|
| `ea_font` / `latin_font` / `body_size` / `header_size` | 字体字号 |
| `indent_chars` / `line_spacing` / `margin` / `top_margin` / `center_first` | 缩进行距边距 |
| `title` / `header` / `page_number` | 页眉标题、是否写页眉页码 |
| `pandoc` / `no_word_check` / `backup_suffix` | 依赖与流程 |

> `backup_suffix` 写 `bak_YYYYMMDD` 会被解析成当天日期（也可写 strftime 格式串如
> `bak_%Y%m%d_%H%M`）；直接写字面量则原样当后缀。

## 核心技术：pandoc 能产 OMML

**这是本技能的关键。** 不需要 latex2mathml / sympy / MathType，
pandoc 就能把 LaTeX 转成 Word 原生 OMML：

```bash
printf '$$E=mc^2 + \\frac{\\alpha_2}{\\beta}$$' > t.md
pandoc t.md -o t.docx        # 产出 <m:oMath ...>，可移植进已有文档
```

Windows 上 pandoc 常在 `D:\Anaconda3\Library\bin\pandoc.exe`（Anaconda 自带）。
先 `where pandoc` / `which pandoc` 确认；没有就 `conda install -c conda-forge pandoc`。

**送 pandoc 之前必须剥掉两端定界符。** 若 LaTeX 自带 `$$...$$`，直接送会变成
`$$$$...$$$$`，pandoc 报 `no oMath produced`。剥法定界符 + 摘式号一步到位：

```python
LEAD_DELIM_RE = re.compile(r"^\s*\${1,2}\s*")
TAIL_DELIM_RE = re.compile(r"\s*\${1,2}\s*$")

def strip_delims(latex):
    t = (latex or "").strip()
    t = LEAD_DELIM_RE.sub("", t)
    t = TAIL_DELIM_RE.sub("", t)
    return t.strip()
```

取出 OMML 并塞进现有段落：

```python
from lxml import etree
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
root = etree.fromstring(para_xml.encode("utf-8"))
for el in root.findall(".//{%s}oMath" % M_NS):
    target_para._element.append(copy.deepcopy(el))   # 必须 deepcopy
```

**必须 deepcopy**，否则同一元素被多处引用会丢失。

> 同一仓库的 `translate-import` 也有个 `scripts/omml.py`，是**逐块构建时**用的转换器
> （带缓存、失败降级）。两者的定位不同：那边在新译文构建时把 LaTeX 转成公式对象；
> 这边在事后批量修复旧文档。需要写新流程时可以互相参考。

## 处理规则

| 对象 | 处理 |
|---|---|
| 全部 run | 清 `w:highlight` 与 `w:shd` |
| 行间公式段 | 清空 run → 追加 OMML；有式号则加**右对齐制表位**（宽度=版心宽）放 `\t(2.1)`；无式号则整段居中 |
| 行内公式段 | 按 `$` 切分，交替插入文本 run 与内联 OMML |
| 图注 | 正则 `^\s*图\s*(\d+)\s*[.．:：]?\s*(.*)$`，**且题注正文不得以「给出/显示/展示/表明/说明/可见/反映/描绘/绘制/示意/标注」开头**（否则是正文引用句）→ 规范为「图 N　题注」（全角空格），9pt 居中，前后留间距。**反向也修**：这类正文引用句若已被排成图注样式（居中 / 小字号），恢复为正文样式（两端对齐 + 缩进 2 字符 + 正文行距） |
| 图片源文件残留标记 | 形如「原文图 p07_02.png」的孤立段（正则 `^(原文图\|原始图\|原图\|图片\|图源)\s*[:：]?\s*\S+\.(png\|jpg\|...)$`）→ **整段删除**；以「图 N」开头的不删 |
| 正文 | 1.5 倍行距、首行缩进 `Pt(21)`（=2 字符）、两端对齐 |
| 参考文献 | 首行缩进归零、左对齐 |
| 标题 | H1 14pt / H2 12pt，黑色加粗 |
| 页眉 | 文章短标题，9pt 居中 |
| 页脚 | PAGE 域，9pt 居中 |

**式号必须在送 pandoc 之前剥离**（`extract_formulas.py::split_num`）。
若把 `\quad (2.1)` 留给 pandoc，它会被排进 OMML，之后你再右对齐渲染一次式号，
结果同一式号出现两遍：`(2.1) …… (2.1)`。

**图注 vs 正文引用**：`图 1：给出菲佐干涉仪原理示意。` 和 `图 1：菲佐干涉仪原理示意。`
都匹配 `CAP_RE`，但前者是正文（「图1给出了…」），后者才是图注。
判据：题注主体若以动词开头（给出/显示/展示/表明/说明/可见/反映/描绘/绘制/示意/标注），
判为正文，不加全角空格、不居中。**不要把「由/为/是/如」列入**——它们是图注常见起笔
（如「由四个方位的测量反演得到的廓线」）。

**反向也要修**：外部旧文档里，上游流水线常把**所有**「图 N」开头的段落都当图注排，
于是「图 1 给出了…」这类正文被排成居中 9pt。脚本会把它恢复成正文样式。

> **规则有两份，改一处必须改两处。** 上面这套图注/正文判定在
> `translate-import/scripts/finalize.py` 里还有一份（那是构建时的"正式版"）。
> 本技能会被**单独安装**到 `~/.workbuddy/skills/docx-polish/`（那份里没有
> `translate-import`），跨技能 import 会让已安装副本直接崩，所以只能各存一份。
> 一致性由 `tests/test_rule_parity.py` 盯着：正则、常量、判定行为逐项比对，
> 漂移就让 CI 变红。改这里的 `CAP_RE` / `CAP_VERB_RE` / 字号常量，
> 请同步改 `finalize.py`。
判据是「形似图注 **且** 当前确实排成图注样（居中，或字号明显小于正文）」——
所以正常正文段落不会因为开头恰好是「图 9 展示了…」而被误改。
统计里体现为 `prose_restyled`。`finalize.py`（translate-import 侧）行为一致。

**图片源文件残留标记**：翻译流水线常在图片段与图注段之间留下一行
`原文图 p07_02.png`。它无正文价值，应整段删除（`p._element.getparent().remove(p._element)`）。
删除后段落总数会相应减少，这是预期行为。

**PAGE 域不能靠 `add_run("PAGE")` 文本**，要构造 fldChar：

```python
for typ, text in (("begin", None), (None, " PAGE "), ("end", None)):
    if typ:
        el = run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): typ})
    else:
        el = run._element.makeelement(qn("w:instrText"), {})
        el.text = text
    run._element.append(el)
```

## 交叉引用（参考文献可点击跳转）

`scripts/add_xref.py` 给文献条目加隐藏书签、把正文 `[5]` / `[5, 6]` 换成指向书签的
内部超链接（`<w:hyperlink w:anchor="_RefList5">`）：

```bash
python scripts/add_xref.py in.docx out.docx                      # 保持正文字体外观
python scripts/add_xref.py in.docx out.docx --hyperlink-style    # 蓝色下划线，一眼可见
```

默认**不**套用 Hyperlink 样式，与 Word 原生交叉引用外观一致（黑、无下划线、可点击）。
编号文本一律不动，公式对象不受影响。

### 三种实现方式（均已实测）

| 方式 | 文献列表外观 | 分组引用 `[5, 6]` | 增删条目自动重编号 | 点击跳转 |
|---|---|---|---|---|
| 超链接（本脚本） | 不变 | ✅ | ❌ | ✅ |
| `SEQ` 域 + 书签 + `REF \h` | 不变 | ✅ | ✅（新条目须带 SEQ 域） | ✅ |
| 自动编号列表 + `REF \r \h` | 变成不带方括号的 `1` | ⚠️ 实现别扭 | ✅ | ✅ |

**关键实测 —— 它决定了上表第 3 行为什么要牺牲外观**：
`{ REF _RefN \r \h }` 的输出**包含列表编号格式里的全部字面文本**。
编号格式设成 `[%1]` 时，域结果就是 `[1]` 而非 `1`；正文若再手写一对方括号
就成了 `[[1]]`，多篇挤在一起则是 `[[5], [6]]`。
⇒ 想用 `\r` 支持分组引用，必须把列表编号格式改成不带方括号的 `%1`。

**`\h` 的跳转不会落成 `w:hyperlink`**：`REF … \h` 的链接由 Word 在渲染期生成，
`doc.Hyperlinks.Count` 仍为 0，XML 里也搜不到 `<w:hyperlink>`。
判断它是否生效要看**导出 PDF 里的 GOTO 链接注释**（`page.get_links()`）。
而 `add_xref.py` 用的是真 `w:hyperlink` 元素，`doc.Hyperlinks.Count` 会如实计数。

**python-docx 的 `Paragraph.text` 不含 `w:hyperlink` 里的 run**：转换后的段落用它读会
**整段丢掉引用标记**（且不报错）。验收必须用：

```python
text = "".join(t.text or "" for t in p._p.iter(qn("w:t")))
```

## 验证（必须做到）

**权威判据 —— 让 Word 自己数公式对象：**

```python
import win32com.client
w = win32com.client.Dispatch("Word.Application"); w.Visible = False
doc = w.Documents.Open(path)
print("OMaths:", doc.OMaths.Count)   # 必须等于预期公式数
```

这比数 XML 里的 `<m:oMath>` 更可信：只有 Word 真认成公式对象，
`OMaths.Count` 才对得上。`scripts/verify_word.py` 已封装，还能顺手导出 PDF。

`scripts/diagnose.py` 断言：
- highlight 残留 == 0
- 段落含 `$` == 0
- 段落含裸 LaTeX 命令 == 0
- OMML 对象数 > 0
- 图片数、段落数与原件一致

**目视复核**：`verify_word.py --pdf out.pdf` → `pymupdf` 渲染 PNG → 逐页看。
重点看公式页（分式/积分/希腊字母是否正确）、图注页、参考文献页。

## 安全约定

- 改用户文件前**先备份并校验**：`shutil.copy2` 后比对 **字节数 + md5**，两者都一致才算成功
- 备份名带日期后缀（`.bak_YYYYMMDD`），同名时自动加时间戳避免覆盖
- **先做完全部工作再写回**：任何一步失败，源文件保持原样（`run_polish.py` 的顺序保证）
- 用户文档路径含中文时，全程用 Python 传参，不要用 shell 拼接

## 踩坑清单

- **Bash 工具里 `python -c` 带反斜杠正则会被 shell 吃掉**（`re.error: bad escape \q`）
  → 写成 `.py` 文件再跑，别用 `-c` 内联
- **PowerShell 的 here-string `@'...'@` 用在 Bash 工具里**会把字面 `@` 写进内容
  → 长文本先 `Write` 成文件再引用（如 `git commit -F file`）
- **pandoc 临时文件要在 `finally` 里删掉**，否则残留 `_f.md` / `_f.docx`
- **OMML 元素复用务必 `copy.deepcopy`**
- **Word COM 首调可能报 RPC 失败**（`-2147023170 远程过程调用失败`），此时 `w.Quit()`
  还会因 `__getattr__` 抛 AttributeError。**过一会儿重试即可**。所以必须对
  Dispatch / Open / ComputeStatistics / Close / Quit **逐层 try 包裹**；
  `ComputeStatistics` 要单独 try —— 页数字数读不到不该影响公式判定
- Word COM 用完必须 `doc.Close(False)` + `w.Quit()`，否则残留 WINWORD.EXE 进程
- **Word 开着文档时会持有锁文件 `~$xxx.docx`**，且会阻碍写回/删除。脚本里删临时文件
  若报 `trash-failed` 但能确认 Word 已退出，重试一次即可

## 文件说明

```text
docx-polish/
  SKILL.md                技能说明（本文件）
  README.md               使用说明（给人看）
  config.example.json     配置示例（全项可选）
  requirements.txt        依赖
  scripts/
    run_polish.py         一键编排（诊断→抽取→重建→校验→备份写回）
    diagnose.py           诊断/验收：统计各项指标并判定
    extract_formulas.py   抽取 LaTeX → pandoc → OMML，产出 formulas.json
    optimize.py           以原文档为基底逐段重建，产出 optimized.docx
    add_xref.py           给文献列表加书签、正文引用换内部超链接（可点击跳转）
    verify_word.py        Word COM 权威校验 OMaths.Count + 导出 PDF
```
