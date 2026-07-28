---
project: TransRealm
file_role: agent-entrypoint-and-runtime-checkpoint
protocol_version: 1
current_phase: Phase 0
current_release: V0.x
current_task: P0-T01
current_milestone: P0-T01-M01
state: in_progress
last_updated: 2026-07-28
---

# 译境 / TransRealm — Agent 自动开工与开发状态

## 0. 给 Agent 的最高优先级指令

你正在接手 `D:\TransRealm` 的持续开发。

**读取本文件即代表用户要求你恢复现场并自动开工。不要只总结文档、复述计划、询问是否开始，也不要停在“下一步建议”。完成启动检查后，直接执行当前可执行小目标。**

只有以下情况才暂停并询问用户：

- 不同理解会导致明显不同的产品行为或数据格式；
- 需要改变已批准的 PRD、架构、技术栈或 V1.0 范围；
- 需要执行删除数据、覆盖未知文件、发布、推送、付费调用等难以撤销或对外操作；
- 缺少只有用户才能提供的凭据、文件或业务决定；
- 工作区实际状态与本文件冲突，且无法从代码、测试或 Git 记录判断正确状态。

命名、目录内局部组织、测试数据等常规可逆选择由你采用合理默认值，不要为小决定阻塞开发。

## 1. 自动启动协议

严格执行以下步骤：

1. 确认工作目录为 `D:\TransRealm`。
2. 读取本文件的 `current_task`、`current_milestone` 和 `state`。
3. 读取 `07_Developer_Task_List.md` 中当前 Task 的完整定义。
4. 按该 Task 的“输入文档”读取相关编号文档；首次接手或发现上下文不足时，按 00–08 顺序补读全部编号文档。
5. 检查当前文件树、Git 状态（若已初始化 Git）、已有实现和测试，验证本文件是否陈旧。不要覆盖用户或其他 Agent 的未提交工作。
6. 若状态为 `ready` 或 `in_progress` 且无真实阻塞：将本文件状态更新为 `in_progress`，记录启动时间/现场摘要，然后直接工作。
7. 一次只推进一个 `current_milestone`，采用垂直切片：测试或验收样例 → 最小实现 → 验证 → 文档/状态更新。
8. 小目标通过验收后，执行一次原子状态更新：写入测试证据；把已完成项改为 `completed`；把队列中下一项从 `pending` 改为 `ready`；同步修改 frontmatter 的 `current_milestone`、正文“当前小目标”和 `Last checkpoint`。任何一项未更新都视为检查点未完成，不得结束会话。
9. 当前 Task 的全部验收满足后，才把 Task 标记为 `completed`；随后从 `07_Developer_Task_List.md` 选择依赖已满足的下一 Task，并为它拆出第一个小目标。
10. 如果工作被中断，保持当前指针不变并将状态写为 `in_progress` 或 `blocked`，确保本文件足以让下一个 Agent 不依赖聊天记录继续开发。

## 2. 权威来源与冲突顺序

发生冲突时按以下顺序处理：

1. 用户在当前会话中的明确指令；
2. `01_PRD.md` 的产品范围；
3. `08_Architecture_Review.md` 的已批准架构决策；
4. `03_Technical_Design.md`、`04_Database_Schema.md`、`05_Prompt_Architecture.md` 的实现契约；
5. `02_Development_Roadmap.md` 的阶段与版本安排；
6. `07_Developer_Task_List.md` 的任务定义；
7. 本文件的运行状态。

本文件只记录执行现场，不得擅自改变产品或架构。发现本文件陈旧时，以代码、测试和权威编号文档为准，并修正本文件。

## 3. 固定项目基线

- 核心语言：Python 3.12；
- GUI：PySide6（Qt 6）；
- 数据库：SQLite；
- 测试：pytest，Qt 交互测试可使用 pytest-qt；
- 首发平台：Windows 11；
- 发布形态：绿色版优先；
- V1.0 Model Adapter：OpenAI-compatible HTTP；
- llama.cpp、Ollama：优先使用兼容端点；
- Sakura、Murasaki：Model Profile，不代表专有调用协议；
- V1.0 不包含 RAG、智能 TM、World State、节点式 Workflow 编辑器、插件、内置模型管理、多人协作或原生多厂商 API。

## 4. 当前开发现场

### 当前环境检查

- 2026-07-28 检测时 Python 3.12 缺失，已阻塞；当前会话 `py -3.12 --version` 返回 Python 3.12.10，阻塞解除。

### 当前 Task

