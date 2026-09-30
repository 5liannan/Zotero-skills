# -*- coding: utf-8 -*-
"""质量审计的回归测试：用合成 fixture 造出各类情形，断言判定与清单正确。

跑法：
    python tests/test_storage_quality.py

不依赖真实 Zotero：fixture 里自建一个最小 sqlite（只含审计用到的表）和若干 docx。
覆盖：
  1. 判定函数：模板套话 / 段落重复 / 裸 LaTeX / 高亮 / 中文字数过少 / 中英混排
  2. 交叉比对：挂错附件 -> problems+relink；附件指向不存在的文件 -> extra_relink
  3. 保留的合格译文 -> optimize；不过关译文 -> garbage（含是否仍被引用）
  4. 报告产出：report.md / problems.csv / audit.json
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import docx_quality as dq  # noqa: E402

GOOD_SENTENCE = ("示例正文：该方法可对待测物理量进行连续监测，"
                 "其空间分辨率与信噪比之间存在相互制约关系，需要综合优化。")
TEMPLATE_HEAD = [
    "本文题为《示例文献》，属于气体、温度、黏滞、压力方向的研究工作。原文摘要表明："
    "研究针对相关科学或工程问题展开。",
    "引言部分阐述研究背景与动机。相关技术在结构健康监测、管道与周界安全等方面具有重要应用需求。",
    "方法与装置部分给出实现研究目标的技术方案。对实验工作，描述光源与调制、探测与采集链路。",
    "结果与讨论部分展示主要实验或计算结果。作者给出谱形、拟合曲线与性能指标。",
    "结论总结本文主要发现：所提方法在所述条件下能够有效服务相关测量、诊断或系统设计。",
    "参考文献保留英文原文，编号与原文一致，详见原 PDF。",
]


def make_docx(path: Path, paragraphs, *, table=False):
    from docx import Document
    d = Document()
    for t in paragraphs:
        d.add_paragraph(t)
    if table:
        d.add_table(rows=2, cols=2)
    d.save(str(path))


def good_paras():
    """一份合格译文：中文够量、无模板话术、**段落各不相同**、带 [n] 文献条目。"""
    body = [GOOD_SENTENCE * 6 + "本节讨论第 %d 个方面。" % i for i in range(10)]
    refs = ["[%d] Author, A.: Demo reference %d, J. Demo, 1(1), 1-2, 2024." % (i, i)
            for i in range(1, 6)]
    return ["示例文献标题"] + body + ["参考文献"] + refs


def garbage_paras(n=6):
    """模板垃圾：套话 + 同一批图注重复 n 遍。"""
    caps = ["图 %d：Temperature variation of selected fluids." % i for i in range(1, 6)]
    out = ["示例文献标题"]
    for _ in range(n):
        out += TEMPLATE_HEAD + ["补全图注（对齐原文图号）"] + caps + ["$R p\\tau i,$  (3)"]
    return out


def build_fixture(root: Path):
    """建 storage + 最小 zotero.sqlite。返回 (storage, dbfile)。"""
    storage = root / "storage"
    rows = []          # (key, parent_key, path, is_parent)

    def mkdir(key):
        (storage / key).mkdir(parents=True, exist_ok=True)

    # K1: 合格译文 + 模板垃圾同目录；附件指向垃圾  -> 问题条目 + 改挂
    mkdir("K0000001")
    make_docx(storage / "K0000001" / "合格译文.docx", good_paras())
    make_docx(storage / "K0000001" / "模板垃圾.docx", garbage_paras())
    rows.append(("K0000001", "P0000001", "storage:模板垃圾.docx"))

    # K2: 只有模板垃圾，无替代  -> garbage 且仍被引用
    mkdir("K0000002")
    make_docx(storage / "K0000002" / "模板垃圾.docx", garbage_paras())
    rows.append(("K0000002", "P0000002", "storage:模板垃圾.docx"))

    # K3: 合格译文在，但附件指向不存在的文件  -> extra_relink
    mkdir("K0000003")
    make_docx(storage / "K0000003" / "合格译文.docx", good_paras())
    rows.append(("K0000003", "P0000003", "storage:不存在的文件.docx"))

    # K4: 合格译文 + 附件正确指向  -> 无问题
    mkdir("K0000004")
    make_docx(storage / "K0000004" / "合格译文.docx", good_paras())
    rows.append(("K0000004", "P0000004", "storage:合格译文.docx"))

    dbfile = root / "zotero.sqlite"
    con = sqlite3.connect(dbfile)
    con.executescript("""
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, libraryID INT,
                            itemTypeID INT, dateAdded TEXT, version INT);
        CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT,
                                      linkMode INT, contentType TEXT, path TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
    """)
    con.execute("INSERT INTO fields VALUES (110,'title')")
    iid = 1
    vid = 1
    for att_key, parent_key, path in rows:
        # 父条目
        con.execute("INSERT INTO items (itemID,key,libraryID,itemTypeID,version) "
                    "VALUES (?,?,1,4,0)", (iid, parent_key))
        con.execute("INSERT INTO itemDataValues VALUES (?,?)", (vid, "标题 " + parent_key))
        con.execute("INSERT INTO itemData VALUES (?,110,?)", (iid, vid))
        pid, vid = iid, vid + 1
        iid += 1
        # 附件
        con.execute("INSERT INTO items (itemID,key,libraryID,itemTypeID,version) "
                    "VALUES (?,?,1,3,0)", (iid, att_key))
        con.execute("INSERT INTO itemAttachments VALUES (?,?,0,?,?)",
                    (iid, pid, "application/vnd.openxmlformats-officedocument."
                               "wordprocessingml.document", path))
        con.execute("INSERT INTO itemDataValues VALUES (?,?)", (vid, "[docx]标题 " + att_key))
        con.execute("INSERT INTO itemData VALUES (?,110,?)", (iid, vid))
        iid += 1
        vid += 1
    con.commit()
    con.close()
    return storage, str(dbfile)


# ------------------------------------------------------------------ 单测
def check_verdicts():
    ok = True
    good = dq.probe(Path(os.environ["FIXTURE_GOOD"]))
    assert dq.verdict(good) == [], "合格译文被误判: %s" % dq.verdict(good)
    bad = dq.probe(Path(os.environ["FIXTURE_BAD"]))
    v = dq.verdict(bad)
    assert v, "模板垃圾未被判不过关"
    assert any(x.startswith("模板套话") for x in v), v
    assert any(x.startswith("段落重复率") for x in v), v
    assert any(x.startswith("中文字数过少") for x in v), v
    print("  判定函数            PASS  bad=%s" % "；".join(v)[:80])

    # 逐条信号单测（直接喂指标，不依赖 docx）
    def mk(**kw):
        base = {"cjk": 5000, "chars": 9000, "template_hits": [], "dup_rate": 0.0,
                "raw_dollar": 0, "raw_latex": 0, "hl": 0, "func_per_para": 1.0,
                "mixed_ratio": 0.0, "has_ref_head": True, "refs": 3,
                "images": 2, "paras": 40, "cjk_ratio": 55}
        base.update(kw)
        return base

    assert dq.verdict(mk()) == []
    assert dq.verdict(mk(cjk=100)) is None, "非译文不应参与判定"
    assert dq.verdict(mk(raw_dollar=2))
    assert dq.verdict(mk(raw_latex=1))
    assert dq.verdict(mk(hl=7))
    assert dq.verdict(mk(dup_rate=0.5))
    assert dq.verdict(mk(template_hits=["本文题为《"]))
    assert dq.verdict(mk(cjk=1500, chars=1600))
    assert dq.verdict(mk(func_per_para=9.0, mixed_ratio=0.3)), "中英混排应被判定"
    # 双条件：只满足一个不判（避免误伤英文引文多的正常译文）
    assert dq.verdict(mk(func_per_para=9.0, mixed_ratio=0.0)) == []
    assert dq.verdict(mk(func_per_para=2.0, mixed_ratio=0.5)) == []
    # 提示项不参与判定
    n = dq.notes(mk(has_ref_head=True, refs=0))
    assert any("作者-年份制" in x for x in n), n
    print("  信号逐条（含双条件）PASS")
    return ok


def check_scan(storage, dbfile):
    res = dq.scan(storage, dbfile, quiet=True)
    s = res["summary"]
    print("  扫描汇总            dirs=%d translations=%d bad=%d good=%d "
          "problems=%d extra_relink=%d mixed=%d"
          % (s["dirs"], s["translations"], s["bad"], s["good"],
             s["problems"], s["extra_relink"], s["mixed_dirs"]))
    assert s["dirs"] == 4, s
    assert s["translations"] == 5, s                 # K1×2 + K2×1 + K3×1 + K4×1
    assert s["bad"] == 2, s                          # K1 的模板垃圾 + K2 的模板垃圾
    assert s["problems"] == 1, s
    assert s["extra_relink"] == 1, s                 # K1 已进 relink，不应重复计入
    assert s["mixed_dirs"] == 1, s                   # 只有 K1 有两个译文

    p = [x for x in res["problems"] if x["key"] == "K0000001"]
    assert p and p[0]["attached"] == "模板垃圾.docx", p
    assert p[0]["candidates"] == ["合格译文.docx"], p
    r = [x for x in res["relink"] if x["dir"] == "K0000001"]
    assert r and r[0]["new_file"] == "合格译文.docx", r
    assert r[0]["att_item_id"], r
    x = [y for y in res["extra_relink"] if y["dir"] == "K0000003"]
    assert x and x[0]["old_file"] == "不存在的文件.docx", x
    assert x[0]["new_file"] == "合格译文.docx", x

    g = {(y["dir"], y["file"]) for y in res["garbage"]}
    assert ("K0000001", "模板垃圾.docx") in g, g
    assert ("K0000002", "模板垃圾.docx") in g, g
    assert ("K0000001", "合格译文.docx") not in g, g
    ref = {(y["dir"], y["file"]) for y in res["garbage"] if y["attached"]}
    assert ("K0000002", "模板垃圾.docx") in ref, ref
    assert ("K0000001", "模板垃圾.docx") in ref, ref
    free = {(y["dir"], y["file"]) for y in res["garbage"] if not y["attached"]}
    assert free == set(), free

    o = {(y["dir"], y["file"]) for y in res["optimize"]}
    assert ("K0000004", "合格译文.docx") in o, o
    assert ("K0000003", "合格译文.docx") in o, o
    assert ("K0000001", "合格译文.docx") in o, o
    print("  问题条目 / 补挂 / 垃圾 / 待优化  全部命中 PASS")
    return res


def check_outputs(res, outdir):
    paths = dq.write_outputs(res, outdir, with_md5=True)
    for k in ("report", "problems_csv", "audit_json", "manifest"):
        assert os.path.exists(paths[k]), (k, paths[k])
    md = open(paths["report"], encoding="utf-8").read()
    assert "Zotero 译文质量审计报告" in md and "K0000001" in md, md[:300]
    man = json.load(open(paths["manifest"], encoding="utf-8"))
    assert len(man) == len(res["garbage"]) and man[0]["md5"], man[:1]
    print("  报告 / CSV / 清单    产出并校验 PASS")
    return paths


def check_snapshot_no_wal():
    """复制库副本时缺 -wal 也能工作（只读降级路径）。"""
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "z.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t (a INT)")
        con.commit()
        con.close()
        tmp, copy = dq.snapshot_db(str(db))
        try:
            assert os.path.exists(copy)
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)
    print("  库副本（无 WAL）     PASS")


def check_cli(storage, dbfile, work):
    """`manage_zotero_storage.py quality` 子命令的冒烟测试（覆盖 CLI 接线）。"""
    import subprocess
    cli = str(HERE.parent / "scripts" / "manage_zotero_storage.py")
    r = subprocess.run(
        [sys.executable, "-X", "utf8", cli, "quality",
         "--storage", str(storage), "--sqlite", str(dbfile), "--work", str(work)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    assert "problems=1" in out, out[-500:]
    assert r.returncode == 1, "有问题条目时应返回 1，实际 %d\n%s" % (r.returncode, out)
    rep = Path(work) / "quality" / "quality_report.md"
    assert rep.exists(), rep
    # --dry-run 的改挂预览不应写库
    r2 = subprocess.run(
        [sys.executable, "-X", "utf8", cli, "quality-relink", "--dry-run",
         "--storage", str(storage), "--sqlite", str(dbfile), "--work", str(work)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r2.returncode == 0 and "dry-run" in (r2.stdout or ""), r2.stdout
    print("  CLI 子命令（quality / relink --dry-run）PASS")


def main():
    root = Path(tempfile.mkdtemp(prefix="qtest_"))
    try:
        storage, dbfile = build_fixture(root)
        os.environ["FIXTURE_GOOD"] = str(storage / "K0000004" / "合格译文.docx")
        os.environ["FIXTURE_BAD"] = str(storage / "K0000002" / "模板垃圾.docx")
        print("=" * 72)
        print("译文质量审计回归测试（fixture %s）" % root)
        print("=" * 72)
        check_verdicts()
        res = check_scan(storage, dbfile)
        check_outputs(res, root / "out")
        check_snapshot_no_wal()
        check_cli(storage, dbfile, root / "cliwork")
        print("=" * 72)
        print("PASS：全部通过")
        return 0
    finally:
        import shutil as _sh
        _sh.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
