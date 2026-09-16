# -*- coding: utf-8 -*-
"""Batch-register translated DOCX files as Zotero attachments.

Requires: Zotero fully quit; zotero.sqlite writable.
Backs up DB first. For each status-ok DOCX not already registered,
finds parent item via sibling PDF in same storage folder (or task mapping),
creates a new attachment item + storage/<key>/ copy, inserts DB rows.
"""
import json, os, sys, sqlite3, shutil, random, string, time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

ZC = r"C:\Users\Administrator\Zotero"
STORAGE = os.path.join(ZC, "storage")
DB = os.path.join(ZC, "zotero.sqlite")
STATUS = r"C:\Users\Administrator\.openclaw-autoclaw\workspace\zcode-continuation\status_oc.json"
TASKS = os.path.join(ZC, "zotero_tasks.json")
BACKUP = os.path.join(ZC, "zotero.sqlite.bak_before_docx_attach_%s" % time.strftime("%Y%m%d_%H%M%S"))
DOCX_CTYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ATT_TYPEID = 3

# Zotero key alphabet (no vowels I,O etc. typical)
KEY_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

def new_key(n=8):
    return "".join(random.choice(KEY_CHARS) for _ in range(n))

def now_zotero():
    # Zotero dates like 2026-09-16 12:00:00
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def main():
    if not os.path.exists(DB):
        print("DB not found", DB)
        return 1
    # fail if locked for write
    try:
        con = sqlite3.connect(DB)
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
    except Exception as e:
        print("DB still locked:", e)
        print("Please fully quit Zotero and retry.")
        return 2
    finally:
        try:
            con.close()
        except Exception:
            pass

    print("Backing up DB ->", BACKUP)
    shutil.copy2(DB, BACKUP)

    status = json.load(open(STATUS, encoding="utf-8"))
    tasks = json.load(open(TASKS, encoding="utf-8"))

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")

    # index items: key -> itemID, itemID -> key
    cur.execute("SELECT itemID, key FROM items")
    id2key = {}
    key2id = {}
    for iid, key in cur.fetchall():
        id2key[iid] = key
        key2id[key] = iid

    cur.execute("SELECT MAX(itemID) FROM items")
    next_item = (cur.fetchone()[0] or 0) + 1

    # existing imported attachments: (storage_folder_key, filename) -> True
    cur.execute("SELECT itemID, path, linkMode FROM itemAttachments")
    existing = set()
    parent_of_storage_folder = {}  # pdf storage key -> parent itemID
    for iid, path, linkMode in cur.fetchall():
        if not path or not path.startswith("storage:"):
            continue
        fn = path[len("storage:"):]
        fk = id2key.get(iid, "")
        existing.add((fk, fn))

    # map storage folder of each PDF to parent item
    # walk storage for pdfs and find their attachment item
    pdf_folder_to_parent = {}
    for folder in os.listdir(STORAGE):
        fpath = os.path.join(STORAGE, folder)
        if not os.path.isdir(fpath):
            continue
        for fn in os.listdir(fpath):
            if fn.lower().endswith(".pdf"):
                if (folder, fn) in existing:
                    # find att item with this key+fn - already have via existing set
                    # need parent: query
                    pass

    # rebuild properly
    cur.execute("SELECT itemID, parentItemID, path FROM itemAttachments WHERE path LIKE 'storage:%'")
    storage_att = []
    for iid, parent, path in cur.fetchall():
        fn = path[len("storage:"):]
        fk = id2key.get(iid, "")
        storage_att.append((fk, fn, iid, parent))

    pdf_rel_to_parent = {}
    for fk, fn, iid, parent in storage_att:
        if fn.lower().endswith(".pdf") and parent:
            pdf_rel_to_parent[(fk, fn)] = parent

    # also from tasks: pdf path -> itemID
    task_pdf_to_item = {}
    for t in tasks:
        p = t.get("pdf", "")
        if p:
            task_pdf_to_item[os.path.normcase(p)] = t["itemID"]

    registered = 0
    skipped = 0
    failed = []
    moved = 0

    for k, v in sorted(status.items(), key=lambda x: int(x[0])):
        if not isinstance(v, dict) or v.get("status") != "ok":
            continue
        docx = v.get("docx", "")
        if not docx or not os.path.exists(docx) or os.path.getsize(docx) < 2000:
            skipped += 1
            continue
        folder = os.path.basename(os.path.dirname(docx))
        fn = os.path.basename(docx)
        if (folder, fn) in existing:
            skipped += 1
            continue

        # find parent item
        parent = None
        # 1) same storage folder has a pdf with parent
        fdir = os.path.dirname(docx)
        for f in os.listdir(fdir):
            if f.lower().endswith(".pdf"):
                parent = pdf_rel_to_parent.get((folder, f))
                if parent:
                    break
        # 2) task itemID
        if not parent:
            iid_task = int(k)
            # find pdf from tasks
            for t in tasks:
                if t["itemID"] == iid_task:
                    pp = os.path.normcase(t.get("pdf", ""))
                    parent = task_pdf_to_item.get(pp)
                    # or use itemID if it exists in items
                    if not parent and iid_task in id2key:
                        parent = iid_task
                    break
        if not parent:
            failed.append((docx, "no_parent"))
            continue

        # create attachment
        att_id = next_item
        next_item += 1
        att_key = new_key()
        while att_key in key2id:
            att_key = new_key()
        key2id[att_key] = att_id
        id2key[att_id] = att_key

        dest_dir = os.path.join(STORAGE, att_key)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, fn)
        try:
            shutil.copy2(docx, dest)
            moved += 1
        except Exception as e:
            failed.append((docx, "copy:%s" % e))
            continue

        ts = now_zotero()
        try:
            cur.execute(
                "INSERT INTO items (itemID, itemTypeID, dateAdded, dateModified, clientDateModified, libraryID, key, version, synced) "
                "VALUES (?,?,?,?,?,?,?,?,0)",
                (att_id, ATT_TYPEID, ts, ts, ts, 1, att_key, 0),
            )
            cur.execute(
                "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, charsetID, path, syncState, storageModTime, storageHash, lastProcessedModificationTime, lastRead) "
                "VALUES (?,?,0,?,NULL,?,0,NULL,NULL,NULL,NULL)",
                (att_id, parent, DOCX_CTYPE, "storage:" + fn),
            )
            existing.add((att_key, fn))
            registered += 1
        except Exception as e:
            failed.append((docx, "db:%s" % e))
            # cleanup empty?
            continue

    con.commit()
    con.close()
    print("registered", registered)
    print("skipped (already ok/cn/missing)", skipped)
    print("copied files", moved)
    print("failed", len(failed))
    for f in failed[:20]:
        print(" ", f)
    print("backup:", BACKUP)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
