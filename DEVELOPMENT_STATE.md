---
project: TransRealm
file_role: agent-entrypoint-and-runtime-checkpoint
protocol_version: 2
plan_alignment: pending_reality_check
current_phase: Phase 0
current_release: V0.x
current_task: P0-T07
current_milestone: P0-T07-M01
state: ready
last_updated: 2026-07-30
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

计划是等待代码现场验证的执行假设，不是不可质疑的实现命令。目标、非目标、验收、兼容性和安全边界属于硬约束；内部类名、文件落点、局部算法和未明确批准的存储建议默认属于参考实现。

发现计划与现场不吻合时，严格按 `06_AI_Development_Guide.md` 记录 `FIT`、`ADAPT` 或 `REPLAN`：`ADAPT` 范围内自主处理，只有 `REPLAN` 才暂停冲突部分并回流规划，禁止机械硬改。

## 1. 自动启动协议

严格执行以下步骤：

1. 确认工作目录为 `D:\TransRealm`。
2. 读取 `AI_CONTEXT_INDEX.md`，按索引路由当前任务所需文档与代码；不要默认通读全部编号文档。
3. 读取 `06_AI_Development_Guide.md` 的决策边界、硬约束/参考实现、Reality Check 和最小设计门禁。
4. 读取本文件的 `current_task`、`current_milestone`、`state` 和 `plan_alignment`。
5. 读取 `07_Developer_Task_List.md` 当前 Task 的完整定义，并按“执行解释规则”区分硬约束与参考实现。
6. 按该 Task 的输入文档和索引读取相关章节；仅在冲突、首次进入新领域或索引失效时扩大阅读范围。
7. 检查文件树、Git 状态、已有实现和测试，验证本文件是否陈旧。不要覆盖用户或其他 Agent 的未提交工作。
8. 在写测试或代码前完成 Reality Check，并在本文件记录 `FIT`、`ADAPT` 或 `REPLAN` 及现场依据。`FIT` 直接执行；`ADAPT` 自主调整；`REPLAN` 仅暂停冲突部分并提交偏差证据。
9. 若状态为 `ready`、`in_progress` 或 `verification` 且结论不是 `REPLAN`：保持或更新为 `in_progress`，记录现场摘要，然后直接工作。
10. 一次只推进一个 `current_milestone`，采用垂直切片：测试或验收样例 → 最小实现 → 功能/异常测试 → Code Review → 文档/状态更新。
11. 小目标通过验收后，执行原子状态更新：写入测试证据；把已完成项改为 `completed`；把队列中下一项从 `pending` 改为 `ready`；同步 frontmatter、正文“当前小目标”和 `Last checkpoint`。
12. 当前 Task 全部验收满足后，才标记 Task `completed`；下一 Task 开工前重新执行 Reality Check，未来计划不得自动推进运行指针。
13. 如果工作被中断，保持当前指针不变并写明状态、plan_alignment、现场依据和恢复动作，使下一 Agent 不依赖聊天记录继续。
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

### 当前计划治理状态

- 已启用 `06_AI_Development_Guide.md` V4：规划 Agent 定义目标、边界和验收，执行 Agent 对代码现场和范围内最小实现负责。
- 当前及未来 Milestone 开工前必须记录 `FIT`、`ADAPT` 或 `REPLAN`；没有 `REPLAN` 证据时不得仅因计划可能不完美而停工。
- 已完成的 P0-T01 至 P0-T06 默认保留，不做无证据的推倒重来；发现具体缺陷时以测试保护的最小修正处理。
- 未来 Task 中的类名、Manager/Service、文件落点和局部算法默认是参考实现，除非权威文档明确标注为强制契约。
### 当前 Task

- **Task：** P0-T07 — Attempt / Revision / 恢复状态机
- **状态：** ready
- **完整定义：** `07_Developer_Task_List.md` 的“P0-T07”章节
- **前置依赖：** P0-T03 至 P0-T06 的工作树能力和测试现场已存在，但 Git HEAD 仍停在 P0-T02-M02；实现前先形成受保护、可恢复的 Git 基线并重新验证。

### 当前小目标

