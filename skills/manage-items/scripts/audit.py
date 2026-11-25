# -*- coding: utf-8 -*-
"""审计：条目标题语言、附件命名、PDF/DOCX 分目录、库内记录与磁盘文件一致性。

只读，不改库。输出 audit.json / audit.csv 与终端摘要。

用法:
    python audit.py [--out DIR] [--limit N]
"""
import argparse
import csv
import json
import os
import re
import sys

from config import cfg, ensure_utf8_stdio
from zoterodb import DB, connect, CJK

ensure_utf8_stdio()

DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def classify(path, ctype):
    p = (path or "").lower()
    if p.endswith(".pdf") or (ctype or "").startswith("application/pdf"):
        return "pdf"
    if p.endswith(".docx") or ctype == DOCX_CT:
        return "docx"
    if p.endswith(".doc"):
        return "doc"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--collection", type=int, default=None, help="只处理该分类(collectionID)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    con = connect(readonly=True)
    db = DB(con)
    ids = db.items(collection=args.collection)
    if args.limit:
        ids = ids[:args.limit]

    rows = []
    no_zh = []
    stat = {"items": len(ids), "pdf": 0, "docx": 0, "other": 0,
            "title_prefix_bad": 0, "filename_bad": 0, "missing_file": 0,
            "shared_dir": 0, "has_pdf_no_docx": 0, "no_pdf": 0, "orphan_docx_unlinked": 0}

    for iid in ids:
        title = db.title(iid)
        zh = bool(CJK.search(title or ""))
        if not zh:
            no_zh.append({"itemID": iid, "title": title})

        atts = db.attachments(iid)
        has_pdf = has_docx = False
        dirs = {}
        for aid, link, path, ctype, akey in atts:
            kind = classify(path, ctype)
            if kind == "pdf":
                stat["pdf"] += 1
                has_pdf = True
            elif kind in ("docx", "doc"):
                stat["docx"] += 1
                has_docx = True
            else:
                stat["other"] += 1
                continue

            atitle = db.get(aid, "title")
            want = cfg["pdf_title_prefix"] if kind == "pdf" else cfg["docx_title_prefix"]
            if not (atitle or "").startswith(want):
                stat["title_prefix_bad"] += 1

            fpath = db.file_of(aid, path, akey)
            fname = os.path.basename(fpath) if fpath else ""
            if fpath and not os.path.exists(fpath):
                stat["missing_file"] += 1
            if fpath:
                dirs.setdefault(os.path.dirname(fpath), []).append(fname)
            rows.append({
                "itemID": iid, "title_zh": title, "att_itemID": aid, "kind": kind,
                "linkMode": link, "att_title": atitle, "filename": fname,
                "path": path, "exists": os.path.exists(fpath) if fpath else False,
                "prefix_ok": (atitle or "").startswith(want),
            })

        if has_pdf and not has_docx:
            stat["has_pdf_no_docx"] += 1
        if not has_pdf and not has_docx:
            stat["no_pdf"] += 1
        for d, files in dirs.items():
            if len(files) > 1:
                stat["shared_dir"] += 1
                break

    # 磁盘上存在但未登记的目录
    registered = {r[0] for r in con.execute("SELECT key FROM items")}
    storage = cfg["storage_dir"]
    orphan_dirs = []
    if os.path.isdir(storage):
        for d in os.listdir(storage):
            p = os.path.join(storage, d)
            if os.path.isdir(p) and d not in registered:
                orphan_dirs.append(d)

    con.close()

    report = {"stats": stat, "non_chinese_titles": no_zh,
              "orphan_storage_dirs": orphan_dirs, "attachments": rows}
    json.dump(report, open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "audit.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["itemID"])
        w.writeheader()
        w.writerows(rows)

    print("=" * 56)
    print("条  目: %d（其中标题非中文 %d）" % (stat["items"], len(no_zh)))
    print("附  件: PDF %d | DOCX %d | 其他 %d" % (stat["pdf"], stat["docx"], stat["other"]))
    print("命名  : 标题前缀不合规 %d ｜ 磁盘缺失文件 %d" % (stat["title_prefix_bad"], stat["missing_file"]))
    print("目录  : 多附件共用目录 %d 个条目 ｜ 未登记目录 %d 个" % (stat["shared_dir"], len(orphan_dirs)))
    print("译  文: 有 PDF 无 DOCX %d ｜ 无任何附件 %d" % (stat["has_pdf_no_docx"], stat["no_pdf"]))
    print("=" * 56)
    print("报告:", os.path.join(args.out, "audit.json"))
    if no_zh[:5]:
        print("\n标题非中文示例:")
        for x in no_zh[:5]:
            print("  %-6d %s" % (x["itemID"], (x["title"] or "")[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
