# 论文翻译子代理手册（模板）

> 用法：复制到 `<work_base>/WORKFLOW.md`，替换 `<...>` 占位符后，作为每个子代理的**唯一流程手册**。
> 子代理的提示词只需说"先读 WORKFLOW.md"，细节都在这里。

目标：把一篇英文 PDF 论文完整翻译为中文 Word（.docx），保留图/表/公式/参考文献，通过校验。
**只产出 docx + report.json。不要挂接 Zotero，不要改 PROGRESS.md / status_oc.json**（由主控统一处理）。

## 路径

- 任务清单：`<work_base>/tasks.json`（按 itemID 查条目，含 ztitle / title / path / pages）
- 工作目录：`<work_base>/work/item_<itemID>/`
  子目录：`figs/  parts/  images/  figures/  formulas/`
- 核心脚本：`<skill_root>/scripts/`
  （probe_layout.py、extract_pdf_text.py、check_parts.py、build_docx.py、verify_docx.py、
  render_formulas.py、export_cols2.py / export_single.py）
- Zotero 库：`<zotero_data_dir>/zotero.sqlite`（只读；**复制到自己唯一命名的临时文件再查，用完删除**）
- 生成脚本统一写到：`<scripts_dir>/gen_<itemID>.py`（唯一名，勿动他人文件）

## 标准步骤

1. **核对真实 Zotero itemID**：任务清单 ID 可能失效。复制 sqlite 后按标题关键词查：
   ```python
   c.execute("SELECT i.itemID,i.key,d.value FROM items i JOIN itemData id ON id.itemID=i.itemID "
             "JOIN itemDataValues d ON d.valueID=id.valueID WHERE d.value LIKE ? LIMIT 10", ('%关键词%',))
   ```
   有 PDF 附件的父条目才是真实条目（本流程不挂接，但 report.json 里必须给出 `zotero_real_itemID`）。
   若清单 path 失效，按标题在 `storage/` 下找 PDF。
2. **布局探测**：
   `PYTHONUTF8=1 python probe_layout.py <PDF> -o $WD/layout.json --crop-dir $WD/figs --contact`
   看 pages/columns/header/captions。**verdict 可能误判**（曾有文本层判成 scanned），以 extract 的文本量为准。
3. **提取文本**：
   `PYTHONUTF8=1 python extract_pdf_text.py <PDF> $WD/images $WD/figures $WD/formulas > $WD/extract.json 2>$WD/extract.err`
   然后清洗 JSON（MuPDF 警告会污染）：
   ```python
   raw=open(p,encoding='utf8').read(); i=raw.find('{'); d=json.loads(raw[i:])
   json.dump(d,open(p,'w',encoding='utf8'),ensure_ascii=False)
   ```
4. **导出正文**（去页眉页脚）：
   - 双栏：`PYTHONUTF8=1 python export_cols2.py $WD <页宽> "<页眉关键词1>" "<页眉关键词2>" ...`
     （页宽用点值 576/595/612；栏界≈页宽/2。**页宽猜错会把两栏交错混排**）
   - 单栏：`PYTHONUTF8=1 python export_single.py $WD "<页眉关键词>" ...`
   - 输出 `$WD/_body3.txt`（双栏）或 `$WD/_bodyS.txt`（单栏）。
   - **注意**：页眉关键词若含刊名，会把含该刊名的参考文献条目误当页眉删掉；
     发现文献条数异常时从 extract.json 原始块找回。
5. **通读全文**：分段读 `_body*.txt`，逐句精译。章节标题用 `h()`，正文 `p()`。
   摘要/引言/方法/结果/结论/致谢/参考文献都要译。
   > 导出的文本行可能超长，Read 工具会截断到 2000 字符——用 Python 单独取全文再读。
6. **图**：probe 自动裁图常混乱（合并、错位、混入正文）。以 extract.json 每页 images 的 bbox
   或页面文本块间隙为准，用 PDF 点坐标 `get_pixmap(clip)` 3x 重裁：
   ```python
   pix = doc[pno].get_pixmap(matrix=fitz.Matrix(3,3), clip=fitz.Rect(x0,y0,x1,y1)); pix.save(outdir/name)
   ```
   裁完用 PIL 拼验证图、ViewImage 检查（无截断、无正文混入、无页眉横幅）。
   图注单独 `cap()` 或 `fig(file, caption)`。多子图可拆多幅 `fig`。
7. **公式**：文本层常碎片化。按 PDF 坐标渲染公式条带（4x），ViewImage 目视转录 LaTeX。
   用 `eq(latex, "编号")`；编号无则传 `""`。
   **多行 LaTeX 勿用 `\\` 换行**（OMML 失败）→ 拆多个 eq 或写单行；`\quad` 后必须有空格。
   跨栏全宽公式必须按全宽渲染，单栏裁剪只能截到半条。