- **Milestone：** P0-T07-M01 — 可重开执行骨架：新 migration 后可读取版本化只读内置 Workflow、创建 Run，并在第一次外部请求前持久化包含最小快照/审计基础的 Attempt
- **状态：** ready
- **plan_alignment：** pending_reality_check
- **目标：** 在兼容旧 Project 的新 migration 上建立可重开的内置 Workflow/Run/Attempt 执行起点，锁定后续状态机所需的最小审计和引用完整性；Revision 完成事务由 M03 垂直交付。
- **硬约束：** 已发布 migration 不重写；只读内置 Workflow 可版本化/hash 校验；Run/Attempt 引用完整且 Attempt 在第一次外部模型请求前持久化；保留后续 Revision/lease/fencing 所需 schema，但不以水平 CRUD 作为完成结果；不引入 Workflow 编辑器或复杂 UI。
- **参考实现：** 新编号 migration、最小领域值对象和共享连接的持久化操作；内部表拆分、类名和 Repository 数量由执行 Agent按现场决定。
- **非目标：** 不实现 GUI、自动/工作台模式、RAG/TM 或项目包。
- **恢复前 Reality Check：** 待下一 Agent 在写测试或代码前按 `06_AI_Development_Guide.md` 完成现场核验，并记录 `FIT`/`ADAPT`/`REPLAN`。
- **已知未完成：** P0-T07-M01 至 M05 均未开始。
- **技术阻塞：** 无。
### P0-T07-M01 必读文档

按 `AI_CONTEXT_INDEX.md` 路由读取：

1. `01_PRD.md` 第 10/18/20/21 节 — 用户可见断点恢复、版本保护、兼容性与 V1.0 边界；
2. `07_Developer_Task_List.md` — P0-T07 完整 Task 与 M01；
3. `03_Technical_Design.md` 第 6/11 节 — Segment claim/fencing/恢复、Attempt 可观测性与安全；
4. `04_Database_Schema.md` 第 2/3/5/6 节 — 已发布 migration、Workflow/Run/Attempt/Revision、约束和事务；
5. `05_Prompt_Architecture.md` 第 3/6/7 节 — 翻译流程、输出/重试边界、Context Manifest 与 Debug。

### 规划审查后的 M01 执行提醒

- 当前指针、`state: ready` 和 `plan_alignment: pending_reality_check` 保持不变；本次只完成后续规划审查，不代表 M01 已开工或完成。
- Git HEAD 仍停在 P0-T02-M02；P0-T03 至 P0-T06 的大量代码、tests 和 migrations `003`–`005` 位于未提交 working tree。执行 Agent 必须保护并重新验证这些文件，禁止从 HEAD 重建或覆盖。
- M01 不重复添加 `segments.current_revision_id/version/lease_*`，不重写 migration backup；应根据 `002` 现状用新 migration 增量建立 Workflow/Run/Attempt 及后续 Revision/fencing 所需约束，但以 M01 可重开行为为验收，不要求一次交付全部 CRUD。
- claim identity 采用 `lease_owner + version` fencing；Attempt 在成功 claim 后、第一次外部模型请求前创建。transport retry/capability degradation 同 Attempt，输出 repair/业务 retry 新 Attempt。
- 只实现版本化只读内置 Workflow；不实现用户 Workflow CRUD、队列、事件总线、worker pool 或 UI。
- 执行前仍须把现场结论写为 `FIT / ADAPT / REPLAN`；若 schema/公共契约与 Task 冲突，按 `REPLAN` 只暂停冲突部分。

## 5. 历史 Milestone 状态索引

只有当前小目标完成后才激活下一项：

