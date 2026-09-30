# -*- coding: utf-8 -*-
"""重建译文 DOCX：LaTeX → Word 原生公式 + 全套排版。

读取 extract_formulas.py 产出的 formulas.json，以原文档为基底逐段重建。

用法：
    python optimize.py <src.docx> <out.docx> [formulas.json] \\
        --title "页眉标题" --header/--no-header --page-number/--no-page-number \\
        --body-size 10.5 --header-size 9 --indent-chars 2 --line-spacing 1.5

设计要点：
  * 逐段处理原文档，**保留图片与段落顺序**，不从零重建
  * 行间公式：清 run → 追加 OMML → 有式号则右对齐制表位
  * 行内公式：按 $ 切分，交替插入文本 run 与内联 OMML
"""
import argparse
import copy
import json
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
CAP_RE = re.compile(r"^\s*图\s*(\d+)\s*[.．:：]?\s*(.*)$", re.S)
REF_RE = re.compile(r"^[A-Z][a-zA-Z\-']+,?\s+[A-Z]?\.?")
# 这些小节标题下的段落不缩进、左对齐
NO_INDENT_HEADS = ("补充材料", "利益声明", "数据可用性声明", "参考文献", "引用本文", "关键词")


def omml_of(xml):
    """从 pandoc 产出的段落 XML 里取出 <m:oMath> 元素列表。"""
    from lxml import etree
    root = etree.fromstring(xml.encode("utf-8"))
    return root.findall(".//{%s}oMath" % M_NS)


class Styler(object):
    def __init__(self, ea_font, latin_font, body_size):
        self.ea = ea_font
        self.latin = latin_font
        self.body_size = body_size

    def apply(self, run, size=None, bold=None):
        run.font.name = self.latin
        rpr = run._element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:eastAsia"), self.ea)
        if size is not None:
            run.font.size = Pt(size)
        if bold is not None:
            run.font.bold = bold
        run.font.color.rgb = RGBColor(0, 0, 0)

    @staticmethod
    def clear_highlight(para):
        for r in para.runs:
            rpr = r._element.find(qn("w:rPr"))
            if rpr is None:
                continue
            for tag in ("w:highlight", "w:shd"):
                el = rpr.find(qn(tag))
                if el is not None:
                    rpr.remove(el)

    @staticmethod
    def clear_runs(para):
        for r in list(para.runs):
            r._element.getparent().remove(r._element)


def add_page_field(para, styler, size):
    """页脚页码域。不能只写 'PAGE' 文本，必须构造 fldChar。"""
    run = para.add_run()
    styler.apply(run, size)
    for typ, text in (("begin", None), (None, " PAGE "), ("end", None)):
        if typ:
            el = run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): typ})
        else:
            el = run._element.makeelement(qn("w:instrText"), {})
            el.text = text
        run._element.append(el)


