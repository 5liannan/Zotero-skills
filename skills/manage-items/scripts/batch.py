# -*- coding: utf-8 -*-
"""分批翻译调度：挑下一批待译条目、记录进度。

用法:
    python batch.py --status                # 看总进度
    python batch.py --next 3                # 取下一批（打印 PDF 路径，不翻译）
    python batch.py --next 3 --extract      # 并调用 ② 的 extract 抽取正文
    python batch.py --done 10642 --docx <path>   # 记为已挂载（需 Zotero 已退出）

台账: outputs/ledger.csv（itemID, 标题, 年份, 状态, docx, 更新时间）
状态: todo 待译 / extracted 已抽取 / translated 已译 / attached 已挂载
"""
import argparse
import csv
import os
import sqlite3
import subprocess
import sys

from config import cfg, ensure_utf8_stdio
from zoterodb import DB, connect

ensure_utf8_stdio()
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "outputs")
LEDGER = os.path.join(OUT, "ledger.csv")
WORK = os.environ.get("ZOTERO_TRANSLATE_WORK", os.path.join(HERE, "work"))
EXTRACT = os.path.join(HERE, "..", "translate-import", "scripts", "extract_pdf_text.py")


def load_ledger():
    if not os.path.exists(LEDGER):
        return {}
    return {r["itemID"]: r for r in csv.DictReader(open(LEDGER, encoding="utf-8-sig"))}


def save_ledger(rows):
    os.makedirs(OUT, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["itemID", "标题", "年份", "状态", "docx", "更新时间"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})


def scan():
    con = connect(readonly=True)
    db = DB(con)
    out = []
    for iid in db.items():
        kinds = []
        pdf = None
        for aid, link, path, ctype, akey in db.attachments(iid):
            p = (path or "").lower()
            if p.endswith(".pdf"):
                kinds.append("pdf")
                pdf = pdf or db.file_of(aid, path, akey)
            elif p.endswith((".docx", ".doc")):
                kinds.append("docx")
        if "pdf" in kinds and "docx" not in kinds and pdf and os.path.exists(pdf):
            # 跳过中文原版：PDF 文件名含中文且「其他」里没有英文原名 → 本身就是中文文献
            name = os.path.basename(pdf)
            extra = db.get(iid, "extra") or ""
            if any("\u4e00" <= ch <= "\u9fa5" for ch in name) and "Original Title:" not in extra:
                continue
            out.append({"itemID": str(iid), "标题": db.title(iid), "年份": db.year_of(iid) or "", "pdf": pdf})
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--next", type=int, default=0)
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--done", type=str)
    ap.add_argument("--docx", type=str)
    args = ap.parse_args()

    rows = load_ledger()
    cand = scan()
    pending = [c for c in cand if rows.get(c["itemID"], {}).get("状态") not in ("attached", "translated")]

    if args.done:
        iid = args.done
        cur = rows.get(iid, {"itemID": iid})
        cur.update({"状态": "attached", "docx": args.docx or cur.get("docx", ""),
                    "更新时间": __import__("time").strftime("%Y-%m-%d %H:%M")})
        info = next((c for c in cand if c["itemID"] == iid), None)
        if info:
            cur.setdefault("标题", info["标题"])
            cur.setdefault("年份", info["年份"])
        rows[iid] = cur
        save_ledger(rows.values())
        print("已记录:", iid, args.docx)
        return 0

    if args.status:
        done = sum(1 for r in rows.values() if r.get("状态") == "attached")
        print("库内缺译文:", len(cand), "｜ 台账已挂载:", done, "｜ 剩余:", len(pending))
        return 0

    if args.next:
        batch = pending[:args.next]
        os.makedirs(WORK, exist_ok=True)
        for c in batch:
            print("%-6s %-4s %s" % (c["itemID"], c["年份"], c["标题"]))
            print("       %s" % c["pdf"])
            if args.extract:
                wd = os.path.join(WORK, c["itemID"])
                os.makedirs(os.path.join(wd, "images"), exist_ok=True)
                r = subprocess.run([sys.executable, EXTRACT, c["pdf"], os.path.join(wd, "images")],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                open(os.path.join(wd, "extract.json"), "w", encoding="utf-8").write(r.stdout or "")
                print("       extract ->", os.path.join(wd, "extract.json"), r.stderr.strip()[:60])
            rows.setdefault(c["itemID"], {"itemID": c["itemID"], "标题": c["标题"], "年份": c["年份"],
                                          "状态": "extracted" if args.extract else "todo", "docx": "",
                                          "更新时间": __import__("time").strftime("%Y-%m-%d %H:%M")})
        save_ledger(rows.values())
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
