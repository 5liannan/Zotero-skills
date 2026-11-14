# -*- coding: utf-8 -*-
"""parts 静态检查（check_parts.py）的回归测试。

跑法：
    python tests/test_parts_lint.py

只用标准库，不需要 pymupdf / pandoc / Word。

覆盖的坑（都真实发生过）：
  1. 未知块类型只打 warning，构建时静默跳过 —— 必须被 lint 拦成 error
  2. `**58**` 在 para 里原样印出星号 —— 已踩两次
  3. figure 指向不存在的图 / caption 为空 —— Word 里变成孤图
  4. 式号重复、parts 编号断号 —— 交叉引用会指错
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "translate-import" / "scripts"))

import check_parts  # noqa: E402


def _run(parts_dir):
    """跑 lint 的 --json 模式，返回 (退出码, 结果字典)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_parts.main([parts_dir, "--json"])
    return rc, json.loads(buf.getvalue())


def _write(tmp, name, blocks):
    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
        json.dump({"blocks": blocks}, f, ensure_ascii=False)


def test_clean_parts_pass():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [
            {"type": "heading", "level": 1, "text": "标题"},
            {"type": "para", "text": "正常段落。"},
            {"type": "formula", "latex": "$$E=mc^2$$", "no": "1"},
        ])
        rc, res = _run(tmp)
        assert rc == 0, res
        assert res["ok"] is True
        assert not res["errors"]


def test_unknown_block_type_is_error():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [{"type": "table_fig", "file": "x.png", "caption": "图 1　x"}])
        rc, res = _run(tmp)
        assert rc == 1
        assert any("E2" in e and "table_fig" in e for e in res["errors"]), res["errors"]
        # 应给出近似建议，避免只骂人不给方向
        assert any("table" in e for e in res["errors"])


def test_markdown_bold_is_error():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [{"type": "para", "text": "Physica **58**, 165 (1973)."}])
        rc, res = _run(tmp)
        assert rc == 1
        assert any("E7" in e for e in res["errors"]), res["errors"]


def test_missing_figure_and_empty_caption():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [{"type": "figure", "file": "nope.png", "caption": ""}])
        rc, res = _run(tmp)
        assert rc == 1
        msgs = " ".join(res["errors"])
        assert "E4" in msgs and "E5" in msgs, res["errors"]


def test_duplicate_equation_number_warns():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [
            {"type": "formula", "latex": "$$a$$", "no": "3"},
            {"type": "formula", "latex": "$$b$$", "no": "3"},
        ])
        rc, res = _run(tmp)
        assert rc == 0, res["errors"]
        assert any("W1" in w for w in res["warnings"]), res["warnings"]


def test_gap_in_part_numbering_warns():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "01.json", [{"type": "para", "text": "a"}])
        _write(tmp, "03.json", [{"type": "para", "text": "b"}])
        rc, res = _run(tmp)
        assert any("W2" in w for w in res["warnings"]), res["warnings"]


def main():
    cases = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in cases:
        fn()
        print("ok  %s" % fn.__name__)
    print("全部 %d 项通过" % len(cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
