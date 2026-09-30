# -*- coding: utf-8 -*-
"""LaTeX → Word 原生公式对象（OMML）转换。

**这是译文 DOCX 公式正确渲染的关键。** 不依赖 latex2mathml / sympy / MathType，
借助 pandoc 把 LaTeX 转成 docx 再取回 <m:oMath> 元素。

用法：
    from omml import LatexToOmml, pandoc_available

    conv = LatexToOmml()                 # 自动探测 pandoc
    if conv.ok:
        els = conv.convert(r"E=mc^2", display=False)   # -> list[Element] 或 None
        for el in els:
            para._element.append(copy.deepcopy(el))

设计要点：
  * **失败返回 None，由调用方硬失败**：pandoc 缺失或转换失败时返回 None，
    调用方（build_docx.py）据此中止构建、不产出纯文本 LaTeX 的半成品。
    本模块自身不抛异常中断，把「是否容忍失败」的决策交给上层。
  * **结果缓存**：同一公式（论文里重复出现的符号很常见）只调一次 pandoc。
  * **临时文件必清理**：放在 tempfile 目录，finally 里删掉。
"""
import os
import re
import shutil
import subprocess
import tempfile

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# LaTeX 定界符：$$...$$ 或 $...$
DISPLAY_RE = re.compile(r"^\s*\${1,2}\s*(.+?)\s*\${1,2}\s*$", re.S)
INLINE_RE = re.compile(r"\$([^$]+?)\$")
# 末尾式号 (2.1) / (12)
NUM_RE = re.compile(r"\((\d+(?:\.\d+)?)\)\s*$")
# 式号前的排版指令与标点
TAIL_CMD_RE = re.compile(r"(\\quad|\\qquad|\\;|\\,|\\!|,|\.|\s)+$")

# Windows 上 pandoc 常见位置（Anaconda 自带）
COMMON_PANDOC = [
    "pandoc",
    # common install locations probed at runtime
    r"C:\ProgramData\Anaconda3\Library\bin\pandoc.exe",
    os.path.expanduser(r"~\Anaconda3\Library\bin\pandoc.exe"),
    "/usr/local/bin/pandoc",
    "/opt/homebrew/bin/pandoc",
]


