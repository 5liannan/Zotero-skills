# -*- coding: utf-8 -*-
"""校验：命名规范、一附件一目录、库内记录与磁盘一致。

退出码 0 全部通过；1 存在问题（见输出）。

用法:
    python verify.py [--expect-docx]
"""
import argparse
import os
import re
import sys

from config import cfg, ensure_utf8_stdio
from zoterodb import DB, connect, render, clean_title, CJK

ensure_utf8_stdio()
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def kind(path, ctype):
    p = (path or "").lower()
    if p.endswith(".pdf") or (ctype or "").startswith("application/pdf"):
        return "pdf"
    if p.endswith(".docx") or ctype == DOCX_CT:
        return "docx"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-docx", action="store_true", help="要求有 PDF 的条目也必须有 DOCX")
    ap.add_argument("--collection", type=int, default=None, help="只处理该分类(collectionID)")
    args = ap.parse_args()

    con = connect(readonly=True)
    db = DB(con)
    bad_title, bad_name, missing, shared, no_docx = [], [], [], [], []
    n_att = 0
    for iid in db.items(collection=args.collection):
        zh = db.title(iid)
        en = None
        m = re.search(r"Original Title:\s*(.+)", db.get(iid, "extra") or "")
        if m:
            en = m.group(1).strip()
        author, year = db.first_author_surname(iid), db.year_of(iid)
        kinds = set()
        by_dir = {}
        for aid, link, path, ctype, akey in db.attachments(iid):
            k = kind(path, ctype)
            if k == "other":
                continue
            kinds.add(k)
            n_att += 1
            at = db.get(aid, "title") or ""
            prefix = cfg["pdf_title_prefix"] if k == "pdf" else cfg["docx_title_prefix"]
            if not at.startswith(prefix):
                bad_title.append((aid, iid, at[:50]))
            fp = db.file_of(aid, path, akey)
            if not fp or not os.path.exists(fp):
                missing.append((aid, iid, path))
            else:
                by_dir.setdefault(os.path.dirname(fp), []).append(os.path.basename(fp))
                src = en if k == "pdf" else (zh if CJK.search(zh or "") else en)
                if src:
                    pat = cfg["pdf_filename"] if k == "pdf" else cfg["docx_filename"]
                    want = render(pat, author, year, en or src,
                                  clean_title(zh) if CJK.search(zh or "") else src)
                    if os.path.basename(fp) != want:
                        bad_name.append((aid, iid, os.path.basename(fp)[:44], want[:44]))
        for d, files in by_dir.items():
            if len(files) > 1:
                shared.append((iid, os.path.basename(d), files))
        if args.expect_docx and "pdf" in kinds and "docx" not in kinds:
            no_docx.append(iid)

    print("附件总数:", n_att)
    print("标题缺前缀 :", len(bad_title))
    print("文件名不合规:", len(bad_name))
    print("磁盘缺文件 :", len(missing))
    print("共用目录   :", len(shared))
    if args.expect_docx:
        print("有 PDF 无译文:", len(no_docx))
    for label, arr in (("前缀", bad_title), ("命名", bad_name), ("缺文件", missing)):
        for x in arr[:3]:
            print("  [%s] %s" % (label, x))
    con.close()
    ok = not (bad_title or bad_name or missing or shared or (args.expect_docx and no_docx))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
