# -*- coding: utf-8 -*-
"""Extract text blocks, figures and formula crops from a PDF for translation.

Usage:
    python extract_pdf_text.py <pdf_path> <image_dir> [<figure_dir>] [<formula_dir>]

Defaults: <figure_dir> = <image_dir>/../figures, <formula_dir> = <image_dir>/../formulas

stdout: JSON
  {file, npages, total_chars, math_fonts,
   pages:[{page, blocks:[...], images:[...], figures:[...], formulas:[...]}]}

图（figures）—— 两级优先
  1) 原始图：优先递归抽取页面里真实存在的嵌入位图（含 Form XObject 内的位图），
             按原始分辨率导出 PNG。
  2) PDF 裁切：对无位图的图区（矢量图，或被拆散成多个小位图的图），
             按「图注上沿 → 上一文本块下沿」的版面区域整页高 DPI 渲染再裁切。

公式（formulas）
  本脚本负责定位公式区（数学字体启发式 + 行内/行间分类），供 Agent 依据
  定位结果把 LaTeX 写法写进 parts/*.json 的 {"type":"formula","latex":"$$...$$"}；
  译文构建时由 build_docx.py 把 LaTeX 转成 Word 原生公式对象（OMML）。
"""
import json
import os
import re
import sys

import pymupdf

# ---------------------------------------------------------------- 常量

# 渲染倍率：公式与图裁切用高 DPI，保证上下标、希腊字母可辨
FORMULA_ZOOM = 4.0
FIGURE_ZOOM = 2.5

# 嵌入位图最小边长（PDF 用户空间 pt）与最小原始像素
MIN_IMG_PT = 60.0
MIN_IMG_PX = 120

# 裁切区域最小尺寸，低于此值视为噪声
MIN_CROP_PT = 40.0

# 数学字体识别。
# 覆盖三类：
#   ① 专名数学字体：Cambria Math、XITS、Latin Modern Math、STIX、TeX 系列的
#      cmmi/cmsy/cmex、Mathematica 的 MT Extra、Symbol、Euclid 等；
#   ② 常见的「数学斜体」变体：Cambria-Italic / Times-Italic 等（论文公式多用斜体排）；
#   ③ 打包器命名：math、eqn、formula。
MATH_FONT_RE = re.compile(
    r"("
    r"cmmi|cmsy|cmex|cmr\d|msam|msbm|cmbsy|cmtt|cmsl"
    r"|math|mathtype|stix|xits|lmmath|lmroman|lmmono"
    r"|cambria|mtmi|mtsy|mtm?extra|mtextra"
    r"|symbol|euclid|rsfs|wasy|esint|txmi|xits|eufm|eusm|eurm|fasl"
    r"|eqn|formula"
    r")",
    re.I,
)

# 内容启发式：即使字体名不含数学线索，正文里的行间公式也能靠「字符类占比」认出。
# 典型公式字符：= + − ± × ÷ ∑ ∫ √ ∂ ≤ ≥ ≠ ≈ → ∞ α β γ δ θ λ μ π σ φ ω Ω ∇ ∈ ⊗ 等
FORMULA_CHAR_RE = re.compile(
    r"[=+\-−±×÷∑∫√∂≤≥≠≈∼→←↔∞⟨⟩⊗⊗∪∩∈⊂αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ∇·"
    r"\^\{\}_\\]"
)
# 上述字符占比达到该阈值、且文本足够短、几乎无中文，即判为公式
FORMULA_CHAR_RATIO = 0.22
FORMULA_MAX_CHARS = 240


def _looks_like_formula_text(text):
    """内容启发式：不依赖字体名，判断一段文本是否是公式。"""
    t = (text or "").strip()
    if not t or len(t) > FORMULA_MAX_CHARS:
        return False
    # 含中文 → 不是公式
    if any("\u4e00" <= ch <= "\u9fff" for ch in t):
        return False
    # 至少要有 2 个字母（变量名）
    letters = sum(1 for ch in t if ch.isalpha() and ch.isascii())
    if letters < 2:
        return False
    # 必须有等号/关系符（纯数字列表不算公式）
    if not re.search(r"[=<>≤≥≈≠∼→∝]", t):
        return False
    hits = len(FORMULA_CHAR_RE.findall(t))
    return hits / max(len(t), 1) >= FORMULA_CHAR_RATIO and hits >= 3

# 行内公式（嵌在句子中间的短式）长度上限（字符）
INLINE_MAX_CHARS = 40


