---
name: zotero-translate
description: 将 Zotero 库中的英文 PDF 学术论文翻译为规范中文 DOCX 并挂回对应条目。适用于布里渊/瑞利散射/光纤传感等文献库的批量中文化。触发词：翻译 Zotero PDF、中文译文入库、PDF to DOCX 中文、批量翻译文献。
---

# Zotero 文献中文翻译 Skill

## 目标

用户要求把 Zotero 里的英文论文变成中文 DOCX，并在 Zotero 条目下能看到译文附件时使用本技能。

## 前置检查

1. 确认 Python 3.12+，已安装 `pymupdf`、`python-docx`
2. Windows：使用 `python -X utf8`，设置 `PYTHONUTF8=1`
3. 若需写 `zotero.sqlite`：**确认 Zotero 已完全退出**
4. 确认路径：
   - Zotero 数据目录（含 `storage/` 与 `zotero.sqlite`）
   - 任务表 `zotero_tasks.json`（可选，用于批量）
   - 台账 `status_oc.json`（可选）

## 工作流

### 单篇

1. `extract_pdf_text.py <pdf> <workdir>/images > extract.json`
2. 读 `fulltext.txt`，写出 `parts/01.json`（中文标题 + 摘要/引言/方法/结果/结论）
3. `build_docx.py <workdir>/parts <out.docx>`
4. `verify_docx.py <out.docx>`，要求 `ok=true` 且 `chars>=3000`（全文精译）
5. 若用户要求入库：运行 `register_zotero_docx.py`（先退出 Zotero）

### 批量

1. 维护 `zotero_tasks.json`：`itemID / mode / ztitle / pdf / docx / folder`
2. 运行 `full_v3_pipeline.py [N]` 分批处理
3. `update_status.py` 刷新台账（若用户环境有）
4. 全量审计：每个任务的 `docx` 路径存在且校验通过

## 译文结构（B 档全文精译）

- 摘要
- 1 引言
- 2 方法与装置
- 3 结果与讨论
- 4 结论
- 5 应用与展望
- 参考文献（保留英文）

公式用 `$...$`；术语首现可括注英文；图表标题译中文，坐标轴/图例数值保持原样。

## Zotero 挂接要点

- 原生规则：一个附件一个 storage 目录
- `create_new`：译文与 PDF 可先同目录生成，登记时复制到新 key 目录
- `fill_existing`：覆盖 `docx` 字段路径（可能与 PDF 不同目录）
- 登记后需有 `itemAttachments.path = storage:<文件名>` 与 title 字段

## 禁止事项

- Zotero 运行时写 `zotero.sqlite`
- 删除用户数据前不备份
- 把受版权 PDF 上传到公网

## 完成标准

- [ ] DOCX 校验通过且篇幅达标
- [ ] 中文标题正确
- [ ] 台账 `status_oc.json` 已更新
- [ ] （若入库）Zotero 条目下可见译文附件

## 路径配置

优先使用环境变量 `ZOTERO_DATA_DIR` / `ZOTERO_WORK_BASE` / `ZOTERO_PYTHON`，或 `translate/config.json`。
用 `python scripts/print_paths.py` 确认解析结果后再跑写库脚本。

本 skill 位于 `skills/translate-import/`。
