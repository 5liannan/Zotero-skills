# -*- coding: utf-8 -*-
"""探测 PDF 版面结构，为「读图转录 + 裁切插图」提供坐标，免去逐篇试错。

Usage:
    python probe_layout.py <pdf> [-o report.json]
                            [--crop-dir DIR] [--contact] [--scale 5]
                            [--min-caption-chars 15]

输出（report.json）：
    pages / page_size          页数与页面尺寸（pt）
    text_layer.verdict         "text" | "mixed" | "scanned"，含 scanned_pages 列表
    columns.split              双栏分界 x（单栏为 null）与 confidence
    header_band.y_max          页眉带下沿（正文建议起点）
    footer_band.y_min          页脚带上沿（正文建议终点）
    captions[]                 page / num / bbox / text / column
    equations[]                page / no / bbox（编号公式，供拼版读图）
    figure_boxes[]             caption_num / bbox / top_source / edge_dirty

为什么需要它
------------
栏分界、页眉页脚带、图注上沿这三件事，每换一个期刊就得重试一次：
PRL 双栏 x≈306 且页眉横线压在 y 41.5–42.2；JCP 是 300/313；SPIE 是 310。
裁图时顶界只要多取 2pt，就会把那条横线一起裁进图里；底界少取 3pt，
横轴标签 ω/2π (GHz) 就被切掉一半。本脚本把这几项一次量出来，
--crop-dir 还会顺手裁图并对四边做「脏边」自检。

依赖
----
pymupdf（必装）；--contact 拼自检图时额外需要 Pillow。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys

try:                                                  # Windows 控制台中文
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                     # pragma: no cover
    pass

# 图注 / 表注：英文 "FIG. 1" "Figure 2" "TABLE I"，中文「图 1　」「表 II　」
CAP_EN = re.compile(r"^(?:FIG(?:URE)?|TABLE)\s*[\.:]?\s*([0-9]+[a-zA-Z]?|[IVX]+)\b")
CAP_ZH = re.compile(r"^[图表]\s*([0-9]+[a-zA-Z]?)(?:[\.．:：]|\u3000|\s{2,})")
# 正文引用句：'Figure 2 shows ...' / 'Fig. 3 gives ...' —— 与真图注同样以图号开头
CAP_CITE = re.compile(r"^(?:FIG(?:URE)?|TABLE)\s*[\.:]?\s*[0-9IVX]+\s+"
                      r"(?:shows?|gives?|illustrates?|depicts?|displays?|presents?|"
                      r"compares?|is|are|was|were|and)\b", re.I)
# 编号公式：独占一块的 "(3)" "(12)"，也允许 "(2.1)" "(A1)"
EQ_NO = re.compile(r"^\(\s*([0-9]+(?:\.[0-9]+)?|[A-Z][0-9]+(?:\.[0-9]+)?)\s*\)$")


def _words_per_page(page):
    try:
        return len(page.get_text("words"))
    except Exception:
        return 0


def _blocks(page):
    """返回 (x0, y0, x1, y1, text) —— 空白块丢弃。"""
    out = []
    for b in page.get_text("blocks"):
        t = " ".join((b[4] or "").split())
        if t:
            out.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), t))
    return out


def detect_columns(pages_words, width, y_lo=0.0, y_hi=1e9):
    """用纵轴空白带找双栏分界。

    做法：把 [0, width] 切成 1pt 桶，统计每个 x 被单词跨越的次数；
    在页面中部（0.3W–0.7W）找最长的「零命中」连续段，取中点作分界。
    单栏正文的零命中段会很窄，此时返回 None。

    y_lo / y_hi 用于只看正文带：页脚那条横跨全宽的版权声明会把每个 x 都点亮，
    不排掉就永远找不到栏缝。
    """
    if not pages_words or width <= 0:
        return None, 0.0
    hits = [0] * (int(width) + 2)
    total = 0
    for words in pages_words:
        for w in words:
            y0 = float(w[1])
            if not (y_lo <= y0 <= y_hi):
                continue
            x0, x1 = float(w[0]), float(w[2])
            if x1 <= x0:
                continue
            # 只标记「横跨该 x」的词，正文块跨度大，栏间窄缝命中最少
            a, b = max(0, int(x0)), min(len(hits) - 1, int(x1))
            for x in range(a, b + 1):
                hits[x] += 1
            total += 1
    if not total:
        return None, 0.0
    lo, hi = int(width * 0.30), int(width * 0.70)
    window = hits[lo:hi]
    if not window:
        return None, 0.0
    # 栏缝不是「零命中」——跨栏的词（"Brook," 299–320）会点几个桶，
    # 真正可靠的是「相对全页中位数极低」的那条带，所以阈值取自适应值。
    base = statistics.median(window) or 1.0
    thr = min(window) + max(2.0, 0.03 * base)
    best_len, best_mid, cur_start = 0, None, None
    for k, v in enumerate(window):
        if v <= thr:
            if cur_start is None:
                cur_start = k
        else:
            if cur_start is not None:
                if k - cur_start > best_len:
                    best_len, best_mid = k - cur_start, lo + (cur_start + k) // 2
                cur_start = None
    if cur_start is not None and len(window) - cur_start > best_len:
        best_len, best_mid = len(window) - cur_start, lo + (cur_start + len(window)) // 2
    # 窄于页面 1.2% 的缝隙当作词间空隙，不认作栏分界
    if best_mid is None or best_len < max(4, width * 0.012):
        return None, 0.0
    # 单栏验证：真双栏时，分界两侧都该有足量「不与对侧重叠」的词；单栏右侧近乎为空
    n_left = sum(1 for words in pages_words for w in words if float(w[2]) < best_mid - 12)
    n_right = sum(1 for words in pages_words for w in words if float(w[0]) > best_mid + 12)
    tot = n_left + n_right
    if not tot or n_left / tot < 0.25 or n_right / tot < 0.25:
        return None, 0.0
    return float(best_mid), round(min(1.0, best_len / 40.0), 2)


def bands(pages_blocks, height):
    """页眉带下沿 / 页脚带上沿。

    判据是「跨页重复」而不是「位置靠边」：只有同一段文字（去数字后）出现在
    过半页面的页边带里，才算页眉/页脚。这样正文首行（仅一页出现）不会被误判，
    从而把 header 抬到 y=131 那种荒唐值。单页 PDF 退化为固定比例。
    """
    n = max(1, len(pages_blocks))
    head_g, foot_g = {}, {}
    for blocks in pages_blocks:
        for x0, y0, x1, y1, t in blocks:
            k = re.sub(r"\d+", "#", t)[:40]
            if y1 < height * 0.10:
                head_g.setdefault(k, []).append(y1)
            if y0 > height * 0.90:
                foot_g.setdefault(k, []).append(y0)
    need = max(2, n * 0.5)
    heads = [max(v) for v in head_g.values() if len(v) >= need]
    foots = [min(v) for v in foot_g.values() if len(v) >= need]
    head = max(heads) if heads else height * 0.06
    foot = min(foots) if foots else height * 0.94
    return round(head + 3, 1), round(foot - 2, 1)


def find_captions(pages_blocks, min_chars):
    """定位图注/表注块。要求：以图号开头、且字数足够（排除正文引用句）。"""
    out = []
    for i, blocks in enumerate(pages_blocks):
        for x0, y0, x1, y1, t in blocks:
            if CAP_CITE.match(t):                      # 「Figure 2 shows …」是正文，不是图注
                continue
            m = CAP_EN.match(t) or CAP_ZH.match(t)
            if not m:
                # 文本层把 "TABLE III" 识别成 "TABLE m." 时仍要能定位，编号记 "?"
                if re.match(r"^(?:TABLE|FIG(?:URE)?)\b", t, re.I) and len(t) >= min_chars:
                    num = "?"
                else:
                    continue
            else:
                num = m.group(1)
            if len(t) < min_chars:                     # 「图 4　(d) 表明…」这类引用
                continue
            out.append({
                "page": i + 1, "num": num, "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                "text": t[:120], "width": round(x1 - x0, 1),
            })
    return out


def find_equations(pages_blocks):
    out = []
    for i, blocks in enumerate(pages_blocks):
        for x0, y0, x1, y1, t in blocks:
            m = EQ_NO.match(t)
            if m:
                out.append({"page": i + 1, "no": m.group(1),
                            "bbox": [round(v, 1) for v in (x0, y0, x1, y1)]})
    return out


def column_of(x0, split):
    if split is None:
        return "full"
    return "L" if x0 < split - 10 else "R"


def _is_prose(b, col_w):
    """能当「图区上界」的必须是正文段落，不能是图内的 (a)/(b) 或坐标轴标签。"""
    x0, y0, x1, y1, t = b
    return len(t) >= 25 and (x1 - x0) > col_w * 0.45


def _looks_like_row(t):
    """表格行 vs 正文段的粗判：行短、词少、数字密。"""
    if len(t) > 170:                       # 正文段普遍 200+ 字符
        return False
    words = t.split()
    if len(words) > 14:
        return False
    digits = sum(1 for ch in t if ch.isdigit())
    return digits >= 3 or len(words) <= 4


def _table_extent(same, cap_y1, footer_top):
    """表题在表上方：从题注下沿往下，连续「像表格行」的块构成表体。

    只靠行距判断会失效——表 I 最后一行与紧随的正文只差 13pt，会把整段正文
    一起框进来（实测框到 344pt 高）。所以主判据是文本形态（短、词少、数字多），
    行距只作辅助：遇到非行块或 >34pt 的断档即停。
    """
    rows = sorted([b for b in same if b[1] > cap_y1 + 1], key=lambda b: b[1])
    if not rows:
        return cap_y1 + 2
    bottom, prev_y1 = rows[0][3], rows[0][3]
    for b in rows[1:]:
        if b[1] - prev_y1 > 34 or not _looks_like_row(b[4]):
            break
        bottom, prev_y1 = b[3], b[3]
    return min(bottom + 2, footer_top)


def figure_boxes(pages_blocks, captions, split, header_bottom, page_w, page_h,
                 footer_top=None):
    """按「图注上沿 → 上方最近正文块下沿」推图区 bbox（栏内计算）。

    三个坑决定了这里的写法：
    * 坐标轴标签（`ω/2π (GHz)`）与子图标号 `(a)` 就在图注上方，若当成「上方文本块」，
      bbox 会塌成一条 30pt 的细带 —— 上界块必须是正文级（够长、够宽）。
    * 紧挨上一条题注的图（题注1 结束 425、图 2 从 427 开始）不能因为「太近」被判成
      轴标签，所以排除后要立刻回退到下一块，而不是一路退到页眉。
    * 表题在**表的上方**（图题在图的下方），方向相反，必须分开算。
    """
    footer_top = page_h * 0.94 if footer_top is None else footer_top
    by_page = {}
    for c in captions:
        by_page.setdefault(c["page"], []).append(c)
    boxes = []
    for c in captions:
        pg = c["page"]
        blocks = [b for b in pages_blocks[pg - 1]
                  if b[1] > header_bottom - 40 and b[3] < footer_top + 2]
        col = column_of(c["bbox"][0], split)
        if col == "L":
            same = [b for b in blocks if b[0] < (split or page_w) - 10]
            left = min([b[0] for b in same], default=page_w * 0.06) - 4
            right = (split or page_w) - 3
        elif col == "R":
            same = [b for b in blocks if b[0] >= (split or 0) - 10]
            left = (split or 0) + 3
            right = max([b[2] for b in same], default=page_w * 0.94) + 4
        else:
            same = blocks
            left = min([b[0] for b in same], default=page_w * 0.06) - 4
            right = max([b[2] for b in same], default=page_w * 0.94) + 4
        col_w = max(60.0, right - left)
        cap_y0, cap_y1 = c["bbox"][1], c["bbox"][3]
        is_table = c["text"].upper().startswith("TABLE") or c["text"].startswith("表")

        if is_table:                                  # 表：题注在上，表体在下
            top, bottom = cap_y1 + 2, _table_extent(same, cap_y1, footer_top)
        else:                                         # 图：图在上，题注在下
            cand = [b for b in same if b[3] < cap_y0 - 6 and _is_prose(b, col_w)]
            top = None
            while cand:
                pick = max(cand, key=lambda b: b[3])
                if cap_y0 - pick[3] < 12 and len(cand) > 1:
                    cand = [b for b in cand if b[3] < pick[1] - 1]
                    continue
                top = pick[3]
                break
            if top is None:
                top = header_bottom - 6
            # 同页靠上的另一个图注也要当作上界（图 2 的图区不能跨到图 1 的题注里）
            for prev in by_page.get(pg, []):
                # 只认同栏的上一题注；跨栏比较会让左栏图 1 被右栏图 3 的题注压扁
                if prev is c or column_of(prev["bbox"][0], split) != col:
                    continue
                if prev["bbox"][3] < cap_y0 and prev["bbox"][3] > top:
                    top = prev["bbox"][3]
            top += 2
            bottom = cap_y0 - 2

        boxes.append({
            "page": pg, "caption_num": c["num"], "column": col, "kind": "table" if is_table else "figure",
            "bbox": [round(left, 1), round(top, 1), round(right, 1), round(bottom, 1)],
            "height": round(bottom - top, 1),
        })
    return boxes


def edge_dirty(path, band=3, thr=0.02):
    """四边 band 像素带内的「非白」比例超过 thr ⇒ 判为脏边（页眉横线、邻栏碎字）。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    edges = []
    for y in range(min(band, h)):
        edges += [px[x, y] for x in range(w)]
    for y in range(max(0, h - band), h):
        edges += [px[x, y] for x in range(w)]
    for x in range(min(band, w)):
        edges += [px[x, y] for y in range(h)]
    for x in range(max(0, w - band), w):
        edges += [px[x, y] for y in range(h)]
    if not edges:
        return False
    dark = sum(1 for v in edges if v < 235)
    return (dark / len(edges)) > thr