def _setup_fonts(doc):
    """文档级收集字体名，返回 math_fonts 集合（避免逐 span 重复扫描）。"""
    math_fonts = set()
    try:
        for pno in range(doc.page_count):
            for f in doc[pno].get_fonts(full=True):
                name = (f[3] or "").strip()
                if name and MATH_FONT_RE.search(name):
                    math_fonts.add(name)
    except Exception:
        pass
    return math_fonts


# ---------------------------------------------------------------- 位图抽取

def _extract_bitmaps(doc, page, pno, image_dir, saved, counters):
    """抽取页面上真实存在的嵌入位图。返回 [{"file","bbox","source"}]。

    修复原实现的两个缺陷：
      * 原版在 saved 缓存命中分支下 name 仍为 None，却照样 append，
        产出 {"file": null}，下游 build_docx 静默渲染成「（缺失图片：）」。
        现在只在确实拿到文件名时才 append。
      * 原版用 get_image_rects(xref)[0] 只取第一处实例；同一 xref 在
        多页/多处复用时其余实例会漏。现在遍历全部 rects。
    """
    out = []
    try:
        infos = page.get_images(full=True)
    except Exception:
        return out

    for info in infos:
        xref = info[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        if not rects:
            continue

        name = saved.get(xref)
        if name is None:
            try:
                pix = pymupdf.Pixmap(doc, xref)
                if pix.colorspace is None:
                    continue
                if pix.colorspace.n > 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                if pix.width < MIN_IMG_PX or pix.height < MIN_IMG_PX:
                    continue
                counters[0] += 1
                name = "p{:02d}_bitmap{:02d}.png".format(pno + 1, counters[0])
                pix.save(os.path.join(image_dir, name))
                saved[xref] = name
            except Exception:
                continue

        for r in rects:
            if r.width < MIN_IMG_PT or r.height < MIN_IMG_PT:
                continue
            out.append({
                "file": name,
                "bbox": [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
                "source": "original",
            })
    return out


# ---------------------------------------------------------------- 矢量图区

def _vector_clusters(page):
    """取矢量绘图块（type==1）并聚合为若干「图区」候选。

    matplotlib / MATLAB 出图通常是矢量：get_drawings() 返回大量细碎路径
    （坐标轴、刻度、曲线、图例框）。按 bbox 做并查式合并得到图区。
    """
    rects = []
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r is None or r.width <= 0 or r.height <= 0:
                continue
            # 排除页边框、页眉页脚横线等横贯整页的细长条
            if r.width > page.rect.width * 0.9 and r.height < 6:
                continue
            if r.height > page.rect.height * 0.9 and r.width < 6:
                continue
            rects.append(pymupdf.Rect(r))
    except Exception:
        return []

    if not rects:
        return []

    PAD = 18.0
    clusters = []
    for r in rects:
        for c in clusters:
            grown = pymupdf.Rect(c)
            grown.x0 -= PAD
            grown.y0 -= PAD
            grown.x1 += PAD
            grown.y1 += PAD
            if grown.intersects(r):
                c |= r
                break
        else:
            clusters.append(pymupdf.Rect(r))

    # 聚合可能产生新的相邻簇，再收敛一轮
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a = pymupdf.Rect(clusters[i])
                a.x0 -= PAD
                a.y0 -= PAD
                a.x1 += PAD
                a.y1 += PAD
                if a.intersects(clusters[j]):
                    clusters[i] |= clusters[j]
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break

    return [c for c in clusters if c.width >= MIN_CROP_PT and c.height >= MIN_CROP_PT]


# ---------------------------------------------------------------- 图注

FIG_LABEL_RE = re.compile(r"^\s*(?:fig(?:ure)?\.?|图)\s*\.?\s*(\d{1,3})\b", re.I)


def _caption_anchors(blocks):
    out = []
    for b in blocks:
        m = FIG_LABEL_RE.match(b["text"].strip())
        if m:
            out.append({"num": int(m.group(1)), "bbox": b["bbox"], "text": b["text"].strip()})
    return out


# ---------------------------------------------------------------- 公式识别

def _formula_spans(page, math_fonts):
    """收集公式区：字体启发式 + 内容启发式（两条路取并集）。

    字体启发式会漏：论文正文常用 Times 排版，公式里混排的正体变量、
    数字、括号与正文字体同名字体，仅靠字体名会漏掉半截公式。
    内容启发式会漏：纯符号的短式（如 "α + β"）拿不到等号。
    两者并集后再合并相邻项，召回率显著高于任何单独一条。
    """
    items = []
    try:
        raw = page.get_text("dict", sort=True)
    except Exception:
        return []

    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                txt = (sp.get("text") or "").strip()
                if not txt:
                    continue
                fname = (sp.get("font") or "").strip()
                by_font = fname in math_fonts or bool(MATH_FONT_RE.search(fname))
                by_text = _looks_like_formula_text(txt)
                if not (by_font or by_text):
                    continue
                r = pymupdf.Rect(sp["bbox"])
                if r.width <= 0 or r.height <= 0:
                    continue
                items.append({"rect": r, "text": txt,
                              "line_bbox": pymupdf.Rect(line["bbox"]),
                              "by_font": by_font, "by_text": by_text})

    groups = []
    for it in items:
        for g in groups:
            if abs(g["rect"].y0 - it["rect"].y0) < 3.0:
                gap = it["rect"].x0 - g["rect"].x1
                if -1.0 <= gap <= 12.0:
                    g["rect"] |= it["rect"]
                    g["text"] += it["text"]
                    g["by_font"] = g["by_font"] or it["by_font"]
                    break
        else:
            groups.append({"rect": pymupdf.Rect(it["rect"]), "text": it["text"],
                           "line_bbox": it["line_bbox"], "by_font": it["by_font"]})
    # 只有内容命中（字体不命中）的孤立短串容易误报，收紧：要求具备等号关系符
    groups = [g for g in groups
              if g["by_font"] or re.search(r"[=<>≤≥≈≠∼→∝]", g["text"])]
    return groups


def _is_display_formula(group, page_rect):
    """行间独立公式 vs 行内内嵌公式。"""
    r, lb = group["rect"], group["line_bbox"]
    if lb.width > 0 and r.width / lb.width > 0.62:
        return True
    if len(group["text"].strip()) <= INLINE_MAX_CHARS and r.width < page_rect.width * 0.18:
        return False
    return r.width > page_rect.width * 0.25


def _crop_pixmap(page, rect, zoom, path):
    """高 DPI 渲染并裁切；rect 钳制到页面内，留 2pt 白边。"""
    r = pymupdf.Rect(rect)
    r.x0 -= 2.0
    r.y0 -= 2.0
    r.x1 += 2.0
    r.y1 += 2.0
    r.intersect(page.rect)
    if r.width < 4 or r.height < 4:
        return False
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=r, alpha=False)
    if pix.width < 8 or pix.height < 8:
        return False
    pix.save(path)
    return True


# ---------------------------------------------------------------- 主流程

def main():
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: extract_pdf_text.py <pdf> <image_dir> [<figure_dir>] [<formula_dir>]")
    pdf_path = sys.argv[1]
    image_dir = sys.argv[2]
    parent = os.path.dirname(os.path.abspath(image_dir))
    figure_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(parent, "figures")
    formula_dir = sys.argv[4] if len(sys.argv) > 4 else os.path.join(parent, "formulas")

    for d in (image_dir, figure_dir, formula_dir):
        os.makedirs(d, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    math_fonts = _setup_fonts(doc)

    out = {"file": pdf_path, "npages": doc.page_count, "pages": []}
    total_chars = 0
    saved = {}          # xref -> filename
    saved_fig = {}      # 裁切去重键 -> filename
    counters = [0]
    fig_counters = [0]
    fml_counters = [0]

    for pno in range(doc.page_count):
        page = doc[pno]
        page_rect = page.rect

        # ---- 1. 文本块
        blocks = []
        try:
            d = page.get_text("dict", sort=True)
        except Exception:
            d = {"blocks": []}
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            lines, max_size, bold_chars, all_chars = [], 0.0, 0, 0
            for ln in b.get("lines", []):
                lt = ""
                for sp in ln.get("spans", []):
                    lt += sp.get("text", "")
                    max_size = max(max_size, sp.get("size", 0.0))
                    all_chars += len(sp.get("text", "").strip())
                    if sp.get("flags", 0) & 16:
                        bold_chars += len(sp.get("text", "").strip())
                lines.append(lt)
            text = "\n".join(lines)
            if not text.strip():
                continue
            total_chars += len(text)
            blocks.append({
                "kind": "text",
                "text": text,
                "size": round(max_size, 1),
                "bold": all_chars > 0 and bold_chars >= all_chars * 0.5,
                "bbox": [round(v, 1) for v in b["bbox"]],
            })

        # ---- 2. 原始图（嵌入位图）
        images = _extract_bitmaps(doc, page, pno, image_dir, saved, counters)

        # ---- 3. 图：优先原始图，其次 PDF 裁切
        captions = _caption_anchors(blocks)
        vectors = _vector_clusters(page)
        text_sorted = sorted(blocks, key=lambda b: b["bbox"][1])

        figures = []
        for cap in captions:
            cx0, cy0, cx1, cy1 = cap["bbox"]
            ccx = (cx0 + cx1) / 2

            # 3a. 原始图：垂直紧邻图注上方 + 水平与图注相关
            hit = None
            for im in images:
                ix0, iy0, ix1, iy1 = im["bbox"]
                vgap = cy0 - iy1
                if vgap < -4 or vgap > 90:
                    continue
                if min(cx1, ix1) - max(cx0, ix0) <= 0:
                    continue
                if ix0 <= ccx <= ix1 or abs((ix0 + ix1) / 2 - ccx) < page_rect.width * 0.35:
                    hit = im
                    break
            if hit:
                figures.append({
                    "file": hit["file"], "caption": cap["text"], "num": cap["num"],
                    "bbox": hit["bbox"], "source": "original",
                })
                continue

            # 3b. PDF 裁切：图注上方的矢量图区
            area = None
            for v in vectors:
                vx0, vy0, vx1, vy1 = v
                vgap = cy0 - vy1
                if vgap < -6 or vgap > 120:
                    continue
                if min(cx1, vx1) - max(cx0, vx0) <= 0:
                    continue
                area = v
                break
            if area is None:
                # 无矢量簇：退化为「上一文本块下沿 → 图注上沿」的版面空白区
                top = page_rect.y0 + 40
                for tb in text_sorted:
                    tx0, ty0, tx1, ty1 = tb["bbox"]
                    if ty1 < cy0 - 4 and ty1 > top and (min(cx1, tx1) - max(cx0, tx0) > 0):
                        top = max(top, ty1)
                area = (max(page_rect.x0 + 18, cx0 - 24), top + 6,
                        min(page_rect.x1 - 18, cx1 + 24), cy0 - 4)

            ax0, ay0, ax1, ay1 = area
            if ax1 - ax0 < MIN_CROP_PT or ay1 - ay0 < MIN_CROP_PT:
                continue

            key = (round(ax0 / 6), round(ay0 / 6), round(ax1 / 6), round(ay1 / 6))
            name = saved_fig.get(key)
            if name is None:
                fig_counters[0] += 1
                name = "fig{:02d}_{:02d}.png".format(pno + 1, fig_counters[0])
                if not _crop_pixmap(page, pymupdf.Rect(ax0, ay0, ax1, ay1),
                                    FIGURE_ZOOM, os.path.join(figure_dir, name)):
                    continue
                saved_fig[key] = name
            figures.append({
                "file": name, "caption": cap["text"], "num": cap["num"],
                "bbox": [round(ax0, 1), round(ay0, 1), round(ax1, 1), round(ay1, 1)],
                "source": "crop",
            })

        # ---- 4. 公式定位（按数学字体启发式切出公式区，供 Agent 写 LaTeX）
        formulas = []
        for g in _formula_spans(page, math_fonts):
            display = _is_display_formula(g, page_rect)
            area = g["rect"]
            if display:
                # 行间公式：水平方向放宽以纳入右侧式号
                area = pymupdf.Rect(
                    max(page_rect.x0 + 18, area.x0 - 4), area.y0 - 5,
                    min(page_rect.x1 - 18, area.x1 + 46), area.y1 + 5)
            if area.width < 12 or area.height < 6:
                continue
            fml_counters[0] += 1
            name = "fml{:02d}_{:02d}.png".format(pno + 1, fml_counters[0])
            if not _crop_pixmap(page, area, FORMULA_ZOOM, os.path.join(formula_dir, name)):
                continue
            formulas.append({
                "file": name, "text": g["text"], "display": display,
                "bbox": [round(v, 1) for v in area],
            })

        out["pages"].append({
            "page": pno + 1, "blocks": blocks, "images": images,
            "figures": figures, "formulas": formulas,
        })

    out["total_chars"] = total_chars
    out["math_fonts"] = sorted(math_fonts)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print(file=sys.stdout)
    print("npages={} total_chars={} bitmaps={} figures={} formulas={}".format(
        out["npages"], total_chars, len(saved),
        sum(len(p["figures"]) for p in out["pages"]),
        sum(len(p["formulas"]) for p in out["pages"])), file=sys.stderr)


if __name__ == "__main__":
    main()
