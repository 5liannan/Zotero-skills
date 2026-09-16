# -*- coding: utf-8 -*-
"""Migrate Zotero data directory to a new path (Windows-oriented).

Safety:
- Refuses if Zotero process is running (unless --force)
- Copies entire data dir before changing prefs
- Backs up prefs.js before edit
- Does NOT delete the source; user must verify then delete manually

Usage:
  python migrate_zotero_datadir.py --src "C:/Users/Administrator/Zotero" --dst "E:/Zotero"
  python migrate_zotero_datadir.py --src ... --dst ... --prefs "C:/Users/.../prefs.js"
  python migrate_zotero_datadir.py --src ... --dst ... --dry-run

After migration: open Zotero, verify items/attachments, then delete --src yourself.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def ensure_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def zotero_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq zotero.exe"],
            stderr=subprocess.DEVNULL,
        )
        return b"zotero.exe" in out.lower()
    except Exception:
        return False


def find_default_prefs() -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    root = Path(appdata) / "Zotero" / "Zotero" / "Profiles"
    if not root.is_dir():
        return None
    prefs = list(root.glob("*/prefs.js"))
    # prefer default-ish
    prefs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return prefs[0] if prefs else None


def win_path_for_pref(p: Path) -> str:
    # prefs.js uses JSON-like escaped backslashes
    return str(p).replace("\\", "\\\\")


def update_prefs(prefs_path: Path, data_dir: Path, dry_run: bool) -> None:
    text = prefs_path.read_text(encoding="utf-8", errors="replace")
    backup = prefs_path.with_name(
        prefs_path.name + ".bak_before_migration_" + time.strftime("%Y%m%d_%H%M%S")
    )
    if not dry_run:
        shutil.copy2(prefs_path, backup)
        print("prefs backup:", backup)

    new_line = 'user_pref("extensions.zotero.dataDir", "%s");' % win_path_for_pref(data_dir)
    pat = re.compile(r'user_pref\("extensions\.zotero\.dataDir"\s*,\s*"[^"]*"\s*\);')

    if pat.search(text):
        text2 = pat.sub(new_line, text, count=1)
        print("replaced existing dataDir")
    else:
        if not text.endswith("\n"):
            text += "\n"
        text2 = text + new_line + "\n"
        print("appended dataDir")

    # ensure useDataDir true
    if 'user_pref("extensions.zotero.useDataDir"' not in text2:
        text2 += 'user_pref("extensions.zotero.useDataDir", true);\n'

    if dry_run:
        print("dry-run: would write", new_line)
        return
    prefs_path.write_text(text2, encoding="utf-8", newline="\n")
    print("wrote prefs:", prefs_path)
    print("dataDir ->", data_dir)


def copy_tree(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        print("dry-run: copy", src, "->", dst)
        return
    if dst.exists():
        raise SystemExit("destination already exists: %s" % dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # prefer robocopy on Windows for speed/metadata
    if os.name == "nt":
        cmd = [
            "robocopy",
            str(src),
            str(dst),
            "/E",
            "/COPY:DAT",
            "/R:2",
            "/W:2",
            "/NFL",
            "/NDL",
            "/NP",
        ]
        print("running:", " ".join(cmd))
        proc = subprocess.run(cmd)
        # robocopy: 0-7 success
        if proc.returncode >= 8:
            raise SystemExit("robocopy failed rc=%s" % proc.returncode)
        print("robocopy rc=", proc.returncode)
    else:
        shutil.copytree(src, dst)
        print("copied tree")


def verify(src: Path, dst: Path) -> None:
    for name in ("zotero.sqlite", "storage"):
        if not (dst / name).exists():
            raise SystemExit("missing after copy: %s" % (dst / name))

    def folder_size(p: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    ss, ds = folder_size(src), folder_size(dst)
    print("src bytes=%s dst bytes=%s" % (ss, ds))
    if ds < ss * 0.95:
        raise SystemExit("destination much smaller than source; abort")


def main() -> int:
    ensure_utf8()
    ap = argparse.ArgumentParser(description="Migrate Zotero data directory")
    ap.add_argument("--src", required=True, help="current Zotero data dir")
    ap.add_argument("--dst", required=True, help="new Zotero data dir")
    ap.add_argument("--prefs", default="", help="path to profile prefs.js")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="allow running while zotero.exe exists")
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    dst = Path(args.dst).expanduser()

    if not src.is_dir():
        print("source not found:", src)
        return 1
    if not (src / "zotero.sqlite").exists():
        print("source missing zotero.sqlite:", src)
        return 1

    if zotero_running() and not args.force:
        print("zotero.exe is running. Fully quit Zotero, then retry (or --force).")
        return 2

    prefs = Path(args.prefs).expanduser() if args.prefs else find_default_prefs()
    if not prefs or not prefs.is_file():
        print("prefs.js not found; pass --prefs explicitly")
        return 1

    print("src :", src)
    print("dst :", dst)
    print("prefs:", prefs)

    copy_tree(src, dst, args.dry_run)
    if not args.dry_run:
        verify(src, dst)
    update_prefs(prefs, dst, args.dry_run)

    print("\nNext:")
    print("1) Open Zotero and verify items + PDF/DOCX attachments")
    print("2) After verification, delete source manually:")
    print("   Remove-Item '%s' -Recurse -Force" % src)
    print("3) Update skill env: ZOTERO_DATA_DIR=%s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
