# -*- coding: utf-8 -*-
"""Migrate a Zotero data directory from any path to any path.

Generic: works for C:\\..., E:\\..., /home/..., /mnt/nas/..., UNC, etc.

Safety:
- Refuses if Zotero process is detected (unless --force)
- Copies entire data dir before changing prefs
- Backs up prefs.js before edit
- Never deletes the source; verify in Zotero then delete manually

Usage:
  python migrate_zotero_datadir.py --src "<old>" --dst "<new>" --dry-run
  python migrate_zotero_datadir.py --src "<old>" --dst "<new>"
  python migrate_zotero_datadir.py --src "<old>" --dst "<new>" --prefs "<prefs.js>"
"""
from __future__ import annotations

import argparse
import os
import platform
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
    """Best-effort check for a running Zotero desktop process."""
    system = platform.system().lower()
    try:
        if system == "windows":
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq zotero.exe"],
                stderr=subprocess.DEVNULL,
            )
            return b"zotero.exe" in out.lower()
        if system == "darwin":
            out = subprocess.check_output(["pgrep", "-if", "zotero"], stderr=subprocess.DEVNULL)
            return bool(out.strip())
        # linux
        out = subprocess.check_output(["pgrep", "-if", "zotero"], stderr=subprocess.DEVNULL)
        return bool(out.strip())
    except Exception:
        return False


def default_data_dir() -> Path:
    home = Path.home()
    system = platform.system().lower()
    if system == "windows":
        return home / "Zotero"
    return home / "Zotero"


def candidate_prefs_paths() -> list[Path]:
    home = Path.home()
    system = platform.system().lower()
    candidates: list[Path] = []
    if system == "windows":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        root = Path(appdata) / "Zotero" / "Zotero" / "Profiles"
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/prefs.js"), key=lambda p: p.stat().st_mtime, reverse=True))
    elif system == "darwin":
        root = home / "Library" / "Application Support" / "Zotero" / "Profiles"
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/prefs.js"), key=lambda p: p.stat().st_mtime, reverse=True))
    else:
        for root in (
            home / ".zotero" / "zotero",
            home / ".config" / "zotero",
            Path("/var/home") / os.environ.get("USER", "") / ".zotero" / "zotero",
        ):
            if root.is_dir():
                candidates.extend(sorted(root.glob("*/prefs.js"), key=lambda p: p.stat().st_mtime, reverse=True))
                candidates.extend(sorted(root.glob("*/*/prefs.js"), key=lambda p: p.stat().st_mtime, reverse=True))
    return candidates


def find_default_prefs() -> Path | None:
    prefs = candidate_prefs_paths()
    return prefs[0] if prefs else None


def read_data_dir_from_prefs(prefs_path: Path) -> str | None:
    try:
        text = prefs_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r'user_pref\("extensions\.zotero\.dataDir"\s*,\s*"([^"]*)"\s*\)', text)
    if not m:
        return None
    raw = m.group(1)
    # unescape JSON-style backslashes for display
    return raw.replace("\\\\", "\\")


def pref_escape(path: Path) -> str:
    """Escape a filesystem path for use inside a prefs.js string literal."""
    s = str(path)
    if os.name == "nt" or "\\" in s:
        return s.replace("\\", "\\\\")
    return s


def update_prefs(prefs_path: Path, data_dir: Path, dry_run: bool) -> None:
    text = prefs_path.read_text(encoding="utf-8", errors="replace")
    backup = prefs_path.with_name(
        prefs_path.name + ".bak_before_migration_" + time.strftime("%Y%m%d_%H%M%S")
    )
    if not dry_run:
        shutil.copy2(prefs_path, backup)
        print("prefs backup:", backup)

    new_line = 'user_pref("extensions.zotero.dataDir", "%s");' % pref_escape(data_dir)
    pat = re.compile(r'user_pref\("extensions\.zotero\.dataDir"\s*,\s*"[^"]*"\s*\);')

    if pat.search(text):
        text2 = pat.sub(lambda _m: new_line, text, count=1)
        print("replaced existing dataDir")
    else:
        if not text.endswith("\n"):
            text += "\n"
        text2 = text + new_line + "\n"
        print("appended dataDir")

    if 'user_pref("extensions.zotero.useDataDir"' not in text2:
        text2 += 'user_pref("extensions.zotero.useDataDir", true);\n'

    if dry_run:
        print("dry-run: would write", new_line)
        return
    prefs_path.write_text(text2, encoding="utf-8", newline="\n")
    print("wrote prefs:", prefs_path)
    print("dataDir ->", str(data_dir))


