# Zotero 数据目录完美迁移（Windows）

把 Zotero 数据目录从默认位置（如 `C:\Users\Administrator\Zotero`）迁到其他盘（如 `E:\Zotero`），并保证条目、PDF、DOCX 附件仍可正常打开。

> **不要只剪切文件夹。** Zotero 读的是配置里的 `dataDir`，路径不改会“库空了/附件打不开”。

## 适用场景

- C 盘空间不足  
- 想把文献库放到数据盘  
- 本机已完整验证迁移（2026-09，Windows + Zotero 桌面端）

## 原理

| 组件 | 位置 | 迁移时 |
|---|---|---|
| 数据目录（库+附件） | `extensions.zotero.dataDir` 指向的目录 | **整体复制**，再改 pref |
| 应用配置 / Profile | `%APPDATA%\Zotero\Zotero\Profiles\<id>\` | **不移动**，只改 `prefs.js` 中的 dataDir |
| 程序本体 | 如 `D:\Zotero\zotero.exe` | 不动 |

存储的附件（`storage\<key>\...`）相对数据目录解析；数据目录整体搬迁 + 改 `dataDir` 后路径仍然有效。  
**链接的文件**（Linked File，绝对路径指向库外）若写死旧盘符，迁移后可能失效，需单独重链。

## 步骤

### 0. 准备

1. 确认目标盘剩余空间 ≥ 数据目录大小 × 1.1  
2. **完全退出 Zotero**（主窗口 + 托盘）  
3. 记下当前数据目录路径（默认多为 `C:\Users\<用户>\Zotero`）

查看当前配置（示例）：

```powershell
# Profile 下的 prefs.js
Get-ChildItem "$env:APPDATA\Zotero\Zotero\Profiles" -Recurse -Filter prefs.js
Select-String -Path "<prefs.js路径>" -Pattern "extensions.zotero.dataDir"
```

若无 `dataDir` 行，表示使用 Zotero 默认目录。

### 1. 完整复制数据目录

```powershell
$src = "C:\Users\Administrator\Zotero"
$dst = "E:\Zotero"

# 确认 Zotero 未运行
Get-Process -Name zotero -ErrorAction SilentlyContinue

robocopy $src $dst /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NP
# 退出码 0–7 通常表示成功；≥8 为失败
```

校验：

```powershell
Test-Path "E:\Zotero\zotero.sqlite"
Test-Path "E:\Zotero\storage"
# 体积对比
```

### 2. 修改 dataDir

1. 备份 `prefs.js`  
2. 将 `extensions.zotero.dataDir` 改为新路径（注意 JSON 字符串转义）：

```powershell
$prefs = "$env:APPDATA\Zotero\Zotero\Profiles\<profile>\prefs.js"
Copy-Item $prefs "$prefs.bak_before_migration"

$newLine = 'user_pref("extensions.zotero.dataDir", "E:\\Zotero");'
# 有则替换，无则追加；并确保 extensions.zotero.useDataDir 为 true
```

### 3. 打开 Zotero 验证

- 条目列表是否完整  
- PDF / DOCX 能否打开  
- 分类、标签是否正常  

**验证通过前不要删除旧目录。**

### 4. 验证通过后删除旧目录

```powershell
Remove-Item "C:\Users\Administrator\Zotero" -Recurse -Force
```

## 回滚

1. 退出 Zotero  
2. 把 `prefs.js` 中 `dataDir` 改回旧路径，或恢复 `*.bak_before_migration`  
3. 重新打开 Zotero  

## 本仓库脚本适配

翻译/检索脚本若写死了旧路径，迁移后应改为：

```powershell
$env:ZOTERO_DATA_DIR = "E:\Zotero"
$env:ZOTERO_WORK_BASE = "..."   # 工作区（status/work/results）可按需另迁
```

或编辑 `skills/translate-import/config.json`：

```json
{
  "zotero_data_dir": "E:/Zotero"
}
```

用 `python scripts/print_paths.py` 确认解析结果。

## 检查清单

- [ ] Zotero 已完全退出  
- [ ] 数据目录已完整复制（sqlite + storage + styles…）  
- [ ] `prefs.js` 已备份  
- [ ] `dataDir` 已指向新路径  
- [ ] 打开 Zotero，条目与附件正常  
- [ ] （可选）删除旧目录  
- [ ] 脚本环境变量 / config 已更新  

## 注意

- 不要在 Zotero 运行时改 `prefs.js` 或删旧库  
- 不要只复制 `storage` 而不复制 `zotero.sqlite`  
- 云同步（Zotero Sync）不替代本地附件备份；迁移前后建议各留一份完整目录副本  
