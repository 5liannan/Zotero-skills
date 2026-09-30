# -*- coding: utf-8 -*-
"""终稿规则「两份实现」的一致性守卫。

背景
----
`translate-import/scripts/finalize.py`（构建时正式版）与
`docx-polish/scripts/optimize.py`（事后补救版）是**同一套终稿规则**的两份实现。

为什么不做成一份公共模块？因为 `docx-polish` 会被**单独安装**到
`~/.workbuddy/skills/docx-polish/`（那份里没有 `translate-import`），
跨技能 import 会让已安装的副本直接崩。所以规则只能各存一份 ——
代价就是**会漂移**：改了这边的动词表，那边还是旧的，而且不报错。

本测试把漂移变成 CI 红灯：正则、常量、以及"是否像图注样式"的判定行为，
两边必须逐项相同。改任一侧的规则，就必须同步改另一侧。

运行：python tests/test_rule_parity.py     （需要 python-docx）
"""
import importlib.util
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINALIZE = os.path.join(REPO, "skills", "translate-import", "scripts", "finalize.py")
OPTIMIZE = os.path.join(REPO, "skills", "docx-polish", "scripts", "optimize.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    import docx  # noqa: F401
    fin = _load("_rp_finalize", FINALIZE)
    opt = _load("_rp_optimize", OPTIMIZE)
    HAVE_DOCX = True
    MISSING = ""
except ImportError as e:  # 没有 python-docx 就跳过（CI 的 deps job 里会装）
    fin = opt = None
    HAVE_DOCX = False
    MISSING = str(e)

# 两边都该有、且必须同值的正则
REGEXES = ["CAP_RE", "CAP_VERB_RE", "IMG_MARK_RE", "CAP_HEAD_RE"]
# 两边都该有、且必须同值的常量
CONSTANTS = ["M_NS", "EA_FONT", "LATIN_FONT", "BODY_SIZE", "CAP_MAX_LEN",
             "CAPTION_SIZE", "CAPTION_LINE_SPACING", "CAPTION_SPACE_BEFORE",
             "CAPTION_SPACE_AFTER"]
# 名字不同但含义相同的（finalize 名, optimize 名）
ALIASES = [("INDENT_CHARS", "INDENT_CHARS"),
           ("BODY_LINE_SPACING", "LINE_SPACING")]


@unittest.skipUnless(HAVE_DOCX, "需要 python-docx：%s" % MISSING)
class TestRuleParity(unittest.TestCase):
    def test_both_modules_have_the_rules(self):
        for name in REGEXES + CONSTANTS:
            self.assertTrue(hasattr(fin, name), "finalize.py 缺 %s" % name)
            self.assertTrue(hasattr(opt, name), "optimize.py 缺 %s" % name)

    def test_regexes_are_identical(self):
        for name in REGEXES:
            a = getattr(fin, name)
            b = getattr(opt, name)
            self.assertEqual(a.pattern, b.pattern,
                             "正则 %s 不一致：\n  finalize: %s\n  optimize: %s"
                             % (name, a.pattern, b.pattern))
            self.assertEqual(a.flags, b.flags, "正则 %s 的 flags 不一致" % name)

    def test_constants_are_identical(self):
        for name in CONSTANTS:
            self.assertEqual(getattr(fin, name), getattr(opt, name),
                             "常量 %s 不一致" % name)

    def test_aliased_constants_are_identical(self):
        for fa, oa in ALIASES:
            self.assertTrue(hasattr(fin, fa), "finalize.py 缺 %s" % fa)
            self.assertTrue(hasattr(opt, oa), "optimize.py 缺 %s" % oa)
            self.assertEqual(getattr(fin, fa), getattr(opt, oa),
                             "%s(finalize) != %s(optimize)" % (fa, oa))

    def test_heading_sizes_agree(self):
        """optimize 只管 Heading 1/2，取交集比对即可。"""
        common = set(fin.HEADING_SIZES) & set(opt.HEADING_SIZES)
        self.assertTrue(common, "两份 HEADING_SIZES 没有交集，检查是否改名")
        for k in sorted(common):
            self.assertEqual(fin.HEADING_SIZES[k], opt.HEADING_SIZES[k],
                             "标题字号 %s 不一致" % k)

    # ---------------------------------------------------------------- 行为
    def _paras(self):
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt
        d = Document()
        specs = [
            ("plain", None, None),                              # 普通正文
            ("centered", WD_ALIGN_PARAGRAPH.CENTER, None),      # 居中
            ("small", None, 9.0),                               # 小字号
            ("body", None, 10.5),                               # 正文字号
        ]
        out = []
        for text, align, size in specs:
            p = d.add_paragraph(text)
            if align is not None:
                p.alignment = align
            if size is not None:
                p.runs[0].font.size = Pt(size)
            out.append((text, p))
        return out

    def test_caption_style_detection_agrees(self):
        """「这段是否已被排成图注样式」两边必须给出同样答案。"""
        for name, p in self._paras():
            a = fin._looks_like_caption_style(p, body_size=fin.BODY_SIZE)
            b = opt._looks_like_caption_style(p, fin.BODY_SIZE)
            self.assertEqual(a, b, "段落 %s 的判定不一致：finalize=%s optimize=%s"
                                   % (name, a, b))

    def test_caption_style_detection_semantics(self):
        """顺便钉住语义：居中/小字号算图注样式，普通正文不算。"""
        paras = dict(self._paras())
        self.assertFalse(fin._looks_like_caption_style(paras["plain"]))
        self.assertFalse(fin._looks_like_caption_style(paras["body"]))
        self.assertTrue(fin._looks_like_caption_style(paras["centered"]))
        self.assertTrue(fin._looks_like_caption_style(paras["small"]))

    def test_caption_regex_agrees_on_samples(self):
        """图注识别在典型样本上两边同判。"""
        samples = [
            "图 1　散射光谱",
            "图1: 实验装置",
            "图 2 给出了不同温度下的结果",       # 正文引用句
            "如图 3 所示",                        # 不是图注段
            "图片 p07_02.png",                    # 图片源文件残留标记
        ]
        for s in samples:
            fa = fin.CAP_RE.match(s.strip())
            fb = opt.CAP_RE.match(s.strip())
            self.assertEqual(bool(fa), bool(fb), "CAP_RE 对 %r 判定不一致" % s)
            self.assertEqual(bool(fin.IMG_MARK_RE.match(s)),
                             bool(opt.IMG_MARK_RE.match(s)),
                             "IMG_MARK_RE 对 %r 判定不一致" % s)

    def test_normalize_caption_uses_shared_rules(self):
        """图注规范化应命中共享规则（顺带钉住反向修复的判定）。"""
        self.assertEqual("图 1\u3000散射光谱", fin.normalize_caption("图 1：散射光谱"))
        self.assertIsNone(fin.normalize_caption("图 2 给出了不同温度下的结果"))
        self.assertTrue(fin._is_caption_shaped_prose("图 2 给出了不同温度下的结果"))
        self.assertFalse(fin._is_caption_shaped_prose("图 1　散射光谱"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
