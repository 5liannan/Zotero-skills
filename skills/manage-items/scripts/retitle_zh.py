# -*- coding: utf-8 -*-
"""把条目标题统一为中文译名。

译名来源（按优先级）：
1. --map 提供的 JSON/TSV（{"itemID": "中文标题"} 或 "itemID<TAB>中文标题"）
2. 条目「其他」字段中的 `Chinese Title:` 行
默认跳过已经是中文的标题；--force 强制覆盖。

用法:
    python retitle_zh.py --map zh.json [--apply]
"""
import argparse
import json
import os
import re
import sys

from config import ensure_utf8_stdio
from zoterodb import DB, connect, backup, CJK

ensure_utf8_stdio()


def load_map(path):
    if path.lower().endswith(".json"):
        raw = json.load(open(path, encoding="utf-8"))
        return {int(k): str(v).strip() for k, v in raw.items()}
    out = {}
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if not line or "\t" not in line:
            continue
        a, b = line.split("\t", 1)
        out[int(a)] = b.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="itemID -> 中文标题 的 JSON/TSV")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="已经是中文也覆盖")
    args = ap.parse_args()

    zh = load_map(args.map)
    con = connect(readonly=not args.apply)
    db = DB(con)
    ids = db.items()

    todo, skip_zh, no_map = [], 0, []
    for iid in ids:
        t = db.title(iid)
        if CJK.search(t or "") and not args.force:
            skip_zh += 1
            continue
        if iid in zh:
            todo.append((iid, t, zh[iid]))
        elif not CJK.search(t or ""):
            no_map.append(iid)

    print("待改: %d ｜ 已是中文跳过: %d ｜ 英文但无译名: %d" % (len(todo), skip_zh, len(no_map)))
    for iid, old, new in todo[:5]:
        print("  %-6d %s\n         -> %s" % (iid, (old or "")[:56], new[:56]))

    if args.apply and todo:
        bak = backup(tag="retitle")
        print("备份:", bak)
        for iid, old, new in todo:
            # 英文原名写进「其他」，供 PDF 命名与回溯
            if old and not CJK.search(old) and "Original Title:" not in (db.get(iid, "extra") or ""):
                extra = (db.get(iid, "extra") or "").strip()
                db.set(iid, "extra", (extra + "\nOriginal Title: " + old).strip(), touch=False)
            db.set(iid, "title", new)
        con.commit()
        print("已写入 %d 条" % len(todo))
        bad = con.execute("PRAGMA integrity_check").fetchone()[0]
        print("integrity:", bad)
    elif not args.apply:
        print("[dry-run] 未写入；加 --apply 生效")
    con.close()
    if no_map:
        print("\n需要补译名的条目（前 20）:", no_map[:20])


if __name__ == "__main__":
    sys.exit(main())
