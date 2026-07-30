# TransRealm AI Context Index

> 新对话入口。先读本文件，再按当前指针和路由表按需读取；不要默认通读全部文档。

## 1. 启动顺序

1. 读取 `06_AI_Development_Guide.md` 的“决策权与 Agent 职责”“硬约束与参考实现”“Reality Check 与计划反馈”“最小设计门禁”。
2. 读取 `DEVELOPMENT_STATE.md` 的 frontmatter、当前 Task/小目标、必读文档、Reality Check 和 Last checkpoint。
3. 在 `07_Developer_Task_List.md` 读取当前 Task 完整定义，并按其“执行解释规则”区分硬约束与参考实现。
4. 按下表只读取命中的编号文档章节与代码。
5. 检查 Git 状态、当前实现和相关测试，代码事实以代码/测试/Git 为准。
6. 在写测试或代码前记录 `FIT`、`ADAPT` 或 `REPLAN`；只有 `REPLAN` 才停止冲突部分并回流规划。
7. 仅在冲突、首次进入新领域、索引路径失效或 Task 明确要求时扩大阅读范围。

用户在新对话只需说：`读取 D:\TransRealm\AI_CONTEXT_INDEX.md 并继续`。

## 2. 权威顺序

当前用户指令 → `01_PRD.md` → `08_Architecture_Review.md` → `03_Technical_Design.md` / `04_Database_Schema.md` / `05_Prompt_Architecture.md` → `02_Development_Roadmap.md` → `07_Developer_Task_List.md` → `DEVELOPMENT_STATE.md` → 本索引。

本索引只负责导航，不覆盖权威文档，不保存实现快照。`07_Developer_Task_List.md` 中未来 Task/Milestone 只提供规划导航；真正执行的切片始终由 `DEVELOPMENT_STATE.md` 的 current pointer 决定，索引不得据此提前推进状态。

## 3. 领域路由

| 任务/关键词 | 必读文档 | 代码入口 |
|---|---|---|
| 当前状态、恢复、下一步 | `06` 决策边界/Reality Check；`DEVELOPMENT_STATE.md`；`07` 当前 Task | 当前 Task 的修改范围与测试 |
| Project、路径、绿色版 | `01` §9/10/21；`03` §3；`04` §1–3 | `domain/project.py`、`application/project_service.py`、`infrastructure/repositories/project_repository.py` |
| SQLite、事务、migration、升级备份 | `03` §3/6；`04` §1/2/6/7；`06` 架构修改；`07` P0-T03-M00 | `infrastructure/database.py`、`infrastructure/migrations/`、`src/transrealm/migrations/`、`tests/test_migrations.py` |
| Parser、TXT/JSON/字幕、Segment、导入 | `01` §5/21；`02` §7；`03` §4/6/9；`04` §3/5/6 | `domain/segment.py`、`infrastructure/parsers/`、`application/import_service.py`、`infrastructure/repositories/segment_repository.py` |
| Provider Connection、Model Profile、Adapter | `03` §3/5/8/11；`04` §3/5；`05` §2–6；`07` P0-T03/P0-T04 | `domain/`、`application/`、`infrastructure/repositories/`、`adapters/`；对应 contract/fake transport 测试 |
| Prompt、Context Budget、输出请求契约 | `03` §4/7；`05` 全文；`07` P0-T05 | `application/context.py`、`context_composer.py`、`prompt_renderer.py`；对应测试；不得引入 RAG/TM |
| Output Parser、Validator、修复 | `03` §2/8；`05` §6/9；`07` P0-T06 | `application/output_parser.py`、`tests/test_p0_t06_*.py` |
| Attempt、Revision、lease、恢复、无人值守 | `01` §10/18/20/21；`03` §6/8/11；`04` §3/5/6；`05` §3/6/7；`06` 异常测试；`07` P0-T07 | `domain/segment.py`、相关 `infrastructure/repositories/` 与 application orchestration；fault/recovery 测试 |
| TXT 端到端、Exporter、GUI/PySide6/线程 | `02` Phase 0；`03` §2/4/9/10；`05`；`07` P0-T08 | `ui/`、application orchestration/exporter、E2E/pytest-qt；GUI 不直连 SQLite/Provider |
| JSON/字幕 round-trip、Project 双形态/`.aiproject` | `01` §5/9/21；`02` §7；`03` §3/9；`04` §7；`07` P1-T01/P1-T02 | parser/exporter、manifest/open-directory/package use case；golden、WAL、tamper、path traversal/resource-limit 测试 |
| 多 Profile、Glossary、自动/工作台模式 | `01` §3/4/11/16/21；`03` §2/5/7/10；`04` §3/5；`05` §2/4/5/9；`07` P1-T04 后 P1-T03 | `ui/`、Profile/Glossary repositories/application、composer；pytest-qt/重启恢复 |
| V1.0 Release Gate | `01` §17/20/21；`02` 测试/发布；`03` §3/6/8/10/11；`04`；`06`；`07` P1-T05 | 全测试矩阵、dependency lock/build/smoke、manual checklist；candidate 不等于发布 |
| 未来高级功能构想、V1.x/V2.0/远期愿景 | `01` §11–15/19；`02` Phase 2/3/4；`08` §9/13 | Character Data、TM、World State、Style Memory、RAG、动态 Context、多模型协作、候选译文、QC、节点式 Workflow、插件、内置模型管理、GPU 检测/模型推荐；只导航，不提前进入 V1.0 Task |
| 范围、阶段、任务依赖 | `01`；`02`；`07` §4 与当前 Task；重大决策读 `08` | 不以代码局部便利改变范围 |
| AI 协议、规划偏差、文档同步 | `06` 决策边界/Reality Check/最小设计门禁；`07` §1–3/8；`08` §11/14；`DEVELOPMENT_STATE.md` | 本索引也属于每个 Task 的同步门禁 |

