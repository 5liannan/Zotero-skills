#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给 DOCX 加「可点击跳转」的参考文献交叉引用（不改编号文本、不引入域）。

做什么
------
1. 找到「参考文献 / References」标题，其后的 `[n] xxx` 段落各加一个隐藏书签 `_RefList{n}`；
2. 把正文里的引用标记 `[5]` / `[5, 6, 10]` 换成指向对应书签的内部超链接
   （`<w:hyperlink w:anchor="_RefList5">`），点击即跳到该条文献。

为什么不用 REF 域
-----------------
`{ REF _RefN \\r \\h }` 会**把列表编号的格式一起带出来**（实测：编号格式 `[%1]`
时域结果是 `[1]` 而非 `1`），因此同一对方括号里放多篇文献（`[5, 6]`）会变成
`[[5], [6]]`。要支持分组引用，要么把列表编号改成不带方括号的 `%1`，要么改用
本脚本的纯超链接方案。本脚本选后者：**编号文本原样不动，只加跳转**。

代价：编号是死文本，增删文献不会自动重编号（如需自动重编号，见 SKILL.md
「交叉引用」一节列出的两个已实测可行的域方案）。

用法
----
    python add_xref.py in.docx out.docx
    python add_xref.py in.docx out.docx --prefix _RefList --hyperlink-style

默认 `--hyperlink-style` 关闭：引用保持正文字体（黑、无下划线），与 Word 原生
交叉引用外观一致；打开则套用蓝色下划线超链接样式，便于一眼看出可点击。

注意
----
- 引用标记的 run 会被拆成 `文字 / 超链接 / 文字` 片段，原有 `w:rPr` 逐段复制，
  字体字号不变；
- 公式对象（`m:oMath`）不受影响；
- python-docx 的 `Paragraph.text` **不含** `w:hyperlink` 内的 run，验收时需用
  `''.join(t.text for t in p._p.iter(qn('w:t')))` 才能取到完整文本；
- 只匹配 `[1]` / `[1, 2]` / `[1，2]` / `[1、2]`；区间写法 `[5-7]` 不匹配（会原样保留）。
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import sys

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

HEAD_RE = re.compile(r"^\s*(参考文献|參考文獻|References|REFERENCES)\s*$")
REF_ITEM_RE = re.compile(r"^\s*\[(\d+)\]\s")
CITE_FIND = re.compile(r"\[(\d+(?:\s*[,，、]\s*\d+)*)\]")
NUM_SPLIT = re.compile(r"\s*[,，、]\s*")


def full_text(p):
    """段落全文（含超链接内的 run；Paragraph.text 会漏掉它们）"""
    return "".join(t.text or "" for t in p._p.iter(qn("w:t")))