| Milestone | 目标 | 状态 |
|---|---|---|
| P0-T01-M01 | Python 3.12 `src/` 工程与 pytest 骨架 | completed |
| P0-T01-M02 | SQLite 连接、PRAGMA 与事务基础 | completed |
| P0-T01-M03 | migration discovery、顺序和 history/checksum | completed |
| P0-T01-M04 | `001_init` 与 Project create/open/save API | completed |
| P0-T01-M05 | migration 失败、checksum、只读/Unicode/长路径异常测试 | completed |
| P0-T01-M06 | P0-T01 Code Review、文档同步与完成验收 | completed |
| P0-T02-M01 | TXT 解析器与最小 Segment 模型 | completed |
| P0-T02-M02 | Parser 接口抽象与 TXT 异常测试 | completed |
| P0-T02-M03 | Segment 稳定 key 碰撞与重复导入策略 | completed |
| P0-T03-M00 | SQLite migration 升级前一致性备份 | completed |
| P0-T03-M01 | Provider Connection 非敏感配置模型与持久化 | completed |
| P0-T03-M02 | Model Capability/Profile 模型、持久化、Connection 外键与关闭重开测试 | completed |
| P0-T03-M03 | timeout/retry policy、JSON 配置和关闭重开的一致性验收 | completed |
| P0-T03-M04 | Task review、全回归、编号文档/索引/状态同步 | completed |
| P0-T04-M01 | Adapter Protocol、DTO、capability contract 与 normalized error | completed |
| P0-T04-M02 | OpenAI-compatible 成功请求/响应映射 | completed |
| P0-T04-M03 | timeout、限流、错误分类与有限 transport retry | completed |
| P0-T04-M04 | capability 降级、credential resolver 边界与脱敏验收 | completed |
| P0-T04-M05 | Review、全回归和文档/状态同步 | completed |
| P0-T05-M01 | Context Candidate / Manifest / 预算 DTO | completed |
| P0-T05-M02 | 当前与相邻 Segment 的最小规则预算 | completed |
| P0-T05-M03 | 锁定 Glossary 候选接口与预算不足行为 | completed |
| P0-T05-M04 | Profile 模板渲染与不可破坏输出契约 | completed |
| P0-T05-M05 | 可复现性 review、全回归和同步 | completed |
| P0-T06-M01 | 解析/校验 DTO、错误分类和 fixture 规范。 | completed |
| P0-T06-M02 | 单 Segment parser/validator。 | completed |
| P0-T06-M03 | 批量 items 的 ID/数量/顺序交叉校验。 | completed |
| P0-T06-M04 | 有限修复分类与恶意/异常输出矩阵。 | completed |
| P0-T06-M05 | Review、全回归和同步。 | completed |

Agent 可以在实现中细化这些小目标，但不得扩大当前 Task 的范围。

## 6. 每次更新本文件的格式

完成或中断小目标时更新以下内容，不新增流水账文件：

### Planning checkpoint

- **时间：** 2026-07-30
- **Agent：** Claude（规划 Agent）
- **完成内容：** 对当前 P0-T07-M01 至 V1.0 Release Candidate Gate 完成 Reality Audit、依赖重排、垂直 Milestone 重构和规划级架构审查；P0-T06 无剩余 Milestone，不安排重写；P1-T04 调整到 P1-T03 前，先提供 Project Profile 选择与基础 Glossary；明确 Attempt/lease/retry/Revision、格式保真、Project 双形态与安全导入、UI worker 和 Release Gate 契约。用户裁决 V1.0 保留 `.aiproject` + 高级用户开放目录两种互通 Project 形态。
- **修改文件：** 仅规划/治理文档：`02_Development_Roadmap.md`、`03_Technical_Design.md`、`04_Database_Schema.md`、`05_Prompt_Architecture.md`、`07_Developer_Task_List.md`、`08_Architecture_Review.md`、`DEVELOPMENT_STATE.md`、`AI_CONTEXT_INDEX.md`。
- **验证方式：** 只读检查 Git、代码、migration、依赖和测试分布；规划文档 diff/交叉引用/路径/编号审查。未运行测试；历史 `333 passed` 仅保留为上一代码检查点证据，不作为本次重新验证。
- **未完成：** P0-T07-M01 仍未开始；current pointer、state 和 `plan_alignment` 未推进。
- **风险/阻塞：** 工作树仍包含大量未提交业务代码和 tests，HEAD 只到 P0-T02-M02；开始实现前必须形成受保护、可恢复的代码基线并重新验证。V1.0 Project 双形态已由用户裁决，无剩余需要改变产品范围/技术栈的规划裁决项。
- **恢复动作：** Kimi/执行 Agent 读取 `AI_CONTEXT_INDEX.md` 和本文件，进入 P0-T07-M01；先检查 Git 未提交现场，在不覆盖当前 index/worktree 的前提下形成可恢复 Git 基线（保护范围含 tracked、untracked、staged additions/deletions，并记录恢复方法），再执行 M01 Reality Check 和 `07` 的行为切片。保护完成前不得新增 M01 业务实现，禁止从 HEAD 覆盖现有工作或提前进入未来 Task。

### Last code checkpoint

