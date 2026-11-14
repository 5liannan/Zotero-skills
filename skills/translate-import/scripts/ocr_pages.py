# -*- coding: utf-8 -*-
"""扫描件 OCR：出「带坐标的文本」，供读图转录与定位公式/图注。

Usage:
    python ocr_pages.py <pdf> [--out ocr] [--scale 2.6] [--pages 2-11]
                        [--split auto|none|305] [--keep-images]

产物：
    ocr/ocr.json      每页 items：text / x0,y0,x1,y1（已还原为 pt）/ conf
    ocr/text_col.txt  按栏重排的可读文本，每行前缀 [x0-x1 yNNN] 便于回查坐标
    ocr/pNN.png       页影像（--keep-images 时保留，默认删）

为什么先 OCR 而不是直接让模型看图
--------------------------------
OCR 出来的**坐标**比文字本身更有用：拿到 bbox 后，公式、图注、表头都可以直接
按坐标去 PDF 裁小图（`get_pixmap(clip=Rect(bbox±3))`），比目测试坐标快得多。
文字本身只用来读散文；公式一律以原图为准（OCR 对上下标、希腊字母、根号几乎必错，
`ffiffiffi` 这类连字错认是常态）。

坐标系
------
RapidOCR 返回的是渲染图的像素坐标，除以 --scale 才是 PDF 的 pt 坐标。
这一步不还原，后面所有 clip 都会偏 2.6 倍。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                     # pragma: no cover
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from probe_layout import bands, detect_columns      # 栏检测复用同一套判据
except ImportError:                                    # pragma: no cover
    bands = detect_columns = None


def parse_pages(spec, total):
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


def load_engine():
    """RapidOCR 是可选依赖：缺了就明确告诉用户装哪个包，而不是 ImportError 收场。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("ERROR: 需要 RapidOCR —— pip install rapidocr-onnxruntime\n"
              "       （onnxruntime 自带模型，可离线用；不必装 tesseract）", file=sys.stderr)
        return None
    return RapidOCR()


def ocr_page(engine, img_path, scale):
    """返回 [{text,x0,y0,x1,y1,conf}]，坐标已除以 scale 还原成 pt。"""
    res = engine(img_path)
    items = res[0] if isinstance(res, tuple) else res
    out = []
    for it in (items or []):
        try:
            box, text, conf = it[0], it[1], float(it[2])
        except (IndexError, TypeError, ValueError):
            continue
        if not text or not str(text).strip():
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append({
            "text": str(text).strip(),
            "x0": round(min(xs) / scale, 1), "x1": round(max(xs) / scale, 1),
            "y0": round(min(ys) / scale, 1), "y1": round(max(ys) / scale, 1),
            "conf": round(conf, 3),
        })
    out.sort(key=lambda d: (d["y0"], d["x0"]))
    return out


