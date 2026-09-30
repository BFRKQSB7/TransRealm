# 译境 / TransRealm

TransRealm 是本地优先的个人 AI 长文本翻译工作台，面向小说、游戏文本、字幕及一般长文本。项目复用 SQLite、格式保真、Attempt/Revision 与恢复底座，并把后续开发集中到格式感知分段、单 Segment 请求、Context Memory 和翻译可靠性。

## 权威文档

- [产品范围](docs/PRODUCT.md) — 定位、V1 MUST/SHOULD/WON'T 与用户路径
- [架构](docs/ARCHITECTURE.md) — Single-Segment Pipeline、可靠内核与兼容边界
- [数据库](docs/DATABASE.md) — schema、append-only migration、备份、恢复与格式保真
- [开发规则](docs/DEVELOPMENT.md) — 运行、测试、Task、权限与提交边界
- [本机验收与候选构建](docs/RELEASE.md) — EXE/ZIP 绿色版、本机验收与回滚
- [当前执行入口](tasks/README.md) — 当前 phase 与下一动作

历史 RFC、Review、PRD、Roadmap、Task ledger 和旧状态记录位于 `docs/archive/`，不是当前开发指令。

## 开发基线

- Python 3.12+
- PySide6 / Qt 6
- SQLite
- pytest、Ruff、mypy

```powershell
py -3.12 -m pip install -e ".[dev]"
transrealm
# 或
py -3.12 -m transrealm.ui
```

## 质量检查

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

普通 Coding Agent 默认只读自己的 `tasks/Txx-*.md` 和其中指定源码；只有在 Task 风险需要时才增读对应权威文档。任务与当前执行状态统一见 `tasks/README.md`。
