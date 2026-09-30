# -*- coding: utf-8 -*-
"""翻译流程回归测试 —— 断言「构建产物即终稿」与「坏输入必须被拒绝」。

跑法：
    python tests/test_pipeline.py

不依赖 pytest。每个用例构造一份最小 `parts`，调用 `build_docx.build()` 后断言：
  * 期望失败的用例 —— 抛 SystemExit（或非 0 退出）且**没有产出文件**
  * 期望成功的用例 —— 正常产出，且 `verify_docx.py` 判 `ok=true`

覆盖的失败路径（这些正是历史事故的形态）：
  1. 悬挂引用：正文 [9]，文献列表只有 [1]
  2. 文献列表为空：只剩「（参考文献保留英文原文。）」这类概括说明
  3. 有文献条目但正文一处引用都没有（参考文献被整节丢掉）
  4. 文献编号断号：有 [1][3]、缺 [2]
  5. 未引用条目（默认严格）
  6. 含公式但环境缺 pandoc —— 必须报错，不得降级为纯文本
覆盖的成功路径：
  7. 常规：正文引用 + 完整文献列表，且「图 N 给出了…」这类正文引用句必须被
     恢复成正文样式、真图注必须规范化为「图 N　题注」
  8. 无公式文档在缺 pandoc 环境下仍可构建
  9. `--allow-unused-refs` 放宽未引用条目
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

PY = sys.executable
BASE = None  # 在 main 里建临时目录

# 「图 N 给出了…」这类正文引用句（形似图注、实为正文），不应被排成图注样式
PROSE_REF_RE = re.compile(r"^图\s*\d+\s*(给出|显示|展示|表明|说明)")

HEAD = [
    {"type": "title", "text": "回归测试用例"},
    {"type": "heading", "level": 1, "text": "1 引言"},
]
REF_HEAD = [{"type": "heading", "level": 1, "text": "参考文献"}]


def refs(*nums):
    return [{"type": "para", "noindent": True,
             "text": "[%d] Example, A.: Demo reference number %d, "
                     "J. Demo, 1(1), 1-2, 2024." % (n, n)}
            for n in nums]


# name -> (blocks, expect_fail, needs_no_pandoc, build_kwargs)
CASES = {
    "dangling_cite": (
        HEAD + [{"type": "para", "text": "正文引用了不存在的文献[9]。"}]
        + REF_HEAD + refs(1, 2), True, False, {}),
    "empty_ref_list": (
        HEAD + [{"type": "para", "text": "正文引用了文献[1]。"}]
        + REF_HEAD + [{"type": "para", "noindent": True,
                       "text": "（参考文献保留英文原文。）"}],
        True, False, {}),
    "refs_without_cites": (
        HEAD + [{"type": "para", "text": "正文一处引用标记都没有。"}]
        + REF_HEAD + refs(1, 2), True, False, {}),
    "ref_number_gap": (
        HEAD + [{"type": "para", "text": "引用文献[1]与[3]。"}]
        + REF_HEAD + refs(1, 3), True, False, {}),
    "unused_ref_strict": (
        HEAD + [{"type": "para", "text": "只引用文献[1]。"}]
        + REF_HEAD + refs(1, 2), True, False, {}),
    "pandoc_missing_with_formula": (
        HEAD + [{"type": "formula", "latex": "$$E=mc^2$$", "no": "1"},
                {"type": "para", "text": "式(1)为质能方程[1]。"}]
        + REF_HEAD + refs(1), True, True, {}),
    "ok_basic": (
        HEAD + [{"type": "para", "text": "正文引用文献[1, 2]。"},
                # 形似图注、实为正文引用句 —— 必须被恢复成正文样式
                {"type": "caption", "text": "图 1 给出了系统的基本原理。"},
                {"type": "caption", "text": "图2 系统结构示意图。"}]
        + REF_HEAD + refs(1, 2), False, False, {}),
    "ok_no_formula_no_pandoc": (
        HEAD + [{"type": "para", "text": "无公式文档，引用文献[1]。"}]
        + REF_HEAD + refs(1), False, True, {}),
    "ok_allow_unused": (
        HEAD + [{"type": "para", "text": "只引用文献[1]。"}]
        + REF_HEAD + refs(1, 2), False, False, {"allow_unused_refs": True}),
}


def fresh_build_module(no_pandoc):
    """重新导入 build_docx，必要时把 pandoc 探测结果打成 None。"""
    for m in ("omml", "finalize", "build_docx"):
        sys.modules.pop(m, None)
    import omml
    if no_pandoc:
        omml.find_pandoc = lambda explicit=None: None
    import build_docx
    return build_docx


def run_case(name, spec):
    blocks, expect_fail, no_pandoc, kw = spec
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "01.json"), "w", encoding="utf-8") as f:
        json.dump({"title_cn": name, "blocks": blocks}, f, ensure_ascii=False)
    out = os.path.join(BASE, name + ".docx")
    if os.path.exists(out):
        os.remove(out)

    build_docx = fresh_build_module(no_pandoc)
    err = None
    try:
        build_docx.build(d, out, **kw)
    except SystemExit as e:
        err = str(e)
    except Exception as e:                                   # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, e)

    exists = os.path.exists(out)

    if expect_fail:
        ok = err is not None and not exists
        print("  %-28s %s" % (name, "PASS" if ok else "FAIL"))
        if err:
            print("       拦住原因: %s" % err.replace("\n", " ")[:130])
        if exists:
            print("       !! 竟然还是产出了文件")
        return ok

    ok = err is None and exists
    print("  %-28s %s" % (name, "PASS" if ok else "FAIL"))
    if err:
        print("       !! 意外报错: %s" % str(err)[:150])
        return False
    cmd = [PY, "-X", "utf8", os.path.join(SCRIPTS, "verify_docx.py"), out]
    if kw.get("allow_unused_refs"):
        cmd.append("--allow-unused-refs")
    r = subprocess.run(cmd, capture_output=True, text=True)
    st = json.loads(r.stdout.strip().splitlines()[-1])
    print("       verify ok=%s omath=%s header=%r footer_page=%s xref=%s refs=%s"
          % (st["ok"], st["omath"], (st["header"] or "")[:16], st["footer_page"],
             st["xref"], st["refs"]))
    # 期望成功的用例还必须满足「产物即终稿」的全部规范项
    checks = [st["ok"], st["raw_dollar"] == 0, st["raw_latex"] == 0,
              bool(st["header"]), st["footer_page"], st["xref"] > 0,
              st["bookmarks"] == st["refs"], not st["ref_errors"]]
    if not all(checks):
        print("       !! 终稿规范项未全部满足: %s" % checks)
        return False

    # --- 图注方向性断言 ---------------------------------------------
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    doc = Document(out)
    for x in doc.paragraphs:
        t = "".join(tt.text or "" for tt in x._p.iter(qn("w:t"))).strip()
        if not t.startswith("图"):
            continue
        if PROSE_REF_RE.match(t):
            if x.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                print("       !! 正文引用句仍被排成图注样式: %r" % t[:40])
                return False
        elif re.match(r"^图\s*\d", t) and not re.match(r"^图\s\d+\u3000", t):
            print("       !! 图注未规范化为「图 N　题注」: %r" % t[:40])
            return False
    return True


def main():
    global BASE
    BASE = tempfile.mkdtemp(prefix="tf_test_")
    try:
        print("=" * 70)
        print("翻译流程回归测试（临时目录 %s）" % BASE)
        print("=" * 70)
        results = [run_case(n, s) for n, s in CASES.items()]
        print("=" * 70)
        print("总计 %d 例，通过 %d 例，失败 %d 例"
              % (len(results), sum(results), len(results) - sum(results)))
        return 0 if all(results) else 1
    finally:
        shutil.rmtree(BASE, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
