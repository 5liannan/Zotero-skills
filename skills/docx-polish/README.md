# docx-polish — 译文 DOCX 公式与排版优化

把「LaTeX 源码当纯文本排」的中文译文 DOCX，转成带**真·Word 公式对象**的规范文档。

## 什么时候用它（先看这个）

| 你的情况 | 该用哪个 |
|---|---|
| **新翻译**一篇文献 | **`translate-import`** —— 它构建 DOCX 时已把 LaTeX 转成公式对象，产出即正确，**不用本工具** |
| 拿到**别处给的旧 DOCX**，公式是一堆 `$` 和反斜杠 | **本工具** |
| 需要批量清高亮残留、规范图注、补页眉页码 | **本工具** |
| 译文**丢了参考文献/正文引用**，要按原文补全 | 见 `translate-import` 的验收清单；本工具的 `add_xref.py` 负责补完后加可点击跳转 |
| 想让正文 `[5]` 点一下跳到文末文献 | **本工具的 `add_xref.py`** |

本工具是**修复工具**，不属于翻译流程。

## 它解决什么问题

旧的译文 DOCX 里，公式可能是这样的纯文本：

```text
$E = mc^{2}$                       ← 显示成源码，不是公式
$$\frac{\partial u}{\partial t} = \nabla^{2} u \quad (2.1)$$
```

在 Word 里打开就是一堆 `$` 和反斜杠。本工具把它们转成**可双击编辑的 Word 原生公式对象**，
同时清掉上一环节留下的黄色高亮、规范图注、统一行距缩进、补上页眉页码。

> 注：`translate-import` 现在已在构建阶段做这件事，所以只有**旧文档**才需要本工具。

## 安装

```bash
pip install -r requirements.txt

# pandoc 是外部依赖，pip 装不了：
# Windows: conda install -c conda-forge pandoc
# macOS:   brew install pandoc
# Linux:   apt install pandoc
```

## 用法

### 一键（推荐）

```bash
python scripts/run_polish.py "相干瑞利-布里渊散射：分子间势能和啁啾率的影响.docx" \
    --title "相干瑞利-布里渊散射"
```

自动完成：诊断基线 → 抽取转 OMML → 重建排版 → 验收 → Word 校验 → 备份 → 原地写回。

**先试跑**（不碰源文件）：

```bash
python scripts/run_polish.py "译文.docx" --dry-run
```

### 分步（便于排查）

```bash
# 1. 看现状：有多少未转换公式、多少高亮残留
python scripts/diagnose.py "译文.docx"

# 2. 抽公式并转 OMML（Windows 上 pandoc 不在 PATH 时加 --pandoc）
python scripts/extract_formulas.py "译文.docx" formulas.json \
    --pandoc "D:/Anaconda3/Library/bin/pandoc.exe"

# 3. 重建文档
python scripts/optimize.py "译文.docx" optimized.docx formulas.json \
    --title "文章短标题"

# 4. 验收
python scripts/diagnose.py optimized.docx

# 5. Word 权威校验 + 导出 PDF 目视复核
python scripts/verify_word.py optimized.docx --expect-omath 153 --pdf out.pdf
```

## 参数

`optimize.py` / `run_polish.py` 支持：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--title` | 首段 | 页眉标题 |
| `--no-header` | — | 不写页眉 |
| `--no-page-number` | — | 不写页码 |
| `--ea-font` | 宋体 | 中文字体 |
| `--latin-font` | Times New Roman | 西文字体 |
| `--body-size` | 10.5 | 正文字号(pt) |
| `--header-size` | 9 | 页眉页脚字号 |
| `--indent-chars` | 2.0 | 首行缩进字符数 |
| `--line-spacing` | 1.5 | 行距倍数 |
| `--margin` | 2.5 | 左右页边距(cm) |
| `--top-margin` | 2.4 | 上下页边距(cm) |
| `--center-first` | 4 | 前 N 段视为标题区，不缩进 |
| `--no-word-check` | — | 跳过 Word COM 校验 |
| `--no-backup` | — | 不备份（不推荐） |

## 输出

| 文件 | 内容 |
|---|---|
| `formulas.json` | 抽取结果 + 每个公式的 OMML，失败项记 `err` 不静默丢 |
| `optimized.docx` | 重建后的成品 |
| `<源文件>.bak_YYYYMMDD` | 源文件备份（写回前自动生成并校验） |

工作目录默认 `<源文件同级>/_polish_work/`，可用 `--workdir` 改。

## 加交叉引用（参考文献可点击跳转）

译文正文里的 `[5]`、`[5, 6]` 可以变成**可点击的内部跳转**，点了直接跳到文末对应文献：

```bash
# 保持正文字体外观（与 Word 原生交叉引用一致：黑、无下划线、可点击）
python scripts/add_xref.py in.docx out.docx

# 想要一眼看出可点击，套用蓝色下划线
python scripts/add_xref.py in.docx out.docx --hyperlink-style
```

它做两件事：给每条文献加隐藏书签 `_RefList1…N`，再把正文引用标记换成指向书签的
`<w:hyperlink>`。**编号文本一律不动**，公式对象不受影响。

> 注意：这是「只加跳转、不自动重编号」的轻量方案 —— 编号仍是死文本，增删文献需要
> 自己维护。要自动重编号得用域（`SEQ` 或 Word 自动编号），各自的取舍见 `SKILL.md`
> 的「交叉引用」一节（三种方式均已实测）。

验收要同时看三样：

| 检查 | 命令 / 判据 |
|---|---|
| Word 认到几个超链接 | `doc.Hyperlinks.Count` = 预期链接数 |
| 文本是否原样 | 用 `''.join(t.text for t in p._p.iter(qn('w:t')))` 比对（**`Paragraph.text` 会漏掉超链接里的 run**） |
| 跳转是否真的生效 | 导出 PDF 后 `page.get_links()`，GOTO 注释数 = 链接数，目标页正确 |

## 安全设计

1. **源文件最后一步才动** —— 前面任何一步失败，源文件保持原样
2. **备份双校验** —— `shutil.copy2` 后比对字节数 + md5，一致才写回
3. **备份名带日期** —— 同名已存在时自动加时间戳，避免二次备份覆盖
4. **失败不静默** —— 公式转换失败会打印 `[FAIL] para N: <原因>` 并保留原文

## 限制

- **只处理 `$...$` / `$$...$$` 定界的 LaTeX**。若译文里公式是 `\(...\)` 或 `\begin{equation}`
  等其他定界，需先改 `extract_formulas.py` 里的 `DISPLAY_RE` / `INLINE_RE`
- **公式要在单个段落内**。跨段的 LaTeX 无法识别
- **Word 校验需 Windows + 装 Word + pywin32**。其他平台用 `--no-word-check`，
  退化为数 XML 的 `<m:oMath>`（不如前者可信）
- **图注正则只认 `图 N`**。`图 1-1`、`图 A.2` 这类多级编号改 `CAP_RE` 即可
- **图注会误吞正文引用句**（如「图 1 给出了…」），已用 `CAP_VERB_RE` 排除；
  若你的文档里正文引用句以其他动词开头，补进该正则即可
- **交叉引用只认 `[1]` / `[1, 2]` / `[1，2]` / `[1、2]`**。区间写法 `[5-7]`
  和上标形式 `⁵` 不匹配，会原样保留（改 `add_xref.py` 里的 `CITE_FIND` 即可）
- **交叉引用要求文献列表是 `[n] 内容` 的独立段落**，且 `n` 从 1 连续编号；
  编号不连续会打印警告，引用到不存在的编号则跳过并报告
