# -*- coding: utf-8 -*-
"""译文 DOCX 质量审计：判定 Zotero storage 里的译文「过关 / 不过关」，并与附件登记交叉比对。

为什么需要它
------------
Zotero 条目下挂的译文可能是**旧流水线留下的假译文**：模板套话（「本文题为《…》」
「引言部分阐述研究背景与动机」「参考文献保留英文原文…详见原 PDF」「补全图注（对齐原文图号）」）、
同一批图注重复 6–8 遍、公式还是裸 LaTeX。而正确的那份译文可能就躺在同一个目录里没被登记。
本模块负责把这类情况找出来，产出可执行的清单。

判定原则
--------
只看**可复现的客观结构信号**，不依赖主观阅读。硬信号（命中任一即不过关）：

  模板套话    出现旧流水线的固定话术
  段落重复    非空段落（>=12 字）中重复文本占比 > 30%
  裸 LaTeX    残留 `$...$` 或 `\\frac` 之类命令
  高亮残留    仍有 w:highlight
  中文字数过少 正文中文字符 < 2000（含「摘要式短稿」与「中文名却是英文内容」两种）
  中英混排    每段英文功能词 > 4 且中英混排段占比 > 15%（逐词替换式伪翻译）

**不参与判定、只作提示**（可能合法）：
  参考文献有标题但无 `[n]` 条目（作者-年份制本来就无编号）、英文功能词偏多、
  中文字数偏少、无图片。

用法
----
    python scripts/docx_quality.py <audit|plan> [--storage ...] [--sqlite ...] [--out DIR]

`manage_zotero_storage.py quality` 是对本模块的封装。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
TOKEN = re.compile(r"[A-Za-z']+")
BACKSLASH_CMD = re.compile(
    r"\\(?:frac|sqrt|sum|int|alpha|beta|gamma|delta|lambda|sigma|omega|"
    r"times|cdot|le|ge|neq|approx|partial|nabla|infty|left|right|mathrm)\b")
REF_HEAD = re.compile(r"^\s*(参考文献|參考文獻|引用文献|References|REFERENCES)\s*$")
REF_ITEM = re.compile(r"^\s*\[(\d+)\]\s")

# 旧模板流水线的固定话术
TEMPLATE_PAT = [
    "本文题为《", "部分阐述研究背景与动机", "部分给出实现研究目标的技术方案",
    "部分展示主要实验或计算结果", "结论总结本文主要发现",
    "参考文献保留英文原文", "详见原 PDF", "补全图注（对齐原文图号）",
    "补全编号公式（对齐原文式号）", "补全表格",
]

# 英文功能词：真中文译文里只在引文/参考文献出现；逐词替换式伪翻译里满篇都是
FUNC = {
    "the", "of", "and", "in", "a", "an", "is", "are", "was", "were", "to", "for",
    "with", "by", "as", "that", "this", "these", "those", "we", "it", "its", "on",
    "at", "from", "can", "be", "been", "has", "have", "had", "which", "using",
    "between", "when", "where", "such", "than", "then", "also", "may", "more",
    "study", "results", "shown", "shows", "figure", "fig", "table", "however",
}

DUP_THRESHOLD = 0.30        # 段落重复率
CJK_MIN_TRANSLATION = 300   # 低于此不算「译文」，不参与判定
CJK_MIN_FULL = 2000         # 低于此判「中文字数过少」
FUNC_MAX = 4.0              # 每段英文功能词上限
MIXED_MAX = 0.15            # 中英混排段占比上限
KEY_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


# ---------------------------------------------------------------- docx 读取
def _qn(tag):
    from docx.oxml.ns import qn
    return qn(tag)


def full_text(p):
    """段落全文——**含超链接内的 run**（`Paragraph.text` 会静默漏掉它们）。"""
    qn = _qn
    return "".join(t.text or "" for t in p._p.iter(qn("w:t")))


def is_bak(name: str) -> bool:
    low = name.lower()
    return "bak" in low or bool(re.search(r"\.bak[_.]", low))


def probe(path) -> dict:
    """采集单个 docx 的结构指标（不做任何判定）。"""
    st: dict = {"size": os.path.getsize(path)}
    try:
        from docx import Document
        d = Document(str(path))
    except Exception as e:  # noqa: BLE001
        st["error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
        return st

    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    qn = _qn
    paras = [full_text(p).strip() for p in d.paragraphs]
    nonempty = [t for t in paras if t]
    body = "".join(nonempty)

    st["paras"] = len(nonempty)
    st["chars"] = len(body)
    st["cjk"] = len(CJK.findall(body))
    st["cjk_ratio"] = round(100 * st["cjk"] / max(1, st["chars"]))
    st["omath"] = sum(len(p._element.findall(".//{%s}oMath" % M))
                      for p in d.paragraphs)
    st["raw_dollar"] = sum(1 for t in nonempty if "$" in t)
    st["raw_latex"] = sum(1 for t in nonempty if BACKSLASH_CMD.search(t))
    hl = 0
    for p in d.paragraphs:
        for r in p.runs:
            rpr = r._element.find(qn("w:rPr"))
            if rpr is not None and rpr.find(qn("w:highlight")) is not None:
                hl += 1
    st["hl"] = hl
    st["images"] = len(d.inline_shapes)
    st["tables"] = len(d.tables)

    longp = [t for t in nonempty if len(t) >= 12]
    dup = len(longp) - len(set(longp))
    st["dup_rate"] = round(dup / len(longp), 3) if longp else 0.0

    st["template_hits"] = sorted({p for p in TEMPLATE_PAT if p in body})

    # 参考文献条目
    head = None
    for i, t in enumerate(paras):
        if REF_HEAD.match(t):
            head = i
            break
    refs = 0
    if head is not None:
        for i in range(head + 1, len(paras)):
            if REF_ITEM.match(paras[i]):
                refs += 1
            elif refs and paras[i]:
                break
    st["has_ref_head"] = head is not None
    st["refs"] = refs

    # 图注数（形如「图 N」的段落）
    st["captions"] = sum(1 for t in nonempty
                         if re.match(r"^图\s*\d+\s*[.．:：\u3000]?", t))

    # 英文功能词密度 + 中英混排段占比
    toks = TOKEN.findall(body)
    fw = sum(1 for t in toks if t.lower() in FUNC)
    st["func_words"] = fw
    st["func_per_para"] = round(fw / max(1, len(nonempty)), 2)
    mixed = 0
    for t in nonempty:
        if CJK.search(t):
            n = sum(1 for x in TOKEN.findall(t) if x.lower() in FUNC)
            if n >= 4:
                mixed += 1
    st["mixed_ratio"] = round(mixed / max(1, len(nonempty)), 3)
    return st


# ---------------------------------------------------------------- 判定
def verdict(st: dict):
    """返回不过关原因列表；[] = 过关；None = 不是译文（不参与判定）。"""
    if st.get("error"):
        return ["无法解析"]
    if st.get("cjk", 0) < CJK_MIN_TRANSLATION:
        return None
    bad = []
    if st.get("template_hits"):
        bad.append("模板套话(%s)" % ",".join(st["template_hits"][:2]))
    if st.get("dup_rate", 0) > DUP_THRESHOLD:
        bad.append("段落重复率%.0f%%" % (st["dup_rate"] * 100))
    if st.get("raw_dollar") or st.get("raw_latex"):
        bad.append("裸LaTeX($%d,\\%d)" % (st["raw_dollar"], st["raw_latex"]))
    if st.get("hl"):
        bad.append("高亮残留%d" % st["hl"])
    if st.get("cjk", 0) < CJK_MIN_FULL:
        bad.append("中文字数过少(%d字/共%d字符)" % (st["cjk"], st["chars"]))
    # 两个条件同时满足才判，避免把「英文引文较多的正常译文」误判
    if st.get("func_per_para", 0) > FUNC_MAX and st.get("mixed_ratio", 0) > MIXED_MAX:
        bad.append("中英混排(每段英文功能词%.1f/混排段%.0f%%)"
                   % (st["func_per_para"], st["mixed_ratio"] * 100))
    return bad


def notes(st: dict) -> list:
    """提示项：不算不过关，但值得人看一眼。"""
    out = []
    if st.get("has_ref_head") and st.get("refs", 0) == 0:
        out.append("有参考文献标题但无[n]条目（若为作者-年份制则正常）")
    if st.get("func_per_para", 0) > 1.5:
        out.append("英文功能词密度偏高(%.1f/段)，建议确认英文引文占比"
                   % st["func_per_para"])
    if st.get("cjk", 0) < 3000 and st.get("cjk") is not None:
        out.append("中文字数偏少(%d字)" % st["cjk"])
    if st.get("images", 0) == 0:
        out.append("无图片（若原文有图则缺失）")
    return out


# ---------------------------------------------------------------- Zotero 读取
def snapshot_db(db_path) -> tuple[str, str]:
    """连 WAL/SHM 一起复制一份库副本。

    Zotero 运行中会锁库，即使只读 URI 也连不上；复制时必须带上 `-wal` / `-shm`，
    否则会读到不含最新事务的旧状态。
    """
    tmp = tempfile.mkdtemp(prefix="zdb_")
    base = os.path.basename(db_path)
    for suf in ("", "-wal", "-shm"):
        src = db_path + suf
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(tmp, base + suf))
    return tmp, os.path.join(tmp, base)


def load_attachments(db_file):
    """读 Zotero 库：返回 (附件列表, 条目标题表)。只读，不改库。"""
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT ia.itemID AS item_id, ia.parentItemID AS parent_id,
               i.key AS att_key, ia.path AS path, ia.contentType AS ctype,
               pi.key AS parent_key
        FROM itemAttachments ia
        JOIN items i ON i.itemID = ia.itemID
        LEFT JOIN items pi ON pi.itemID = ia.parentItemID
    """).fetchall()
    titles = {}
    for r in con.execute("""
            SELECT id.itemID AS iid, idv.value AS title
            FROM itemData id
            JOIN itemDataValues idv ON idv.valueID = id.valueID
            JOIN fields f ON f.fieldID = id.fieldID AND f.fieldName = 'title'"""):
        titles.setdefault(r["iid"], r["title"])
    con.close()
    return [dict(r) for r in rows], titles