def main():
    ap = argparse.ArgumentParser(description="译文 DOCX 公式与排版优化")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("formulas", nargs="?", default="formulas.json")
    ap.add_argument("--title", default="", help="页眉标题（默认取首个非空段落）")
    ap.add_argument("--no-header", action="store_true", help="不写页眉")
    ap.add_argument("--no-page-number", action="store_true", help="不写页码")
    ap.add_argument("--ea-font", default="宋体", help="中文字体")
    ap.add_argument("--latin-font", default="Times New Roman")
    ap.add_argument("--body-size", type=float, default=10.5)
    ap.add_argument("--header-size", type=float, default=9)
    ap.add_argument("--indent-chars", type=float, default=2.0, help="首行缩进字符数")
    ap.add_argument("--line-spacing", type=float, default=1.5)
    ap.add_argument("--margin", type=float, default=2.5, help="左右页边距(cm)")
    ap.add_argument("--top-margin", type=float, default=2.4)
    ap.add_argument("--center-first", type=int, default=4,
                    help="前 N 段按标题区居中处理")
    args = ap.parse_args()

    styler = Styler(args.ea_font, args.latin_font, args.body_size)
    body_pt = args.body_size
    indent_pt = Pt(body_pt * args.indent_chars)

    recs = json.load(open(args.formulas, encoding="utf-8"))
    by_para = {}
    for r in recs:
        by_para.setdefault(r["para"], []).append(r)

    doc = Document(args.src)
    sec = doc.sections[0]

    sec.top_margin = Cm(args.top_margin)
    sec.bottom_margin = Cm(args.top_margin)
    sec.left_margin = Cm(args.margin)
    sec.right_margin = Cm(args.margin)
    TEXT_W = sec.page_width - sec.left_margin - sec.right_margin

    # ---------- Normal ----------
    normal = doc.styles["Normal"]
    normal.font.name = args.latin_font
    normal.font.size = Pt(body_pt)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), args.ea_font)
    npf = normal.paragraph_format
    npf.line_spacing = args.line_spacing
    npf.space_before = Pt(0)
    npf.space_after = Pt(0)

    for name, size in (("Heading 1", 14), ("Heading 2", 12)):
        try:
            st = doc.styles[name]
        except KeyError:
            continue
        st.font.name = args.latin_font
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)
        st.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), args.ea_font)
        st.paragraph_format.space_before = Pt(10)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = 1.3

    # ---------- 页眉 / 页脚 ----------
    header_title = args.title
    if not header_title:
        for p in doc.paragraphs:
            if p.text.strip():
                header_title = p.text.strip()
                break

    if not args.no_header and header_title:
        hp = sec.header.paragraphs[0]
        hp.text = ""
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        styler.apply(hp.add_run(header_title[:80]), args.header_size)

    fp = sec.footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if not args.no_page_number:
        add_page_field(fp, styler, args.header_size)

    # ---------- 逐段 ----------
    stats = {"hl": 0, "display": 0, "display_num": 0, "inline": 0,
             "caption": 0, "para": 0, "head": 0, "failed": 0}

    for pi, para in enumerate(doc.paragraphs):
        text = para.text
        style = para.style.name
        styler.clear_highlight(para)

        # --- 公式段
        if pi in by_para:
            rec = by_para[pi][0]

            if rec["kind"] == "display":
                if not rec.get("ok"):
                    stats["failed"] += 1
                    continue
                num = rec.get("num")   # 式号已在提取阶段剥离
                styler.clear_runs(para)
                para.paragraph_format.first_line_indent = Pt(0)
                para.paragraph_format.line_spacing = args.line_spacing
                for el in omml_of(rec["omml"]):
                    para._element.append(copy.deepcopy(el))
                if num:
                    para.paragraph_format.tab_stops.add_tab_stop(
                        TEXT_W, WD_TAB_ALIGNMENT.RIGHT)
                    styler.apply(para.add_run("\t(%s)" % num), body_pt)
                    stats["display_num"] += 1
                else:
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                stats["display"] += 1
                continue

            if rec["kind"] == "inline":
                if not all(it["ok"] for it in rec["results"]):
                    stats["failed"] += 1
                    continue
                old_text = text
                styler.clear_runs(para)
                cursor, segs = 0, []
                for m in re.finditer(r"\$([^$]+?)\$", old_text):
                    if m.start() > cursor:
                        segs.append(("text", old_text[cursor:m.start()]))
                    segs.append(("math", m.group(1).strip()))
                    cursor = m.end()
                if cursor < len(old_text):
                    segs.append(("text", old_text[cursor:]))
                mit = iter(rec["results"])
                for kind, val in segs:
                    if kind == "text":
                        if val:
                            styler.apply(para.add_run(val), body_pt)
                    else:
                        it = next(mit, None)
                        if it and it.get("ok"):
                            for el in omml_of(it["omml"]):
                                para._element.append(copy.deepcopy(el))
                            stats["inline"] += 1
                        else:
                            styler.apply(para.add_run("$%s$" % val), body_pt)
                pf = para.paragraph_format
                pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                pf.first_line_indent = indent_pt
                pf.line_spacing = args.line_spacing
                continue

        # --- 图注
        m = CAP_RE.match(text.strip())
        if m and len(text.strip()) < 200 and not style.startswith("Heading"):
            styler.clear_runs(para)
            styler.apply(para.add_run("图%s  %s" % (m.group(1), m.group(2).strip())), 9)
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = para.paragraph_format
            pf.first_line_indent = Pt(0)
            pf.line_spacing = 1.3
            pf.space_before = Pt(3)
            pf.space_after = Pt(8)
            stats["caption"] += 1
            continue

        # --- 标题
        if style.startswith("Heading"):
            sz = para.style.font.size.pt if para.style.font.size else 14
            for r in para.runs:
                styler.apply(r, int(sz), True)
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            para.paragraph_format.first_line_indent = Pt(0)
            stats["head"] += 1
            continue

        # --- 普通正文
        para.paragraph_format.line_spacing = args.line_spacing
        t = text.strip()
        is_ref = bool(REF_RE.match(t)) and "," in t and "(" in t
        is_foot = any(t.startswith(s) for s in NO_INDENT_HEADS)
        if not t:
            para.paragraph_format.first_line_indent = Pt(0)
        elif is_ref or is_foot:
            para.paragraph_format.first_line_indent = Pt(0)
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif pi <= args.center_first:
            para.paragraph_format.first_line_indent = Pt(0)
        else:
            para.paragraph_format.first_line_indent = indent_pt
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for r in para.runs:
            sz = r.font.size.pt if r.font.size else body_pt
            styler.apply(r, sz)
        stats["para"] += 1

    doc.save(args.out)
    print("已保存:", args.out)
    print("统计:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
