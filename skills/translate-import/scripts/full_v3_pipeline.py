# -*- coding: utf-8 -*-
"""Batch pipeline for sentence-faithful full translation of Zotero PDFs.

本脚本**只做机械步骤**：
    提取（extract） → 构建（build，内含终稿规范化） → 校验（verify） → 记录台账

其中「构建」这一步（`build_docx.py`）产出的**就已经是终稿**：公式是 Word 原生公式
对象、带页眉页码、图注规范、正文引用可点击跳转、参考文献一致性已校验。构建阶段
任何一项不通过（缺 pandoc、公式转不动、参考文献对不上号）都会返回 `build_failed`，
**不会**留下一份看起来成功、实际有问题的 DOCX。

它**不生成任何译文内容**。
「全文精译 · 逐句对应」的 parts/*.json 必须由 Agent / 人工按英文原文逐句写出，
脚本绝不代写、绝不套模板、绝不按章节摘要扩写。

已彻底删除（历史遗留、与「全文精译」宗旨冲突）：
    build_full_blocks()  —— 模板化摘要生成器
    zh_abs() / zh_intro() / zh_methods() / zh_results() / zh_concl()
                         —— 五段写死的中文模板
    topics_of() / nums_of() / get_chunk()
                         —— 仅供上述模板投料的关键词与片段抽取
这些函数会拼出「摘要 / 1 引言 / 2 方法与装置 / 3 结果与讨论 / 4 结论 /
5 应用与展望」的固定骨架，属于 SKILL.md 明令禁止的「按固定模板扩写」，
且会丢光全部公式，因此整块移除。译文只从 <work>/item_<id>/parts/*.json 读取。

用法:
    python full_v3_pipeline.py [N]           # 处理 N 篇（默认 25）
    python full_v3_pipeline.py [N] --extract-only   # 只做提取，产出待译素材
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate_config import cfg, ensure_utf8_stdio

ensure_utf8_stdio()
BASE = str(cfg.work_base)
ZC = os.path.dirname(os.path.abspath(__file__))
PY = cfg.python
env = dict(os.environ, PYTHONUTF8="1")
# 质量标准 = 与英文原文逐句对应；不设任何字数上下限。

tasks = {t["itemID"]: t for t in json.load(open(str(cfg.tasks_json), encoding="utf-8"))}
status_path = str(cfg.status_json)
status = json.load(open(status_path, encoding="utf-8")) if os.path.exists(status_path) else {}


def _docx_ok(docx):
    """DOCX 存在且可解析、非空。不使用字数阈值判定。"""
    if not docx or not os.path.exists(docx):
        return False
    try:
        vr = subprocess.run([PY, "-X", "utf8", os.path.join(ZC, "verify_docx.py"), docx],
                            capture_output=True, env=env, timeout=120)
        v = json.loads(vr.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        return bool(v.get("ok"))
    except Exception:
        return False


def pending_items():
    """待处理 = 台账标记 ok 但产物缺失/不可解析，或 DOCX 尚未登记。"""
    out = []
    for k, v in status.items():
        if not isinstance(v, dict):
            continue
        if v.get("status") != "ok":
            out.append({"id": int(k), "title": v.get("title_cn", ""), "docx": v.get("docx", "")})
        elif not _docx_ok(v.get("docx", "")):
            out.append({"id": int(k), "title": v.get("title_cn", ""), "docx": v.get("docx", "")})
    return out


def ensure_extract(iid):
    """提取 PDF：文本块 + 原始图 + 裁切图 + 公式定位。返回 extract.json 路径。"""
    t = tasks.get(iid)
    if not t:
        return None
    wd = os.path.join(BASE, "work", "item_%d" % iid)
    img_dir = os.path.join(wd, "images")
    fig_dir = os.path.join(wd, "figures")
    fml_dir = os.path.join(wd, "formulas")
    for d in (img_dir, fig_dir, fml_dir):
        os.makedirs(d, exist_ok=True)
    ex = os.path.join(wd, "extract.json")
    if not (os.path.exists(ex) and os.path.getsize(ex) > 100):
        with open(ex, "wb") as fout:
            subprocess.run(
                [PY, "-X", "utf8", os.path.join(ZC, "extract_pdf_text.py"),
                 t["pdf"], img_dir, fig_dir, fml_dir],
                stdout=fout, stderr=subprocess.DEVNULL, env=env, timeout=1800)
    return ex


def extract_only(limit):
    """只做提取，产出待译素材（extract.json + images/figures/formulas）。"""
    n = 0
    for rec in pending_items()[:limit]:
        iid = rec["id"]
        ex = ensure_extract(iid)
        if not ex or not os.path.exists(ex):
            print("EXTRACT FAIL", iid)
            continue
        try:
            data = json.load(open(ex, encoding="utf-8"))
        except Exception:
            print("EXTRACT BAD", iid)
            continue
        nf = sum(len(p.get("figures", [])) for p in data.get("pages", []))
        nm = sum(len(p.get("formulas", [])) for p in data.get("pages", []))
        print("EXTRACTED", iid, "chars=%d" % data.get("total_chars", 0),
              "figures=%d" % nf, "formulas=%d" % nm)
        n += 1
    print("extracted", n)


def build_one(rec):
    """构建 + 校验。parts/*.json 必须已由 Agent/人工写好；缺失则跳过，绝不代写。"""
    iid = rec["id"]
    t = tasks.get(iid)
    if not t:
        return None
    wd = os.path.join(BASE, "work", "item_%d" % iid)
    parts = os.path.join(wd, "parts")
    if not os.path.isdir(parts) or not glob_json(parts):
        return {"itemID": iid, "status": "no_translation",
                "note": "parts/*.json 缺失：译文须由 Agent 逐句精译补齐，脚本不代写"}
    st = status.get(str(iid), {})
    title = (st.get("title_cn") or rec.get("title") or t.get("ztitle") or "未命名")
    title = title.replace("【!】", "").strip()
    docx = st.get("docx") or ""
    if not docx:
        fn = re.sub(r'[\\/:*?"<>|]', "_", title)[:90]
        docx = os.path.join(t.get("folder") or os.path.dirname(t.get("pdf", ".")), fn + ".docx")
    br = subprocess.run([PY, "-X", "utf8", os.path.join(ZC, "build_docx.py"),
                         parts, docx], capture_output=True, env=env, timeout=3600)
    if br.returncode != 0:
        err = br.stderr.decode("utf-8", "replace").strip().splitlines()
        return {"itemID": iid, "status": "build_failed", "docx": docx,
                "title_cn": title, "chars": 0, "images": 0,
                "note": " / ".join(err[-6:])[:600] or
                        "build_docx.py exit %d" % br.returncode}
    vr = subprocess.run([PY, "-X", "utf8", os.path.join(ZC, "verify_docx.py"), docx],
                        capture_output=True, env=env, timeout=600)
    try:
        v = json.loads(vr.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except Exception:
        v = {"ok": False}
    return {"itemID": iid, "status": "ok" if v.get("ok") else "verify_failed",
            "docx": docx, "title_cn": title, "chars": v.get("chars", 0),
            "images": v.get("images", 0),
            "note": "full_cn_sentence_faithful"}


def glob_json(parts_dir):
    return [f for f in os.listdir(parts_dir) if f.lower().endswith(".json")]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    limit = int(args[0]) if args else 25

    if "--extract-only" in flags:
        extract_only(limit)
        return

    ok = fail = skip = 0
    for rec in pending_items()[:limit]:
        iid = rec["id"]
        try:
            ensure_extract(iid)
            out = build_one(rec)
            if out is None:
                fail += 1
                print("FAIL", iid, "(no task)")
                continue
            if out["status"] == "no_translation":
                skip += 1
                print("SKIP", iid, "缺 parts/*.json（需逐句精译）")
                continue
            os.makedirs(os.path.join(BASE, "results"), exist_ok=True)
            open(os.path.join(BASE, "results", "r_%d.json" % iid), "w",
                 encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
            if out["status"] == "ok":
                ok += 1
                print("OK", iid, out.get("chars", 0), out.get("title_cn", "")[:40])
            elif out["status"] == "build_failed":
                fail += 1
                print("BUILD FAIL", iid, "->", (out.get("note") or "")[:160])
            else:
                fail += 1
                print("VERIFY FAIL", iid, out.get("title_cn", "")[:40],
                      "->", (out.get("note") or "")[:160])
        except Exception as e:
            fail += 1
            print("ERR", iid, type(e).__name__, e)
    print("batch ok", ok, "fail", fail, "skip(no translation)", skip)


if __name__ == "__main__":
    main()
