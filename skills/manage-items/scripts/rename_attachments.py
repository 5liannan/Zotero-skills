# -*- coding: utf-8 -*-
"""按规范重命名附件（标题栏 + 文件名），并保证一附件一目录。

规范（见 SKILL.md）：
    PDF  标题栏 = [pdf]<英文标题>     文件名 = <作者>等 - <年> - <英文标题>.pdf
    DOCX 标题栏 = [docx]<中文标题>    文件名 = <作者>等 - <年> - <中文标题>.docx
英文标题优先取条目「其他」字段的 `Original Title:` 行，其次取当前标题（若为英文）；
中文标题取当前标题（若为中文）。

用法:
    python rename_attachments.py [--apply] [--only pdf|docx] [--limit N]
"""
import argparse
import os
import re
import sys

from config import cfg, ensure_utf8_stdio
from zoterodb import DB, connect, backup, render, CJK

ensure_utf8_stdio()
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def kind_of(path, ctype):
    p = (path or "").lower()
    if p.endswith(".pdf") or (ctype or "").startswith("application/pdf"):
        return "pdf"
    if p.endswith(".docx") or ctype == DOCX_CT:
        return "docx"
    return "other"


def original_title(db, iid):
    extra = db.get(iid, "extra") or ""
    m = re.search(r"Original Title:\s*(.+)", extra)
    if m:
        return m.group(1).strip()
    t = db.title(iid)
    return t if t and not CJK.search(t) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", choices=["pdf", "docx"], default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = connect(readonly=not args.apply)
    db = DB(con)
    ids = db.items()
    if args.limit:
        ids = ids[:args.limit]

    acts, problems = [], []
    for iid in ids:
        zh = db.title(iid)
        en = original_title(db, iid)
        author = db.first_author_surname(iid)
        year = db.year_of(iid)
        for aid, link, path, ctype, akey in db.attachments(iid):
            kind = kind_of(path, ctype)
            if kind not in ("pdf", "docx"):
                continue
            if args.only and kind != args.only:
                continue
            if link != 0:
                problems.append((aid, iid, "非导入型附件(linkMode=%s)" % link))
                continue
            title_src = en if kind == "pdf" else (zh if CJK.search(zh or "") else en)
            if not title_src:
                problems.append((aid, iid, "缺标题来源"))
                continue
            prefix = cfg["pdf_title_prefix"] if kind == "pdf" else cfg["docx_title_prefix"]
            want_title = prefix + title_src
            pattern = cfg["pdf_filename"] if kind == "pdf" else cfg["docx_filename"]
            want_file = render(pattern, author, year, en or title_src, zh if CJK.search(zh or "") else title_src)
            cur_file = os.path.basename(db.file_of(aid, path, akey) or "")
            cur_title = db.get(aid, "title")
            if cur_title == want_title and cur_file == want_file:
                continue
            acts.append((aid, iid, kind, cur_title, want_title, cur_file, want_file, path, akey))

    print("需要改名: %d ｜ 跳过(非导入型/缺标题): %d" % (len(acts), len(problems)))
    for a in acts[:8]:
        print("  [%s] %s\n       -> %s\n       %s -> %s" % (a[2], (a[3] or "")[:56], a[4][:56], a[5][:46], a[6][:46]))

    if not args.apply:
        print("[dry-run] 未写入；加 --apply 生效")
        con.close()
        return 0
    if not acts:
        con.close()
        return 0

    print("备份:", backup(tag="rename"))
    done = fail = 0
    for aid, iid, kind, _, want_title, cur_file, want_file, path, akey in acts:
        src_dir = os.path.join(cfg["storage_dir"], akey)
        src = os.path.join(src_dir, cur_file) if cur_file else None
        try:
            if src and os.path.exists(src):
                # 若目录里还有其他文件，先拆到独立目录
                if len([f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f))]) > 1:
                    new_src, st = db.move_attachment_to_own_dir(aid, want_file)
                    if not new_src:
                        raise RuntimeError(st)
                else:
                    dst = os.path.join(src_dir, want_file)
                    if src != dst:
                        os.replace(src, dst)
                    db.cur.execute("UPDATE itemAttachments SET path=? WHERE itemID=?",
                                   ("storage:" + want_file, aid))
            db.set(aid, "title", want_title)
            done += 1
        except Exception as e:
            fail += 1
            print("  失败", aid, e)
    con.commit()
    print("完成 %d ｜ 失败 %d ｜ integrity: %s" %
          (done, fail, con.execute("PRAGMA integrity_check").fetchone()[0]))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
