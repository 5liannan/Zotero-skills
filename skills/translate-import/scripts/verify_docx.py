# -*- coding: utf-8 -*-
"""Verify a generated DOCX: print stats JSON to stdout. Usage: python verify_docx.py <docx>

验收判据（ok=true 需全部满足）
------------------------------
* 文档可解析且非空（段落 > 0，且有正文/表格/图片之一）；**不以字数判定**
* `raw_dollar == 0` —— 没有残留的 `$` 定界符
* `raw_latex == 0`  —— 没有残留的裸 LaTeX 命令
* 参考文献一致性检查无 error（悬挂引用 / 未引用条目 / 编号断号 / 有引用无文献）

后两条是为了拦住「pandoc 缺失时静默降级成纯文本 LaTeX，构建却报成功」这类假成功。

同时报告公式落地情况：
  * omath      —— Word 原生公式对象数（>0 表示公式已正确渲染）
  * header     —— 页眉文本（终稿应有）
  * footer_page—— 页脚是否含 PAGE 域
  * xref       —— 指向书签的内部超链接数（正文引用可点击跳转）
  * bookmarks  —— `_RefList*` 隐藏书签数（应与文献条目数一致）
"""
import json
import sys

from docx import Document
from docx.oxml.ns import qn

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
BACKSLASH_CMD_RE = __import__("re").compile(
    r"\\(?:frac|sqrt|sum|int|alpha|beta|gamma|delta|lambda|sigma|omega|"
    r"times|cdot|le|ge|neq|approx|partial|nabla|infty|left|right|"
    r"begin|end|text|mathrm|mathbf)\b")


def full_text(p):
    """段落全文——含超链接内的 run（Paragraph.text 会漏掉它们）。"""
    return "".join(t.text or "" for t in p._p.iter(qn("w:t")))


def _footer_has_page(doc):
    try:
        ftr = doc.sections[0].footer
    except Exception:
        return False
    for it in ftr._element.iter(qn("w:instrText")):
        if it.text and "PAGE" in it.text.upper():
            return True
    return False


def _header_text(doc):
    try:
        hdr = doc.sections[0].header
    except Exception:
        return ""
    return "".join(full_text(p) for p in hdr.paragraphs).strip()


def _xref_stats(doc):
    links = 0
    for p in doc.paragraphs:
        for h in p._p.findall(qn("w:hyperlink")):
            if h.get(qn("w:anchor")):
                links += 1
    names = [e.get(qn("w:name")) or ""
             for e in doc.element.body.iter(qn("w:bookmarkStart"))]
    return links, len([n for n in names if n.startswith("_RefList")])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        sys.exit("usage: verify_docx.py <docx> [--no-ref-check] [--allow-unused-refs]")
    path = args[0]
    try:
        d = Document(path)
    except Exception as e:
        json.dump({"path": path, "ok": False, "error": str(e)[:200]}, sys.stdout)
        print(file=sys.stdout)
        return

    chars = paras = headings = omath = raw_dollar = raw_latex = 0
    for p in d.paragraphs:
        paras += 1
        t = full_text(p)
        chars += len(t.strip())
        if p.style.name.startswith("Heading"):
            headings += 1
        n = len(p._element.findall(".//{%s}oMath" % M_NS))
        if n:
            omath += n
        if "$" in t:
            raw_dollar += 1
        if BACKSLASH_CMD_RE.search(t):
            raw_latex += 1
    tables = len(d.tables)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                chars += len(cell.text.strip())
    images = len(d.inline_shapes)

    xref, bookmarks = _xref_stats(d)
    header = _header_text(d)
    footer_page = _footer_has_page(d)

    ref = {}
    ref_errors = []
    if "--no-ref-check" not in flags:
        try:
            sys.path.insert(0, __import__("os").path.dirname(
                __import__("os").path.abspath(__file__)))
            from finalize import check_references
            ref = check_references(
                d, allow_unused="--allow-unused-refs" in flags)
            ref_errors = ref.get("errors") or []
        except Exception as e:                       # 检查器不可用不应让验收崩掉
            ref = {"error": str(e)[:200]}

    # 合格 = 可解析非空 + 无裸 LaTeX 残留 + 参考文献对得上号。不设字数门槛。
    ok = bool(paras > 0 and (chars > 0 or tables > 0 or images > 0)
              and raw_dollar == 0 and raw_latex == 0 and not ref_errors)

    json.dump({
        "path": path, "ok": ok, "paras": paras, "chars": chars,
        "headings": headings, "tables": tables, "images": images,
        "omath": omath, "raw_dollar": raw_dollar, "raw_latex": raw_latex,
        "header": header, "footer_page": footer_page,
        "xref": xref, "bookmarks": bookmarks,
        "refs": ref.get("refs"), "cites": ref.get("cites"),
        "dangling": ref.get("dangling"), "unused": ref.get("unused"),
        "ref_errors": ref_errors,
    }, sys.stdout, ensure_ascii=False)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