- **Task：** P0-T01 — Project / SQLite / Migration 基础
- **状态：** in_progress
- **完整定义：** `07_Developer_Task_List.md` 的“P0-T01”章节
- **前置依赖：**文档与技术决策已满足；Python 3.12 已可用

### 当前小目标

- **Milestone：** P0-T01-M01 — 建立可测试的 Python 工程骨架
- **状态：** in_progress
- **目标：** 创建符合 Technical Design 分层要求的最小 Python 3.12 `src/` 工程和 pytest 测试环境，为后续 migration 与 Project Repository 提供基础。
- **非目标：** 不实现 PySide6 页面、不调用模型、不实现 Parser、Prompt、`.aiproject` 或完整数据库业务表。

### M01 必读文档

按顺序读取：

1. `07_Developer_Task_List.md` — P0-T01 完整任务；
2. `03_Technical_Design.md` — 技术栈、Python 分层、Project/路径规则；
3. `04_Database_Schema.md` — migration 与 V1.0 最小实体；
4. `06_AI_Development_Guide.md` — 开发、测试和报告规则；
5. `01_PRD.md` 第 21 节 — V1.0 与平台边界。

### M01 预期交付物

- Python 3.12 项目元数据与锁定依赖的基础配置；
- `src/` 布局；
- `ui`、`application`、`domain`、`infrastructure`、`adapters` 包边界；
- `tests/` 与可运行 pytest 配置；
- 最小 smoke test，验证包可导入、测试可执行；
- Windows 路径和 UTF-8 基线配置；
- 不引入未被当前目标使用的框架或依赖。

### M01 验收

- Python 版本约束明确为 3.12；
- `pytest` 能运行且至少包含一个有显式断言的 smoke test；
- domain 层不依赖 PySide6、SQLite 或 HTTP SDK；
- 当前工程结构与 `03_Technical_Design.md` 一致；
- 记录实际测试命令、通过数和失败数；
- 本文件已更新为下一个小目标。

## 5. P0-T01 建议小目标队列

只有当前小目标完成后才激活下一项：

| Milestone | 目标 | 状态 |
|---|---|---|
| P0-T01-M01 | Python 3.12 `src/` 工程与 pytest 骨架 | in_progress |
| P0-T01-M02 | SQLite 连接、PRAGMA 与事务基础 | pending |
| P0-T01-M03 | migration discovery、顺序和 history/checksum | pending |
| P0-T01-M04 | `001_init` 与 Project create/open/save API | pending |
| P0-T01-M05 | migration 失败、checksum、只读/Unicode/长路径异常测试 | pending |
| P0-T01-M06 | P0-T01 Code Review、文档同步与完成验收 | pending |

Agent 可以在实现中细化这些小目标，但不得扩大 P0-T01 的范围。

## 6. 每次更新本文件的格式

完成或中断小目标时更新以下内容，不新增流水账文件：

### Last checkpoint

- **时间：** 2026-07-28
- **Agent：** Claude Code (Haiku 4.5)
- **完成内容：** Python 3.12 已可用；M01 从 blocked 改为 in_progress；开始创建 Python 3.12 工程骨架
- **修改文件：** `DEVELOPMENT_STATE.md`
- **测试命令：** `py -3.12 --version`
- **测试结果：** Python 3.12.10 可用
- **未完成：** P0-T01-M01 工程骨架、测试与文档同步
- **风险/阻塞：** 无
- **恢复动作：** 继续完成 M01 工程骨架、pytest 验收、文档同步与 Git 提交

### Completed milestones

暂无。

### Decisions made during implementation

暂无。只记录不能从编号文档、代码或 Git 历史直接推导，但会影响后续工作的局部决定。

## 7. 状态更新规则

- `ready`：要求明确，可立即开工；
- `in_progress`：已修改工作区但小目标未完成；
- `blocked`：缺少用户决定、凭据或外部资源；必须写清解除条件；
- `verification`：实现完成，正在测试或 Review；
- `completed`：功能测试、异常测试、Review 和必要文档同步全部完成。

禁止为了显得有进度而虚报状态。测试失败时保持 `in_progress` 或 `blocked`。

## 8. Agent 结束本次工作的条件

仅在以下任一条件成立时结束：

- 当前小目标完成、验证并已把下一小目标写入本文件；
- 遇到真实阻塞，已尽可能完成不受阻部分，并把解除条件写入本文件；
- 用户明确要求停止。

结束回复先报告实际结果，再报告测试和下一检查点。不要以“如果你愿意，我可以开始”结尾。