- **时间：** 2026-07-30
- **Agent：** Claude
- **完成内容：** 完成 P0-T06-M05：M05 Reality Check 结论为 **ADAPT**（`07_Developer_Task_List.md` 中 P0-T06-M03 状态陈旧，已同步为 completed）；执行 P0-T06 全 Task Code Review，未发现需要修复的缺陷；运行全量回归（pytest 333 passed）、Ruff 和 mypy（59 source files 无问题）；同步 `DEVELOPMENT_STATE.md` 与 `07_Developer_Task_List.md`，将 P0-T06 标记为 completed，指针推进至 P0-T07-M01（ready，待 Reality Check）。
- **修改文件：** `DEVELOPMENT_STATE.md`（frontmatter 当前 task/milestone/last_updated、当前 Task/小目标/必读文档、Last checkpoint、M05 completed、已完成里程碑追加 P0-T06-M05）；`07_Developer_Task_List.md`（P0-T06 状态 completed、M05 completed）。
- **测试命令：** `py -3.12 -m pytest -v`；`py -3.12 -m ruff check src tests`；`py -3.12 -m mypy src tests`
- **测试结果：** 全量回归 pytest 333 passed；Ruff All checks passed；mypy Success: no issues found in 59 source files。
- **未完成：** P0-T07-M01 未开始。
- **风险/阻塞：** 无技术阻塞。
- **恢复动作：** 读取 `AI_CONTEXT_INDEX.md` 并按启动顺序加载；当前小目标为 P0-T07-M01，状态 ready，plan_alignment pending_reality_check。先保护包含 staged/unstaged/untracked/deleted 状态的完整工作树并记录恢复方法；保护完成前不得新增 M01 业务实现。之后以 `07` 当前 P0-T07-M01 的“可重开执行骨架”行为和完成条件为准，记录 `FIT/ADAPT/REPLAN`，再做测试与最小实现。

### Completed milestones

- **P0-T01-M01** — Python 3.12 `src/` 工程与 pytest 骨架（completed）
  - 交付物：`pyproject.toml`、分层 `src/transrealm/` 包、`tests/test_smoke.py`、`.gitignore`、`README.md`
  - 验收证据：pytest 4 passed；Ruff/mypy 无问题；domain 层无 PySide6/SQLite/HTTP 依赖
- **P0-T01-M02** — SQLite 连接、PRAGMA 与事务基础（completed）
  - 交付物：`src/transrealm/infrastructure/database.py`、事务与错误类型、`tests/test_database.py`
  - 验收证据：pytest 12 passed（合计 16）；Ruff/mypy 无问题；外键/WAL/Unicode/长路径/只读路径已覆盖
- **P0-T01-M03** — migration discovery、顺序和 history/checksum（completed）
  - 交付物：`infrastructure/migrations/` 包、`schema_migrations` 表与 runner、`tests/test_migrations.py`
  - 验收证据：pytest 10 passed（合计 26）；Ruff/mypy 无问题；发现/顺序/幂等/checksum/回滚已覆盖
- **P0-T01-M04** — `001_init` 与 Project create/open/save API（completed）
  - 交付物：`001_init.sql`、Project 实体、Repository、Application Service、`tests/test_project.py`
  - 验收证据：pytest 8 passed（合计 34）；Ruff/mypy 无问题；创建/打开/保存/幂等已覆盖
- **P0-T01-M05** — migration 失败、checksum、只读/Unicode/长路径异常测试（completed）
  - 交付物：`tests/test_exceptions.py`
  - 验收证据：pytest 7 passed（合计 41）；Ruff/mypy 无问题；失败回滚/checksum/只读/Unicode/长路径已覆盖
- **P0-T01-M06** — P0-T01 Code Review、文档同步与完成验收（completed）
  - 交付物：范围内 Code Review 修复、`07_Developer_Task_List.md` 状态同步、`DEVELOPMENT_STATE.md` 推进
  - 验收证据：全部 41 测试通过；ruff/mypy 无问题；MigrationRunner.close 与错误检查已加固
- **P0-T02-M01** — TXT 解析器与最小 Segment 模型（completed）
  - 交付物：`domain/segment.py`、TXT parser、Import Service、Segment Repository、`002` migration、`tests/test_txt_parser.py`
  - 验收证据：pytest 8 passed（合计 49）；Ruff/mypy 无问题；TXT 分段/stable key/重复导入/空文件/编码错误已覆盖
