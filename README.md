# 译境 / TransRealm

本地优先、AI 辅助的翻译工作台。V1.0 目标：单用户、SQLite、OpenAI-compatible HTTP、Windows 11 绿色版优先。

## 用户文档（v0.2.0 候选）

- [安装与使用指南](docs/user-guide.md) — 绿色版安装、三标签页操作、Auto/Workbench 模式、Profile/Glossary、导出与清理
- [数据安全](docs/data-safety.md) — 迁移、备份、恢复/回滚、卸载清理
- [已知问题与未覆盖项](docs/known-issues.md) — 候选行为限制与尚未闭环的验证项
- [第三方依赖与许可](docs/third-party-licenses.md) — 运行时与工具链许可清单

## 开发基线

- Python 3.12+
- PySide6（Qt 6）
- SQLite
- pytest

## 目录结构

```text
src/transrealm/
  ui/               # PySide6 页面与信号
  application/      # 应用服务与编排
  domain/           # 领域模型与业务规则（不依赖 Qt/SQLite/HTTP）
  infrastructure/   # SQLite、Repository、持久化
  adapters/         # 外部模型端点适配

tests/              # pytest 测试
```

## 安装开发依赖

```bash
py -3.12 -m pip install -e ".[dev]"
```

## 运行桌面版

```bash
transrealm
# 或 python -m transrealm.ui
```

数据默认存于 `~/.transrealm/project.sqlite`（Phase 0 桌面壳：Settings 管理 Connection/Profile，Project 建项目并导入 TXT，Translation 选择 Profile、翻译/取消/进度与 TXT 导出）。

## 打包候选（P1-T05，PyInstaller）

从锁定环境构建 Windows 绿色版候选（onedir + zip + `build_manifest.json`，记录工具/版本/hash/size）：

```bash
py -3.12 scripts/build_release.py
```

产物在 `dist/`（gitignored）：`transrealm/`（onedir）、`transrealm-0.2.0-win-x64.zip`（绿色 artifact）、`build_manifest.json`（候选身份与 hash）。迁移 SQL 数据文件由脚本以 `--add-data "src/transrealm/migrations;transrealm/migrations"` 收集，否则冻结应用无法应用迁移。构建候选不等于提交、推送或发布；外部动作始终需用户单独授权。依赖锁、体积、Qt 插件与杀毒扫描仍属当前 v0.2.0 Release Gate（`03` §12）。

## 开发质量检查

```bash
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

无人开发的裁决与质量门禁见 `09_Unattended_Development_Governance.md`；候选发布执行清单见 `RELEASE_CHECKLIST.md`。交给开发 Agent 时只需提供 `DEVELOPMENT_STATE.md`；二者不代表已发布版本。