def find_pandoc(explicit=None):
    """定位 pandoc。返回可执行路径，找不到返回 None。"""
    cands = ([explicit] if explicit else []) + COMMON_PANDOC
    for c in cands:
        if not c:
            continue
        p = shutil.which(c) if os.path.basename(c) == c else (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def pandoc_available(explicit=None):
    return find_pandoc(explicit) is not None


def split_num(latex):
    """摘出末尾式号，返回 (纯公式, 式号或 None)。

    **必须在送 pandoc 之前剥离**：否则式号会被排进 OMML，
    之后右对齐再渲染一次，同一式号出现两遍——「(2.1) …… (2.1)」。
    """
    m = NUM_RE.search(latex)
    if not m:
        return latex, None
    pure = TAIL_CMD_RE.sub("", latex[:m.start()])
    return pure.strip(), m.group(1)


# 开头的 $ / $$ 与结尾的 $ / $$
LEAD_DELIM_RE = re.compile(r"^\s*\${1,2}\s*")
TAIL_DELIM_RE = re.compile(r"\s*\${1,2}\s*$")


def strip_delims(latex):
    """剥掉 LaTeX 两端可能自带的 `$` / `$$` 定界符。

    parts/*.json 里的 `latex` 字段常写成 `$$...$$`，
    直接送 pandoc 会变成 `$$$$...$$$$` 而解析失败。
    """
    t = (latex or "").strip()
    if not t:
        return t
    t = LEAD_DELIM_RE.sub("", t)
    t = TAIL_DELIM_RE.sub("", t)
    return t.strip()


def clean_latex(latex):
    """一步到位：剥定界符 → 剥式号。返回 (纯公式, 式号或 None)。"""
    pure, num = split_num(strip_delims(latex))
    return pure, num


class LatexToOmml(object):
    """LaTeX → OMML 转换器（带缓存；失败返回 None 由调用方决定）。"""

    def __init__(self, pandoc=None, timeout=60, verbose=False):
        self.pandoc = find_pandoc(pandoc)
        self.timeout = timeout
        self.verbose = verbose
        self._cache = {}          # (latex, display) -> list[Element] | None
        self._fail = {}           # 记录失败原因，便于一次性汇报
        self.stats = {"hit": 0, "miss": 0, "fail": 0}

    @property
    def ok(self):
        return self.pandoc is not None

    def _run_pandoc(self, latex, display):
        """实际调用 pandoc，返回 OMML 元素列表或 None。"""
        delim = "$$" if display else "$"
        tmpdir = tempfile.mkdtemp(prefix="omml_")
        md = os.path.join(tmpdir, "t.md")
        dx = os.path.join(tmpdir, "t.docx")
        try:
            with open(md, "w", encoding="utf-8") as f:
                f.write("%s%s%s\n" % (delim, latex, delim))
            p = subprocess.run([self.pandoc, md, "-o", dx],
                               capture_output=True, timeout=self.timeout)
            if p.returncode != 0:
                self._fail[latex] = p.stderr.decode("utf-8", "replace")[:200]
                return None
            # 延迟导入，避免无 docx 时也报错
            from docx import Document
            from lxml import etree
            for para in Document(dx).paragraphs:
                xml = para._element.xml
                if "oMath" in xml:
                    root = etree.fromstring(xml.encode("utf-8"))
                    els = root.findall(".//{%s}oMath" % M_NS)
                    if els:
                        return els
            self._fail[latex] = "no oMath produced"
            return None
        except subprocess.TimeoutExpired:
            self._fail[latex] = "pandoc timeout"
            return None
        except Exception as e:
            self._fail[latex] = "%s: %s" % (type(e).__name__, e)
            return None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def convert(self, latex, display=False):
        """转成 OMML 元素列表。

        返回 list[Element]，失败返回 None（调用方据此中止构建）。
        **注意：调用方必须 copy.deepcopy 后再插入，否则元素被多处引用会丢失。**
        """
        if not self.ok:
            return None
        latex = (latex or "").strip()
        if not latex:
            return None
        key = (latex, bool(display))
        if key in self._cache:
            self.stats["hit"] += 1
            return self._cache[key]
        self.stats["miss"] += 1
        els = self._run_pandoc(latex, display)
        if els is None:
            self.stats["fail"] += 1
            if self.verbose:
                print("  [omml-fail] %r -> %s" % (latex[:60], self._fail.get(latex)))
        self._cache[key] = els
        return els

    def failures(self):
        """返回失败清单 [(latex, reason)]，供构建结束时汇总汇报。"""
        return sorted(self._fail.items())

    def report(self):
        if not self.ok:
            return "pandoc 不可用：含公式时构建将中止"
        s = self.stats
        return "OMML: 缓存命中 %d / 转换 %d / 失败 %d" % (s["hit"], s["miss"], s["fail"])


# ---------------- 段落级辅助（供 build_docx.py 直接用） ----------------

def segment_inline(text):
    """把一段含 $...$ 的文本切成 [("text", s) | ("math", s), ...]。

    无公式时返回 [("text", text)]，调用方可据此走快速路径。
    """
    if "$" not in text:
        return [("text", text)]
    segs = []
    cursor = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > cursor:
            segs.append(("text", text[cursor:m.start()]))
        segs.append(("math", m.group(1).strip()))
        cursor = m.end()
    if cursor < len(text):
        segs.append(("text", text[cursor:]))
    return segs


def classify(text):
    """判断整段文本是行间公式还是含行内公式的正文。

    返回 ("display", latex) | ("inline", text) | None
    """
    t = (text or "").strip()
    if not t or "$" not in t:
        return None
    m = DISPLAY_RE.match(t)
    if m:
        return "display", m.group(1).strip()
    return "inline", t