def copy_tree(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        print("dry-run: copy", src, "->", dst)
        return
    if dst.exists():
        raise SystemExit("destination already exists: %s" % dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        cmd = ["robocopy", str(src), str(dst), "/E", "/COPY:DAT", "/R:2", "/W:2", "/NFL", "/NDL", "/NP"]
        print("running:", " ".join(cmd))
        proc = subprocess.run(cmd)
        if proc.returncode >= 8:
            raise SystemExit("robocopy failed rc=%s" % proc.returncode)
        print("robocopy rc=", proc.returncode)
    else:
        # copytree for POSIX; preserve metadata best-effort
        shutil.copytree(src, dst, symlinks=True)
        print("copied tree")


def folder_size(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def verify(src: Path, dst: Path) -> None:
    for name in ("zotero.sqlite", "storage"):
        if not (dst / name).exists():
            raise SystemExit("missing after copy: %s" % (dst / name))
    ss, ds = folder_size(src), folder_size(dst)
    print("src bytes=%s dst bytes=%s" % (ss, ds))
    if ss > 0 and ds < ss * 0.95:
        raise SystemExit("destination much smaller than source; abort")


def normalize_path(p: str) -> Path:
    return Path(p).expanduser()


def main() -> int:
    ensure_utf8()
    ap = argparse.ArgumentParser(
        description="Migrate Zotero data directory from any path to any path"
    )
    ap.add_argument("--src", required=False, help="current Zotero data dir (default: auto-detect)")
    ap.add_argument("--dst", required=True, help="new Zotero data dir")
    ap.add_argument("--prefs", default="", help="path to profile prefs.js (default: auto-detect)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="allow run even if Zotero process is detected")
    args = ap.parse_args()

    # resolve src
    if args.src:
        src = normalize_path(args.src)
    else:
        # try prefs first
        prefs_guess = Path(args.prefs).expanduser() if args.prefs else find_default_prefs()
        detected = read_data_dir_from_prefs(prefs_guess) if prefs_guess and prefs_guess.is_file() else None
        if detected:
            src = Path(detected)
            print("auto-detected dataDir from prefs:", src)
        else:
            src = default_data_dir()
            print("using default data dir guess:", src)

    dst = normalize_path(args.dst)
    prefs = Path(args.prefs).expanduser() if args.prefs else find_default_prefs()

    print("platform:", platform.platform())
    print("src :", src)
    print("dst :", dst)
    print("prefs:", prefs if prefs else "(not found)")

    if not src.is_dir():
        print("source not found:", src)
        print("Hint: pass --src explicitly, or set it in prefs before migrating.")
        return 1
    if not (src / "zotero.sqlite").exists():
        print("source missing zotero.sqlite:", src)
        print("Is this really the Zotero data directory?")
        return 1
    if not prefs or not prefs.is_file():
        print("prefs.js not found; pass --prefs explicitly")
        return 1

    if str(src.resolve()) == str(dst.resolve()):
        print("src and dst are the same path")
        return 1

    if zotero_running() and not args.force:
        print("Zotero appears to be running. Fully quit Zotero, then retry (or --force).")
        return 2

    copy_tree(src, dst, args.dry_run)
    if not args.dry_run:
        verify(src, dst)
    update_prefs(prefs, dst, args.dry_run)

    print("\nNext:")
    print("1) Open Zotero and verify items + PDF/DOCX attachments")
    print("2) After verification, delete source manually:")
    if os.name == "nt":
        print("   Remove-Item '%s' -Recurse -Force" % src)
    else:
        print("   rm -rf '%s'" % src)
    print("3) Update local tooling if needed: ZOTERO_DATA_DIR=%s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