def _path_filename(path):
    if not path:
        return ""
    return path.split("storage:", 1)[-1].split("/")[-1]


# ---------------------------------------------------------------- 全量扫描
def scan(storage, db_file, *, quiet=False) -> dict:
    """扫描 storage 下全部 docx，并与 Zotero 附件登记交叉比对。

    返回：
      dirs      每个含 docx 的目录 -> {entries, reg, n_trans}
      problems  挂的是不过关译稿、且同目录有合格译稿可改挂
      relink    改挂清单（含附件 itemID / 目标文件名）
      garbage   不过关译文清单（含是否仍被引用）
      optimize  保留的合格译文清单
      summary   汇总数字
    """
    storage = Path(storage)
    atts, titles = load_attachments(db_file)

    att_by_key: dict = {}
    for a in atts:
        fn = _path_filename(a["path"])
        if fn.lower().endswith(".docx"):
            att_by_key.setdefault(a["att_key"], []).append(
                {"file": fn, "item_id": a["item_id"], "parent_id": a["parent_id"],
                 "parent_key": a["parent_key"],
                 "parent_title": titles.get(a["parent_id"], "") if a["parent_id"] else ""})

    dirs = {}
    for folder in sorted(storage.iterdir()):
        if not folder.is_dir():
            continue
        files = [f for f in sorted(folder.iterdir())
                 if f.is_file() and f.name.lower().endswith(".docx")
                 and not f.name.startswith("~$") and not is_bak(f.name)]
        if not files:
            continue
        entries = []
        for f in files:
            st = probe(f)
            st["file"] = f.name
            st["bad"] = verdict(st)
            st["warn"] = notes(st)
            entries.append(st)
        trans = [e for e in entries if e["bad"] is not None]
        dirs[folder.name] = {"key": folder.name, "entries": entries,
                             "n_trans": len(trans),
                             "reg": att_by_key.get(folder.name, [])}
        if not quiet and len(dirs) % 50 == 0:
            print("   ... 已扫描 %d 个目录" % len(dirs))

    problems, relink, garbage, optimize = [], [], [], []
    for key, d in dirs.items():
        regfiles = {x["file"] for x in d["reg"]}
        good = [e for e in d["entries"] if e["bad"] is not None and not e["bad"]]
        for e in d["entries"]:
            if e["bad"] is None:
                continue
            if e["bad"]:
                attached = e["file"] in regfiles
                a = next((x for x in d["reg"] if x["file"] == e["file"]), None)
                garbage.append({
                    "dir": key, "file": e["file"], "size": e["size"],
                    "attached": attached, "reasons": e["bad"],
                    "n_trans": d["n_trans"],
                    "has_good_sibling": bool(good),
                    "att_item_id": a["item_id"] if a else None,
                })
            else:
                optimize.append({"dir": key, "file": e["file"], "size": e["size"],
                                 "cjk": e["cjk"], "omath": e["omath"],
                                 "images": e["images"],
                                 "attached": e["file"] in regfiles})

        # 已挂的不过关件，且目录里有合格件 -> 问题条目
        for e in d["entries"]:
            if e["bad"] is None or not e["bad"] or e["file"] not in regfiles:
                continue
            if not good:
                continue
            a = next(x for x in d["reg"] if x["file"] == e["file"])
            g = good[0]
            problems.append({"key": key, "attached": e["file"],
                             "reasons": e["bad"],
                             "candidates": [x["file"] for x in good],
                             "parent_key": a["parent_key"],
                             "parent_title": a["parent_title"]})
            relink.append({"dir": key, "att_item_id": a["item_id"],
                           "parent_item_id": a["parent_id"],
                           "parent_title": a["parent_title"],
                           "old_file": e["file"], "old_size": e["size"],
                           "new_file": g["file"], "new_size": g["size"],
                           "new_cjk": g["cjk"], "new_images": g["images"]})

    # 目录里有合格译文、但没有任何附件指向它 -> 需补挂
    # （已在 relink 里的目录跳过，避免同一目录重复出现在两个清单）
    relinked_dirs = {x["dir"] for x in relink}
    extra_relink = []
    for key, d in dirs.items():
        if key in relinked_dirs:
            continue
        good = [e for e in d["entries"] if e["bad"] is not None and not e["bad"]]
        if not good:
            continue
        present = {p.name for p in (storage / key).iterdir() if p.is_file()}
        ok_attached = [x for x in d["reg"]
                       if x["file"] in present and x["file"] in {g["file"] for g in good}]
        if ok_attached:
            continue
        for x in d["reg"]:
            extra_relink.append({
                "dir": key, "att_item_id": x["item_id"],
                "parent_item_id": x["parent_id"], "parent_title": x["parent_title"],
                "old_file": x["file"], "old_size": 0,
                "new_file": good[0]["file"], "new_size": good[0]["size"],
                "new_cjk": good[0]["cjk"], "new_images": good[0]["images"],
                "note": "目录里有合格译文但附件指向别处/不存在",
            })

    summary = {
        "dirs": len(dirs),
        "docx": sum(len(d["entries"]) for d in dirs.values()),
        "translations": sum(d["n_trans"] for d in dirs.values()),
        "bad": sum(len([e for e in d["entries"] if e["bad"]]) for d in dirs.values()),
        "good": sum(len([e for e in d["entries"]
                         if e["bad"] is not None and not e["bad"]])
                    for d in dirs.values()),
        "problems": len(problems),
        "mixed_dirs": sum(1 for d in dirs.values() if d["n_trans"] >= 2),
        "extra_relink": len(extra_relink),
    }
    return {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "storage": str(storage), "dirs": dirs,
            "problems": problems, "relink": relink, "extra_relink": extra_relink,
            "garbage": garbage, "optimize": optimize, "summary": summary}


