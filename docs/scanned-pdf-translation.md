# 扫描件 PDF 翻译流程（无文本层）

适用：纸质扫描、影像版 PDF、或文本层损坏（仅水印/下载声明）的英文文献。目标与文本层相同——**全文精译 · 逐句对应**——但必须先 **页影像识读**，再翻译。

## 1. 何时判定为扫描件

| 信号 | 说明 |
|---|---|
| 文本极少 | `extract_pdf_pypdfium2.py` 得到 `fulltext.txt` 字符数远小于页数×正常密度 |
| 只有横幅 | 内容为 `Downloaded from…`、`CORE`、期刊封面广告等 |
| 整页无字 | `page.get_text_bounded()` 为空，但 `page.render()` 有清晰版面 |
| 伪图 | `extract_pdf_images.py` 只得到 1×1、色条、logo 碎片 |

**不要**把残缺 OCR 当作完整正文去做「摘要式」翻译。

## 2. 渲染页影像

```python
import pypdfium2 as pdfium
from pathlib import Path

pdf = Path("paper.pdf")
out = Path("pages"); out.mkdir(exist_ok=True)
doc = pdfium.PdfDocument(str(pdf))
for i, page in enumerate(doc):
    # 扫描件建议 scale 1.6–2.0，保证字可读
    page.render(scale=1.8).to_pil().save(out / f"p{i+1:02d}.png", optimize=True)
```

- 封面、空白、下载横幅页可跳过或在译文中不占结构
- 正文页用 `p01, p02, …` 便于对照

## 3. 识读与精译

1. **逐页识读**：视觉模型直接读 `pages/pNN.png`；或先本地 OCR（RapidOCR 等）再人工校对。
2. **逐句翻译**：严格按「全文精译 · 逐句对应」写 `parts/01.json`（必要时 `02.json`）。
3. **结构跟原文**：Letter/PRL 不硬套「1 引言 / 5 应用与展望」；有编号章节才译编号章节。
4. **禁止**：编造未识别的段落、用目录/摘要拼正文、按页数凑字数。

页像无法辨认时写 `[本页图像无法识别]`，宁缺毋假。

## 4. 公式、图表

- **公式**：OCR 常丢 `√`、希腊字母、上下标。依据 `where` 定义与量纲还原为 `$...$`，**式号与原文一致**。
- **图**：无位图则只写中文 `caption`（含坐标轴/图例关键数值）；有可裁切图元再 `image`。
- **表**：按原文列成 `table` blocks，数字照抄。
- **参考文献**：保留英文，按原文编号。

## 5. 构建与入库

与文本层相同：

```bash
# $MIMO_PYTHON 或 python
python build_docx.py <workdir>/parts <out.docx>
python verify_docx.py <out.docx>   # ok=true
# 退出 Zotero 后 register_zotero_docx.py / 既有 fill 脚本
```

挂接规则见 `zotero-storage-management.md`：一附件一目录；PDF 与 DOCX 分目录。

## 6. 扫描件验收清单

- [ ] 正文页均有译文对应，无整页遗漏
- [ ] 公式编号齐全，关键变量可追溯 `where` 定义
- [ ] 图/表题注中文且图号与原文一致
- [ ] 未译入水印、页眉页脚、下载声明
- [ ] 术语与同库其它译文一致（如：体黏滞 / bulk viscosity，瑞利–布里渊散射 / RBS）
- [ ] `verify_docx.py` 返回 `ok=true`

## 7. 与批量任务

批量时可对每篇：`判定是否扫描件 → 渲染 pages/ → 精译 → build → verify`。  
扫描件优先串行或少量并行，避免视觉识读上下文过载。
