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
from zoterodb import DB, connect, backup, render, strip_tags, CJK

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
    ap.add_argument("--titles-only", action="store_true", help="只统一标题栏，不动磁盘文件名")
    args = ap.parse_args()

    con = connect(readonly=not args.apply)
    db = DB(con)
    ids = db.items()
    if args.limit:
        ids = ids[:args.limit]

    # 每个目录里"其他附件登记引用的文件"（忽略 .zotero-ft-cache 等伴随文件）
    refs_by_dir = {}
    for path_v, akey2 in con.execute(
            "SELECT a.path, i.key FROM itemAttachments a JOIN items i ON i.itemID=a.itemID "
            "WHERE a.linkMode=0 AND a.path LIKE 'storage:%'"):
        d2 = os.path.normpath(os.path.join(cfg["storage_dir"], akey2))
        refs_by_dir.setdefault(d2, set()).add(path_v[len("storage:"):])

    acts, problems = [], []
    used_files = {}  # (parentItemID, kind) -> set(已占用目标文件名, 小写)
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
            prefix = cfg["pdf_title_prefix"] if kind == "pdf" else cfg["docx_title_prefix"]
            cur_raw = (db.get(aid, "title") or "").strip()
            for pfx in (cfg["pdf_title_prefix"], cfg["docx_title_prefix"]):
                if cur_raw.startswith(pfx):
                    cur_raw = cur_raw[len(pfx):].strip()
            cur_raw = strip_tags(cur_raw)
            # 占位标题（"PDF"/"Full Text" 之类）视为空
            if len(cur_raw) < 5 or cur_raw.lower() in ("pdf", "full text", "document", "untitled", "全文"):
                cur_raw = ""
            stem = strip_tags(os.path.splitext(os.path.basename((path or "").replace("storage:", "")))[0])
            zh_s, en_s = strip_tags(zh), strip_tags(en or "")
            # PDF 优先英文原名；没有则沿用现有标题，再不济用原文件名（不臆造）
            # DOCX：条目中文标题 → 现有附件标题（若为中文，避免英文标题条目的
            #       中文译文标题被回退成英文）→ 英文原名 → 原文件名
            # 条目标题中的【分类标签】不进入附件标题与文件名（strip_tags）
            title_src = (en_s or cur_raw or stem) if kind == "pdf" else \
                (zh_s if CJK.search(zh_s or "") else
                 (cur_raw if CJK.search(cur_raw or "") else (en_s or stem)))
            if not title_src:
                problems.append((aid, iid, "缺标题来源"))
                continue
            # 去掉标题来源里内嵌的「作者 - 年 - 」前缀，避免文件名出现重复前缀
            _m = re.match(r"^(?P<who>.{1,60}?)\s+-\s+(?P<yr>(19|20)\d{2})\s+-\s+(?P<rest>.+)$", title_src or "")
            if _m and author and author in _m.group("who") and (not year or _m.group("yr") == year):
                title_src = _m.group("rest").strip()
            want_title = prefix + title_src
            pattern = cfg["pdf_filename"] if kind == "pdf" else cfg["docx_filename"]
            want_file = render(pattern, author, year, en_s or title_src, zh_s if CJK.search(zh_s or "") else title_src)
            # 同条目同类附件目标重名消歧：第 2+ 个改用原文件名 stem，仍重复则追加 (N)
            used = used_files.setdefault((iid, kind), set())
            if want_file.lower() in used:
                stem_c = stem
                for _ in range(5):
                    _m2 = re.match(r"^(?P<who>.{1,60}?)\s+-\s+(?P<yr>(19|20)\d{2})\s+-\s+(?P<rest>.+)$", stem_c)
                    if not (_m2 and author and author in _m2.group("who")
                            and (not year or _m2.group("yr") == year)):
                        break
                    stem_c = _m2.group("rest").strip()
                alt = render(pattern, author, year, title_src, stem_c)
                if alt.lower() in used:
                    _base, _ext = os.path.splitext(want_file)
                    _k = 2
                    while ("%s (%d)%s" % (_base, _k, _ext)).lower() in used:
                        _k += 1
                    alt = "%s (%d)%s" % (_base, _k, _ext)
                want_file = alt
            used.add(want_file.lower())
            cur_file = os.path.basename(db.file_of(aid, path, akey) or "")
            cur_title = db.get(aid, "title")
            if args.titles_only:
                if cur_title == want_title:
                    continue
            elif cur_title == want_title and cur_file == want_file:
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
        if args.titles_only:
            db.set(aid, "title", want_title)
            done += 1
            continue
        src_dir = os.path.join(cfg["storage_dir"], akey)
        src = os.path.join(src_dir, cur_file) if cur_file else None
        try:
            if src and os.path.exists(src):
                # 若目录里还有其他附件登记的文件，先拆到独立目录
                # （.zotero-ft-cache / jasminum-outline.json 等伴随文件不算）
                if len([f for f in refs_by_dir.get(os.path.normpath(src_dir), set())
                        if f != cur_file]) > 0:
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
