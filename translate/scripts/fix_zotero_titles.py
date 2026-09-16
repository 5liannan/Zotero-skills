# -*- coding: utf-8 -*-
"""Add title field to Zotero DOCX attachments that lack it."""
import os, sys, sqlite3, shutil, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate_config import cfg, ensure_utf8_stdio

ensure_utf8_stdio()
DB = str(cfg.sqlite_path)
BACKUP = os.path.join(str(cfg.zotero_data_dir), "zotero.sqlite.bak_before_titles_%s" % time.strftime("%Y%m%d_%H%M%S"))

def main():
    # lock check
    try:
        con = sqlite3.connect(DB)
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        con.close()
    except Exception as e:
        print("DB locked:", e)
        print("Please fully quit Zotero.")
        return 2

    print("backup ->", BACKUP)
    shutil.copy2(DB, BACKUP)

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")

    cur.execute("SELECT fieldID FROM fields WHERE fieldName='title'")
    title_fid = cur.fetchone()[0]

    # attachments missing title
    cur.execute("""
        SELECT ia.itemID, ia.path
        FROM itemAttachments ia
        WHERE ia.itemID NOT IN (
            SELECT itemID FROM itemData WHERE fieldID=?
        )
        AND ia.path LIKE 'storage:%'
    """, (title_fid,))
    rows = cur.fetchall()
    print("attachments missing title:", len(rows))

    # max valueID
    cur.execute("SELECT MAX(valueID) FROM itemDataValues")
    next_vid = (cur.fetchone()[0] or 0) + 1

    n = 0
    for iid, path in rows:
        fn = path[len("storage:"):]
        title = os.path.splitext(fn)[0]
        # reuse existing value if present
        cur.execute("SELECT valueID FROM itemDataValues WHERE value=?", (title,))
        r = cur.fetchone()
        if r:
            vid = r[0]
        else:
            vid = next_vid
            next_vid += 1
            cur.execute("INSERT INTO itemDataValues (valueID, value) VALUES (?,?)", (vid, title))
        cur.execute(
            "INSERT OR IGNORE INTO itemData (itemID, fieldID, valueID) VALUES (?,?,?)",
            (iid, title_fid, vid),
        )
        n += 1

    con.commit()
    con.close()
    print("titles added:", n)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