编号简称：`01` = `01_PRD.md`，依此类推。

## 4. 验证路由

```bash
py -3.12 -m pytest -v
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

从仓库外执行时：pytest 使用 `-c D:/TransRealm/pyproject.toml` 并传绝对测试路径；Ruff 使用 `--config D:/TransRealm/pyproject.toml`；mypy 使用 `--config-file D:/TransRealm/pyproject.toml`，或先把工作目录切到 `D:\TransRealm`。UI 改动必须实际启动并操作；无 UI 的 Task 明确记 N/A。

## 5. 扩大阅读条件

仅当以下任一成立时扩大到其他文档/全库搜索：

- 当前 Task 的输入文档明确要求；
- 代码、测试、Git 与 `DEVELOPMENT_STATE.md` 冲突；
- 修改数据库格式、Project 兼容性、默认产品行为、依赖或安全边界；
- 首次进入路由表尚无代码入口的新领域；
- 本索引的路径、章节或符号已不存在。

## 6. AI 维护规则

以下变化必须在同一 Task 内更新本索引：

- 文件移动/重命名、关键职责迁移；
- 编号文档章节重排；
- Task 依赖或验证命令变化；
- 新增一个需要独立路由的领域。

未来高级功能治理：V1.0 Task 中的 `SIMPLIFY / DEFER / REMOVE` 只调整当前版本的执行范围，不得据此删除 `01_PRD.md`、`02_Development_Roadmap.md` 或 `08_Architecture_Review.md` 中的 V1.x/V2.0/远期构想。真正取消、合并或改变这些长期能力，必须由用户明确裁决，并同步更新 PRD、Roadmap、Architecture Review 和本索引；“当前不实现”不等于“已取消”。

只更新导航信息。不要复制当前状态、测试通过数或临时实现快照；这些分别属于 `DEVELOPMENT_STATE.md`、代码、测试和 Git。高级功能名称可作为长期愿景导航保留，但详细需求和状态仍以权威文档为准。
