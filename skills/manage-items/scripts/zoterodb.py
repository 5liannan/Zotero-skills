# -*- coding: utf-8 -*-
"""Zotero 数据库与 storage 的低层读写工具（仅标准库）。

设计约束：
- 字段/类型 ID 一律按名称动态解析，不硬编码，兼容不同 Zotero 版本。
- 写库前必须确认 Zotero 已退出（write 模式会检查 -wal 是否被占用由调用方负责）。
- 一个附件一个 storage 目录：storage/<附件 key>/<文件名>。
"""
import os
import random
import re
import shutil
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone

from config import cfg

KEY_CHARS = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')
CJK = re.compile(r"[\u4e00-\u9fa5]")


def new_key(n=8):
    return "".join(random.choice(KEY_CHARS) for _ in range(n))


def now_zotero():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(readonly=False, db_path=None):
    """只读连接。Zotero 运行时会持有写锁，此时自动降级为「复制副本后读」。"""
    path = db_path or cfg["sqlite_path"]
    if readonly:
        uri = "file:///" + path.replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        try:
            con.execute("SELECT COUNT(*) FROM items").fetchone()
            return con
        except sqlite3.OperationalError:
            con.close()
            import tempfile
            tmpdir = tempfile.mkdtemp(prefix="zotero_ro_")
            dst = os.path.join(tmpdir, "zotero.sqlite")
            shutil.copy2(path, dst)
            for suf in ("-wal", "-shm"):
                if os.path.exists(path + suf):
                    shutil.copy2(path + suf, dst + suf)
            con = sqlite3.connect(dst)
            con.text_factory = lambda b: b.decode("utf-8", "replace")
            return con
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    return con


