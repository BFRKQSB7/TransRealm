# 译境 / TransRealm

本地优先、AI 辅助的翻译工作台。V1.0 目标：单用户、SQLite、OpenAI-compatible HTTP、Windows 11 绿色版优先。

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

## 打包 smoke（Phase 0 候选，PyInstaller）

Phase 0 只验证候选工具能 build/start，不冻结最终打包工具或发布 artifact：

```bash
py -3.12 -m pip install pyinstaller
py -3.12 -m PyInstaller --noconfirm --clean --onedir --windowed --name transrealm \
  --paths src --add-data "src/transrealm/migrations;transrealm/migrations" \
  <入口脚本或模块>
```

迁移 SQL 数据文件必须用 `--add-data` 收集，否则冻结应用无法应用迁移。依赖锁、体积、Qt 插件与杀毒扫描属 V1.0 Release Gate。

## 开发质量检查

```bash
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

无人开发的裁决与质量门禁见 `09_Unattended_Development_Governance.md`；候选发布执行清单见 `RELEASE_CHECKLIST.md`。交给开发 Agent 时只需提供 `DEVELOPMENT_STATE.md`；二者不代表已发布版本。
