# docx-polish — 译文 DOCX 公式与排版优化

把「LaTeX 源码当纯文本排」的中文译文 DOCX，转成带**真·Word 公式对象**的规范文档。

## 它解决什么问题

`translate-import` 产出的译文 DOCX 里，公式可能是这样的纯文本：

```text
$E = mc^{2}$                       ← 显示成源码，不是公式
$$\frac{\partial u}{\partial t} = \nabla^{2} u \quad (2.1)$$
```

在 Word 里打开就是一堆 `$` 和反斜杠。本技能把它们转成**可双击编辑的 Word 原生公式对象**，
同时清掉上一环节留下的黄色高亮、规范图注、统一行距缩进、补上页眉页码。

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
