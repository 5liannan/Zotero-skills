# -*- coding: utf-8 -*-
"""构建前给 parts/*.json 做静态检查（lint），把「静默出问题」挡在构建之前。

Usage:
    python check_parts.py parts/ [--max-caption 0] [--json] [--quiet]

检查项（error 会让退出码为 1）：
    E1  文件不是合法 JSON / 顶层不是 {"blocks": [...]}
    E2  块类型不在白名单（build_docx 对未知类型只打 warning，很容易被后续日志淹没）
    E3  文本类块缺 text（空段落会让正文出现莫名空行）
    E4  figure/image 的 file 不存在（相对 parts 目录的父目录解析，与 build_docx 一致）
    E5  figure/image 的 caption 为空
    E6  formula/equation 的 latex 与 text 都为空
    E7  文本里含 `**`（**build_docx 的 para 块不支持 markdown 粗体**，会原样印出星号）
    E8  --max-caption>0 时，图注超长
警告（不影响退出码）：
    W1  `no`（式号）重复
    W2  parts 文件编号不连续
    W3  参考文献块不像 `[n] …`（提醒可能在用别的编号法）

为什么要有 E7
-------------
`para` 块走的是纯文本 run，markdown 的 `**粗体**` 不会被解析。写参考文献时
本能地想给卷号加粗，结果 PDF 里原样印出「**58**」——已经踩过两次，且都是在
导出 PDF 逐页核对时才发现。静态检查比肉眼可靠。
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                     # pragma: no cover
    pass

ALLOWED = {"title", "subtitle", "heading", "para", "caption",
           "image", "figure", "formula", "equation", "table"}
TEXT_BLOCKS = {"title", "subtitle", "heading", "para", "caption"}


def check_file(path, parts_dir, max_caption):
    errs, warns, stats = [], [], {"blocks": 0, "chars": 0, "figures": 0, "formulas": 0}
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return ["E1 %s：JSON 解析失败 —— %s" % (name, e)], [], stats
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        return ["E1 %s：顶层必须是 {\"blocks\": [...]}" % name], [], stats

    base = os.path.dirname(os.path.abspath(parts_dir))     # 与 build_docx 的 _resolve 一致
    seen_no = {}
    for i, b in enumerate(data["blocks"]):
        where = "%s[%d]" % (name, i)
        if not isinstance(b, dict):
            errs.append("E2 %s：块不是对象" % where)
            continue
        bt = b.get("type")
        stats["blocks"] += 1
        if bt not in ALLOWED:
            near = difflib.get_close_matches(str(bt), ALLOWED, n=2)
            hint = ("，是不是 %s？" % " / ".join(near)) if near else ""
            errs.append("E2 %s：未知块类型 %r%s（build 只会 warning，随后静默跳过）"
                        % (where, bt, hint))
            continue

        txt = b.get("text") or ""
        if isinstance(txt, str):
            stats["chars"] += len(txt)
        if bt in TEXT_BLOCKS and not str(txt).strip():
            errs.append("E3 %s：%s 块内容为空" % (where, bt))
        if "**" in str(txt):
            errs.append("E7 %s：文本含 `**`（para 不支持 markdown 粗体，会原样印出）：%s"
                        % (where, str(txt)[:40]))
        if bt == "para" and str(txt).lstrip().startswith("["):
            if not txt.lstrip().startswith("[") or "]" not in txt[:8]:
                warns.append("W3 %s：疑似文献条目但编号格式不是 `[n] …`" % where)

        if bt in ("figure", "image"):
            stats["figures"] += 1
            f = b.get("file") or ""
            if not f:
                errs.append("E4 %s：figure 缺 file" % where)
            else:
                full = f if os.path.isabs(f) else os.path.join(base, f)
                if not os.path.exists(full):
                    errs.append("E4 %s：图片不存在 %s" % (where, full))
            cap = str(b.get("caption") or "")
            if not cap.strip():
                errs.append("E5 %s：figure 缺 caption（Word 里会变成孤图）" % where)
            if max_caption and len(cap) > max_caption:
                errs.append("E8 %s：图注 %d 字符，超过上限 %d" % (where, len(cap), max_caption))

        if bt in ("formula", "equation"):
            stats["formulas"] += 1
            if not str(b.get("latex") or b.get("text") or "").strip():
                errs.append("E6 %s：formula 的 latex 为空" % where)

        no = b.get("no") or b.get("number")
        if no:
            key = str(no)
            if key in seen_no:
                warns.append("W1 %s：式号 (%s) 与 %s 重复" % (where, key, seen_no[key]))
            seen_no[key] = where
    return errs, warns, stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="检查 parts/*.json：块类型、图片存在性、粗体星号、式号重复等",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python check_parts.py parts/            # 只看 error\n"
               "  python check_parts.py parts/ --json     # 机器可读\n")
    ap.add_argument("parts", help="parts 目录（含 01.json, 02.json …）")
    ap.add_argument("--max-caption", type=int, default=0,
                    help="图注字符上限（默认 0 = 不检查；确认目标排版有要求时再开）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--quiet", action="store_true", help="只输出统计与 error")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.parts, "*.json")))
    if not files:
        print("ERROR: %s 下没有 .json" % args.parts, file=sys.stderr)
        return 2

    all_err, all_warn = [], []
    total = {"blocks": 0, "chars": 0, "figures": 0, "formulas": 0, "files": len(files)}
    for f in files:
        e, w, st = check_file(f, args.parts, args.max_caption)
        all_err += e
        all_warn += w
        for k in ("blocks", "chars", "figures", "formulas"):
            total[k] += st[k]

    # 编号连续性（按文件名里的数字）
    nums = []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem.isdigit():
            nums.append(int(stem))
    if nums and nums != list(range(nums[0], nums[0] + len(nums))):
        all_warn.append("W2 文件编号不连续：%s" % ", ".join("%02d" % n for n in sorted(nums)))

    if args.json:
        print(json.dumps({"ok": not all_err, "totals": total,
                          "errors": all_err, "warnings": all_warn},
                         ensure_ascii=False, indent=1))
    else:
        for e in all_err:
            print("ERROR " + e)
        if not args.quiet:
            for w in all_warn:
                print("WARN  " + w)
        print("---- %d 个 parts / %d 块 / %d 字 / %d 图 / %d 式 | error %d / warn %d"
              % (total["files"], total["blocks"], total["chars"], total["figures"],
                 total["formulas"], len(all_err), len(all_warn)))
    return 0 if not all_err else 1


if __name__ == "__main__":
    raise SystemExit(main())