def _mk_run(rPr, text, link_style=False):
    r = OxmlElement("w:r")
    if rPr is not None:
        nrPr = copy.deepcopy(rPr)
        if link_style:
            for tag in ("w:color", "w:u"):
                el = nrPr.find(qn(tag))
                if el is not None:
                    nrPr.remove(el)
            nrPr.insert(0, OxmlElement("w:rStyle"))
            nrPr[0].set(qn("w:val"), "Hyperlink")
        r.append(nrPr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    return r


def _mk_link(rPr, text, anchor, link_style=False):
    h = OxmlElement("w:hyperlink")
    h.set(qn("w:anchor"), anchor)
    h.set(qn("w:history"), "1")
    h.append(_mk_run(rPr, text, link_style))
    return h


def _next_bookmark_id(doc):
    ids = []
    for e in doc.element.body.iter(qn("w:bookmarkStart")):
        v = e.get(qn("w:id"))
        if v and v.lstrip("-").isdigit():
            ids.append(int(v))
    return (max(ids) + 1) if ids else 1


def run_add_xref(src, dst, prefix="_RefList", link_style=False, quiet=False):
    def log(*a):
        if not quiet:
            print(*a)

    doc = Document(src)
    ps = doc.paragraphs

    # --- 1. 定位参考文献标题与条目 -------------------------------------
    head = None
    for i, p in enumerate(ps):
        if HEAD_RE.match(p.text):
            head = i
            break
    if head is None:
        raise SystemExit("未找到「参考文献 / References」标题段，无法定位文献列表")

    ref_map = {}
    first = last = None
    for i in range(head + 1, len(ps)):
        m = REF_ITEM_RE.match(ps[i].text.strip())
        if m and len(ps[i].runs) == 1:
            ref_map[int(m.group(1))] = ps[i]
            first = i if first is None else first
            last = i
        elif ref_map:
            break
    if not ref_map:
        raise SystemExit("「参考文献」标题之后没有找到 `[n] ...` 形式的条目段")
    log("参考文献标题段 = %d；条目 %d 条（段 %d-%d）" % (head, len(ref_map), first, last))

    nums = sorted(ref_map)
    gap = [n for n in range(1, max(nums) + 1) if n not in ref_map]
    if gap:
        log("  注意：编号不连续，缺 %s" % gap)

    # --- 2. 给文献条目加书签 -------------------------------------------
    bid = _next_bookmark_id(doc)
    for n in nums:
        p = ref_map[n]
        pPr = p._p.find(qn("w:pPr"))
        pos = (list(p._p).index(pPr) + 1) if pPr is not None else 0
        s = OxmlElement("w:bookmarkStart")
        s.set(qn("w:id"), str(bid))
        s.set(qn("w:name"), "%s%d" % (prefix, n))
        e = OxmlElement("w:bookmarkEnd")
        e.set(qn("w:id"), str(bid))
        p._p.insert(pos, s)
        p._p.append(e)
        bid += 1
    log("新增书签 = %d（%s1 … %s%d）" % (len(nums), prefix, prefix, max(nums)))

    # --- 3. 正文引用标记 -> 内部超链接 ---------------------------------
    replaced = links = 0
    skipped = []
    for i in range(0, head):
        for run in list(ps[i].runs):
            t = run.text
            if not t or "[" not in t:
                continue
            hits = list(CITE_FIND.finditer(t))
            if not hits:
                continue
            r = run._r
            parent = r.getparent()
            pos = list(parent).index(r)
            rPr = r.find(qn("w:rPr"))

            new = []
            cursor = 0
            ok = True
            for m in hits:
                groups = []
                for chunk in NUM_SPLIT.split(m.group(1)):
                    try:
                        groups.append(int(chunk))
                    except ValueError:
                        ok = False
                if not ok or any(x not in ref_map for x in groups):
                    ok = False
                    break
                if m.start() > cursor:
                    new.append(_mk_run(rPr, t[cursor:m.start()]))
                if len(groups) == 1:
                    new.append(_mk_link(rPr, "[%d]" % groups[0],
                                        "%s%d" % (prefix, groups[0]), link_style))
                    links += 1
                else:
                    new.append(_mk_run(rPr, "["))
                    for k, x in enumerate(groups):
                        if k:
                            new.append(_mk_run(rPr, ", "))
                        new.append(_mk_link(rPr, str(x), "%s%d" % (prefix, x), link_style))
                        links += 1
                    new.append(_mk_run(rPr, "]"))
                cursor = m.end()
            if not ok or not new:
                if not ok:
                    skipped.append((i, t[:70]))
                continue
            if cursor < len(t):
                new.append(_mk_run(rPr, t[cursor:]))

            for k, el in enumerate(new):
                parent.insert(pos + k, el)
            parent.remove(r)
            replaced += 1

    log("替换引用 run = %d 个；生成超链接 = %d 个" % (replaced, links))
    if skipped:
        log("  跳过 %d 处（引用编号在文献列表中不存在）：" % len(skipped))
        for i, s in skipped[:10]:
            log("    段%d: %r" % (i, s))

    doc.save(dst)
    log("saved -> %s" % dst)
    return {"refs": len(nums), "links": links, "replaced": replaced}


def main():
    ap = argparse.ArgumentParser(description="给 DOCX 加参考文献交叉引用超链接")
    ap.add_argument("src", help="输入 .docx")
    ap.add_argument("dst", help="输出 .docx")
    ap.add_argument("--prefix", default="_RefList", help="书签名前缀（默认 _RefList）")
    ap.add_argument("--hyperlink-style", action="store_true",
                    help="套用蓝色下划线超链接样式（默认保持正文字体外观）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if os.path.abspath(a.src) == os.path.abspath(a.dst):
        sys.exit("输入输出不能是同一个文件（先写到临时文件再覆盖）")
    run_add_xref(a.src, a.dst, a.prefix, a.hyperlink_style, a.quiet)


if __name__ == "__main__":
    main()
