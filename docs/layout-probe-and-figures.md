# 版面探测、公式拼版、OCR 与补图：四个「每篇都要重写」的脚本

这四件事在每一篇新文献上都要重做一遍，而且每次都要靠试错：

| 要测的东西 | 为什么不能固定 | 实测例子 |
|---|---|---|
| 双栏分界 x | 每个期刊不同 | PRL 306、JCP 300/313、SPIE 310、Optical Engineering 310 |
| 页眉带下沿 | 页眉横线会跟着裁进图里 | PRL 横线在 y 41.5–42.2 |
| 图注上沿 | 决定图区 bbox 的顶界 | 取多了带进页眉，取少了切掉横轴标签 `ω/2π (GHz)` |
| 编号公式坐标 | 数学字体无 ToUnicode，只能读图 | 一页一整页读比分条读慢一倍 |

对应四个脚本，全部在 `skills/translate-import/scripts/`，都只依赖 pymupdf（`render_formulas` 另需 Pillow，
`ocr_pages` 另需 RapidOCR），不写库、不碰 Zotero。

```text
python scripts/probe_layout.py paper.pdf -o report.json --crop-dir figs --contact
python scripts/render_formulas.py paper.pdf --out sheets --per-sheet 3
python scripts/ocr_pages.py scan.pdf --out ocr --pages 2-11
python scripts/patch_figures.py --docx old.docx --figs figs/*.png --out new.docx
python scripts/check_parts.py parts/          # 构建前 lint
```

## 1. probe_layout.py —— 一次量出五个数

```bash
python scripts/probe_layout.py <pdf> [-o report.json] \
       [--crop-dir DIR] [--contact] [--scale 5] [--min-caption-chars 15] [--first-page 1]
```

输出 `report.json`：

| 字段 | 含义 | 怎么用 |
|---|---|---|
| `text_layer.verdict` | `text` / `mixed` / `scanned` | 为 `scanned` 时改走 [扫描件流程](scanned-pdf-translation.md) + `ocr_pages.py` |
| `columns.split` | 双栏分界 x（单栏为 `null`） | 传给 `render_formulas.py --split`，或自己裁图时定左右边界 |
| `header_band.y_max` | 页眉带下沿 | 裁图顶界的**绝对下限** |
| `footer_band.y_min` | 页脚带上沿 | 裁图底界上限 |
| `captions[]` | 图注/表注的 `page / num / bbox / text` | 定位题注；`num` 可能是 `?`（文本层把罗马数字认成字母） |
| `equations[]` | 编号式号的 bbox | 交给 `render_formulas.py` 用 |
| `figure_boxes[]` | 图区建议 bbox + `kind` + `edge_dirty` | 直接裁，或当人工微调的起点 |

三条判据值得记下来：

- **页眉/页脚用「跨页重复」判，不看位置**。只按 `y < 0.1H` 取，会把只出现一页的正文标题
  也算成页眉（实测把 header 抬到 y=131，等于把半页正文当页眉）。
- **栏缝不是零命中**。跨栏的词（`Brook,` 从 299 跨到 320）会在缝里点几个桶，
  所以要取「相对全页中位数极低」的带，再用「两侧都有 ≥25% 的词」验证是不是真双栏。
- **图区顶界只认正文级块**。`(a)`、`ω/2π (GHz)` 这些图内文字也在 `get_text("blocks")` 里，
  不加「长度 ≥25 字符且宽度 >45% 栏宽」的过滤，bbox 会塌成一条 30pt 的细带。

`--crop-dir` 会顺手裁图，并对四边 3px 带做非白像素扫描：密度 >2% 标 `edge_dirty`，
用来抓「页眉横线被裁进来」「右边缘混进邻栏竖排字母」这两类脏边。`--contact` 再拼一张
`contact.png`，一眼看完所有裁片。

实测（Lao 等 1976, J. Chem. Phys. 64, 5013）：`split=306`、`header≤52`、`footer≥789`，
6 个图表 bbox 全部落位。

## 2. render_formulas.py —— 一版三条，读图转录

```bash
python scripts/render_formulas.py <pdf> [--out sheets] [--per-sheet 3] \
       [--scale 5] [--top-pad 78] [--bottom-pad 10] [--pages 2-11] [--equations 1,2,10]
```

产物 `sheets/EQ01.png …`（红字标 `EQ 编号 (p.页码)`）与 `sheets/index.json`。

上界不是固定值：编号块只标出「式号」那一行，分式的分子在上方几十 pt。这里取
`max(y0 − top‑pad, 上一条 y1 + 2, 页眉带下沿 + 2)`，逐条自适应——固定 padding 要么切掉分子，
要么把上一段正文带进来。

