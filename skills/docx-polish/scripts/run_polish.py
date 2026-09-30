# -*- coding: utf-8 -*-
"""一键：诊断 → 抽取转 OMML → 重建排版 → 校验。带自动备份。

用法：
    python run_polish.py <file.docx> [--title "..."] [--pandoc PATH] \\
        [--workdir DIR] [--dry-run] [--no-backup] [--backup-suffix SUFFIX]

流程（全程不改源文件，最后一步才写回）：
    1. diagnose 源文件            → 记录优化前基线
    2. extract_formulas.py        → formulas.json（含 OMML）
    3. optimize.py                → optimized.docx
    4. diagnose optimized.docx    → 断言通过
    5. verify_word.py（可选）     → Word 确认 OMaths.Count
    6. 备份源文件 → 覆盖写入

安全：第 6 步前若任一步失败，源文件保持原样。
备份用 shutil.copy2，并校验 字节数 + md5。

配置
----
按 `--config` > `$DOCX_POLISH_CONFIG` > `<技能根>/config.json` >
`<技能根>/config.example.json` 的顺序取第一个存在的文件。
**命令行参数优先级高于配置文件。** 配置项见 `config.example.json`
（`_` 开头的键是说明文字，会被忽略）。排版类配置（字体/字号/缩进/行距/边距/
标题区段数）会原样转发给 `optimize.py`。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

# optimize.py 支持、且允许由配置文件覆盖的排版参数：配置键 -> CLI 旗标
_LAYOUT_OPTS = [
    ("ea_font", "--ea-font", str),
    ("latin_font", "--latin-font", str),
    ("body_size", "--body-size", float),
    ("header_size", "--header-size", float),
    ("indent_chars", "--indent-chars", float),
    ("line_spacing", "--line-spacing", float),
    ("margin", "--margin", float),
    ("top_margin", "--top-margin", float),
    ("center_first", "--center-first", int),
]


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(explicit=None):
    """取第一个存在的配置文件；返回 (配置dict, 路径或None)。"""
    cands = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("DOCX_POLISH_CONFIG", "").strip()
    if env:
        cands.append(env)
    cands.append(os.path.join(SKILL_ROOT, "config.json"))
    cands.append(os.path.join(SKILL_ROOT, "config.example.json"))
    for p in cands:
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:  # noqa: BLE001
                print("[WARN] 配置文件解析失败，已忽略：%s（%s）" % (p, e))
                continue
            if isinstance(data, dict):
                return data, p
    return {}, None


def cfg_get(cfg, key, default):
    v = cfg.get(key, default)
    return default if v in (None, "") else v


def resolve_backup_suffix(v):
    """把配置里的备份后缀解析成可用字符串。

    示例配置写的是占位写法 `bak_YYYYMMDD`，直接当字面量用会得到
    `xxx.bak_YYYYMMDD` 这种假日期备份名，所以这里要认出来并替换；
    含 `%` 的值视为 strftime 格式串，交给用户自定义。
    """
    if not v:
        return time.strftime("bak_%Y%m%d")
    if "%" in v:
        try:
            return time.strftime(v)
        except ValueError:
            return v
    if v.strip().upper() == "BAK_YYYYMMDD":
        return time.strftime("bak_%Y%m%d")
    return v


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
    # 先只解析 --config，好让配置文件给其余参数提供默认值
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    known, _ = pre.parse_known_args()
    cfg, cfg_path = load_config(known.config)

    ap = argparse.ArgumentParser()
    ap.add_argument("docx", help="待优化的译文 DOCX（原地覆盖）")
    ap.add_argument("--config", default="", help="配置文件路径（默认自动查找）")
    ap.add_argument("--title", default=str(cfg_get(cfg, "title", "")),
                    help="页眉标题")
    ap.add_argument("--pandoc", default=str(cfg_get(cfg, "pandoc", "pandoc")))
    ap.add_argument("--python", default=sys.executable, help="Python 解释器")
    ap.add_argument("--workdir", default=None,
                    help="工作目录（默认 <docx同级>/_polish_work）")
    ap.add_argument("--dry-run", action="store_true", help="不写回源文件")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-word-check", action="store_true",
                    default=bool(cfg_get(cfg, "no_word_check", False)),
                    help="跳过 Word COM 校验")
    ap.add_argument("--backup-suffix",
                    default=resolve_backup_suffix(
                        cfg_get(cfg, "backup_suffix", "")))
    a = ap.parse_args()

    src = os.path.abspath(a.docx)
    if not os.path.exists(src):
        print("[ERR] 文件不存在:", src)
        return 2

    if cfg_path:
        print("配置:", cfg_path)
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

    # 3) 重建（排版参数按配置转发给 optimize.py）
    cmd = [py, op, src, opt_docx, formulas_json]
    if a.title:
        cmd += ["--title", a.title]
    if not cfg_get(cfg, "header", True):
        cmd += ["--no-header"]
    if not cfg_get(cfg, "page_number", True):
        cmd += ["--no-page-number"]
    for key, flag, cast in _LAYOUT_OPTS:
        if cfg.get(key) not in (None, ""):
            try:
                cmd += [flag, str(cast(cfg[key]))]
            except (TypeError, ValueError):
                print("[WARN] 配置项 %s=%r 类型不对，已忽略" % (key, cfg[key]))
    if not run(cmd, "重建排版 → optimized.docx"):
        return 1

    # 4) 校验
    if not run([py, dg, opt_docx], "诊断：优化后验收"):
        print("\n[WARN] 验收未通过，源文件未改动。请检查:", opt_docx)
        return 1

    # 5) Word 权威校验
    if not a.no_word_check:
        with open(formulas_json, encoding="utf-8") as f:
            recs = json.load(f)
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
