# -*- coding: utf-8 -*-
"""给「已有译文 DOCX」补插图，不动正文（不重建、不改文字）。

Usage:
    # 按图号自动配对：题注「图 1 …」→ 插在它上方
    python patch_figures.py --docx old.docx --figs figs/p05_fig1.png,figs/p05_fig2.png \\
                           --out new.docx

    # 显式指定哪张插到哪个题注
    python patch_figures.py --docx old.docx --at "图 1=figs/a.png" --at "表 2=figs/b.png" \\
                           --place after --out new.docx

    # 只看匹配情况，不写文件
    python patch_figures.py --docx old.docx --figs figs/*.png --dry-run

为什么要单独有这条路径
--------------------
`build_docx.py` 是「从 parts 重建」，适合新译。但先前的译稿若只是**缺图**
（文字与公式都在、Word 里能正常编辑），重建等于把整篇重排一遍，风险大于收益：
图注样式、页眉页脚、交叉引用都要重新对齐。就地插图只碰图与图题两个对象。

两个坑
------
* **锚点必须用正则**：`startswith("图 4")` 会同时命中正文里的「图 4(a,d) 中…」
  与「图 4　(d) 表明…」（全角空格），报「匹配到 2 段」。
* **图与题注不能分页**：插入段设 `keep_with_next`，否则 Word 会把图留在上页、
  题注单独跑到下页。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                     # pragma: no cover
    pass


def anchor_re(num):
    """题注锚点：图号后可跟句点、全角空格、冒号或多个空格，但后面不能紧跟数字。"""
    return re.compile(r"^图\s*%d(?!\d)(?:[\.．:：\u3000]|\s{2,}|\s+)" % num)


def has_drawing(p):
    from docx.oxml.ns import qn
    return bool(p._p.findall(".//" + qn("w:drawing")))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="给已有译文 DOCX 补插图（就地插入，不重建正文）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python patch_figures.py --docx t.docx --figs figs/*.png --out t2.docx\n"
               "  python patch_figures.py --docx t.docx --at \"图 3=figs/f3.png\" --place after --out t2.docx\n")
    ap.add_argument("--docx", required=True, help="输入 DOCX")
    ap.add_argument("--figs", default="", help="图片列表（逗号分隔，支持通配符），按文件名里的 pNN_figM 配图号")
    ap.add_argument("--at", action="append", default=[],
                    help="显式映射，可重复：--at \"图 1=figs/a.png\"")
    ap.add_argument("--out", default="", help="输出 DOCX（默认 <原名>_with_figs.docx）")
    ap.add_argument("--inplace", action="store_true", help="直接覆盖输入文件（会先同目录留 .bak）")
    ap.add_argument("--width", type=float, default=14.0, help="图片宽度 cm（默认 14）")
    ap.add_argument("--place", choices=["before", "after"], default="before",
                    help="插在题注前还是后（默认 before；表题常在表上方，用 after 的场合少）")
    ap.add_argument("--force", action="store_true", help="即使题注上方已有图也再插一张")
    ap.add_argument("--dry-run", action="store_true", help="只报告匹配结果，不写文件")
    args = ap.parse_args(argv)

    try:
        import docx
        from docx.shared import Cm, Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        print("ERROR: 需要 python-docx —— pip install python-docx", file=sys.stderr)
        return 2
    if not os.path.exists(args.docx):
        print("ERROR: 找不到 %s" % args.docx, file=sys.stderr)
        return 2

    # 组装 (图号, 图片路径)
    jobs = []
    for spec in args.at:
        if "=" not in spec:
            print("ERROR: --at 需要「图号=路径」形式：%r" % spec, file=sys.stderr)
            return 2
        num_s, path = spec.split("=", 1)
        m = re.search(r"(\d+)", num_s)
        if not m:
            print("ERROR: --at 里没写图号：%r" % num_s, file=sys.stderr)
            return 2
        jobs.append((int(m.group(1)), path.strip()))
    if args.figs:
        paths = []
        for pat in args.figs.split(","):
            pat = pat.strip()
            if not pat:
                continue
            hit = sorted(glob.glob(pat))
            paths += hit if hit else [pat]
        for p in paths:
            m = re.search(r"fig\s*_?(\d+)", os.path.basename(p), re.I)
            if m:
                jobs.append((int(m.group(1)), p))
            else:
                print("跳过（文件名里没有图号，可用 --at 指定）：%s" % p, file=sys.stderr)

    if not jobs:
        print("ERROR: 没有可插的图（--figs 或 --at 至少给一个）", file=sys.stderr)
        return 2
    jobs.sort(key=lambda x: x[0])

    d = docx.Document(args.docx)
    paras = d.paragraphs
    done, skipped, already = 0, 0, 0
    for num, img in jobs:
        rx = anchor_re(num)
        cand = [p for p in paras if rx.match(p.text.strip())]
        if len(cand) != 1:
            print("✗ 图 %d：锚点匹配到 %d 段，跳过（%s）" % (num, len(cand), img), file=sys.stderr)
            skipped += 1
            continue
        if not os.path.exists(img):
            print("✗ 图 %d：图片不存在 %s" % (num, img), file=sys.stderr)
            skipped += 1
            continue
        anchor = cand[0]
        if not args.force:
            prev = anchor._p.getprevious()
            if prev is not None and prev.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"):
                print("· 图 %d：题注上方已有图片，跳过（--force 可强制再插）" % num)
                skipped += 1
                already += 1
                continue
        if args.place == "before":
            newp = anchor.insert_paragraph_before()
        else:
            newp = anchor.insert_paragraph_after()
        newp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        newp.paragraph_format.space_before = Pt(6)
        newp.paragraph_format.space_after = Pt(3)
        newp.paragraph_format.keep_with_next = (args.place == "before")
        newp.add_run().add_picture(img, width=Cm(args.width))
        print("✓ 图 %d ← %s" % (num, os.path.basename(img)))
        done += 1

    if args.dry_run:
        print("dry-run：将插入 %d 张，跳过 %d 张（未写文件）" % (done, skipped))
        return 0

    out = args.docx
    if args.inplace:
        out = args.docx
        bak = args.docx + ".bak"
        if not os.path.exists(bak):
            import shutil
            shutil.copy2(args.docx, bak)
            print("原件已备份：%s" % bak)
    elif args.out:
        out = args.out
    else:
        base, ext = os.path.splitext(args.docx)
        out = base + "_with_figs" + ext

    d.save(out)
    print("saved %s  (%d 张图 / %d 张跳过)" % (out, done, skipped))
    if done == 0:
        if already:
            print("目标图题上方都已有图片，未重复插入（--force 可强制）")
            return 0
        print("未插入任何图 —— 检查题注写法（锚点正则见 anchor_re）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
