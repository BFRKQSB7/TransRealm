# TransRealm 本机验收与候选构建

> 状态：本机候选构建、验收和回滚的唯一长期清单。版本特定证据保存在项目内验证目录；执行状态只写入 `tasks/README.md`，不写回静态 Task 文件或本文件。

## 0. 当前交付范围

本阶段只保证用户当前 Windows 电脑可用，交付可双击运行的 EXE/ZIP 绿色版。使用本机实际解压、启动和核心翻译流程作为环境验收；不要求纯净 Windows 11、虚拟机或其他电脑的兼容性证明。

AV 扫描和扫描/跳过状态记录不属于当前验收。移除这些要求不改变数据保护、凭据隔离、格式保真与恢复要求；未实际运行的本机检查仍须如实记录。

## 1. 候选身份

- 记录版本、Git commit、分支、工作树状态、构建时间、Windows 架构和执行者。
- 候选必须来自已验证、可定位且已获构建授权的基线；manifest 中的版本、commit 和 `git_dirty` 必须与实际一致。
- 当前流程先提交经过审阅的源码与文档，再从干净工作树构建；保留现有构建脚本的干净源码门禁，不绕过它。
- 候选范围不得包含 API Key、token、凭据正文、用户数据库、备份、日志、导出、`.aiproject`、未脱敏截图或旧候选残留。
- 记录 artifact/ZIP hash、大小、构建工具与恢复 ref；活动 `dist/` 只放当前候选，历史候选连同 manifest/hash 归档到项目内 `.local/archive/`。

## 2. 质量与数据门禁

必须通过并保存原始结果：

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

此外验证：

- 旧数据库 migration、升级前备份、失败恢复与 foreign keys。
- lease/Attempt/Revision/locked current 的崩溃恢复。
- 六格式 Parser/Exporter/Fidelity round-trip。
- `env:`/`wincred:`、错误与日志无 secret 泄露。
- `.aiproject`/Open Directory 的路径、hash、资源限制、篡改、隔离 staging 与秘密排除。
- 本轮源码审阅与实际本机验收无未解决的数据、安全或兼容阻塞；不要求额外独立评审或正式发布签核。

任何未运行或 Unknown 只能如实记录，不能算作通过。P0、秘密、migration 和发布门禁不得用普通例外放行。

本机不具备创建文件符号链接权限时，相关测试可保留为已注明原因的未覆盖项，不要求修改系统权限，也不得写为通过。实际本机启动与核心流程、迁移/恢复、凭据隔离和格式保真检查不能以环境不可用为由省略。

## 3. Windows 绿色版

从锁定环境运行：

```powershell
py -3.12 scripts/build_release.py
```

脚本生成 onedir、ZIP 与 `build_manifest.json`。候选必须包含 `src/transrealm/migrations/*.sql`、Qt 平台插件、i18n `.qm` 和其他必要资源；在用户当前电脑的项目内独立验证目录实际解压并启动，避免覆盖真实用户配置与数据。

在可写目录完成创建/打开 Project、迁移、六格式导入导出、受控兼容端点调用、Stop/Resume、关闭重开和恢复。验证只读目录、Unicode/长路径、网络/模型中断与不可写目标的错误可操作。删除程序目录不得删除外置 Project、备份或凭据。

## 4. 验收与外部动作

用户已授权的源码提交与本机候选构建按当前会话范围执行，不重复索要同一授权。签名、push、tag、PR 合并、上传 artifact、创建 GitHub Release 和正式发布仍分别需要明确授权。本机候选以源码审阅和实际本机验收为准；已知问题和未覆盖项必须与候选身份绑定，不能把历史证据套用到新候选。

## 5. 回滚

发布前验证以下路径：停止分发；回退到已知候选 artifact/ref；保留用户 Project、升级前备份与凭据；提供数据库前向修复或恢复步骤。不得通过降级应用去修改已被新 schema 打开的唯一用户数据副本；先复制并验证可恢复性。