- **P0-T02-M02** — Parser 接口抽象与 TXT 异常测试（completed）
  - 交付物：`infrastructure/parsers/parser.py`、Parser Protocol、ParserRegistry、TxtParser 类、扩展测试
  - 验收证据：pytest 7 passed（合计 56）；Ruff/mypy 无问题；协议/注册表/空行/重复行/不支持格式已覆盖
- **P0-T02-M03** — Segment 稳定 key 碰撞与重复导入策略（completed）
  - 交付物：`003_add_import_uniqueness.sql`、原子导入 Repository API、不可变内容版本策略、`AI_CONTEXT_INDEX.md`、回归测试与契约同步
  - 验收证据：pytest 62 passed；Ruff/mypy 无问题；同 hash 幂等、内容变化保留旧版本、空文件、约束碰撞回滚、旧库冲突保留已覆盖
- **P0-T03-M00** — SQLite migration 升级前一致性备份（completed）
  - 交付物：`infrastructure/migrations/backup.py`、runner 集成、`MigrationBackupError`、备份发现/打开/阻断/失败保留/WAL/命名/不可写目标测试
  - 验收证据：pytest 69 passed；Ruff/mypy 无问题；仅 pending migration 时创建备份、备份失败阻止 migration、备份保留失败前数据、WAL 下一致性复制、备份文件可发现可打开已覆盖
- **P0-T03-M01** — Provider Connection 非敏感配置模型与持久化（completed）
  - 交付物：`004_add_provider_connection.sql`、`domain/provider_connection.py`、Repository、Application Service、`tests/test_provider_connection.py`；`credential_reference` 仅接受 `env:`/`wincred:` 语法；同步更新 `04_Database_Schema.md`
  - 验收证据：pytest 102 passed；Ruff/mypy 无问题；CRUD/唯一名/关闭重开/空名/非法 endpoint/超时/重试/原始 API Key 拒绝已覆盖

- **P0-T03-M02** — Model Capability/Profile 模型、持久化、Connection 外键与关闭重开测试（completed）
  - 交付物：`005_add_model_profile.sql`、`domain/model_profile.py`（`ModelCapability`/`ModelProfile`）、`ModelProfileRepository`、`ModelProfileService`、`tests/test_model_profile.py`；`model_profiles.provider_connection_id` 外键 RESTRICT 保护引用完整性；同步更新 `04_Database_Schema.md`
  - 验收证据：pytest 129 passed；Ruff/mypy 无问题；Capability 验证/snapshot、Profile CRUD、外键约束、关闭重开一致性、缺失 Connection 预校验、被引用 Connection 删除阻断已覆盖
- **P0-T03-M03** — timeout/retry policy、JSON 配置和关闭重开一致性验收（completed）
  - 交付物：`tests/test_p0_t03_m03.py`；覆盖 timeout/retry 边界、复杂嵌套 JSON round-trip、部分 JSON 更新保真、跨 service 关闭重开一致性、多 Profile 共享 Connection、capability snapshot 刷新
  - 验收证据：pytest 140 passed；Ruff/mypy 无问题
- **P0-T03-M04** — Task review、全回归、编号文档/索引/状态同步（completed）
  - 交付物：删除未使用 `_REQUIRED_PARAMETERS`/`ClassVar`、空 capability snapshot 防护与测试；更新 `04_Database_Schema.md`、`07_Developer_Task_List.md`、`DEVELOPMENT_STATE.md`
  - 验收证据：pytest 140 passed；Ruff/mypy 无问题
- **P0-T04-M01** — Adapter Protocol、DTO、capability contract 与 normalized error（completed）
  - 交付物：`adapters/dto.py`、`adapters/protocol.py`、`adapters/errors.py`、`adapters/openai_adapter.py`、`tests/test_adapter_protocol.py`；`ModelAdapter`/`Transport`/`CredentialResolver` Protocol、normalized error taxonomy、OpenAI-compatible 请求/响应映射与 capability 校验
  - 验收证据：pytest 177 passed；Ruff/mypy 无问题；DTO 校验、错误分类、capability 过滤、请求/响应映射、HTTP 错误映射、凭据边界与脱敏均已覆盖
- **P0-T04-M02** — OpenAI-compatible 成功请求/响应映射（completed）
  - 交付物：`tests/test_p0_t04_m02.py`；修复 `openai_adapter.py` 中 `stream=True` 请求体映射，加固 usage 解析对非整数/负值的处理
  - 验收证据：pytest 198 passed；Ruff/mypy 无问题；endpoint、model、参数、usage、request ID、finish reason、多 choices、空 content、raw_response 保留均已覆盖
