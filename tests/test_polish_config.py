# -*- coding: utf-8 -*-
"""docx-polish：配置文件加载与排版参数转发的回归测试。

为什么需要它
------------
历史上 `skills/docx-polish/config.example.json` 存在但**没有任何代码读取它**，
README 里写的"复制成 config.json 改参数"其实是无效操作。本测试锁死两件事：

1. 配置确实被加载，且优先级为
   `--config` > `$DOCX_POLISH_CONFIG` > `<技能根>/config.json` > `config.example.json`
2. 配置里的排版项确实被转发给 `optimize.py`（而不是只改了 --title）

只用标准库，且用桩替换子进程，因此不需要 pandoc / Word / python-docx。
运行：python tests/test_polish_config.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "skills", "docx-polish", "scripts")
SKILL_ROOT = os.path.dirname(SCRIPTS)

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import run_polish  # noqa: E402


class _Proc:
    returncode = 0


def _stub_run(calls, formulas=("[{\"kind\": \"display\"}]")):
    """替换 subprocess.run：记录命令，并伪造 extract_formulas 的产物。"""

    def _run(cmd, **kw):
        calls.append(list(cmd))
        joined = " ".join(cmd)
        if "extract_formulas.py" in joined and len(cmd) >= 4:
            with open(cmd[3], "w", encoding="utf-8") as f:
                f.write(formulas)
        return _Proc()

    return _run


class _Capture:
    """跑 run_polish.main()，收集命令与屏幕输出。"""

    def __init__(self, argv, env=None, formulas='[{"kind": "display"}]'):
        self.argv = argv
        self.env = env
        self.calls = []
        self.out = ""
        self.rc = None
        self._formulas = formulas

    def __enter__(self):
        self._old_run = run_polish.subprocess.run
        self._old_env = os.environ.get("DOCX_POLISH_CONFIG")
        run_polish.subprocess.run = _stub_run(self.calls, self._formulas)
        if self.env is None:
            os.environ.pop("DOCX_POLISH_CONFIG", None)
        else:
            os.environ["DOCX_POLISH_CONFIG"] = self.env
        buf = io.StringIO()
        self._old_stdout = sys.stdout
        sys.stdout = buf
        self._buf = buf
        return self

    def __exit__(self, *exc):
        sys.stdout = self._old_stdout
        run_polish.subprocess.run = self._old_run
        if self._old_env is None:
            os.environ.pop("DOCX_POLISH_CONFIG", None)
        else:
            os.environ["DOCX_POLISH_CONFIG"] = self._old_env
        self.out = self._buf.getvalue()
        return False

    def run(self):
        old_argv = sys.argv
        sys.argv = ["run_polish.py"] + self.argv
        try:
            self.rc = run_polish.main()
        finally:
            sys.argv = old_argv
        return self.rc

    def cmd_of(self, needle):
        for c in self.calls:
            if any(needle in x for x in c):
                return " ".join(c)
        return ""


class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="polish_cfg_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def test_example_config_exists_and_is_json(self):
        """技能根必须有可解析的示例配置（否则文档里的用法是空的）。"""
        p = os.path.join(SKILL_ROOT, "config.example.json")
        self.assertTrue(os.path.isfile(p), "缺少 config.example.json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_explicit_config_wins(self):
        p = self._write("custom.json", {"title": "T1"})
        cfg, path = run_polish.load_config(p)
        self.assertEqual(cfg["title"], "T1")
        self.assertEqual(os.path.abspath(path), os.path.abspath(p))

    def test_env_config_used_when_no_explicit(self):
        p = self._write("env.json", {"title": "T2"})
        os.environ["DOCX_POLISH_CONFIG"] = p
        self.addCleanup(os.environ.pop, "DOCX_POLISH_CONFIG", None)
        cfg, path = run_polish.load_config("")
        self.assertEqual(cfg["title"], "T2")

    def test_falls_back_to_skill_root(self):
        os.environ.pop("DOCX_POLISH_CONFIG", None)
        cfg, path = run_polish.load_config("")
        self.assertTrue(path, "未回落到任何配置文件")
        self.assertIn("docx-polish", path.replace("\\", "/"))

    def test_broken_json_is_ignored_not_fatal(self):
        p = os.path.join(self.tmp, "broken.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        cfg, path = run_polish.load_config(p)  # 不应抛异常
        self.assertTrue(isinstance(cfg, dict))
        # 坏文件被跳过，应继续回落到技能根
        self.assertNotEqual(os.path.abspath(path or ""), os.path.abspath(p))

    def test_non_dict_json_is_ignored(self):
        p = self._write("list.json", [1, 2, 3])
        cfg, _ = run_polish.load_config(p)
        self.assertTrue(isinstance(cfg, dict))

    def test_underscore_keys_are_comments(self):
        """`_` 开头的键是说明文字，不应被当排版项转发。"""
        for k in run_polish._LAYOUT_OPTS:
            self.assertFalse(k[0].startswith("_"))
        p = os.path.join(SKILL_ROOT, "config.example.json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        layout_keys = {k for k, _, _ in run_polish._LAYOUT_OPTS}
        unknown = [k for k in data
                   if not k.startswith("_") and k not in layout_keys
                   and k not in ("title", "pandoc", "no_word_check",
                                 "backup_suffix", "header", "page_number")]
        self.assertEqual([], unknown, "示例配置里有代码不认识的键：%s" % unknown)


class TestForwarding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="polish_fwd_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.docx = os.path.join(self.tmp, "fake.docx")
        with open(self.docx, "wb") as f:
            f.write(b"PK\x03\x04")

    def _config(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def test_layout_options_forwarded(self):
        cfg = self._config("c.json", {
            "ea_font": "黑体", "latin_font": "Arial", "body_size": 12.0,
            "header_size": 10.0, "indent_chars": 0.0, "line_spacing": 1.25,
            "margin": 3.0, "top_margin": 3.2, "center_first": 2,
            "title": "自定义标题", "header": False, "page_number": False,
            "no_word_check": True,
        })
        with _Capture([self.docx, "--config", cfg, "--dry-run"]) as c:
            c.run()
        opt = c.cmd_of("optimize.py")
        self.assertTrue(opt, "未调用 optimize.py")
        for frag in ("--ea-font 黑体", "--latin-font Arial", "--body-size 12.0",
                     "--header-size 10.0", "--line-spacing 1.25",
                     "--margin 3.0", "--top-margin 3.2", "--center-first 2",
                     "--no-header", "--no-page-number", "--title 自定义标题"):
            self.assertIn(frag, opt, "缺少转发: %s" % frag)
        # indent_chars=0 是合法值，不能被当成"空"丢掉
        self.assertIn("--indent-chars 0.0", opt)

    def test_no_word_check_skips_verify_word(self):
        cfg = self._config("c.json", {"no_word_check": True})
        with _Capture([self.docx, "--config", cfg, "--dry-run"]) as c:
            c.run()
        self.assertNotIn("verify_word.py", " ".join(" ".join(x) for x in c.calls))

    def test_word_check_runs_by_default(self):
        """默认不能静默跳过 Word 校验（历史上有过取反的 bug）。"""
        cfg = self._config("c.json", {"no_word_check": False})
        with _Capture([self.docx, "--config", cfg, "--dry-run"],
                      formulas='[{"kind": "display"}]') as c:
            c.run()
        self.assertIn("verify_word.py", " ".join(" ".join(x) for x in c.calls))

    def test_header_and_page_number_on_by_default(self):
        cfg = self._config("c.json", {})
        with _Capture([self.docx, "--config", cfg, "--dry-run"]) as c:
            c.run()
        opt = c.cmd_of("optimize.py")
        self.assertNotIn("--no-header", opt)
        self.assertNotIn("--no-page-number", opt)

    def test_bad_type_is_ignored_with_warning(self):
        cfg = self._config("c.json", {"body_size": "很大", "ea_font": "宋体"})
        with _Capture([self.docx, "--config", cfg, "--dry-run"]) as c:
            c.run()
        opt = c.cmd_of("optimize.py")
        self.assertIn("--ea-font 宋体", opt)
        self.assertNotIn("--body-size", opt)
        self.assertIn("WARN", c.out)

    def test_dry_run_does_not_overwrite_source(self):
        before = b"PK\x03\x04"
        cfg = self._config("c.json", {"no_word_check": True})
        with _Capture([self.docx, "--config", cfg, "--dry-run"]) as c:
            c.run()
        with open(self.docx, "rb") as f:
            self.assertEqual(before, f.read(), "dry-run 竟然改动了源文件")
        self.assertIn("dry-run", c.out)

    def test_backup_suffix_placeholder_is_resolved(self):
        """示例里的 bak_YYYYMMDD 是占位写法，不能原样当后缀用。"""
        import time
        want = time.strftime("bak_%Y%m%d")
        self.assertEqual(want, run_polish.resolve_backup_suffix("bak_YYYYMMDD"))
        self.assertEqual(want, run_polish.resolve_backup_suffix(""))
        self.assertEqual(want, run_polish.resolve_backup_suffix(None))
        self.assertEqual("mine", run_polish.resolve_backup_suffix("mine"))
        self.assertEqual(time.strftime("bak_%Y"),
                         run_polish.resolve_backup_suffix("bak_%Y"))

    def test_missing_file_reports_error(self):
        p = os.path.join(self.tmp, "nope.docx")
        with _Capture([p, "--dry-run"]) as c:
            rc = c.run()
        self.assertEqual(2, rc)
        self.assertIn("文件不存在", c.out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
