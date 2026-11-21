# -*- coding: utf-8 -*-
"""把共用同一 storage 目录的附件拆到各自目录（一附件一目录）。

Zotero 原生规则是一个附件一个 storage/<key>/ 目录；历史上 PDF 与译文 DOCX
常被放进同一目录，本脚本按附件逐条搬迁并改写 path 与附件 key。

用法:
    python split_storage.py [--apply] [--limit N]
"""
import argparse
import os
import sys

from config import cfg, ensure_utf8_stdio
from zoterodb import DB, connect, backup

ensure_utf8_stdio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = connect(readonly=not args.apply)
    db = DB(con)
    ids = db.items()
    if args.limit:
        ids = ids[:args.limit]

    targets = []
    for iid in ids:
        by_dir = {}
        for aid, link, path, ctype, akey in db.attachments(iid):
            if link != 0 or not (path or "").startswith("storage:"):
                continue
            d = os.path.join(cfg["storage_dir"], akey)
            if not os.path.isdir(d):
                continue
            files = [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
            by_dir.setdefault(akey, []).extend(files)
        for akey, files in by_dir.items():
            if len(files) > 1:
                targets.append((iid, akey, files))

    print("共用目录: %d 个（涉及 %d 个条目）" % (len(targets), len({t[0] for t in targets})))
    for iid, akey, files in targets[:6]:
        print("  item %-6d %s -> %s" % (iid, akey, files))

    if not args.apply:
        print("[dry-run] 未写入；加 --apply 生效")
        con.close()
        return 0
    if not targets:
        con.close()
        return 0

    print("备份:", backup(tag="split"))
    moved = 0
    seen = set()
    for iid, akey, _ in targets:
        # 该目录下所有附件逐个迁出，保留第一个原目录
        atts = [a for a in db.attachments(iid) if a[4] == akey and a[1] == 0]
        keep = True
        for aid, link, path, ctype, k in atts:
            if keep:
                keep = False
                continue
            if aid in seen:
                continue
            dst, st = db.move_attachment_to_own_dir(aid)
            if dst:
                moved += 1
                seen.add(aid)
    con.commit()
    print("搬迁 %d 个附件 ｜ integrity: %s" %
          (moved, con.execute("PRAGMA integrity_check").fetchone()[0]))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