排序按 **页 → 栏 → y**。只按 `(page, y)` 排会把右栏顶部的式 (7) 排到左栏底部的式 (6) 前面。

> 读图时把 `where …` 的正文一起裁进来是有意的：变量的定义通常就在公式下一行，
> 分条裁反而要回去翻。

## 3. ocr_pages.py —— 扫描件的「坐标源」

```bash
python scripts/ocr_pages.py <pdf> [--out ocr] [--scale 2.6] [--pages 2-11] \
       [--split auto|none|290] [--keep-images] [--min-conf 0.3]
```

产物：

- `ocr/ocr.json`：每页 `items[]`，含 `text / x0,y0,x1,y1 / conf`，**坐标已除以 scale 还原成 pt**
- `ocr/text_col.txt`：按栏重排的散文，每行前缀 `[x0-x1 yNNN]`

**OCR 的价值在坐标，不在文字**。散文可以直接用；公式一律回原文裁图——`ffiffiffi`→`√`、
上下标拆行、希腊字母错认都是常态。拿到 bbox 后：

```python
pm = page.get_pixmap(matrix=pymupdf.Matrix(6, 6),
                     clip=pymupdf.Rect(x0 - 3, y0 - 3, x1 + 3, y1 + 3))
```

`--split` 的检测顺序：文本层 → OCR 行框 → 放弃（按单栏输出并提示）。扫描件没有文本层，
所以栏检测是用 OCR 出来的行框反推的；单页样本常常判不出，此时手工给 `--split`。

依赖：`pip install rapidocr-onnxruntime`（onnxruntime 自带模型，可离线；不需要 tesseract）。

## 4. patch_figures.py —— 给已有 DOCX 补图，不重建

```bash
python scripts/patch_figures.py --docx old.docx --figs figs/*.png --out new.docx
python scripts/patch_figures.py --docx old.docx --at "图 1=figs/a.png" --place after --out new.docx
python scripts/patch_figures.py --docx old.docx --figs figs/*.png --dry-run
```

适用场景：译文**只缺图**，文字与公式都在（Word 里能双击编辑公式）。此时重建等于把整篇重排，
图注样式、页眉页脚、交叉引用全要重新对齐；就地插图只碰图与题注两个对象。

- 锚点用正则 `^图\s*N(?!\d)(?:[\.．:：\u3000]|\s{2,}|\s+)`。
  **不能用 `startswith("图 4")`**：正文的「图 4(a,d) 中…」「图 4　(d) 表明…」都会命中。
- 插入段设 `keep_with_next`，否则 Word 会把图留在上页、题注跑到下页。
- **幂等**：题注上方已有 `w:drawing` 就跳过，重复跑不会叠两张（`--force` 可强制）。
- `--inplace` 会先在原目录留 `.bak`；默认输出 `<原名>_with_figs.docx`。

## 5. check_parts.py —— 构建前 lint

```bash
python scripts/check_parts.py parts/ [--max-caption 0] [--json] [--quiet]
```

| 码 | 含义 |
|---|---|
| E1 | JSON 非法 / 顶层不是 `{"blocks": [...]}` |
| E2 | 未知块类型（**build 只 warning 后静默跳过**，最容易漏） |
| E3 | 文本类块内容为空 |
| E4 / E5 | 图片不存在 / 图注为空 |
| E6 | formula 的 `latex` 为空 |
| E7 | 文本含 `**` —— `para` 不支持 markdown 粗体，会原样印出 |
| E8 | 图注超长（需显式 `--max-caption`） |
| W1 / W2 / W3 | 式号重复 / parts 断号 / 文献编号不像 `[n]` |

E2 与 E7 是这套检查的主要理由：两者在 build 阶段都不会让构建失败，只在导出 PDF 逐页
核对时才暴露——那时已经改了一轮稿。

## 端到端

```bash
# 文本层 PDF
python scripts/probe_layout.py paper.pdf -o report.json --crop-dir figs --contact
python scripts/render_formulas.py paper.pdf --out sheets
#   → 读 figs/contact.png 与 sheets/EQ*.png，写 parts/NN.json
python scripts/check_parts.py parts/
python scripts/build_docx.py parts out.docx
python scripts/verify_docx.py out.docx          # 要求 ok=true

# 扫描件
python scripts/probe_layout.py scan.pdf -o report.json     # verdict=scanned
python scripts/ocr_pages.py scan.pdf --out ocr --pages 2-11
python scripts/render_formulas.py scan.pdf --out sheets    # 无文本层时改用 bbox 手裁
```

`build_docx.py` 对未知块类型只打 `warning: unrendered block types: [...]`，
而它往往被后面的 `formula: OMML …` 与 `finalize: …` 两行盖过去——所以 `check_parts.py`
要**在 build 之前**跑，不要指望 build 帮你发现。
