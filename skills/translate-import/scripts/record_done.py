# -*- coding: utf-8 -*-
"""一条命令完成「记账 + 挂接」：多篇并行翻译的收尾入口。

用法：
    python record_done.py work/item_11847/report.json [更多 report.json ...] \
        [--work-root DIR] [--total N] [--no-attach] [--no-progress]

report.json 由翻译代理在完成时写出，字段（必需 itemID / docx）：

    {
      "itemID": 11847,                       # 真实父条目（PDF 所属）
      "title": "中文标题",
      "docx": "work/item_11847/中文标题.docx",
      "pages": 18, "chars": 8600,
      "figures": 31, "equations": 31, "tables": 1, "refs": 68,
      "zotero_real_itemID": 11847,           # 缺省 = itemID
      "zotero_sibling_itemIDs": [11256],     # 同文重复条目（可选，一起挂接）
      "notes": "同文条目 11256"
    }

做的事：
1. 校验 docx 与 report.json 存在（不信任"已完成"的口头汇报）；
2. 更新台账 status_oc.json（默认 cfg.status_json）；
3. 若 work-root 下有 PROGRESS.md：计数 +1（**同一 itemID 重复记账自动跳过**），
   追加表格行与说明；`--total` 未给时沿用 PROGRESS 头里的总数；
4. 调 attach_docx.main() 挂接主条目 + 全部 zotero_sibling_itemIDs（幂等）。

设计要点（踩过的坑）：
- 同一篇完成消息可能被触发两次，重复记账会虚增计数、插重复行 —— 本脚本按 itemID 去重；
- 只认 report.json 里的 docx 实际存在，避免"代理报完成、产物为空"；
- 兄弟条目由 report 显式列出，不猜。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translate_config import cfg, ensure_utf8_stdio  # noqa: E402

import attach_docx  # noqa: E402

_DONE_HDR = re.compile(r"## 已完成（(\d+)\s*/\s*(\d+)）")


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(n or "")


def load_reports(paths: list[str]) -> list[dict]:
    reports = []
    for p in paths:
        rp = Path(p)
        if not rp.is_file():
            raise SystemExit(f"report 不存在：{rp}")
        r = json.loads(rp.read_text(encoding="utf-8"))
        docx = Path(str(r.get("docx", "")))
        if not docx.is_file():
            raise SystemExit(f"report 指向的 docx 不存在：{docx}")
        r.setdefault("zotero_real_itemID", r["itemID"])
        r["_report"] = str(rp)
        reports.append(r)
    return reports


def update_status(status_path: Path, reports: list[dict]) -> None:
    if not status_path.parent.exists():
        status_path.parent.mkdir(parents=True, exist_ok=True)
    st = {}
    if status_path.is_file():
        st = json.loads(status_path.read_text(encoding="utf-8"))
    for r in reports:
        st[str(r["itemID"])] = {
            "status": "ok",
            "docx": str(r["docx"]),
            "itemID": r["itemID"],
            "zotero_real_itemID": r.get("zotero_real_itemID", r["itemID"]),
            "siblings": r.get("zotero_sibling_itemIDs", []),
            "attachment_key": r.get("attachment_key", ""),
            "title": r.get("title", ""),
        }
    status_path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def update_progress(prog_path: Path, reports: list[dict], total: int | None) -> tuple[int, int]:
    """返回 (已完成数, 总数)。同一 itemID 重复记账不增计数、不插行。"""
    if not prog_path.is_file():
        return (0, total or 0)
    txt = prog_path.read_text(encoding="utf-8")
    m = _DONE_HDR.search(txt)
    if m:
        done_n, total_n = int(m.group(1)), int(m.group(2))
    else:
        done_n, total_n = 0, total or 0
    if total:
        total_n = total

    lines = txt.split("\n")
    new_rows = []
    for r in reports:
        iid = str(r["itemID"])
        if re.search(rf"^\|\s*{re.escape(iid)}\s*\|", "\n".join(lines), re.M):
            continue  # 已记过账
        new_rows.append(r)
    done_n += len(new_rows)
    txt = _DONE_HDR.sub(f"## 已完成（{done_n} / {total_n}）", txt, count=1) if m else txt
    lines = txt.split("\n")

    if new_rows:
        last_tbl = -1
        in_done = False
        for i, ln in enumerate(lines):
            if ln.startswith("## 已完成"):
                in_done = True
            elif ln.startswith("## ") and in_done:
                in_done = False
            if in_done and re.match(r"^\| \d+ \|", ln):
                last_tbl = i
        if last_tbl > 0:
            for r in reversed(new_rows):
                akey = r.get("attachment_key") or "?"
                row = (
                    f"| {r['itemID']} | {r.get('title', '')} | {r.get('pages', '')} | "
                    f"{fmt_int(r.get('chars', 0))} | {r.get('figures', '')} | "
                    f"{r.get('equations', '')} | {r.get('tables', '')} | "
                    f"{r.get('refs', '')} | {akey} | ok=true |"
                )
                lines.insert(last_tbl + 1, row)
                note = (
                    f"- {r['itemID']} = {r.get('title', '')}"
                    f"（{r.get('pages', '')} 页/{fmt_int(r.get('chars', 0))} 字/"
                    f"{r.get('figures', '')} 图/{r.get('equations', '')} 式/"
                    f"{r.get('tables', '')} 表/{r.get('refs', '')} 文献"
                )
                sib = r.get("zotero_sibling_itemIDs") or []
                if sib:
                    note += f"；同文条目 {'、'.join(str(s) for s in sib)}"
                if r.get("notes"):
                    note += f"；{r['notes']}"
                note += "）"
                j = last_tbl + 2
                while j < len(lines) and lines[j].strip() != "":
                    j += 1
                lines.insert(j + 1, note)
        ids = "、".join(str(r["itemID"]) for r in new_rows)
        for i, ln in enumerate(lines):
            if ln.strip().startswith("- **当前进度**"):
                lines[i] = (
                    f"- **当前进度**：累计 {done_n}/{total_n}，刚完成 {ids}；继续处理剩余待办。"
                )
                break
    prog_path.write_text("\n".join(lines), encoding="utf-8")
    return done_n, total_n


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="记账 + 挂接：多篇并行翻译的收尾入口")
    ap.add_argument("reports", nargs="+", help="report.json 路径")
    ap.add_argument("--work-root", default="", help="工作根目录（默认 ZOTERO_WORK_BASE）")
    ap.add_argument("--total", type=int, default=None, help="任务总数（默认沿用 PROGRESS 头）")
    ap.add_argument("--no-attach", action="store_true", help="只记账，不挂接")
    ap.add_argument("--no-progress", action="store_true", help="不更新 PROGRESS.md")
    ap.add_argument("--status", default="", help="台账路径（默认 cfg.status_json）")
    args = ap.parse_args(argv)

    work_root = Path(args.work_root) if args.work_root else Path(cfg.work_base)
    status_path = Path(args.status) if args.status else Path(cfg.status_json)
    prog_path = work_root / "PROGRESS.md"

    reports = load_reports(args.reports)
    update_status(status_path, reports)
    done_n, total_n = (0, 0)
    if not args.no_progress:
        done_n, total_n = update_progress(prog_path, reports, args.total)
        if done_n:
            print(f"progress: {done_n}/{total_n}")

    if args.no_attach:
        print("attach: skipped (--no-attach)")
        return 0

    jobs = []
    for r in reports:
        for pid in [r.get("zotero_real_itemID", r["itemID"]), *(r.get("zotero_sibling_itemIDs") or [])]:
            jobs.append({"itemID": int(pid), "docx": r["docx"]})
    rc = attach_docx.main(jobs, dry_run=False)
    print(f"done: {[r['itemID'] for r in reports]}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
