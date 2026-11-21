# -*- coding: utf-8 -*-
"""把磁盘上已有的中文译文 DOCX 挂到对应条目下（补齐缺失译文附件）。

匹配方式：
1. --map 显式映射 {"itemID": "路径"} 或 "itemID<TAB>路径"
2. --dir 目录扫描：按中文标题归一化后与条目标题精确/包含匹配

挂载时按规范命名：标题栏 [docx]<中文标题>，文件名 <作者>等 - <年> - <中文标题>.docx，
并复制到该附件独占的 storage 目录。

用法:
    python link_docx.py --dir "E:/翻译稿" [--apply]
    python link_docx.py --map docx_map.tsv [--apply]
"""
import argparse
import json
import os
import re
import sys
import unicodedata

from config import ensure_utf8_stdio, cfg
from zoterodb import DB, connect, backup, render, CJK

ensure_utf8_stdio()
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fa5]", "", s)


def load_map(path):
    if path.lower().endswith(".json"):
        raw = json.load(open(path, encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    out = {}
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        if not line or "\t" not in line:
            continue
        a, b = line.split("\t", 1)
        out[int(a)] = b.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="译文 DOCX 所在目录")
    ap.add_argument("--map", help="itemID -> docx 路径")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有 DOCX 也再挂一份")
    args = ap.parse_args()
    if not args.dir and not args.map:
        print("需要 --dir 或 --map")
        return 2

    con = connect(readonly=not args.apply)
    db = DB(con)
    ids = db.items()

    # 建立 中文标题 -> itemID 索引
    by_title = {}
    for iid in ids:
        t = norm(db.title(iid))
        if t:
            by_title.setdefault(t, iid)

    pairs = []
    if args.map:
        for iid, p in load_map(args.map).items():
            if os.path.exists(p):
                pairs.append((iid, p))
            else:
                print("  路径不存在:", p)
    if args.dir:
        for fn in os.listdir(args.dir):
            if not fn.lower().endswith(".docx") or fn.startswith("~$"):
                continue
            p = os.path.join(args.dir, fn)
            stem = norm(os.path.splitext(fn)[0])
            iid = by_title.get(stem)
            if not iid:
                # 退化：目录名包含关系
                cand = [v for k, v in by_title.items() if stem and (stem in k or k in stem)]
                iid = cand[0] if len(cand) == 1 else None
            if iid:
                pairs.append((iid, p))

    seen, final = set(), []
    for iid, p in pairs:
        if iid in seen:
            continue
        seen.add(iid)
        final.append((iid, p))

    todo = []
    for iid, p in final:
        has = any((x[2] or "").lower().endswith((".docx", ".doc")) for x in db.attachments(iid))
        if has and not args.force:
            continue
        todo.append((iid, p))

    print("可挂载: %d ｜ 已有译文跳过: %d" % (len(todo), len(final) - len(todo)))
    for iid, p in todo[:8]:
        print("  %-6d %s <- %s" % (iid, db.title(iid)[:40], os.path.basename(p)[:46]))

    if not args.apply:
        print("[dry-run] 未写入；加 --apply 生效")
        con.close()
        return 0
    if not todo:
        con.close()
        return 0

    print("备份:", backup(tag="linkdocx"))
    ok = 0
    for iid, p in todo:
        zh = db.title(iid)
        en = (re.search(r"Original Title:\s*(.+)", db.get(iid, "extra") or "") or [None, None])[1] if False else None
        m = re.search(r"Original Title:\s*(.+)", db.get(iid, "extra") or "")
        en = m.group(1).strip() if m else None
        author = db.first_author_surname(iid)
        year = db.year_of(iid)
        fname = render(cfg["docx_filename"], author, year, en or zh, zh)
        title = cfg["docx_title_prefix"] + (zh if CJK.search(zh or "") else (en or ""))
        db.add_file_attachment(iid, p, fname, DOCX_CT, title)
        ok += 1
    con.commit()
    print("挂载 %d ｜ integrity: %s" % (ok, con.execute("PRAGMA integrity_check").fetchone()[0]))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
