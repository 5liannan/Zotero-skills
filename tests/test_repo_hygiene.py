# -*- coding: utf-8 -*-
"""仓库卫生回归测试（把已经踩过的坑钉死）。

历史上真实踩到、现在由本测试拦截的问题：

1. **硬编码个人绝对路径** —— `config.example.json` / 示例脚本里写过形如
   `<盘符>:\\Users\\<真人名>\\...` 的路径，别人 clone 下来全部失效，还会误导
   自动化脚本。（文档里的 `<盘符>:\\Users\\<用户>\\...`、`/home/...`
   这类占位符白名单放行。）
2. **UTF-8 BOM** —— `search-import/README.md` 带过 BOM，导致按 `# ` 定位标题的
   脚本匹配失败。
3. **Markdown 相对死链** —— `search-import/README.md` 里 9 条 `translate/...` 链接
   在目录改名后全部失效，文档看起来完整但无处可去。
4. **示例配置文件不是合法 JSON** —— 会被静默忽略，用户以为改了参数其实没生效。

只用标准库，不依赖 Zotero / pandoc / Word。
运行：python tests/test_repo_hygiene.py
"""
import io
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {".git", "__pycache__", ".idea", ".vscode", "node_modules",
             "_polish_work"}
TEXT_EXT = {".py", ".md", ".json", ".yml", ".yaml", ".txt", ".cfg", ".ini"}

# 路径里出现这些，说明是文档占位符而不是真实用户名
PLACEHOLDER_TOKENS = {"you", "yourname", "your_name", "username", "user",
                      "name", "someone", "me", "example", "test", "default",
                      "xxx", "xxxx", "foo", "bar", "alice", "bob"}
WIN_RE = re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]([^\\/]+)")
POSIX_RE = re.compile(r"(?<![\w.])(?:^|[\s\"'=:(])(?:/Users|/home)/([A-Za-z0-9_.-]+)")


def _is_placeholder(seg):
    seg = seg.strip()
    if any(ch in seg for ch in "<>{}%$"):
        return True
    if set(seg) <= {"."} or ".." in seg:      # `...` 是文档里的通配写法
        return True
    return seg.lower() in PLACEHOLDER_TOKENS


def _tracked_files():
    """只检查 git 已跟踪的文件（临时产物不该影响结论）；无 git 时退回遍历。"""
    try:
        import subprocess
        p = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if p.returncode == 0 and p.stdout:
            names = [n for n in p.stdout.decode("utf-8", "replace").split("\0") if n]
            return [os.path.join(REPO, n.replace("/", os.sep)) for n in names]
    except OSError:
        pass
    return None


def iter_text_files():
    tracked = _tracked_files()
    if tracked is not None:
        for p in sorted(tracked):
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in TEXT_EXT:
                yield p
        return
    for root, dirs, files in os.walk(REPO):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(root, fn)


def rel(p):
    return os.path.relpath(p, REPO).replace("\\", "/")


class TestNoBom(unittest.TestCase):
    def test_no_utf8_bom(self):
        bad = []
        for p in iter_text_files():
            with open(p, "rb") as f:
                if f.read(3) == b"\xef\xbb\xbf":
                    bad.append(rel(p))
        self.assertEqual([], bad, "以下文件带 UTF-8 BOM（会破坏标题/解析）：%s" % bad)


class TestNoPersonalPaths(unittest.TestCase):
    def test_no_hardcoded_personal_absolute_paths(self):
        hits = []
        for p in iter_text_files():
            try:
                with io.open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            for m in WIN_RE.finditer(txt):
                if not _is_placeholder(m.group(1)):
                    hits.append("%s: %s" % (rel(p), m.group(0)))
            for m in POSIX_RE.finditer(txt):
                if not _is_placeholder(m.group(1)):
                    hits.append("%s: %s" % (rel(p), m.group(0).strip()))
        self.assertEqual([], hits,
                         "疑似硬编码个人绝对路径（请用 ~ 或占位符）：\n  " +
                         "\n  ".join(hits))


class TestMarkdownLinks(unittest.TestCase):
    LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

    def test_relative_links_resolve(self):
        dead = []
        for p in iter_text_files():
            if not p.endswith(".md"):
                continue
            base = os.path.dirname(p)
            with io.open(p, encoding="utf-8", errors="replace") as f:
                txt = f.read()
            for m in self.LINK_RE.finditer(txt):
                t = m.group(1).strip()
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t) or \
                        t.startswith("mailto:"):
                    continue
                t = t.split("#")[0].strip()
                if t.startswith("<") and t.endswith(">"):
                    t = t[1:-1]
                if not t:
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(base, t))):
                    dead.append("%s -> %s" % (rel(p), m.group(1)))
        self.assertEqual([], dead,
                         "Markdown 相对死链：\n  " + "\n  ".join(dead))


class TestExampleConfigs(unittest.TestCase):
    def test_config_examples_are_valid_json(self):
        bad = []
        for p in iter_text_files():
            if not p.endswith("config.example.json"):
                continue
            try:
                with io.open(p, encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:  # noqa: BLE001
                bad.append("%s: %s" % (rel(p), e))
        self.assertEqual([], bad, "示例配置不是合法 JSON：\n  " + "\n  ".join(bad))

    def test_example_configs_have_no_personal_defaults(self):
        """示例配置里不应出现写死的目录/用户路径。"""
        bad = []
        for p in iter_text_files():
            if not p.endswith("config.example.json"):
                continue
            with io.open(p, encoding="utf-8") as f:
                data = json.load(f)
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    stack.extend(cur.values())
                elif isinstance(cur, list):
                    stack.extend(cur)
                elif isinstance(cur, str):
                    for m in WIN_RE.finditer(cur):
                        if not _is_placeholder(m.group(1)):
                            bad.append("%s: %s" % (rel(p), cur))
        self.assertEqual([], bad, "示例配置含硬编码路径：\n  " + "\n  ".join(bad))


    # 盘符前不能再是字母数字，否则 `http://...` 里的 `p://` 会被误判
    ABS_WIN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])")

    def test_example_configs_have_no_machine_specific_paths(self):
        """示例配置的值里不该出现任何盘符绝对路径（换台机器就失效）。"""
        bad = []
        for p in iter_text_files():
            if not p.endswith("config.example.json"):
                continue
            with io.open(p, encoding="utf-8") as f:
                data = json.load(f)
            stack = [("", data)]
            while stack:
                path, cur = stack.pop()
                if isinstance(cur, dict):
                    for k, v in cur.items():
                        stack.append(("%s.%s" % (path, k), v))
                elif isinstance(cur, list):
                    for i, v in enumerate(cur):
                        stack.append(("%s[%d]" % (path, i), v))
                elif isinstance(cur, str) and not path.split(".")[-1].startswith("_"):
                    if self.ABS_WIN_RE.search(cur):
                        bad.append("%s%s = %s" % (rel(p), path, cur))
        self.assertEqual([], bad, "示例配置值含盘符绝对路径：\n  " + "\n  ".join(bad))


class TestSkillLayout(unittest.TestCase):
    def test_every_skill_has_skill_md(self):
        skills = os.path.join(REPO, "skills")
        if not os.path.isdir(skills):
            self.skipTest("无 skills/ 目录")
        missing = []
        for name in sorted(os.listdir(skills)):
            d = os.path.join(skills, name)
            if os.path.isdir(d) and not os.path.isfile(os.path.join(d, "SKILL.md")):
                missing.append(name)
        self.assertEqual([], missing, "技能缺 SKILL.md：%s" % missing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
