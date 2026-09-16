# Zotero 数据目录通用迁移指南

将 Zotero **数据目录**（库文件 + PDF/DOCX 附件）从任意当前路径迁到任意新路径，迁移后条目与附件仍可正常打开。

适用于：换盘、换分区、外接硬盘、NAS、移动到用户目录外等任意 **源路径 → 目标路径**。

> **不要只剪切文件夹。** Zotero 读的是配置里的数据目录路径（`dataDir`），路径不改会出现“库空了 / 附件打不开”。

## 原理

| 组件 | 典型位置 | 迁移时 |
|---|---|---|
| **数据目录**（`zotero.sqlite`、`storage/` 等） | 由 `extensions.zotero.dataDir` 决定；未配置时为系统默认 | **整体复制**，再改 pref |
| **应用配置 / Profile** | 见下表 | **不移动**，只改其中的 dataDir |
| **程序本体** | 安装目录（如 `D:\Zotero`、`/opt/zotero`） | 不动 |

存储附件（`storage/<key>/...`）相对数据目录解析；数据目录整体搬迁 + 改 `dataDir` 后一般仍有效。  
**链接文件**（Linked File，绝对路径指向库外）若指向旧路径，迁移后可能失效，需单独重链。

### 默认数据目录与 Profile 位置（常见）

| 平台 | 数据目录（未自定义时） | Profile |
|---|---|---|
| Windows | `C:\Users\<用户>\Zotero` | `%APPDATA%\Zotero\Zotero\Profiles\<id>\prefs.js` |
| macOS | `~/Zotero` | `~/Library/Application Support/Zotero/Profiles/<id>/prefs.js` |
| Linux | `~/Zotero` | `~/.zotero/zotero/<id>/prefs.js` 或 `~/snap/zotero/...` |

以本机 `prefs.js` 里实际的 `extensions.zotero.dataDir` 为准。

## 通用步骤

### 0. 准备

1. 记下**源目录** `<SRC>` 与**目标目录** `<DST>`（任意绝对路径）  
2. 目标盘剩余空间 ≥ 源目录大小 × 1.1  
3. **完全退出 Zotero**（含托盘/后台进程）  
4. 确认当前 dataDir：

```powershell
# Windows 示例
Select-String -Path "$env:APPDATA\Zotero\Zotero\Profiles\*\prefs.js" -Pattern "extensions.zotero.dataDir"
```

```bash
# Linux / macOS 示例
grep -R "extensions.zotero.dataDir" ~/.zotero ~/.config/zotero 2>/dev/null
```

若无该 pref，表示使用上表中的默认数据目录。

### 1. 使用脚本（推荐）

仓库内脚本支持任意 `--src` / `--dst`，并可自动查找默认 `prefs.js`。

**先演练：**

```bash
python scripts/migrate_zotero_datadir.py \
  --src "<SRC>" \
  --dst "<DST>" \
  --dry-run
```

**再执行：**

```bash
python scripts/migrate_zotero_datadir.py \
  --src "<SRC>" \
  --dst "<DST>"
# 可选：--prefs "<prefs.js 完整路径>"
# 可选：--force  （仅在确认无 zotero 进程时）
```

脚本会：

1. 检测 Zotero 是否在运行（Windows 查 `zotero.exe`；其他平台尽力检测）  
2. 完整复制数据目录（Windows 优先 `robocopy`）  
3. 校验 `zotero.sqlite`、`storage` 存在，且体积与源大致相当  
4. **备份** `prefs.js` 后写入新的 `dataDir`  

脚本**不会**自动删除 `<SRC>`。

### 2. 手工步骤（无脚本时）

1. 完整复制 `<SRC>` → `<DST>`（含隐藏文件）  
2. 备份 Profile 下的 `prefs.js`  
3. 修改或追加（Windows 路径在 pref 字符串里需写成 `\\`）：

```javascript
user_pref("extensions.zotero.dataDir", "<DST 的 JSON 转义路径>");
user_pref("extensions.zotero.useDataDir", true);
```

4. 保存后启动 Zotero  

### 3. 验证

- 条目列表完整  
- PDF / DOCX 能打开  
- 分类、标签、笔记正常  

**验证通过前不要删除 `<SRC>`。**

### 4. 验证通过后删除源目录

```powershell
Remove-Item "<SRC>" -Recurse -Force   # Windows
```

```bash
rm -rf "<SRC>"                         # Linux / macOS
```

## 回滚

1. 退出 Zotero  
2. 恢复 `prefs.js` 备份，或把 `dataDir` 改回 `<SRC>`  
3. 重新打开 Zotero  

## 本仓库脚本适配

迁移后若本地仍有硬编码旧路径，应改为环境变量或配置：

```bash
export ZOTERO_DATA_DIR="<DST>"
# Windows PowerShell:
# $env:ZOTERO_DATA_DIR = "<DST>"
```

或编辑 `skills/translate-import/config.json` 中的 `zotero_data_dir`。  
用 `python scripts/print_paths.py` 确认解析结果。

## 示例（与盘符无关）

```bash
# 外接盘 → 内置盘
python scripts/migrate_zotero_datadir.py \
  --src "D:/Portable/Zotero" \
  --dst "C:/Users/you/Zotero" --dry-run

# 用户目录 → NAS / 共享盘（路径按实际填写）
python scripts/migrate_zotero_datadir.py \
  --src "/home/you/Zotero" \
  --dst "/mnt/nas/zotero-data" --dry-run

# 指定非默认 profile
python scripts/migrate_zotero_datadir.py \
  --src "E:/Old/Zotero" \
  --dst "F:/Data/Zotero" \
  --prefs "C:/Users/you/AppData/Roaming/Zotero/Zotero/Profiles/xxxx.default/prefs.js"
```

## 检查清单

- [ ] 已退出 Zotero  
- [ ] `<SRC>` 为当前真实数据目录  
- [ ] `<DST>` 空间足够且可写  
- [ ] 已 `--dry-run` 或手工核对路径  
- [ ] `prefs.js` 已备份  
- [ ] `dataDir` 已指向 `<DST>`  
- [ ] 打开 Zotero，条目与附件正常  
- [ ] （可选）删除 `<SRC>`  
- [ ] 脚本 `ZOTERO_DATA_DIR` / config 已更新  

## 注意

- 不要在 Zotero 运行时改 `prefs.js` 或删旧库  
- 不要只拷 `storage` 而不拷 `zotero.sqlite`  
- 云同步不替代本地附件备份；迁移前后建议各保留一份完整目录  
- 从网络盘迁回本地盘流程相同，仅 `--src` / `--dst` 对调  
