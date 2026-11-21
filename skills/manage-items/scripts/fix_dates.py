# -*- coding: utf-8 -*-
"""补全条目日期：优先用 DOI 查 OpenAlex 的 publication_date，
无 DOI 或查不到时回退到解析 PDF 首页的「出版/录用/期号」信息。

规则：
- 只处理不完整的日期（仅年份 / 年-月 / 空）
- 新年份必须与已有年份一致，否则跳过（防错配）
- 写入 Zotero 的多段格式：`YYYY-MM-DD YYYY-MM-DD`

用法:
    python fix_dates.py [--apply] [--no-pdf] [--limit N]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from config import ensure_utf8_stdio
from zoterodb import DB, connect, backup

ensure_utf8_stdio()

MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}
MON = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
PAT_PUB = re.compile(r"(?:Published|Publication Date|Date of Publication|Published Online)[:\s]*"
                     r"(\d{1,2})?\s*" + MON + r"?[,\s]*(\d{4})", re.I)
PAT_ACC = re.compile(r"(?:Accepted|Revised)[:\s]*(\d{1,2})\s*" + MON + r"\s*(\d{4})", re.I)
PAT_ISSUE = re.compile(MON + r"\s+(\d{4})")


def want_date(day, mon, year):
    y = int(year)
    m = MONTHS.get((mon or "").title(), 0)
    d = int(day) if day and day.isdigit() and 1 <= int(day) <= 31 else 0
    if not m:
        return "%04d-00-00 %04d-00" % (y, y)
    if not d:
        return "%04d-%02d-00 %04d-%02d" % (y, m, y, m)
    return "%04d-%02d-%02d %04d-%02d-%02d" % (y, m, d, y, m, d)


def from_pdf(path):
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            return None
    try:
        doc = pymupdf.open(path)
        txt = "\n".join(doc[i].get_text() for i in range(min(2, len(doc))))
    except Exception:
        return None
    m = PAT_PUB.search(txt)
    if m:
        g = m.groups()  # (day, month, year)
        return want_date(g[0], g[1], g[2]), "pdf:published"
    m = PAT_ACC.search(txt)
    if m:
        return want_date(m.group(1), m.group(2), m.group(3)), "pdf:accepted"
    m = PAT_ISSUE.search(txt)
    if m:
        return want_date(None, m.group(1), m.group(2)), "pdf:issue"
    return None


def openalex(dois):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    op.addheaders = [("User-Agent", "zotero-date-fix/1.0")]
    out = {}
    for i in range(0, len(dois), 40):
        flt = "doi:" + "|".join(dois[i:i + 40])
        url = ("https://api.openalex.org/works?filter=" + urllib.parse.quote(flt, safe=":|/.-_") +
               "&per-page=50&select=doi,publication_date")
        for _ in range(2):
            try:
                with op.open(url, timeout=45) as r:
                    d = json.loads(r.read().decode())
                for w in d.get("results", []):
                    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
                    if w.get("publication_date"):
                        out[doi] = w["publication_date"]
                break
            except Exception:
                time.sleep(2)
        time.sleep(0.2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = connect(readonly=not args.apply)
    db = DB(con)
    todo = []
    for iid in db.items():
        d = (db.get(iid, "date") or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.split(" ")[0]):
            continue
        todo.append(iid)
    if args.limit:
        todo = todo[:args.limit]
    print("日期不完整的条目:", len(todo))

    dois = [(iid, (db.get(iid, "doi") or "").strip().lower()) for iid in todo]
    oa = openalex([d for _, d in dois if d])
    print("OpenAlex 命中:", len(oa))

    changes, skipped = [], []
    for iid in todo:
        old = (db.get(iid, "date") or "").strip()
        old_year = old[:4] if old[:4].isdigit() else None
        doi = (db.get(iid, "doi") or "").strip().lower()
        new = oa.get(doi)
        src = "openalex"
        if new:
            parts = (new or "").split("-")
            y = parts[0]
            m = parts[1] if len(parts) > 1 and parts[1] != "00" else "00"
            d = parts[2] if len(parts) > 2 and parts[2] != "00" else "00"
            if m == "00":
                new_fmt = "%s-00-00 %s-00" % (y, y)
            elif d == "00":
                new_fmt = "%s-%s-00 %s-%s" % (y, m, y, m)
            else:
                new_fmt = "%s-%s-%s %s-%s-%s" % (y, m, d, y, m, d)
        else:
            new_fmt, src = None, None
            if not args.no_pdf:
                for a in db.attachments(iid):
                    if (a[2] or "").lower().endswith(".pdf"):
                        fp = db.file_of(a[0], a[2], a[4])
                        if fp and os.path.exists(fp):
                            r = from_pdf(fp)
                            if r:
                                new_fmt, src = r
                        break
        if not new_fmt:
            skipped.append((iid, "无可靠日期"))
            continue
        new_year = new_fmt[:4]
        if old_year and new_year != old_year:
            skipped.append((iid, "年份冲突 %s→%s" % (old_year, new_year)))
            continue
        changes.append((iid, old, new_fmt, src))

    print("可更新: %d ｜ 跳过: %d" % (len(changes), len(skipped)))
    for iid, old, new, src in changes[:8]:
        print("  %-6d %-22s -> %-22s [%s]" % (iid, old or "空", new, src))
    for iid, why in skipped[:5]:
        print("  跳过 %-6d %s" % (iid, why))

    if not args.apply:
        print("[dry-run] 未写入；加 --apply 生效")
        con.close()
        return 0

    if changes:
        print("备份:", backup(tag="dates"))
        for iid, _, new, _ in changes:
            db.set(iid, "date", new)
        con.commit()
        print("已写入 %d ｜ integrity: %s" %
              (len(changes), con.execute("PRAGMA integrity_check").fetchone()[0]))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