8. **表格**：`table(rows, header=True)` 结构化转录（rows 为二维 list[str]）。渲染页面核对数值。
   **表注类型必须是 `caption`（用 cap()），不能写 table_caption。**
   表格前正文若缺文献号，补出（finalize 不扫表格）。
9. **参考文献**：保留英文著录 + `[n]` 编号。正文引用一律方括号 `[n]`
   （圆括号数字制、著者-年份制都要转换）。
   **区间引用 [1]–[3] 必须展开为 `[1], [2], [3]`**（中间号会被判"未引用"）。
   数组/向量写在圆括号里，避免被当成引用号。
10. **生成 parts**：写 `gen_<itemID>.py`（模板见下），生成 `$WD/parts/01.json`（长文拆 01/02/03）。
11. **校验-构建-验证**：
    ```
    PYTHONUTF8=1 python check_parts.py $WD/parts
    PYTHONUTF8=1 python build_docx.py $WD/parts "$OUT"
    PYTHONUTF8=1 python verify_docx.py "$OUT"
    ```
    `$OUT = $WD/<中文标题>.docx`。**必须 verify ok=true 且 dangling/unused 为空**，反复修到通过。
12. **写报告** `$WD/report.json`：
    ```json
    {"itemID": 11847, "zotero_real_itemID": 11847, "zotero_key": "XXXXXXXX",
     "title": "<中文标题>", "docx": "<绝对路径>",
     "pages": 18, "chars": 8600, "figures": 31, "equations": 31,
     "tables": 1, "refs": 68, "verify_ok": true,
     "zotero_sibling_itemIDs": [11256], "notes": "同文条目 11256"}
    ```

## parts helper 模板（复制到 gen 脚本开头）

```python
# -*- coding: utf-8 -*-
import json, os, re
WD = r'<work_base>/work/item_<itemID>'
os.makedirs(os.path.join(WD, 'parts'), exist_ok=True)
_ILL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
def clean(o):
    if isinstance(o, str): return _ILL.sub('', o)
    if isinstance(o, list): return [clean(x) for x in o]
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    return o
B = []
def h(text, level=1): B.append({"type": "heading", "level": level, "text": text})
def p(text, noindent=False):
    d = {"type": "para", "text": text}
    if noindent: d["noindent"] = True
    B.append(d)
def eq(latex, no): B.append({"type": "formula", "latex": latex, "no": no})
def cap(text): B.append({"type": "caption", "text": text})
def fig(file, caption): B.append({"type": "figure", "file": "figs/" + file, "caption": caption})
def table(rows, header=True): B.append({"type": "table", "header": header, "rows": rows})
# ... 内容 ...
B.append({"type": "title", "text": "<中文标题>"})
B.append({"type": "subtitle", "text": "<英文原题>"})
os.makedirs(os.path.join(WD, 'parts'), exist_ok=True)
with open(os.path.join(WD, 'parts', '01.json'), 'w', encoding='utf8') as f:
    json.dump(clean({"blocks": B}), f, ensure_ascii=False, indent=1)
print('OK', len(B))
```

## 翻译质量要求

- 全文完整：标题、作者、单位、摘要、关键词、全部章节、公式编号、图注、表注、结论、致谢、
  参考文献、作者简介（如有）。
- 术语一致；机构/人名首次出现给中文 + 原文；作者拼音名保留原拼写。
- 译文里**不要残留英文整句**；专有名词/算法名可保留英文。
- 图注/表注中**不要写 `$...$`**（会残留美元符号报 raw_dollar），用纯文本符号。
- 原文自相矛盾处（图注与正文、式号与正文）**照原文忠实翻译**，不改动、不臆补，在 report.notes 记一笔。

## 已知坑（务必遵守）

- 区间引用展开为列举式；表格里的 `[n]` 不算引用，正文要补出。
- 数组 `[0, 1]`、`[128, 256]` 会被 CITE_FIND 当成引用号，改写为圆括号。
- 公式 `\quad` 后加空格；勿多行拼接 LaTeX。
- 表注用 `cap()`；提取 JSON 先清洗再解析。
- 图注会打断正文句（MDPI 等），拼接完整句再译。
- 照片大图转 JPEG（宽 ≤2000px，q=88）控体积。
- SAGE 的 φ 常被抽成 j/F，统一 φ-OTDR。
- ACS 综述用 (1) 编号，文本层可能丢文献条目，缺号加占位并在 notes 说明。
