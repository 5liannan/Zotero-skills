# -*- coding: utf-8 -*-
"""Verify a generated DOCX: print stats JSON to stdout. Usage: python verify_docx.py <docx>

同时报告公式落地情况：
  * omath      —— Word 原生公式对象数（>0 表示公式已正确渲染）
  * raw_dollar —— 仍残留 $ 定界符的段落数（>0 说明有公式未转换）
  * raw_latex  —— 仍残留反斜杠 LaTeX 命令的段落数
"""
import json, sys
from docx import Document
from docx.oxml.ns import qn

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
BACKSLASH_CMD_RE = __import__("re").compile(
    r"\\(?:frac|sqrt|sum|int|alpha|beta|gamma|delta|lambda|sigma|omega|"
    r"times|cdot|le|ge|neq|approx|partial|nabla|infty|left|right|"
    r"begin|end|text|mathrm|mathbf)\b")


def main():
    path = sys.argv[1]
    try:
        d = Document(path)
    except Exception as e:
        json.dump({"path": path, "ok": False, "error": str(e)[:200]}, sys.stdout)
        print(file=sys.stdout)
        return
    chars = 0
    paras = 0
    headings = 0
    omath = 0
    raw_dollar = 0
    raw_latex = 0
    for p in d.paragraphs:
        paras += 1
        chars += len(p.text.strip())
        if p.style.name.startswith("Heading"):
            headings += 1
        n = len(p._element.findall(".//{%s}oMath" % M_NS))
        if n:
            omath += n
        if "$" in p.text:
            raw_dollar += 1
        if BACKSLASH_CMD_RE.search(p.text):
            raw_latex += 1
    tables = len(d.tables)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                chars += len(cell.text.strip())
    images = len(d.inline_shapes)
    # Quality is sentence-by-sentence fidelity to the English source; no char thresholds.
    ok = paras > 0 and (chars > 0 or tables > 0 or images > 0)
    json.dump({
        "path": path, "ok": ok, "paras": paras, "chars": chars,
        "headings": headings, "tables": tables, "images": images,
        "omath": omath, "raw_dollar": raw_dollar, "raw_latex": raw_latex,
    }, sys.stdout, ensure_ascii=False)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
