# -*- coding: utf-8 -*-
"""Shared path/config loader for Zotero translate skill.

Resolution order for each key:
1. Environment variable (ZOTERO_<KEY upper>)
2. Field in config JSON (config.json next to this file, or TRANSLATE_CONFIG)
3. Built-in default

Usage:
    from translate_config import cfg
    print(cfg.zotero_data_dir)
    print(cfg["python"])
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent

_DEFAULTS: Dict[str, Any] = {
    "zotero_data_dir": str(Path.home() / "Zotero"),
    "python": sys.executable or "python",
    "work_base": str(Path.home() / ".openclaw-autoclaw" / "workspace" / "zcode-continuation"),
    "tasks_json": "",
    "status_json": "",
    "docx_content_type": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


# Map config keys to environment variable names.
# Convention: strip leading "zotero_" then prefix ZOTERO_ (avoid ZOTERO_ZOTERO_*).
_ENV_MAP = {
    "zotero_data_dir": "ZOTERO_DATA_DIR",
    "python": "ZOTERO_PYTHON",
    "work_base": "ZOTERO_WORK_BASE",
    "tasks_json": "ZOTERO_TASKS_JSON",
    "status_json": "ZOTERO_STATUS_JSON",
    "docx_content_type": "ZOTERO_DOCX_CONTENT_TYPE",
}


def _env_key(key: str) -> str:
    if key in _ENV_MAP:
        return _ENV_MAP[key]
    return "ZOTERO_" + key.upper()


def _load_file_config() -> Dict[str, Any]:
    path = os.environ.get("TRANSLATE_CONFIG", "").strip()
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.append(_HERE / "config.json")
    candidates.append(_HERE / "config.example.json")
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    return {}


class _Cfg:
    def __init__(self) -> None:
        self._file = _load_file_config()

    def get(self, key: str, default: Any = None) -> Any:
        env_v = os.environ.get(_env_key(key))
        if env_v is not None and env_v != "":
            return env_v
        if key in self._file and self._file[key] not in (None, ""):
            return self._file[key]
        if key in _DEFAULTS and _DEFAULTS[key] not in (None, ""):
            return _DEFAULTS[key]
        return default

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def path(self, key: str) -> Path:
        return Path(str(self.get(key))).expanduser()

    # convenience properties
    @property
    def zotero_data_dir(self) -> Path:
        return self.path("zotero_data_dir")

    @property
    def storage_dir(self) -> Path:
        return self.zotero_data_dir / "storage"

    @property
    def sqlite_path(self) -> Path:
        return self.zotero_data_dir / "zotero.sqlite"

    @property
    def python(self) -> str:
        return str(self.get("python"))

    @property
    def work_base(self) -> Path:
        return self.path("work_base")

    @property
    def tasks_json(self) -> Path:
        v = str(self.get("tasks_json") or "")
        if v:
            return Path(v)
        return self.zotero_data_dir / "zotero_tasks.json"

    @property
    def status_json(self) -> Path:
        v = str(self.get("status_json") or "")
        if v:
            return Path(v)
        return self.work_base / "status_oc.json"

    @property
    def results_dir(self) -> Path:
        return self.work_base / "results"

    @property
    def work_item_dir(self) -> Path:
        return self.work_base / "work"

    @property
    def docx_content_type(self) -> str:
        return str(self.get("docx_content_type"))


cfg = _Cfg()


def ensure_utf8_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    ensure_utf8_stdio()
    print(json.dumps({
        "zotero_data_dir": str(cfg.zotero_data_dir),
        "storage": str(cfg.storage_dir),
        "sqlite": str(cfg.sqlite_path),
        "python": cfg.python,
        "work_base": str(cfg.work_base),
        "tasks_json": str(cfg.tasks_json),
        "status_json": str(cfg.status_json),
    }, ensure_ascii=False, indent=2))
