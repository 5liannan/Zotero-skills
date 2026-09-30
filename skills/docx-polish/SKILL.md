---
name: docx-polish
description: 把中文译文/学术 DOCX 里「未转换的 LaTeX 源码」批量转成 Word 原生公式对象（OMML），并顺带清理高亮残留、规范图注、统一行距缩进、补页眉页码。当用户要求「优化翻译好的 docx」「公式没渲染」「LaTeX 显示成源码」「$...$ 一堆乱码」「给译文排版」时使用。触发词：优化 docx、docx 排版、公式没显示、LaTeX 转 Word 公式、OMML、$ 乱码、译文美化。
---

# DOCX 公式与排版优化（LaTeX → OMML）

把「LaTeX 源码当纯文本排」的译文 DOCX，转成带**真·Word 公式对象**的规范文档。

> 与 `translate-import` 的关系：那边负责**产出**译文 DOCX；
> 这边负责**事后补救**——当译文里的公式是纯文本 LaTeX 时，转成可编辑的 Word 公式。

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

## 核心技术：pandoc 能产 OMML

**这是本技能的关键。** 不需要 latex2mathml / sympy / MathType，
pandoc 就能把 LaTeX 转成 Word 原生 OMML：

```bash
printf '$$E=mc^2 + \\frac{\\alpha_2}{\\beta}$$' > t.md
pandoc t.md -o t.docx        # 产出 <m:oMath ...>，可移植进已有文档
```

Windows 上 pandoc 常在 `D:\Anaconda3\Library\bin\pandoc.exe`（Anaconda 自带）。
先 `where pandoc` / `which pandoc` 确认；没有就 `conda install -c conda-forge pandoc`。

取出 OMML 并塞进现有段落：

```python
from lxml import etree
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
root = etree.fromstring(para_xml.encode("utf-8"))
for el in root.findall(".//{%s}oMath" % M_NS):
    target_para._element.append(copy.deepcopy(el))   # 必须 deepcopy
```

**必须 deepcopy**，否则同一元素被多处引用会丢失。

## 处理规则

| 对象 | 处理 |
|---|---|
| 全部 run | 清 `w:highlight` 与 `w:shd` |
| 行间公式段 | 清空 run → 追加 OMML；有式号则加**右对齐制表位**（宽度=版心宽）放 `\t(2.1)`；无式号则整段居中 |
| 行内公式段 | 按 `$` 切分，交替插入文本 run 与内联 OMML |
| 图注 | 正则 `^\s*图\s*(\d+)\s*[.．:：]?\s*(.*)$` → 规范为「图N  题注」，9pt 居中，前后留间距 |
| 正文 | 1.5 倍行距、首行缩进 `Pt(21)`（=2 字符）、两端对齐 |
| 参考文献 | 首行缩进归零、左对齐 |
| 标题 | H1 14pt / H2 12pt，黑色加粗 |
| 页眉 | 文章短标题，9pt 居中 |
| 页脚 | PAGE 域，9pt 居中 |

**式号必须在送 pandoc 之前剥离**（`extract_formulas.py::split_num`）。
若把 `\quad (2.1)` 留给 pandoc，它会被排进 OMML，之后你再右对齐渲染一次式号，
结果同一式号出现两遍：`(2.1) …… (2.1)`。

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
    verify_word.py        Word COM 权威校验 OMaths.Count + 导出 PDF
```
