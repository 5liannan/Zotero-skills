# -*- coding: utf-8 -*-
"""Zotero storage / attachment hygiene tool.

Implements docs/zotero-storage-management.md:
  check | split | dedup-hash | dedup-parent | clean-bak | align | restore | doctor

Never hard-deletes user files: extras go to $ZOTERO_WORK_BASE/quarantine_*.
Writes zotero.sqlite only when needed (split / dedup-parent / align / restore).
Caller must fully quit Zotero before write steps and keep a DB backup (auto).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CJK = re.compile(r"[一-鿿]")
ATT_TYPEID = 3  # Zotero itemTypes.attachment


def env_path(name: str, default: Path | None = None) -> Path:
    v = os.environ.get(name, "").strip()
    return Path(v) if v else (default or Path("."))


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    data = Path(args.data_dir) if args.data_dir else env_path("ZOTERO_DATA_DIR")
    if args.sqlite:
        db = Path(args.sqlite)
    elif os.environ.get("ZOTERO_SQLITE"):
        db = Path(os.environ["ZOTERO_SQLITE"])
    else:
        db = data / "zotero.sqlite"
    if args.storage:
        storage = Path(args.storage)
    elif os.environ.get("ZOTERO_STORAGE"):
        storage = Path(os.environ["ZOTERO_STORAGE"])
    else:
        storage = data / "storage"
    work = Path(args.work) if args.work else env_path("ZOTERO_WORK_BASE", Path.cwd())
    return data, db, storage, work


def open_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def open_rw(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise SystemExit(f"DB not found: {db}")
    # fail fast if Zotero holds the DB
    try:
        probe = sqlite3.connect(f"file:{db.as_posix()}?mode=rw", uri=True, timeout=5)
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()
        probe.close()
    except sqlite3.OperationalError as e:
        raise SystemExit(
            f"DB locked ({e}). Fully quit Zotero before write steps."
        ) from e
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=rw", uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def backup_db(db: Path, tag: str) -> Path:
    dest = db.parent / f"zotero.sqlite.bak_before_{tag}_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db, dest)
    return dest


def new_key() -> str:
    return "".join(KEY_ALPHABET[b % len(KEY_ALPHABET)] for b in uuid.uuid4().bytes[:8])


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_bak(name: str) -> bool:
    return "bak" in name.lower() or name.lower().endswith(".bak")


def visible_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [
        p
        for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and not is_bak(p.name)
    ]


def quar_dir(work: Path, name: str) -> Path:
    q = work / name
    q.mkdir(parents=True, exist_ok=True)
    return q


def move_to_quar(p: Path, quar: Path, keep_tree: bool = True) -> Path:
    dest_root = quar / (p.parent.name if keep_tree else "")
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / p.name
    if dest.exists():
        dest = dest_root / f"{int(time.time())}_{p.name}"
    shutil.move(str(p), str(dest))
    return dest


def path_filename(path: str | None) -> str:
    if not path:
        return ""
    return path.split("storage:", 1)[-1].split("/")[-1]


def pick_main(folder: Path, ctype: str | None) -> Path | None:
    files = visible_files(folder)
    if not files:
        return None
    ctype = (ctype or "").lower()
    if "pdf" in ctype:
        pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
        return pdfs[0] if pdfs else files[0]
    if "word" in ctype or "docx" in ctype:
        docs = [p for p in files if p.suffix.lower() == ".docx"]
        return docs[0] if docs else files[0]
    return files[0]


def cjk_count(path: Path) -> int:
    try:
        from docx import Document  # type: ignore

        d = Document(str(path))
        t = "\n".join(p.text for p in d.paragraphs)
        return len(CJK.findall(t))
    except Exception:
        return 0


def write_report(work: Path, step: str, payload: dict) -> Path:
    out = work / f"{step}_result.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {out}")
    return out


def load_atts(db: Path) -> list[dict]:
    con = open_ro(db)
    rows = con.execute(
        """
        SELECT ia.itemID AS item_id,
               ia.parentItemID AS parent_id,
               i.key AS key,
               ia.path AS path,
               ia.contentType AS ctype,
               pi.key AS parent_key
        FROM itemAttachments ia
        JOIN items i ON i.itemID = ia.itemID
        LEFT JOIN items pi ON pi.itemID = ia.parentItemID
        """
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def ensure_value_id(cur: sqlite3.Cursor, val: str) -> int:
    cur.execute("SELECT valueID FROM itemDataValues WHERE value=?", (val,))
    hit = cur.fetchone()
    if hit:
        return hit[0]
    cur.execute("INSERT INTO itemDataValues (value) VALUES (?)", (val,))
    return cur.lastrowid


def set_title(cur: sqlite3.Cursor, item_id: int, title_field: int, title: str) -> None:
    vid = ensure_value_id(cur, title)
    cur.execute(
        "SELECT valueID FROM itemData WHERE itemID=? AND fieldID=?",
        (item_id, title_field),
    )
    ex = cur.fetchone()
    if ex:
        if ex[0] == vid:
            return
        shared = cur.execute(
            "SELECT COUNT(*) FROM itemData WHERE valueID=?", (ex[0],)
        ).fetchone()[0]
        if shared == 1:
            try:
                cur.execute(
                    "UPDATE itemDataValues SET value=? WHERE valueID=?",
                    (title, ex[0]),
                )
                return
            except sqlite3.IntegrityError:
                pass
        cur.execute(
            "UPDATE itemData SET valueID=? WHERE itemID=? AND fieldID=?",
            (vid, item_id, title_field),
        )
    else:
        cur.execute(
            "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?,?,?)",
            (item_id, title_field, vid),
        )


def delete_attachment(cur: sqlite3.Cursor, item_id: int) -> None:
    # Hard-remove attachment metadata; file itself is already quarantined.
    cur.execute("DELETE FROM itemData WHERE itemID=?", (item_id,))
    cur.execute("DELETE FROM itemAttachments WHERE itemID=?", (item_id,))
    cur.execute("DELETE FROM itemNotes WHERE itemID=?", (item_id,))
    cur.execute("DELETE FROM itemCreators WHERE itemID=?", (item_id,))
    cur.execute("DELETE FROM deletedItems WHERE itemID=?", (item_id,))
    cur.execute("DELETE FROM items WHERE itemID=?", (item_id,))


# ----- steps -----


def cmd_check(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    atts = load_atts(db)
    mixed = []
    multi_docx: dict[str | None, list] = defaultdict(list)
    bak_files = []
    for folder in sorted(storage.iterdir()):
        if not folder.is_dir():
            continue
        pdfs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
        docxs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".docx"]
        if pdfs and docxs:
            mixed.append(str(folder))
        for p in folder.iterdir():
            if p.is_file() and is_bak(p.name):
                bak_files.append(str(p))

    by_parent: dict[str | None, list] = defaultdict(list)
    path_mismatch = []
    missing = []
    type_mismatch = []
    key_set = {a["key"] for a in atts}
    for a in atts:
        if (a["ctype"] or "").lower().find("word") >= 0 or path_filename(a["path"]).lower().endswith(".docx"):
            by_parent[a["parent_id"]].append(a)
        folder = storage / a["key"]
        main = pick_main(folder, a["ctype"])
        want_name = path_filename(a["path"])
        if main is None:
            missing.append({"key": a["key"], "path": a["path"], "ctype": a["ctype"]})
            continue
        if want_name and main.name != want_name:
            path_mismatch.append({"key": a["key"], "path": a["path"], "actual": main.name})
        ext = main.suffix.lower()
        ctype = (a["ctype"] or "").lower()
        if "pdf" in ctype and ext != ".pdf":
            type_mismatch.append({"key": a["key"], "ctype": a["ctype"], "file": main.name})
        if ("word" in ctype or "docx" in ctype) and ext != ".docx":
            type_mismatch.append({"key": a["key"], "ctype": a["ctype"], "file": main.name})

    multi = {k: v for k, v in by_parent.items() if len(v) > 1}
    orphan_disk = []
    for folder in storage.iterdir():
        if folder.is_dir() and folder.name not in key_set:
            for p in folder.iterdir():
                if p.suffix.lower() in {".pdf", ".docx"} and not is_bak(p.name):
                    orphan_disk.append(str(p))

    report = {
        "mixed_folders": mixed,
        "multi_docx_parents": {str(k): len(v) for k, v in multi.items()},
        "multi_docx_extra": sum(len(v) - 1 for v in multi.values()),
        "path_mismatch": path_mismatch,
        "missing_file": missing,
        "type_mismatch": type_mismatch,
        "bak_files": bak_files,
        "orphan_disk": orphan_disk,
        "ok": not (mixed or multi or path_mismatch or missing or type_mismatch or bak_files or orphan_disk),
    }
    write_report(work, "check", report)
    print(
        f"mixed={len(mixed)} multi_docx_parents={len(multi)} extra_docx={report['multi_docx_extra']} "
        f"path_mismatch={len(path_mismatch)} missing={len(missing)} type_mismatch={len(type_mismatch)} "
        f"bak={len(bak_files)} orphan={len(orphan_disk)} ok={report['ok']}"
    )
    return 0 if report["ok"] else 1


def cmd_split(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    atts = load_atts(db)
    by_key = {a["key"]: a for a in atts}
    mixed = []
    for folder in storage.iterdir():
        if not folder.is_dir():
            continue
        pdfs = [p for p in folder.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()]
        docxs = [p for p in folder.iterdir() if p.suffix.lower() == ".docx" and p.is_file()]
        if pdfs and docxs:
            mixed.append((folder, pdfs, docxs))
    print("mixed folders", len(mixed))
    if not mixed:
        write_report(work, "split", {"report_n": 0, "mixed_after": 0, "sample": []})
        return 0

    backup_db(db, "split")
    con = open_rw(db)
    cur = con.cursor()
    title_field = cur.execute(
        "SELECT fieldID FROM fields WHERE fieldName='title'"
    ).fetchone()[0]
    report = []
    for folder, pdfs, docxs in mixed:
        key = folder.name
        meta = by_key.get(key)
        parent_id = meta["parent_id"] if meta else None
        for d in docxs:
            dest_key = None
            for a in atts:
                if (
                    a["parent_id"] == parent_id
                    and parent_id is not None
                    and ("word" in (a["ctype"] or "").lower() or path_filename(a["path"]).lower().endswith(".docx"))
                    and a["key"] != key
                ):
                    dest_key = a["key"]
                    break
            if dest_key:
                dest_dir = storage / dest_key
                dest_dir.mkdir(exist_ok=True)
                dest = dest_dir / d.name
                shutil.move(str(d), str(dest))
                report.append({"from": str(d), "to": str(dest), "action": "move-to-docx-att"})
                continue
            ak = new_key()
            while (storage / ak).exists() or ak in by_key:
                ak = new_key()
            dest_dir = storage / ak
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / d.name
            shutil.move(str(d), str(dest))
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "INSERT INTO items (itemTypeID, dateAdded, clientDateModified, libraryID, key, version, synced) "
                "SELECT ?, ?, ?, libraryID, ?, 0, 0 FROM items WHERE key=? LIMIT 1",
                (ATT_TYPEID, now, now, ak, key if meta else ak),
            )
            item_id = cur.lastrowid
            title = re.sub(r"\.docx$", "", d.name, flags=re.I)
            set_title(cur, item_id, title_field, f"[docx]{title}")
            cur.execute(
                "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, charsetID, path, syncState, storageModTime) "
                "VALUES (?,?,1,?,?,?,?,?)",
                (item_id, parent_id, DOCX_CT, None, "storage:" + d.name, "U", int(time.time() * 1000)),
            )
            by_key[ak] = {
                "item_id": item_id,
                "parent_id": parent_id,
                "key": ak,
                "path": "storage:" + d.name,
                "ctype": DOCX_CT,
            }
            report.append(
                {"from": str(folder / d.name), "to": str(dest), "action": "create-docx-att", "key": ak}
            )
    con.commit()
    con.close()

    mixed2 = 0
    for folder in storage.iterdir():
        if not folder.is_dir():
            continue
        files = list(folder.iterdir())
        if any(p.suffix.lower() == ".pdf" for p in files) and any(
            p.suffix.lower() == ".docx" for p in files
        ):
            mixed2 += 1
    print("moved/created", len(report), "mixed remaining", mixed2)
    write_report(work, "split", {"report_n": len(report), "mixed_after": mixed2, "sample": report[:30]})
    return 0


def cmd_dedup_hash(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    quar = quar_dir(work, "quarantine_dup_docx")
    all_docx = [p for p in storage.rglob("*.docx") if not is_bak(p.name)]
    print("docx non-bak", len(all_docx))
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for p in all_docx:
        by_hash[md5_file(p)].append(p)
    moved = []
    for h, paths in by_hash.items():
        if len(paths) <= 1:
            continue
        paths_sorted = sorted(
            paths,
            key=lambda x: (0 if x.name != "translation.docx" else 1, -len(x.name), x.parent.name),
        )
        keep = paths_sorted[0]
        for p in paths_sorted[1:]:
            dest = move_to_quar(p, quar)
            moved.append({"from": str(p), "to": str(dest), "hash": h, "keep": str(keep)})
    print("hash dups quarantined", len(moved))
    write_report(work, "dedup-hash", {"moved": len(moved), "sample": moved[:20]})
    return 0


def cmd_dedup_parent(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    quar = quar_dir(work, "quarantine_dup_docx")
    atts = load_atts(db)
    docx_atts = [
        a
        for a in atts
        if "word" in (a["ctype"] or "").lower()
        or path_filename(a["path"]).lower().endswith(".docx")
    ]
    print("docx attachments in db", len(docx_atts))
    by_parent: dict = defaultdict(list)
    for a in docx_atts:
        by_parent[a["parent_id"] or a["item_id"]].append(a)
    multi = {k: v for k, v in by_parent.items() if len(v) > 1}
    print("parents with >1 docx", len(multi), "extra", sum(len(v) - 1 for v in multi.values()))
    if not multi:
        write_report(work, "dedup-parent", {"removed": 0, "kept": 0})
        return 0

    backup_db(db, "dedup_parent")
    con = open_rw(db)
    cur = con.cursor()
    removed = 0
    kept = 0
    detail = []
    for parent_id, lst in multi.items():
        scored = []
        for a in lst:
            folder = storage / a["key"]
            files = visible_files(folder)
            docs = [p for p in files if p.suffix.lower() == ".docx"] or files
            if not docs:
                continue
            f = max(docs, key=lambda x: x.stat().st_size)
            scored.append((cjk_count(f), f.stat().st_mtime, f, a))
        if not scored:
            continue
        scored.sort(key=lambda t: (-t[0], -t[1]))
        keep = scored[0]
        kept += 1
        for _, _, f, a in scored[1:]:
            dest = move_to_quar(f, quar)
            # remove empty storage folder leftovers
            folder = storage / a["key"]
            for leftover in visible_files(folder):
                move_to_quar(leftover, quar)
            delete_attachment(cur, a["item_id"])
            removed += 1
            detail.append(
                {
                    "parent_id": parent_id,
                    "removed_key": a["key"],
                    "kept_key": keep[3]["key"],
                    "quarantined": str(dest),
                }
            )
    con.commit()
    con.close()
    print("kept parents", kept, "removed attachments", removed)
    write_report(work, "dedup-parent", {"removed": removed, "kept": kept, "detail": detail[:40]})
    return 0


def cmd_clean_bak(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    quar = quar_dir(work, "quarantine_docx_bak")
    moved = []
    for p in storage.rglob("*"):
        if p.is_file() and is_bak(p.name):
            dest = move_to_quar(p, quar)
            moved.append({"from": str(p), "to": str(dest)})
    print("bak moved", len(moved))
    write_report(work, "clean-bak", {"moved": len(moved), "sample": moved[:20]})
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    quar = quar_dir(work, "quarantine_orphan_docx")
    atts = load_atts(db)
    backup_db(db, "align")
    con = open_rw(db)
    cur = con.cursor()
    report = {
        "fixed_path": 0,
        "missing_file": [],
        "orphan_disk": [],
        "recovered": 0,
        "type_mismatch": [],
    }
    for a in atts:
        folder = storage / a["key"]
        main = pick_main(folder, a["ctype"])
        if main is None:
            report["missing_file"].append(
                {"key": a["key"], "path": a["path"], "ctype": a["ctype"]}
            )
            continue
        want = "storage:" + main.name
        if a["path"] != want:
            cur.execute(
                "UPDATE itemAttachments SET path=? WHERE itemID=?", (want, a["item_id"])
            )
            report["fixed_path"] += 1
    con.commit()

    keys = {a["key"] for a in atts}
    for folder in storage.iterdir():
        if not folder.is_dir() or folder.name in keys:
            continue
        for f in folder.iterdir():
            if f.suffix.lower() in {".pdf", ".docx"} and not is_bak(f.name):
                dest = move_to_quar(f, quar)
                report["orphan_disk"].append(str(f))
                report["recovered"] += 1
    con.close()
    print(
        "fixed_path",
        report["fixed_path"],
        "missing_file",
        len(report["missing_file"]),
        "orphan_moved",
        report["recovered"],
    )
    write_report(work, "align", report)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    data, db, storage, work = resolve_paths(args)
    align_path = work / "align_result.json"
    if not align_path.exists():
        print("align_result.json not found; run align first")
        return 1
    res = json.loads(align_path.read_text(encoding="utf-8"))
    missing = res.get("missing_file") or res.get("missing") or []
    print("missing", len(missing))
    index: dict[str, list[Path]] = {}
    for q in work.glob("quarantine*"):
        for p in q.rglob("*"):
            if p.is_file():
                index.setdefault(p.name, []).append(p)

    backup_db(db, "restore")
    con = open_rw(db)
    cur = con.cursor()
    restored = 0
    still = []
    for m in missing:
        key = m["key"]
        fname = path_filename(m.get("path") or "")
        if not fname:
            still.append(m)
            continue
        folder = storage / key
        folder.mkdir(exist_ok=True)
        target = folder / fname
        cands = index.get(fname) or []
        cands_sorted = sorted(
            cands, key=lambda p: (0 if key in str(p) else 1, -p.stat().st_size)
        )
        if cands_sorted:
            shutil.copy2(cands_sorted[0], target)
            want = "storage:" + fname
            row = cur.execute("SELECT itemID FROM items WHERE key=?", (key,)).fetchone()
            if row:
                cur.execute(
                    "UPDATE itemAttachments SET path=? WHERE itemID=?",
                    (want, row[0]),
                )
            restored += 1
        else:
            still.append(m)
    con.commit()
    con.close()
    print("restored", restored, "still_missing", len(still))
    write_report(
        work,
        "restore",
        {"restored": restored, "still_missing": still},
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    rc = cmd_check(args)
    for step in (cmd_split, cmd_dedup_hash, cmd_dedup_parent, cmd_clean_bak, cmd_align):
        step(args)
    final = cmd_check(args)
    print("doctor done; final check rc", final, "(restore is manual — inspect align_result.json)")
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step",
        choices=[
            "check",
            "split",
            "dedup-hash",
            "dedup-parent",
            "clean-bak",
            "align",
            "restore",
            "doctor",
        ],
    )
    parser.add_argument("--data-dir", default=os.environ.get("ZOTERO_DATA_DIR", ""))
    parser.add_argument("--sqlite", default=os.environ.get("ZOTERO_SQLITE", ""))
    parser.add_argument("--storage", default=os.environ.get("ZOTERO_STORAGE", ""))
    parser.add_argument("--work", default=os.environ.get("ZOTERO_WORK_BASE", ""))
    args = parser.parse_args(argv)
    if not args.data_dir and not (args.sqlite and args.storage):
        if not os.environ.get("ZOTERO_DATA_DIR"):
            print("warn: ZOTERO_DATA_DIR not set; pass --data-dir or --sqlite/--storage")
    handlers = {
        "check": cmd_check,
        "split": cmd_split,
        "dedup-hash": cmd_dedup_hash,
        "dedup-parent": cmd_dedup_parent,
        "clean-bak": cmd_clean_bak,
        "align": cmd_align,
        "restore": cmd_restore,
        "doctor": cmd_doctor,
    }
    return handlers[args.step](args)


if __name__ == "__main__":
    sys.exit(main())
