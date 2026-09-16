#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print resolved translate skill paths (for debugging env/config)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate_config import cfg, ensure_utf8_stdio

ensure_utf8_stdio()
print("python executable:", cfg.python)
print("Zotero data dir :", cfg.zotero_data_dir)
print("storage         :", cfg.storage_dir)
print("sqlite          :", cfg.sqlite_path)
print("work_base       :", cfg.work_base)
print("tasks_json      :", cfg.tasks_json)
print("status_json     :", cfg.status_json)
print("results_dir     :", cfg.results_dir)
print("min_chars       :", cfg.min_chars)
print("verify_min_chars:", cfg.verify_min_chars)