def crop_boxes(doc, boxes, out_dir, scale):
    """按 bbox 裁图；返回裁片路径与脏边标记。"""
    import pymupdf
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for b in boxes:
        page = doc[b["page"] - 1]
        rect = pymupdf.Rect(*b["bbox"])
        rect = rect & page.rect                             # 夹在页面内
        if rect.is_empty or rect.height < 20 or rect.width < 20:
            b["crop"] = None
            b["skip"] = "bbox 过小"
            continue
        # 编号可能是 "?"（文本层把罗马数字识别成字母），Windows 文件名不能用问号
        safe = re.sub(r"[^0-9A-Za-z]+", "_", str(b["caption_num"])).strip("_") or "x"
        name = "p%02d_%s%s.png" % (b["page"], "tab" if b.get("kind") == "table" else "fig", safe)
        path = os.path.join(out_dir, name)
        pm = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=rect)
        pm.save(path)
        b["crop"] = path
        b["px"] = [pm.width, pm.height]
        b["edge_dirty"] = edge_dirty(path)
        made.append(path)
    return made


def contact_sheet(paths, out_path, cols=4, thumb=420):
    """把所有裁片拼一张，一眼看出哪张带进了页眉横线 / 邻栏碎字。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("提示：未装 Pillow，跳过 contact sheet", file=sys.stderr)
        return None
    if not paths:
        return None
    rows = (len(paths) + cols - 1) // cols
    cell_h = thumb + 26
    sheet = Image.new("RGB", (cols * thumb, rows * cell_h), "white")
    dr = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        try:
            im = Image.open(p)
        except Exception:
            continue
        im.thumbnail((thumb - 8, thumb - 8))
        x, y = (i % cols) * thumb, (i // cols) * cell_h
        sheet.paste(im, (x + 4, y + 22))
        dr.text((x + 6, y + 5), os.path.basename(p), fill="red")
        dr.rectangle([x, y, x + thumb - 1, y + cell_h - 1], outline=(200, 200, 200))
    sheet.save(out_path)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="探测 PDF 版面（栏分界 / 页眉页脚带 / 图注 / 编号公式 / 图区 bbox）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python probe_layout.py paper.pdf -o report.json --crop-dir figs --contact\n")
    ap.add_argument("pdf", help="输入 PDF")
    ap.add_argument("-o", "--out", default="report.json", help="报告输出路径（默认 report.json）")
    ap.add_argument("--crop-dir", default="", help="给出目录则按 figure_boxes 裁图")
    ap.add_argument("--contact", action="store_true", help="额外拼一张裁片自检图")
    ap.add_argument("--scale", type=float, default=5.0, help="裁图缩放倍数（默认 5）")
    ap.add_argument("--min-caption-chars", type=int, default=15,
                    help="图注最短字符数，用于排除正文引用句（默认 15）")
    ap.add_argument("--first-page", type=int, default=1, help="起始页（1 基，默认 1）")
    args = ap.parse_args(argv)

    try:
        import pymupdf
    except ImportError:
        print("ERROR: 需要 pymupdf —— pip install pymupdf", file=sys.stderr)
        return 2
    if not os.path.exists(args.pdf):
        print("ERROR: 找不到 %s" % args.pdf, file=sys.stderr)
        return 2

    doc = pymupdf.open(args.pdf)
    pages = list(range(args.first_page - 1, doc.page_count))
    wc = [_words_per_page(doc[i]) for i in pages]
    scanned = [pages[k] + 1 for k, n in enumerate(wc) if n < 20]
    median = statistics.median(wc) if wc else 0
    verdict = "scanned" if median < 20 else ("mixed" if scanned else "text")

    pages_words = [doc[i].get_text("words") for i in pages]
    pages_blocks = [_blocks(doc[i]) for i in pages]
    page0 = doc[pages[0]]
    pw, ph = page0.rect.width, page0.rect.height

    # 先定页眉页脚带，再只在正文带内找栏缝（页脚版权行横跨全宽，会淹没栏缝）
    hb, fb = bands(pages_blocks, ph)
    split, conf = detect_columns(pages_words, pw, y_lo=hb + 4, y_hi=fb - 15)
    caps = find_captions(pages_blocks, args.min_caption_chars)
    eqs = find_equations(pages_blocks)
    boxes = figure_boxes(pages_blocks, caps, split, hb, pw, ph, footer_top=fb)

    made = []
    if args.crop_dir:
        made = crop_boxes(doc, boxes, args.crop_dir, args.scale)
        if args.contact:
            cp = contact_sheet(made, os.path.join(args.crop_dir, "contact.png"))
            if cp:
                print("contact sheet: %s" % cp)

    report = {
        "pdf": os.path.abspath(args.pdf),
        "pages": doc.page_count,
        "page_size": [round(pw, 1), round(ph, 1)],
        "text_layer": {"median_words": median, "scanned_pages": scanned, "verdict": verdict},
        "columns": {"split": split, "confidence": conf},
        "header_band": {"y_max": hb},
        "footer_band": {"y_min": fb},
        "captions": caps,
        "equations": eqs,
        "figure_boxes": boxes,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("pages=%d  verdict=%s  columns.split=%s (conf %.2f)  header<=%.0f  footer>=%.0f"
          % (doc.page_count, verdict, split, conf, hb, fb))
    print("captions=%d  equations=%d  figure_boxes=%d  -> %s"
          % (len(caps), len(eqs), len(boxes), args.out))
    dirty = [b for b in boxes if b.get("edge_dirty")]
    if dirty:
        print("⚠ 脏边（疑似裁进了页眉横线/邻栏文字）：", file=sys.stderr)
        for b in dirty:
            print("   p%d 图%s bbox=%s" % (b["page"], b["caption_num"], b["bbox"]), file=sys.stderr)
    if verdict != "text":
        print("提示：判定为 %s —— 先跑 ocr_pages.py 拿带坐标的文本，再逐条读图转录公式。" % verdict,
              file=sys.stderr)
    if split is None and len(pages) > 1:
        print("提示：未识别出双栏（单栏或栏缝过窄）。若确认是双栏，可用 --min-caption-chars 调小后复核。",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
