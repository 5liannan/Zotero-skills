# -*- coding: utf-8 -*-
"""把编号公式裁成「一版多条」的拼图，便于逐条读图转录。

Usage:
    python render_formulas.py <pdf> [--out sheets] [--per-sheet 3]
                              [--scale 5] [--top-pad 78] [--bottom-pad 10]
                              [--pages 2-11] [--equations 1,2,3]

产物：
    sheets/EQ01.png …          每版 per-sheet 条，红字标 "EQ 编号 (p.页码)"
    sheets/index.json          每版包含哪些式号、页码与 bbox

为什么不能只读文本层
--------------------
数学字体子集化后通常没有 ToUnicode 映射：`get_text()` 抽出来是散字符块，
`(7)` 这样的编号还在，公式主体却已碎成「分子 / 分母 / 括号」几段（分式尤甚）。
所以公式必须读图。一页一整页读，视线要在正文与公式间来回跳；
把同一页相邻的公式裁成一条窄带拼在一起，一次能读 3 条，效率约为逐页读的两倍。

上界为什么不是固定值
--------------------
编号块只标出「式号」那一行的位置，分式公式的分子在上方几十 pt 处。
固定 top-pad 遇上跨行大公式会切掉分子，遇上短公式又会把上一段正文带进来。
这里按「上一式号 y1 + 2」与「y0 − top-pad」取较大者，逐条自适应。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                     # pragma: no cover
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                                   # 栏检测与页眉页脚带复用 probe_layout
    from probe_layout import bands, detect_columns
except ImportError:                                    # pragma: no cover
    bands = detect_columns = None

EQ_NO = re.compile(r"^\(\s*([0-9]+(?:\.[0-9]+)?|[A-Z][0-9]+(?:\.[0-9]+)?)\s*\)$")


def parse_pages(spec, total):
    """'2-11' / '2,3,5' / '' → 页码列表（1 基）。"""
    if not spec:
        return list(range(1, total + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 1 <= p <= total]


def find_equations(doc, pages):
    """按页收集编号块，附带所在栏范围，供裁剪时定左右边界。"""
    found = []
    for pno in pages:
        page = doc[pno - 1]
        for b in page.get_text("blocks"):
            t = " ".join((b[4] or "").split())
            m = EQ_NO.match(t)
            if not m:
                continue
            found.append({"page": pno, "no": m.group(1),
                          "bbox": [float(b[0]), float(b[1]), float(b[2]), float(b[3])]})
    # 同一式号可能因文本层重复而出现两次（页眉/正文互见），保留 y 最大的那条
    best = {}
    for e in found:
        k = (e["page"], e["no"])
        if k not in best or e["bbox"][1] > best[k]["bbox"][1]:
            best[k] = e
    return sorted(best.values(), key=lambda e: (e["page"], e["bbox"][1]))


def column_bounds(eq, page_w, split):
    """按式号块的 x 判断所在栏，返回该栏 [left, right]。"""
    if split is None:
        return page_w * 0.06, page_w * 0.96
    if eq["bbox"][0] < split - 10:
        return page_w * 0.06, split - 3
    return split + 3, page_w * 0.96


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把 PDF 里的编号公式裁成多条一版的拼图，便于读图转录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python render_formulas.py paper.pdf --pages 2-11 --per-sheet 3\n")
    ap.add_argument("pdf", help="输入 PDF")
    ap.add_argument("--out", default="sheets", help="输出目录（默认 sheets）")
    ap.add_argument("--per-sheet", type=int, default=3, help="一版放几条（默认 3）")
    ap.add_argument("--scale", type=float, default=5.0, help="渲染倍数（默认 5）")
    ap.add_argument("--top-pad", type=float, default=78.0,
                    help="式号块向上扩多少 pt 兜住分子（默认 78，遇跨行大式可加到 110）")
    ap.add_argument("--bottom-pad", type=float, default=10.0, help="向下留白（默认 10）")
    ap.add_argument("--pages", default="", help="只处理这些页，如 2-11 或 2,5,7")
    ap.add_argument("--equations", default="", help="只处理这些式号，如 1,2,10")
    ap.add_argument("--split", type=float, default=None,
                    help="双栏分界 x（默认自动探测；probe_layout.py 会给出该值）")
    args = ap.parse_args(argv)

    try:
        import pymupdf
    except ImportError:
        print("ERROR: 需要 pymupdf —— pip install pymupdf", file=sys.stderr)
        return 2
    if not os.path.exists(args.pdf):
        print("ERROR: 找不到 %s" % args.pdf, file=sys.stderr)
        return 2
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("ERROR: 需要 Pillow —— pip install pillow", file=sys.stderr)
        return 2

    doc = pymupdf.open(args.pdf)
    pages = parse_pages(args.pages, doc.page_count)
    eqs = find_equations(doc, pages)
    if args.equations:
        want = {x.strip() for x in args.equations.split(",") if x.strip()}
        eqs = [e for e in eqs if e["no"] in want]
    if not eqs:
        print("未找到编号公式块。若这是扫描件（无文本层），公式编号也拿不到：\n"
              "  1) 先跑 ocr_pages.py 得到带 bbox 的文本，据此定位式号；\n"
              "  2) 或直接用 probe_layout.py --crop-dir 按图注裁，公式按页整块读图。",
              file=sys.stderr)
        return 1

    page_w = doc[pages[0] - 1].rect.width
    page_h = doc[pages[0] - 1].rect.height
    if bands and detect_columns:                       # 与 probe_layout 同一套判据
        pblocks = [[(float(b[0]), float(b[1]), float(b[2]), float(b[3]), " ".join((b[4] or "").split()))
                    for b in doc[p - 1].get_text("blocks")] for p in pages]
        pwords = [doc[p - 1].get_text("words") for p in pages]
        header_bottom, footer_top = bands(pblocks, page_h)
        split = args.split if args.split is not None else \
            detect_columns(pwords, page_w, header_bottom + 4, footer_top - 15)[0]
    else:                                              # pragma: no cover
        header_bottom, footer_top, split = page_h * 0.06, page_h * 0.94, args.split
    os.makedirs(args.out, exist_ok=True)

    # 阅读顺序是「页 → 栏 → y」：只按 y 排会把右栏顶部（式 7）排到左栏底部（式 6）前面
    def col_of(e):
        return 0 if (split is None or e["bbox"][0] < split - 10) else 1

    eqs.sort(key=lambda e: (e["page"], col_of(e), e["bbox"][1]))
    prev_bottom = {}
    for e in eqs:
        key = (e["page"], col_of(e))
        page = doc[e["page"] - 1]
        left, right = column_bounds(e, page_w, split)
        # 上界三重取大：默认 padding、上一条的下沿、页眉带下沿（防止把页眉裁进来）
        top = max(e["bbox"][1] - args.top_pad, prev_bottom.get(key, 0) + 2, header_bottom + 2)
        bottom = min(e["bbox"][3] + args.bottom_pad, footer_top)
        e["clip"] = [round(left, 1), round(top, 1), round(right, 1), round(bottom, 1)]
        prev_bottom[key] = e["bbox"][3]

    index = []
    for k in range(0, len(eqs), max(1, args.per_sheet)):
        grp = eqs[k:k + max(1, args.per_sheet)]
        crops = []
        for e in grp:
            page = doc[e["page"] - 1]
            pm = page.get_pixmap(matrix=pymupdf.Matrix(args.scale, args.scale),
                                 clip=pymupdf.Rect(*e["clip"]))
            crops.append((e, pm))
        width = max(pm.width for _, pm in crops)
        height = sum(pm.height + 26 for _, pm in crops)
        sheet = Image.new("RGB", (width, max(height, 40)), "white")
        dr = ImageDraw.Draw(sheet)
        y = 0
        for e, pm in crops:
            dr.text((6, y + 6), "EQ %s  (p.%d)" % (e["no"], e["page"]), fill="red")
            sheet.paste(Image.frombytes("RGB", (pm.width, pm.height), pm.samples), (0, y + 24))
            y += pm.height + 26
        name = "EQ%02d.png" % (k // max(1, args.per_sheet) + 1)
        path = os.path.join(args.out, name)
        sheet.save(path)
        index.append({"file": name, "equations": [e["no"] for e in grp],
                      "pages": [e["page"] for e in grp]})
        print("saved %s  eq=%s" % (path, ",".join(e["no"] for e in grp)))

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"pdf": os.path.abspath(args.pdf), "sheets": index,
                   "equations": [{"no": e["no"], "page": e["page"], "clip": e["clip"]} for e in eqs]},
                  f, ensure_ascii=False, indent=1)
    print("共 %d 条公式，%d 版 -> %s" % (len(eqs), len(index), os.path.join(args.out, "index.json")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
