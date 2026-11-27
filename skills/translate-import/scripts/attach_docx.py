# -*- coding: utf-8 -*-
"""幂等注册译文 DOCX 到 Zotero 条目（支持一次挂多个条目）。

用法：
    python attach_docx.py jobs.json [--dry-run] [--kill-zotero]

jobs.json 格式（数组，同一篇译文的多个同文条目各给一条 job 即可）：

    [
      {"itemID": 11860, "docx": "work/item_11860/译文.docx"},
      {"itemID": 11052, "docx": "work/item_11860/译文.docx"},
      {"itemID": 11493, "docx": "work/item_11860/译文.docx"}
    ]

行为：
- 每个 itemID 下若已有同名 docx 附件则跳过（幂等，可反复执行）；
- 新附件按 Zotero 原生规则单独建 storage/<新key>/ 目录，不塞进 PDF 目录；
- 直接写 zotero.sqlite，**写入前 Zotero 必须完全退出**：
  脚本默认检测到 zotero.exe 在跑就拒绝执行；`--kill-zotero` 才会强制结束它；
- `--dry-run` 只打印将要做什么，不写库、不落盘。

依赖：仅标准库 + 本技能 scripts/translate_config.py。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translate_config import cfg, ensure_utf8_stdio  # noqa: E402

ATT_TYPEID = 3  # attachment
KEY_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def new_key() -> str:
    return "".join(random.choice(KEY_CHARS) for _ in range(8))


def now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def zotero_running() -> bool:
    """Windows 下用 tasklist 粗判；其他平台用锁文件粗判。"""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq zotero.exe"],
                capture_output=True, text=True, timeout=10,
            ).stdout.lower()
            return "zotero.exe" in out
        except Exception:
            return False
    return (cfg.zotero_data_dir / "zotero.sqlite-journal").exists()


def ensure_zotero_quit(kill: bool) -> None:
    if not zotero_running():
        return
    if not kill:
        raise SystemExit(
            "Zotero 正在运行。请先完全退出 Zotero 再执行；"
            "或在确认无未保存操作后加 --kill-zotero 让脚本结束它。"
        )
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "zotero.exe"], capture_output=True)
        time.sleep(2)


def main(jobs: list[dict], dry_run: bool = False, kill_zotero: bool = False) -> int:
    db = cfg.sqlite_path
    storage = cfg.storage_dir
    if not db.exists():
        raise SystemExit(f"找不到 zotero.sqlite：{db}")
    if not dry_run:
        ensure_zotero_quit(kill_zotero)

    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")
    id2key = dict(cur.execute("SELECT itemID, key FROM items").fetchall())
    key2id = {v: k for k, v in id2key.items()}

    existing: dict[int, list[tuple[int, str]]] = {}
    for iid, parent, path in cur.execute(
        "SELECT itemID, parentItemID, path FROM itemAttachments WHERE path LIKE 'storage:%'"
    ).fetchall():
        existing.setdefault(parent, []).append((iid, path[len("storage:"):]))

    next_id = (cur.execute("SELECT MAX(itemID) FROM items").fetchone()[0] or 0) + 1
    con.close()

    added, skipped, failed = [], [], []
    for job in jobs:
        pid = int(job["itemID"])
        docx = os.path.abspath(str(job["docx"]))
        if not os.path.exists(docx):
            failed.append((pid, f"missing docx: {docx}"))
            continue
        if pid not in id2key:
            failed.append((pid, "no such item"))
            continue
        fn = os.path.basename(docx)
        if any(f == fn for _, f in existing.get(pid, [])):
            skipped.append((pid, fn))
            continue
        if dry_run:
            added.append((pid, -1, "(dry-run)", fn))
            existing.setdefault(pid, []).append((-1, fn))
            continue

        ak = new_key()
        while ak in key2id:
            ak = new_key()
        d = storage / ak
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(docx, d / fn)
        ts = now_z()
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute(
            "INSERT INTO items (itemID,itemTypeID,dateAdded,dateModified,clientDateModified,"
            "libraryID,key,version,synced) VALUES (?,?,?,?,?,?,?,?,0)",
            (next_id, ATT_TYPEID, ts, ts, ts, 1, ak, 0),
        )
        cur.execute(
            "INSERT INTO itemAttachments (itemID,parentItemID,linkMode,contentType,charsetID,"
            "path,syncState,storageModTime,storageHash,lastProcessedModificationTime,lastRead) "
            "VALUES (?,?,0,?,NULL,?,0,NULL,NULL,NULL,NULL)",
            (next_id, pid, cfg.docx_content_type, "storage:" + fn),
        )
        con.commit()
        con.close()
        existing.setdefault(pid, []).append((next_id, fn))
        key2id[ak] = next_id
        added.append((pid, next_id, ak, fn))
        next_id += 1

    print("added:", len(added), ("(dry-run)" if dry_run else ""))
    for a in added:
        print("   parent=%s att=%s key=%s %s" % a)
    print("skipped (already has same filename):", len(skipped))
    for s in skipped:
        print("   ", s)
    print("failed:", len(failed))
    for f in failed:
        print("   ", f)
    return 1 if failed else 0


def cli(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="幂等挂接译文 DOCX 到 Zotero 条目（支持多父条目）")
    ap.add_argument("jobs", help="jobs.json：[{itemID, docx}, ...]")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写库")
    ap.add_argument("--kill-zotero", action="store_true", help="Zotero 在运行时强制结束它")
    args = ap.parse_args(argv)
    jobs = json.load(open(args.jobs, encoding="utf-8"))
    return main(jobs, dry_run=args.dry_run, kill_zotero=args.kill_zotero)


if __name__ == "__main__":
    raise SystemExit(cli())