def render_text(items, split, page_w):
    """按栏重排：左栏全部在前、右栏在后，栏内按 y 排。"""
    if split is None:
        groups = [items]
    else:
        groups = [[d for d in items if d["x1"] < split + 4],
                  [d for d in items if d["x1"] >= split + 4]]
    lines = []
    for gi, grp in enumerate(groups):
        if split is not None:
            lines.append("--- %s ---" % ("L" if gi == 0 else "R"))
        for d in sorted(grp, key=lambda v: (v["y0"], v["x0"])):
            lines.append("[%3d-%3d y%3d] %s" % (d["x0"], d["x1"], d["y0"], d["text"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="对扫描件 PDF 做 OCR，输出带 pt 坐标的 JSON 与按栏重排的文本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python ocr_pages.py scan.pdf --pages 2-11 --out ocr\n"
               "  python ocr_pages.py scan.pdf --split 290      # 手工指定栏分界\n")
    ap.add_argument("pdf", help="输入 PDF")
    ap.add_argument("--out", default="ocr", help="输出目录（默认 ocr）")
    ap.add_argument("--scale", type=float, default=2.6,
                    help="渲染倍数（默认 2.6；字太小可加到 3.2，太慢可降到 2.0）")
    ap.add_argument("--pages", default="", help="只处理这些页，如 2-11 或 2,5,7")
    ap.add_argument("--split", default="auto",
                    help="栏分界 x：auto（自动探测）/ none（不重排）/ 具体数值")
    ap.add_argument("--keep-images", action="store_true", help="保留页影像 pNN.png")
    ap.add_argument("--min-conf", type=float, default=0.3, help="置信度低于此值的行丢弃（默认 0.3）")
    args = ap.parse_args(argv)

    try:
        import pymupdf
    except ImportError:
        print("ERROR: 需要 pymupdf —— pip install pymupdf", file=sys.stderr)
        return 2
    if not os.path.exists(args.pdf):
        print("ERROR: 找不到 %s" % args.pdf, file=sys.stderr)
        return 2

    engine = load_engine()
    if engine is None:
        return 2

    doc = pymupdf.open(args.pdf)
    pages = parse_pages(args.pages, doc.page_count)
    os.makedirs(args.out, exist_ok=True)

    page_w = doc[pages[0] - 1].rect.width
    page_h = doc[pages[0] - 1].rect.height
    split = float(args.split) if args.split.lower() not in ("auto", "none") else None

    pages_out = []
    for pno in pages:
        page = doc[pno - 1]
        img = os.path.join(args.out, "p%02d.png" % pno)
        page.get_pixmap(matrix=pymupdf.Matrix(args.scale, args.scale)).save(img)
        items = [d for d in ocr_page(engine, img, args.scale) if d["conf"] >= args.min_conf]
        pages_out.append({"page": pno, "items": items})
        print("p%d  items=%d" % (pno, len(items)))
        if not args.keep_images:
            try:
                os.remove(img)
            except OSError:
                pass

    # 定栏分界：文本层优先，扫描件退回用 OCR 自己的行做检测，都失败才按单栏处理
    if args.split == "auto" and split is None and detect_columns:
        probe_items = next((p["items"] for p in pages_out if len(p["items"]) > 20), [])
        if probe_items:
            # OCR 只有行级框，左右边界足够判断栏缝：每行当作一个「词」
            fake = [[d["x0"], d["y0"], d["x1"], d["y1"], d["text"]] for d in probe_items]
            split = detect_columns([fake], page_w, 0, page_h)[0]
        if split is None:
            tb = [[(float(b[0]), float(b[1]), float(b[2]), float(b[3]), " ".join((b[4] or "").split()))
                   for b in doc[p - 1].get_text("blocks")] for p in pages]
            if bands and any(len(x) > 3 for x in tb):
                hb, fb = bands(tb, page_h)
                split = detect_columns([doc[p - 1].get_text("words") for p in pages],
                                       page_w, hb + 4, fb - 15)[0]

    text_all = []
    for p in pages_out:
        text_all.append("===== PAGE %d =====" % p["page"])
        text_all.append(render_text(p["items"], split, page_w))

    with open(os.path.join(args.out, "ocr.json"), "w", encoding="utf-8") as f:
        json.dump({"pdf": os.path.abspath(args.pdf), "scale": args.scale,
                   "split": split, "pages": pages_out}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "text_col.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(text_all))

    if args.split == "auto" and split is None:
        print("提示：未识别出栏分界，text_col.txt 按单栏输出。\n"
              "      双栏扫描件请用 --split <x> 指定（如 --split 290）；\n"
              "      probe_layout.py 在文本层可用时会直接给出 columns.split。", file=sys.stderr)

    total = sum(len(p["items"]) for p in pages_out)
    print("共 %d 页 / %d 行  split=%s  -> %s" % (len(pages_out), total, split, args.out))
    print("下一步：公式按 bbox 裁图转录（get_pixmap(clip=Rect(bbox±3))），散文用 text_col.txt 校读。")
    if total < len(pages_out) * 5:
        print("⚠ 行数偏少，可能整页无字或渲染倍数过低（当前 %.1f）" % args.scale, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
