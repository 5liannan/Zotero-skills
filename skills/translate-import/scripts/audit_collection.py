# -*- coding: utf-8 -*-
"""分类级翻译情况审计：独立扫库，不信任既有台账。

用法：
    python audit_collection.py --collection "DOFS-信号处理" [--out audit.md] \
        [--work-root DIR] [--status status_oc.json]

输出（Markdown + 控制台摘要）：
1. 分类内条目总数 / 已挂译文 / 有 PDF 未译 / 无 PDF；
2. 有 PDF 未译清单（含 PDF 附件 key、DOI）；
3. 无 PDF 清单；
4. 台账一致性（已挂但不在台账 / 台账有但无附件）；
5. **DOI 重复聚类**：同 DOI 的多条目（含跨分类），标注"已译/未译"，
   用于判断"英文条目 + 中文兄弟条目"这类重复对只需译一次、挂多处。

关键实现点（踩过的坑）：
- itemAttachments.path 只是 `storage:<文件名>`，**不含 8 字符子目录**；
  判文件是否存在必须按文件名建 storage 全量索引再匹配（本脚本 build_storage_index）；
- 文件名可能 NFC/NFD 不一致，比较前统一 unicodedata.normalize('NFC')；
- 子分类递归收集（collectionItems 只含直接成员）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translate_config import cfg, ensure_utf8_stdio  # noqa: E402

ATTACH_TYPES = "(SELECT itemTypeID FROM itemTypes WHERE typeName='attachment')"


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def build_storage_index(storage: Path) -> dict[str, str]:
    idx: dict[str, str] = {}
    for root, _dirs, files in os.walk(storage):
        for f in files:
            if f.lower().endswith((".pdf", ".docx")):
                idx[norm(f)] = os.path.join(root, f)
    return idx


def resolve_collections(cur, spec: str) -> list[tuple[int, str]]:
    spec = spec.strip()
    if spec.isdigit():
        row = cur.execute("SELECT collectionID, collectionName FROM collections WHERE collectionID=?", (int(spec),)).fetchone()
        return [row] if row else []
    rows = cur.execute(
        "SELECT collectionID, collectionName FROM collections WHERE collectionName LIKE ?",
        (f"%{spec}%",),
    ).fetchall()
    return rows


def collect_items(cur, coll_ids: list[int]) -> list[tuple[int, str, str, str]]:
    q = (
        "SELECT DISTINCT i.itemID, i.key, "
        "(SELECT d.value FROM itemData id JOIN itemDataValues d ON d.valueID=id.valueID "
        " JOIN fields f ON f.fieldID=id.fieldID WHERE id.itemID=i.itemID AND f.fieldName='title') AS title, "
        "(SELECT d.value FROM itemData id JOIN itemDataValues d ON d.valueID=id.valueID "
        " JOIN fields f ON f.fieldID=id.fieldID WHERE id.itemID=i.itemID AND f.fieldName='DOI') AS doi "
        "FROM items i JOIN collectionItems ci ON ci.itemID=i.itemID "
        f"WHERE ci.collectionID IN ({','.join('?' * len(coll_ids))}) "
        f"AND i.itemTypeID NOT IN {ATTACH_TYPES} ORDER BY i.itemID"
    )
    return cur.execute(q, coll_ids).fetchall()


def item_attachments(cur, iid: int, idx: dict[str, str]) -> tuple[list, list, list]:
    pdfs, docxs, missing = [], [], []
    for apath, akey in cur.execute(
        "SELECT a.path, i.key FROM itemAttachments a JOIN items i ON i.itemID=a.itemID "
        "WHERE a.parentItemID=?",
        (iid,),
    ):
        if not apath:
            continue
        fn = norm(apath.split(":", 1)[1]) if ":" in apath else norm(os.path.basename(apath))
        full = idx.get(fn)
        low = fn.lower()
        if low.endswith(".pdf"):
            pdfs.append((akey, full))
        elif low.endswith(".docx"):
            docxs.append((akey, full))
        else:
            continue
        if not full:
            missing.append(fn)
    return pdfs, docxs, missing


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="分类级翻译情况审计（独立扫库）")
    ap.add_argument("--collection", required=True, help="分类名（子串）或 collectionID")
    ap.add_argument("--out", default="", help="Markdown 报告输出路径")
    ap.add_argument("--work-root", default="", help="工作根目录（默认 ZOTERO_WORK_BASE）")
    ap.add_argument("--status", default="", help="台账 status_oc.json（默认 cfg.status_json）")
    ap.add_argument("--no-doi-dup", action="store_true", help="跳过 DOI 重复聚类")
    args = ap.parse_args(argv)

    db = cfg.sqlite_path
    if not db.exists():
        raise SystemExit(f"找不到 zotero.sqlite：{db}")
    tmp = Path(os.environ.get("TEMP", ".")) / f"_zotero_audit_{os.getpid()}.sqlite"
    # 只拷 .sqlite 会漏掉还在 WAL 里、尚未 checkpoint 的近期变更（分类成员/新附件），
    # 导致"昨晚 152 条、今早 173 条"这类口径漂移；-wal/-shm 必须一起拷。
    shutil.copy(db, tmp)
    for suffix in ("-wal", "-shm"):
        side = Path(str(db) + suffix)
        if side.exists():
            shutil.copy(side, Path(str(tmp) + suffix))
    cur = sqlite3.connect(str(tmp))

    idx = build_storage_index(cfg.storage_dir)
    colls = resolve_collections(cur, args.collection)
    if not colls:
        raise SystemExit(f"找不到分类：{args.collection}")
    root_ids = [c[0] for c in colls]
    coll_ids = list(root_ids)
    queue = list(root_ids)
    while queue:
        pid = queue.pop()
        kids = [r[0] for r in cur.execute("SELECT collectionID FROM collections WHERE parentCollectionID=?", (pid,)).fetchall()]
        coll_ids.extend(kids)
        queue.extend(kids)
    names = "、".join(c[1] for c in colls)

    items = collect_items(cur, coll_ids)
    status_path = Path(args.status) if args.status else Path(cfg.status_json)
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    st_by_id = {int(k): v for k, v in status.items()}

    rows = []
    for iid, ikey, title, doi in items:
        pdfs, docxs, missing = item_attachments(cur, iid, idx)
        inst = st_by_id.get(iid)
        rows.append({
            "itemID": iid, "key": ikey, "title": norm(title), "doi": (doi or "").strip().lower(),
            "pdf_keys": [p[0] for p in pdfs], "pdf_exist": any(p[1] for p in pdfs),
            "docx_keys": [d[0] for d in docxs], "docx_exist": any(d[1] for d in docxs),
            "missing": missing, "in_status": inst is not None,
        })

    # DOI 重复聚类（分类内 + 全库）
    doi_rows: dict[str, list[tuple[int, str]]] = {}
    if not args.no_doi_dup:
        for iid, ikey, title, doi in items:
            d = (doi or "").strip().lower()
            if d:
                doi_rows.setdefault(d, []).append((iid, norm(title)))
        lib_doi: dict[str, list[int]] = {}
        for d in list(doi_rows):
            for (iid,) in cur.execute(
                "SELECT i.itemID FROM items i WHERE i.itemID IN ("
                " SELECT id.itemID FROM itemData id JOIN itemDataValues dv ON dv.valueID=id.valueID "
                " JOIN fields f ON f.fieldID=id.fieldID WHERE f.fieldName='DOI' AND lower(dv.value)=?)",
                (d,),
            ).fetchall():
                lib_doi.setdefault(d, []).append(iid)

    cur.close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)

    done = [r for r in rows if r["docx_exist"]]
    todo = [r for r in rows if not r["docx_exist"] and r["pdf_exist"]]
    nopdf = [r for r in rows if not r["docx_exist"] and not r["pdf_exist"]]
    gaps = [r for r in rows if r["docx_exist"] and not r["in_status"]]
    orphan = [r for r in rows if r["in_status"] and not r["docx_exist"]]
    broken = [r for r in rows if r["missing"]]

    print(f"分类：{names}（{len(coll_ids)} 个分类节点）")
    print(f"条目 {len(rows)} | 已挂译文 {len(done)} | 有 PDF 未译 {len(todo)} | 无 PDF {len(nopdf)}")
    if broken:
        print("附件记录缺文件：", [(r["itemID"], r["missing"]) for r in broken])
    if gaps:
        print("已挂译文但不在台账：", [r["itemID"] for r in gaps])
    if orphan:
        print("台账有但无附件：", [r["itemID"] for r in orphan])

    lines = [
        f"# 翻译情况审计：{names}",
        "",
        f"- 分类节点：{len(coll_ids)}（含子分类）",
        f"- 条目总数：{len(rows)}；已挂译文：{len(done)}；有 PDF 未译：{len(todo)}；无 PDF：{len(nopdf)}",
        f"- 台账：{status_path}（{len(st_by_id)} 条）",
        "",
        "## 一、有 PDF 未翻译",
        "",
        "| itemID | 标题 | DOI | PDF key | 同 DOI 的其他条目 |",
        "|---|---|---|---|---|",
    ]
    for r in todo:
        others = [i for i in (lib_doi.get(r["doi"], []) if r["doi"] else []) if i != r["itemID"]]
        lines.append(f"| {r['itemID']} | {r['title']} | {r['doi']} | {','.join(r['pdf_keys'])} | {','.join(map(str, others))} |")
    lines += ["", "## 二、无 PDF（无法翻译）", "", "| itemID | 标题 |", "|---|---|"]
    for r in nopdf:
        lines.append(f"| {r['itemID']} | {r['title']} |")
    lines += ["", "## 三、已挂译文", "", "| itemID | 标题 | docx key | 在台账 |", "|---|---|---|---|"]
    for r in sorted(done, key=lambda x: x["itemID"]):
        lines.append(f"| {r['itemID']} | {r['title'][:60]} | {','.join(r['docx_keys'])} | {'Y' if r['in_status'] else 'N'} |")
    if not args.no_doi_dup:
        dup_groups = {d: ids for d, ids in lib_doi.items() if len(ids) > 1}
        if dup_groups:
            lines += ["", "## 四、DOI 重复聚类（同文多条目）", "", "| DOI | 条目（已挂译文?） |", "|---|---|"]
            for d, ids in sorted(dup_groups.items()):
                parts = []
                for i in ids:
                    row = next((r for r in rows if r["itemID"] == i), None)
                    mark = "已译" if row and row["docx_exist"] else "未译"
                    parts.append(f"{i}({mark})")
                lines.append(f"| {d} | {'、'.join(parts)} |")
    lines += ["", "## 五、台账一致性", ""]
    lines.append(f"- 已挂译文但不在台账：{ [r['itemID'] for r in gaps] }")
    lines.append(f"- 台账有但无附件：{ [r['itemID'] for r in orphan] }")
    lines.append(f"- 附件记录缺文件：{ [(r['itemID'], r['missing']) for r in broken] }")

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("report ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