# ---------------------------------------------------------------- 输出
def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def write_outputs(result: dict, outdir, *, with_md5=False) -> dict:
    """产出 report.md / problems.csv / audit.json（+ 可选 manifest）。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    s = result["summary"]
    L = []
    A = L.append
    A("# Zotero 译文质量审计报告")
    A("")
    A("- 生成时间：%s" % result["generated"])
    A("- storage：`%s`" % result["storage"])
    A("")
    A("## 一、结论")
    A("")
    A("| 情形 | 数量 |")
    A("|---|---:|")
    A("| **已挂不过关译稿，且同目录有合格译稿可改挂** | **%d** |" % s["problems"])
    A("| 目录里有合格译文但附件未指向它（需补挂） | %d |" % s["extra_relink"])
    A("| 不过关译文 docx | %d |" % s["bad"])
    A("| 合格译文 docx | %d |" % s["good"])
    A("| 含 ≥2 个译文的目录（混放） | %d |" % s["mixed_dirs"])
    A("| 译文 docx 合计 | %d |" % s["translations"])
    A("")
    A("## 二、判定方法")
    A("")
    A("只看可复现的客观结构信号，命中任一即判**不过关**：")
    A("")
    A("| 信号 | 含义 |")
    A("|---|---|")
    A("| 模板套话 | 「本文题为《…》」「引言部分阐述研究背景与动机」"
      "「方法与装置部分给出实现研究目标的技术方案」「参考文献保留英文原文…详见原 PDF」"
      "「补全图注（对齐原文图号）」等旧模板流水线话术 |")
    A("| 段落重复 | 非空段落（≥12 字）中重复文本占比 > %.0f%% |" % (DUP_THRESHOLD * 100))
    A("| 裸 LaTeX | 残留 `$...$` 或 `\\frac` 之类命令 |")
    A("| 高亮残留 | 仍有 `w:highlight` 底色 |")
    A("| 中文字数过少 | 正文中文字符 < %d |" % CJK_MIN_FULL)
    A("| 中英混排 | 每段英文功能词 > %.0f 且中英混排段占比 > %.0f%%"
      "（逐词替换式伪翻译） |" % (FUNC_MAX, MIXED_MAX * 100))
    A("")
    A("以下**不参与判定**，仅作提示：参考文献有标题但无 `[n]` 条目（作者-年份制合法）、"
      "英文功能词偏多、中文字数偏少、无图片。")
    A("")

    if result["problems"]:
        A("## 三、问题清单：已挂不过关译稿，有合格译稿可改挂（%d）"
          % len(result["problems"]))
        A("")
        A("| # | 目录key | 父条目 | 已挂（不过关） | 原因 | 可改挂（合格） |")
        A("|---:|---|---|---|---|---|")
        for i, p in enumerate(result["problems"], 1):
            A("| %d | `%s` | %s | %s | %s | %s |"
              % (i, p["key"], (p["parent_title"] or "")[:32], p["attached"][:40],
                 "；".join(p["reasons"])[:56],
                 " / ".join(c[:36] for c in p["candidates"])))
        A("")
    if result["extra_relink"]:
        A("## 四、需补挂：目录里有合格译文但附件未指向它（%d）"
          % len(result["extra_relink"]))
        A("")
        A("| # | 目录key | 附件现指向（不存在） | 应改挂 |")
        A("|---:|---|---|---|")
        for i, x in enumerate(result["extra_relink"], 1):
            A("| %d | `%s` | %s | %s |"
              % (i, x["dir"], x["old_file"][:46], x["new_file"][:46]))
        A("")

    md = outdir / "quality_report.md"
    md.write_text("\n".join(L), encoding="utf-8")

    csvp = outdir / "quality_problems.csv"
    with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["目录key", "父条目key", "父条目标题", "已挂文件（不过关）",
                    "不过关原因", "可改挂文件（合格）"])
        for p in result["problems"]:
            w.writerow([p["key"], p["parent_key"], p["parent_title"],
                        p["attached"], "；".join(p["reasons"]),
                        " / ".join(p["candidates"])])

    js = outdir / "quality_audit.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                  encoding="utf-8")

    paths = {"report": str(md), "problems_csv": str(csvp), "audit_json": str(js)}
    if with_md5:
        rows = []
        for g in result["garbage"]:
            p = Path(result["storage"]) / g["dir"] / g["file"]
            rec = dict(g)
            rec["path"] = str(p)
            rec["exists"] = p.exists()
            rec["md5"] = _md5(p) if p.exists() else ""
            rows.append(rec)
        man = outdir / "quality_garbage_manifest.json"
        man.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        paths["manifest"] = str(man)
    return paths


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="译文 DOCX 质量审计（只读）")
    ap.add_argument("--storage", required=True)
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--with-md5", action="store_true",
                    help="额外产出垃圾文件清单（含 md5）")
    a = ap.parse_args(argv)
    tmp, dbfile = snapshot_db(a.sqlite)
    try:
        res = scan(a.storage, dbfile)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    paths = write_outputs(res, a.out, with_md5=a.with_md5)
    s = res["summary"]
    print("目录 %d ；译文 %d ；不过关 %d ；问题条目 %d ；需补挂 %d"
          % (s["dirs"], s["translations"], s["bad"], s["problems"],
             s["extra_relink"]))
    for k, v in paths.items():
        print("  %-14s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
