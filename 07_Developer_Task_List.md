# 译境 / TransRealm

# Developer Task List V3

## 1. Task规范

每个 Task 必须包含：

- Task 编号；
- Phase/Release；
- Priority；
- 目标与非目标；
- 前置依赖；
- 输入文档；
- 修改范围；
- 交付物；
- 功能验收；
- 异常验收；
- 测试证据；
- 文档同步项；
- 状态：pending / in_progress / blocked / verification / completed。

一个 Task 只完成一个可验证的小目标，不把后续功能顺手扩入当前 Task。

## 2. 自动执行规则

`07` 定义稳定 Task，`DEVELOPMENT_STATE.md` 定义当前正在执行的小目标和恢复检查点。

Agent 收到 `DEVELOPMENT_STATE.md` 后，无真实阻塞时自动读取当前 Task、加载指定文档并开始，不需要再次请求开工授权。完成小目标后先更新状态文件，再进入下一小目标；只有当前 Task 的全部验收完成，才修改本文件中的 Task 状态。

## 3. 完成流程

```text
需求确认
 -> 实现
 -> 功能测试
 -> 异常测试
 -> Code Review
 -> 更新文档
 -> 标记状态
```

测试失败、证据缺失或文档未同步时，不得标记 `completed`。

## 4. 执行顺序与依赖

```text
P0-T01 Project/SQLite/Migration 基础
  -> P0-T02 Parser 与稳定 Segment
  -> P0-T03 Model Profile 与 Provider Connection
  -> P0-T04 OpenAI-compatible Model Adapter
  -> P0-T05 最小 Context Budget/Prompt/输出契约
  -> P0-T06 Output Parser/Validator
  -> P0-T07 Attempt/Revision/恢复状态机
  -> P0-T08 TXT 翻译端到端流程
  -> P1-T01 JSON/SRT/ASS/SSA/VTT round-trip
  -> P1-T02 .aiproject 迁移与备份
  -> P1-T03 自动模式与工作台模式
  -> P1-T04 多 Model Profile 配置与基础 Glossary
  -> P1-T05 V1.0 异常恢复与发布验收
```

后续 Task 必须在开始前扩展为完整记录。第一项任务定义如下。

## 5. 当前可执行 Task

### P0-T01 — Project / SQLite / Migration 基础

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
- **目标：** 建立可创建、保存、关闭并重新打开的 Project 持久化骨架，以及可重复验证的 SQLite Migration 执行器。
- **非目标：** GUI 完整页面、文件 Parser、模型调用、`.aiproject` 打包、RAG/TM/Character Data。
- **前置依赖：** 编号文档基线、Python 3.12 + PySide6 + SQLite 技术栈、Windows 11 优先和绿色版优先决策均已批准。
- **输入文档：** `01_PRD.md` 第 9/10/21 节；`02_Development_Roadmap.md` Phase 0；`03_Technical_Design.md` 第 3/6 节；`04_Database_Schema.md` 第 1–3 节；`06_AI_Development_Guide.md`。
- **修改范围：** Python 3.12 项目骨架、Project 领域模型、SQLite 初始化、`schema_migrations`、migration runner、Repository 基础接口、pytest 测试；不修改 PySide6 页面、Prompt 或 Model Adapter。
- **交付物：** Python `src/` 项目骨架、依赖与测试配置、`001_init` migration、migration history/checksum、Project create/open/save API、临时测试 Project、pytest 自动化测试。
- **功能验收：** 新建数据库自动应用 migration；重复打开不重复执行；Project 元数据保存后可读回；外键启用；migration 顺序和 checksum 可查询。
- **异常验收：** migration 中途失败时事务回滚；错误 checksum 被拒绝；Windows Unicode/长路径和只读/无权限路径给出可操作错误；升级前备份失败时不得继续 migration。
- **测试证据：** `py -3.12 -m pytest -v` 41 passed；`py -3.12 -m ruff check src tests` All checks passed；`py -3.12 -m mypy src tests` Success: no issues found in 22 source files。
- **文档同步项：** 若表字段或 migration 规则改变，更新 `04_Database_Schema.md`；若 Project 生命周期改变，更新 `03_Technical_Design.md`；不得擅自扩大 PRD。

## 6. V1.0 范围

V1.0 基础可靠版包含：Project、SQLite Migration、Segment、TXT/JSON/字幕、Model Adapter、Model Profile、最小 Context Budget、输出校验、断点恢复、多模型配置和基础 Glossary。

V1.0 不包含：RAG、智能 TM、World State、节点式 Workflow 编辑器、插件、内置模型下载器、多人协作和原生多厂商 API。

## 7. 通用验收门槛

- Parser round-trip 不破坏结构、格式码、字幕时间轴或转义；
- Segment 状态、Revision 和 Attempt 可追踪；
- 无效输出不会直接覆盖译文；
- 网络中断、超时、本地服务停止和程序重启可安全恢复；
- migration 可升级，失败可恢复；
- 人工锁定译文不会被自动重译覆盖；
- Project 导出不包含秘密；
- 测试具有显式断言或可核验结果。

## 8. 文档同步

- 需求/范围变化 → `01_PRD.md`；
- 阶段/版本变化 → `02_Development_Roadmap.md`；
- 实现契约变化 → `03_Technical_Design.md`；
- 数据库变化 → `04_Database_Schema.md`；
- Prompt/输出协议变化 → `05_Prompt_Architecture.md`；
- Agent 流程变化 → `06_AI_Development_Guide.md`；
- 设计理由变化 → `08_Architecture_Review.md`；
- 当前小目标、测试证据、阻塞与恢复动作 → `DEVELOPMENT_STATE.md`。

## 9. P0-T02 — Parser 与稳定 Segment

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** in_progress
- **目标：** 实现 TXT 文件 Parser，生成稳定的 Segment 领域模型，支持导入到 Project 数据库并读取；为后续 JSON/字幕格式 parser 奠定接口。
- **非目标：** 不实现 JSON/SRT/ASS/VTT、GUI、模型调用、翻译流程、RAG/TM。
- **前置依赖：** P0-T01 已完成；Project/SQLite/Migration 基础可用。
- **输入文档：** `01_PRD.md` 第 9/10 节；`02_Development_Roadmap.md` Phase 0；`03_Technical_Design.md` 第 4/6 节；`04_Database_Schema.md` 第 3 节；`06_AI_Development_Guide.md`。
- **修改范围：** `domain/segment.py`、TXT parser、`application/import_service.py`、Segment Repository、`002_add_source_document_and_segment.sql` migration、pytest 测试；不修改 PySide6 页面、Prompt、Model Adapter。
- **交付物：** Segment 与 SourceDocument 领域模型、TXT parser、Import Service、Segment Repository、`002` migration、pytest 自动化测试。
- **功能验收：**
  - TXT 文件按行或段落切分为 Segment；
  - Segment 具有稳定 key（基于源内容/位置 hash）；
  - 导入后 Segment 可写入数据库并读取；
  - 重复导入同一文件不重复生成 Segment；
  - Segment 状态默认为 pending。
- **异常验收：**
  - 空 TXT 文件导入不产生 Segment；
  - 文件不存在时给出可操作错误；
  - 编码错误时被识别并报告；
  - 导入失败不破坏已有 Project 数据。
- **测试证据：** 自动化测试必须有显式断言，记录运行命令、通过数、失败数和关键输出。
- **文档同步项：** 若表字段或 migration 规则改变，更新 `04_Database_Schema.md`；若 Segment/Parser 契约改变，更新 `03_Technical_Design.md`；不得擅自扩大 PRD。