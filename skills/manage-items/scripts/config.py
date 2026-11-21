# -*- coding: utf-8 -*-
"""路径与命名规则配置。

优先级：环境变量 > config.json > 默认值。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULTS = {
    "zotero_data_dir": r"E:\Zotero",
    # 命名模板，可用占位符：{author} {year} {title_en} {title_zh} {ext}
    "pdf_title_prefix": "[pdf]",
    "docx_title_prefix": "[docx]",
    "pdf_filename": "{author}等 - {year} - {title_en}.pdf",
    "docx_filename": "{author}等 - {year} - {title_zh}.docx",
    "max_filename_len": 120,
    "unknown_author": "佚名",
    "unknown_year": "n.d.",
}

ENV_MAP = {
    "zotero_data_dir": "ZOTERO_DATA_DIR",
    "pdf_title_prefix": "ZOTERO_PDF_PREFIX",
    "docx_title_prefix": "ZOTERO_DOCX_PREFIX",
    "pdf_filename": "ZOTERO_PDF_PATTERN",
    "docx_filename": "ZOTERO_DOCX_PATTERN",
}


def _load_json():
    p = os.path.join(ROOT, "config.json")
    if not os.path.exists(p):
        p = os.path.join(ROOT, "config.example.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load():
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _load_json().items() if v not in (None, "")})
    for key, env in ENV_MAP.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    data = cfg["zotero_data_dir"].replace("\\", "/").rstrip("/")
    cfg["zotero_data_dir"] = data
    cfg["storage_dir"] = data + "/storage"
    cfg["sqlite_path"] = data + "/zotero.sqlite"
    return cfg


cfg = load()


def ensure_utf8_stdio():
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