def backup(db_path=None, tag="manage"):
    path = db_path or cfg["sqlite_path"]
    dst = "%s.bak_before_%s_%s" % (path, tag, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(path, dst)
    return dst


class DB:
    def __init__(self, con):
        self.con = con
        self.cur = con.cursor()
        self.fields = {n: i for i, n in self.cur.execute("SELECT fieldID, fieldName FROM fields")}
        self.types = {n: i for i, n in self.cur.execute("SELECT itemTypeID, typeName FROM itemTypes")}
        r = self.cur.execute("SELECT creatorTypeID FROM creatorTypes WHERE creatorType='author'").fetchone()
        self.author_type = r[0] if r else 1
        cv = self.cur.execute(
            "SELECT clientVersion FROM items WHERE clientVersion IS NOT NULL ORDER BY itemID DESC LIMIT 1").fetchone()
        self.client_version = cv[0] if cv else 8809
        self._keys = {r[0] for r in self.cur.execute("SELECT key FROM items")}

    # ---------- 基础字段 ----------
    def get(self, item_id, field_name):
        fid = self.fields.get(field_name)
        if not fid:
            return ""
        r = self.cur.execute(
            "SELECT v.value FROM itemData d JOIN itemDataValues v USING(valueID) WHERE d.itemID=? AND d.fieldID=?",
            (item_id, fid)).fetchone()
        return (r[0] or "") if r else ""

    def set(self, item_id, field_name, value, touch=True):
        fid = self.fields.get(field_name)
        if not fid:
            raise KeyError("未知字段: %s" % field_name)
        value = (value or "").strip()
        if not value:
            return
        r = self.cur.execute("SELECT valueID FROM itemDataValues WHERE value=?", (value,)).fetchone()
        vid = r[0] if r else None
        if not vid:
            self.cur.execute("INSERT INTO itemDataValues (value,valueNormalized) VALUES (?,?)",
                             (value, unicodedata.normalize("NFKD", value).lower()))
            vid = self.cur.lastrowid
        self.cur.execute("INSERT OR REPLACE INTO itemData (itemID,fieldID,valueID) VALUES (?,?,?)",
                         (item_id, fid, vid))
        if touch:
            self.touch(item_id)

    def touch(self, item_id):
        t = now_zotero()
        self.cur.execute("UPDATE items SET dateModified=?, clientDateModified=?, synced=0 WHERE itemID=?",
                         (t, t, item_id))

    def key_of(self, item_id):
        r = self.cur.execute("SELECT key FROM items WHERE itemID=?", (item_id,)).fetchone()
        return r[0] if r else None

    def new_key(self):
        while True:
            k = new_key()
            if k not in self._keys:
                self._keys.add(k)
                return k

    # ---------- 条目 ----------
    def items(self, types=("journalArticle", "conferencePaper", "thesis", "preprint", "book", "bookSection"),
              include_deleted=False):
        tids = [self.types[t] for t in types if t in self.types]
        if not tids:
            return []
        q = "SELECT itemID FROM items WHERE itemTypeID IN (%s)" % ",".join("?" * len(tids))
        if not include_deleted:
            q += " AND itemID NOT IN (SELECT itemID FROM deletedItems)"
        return [r[0] for r in self.cur.execute(q, tids)]

    def title(self, item_id):
        return self.get(item_id, "title")

    def is_chinese(self, text):
        return bool(CJK.search(text or ""))

    # ---------- 作者 ----------
    def first_author_surname(self, item_id):
        r = self.cur.execute(
            "SELECT c.lastName, c.firstName, c.fieldMode FROM itemCreators ic "
            "JOIN creators c ON c.creatorID=ic.creatorID "
            "WHERE ic.itemID=? AND ic.creatorTypeID=? ORDER BY ic.orderIndex LIMIT 1",
            (item_id, self.author_type)).fetchone()
        if not r:
            return None
        last, first, mode = r
        if mode == 1:
            # 单字段姓名：取最后一段
            parts = (last or "").split()
            return parts[-1] if parts else None
        return (last or "").strip() or None

    def year_of(self, item_id):
        d = self.get(item_id, "date")
        m = re.search(r"(1[89]\d{2}|20\d{2})", d or "")
        return m.group(1) if m else None

    # ---------- 附件 ----------
    def attachments(self, parent_id):
        return self.cur.execute(
            "SELECT a.itemID, a.linkMode, a.path, a.contentType, i.key FROM itemAttachments a "
            "JOIN items i ON i.itemID=a.itemID WHERE a.parentItemID=? ORDER BY a.itemID",
            (parent_id,)).fetchall()

    def attachment_count(self, parent_id):
        return self.cur.execute("SELECT COUNT(*) FROM itemAttachments WHERE parentItemID=?",
                                (parent_id,)).fetchone()[0]

    def file_of(self, att_item_id, path_value, att_key):
        """返回附件的实际磁盘路径；解析 storage: / attachments: / 绝对路径。"""
        p = path_value or ""
        if p.startswith("storage:"):
            return os.path.join(cfg["storage_dir"], att_key, p[len("storage:"):])
        if p.startswith("attachments:"):
            return os.path.join(cfg["storage_dir"], "..", "attachments", p[len("attachments:"):])
        if os.path.isabs(p):
            return p
        return None

    def add_file_attachment(self, parent_id, src_path, filename, content_type=None, title=None):
        """把文件复制进新的 storage 目录并登记为导入型附件。"""
        aid, akey = self._alloc_item(self.types["attachment"])
        folder = os.path.join(cfg["storage_dir"], akey)
        os.makedirs(folder, exist_ok=True)
        dst = os.path.join(folder, filename)
        shutil.copy2(src_path, dst)
        mt = int(os.path.getmtime(dst) * 1000)
        self.set(aid, "title", title or filename, touch=False)
        self.cur.execute(
            "INSERT INTO itemAttachments (itemID,parentItemID,linkMode,contentType,charsetID,path,syncState,"
            "storageModTime,storageHash) VALUES (?,?,0,?,NULL,?,0,?,NULL)",
            (aid, parent_id, content_type, "storage:" + filename, mt))
        self.touch(parent_id)
        return aid, akey, dst

    def _alloc_item(self, type_id):
        iid = (self.cur.execute("SELECT MAX(itemID) FROM items").fetchone()[0] or 0) + 1
        key = self.new_key()
        t = now_zotero()
        self.cur.execute(
            "INSERT INTO items (itemID,itemTypeID,dateAdded,dateModified,clientDateModified,libraryID,key,version,"
            "synced,clientVersion) VALUES (?,?,?,?,?,1,?,0,0,?)",
            (iid, type_id, t, t, t, key, self.client_version))
        return iid, key

    def move_attachment_to_own_dir(self, att_item_id, filename=None):
        """确保附件独占一个 storage 目录；必要时搬迁文件并更新 path。"""
        r = self.cur.execute(
            "SELECT a.path, i.key FROM itemAttachments a JOIN items i ON i.itemID=a.itemID WHERE a.itemID=?",
            (att_item_id,)).fetchone()
        if not r:
            return None, "no_attachment"
        path, key = r
        if not (path or "").startswith("storage:"):
            return None, "not_imported_file"
        old_name = path[len("storage:"):]
        src = os.path.join(cfg["storage_dir"], key, old_name)
        if not os.path.exists(src):
            return None, "file_missing"
        others = [f for f in os.listdir(os.path.join(cfg["storage_dir"], key))
                  if os.path.isfile(os.path.join(cfg["storage_dir"], key, f))]
        if len(others) <= 1 and not filename:
            return src, "already_alone"
        new_name = filename or old_name
        newkey = self.new_key()
        folder = os.path.join(cfg["storage_dir"], newkey)
        os.makedirs(folder, exist_ok=True)
        dst = os.path.join(folder, new_name)
        shutil.move(src, dst)
        self.cur.execute("UPDATE items SET key=? WHERE itemID=?", (newkey, att_item_id))
        self.cur.execute("UPDATE itemAttachments SET path=? WHERE itemID=?",
                         ("storage:" + new_name, att_item_id))
        return dst, "moved"


def safe_filename(name, max_len=None):
    max_len = max_len or cfg["max_filename_len"]
    name = ILLEGAL.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > max_len:
        base, ext = os.path.splitext(name)
        name = base[:max_len - len(ext)].rstrip() + ext
    return name


def render(pattern, author, year, title_en, title_zh, ext=""):
    return safe_filename(pattern.format(
        author=author or cfg["unknown_author"],
        year=year or cfg["unknown_year"],
        title_en=(title_en or "").strip(),
        title_zh=(title_zh or "").strip(),
        ext=ext))
