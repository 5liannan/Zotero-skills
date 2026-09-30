# -*- coding: utf-8 -*-
"""一键：诊断 → 抽取转 OMML → 重建排版 → 校验。带自动备份。

用法：
    python run_polish.py <file.docx> [--title "..."] [--pandoc PATH] \\
        [--workdir DIR] [--dry-run] [--no-backup] [--keep-backup-name SUFFIX]

流程（全程不改源文件，最后一步才写回）：
    1. diagnose 源文件            → 记录优化前基线
    2. extract_formulas.py        → formulas.json（含 OMML）
    3. optimize.py                → optimized.docx
    4. diagnose optimized.docx    → 断言通过
    5. verify_word.py（可选）     → Word 确认 OMaths.Count
    6. 备份源文件 → 覆盖写入

安全：第 6 步前若任一步失败，源文件保持原样。
备份用 shutil.copy2，并校验 字节数 + md5。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, desc):
    print("\n" + "=" * 58)
    print(">>> " + desc)
    print("    " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    print("=" * 58)
    p = subprocess.run(cmd)
    if p.returncode != 0:
        print("[ERR] 步骤失败：%s (exit %d)" % (desc, p.returncode))
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", help="待优化的译文 DOCX（原地覆盖）")
    ap.add_argument("--title", default="", help="页眉标题")
    ap.add_argument("--pandoc", default="pandoc")
    ap.add_argument("--python", default=sys.executable, help="Python 解释器")
    ap.add_argument("--workdir", default=None, help="工作目录（默认 <docx同级>/_polish_work）")
    ap.add_argument("--dry-run", action="store_true", help="不写回源文件")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-word-check", action="store_true", help="跳过 Word COM 校验")
    ap.add_argument("--backup-suffix", default=time.strftime("bak_%Y%m%d"))
    a = ap.parse_args()

    src = os.path.abspath(a.docx)
    if not os.path.exists(src):
        print("[ERR] 文件不存在:", src)
        return 2

    work = a.workdir or os.path.join(os.path.dirname(src), "_polish_work")
    os.makedirs(work, exist_ok=True)
    formulas_json = os.path.join(work, "formulas.json")
    opt_docx = os.path.join(work, "optimized.docx")

    py = a.python
    ex, op, dg, vw = (os.path.join(HERE, n) for n in
                      ("extract_formulas.py", "optimize.py",
                       "diagnose.py", "verify_word.py"))

    # 1) 基线
    run([py, dg, src], "诊断：优化前基线")

    # 2) 抽取 + 转 OMML
    cmd = [py, ex, src, formulas_json]
    if a.pandoc:
        cmd += ["--pandoc", a.pandoc]
    if not run(cmd, "抽取 LaTeX → OMML"):
        return 1

    # 3) 重建
    cmd = [py, op, src, opt_docx, formulas_json]
    if a.title:
        cmd += ["--title", a.title]
    if not run(cmd, "重建排版 → optimized.docx"):
        return 1

    # 4) 校验
    if not run([py, dg, opt_docx], "诊断：优化后验收"):
        print("\n[WARN] 验收未通过，源文件未改动。请检查:", opt_docx)
        return 1

    # 5) Word 权威校验
    if not a.no_word_check:
        import json
        recs = json.load(open(formulas_json, encoding="utf-8"))
        expect = sum(1 for r in recs if r["kind"] == "display") + \
                 sum(len(r.get("latex_list", [])) for r in recs if r["kind"] == "inline")
        run([py, vw, opt_docx, "--expect-omath", str(expect)], "Word 权威校验")

    # 6) 备份 + 写回
    if a.dry_run:
        print("\n[dry-run] 未写回源文件。成品在:", opt_docx)
        return 0

    if not a.no_backup:
        bak = src + "." + a.backup_suffix
        if os.path.exists(bak):
            bak = src + "." + a.backup_suffix + "_" + time.strftime("%H%M%S")
        shutil.copy2(src, bak)
        same = (os.path.getsize(bak) == os.path.getsize(src) and md5(bak) == md5(src))
        print("\n备份:", bak)
        print("  校验 字节+md5:", "一致" if same else "不一致 !!")
        if not same:
            print("[ERR] 备份校验失败，中止写回")
            return 1

    shutil.copy2(opt_docx, src)
    print("\n已写回:", src)
    print("  大小:", os.path.getsize(src), " md5:", md5(src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