- **P0-T04-M03** — timeout、限流、网络/服务/认证/参数错误分类与有限 transport retry（completed）
  - 交付物：`openai_adapter.py` 有限重试循环、`tests/test_p0_t04_m03.py`、指数退避与 `Retry-After` 支持、retry 参数校验
  - 验收证据：pytest 211 passed；Ruff/mypy 无问题；非重试错误、5xx/429/408/超时/断连重试、retry-after 头、timeout 每 attempt 一致、请求体跨重试保持一致均已覆盖
- **P0-T04-M04** — capability 降级、credential resolver 边界与脱敏验收（completed）
  - 交付物：`DegradationPolicy`、capability 降级重试、`tests/test_p0_t04_m04.py`、resolver 调用边界与错误脱敏加固
  - 验收证据：pytest 224 passed；Ruff/mypy 无问题；结构化输出/流式降级、无策略/非 capability 400 不降级、降级保留参数、降级失败、resolver 仅按需调用、错误信息无 secret 泄露均已覆盖
- **P0-T04-M05** — Review、全回归和文档/状态同步（completed）
  - 交付物：最终 Code Review 修复（`openai_adapter.py` `_compute_delay` mypy 类型显式转换）、`03_Technical_Design.md` §5 Adapter retry/降级/凭据边界同步、`07_Developer_Task_List.md` P0-T04 完成标记、`DEVELOPMENT_STATE.md` 推进至 P0-T05-M01
  - 验收证据：pytest 224 passed；Ruff All checks passed；mypy Success: no issues found in 47 source files
- **P0-T05-M01** — Context Candidate / Manifest / 预算 DTO（completed）
  - 交付物：`src/transrealm/application/context.py`（`BudgetEstimate`、`ContextCandidate`、`ContextSource`、`EstimateMethod`、`ContextBudget`、`ContextManifest`、`OutputItem`、`OutputContract`）、`tests/test_p0_t05_m01.py`
  - 验收证据：pytest 250 passed；Ruff All checks passed；mypy Success: no issues found in 49 source files；DTO 创建、预算可用空间、预留校验、候选优先级/来源、Manifest 版本记录、输出契约唯一性与空值校验均已覆盖
- **P0-T05-M02** — 当前与相邻 Segment 的最小规则预算（completed）
  - 交付物：`src/transrealm/application/context_composer.py`（`ContextComposer`、`ContextBudgetError`）、`tests/test_p0_t05_m02.py`
  - 验收证据：11 passed；Ruff/mypy 无问题；当前 Segment 必入/不截断、相邻优先级排序、预算不足裁剪、空输入、字符/token 估算、自定义 estimator 均已覆盖
- **P0-T05-M03** — 锁定 Glossary 候选接口与预算不足行为（completed）
  - 交付物：`src/transrealm/application/context_composer.py`（`glossary_candidates` 参数、优先级归一化）、`tests/test_p0_t05_m03.py`
  - 验收证据：8 passed；Ruff/mypy 无问题；空 Glossary 候选、锁定 Glossary 优先于相邻 Segment、自定义估算保留、预算不足时 Glossary 保留/邻居裁剪、Manifest 记录已裁剪 Glossary 均已覆盖
- **P0-T05-M04** — Profile 模板渲染与不可破坏输出契约（completed）
  - 交付物：`src/transrealm/application/prompt_renderer.py`（`PromptRenderer`、`RenderedPrompt`、`PromptRenderError`、`DEFAULT_OUTPUT_SCHEMA`）、`tests/test_p0_t05_m04.py`
  - 验收证据：7 passed；Ruff/mypy 无问题；Prompt 文本与输出契约生成、输出 schema 始终存在、自定义模板变量替换、未知变量报错、缺失当前 Segment 报错、输出契约仅含当前 Segment、自定义 schema 均已覆盖
- **P0-T05-M05** — 可复现性 review、全回归和同步（completed）
  - 交付物：全量回归通过、lint/type 通过、DEVELOPMENT_STATE.md 与 07_Developer_Task_List.md 同步
  - 验收证据：pytest 275 passed；Ruff All checks passed；mypy Success: no issues found in 54 source files
