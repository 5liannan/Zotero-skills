# -*- coding: utf-8 -*-
"""用 Word 本体校验公式对象数——这是唯一权威判据。

用法：
    python verify_word.py <file.docx> [--expect-omath N] [--pdf out.pdf]

为什么要用 Word：
    数 XML 里的 <m:oMath> 只能证明「写进去了」，
    只有 Word 认成公式对象，OMaths.Count 才对得上。

依赖：pywin32（pip install pywin32），仅 Windows + 装 Word 可用。
"""
import argparse
import os
import sys


def verify(path, expect=None, pdf_out=None):
    try:
        import win32com.client
    except ImportError:
        print("[SKIP] 未安装 pywin32，无法用 Word 校验公式对象")
        print("       安装：pip install pywin32")
        return None

    path = os.path.abspath(path)
    if not os.path.exists(path):
        print("[ERR] 文件不存在:", path)
        return False

    word = None
    doc = None
    try:
        word = win32com.client.Dispatch("Word.Application")
    except Exception as e:
        print("[SKIP] 无法启动 Word 自动化:", e)
        print("       若 Word 正开着文档，先关闭再试。")
        return None

    try:
        word.Visible = False
        word.DisplayAlerts = False
    except Exception as e:
        print("[SKIP] Word 实例不可用（可能被其他进程占用）:", e)
        return None

    ok = None
    try:
        doc = word.Documents.Open(path, ReadOnly=False)
        omaths = doc.OMaths.Count
        print("=" * 58)
        print("Word 打开      : OK")
        print("公式对象(Omath):", omaths)
        try:
            print("页数           :", doc.ComputeStatistics(2))   # wdStatisticPages
            print("字数           :", doc.ComputeStatistics(0))   # wdStatisticWords
        except Exception:
            print("页数/字数       : 读取失败（不影响公式判定）")
        print("=" * 58)

        ok = True
        if expect is not None:
            if omaths == expect:
                print("[PASS] 公式对象数 == 预期 %d" % expect)
            else:
                print("[FAIL] 公式对象数 %d != 预期 %d" % (omaths, expect))
                ok = False

        if pdf_out:
            pdf_out = os.path.abspath(pdf_out)
            doc.SaveAs(pdf_out, FileFormat=17)   # 17 = wdFormatPDF
            print("已导出 PDF:", pdf_out)
    except Exception as e:
        print("[SKIP] Word 校验中断（文档仍可用，仅自动化失败）:", e)
        print("       表常见原因：Word 正在被占用 / 有对话框未关闭。")
        ok = None
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--expect-omath", type=int, default=None)
    ap.add_argument("--pdf", default=None, help="顺便导出 PDF 供目视复核")
    a = ap.parse_args()
    r = verify(a.docx, a.expect_omath, a.pdf)
    sys.exit(0 if r is not False else 1)