- **P0-T06-M01** — 解析/校验 DTO、错误分类和 fixture 规范（completed）
  - 交付物：`src/transrealm/application/output_parser.py` 中的 DTO 与错误分类（`IssueCategory`、`OutputParseError`、`TranslationCandidate`、`ParseIssue`、`RepairDescriptor`、`ValidationReport`）、`tests/test_p0_t06_m01.py`
  - 验收证据：pytest 15 passed；Ruff/mypy 无问题；DTO 创建、错误分类、RepairDescriptor 尝试预算、ValidationReport 唯一性均已覆盖

- **P0-T06-M02** — 单 Segment parser/validator（completed）
  - 交付物：`src/transrealm/application/output_parser.py` 单 Segment 解析/校验实现（`OutputParser.parse/parse_or_raise`、markdown fence 提取、ID/类型/空值校验）、`tests/test_p0_t06_m02.py`
  - 验收证据：pytest 15 passed；Ruff All checks passed；mypy Success: no issues found in 57 source files；全量回归 pytest 305 passed；覆盖有效单 item、fence 修复、无效 JSON、缺 items/字段/ID、错 ID、重复 ID、空/非字符串译文、repair limit、repair descriptor 更新与 parse_or_raise 成功/失败。

- **P0-T06-M03** — 批量 items 的 ID/数量/顺序交叉校验（completed）
  - 交付物：`src/transrealm/application/output_parser.py` 批量顺序交叉校验逻辑、`tests/test_p0_t06_m03.py`
  - 验收证据：pytest 10 passed；Ruff All checks passed；mypy Success: no issues found in 58 source files；全量回归 pytest 315 passed；覆盖批量正序/错序/缺项/多余/空数组/部分反转/重复/未知 ID/warnings/notes/多问题。

- **P0-T06-M04** — 有限修复分类与恶意/异常输出矩阵（completed）
  - 交付物：`src/transrealm/application/output_parser.py` 翻译污染检测（`_CONTAMINATION_MARKERS`、`_is_contaminated`、CONTAMINATION issue）、`tests/test_p0_t06_m04.py`
  - 验收证据：pytest 18 passed；Ruff All checks passed；mypy Success: no issues found in 59 source files；全量回归 pytest 333 passed；覆盖修复分类（INVALID_JSON/EMPTY_TRANSLATION/DUPLICATE_ID/REPAIR_LIMIT 等可修复性）、非 dict item、缺 segment_id、冗余字段、markdown fence 污染、顶层数组、items 类型错误、修复消耗/上限、parse_or_raise、空数组、多问题报告。

- **P0-T06-M05** — Review、全回归和同步（completed）
  - 交付物：P0-T06 全 Task Code Review、全量回归（pytest 333 passed）、Ruff/mypy 通过；同步 `DEVELOPMENT_STATE.md` 与 `07_Developer_Task_List.md`，P0-T06 标记 completed，指针推进至 P0-T07-M01。
  - 验收证据：pytest 333 passed；Ruff All checks passed；mypy Success: no issues found in 59 source files；M05 现场结论 **ADAPT**（`07_Developer_Task_List.md` 中 M03 状态陈旧，已同步）。

## 7. 状态更新规则

- `ready`：要求明确，可立即开工；
- `in_progress`：已修改工作区但小目标未完成；
- `blocked`：缺少用户决定、凭据或外部资源；必须写清解除条件；
- `verification`：实现完成，正在测试或 Review；
- `completed`：功能测试、异常测试、Review 和必要文档同步全部完成。

`plan_alignment` 与状态分开维护：

- `pending_reality_check`：当前 Milestone 尚未完成现场核验；
- `FIT`：计划假设与现场一致；
- `ADAPT`：硬约束和验收不变，已记录内部实现调整及证据；
- `REPLAN`：存在重大偏差，必须记录完整偏差模板和解除条件。

禁止为了显得有进度而虚报状态。测试失败时保持 `in_progress` 或 `verification`；只有确有外部解除条件时才使用 `blocked`。`REPLAN` 只阻塞冲突部分，不自动阻塞可独立推进的范围内工作。
## 8. Agent 结束本次工作的条件

仅在以下任一条件成立时结束：

- 当前小目标完成、验证并已把下一小目标写入本文件；
- 遇到真实阻塞，已尽可能完成不受阻部分，并把解除条件写入本文件；
- 用户明确要求停止。

结束回复先报告实际结果，再报告测试和下一检查点。不要以“如果你愿意，我可以开始”结尾。
