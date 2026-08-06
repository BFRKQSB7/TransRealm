---
project: TransRealm
file_role: agent-entrypoint-and-runtime-checkpoint
protocol_version: 2
plan_alignment: FIT
current_phase: Phase 1
current_release: V1.0
current_task: P1-T01
current_milestone: P1-T01-M01
state: blocked
last_updated: 2026-08-06
baseline_commit: 5ef3be6
baseline_integrity: committed_and_verified
worktree_disposition: governance_commit_pending
gate_status: open
review_status: P0_independent_review_resolved
rollback_ref: 5ef3be6
pending_decision: DEC-P1-T01-FOUNDATION
decision_prompt: DEVELOPMENT_STATE.md#pending-decision
decision_result: pending
resume_milestone: P1-T01-M01
---

# 译境 / TransRealm — Agent 自动开工与开发状态

## 0. 唯一 Agent 交接入口

你正在接手 `D:\TransRealm` 的持续开发。**本文件是唯一交接入口。** 不要读取旧的 `AI_CONTEXT_INDEX.md` 或 `00_Project_Manager_Guide.md`；它们只为兼容旧链接而保留。

先读取本文件 frontmatter 和“当前开发现场”，再严格执行：

1. 确认工作目录为 `D:\TransRealm`，检查 Git staged、unstaged、untracked 和测试证据；不得覆盖、丢弃、reset、restore、clean 或删除既有工作。
2. 读取 `07_Developer_Task_List.md` 中 `current_task` 的完整定义；它定义目标、非目标、依赖、修改范围和验收。
3. 读取 `06_AI_Development_Guide.md`；它定义 FIT/ADAPT/REPLAN、最小设计门禁、实现流程和完成报告。
4. 按当前 Task 的“输入文档”读取必要契约：产品/范围读 `01_PRD.md` 与 `02_Development_Roadmap.md`；架构读 `03_Technical_Design.md` 与 `08_Architecture_Review.md`；数据库读 `04_Database_Schema.md`；Prompt/Context/输出读 `05_Prompt_Architecture.md`；高风险、例外、发布/回滚读 `09_Unattended_Development_Governance.md`；候选发布才读 `RELEASE_CHECKLIST.md`。
5. 在写代码前记录 FIT、ADAPT 或 REPLAN。FIT 直接执行；ADAPT 只改可逆内部实现；REPLAN 停止冲突部分并记录证据、最小替代方案、影响、回滚成本和待裁决项。
6. 状态为 `ready`、`in_progress` 或 `verification` 且没有 REPLAN 时，直接推进当前小目标：测试/验收样例 → 最小实现 → 功能与异常测试 → Review → 文档与本文件同步。
7. 完成或中断时，更新本文件中的实际结果、命令/输出、兼容性基线（受影响旧能力、旧测试、新测试和实测结果）、风险、阻塞、恢复动作和下一小目标。没有测试证据、旧功能回归、Review 或文档同步不得标记 `completed`。

只有产品或架构变化、破坏性或对外操作、用户专属凭据/文件、付费调用，或无法由代码/测试/Git 消除的实质歧义才询问用户。常规可逆选择自行决定。

## 1. 权威来源与冲突顺序

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
- 已完成的 P0-T01 至 P0-T08 默认保留，不做无证据的推倒重来；发现具体缺陷时以测试保护的最小修正处理。
- 未来 Task 中的类名、Manager/Service、文件落点和局部算法默认是参考实现，除非权威文档明确标注为强制契约。
- 无人开发的角色、风险、门禁、例外和发布/回滚规则以 `09_Unattended_Development_Governance.md` 为准。

### 待决策节点

- **pending_decision：** `DEC-P1-T01-FOUNDATION`
- **触发 Milestone：** P1-T01-M01
- **问题：** 选择后续六种格式共用的 format metadata、原始 bytes/span 表示和旧 TXT Project 升级策略。该选择决定 no-op byte identity、Revision 只替换目标 span 和 P1-T02 Project 容器的基础，不能由开发 Agent 自行猜测。
- **不可变约束：** 不重写 `001`–`007` migration；TXT no-op 必须字节一致；翻译仅改变目标 span；原编码/BOM/换行必须可恢复；metadata 与源内容版本同事务保存；缺失或错配安全失败；不实现其他格式或改变翻译状态机。
- **现场证据：** 当前 `TxtExporter` 按 Revision 顺序写 UTF-8，未保留原 bytes/encoding/BOM/换行；`SourceDocument` 当前只保存 format、encoding、source_hash、parser_version；P1-T01-M01 是后续 JSON/SRT/VTT/ASS/SSA 的共同底座。
- **候选方案：**
  1. 原始 bytes + 每 Segment byte span；保真最直接，但多字节编码/span 验证复杂。
  2. 原始 bytes + 格式专属定位 metadata；允许每格式安全定位，需严格契约避免五套分叉逻辑。
  3. 重序列化格式对象；拒绝，无法满足 byte identity。
- **技术负责人推荐：** 方案 2：持久化原始 bytes、encoding/BOM/newline 与版本化 format metadata；TXT 使用受验证的 byte/character replacement mapping，后续格式使用同一 metadata envelope 中的格式专属定位信息。理由：满足保真且不强迫 JSON/字幕共享错误的 span 模型。
- **待更新文档：** `03_Technical_Design.md` §9、`04_Database_Schema.md` §3/5、`07_Developer_Task_List.md` P1-T01、必要时 `01_PRD.md`。
- **验收/回滚条件：** 旧库升级有新 migration 与备份；TXT no-op/translated/error/metadata mismatch/不可写目标有 fixture；失败不污染数据库或目标文件；回滚使用迁移前备份或前向修复，不能删除用户数据。
- **resume_milestone：** P1-T01-M01

### 切换至决策 Agent

```text
请切换至决策 Agent。读取 D:\TransRealm\DEVELOPMENT_STATE.md 中的“待决策节点”。
只评估，不写业务代码。基于不可变约束、现场证据和候选方案，输出唯一推荐或明确保留项；说明否决理由、要更新的权威文档、验收、迁移/回滚条件和恢复 Milestone。完成后把 decision_result 与开发恢复提示词写回 DEVELOPMENT_STATE.md，并提醒用户切回开发 Agent。
```

### 切回开发 Agent

决策完成前不要开始 P1-T01-M01。决策 Agent 写回 `decision_result` 后使用：

```text
请切回开发 Agent。读取 D:\TransRealm\DEVELOPMENT_STATE.md 的 decision_result、resume_milestone 及更新后的权威文档。只实施已裁决范围；先重新完成 FIT/ADAPT/REPLAN，再继续目标 Milestone。不得重新讨论已裁决的产品/契约选择。
```

### 当前开发现场

- **基线事实：** `master` 的 P0 基线已在 `5ef3be6` 固化，治理/CI 基线已在 `90f1c70` 固化并推送至公开 GitHub `BFRKQSB7/TransRealm`。候选工作树仅包含尚未提交的决策节点治理文档改动。
- **工作树处置：** 必须保留现有 staged、unstaged、untracked 与用户数据；禁止 `reset --hard`、`restore`、`checkout` 覆盖、`clean` 或递归删除。`x.db` 与备份数据库已由 `.gitignore` 忽略。
- **基线状态：** 当前回滚 ref 为 `90f1c70`；pytest 498 passed、Ruff 通过、mypy 89 source files 无问题，Candidate hygiene CI 已成功。

### 当前 Task

- **Task：** P1-T01 — JSON / SRT / ASS / SSA / VTT round-trip
- **状态：** ready
- **完整定义：** `07_Developer_Task_List.md` 的“P1-T01”章节
- **前置依赖：** P0 基线 `5ef3be6` 已验证；完整质量门禁为 pytest 498 passed、Ruff 通过、mypy 89 source files 无问题。

### 当前小目标

- **Milestone：** P1-T01-M01 — 保真载体与 TXT 证明
- **状态：** blocked（等待 `DEC-P1-T01-FOUNDATION` 裁决）
- **plan_alignment：** FIT
- **目标：** 在旧 Project 可升级前提下持久化格式 metadata，并让 TXT no-op 字节一致、Revision 替换只改目标 span；metadata 缺失/错配安全失败。
- **Reality Check：** P0 的 SourceDocument/Segment、Revision Exporter、Run/Attempt/lease 和迁移链均已受提交与测试保护；M01 必须先重新核验 TXT 原 bytes/encoding/BOM/换行信息是否存在，再决定最小 metadata migration 和 exporter seam。
- **禁止事项：** 不重写 `001`–`007` migration；不实现 JSON/SRT/VTT/ASS/SSA；不改变翻译状态机、Project 格式或公开发布。
- **兼容性基线（裁决后填写）：** base commit 为 `90f1c70`；必须列出 P1-T01-M01 影响的既有 TXT 导入、Revision export、migration backup/upgrade 和 Run/Revision 测试 nodeid，先后各运行一次；新增 TXT 保真测试必须单独列出。全量 pytest 仅作附加门禁。

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
| P0-T07-M01 | 可重开执行骨架：新 migration、只读内置 Workflow、TranslationRun 与 SegmentAttempt 持久化及重开测试。 | completed |
| P0-T07-M02 | 原子领取与幂等：一个 pending Segment 只能被一个 owner 以新 version 领取并关联新 Attempt；重复幂等键返回既有记录、不重复执行；未过期 lease、错误状态和 stale version 被拒绝。 | completed |
| P0-T07-M03 | 成功完成事务：对有效 Validator 结果一次性保存响应审计、追加 Revision、更新 current revision 并完成 Segment/Attempt；任一故障切点全部回滚或保持可恢复 processing，迟到 owner 和 locked/current 已变化时不得提交。 | completed |
| P0-T07-M04 | 失败、取消与启动恢复：normalized permanent/retryable/validation 错误形成可解释 Attempt；仅 retryable failed 可重新排队并创建新 Attempt；取消保留既有 Revision/原因；启动只回收过期 processing，不覆盖人工/locked current。验证 transport retry 同 Attempt、repair/业务 retry 新 Attempt。 | completed |
| P0-T07-M05 | 恢复矩阵与 Task Gate：崩溃注入与重启矩阵验证请求前/后、响应审计、Revision、current/status 各切点崩溃后无伪 completed、无孤立 current revision、历史不覆盖；重复启动恢复幂等；lease 冲突与锁定回归不越 fencing；全量 pytest/Ruff/mypy、范围 Code Review 和文档/索引/状态同步。 | completed |
| P0-T08-M01 | 无 UI 成功闭环：新增 `application/translation_service.py`（TranslationService）复用 ContextComposer/PromptRenderer/OutputParser/ModelAdapter/TranslationRunService，把一个 pending Segment 垂直串成 compose→render→claim→call→validate→T07 finalize，生成可重开 Revision；空 Segment/缺 Profile/预算不足/非 running Run 在 claim 前拦截不发请求；adapter 错误与无效输出 finalize 为 failed Attempt。新增 `tests/test_p0_t08_m01.py` 11 项（含真实 OpenAICompatibleAdapter + FakeTransport 组合）。 | completed |
| P0-T08-M02 | 生产调用边界：新增 `adapters/http_transport.py`（StdlibHttpTransport，urllib.request + asyncio.to_thread，手动重定向循环：同源保留头、跨源/HTTPS 降级剥离 Authorization/Cookie/Proxy-Authorization、只跟随 http/https）、`adapters/credential_resolvers.py`（EnvironmentResolver/WindowsCredentialResolver(ctypes CredReadW)/build_resolver，secret 不进错误消息）、`application/adapter_factory.py`（compose_adapter 组合 Connection+Profile→adapter）。用 stdlib ThreadingHTTPServer 验证 endpoint 组合、超时/断连/截断分类、同源/跨源重定向 Authorization 边界、401/429/500/418 稳定归类、secret 不泄（错误与审计）、TranslationService 对真实本地 server 的完整闭环。Reality Check 结论 **FIT**：零运行时依赖（stdlib），`dependencies=[]` 不变。新增 `tests/test_p0_t08_m02.py` 33 项。 | completed |
| P0-T08-M03 | 失败与有限修复 E2E：`TranslationService.translate_segment` 增加 `max_repair_attempts=1` 参数与有界 repair 重呼——无效但 `issues[0].repairable`（空译文/污染）输出经 `finalize_failure(retryable=True)`→`retry_failed`→`start_attempt`（新幂等键、同 rendered prompt）创建新 Attempt；repair 层独立记账于 repair Attempt 的 `validator_summary`（repair_attempt/repair_reason）；非 repairable 或 repair 耗尽→`finalize_failure(retryable=False)` 永久失败。验证：repair 成功（空译文/污染）、repair 耗尽、`max_repair_attempts=0`/负值守卫、非 repairable 单 Attempt 不重呼、永久 adapter 错误不业务重试（retry_failed 拒绝）、崩溃（repair 第 2 次调用抛 SimulatedCrashError）后重启 recover_expired_leases 回收并重译成功且原 run 可解释。Reality Check 结论 **FIT**：无 schema/公共契约/新依赖。新增 `tests/test_p0_t08_m03.py` 8 项。 | completed |
| P0-T08-M04 | Revision 驱动 TXT 导出：新增 `application/exporter.py`（`TxtExporter`/`ExportError`，构造运行 migration、只读连接，`export_document(source_document_id, target_path, *, revision_overrides=None, encoding='utf-8')`）：按 `ORDER BY sequence` 原顺序取 Segment，默认写 `current_revision_id` 对应 Revision；`revision_overrides: dict[segment_id, revision_id]` 显式选择，逐 Revision 校验存在/归属（`segment_id`），未知 segment 键报错；任一 Segment 缺可用 Revision 即失败、不回退源文；同目录 `tempfile.mkstemp` + `os.replace` 原子写，编码/目标不可写清理临时文件并保持目标不变；默认 UTF-8。`SegmentRepository` 增 `get_source_document_by_id` 只读方法。Reality Check 结论 **FIT**：零新依赖（stdlib tempfile/os）。新增 `tests/test_p0_t08_m04.py` 13 项。 | completed |
| P0-T08-M05 | 非阻塞桌面闭环：新增 `ui/main_window.py`（三 Tab：Settings/Project/Translation）、`ui/pages.py`（SettingsPage/ProjectPage/TranslationPage，经 `ServiceWorker` 调 Application Service）、`ui/worker.py`（`ServiceWorker` 通用任务执行器 + `TranslationWorker` 逐 Segment 翻译，槽经信号排队到各自线程）。PySide6 6.11.1 + pytest-qt 4.5.0 依赖评估完成（LGPL/MIT、Qt 官方维护、`dependencies=["PySide6>=6.8,<6.12"]`，全量锁属 V1.0 Gate）。验证：UI 完整闭环（建项目/导入/建 Profile/翻译/导出，worker 线程执行、主线程 QTimer 在翻译中触发证明不阻塞）、取消在 Segment 边界停止、关闭 request_stop+有界 wait 收敛无 processing 遗留。Reality Check 结论 **FIT**。新增 `tests/test_p0_t08_m05.py` 4 项。 | completed |
| P0-T08-M06 | Phase 0 Gate：复核无 UI 与 GUI 两条入口对成功/失败/关闭/reopen 的 E2E 证据（M01–M05）；全量质量命令 pytest 488 passed、Ruff clean、mypy 87 files no issues；PyInstaller 6.21.0 `--onedir --windowed` build/start 可行性 smoke（~58s、~123 MB、主窗口可见、SQLite 由 frozen app 创建）；**发现并验证修复迁移 SQL 数据文件不被自动收集**（`--add-data "src/transrealm/migrations;transrealm/migrations"` 后 6 迁移全应用）；记录 Qt 插件状态（platforms/styles 等已收集、sqldrivers 缺属预期因仅用 stdlib sqlite3）；不冻结工具/artifact，smoke 产物在 `%TEMP%`。Reality Check 结论 **FIT**。 | completed |

Agent 可以在实现中细化这些小目标，但不得扩大当前 Task 的范围。

## 6. 每次更新本文件的格式

完成或中断小目标时更新以下内容，不新增流水账文件：

### Planning checkpoint

- **时间：** 2026-07-30
- **Agent：** Claude（规划 Agent）
- **完成内容：** 对当前 P0-T07-M01 至 V1.0 Release Candidate Gate 完成 Reality Audit、依赖重排、垂直 Milestone 重构和规划级架构审查；P0-T06 无剩余 Milestone，不安排重写；P1-T04 调整到 P1-T03 前，先提供 Project Profile 选择与基础 Glossary；明确 Attempt/lease/retry/Revision、格式保真、Project 双形态与安全导入、UI worker 和 Release Gate 契约。用户裁决 V1.0 保留 `.aiproject` + 高级用户开放目录两种互通 Project 形态。
- **修改文件：** 仅规划/治理文档：`02_Development_Roadmap.md`、`03_Technical_Design.md`、`04_Database_Schema.md`、`05_Prompt_Architecture.md`、`07_Developer_Task_List.md`、`08_Architecture_Review.md`、`DEVELOPMENT_STATE.md`、旧 Agent 路由文档。
- **验证方式：** 只读检查 Git、代码、migration、依赖和测试分布；规划文档 diff/交叉引用/路径/编号审查。未运行测试；历史 `333 passed` 仅保留为上一代码检查点证据，不作为本次重新验证。
- **未完成：** P0-T07-M01 仍未开始；current pointer、state 和 `plan_alignment` 未推进。
- **风险/阻塞：** 工作树仍包含大量未提交业务代码和 tests，HEAD 只到 P0-T02-M02；开始实现前必须形成受保护、可恢复的代码基线并重新验证。V1.0 Project 双形态已由用户裁决，无剩余需要改变产品范围/技术栈的规划裁决项。
- **恢复动作：** 执行 Agent 读取本文件，进入 P0-T07-M01；先检查 Git 未提交现场，在不覆盖当前工作树的前提下形成可恢复 Git 基线（保护范围含 tracked、untracked、staged additions/deletions，并记录恢复方法），再执行 M01 Reality Check 和 `07` 的行为切片。保护完成前不得新增 M01 业务实现，禁止从 HEAD 覆盖现有工作或提前进入未来 Task。

### Last code checkpoint

- **时间：** 2026-08-06
- **Agent：** Claude（执行 Agent）
- **完成内容：** 完成 P0-T08-M06 Phase 0 Gate。E2E/GUI review：复核无 UI 与 GUI 两条入口对成功/失败/关闭/reopen 的证据——M01 无 UI 成功闭环（可重开 Revision、真实 adapter+fake transport、空 Segment/缺 Profile/预算不足/非 running 不发请求）、M02 生产调用边界（stdlib transport 重定向 Authorization 边界、401/429/500/418 稳定归类、secret 不泄、真实本地 server 闭环）、M03 失败与有限修复 E2E（repair 新建 Attempt、永久错误不业务重试、崩溃重启 lease 恢复重译）、M04 Revision 驱动 TXT 导出（原子写、缺 Revision 不回退源文）、M05 非阻塞 GUI（完整闭环/主线程 QTimer 不阻塞/取消在 Segment 边界/关闭收敛无 processing、Attempt 全终态）；GUI 错误路径经 `task_error`→`_handle_error`→status 标签确认存在。全量质量命令通过：pytest 488 passed、Ruff All checks passed、mypy Success no issues in 87 source files。**打包 smoke：** PyInstaller 6.21.0（dev 工具，不写 pyproject、不冻结）+ hooks-contrib 2026.6；`--onedir --windowed` 单目录 build ~58s、体积约 123 MB（PySide6 主导）；exe 启动进程存活、主窗口 "TransRealm" 经 EnumWindows 可见、`~/.transrealm/project.sqlite` 由 frozen app 创建。Qt 插件：platforms/qwindows.dll/styles/iconengines/imageformats/tls 等自动收集；应用只用 stdlib sqlite3、不导入 QtSql，故 sqldrivers 缺失属预期。**关键发现并验证修复：** 迁移 SQL 数据文件（`transrealm/migrations/*.sql`）不被 PyInstaller 自动收集——初始冻结应用仅建空 `schema_migrations`、无法应用迁移；加 `--add-data "src/transrealm/migrations;transrealm/migrations"` 后全部 6 个迁移应用、11 张业务表创建成功。记录观察：DPI 150% 下窗口物理约 1754×597（Qt 布局最小宽度+WM，外观非阻塞）。smoke 产物在 `%TEMP%\transrealm_smoke_20260806\`（build/dist/截图），属临时证据，已清理进程与 smoke 创建的 `~/.transrealm`。
- **修改文件：** `03_Technical_Design.md`（§10 补充 Phase 0 build/start smoke 与迁移 SQL `--add-data` 发现）；`README.md`（新增"打包 smoke"节与命令）；`07_Developer_Task_List.md`（P0-T08-M06 completed、P0-T08 标记 completed）；`DEVELOPMENT_STATE.md`（指针推进至 P1-T01-M01，Phase 1/V1.0）。`02/04/05/index` 无需改动：无 schema/数据格式/Prompt 契约/路由变化，打包已在 `03` §10 覆盖，Phase 0 打包承诺在 `02` 已写。
- **测试命令：** `py -3.12 -m pytest -q`；`py -3.12 -m ruff check src tests`；`py -3.12 -m mypy src tests`；`py -3.12 -m PyInstaller --noconfirm --clean --onedir --windowed --name transrealm --paths src --add-data "src/transrealm/migrations;transrealm/migrations" <入口>`
- **测试结果：** 全量回归 pytest 488 passed；Ruff All checks passed；mypy Success: no issues found in 87 source files；PyInstaller build/start 可行性 smoke 成功（见完成内容）。
- **未完成：** P1-T01-M01 未开始（当前指针，ready + pending_reality_check）。
- **风险/阻塞：** 无技术阻塞。PyInstaller 未写进 `pyproject.toml`（Phase 0 不冻结工具），正式依赖锁/体积/UPX/图标/签名/杀毒/WAL 恢复属 V1.0 Release Gate；smoke 时窗口物理尺寸受 DPI/布局影响为外观观察，V1.0 再做布局 QA。
- **恢复动作：** 读取本文件；当时的小目标为 P1-T01-M01，状态 ready，plan_alignment pending_reality_check。开工前先核验 SourceDocument/Segment 持久化、`TxtExporter` seam 与旧 TXT Project 升级路径，完成 Reality Check 后从保真载体与 TXT 证明的垂直切片开始，不越出 P1-T01。

### Previous code checkpoint

- **时间：** 2026-08-04
- **Agent：** Claude（执行 Agent）
- **完成内容：** 完成 P0-T08-M05 非阻塞桌面闭环。新增 `src/transrealm/ui/worker.py`（`ServiceWorker` 通用任务执行器 + `TranslationWorker` 逐 Segment 翻译循环）、`ui/pages.py`（`SettingsPage`/`ProjectPage`/`TranslationPage`，全部经 worker 调 Application Service，含 `import_file`/`export_to`/`translate` 免对话框测试入口）、`ui/main_window.py`（三 Tab 主窗口，构造即启动 ServiceWorker 与 TranslationWorker 线程；`closeEvent` 先 `request_stop()` 再 `thread.quit()`+有界 `wait()` 收敛）。**关键修复：** 直接调用 `moveToThread` 后对象的 `@Slot` 方法会在调用线程执行（线程亲和性只对信号连接生效），故 worker 槽改为经 `run_requested`/`start_translate` 信号触发（排队到各自线程），SQLite/Provider/模型调用真正不阻塞主线程。取消经主线程直接置位的 `_stop_requested` 标志在 Segment 边界生效。**依赖：** 安装 PySide6 6.11.1 + pytest-qt 4.5.0，`pyproject.toml` `dependencies=["PySide6>=6.8,<6.12"]`、dev 加 `pytest-qt>=4.2`。Reality Check 结论 **FIT**（P0-T08 预授权；版本/许可 LGPL+MIT/安全/锁定/打包已记录）。新增 `tests/test_p0_t08_m05.py` 4 项（pytest-qt）：UI 完整闭环（建项目/导入/建 Profile/翻译/导出，翻译在 worker 线程、主线程 QTimer 在翻译中触发且 progress<total 证明不阻塞）、取消在 Segment 边界停止（progress<total）、关闭收敛（closeEvent 后无 processing Segment、Attempt 全部终态）。测试用 `_wait_finished`（连接 flag + `waitUntil`）替代跨线程 `waitSignal`（后者会在 worker 槽运行前提前返回）。
- **修改文件：** `src/transrealm/ui/worker.py`、`ui/pages.py`、`ui/main_window.py`（新增）；`src/transrealm/ui/__init__.py`（docstring）；`src/transrealm/infrastructure/repositories/segment_repository.py`（`list_source_documents_by_project`）；`pyproject.toml`（PySide6/pytest-qt 依赖）；`tests/test_p0_t08_m05.py`（新增）；`07_Developer_Task_List.md`（P0-T08-M05 标记 completed）；`03_Technical_Design.md`（§10 补充 Phase 0 桌面壳实现说明）；`DEVELOPMENT_STATE.md`（指针推进至 P0-T08-M06）。`02/04/05/index` 无需改动：无 schema/数据格式/Prompt 契约变化，TXT E2E/GUI 路由已覆盖 `ui/`。
- **测试命令：** `py -3.12 -m pytest -q`；`py -3.12 -m ruff check src tests`；`py -3.12 -m mypy src tests`
- **测试结果：** 全量回归 pytest 488 passed（M05 新增 4 项）；Ruff All checks passed；mypy Success: no issues found in 86 source files。
- **未完成：** P0-T08-M06 未开始。
- **风险/阻塞：** 无技术阻塞。已知取舍：关闭时 `thread.wait(5000)` 若当前段模型调用超长会超时（Phase 0 可接受，T07 lease 兜底）；`request_stop` 跨线程布尔标志依赖 GIL 可见性（Phase 0 可接受）；PySide6 wheel 大（数百 MB），正式打包/体积/杀毒属 V1.0 Release Gate。
- **恢复动作：** 读取本文件；当时的小目标为 P0-T08-M06，状态 ready，plan_alignment pending_reality_check。开工前先复核全量质量命令与 M01–M05 E2E 证据，确认打包候选（PyInstaller）及 PySide6 hook 支持，完成 build/start 可行性 smoke 后同步文档与状态，不越出 P0-T08。

### Previous code checkpoint

- **时间：** 2026-08-03
- **Agent：** Claude（执行 Agent）
- **完成内容：** 完成 P0-T08-M04 Revision 驱动 TXT 导出。新增 `src/transrealm/application/exporter.py`（`TxtExporter`/`ExportError`）：构造运行 migration（与其他 Application Service 一致），只读连接；`export_document(source_document_id, target_path, *, revision_overrides=None, encoding='utf-8')` 按 `ORDER BY sequence` 原顺序取 Segment，默认写 `current_revision_id` 对应 Revision 文本；`revision_overrides: dict[segment_id, revision_id]` 显式选择并逐 Revision 校验存在/归属（`segment_id`），未知 segment 键报错；任一 Segment 缺可用 Revision 即失败、不回退源文；同目录 `tempfile.mkstemp` + `os.replace` 原子写，编码失败（UnicodeEncodeError/LookupError）/目标不可写清理临时文件并保持目标不变；默认 UTF-8（源编码/BOM 保真属 P1-T01）。`SegmentRepository` 增 `get_source_document_by_id` 只读方法（文档存在性校验）。Reality Check 结论 **FIT**：零新依赖（stdlib tempfile/os）。新增 `tests/test_p0_t08_m04.py` 13 项：默认 current 按原顺序导出（含顺序/UTF-8 round-trip）、缺失/部分翻译失败无文件、invalid/cross-segment/未知 segment override 失败、显式非当前有效 Revision 覆盖生效、编码失败保留旧目标且无临时残留、Revision 校验失败保留旧目标、目标目录缺失失败、文档不存在失败。
- **修改文件：** `src/transrealm/application/exporter.py`（新增）；`src/transrealm/infrastructure/repositories/segment_repository.py`（`get_source_document_by_id`）；`tests/test_p0_t08_m04.py`（新增）；`07_Developer_Task_List.md`（P0-T08-M04 标记 completed）；`03_Technical_Design.md`（§9 补充 Phase 0 TxtExporter 实现说明）；`DEVELOPMENT_STATE.md`（指针推进至 P0-T08-M05）。`02/04/05/index` 无需改动：无 schema/数据格式/Prompt 契约/新领域变化，Exporter 路由已覆盖。
- **测试命令：** `py -3.12 -m pytest -q`；`py -3.12 -m ruff check src tests`；`py -3.12 -m mypy src tests`
- **测试结果：** 全量回归 pytest 484 passed（M04 新增 13 项）；Ruff All checks passed；mypy Success: no issues found in 82 source files。
- **未完成：** P0-T08-M05 未开始。
- **风险/阻塞：** 无技术阻塞。已知取舍：TXT 导出默认 UTF-8（源编码/BOM 保真属 P1-T01 `03` §9 V1.0 基线）；空文档导出为空文件（非静默回退）；`os.fdopen` 极端异常路径（fd 泄漏）未覆盖（实际不可达）。
- **恢复动作：** 读取本文件；当时的小目标为 P0-T08-M05，状态 ready，plan_alignment pending_reality_check。开工前先核验 P0-T08 GUI/线程/关闭契约与 Application Service 线程安全边界，评估 PySide6/pytest-qt 版本/许可/安全/锁定/打包影响，完成 Reality Check 后从最小主窗口垂直切片开始，不越出 P0-T08。

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
  - 交付物：`003_add_import_uniqueness.sql`、原子导入 Repository API、不可变内容版本策略、Agent 路由文档、回归测试与契约同步
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
- **P0-T08-M01** — 无 UI 成功闭环（completed）
  - 交付物：`src/transrealm/application/translation_service.py`（`TranslationService`/`TranslationServiceError`）、`tests/test_p0_t08_m01.py`
  - 验收证据：pytest 430 passed（M01 新增 11 项）；Ruff All checks passed；mypy Success: no issues found in 75 source files；成功闭环生成可重开 Revision，Attempt 审计完整；空 Segment/缺 Profile/预算不足/非法 budget/非 running Run 不发请求；adapter 错误与无效输出 finalize failed Attempt。
- **P0-T08-M02** — 生产调用边界（completed）
  - 交付物：`src/transrealm/adapters/http_transport.py`（`StdlibHttpTransport`）、`adapters/credential_resolvers.py`（`EnvironmentResolver`/`WindowsCredentialResolver`/`build_resolver`）、`application/adapter_factory.py`（`compose_adapter`）、`tests/test_p0_t08_m02.py`
  - 验收证据：pytest 463 passed（M02 新增 33 项）；Ruff All checks passed；mypy Success: no issues found in 79 source files；stdlib urllib transport + ctypes wincred 零新依赖；同源重定向保留 Authorization、跨源/HTTPS 降级剥离；超时/断连/截断稳定分类；401/429/500/418 分类与 secret 不泄（错误与审计）；TranslationService 对真实本地 server 完整闭环。
- **P0-T08-M03** — 失败与有限修复 E2E（completed）
  - 交付物：`src/transrealm/application/translation_service.py`（repair 有界重呼）、`tests/test_p0_t08_m03.py`
  - 验收证据：pytest 471 passed（M03 新增 8 项）；Ruff All checks passed；mypy Success: no issues found in 80 source files；repairable 无效输出（空译文/污染）经一次重呼创建新 Attempt（新幂等键）并记账于 validator_summary；非 repairable/repair 耗尽 finalize 永久失败；永久 adapter 错误不业务重试；崩溃重启后 T07 lease 恢复并重译成功。
- **P0-T08-M04** — Revision 驱动 TXT 导出（completed）
  - 交付物：`src/transrealm/application/exporter.py`（`TxtExporter`/`ExportError`）、`src/transrealm/infrastructure/repositories/segment_repository.py`（`get_source_document_by_id`）、`tests/test_p0_t08_m04.py`
  - 验收证据：pytest 484 passed（M04 新增 13 项）；Ruff All checks passed；mypy Success: no issues found in 82 source files；默认 current Revision 按原顺序导出；显式 override 校验存在/归属；缺失/跨 Segment/无效 Revision 失败无文件；编码/目标不可写失败原子、保留旧目标、无临时残留；不回退源文。
- **P0-T08-M05** — 非阻塞桌面闭环（completed）
  - 交付物：`src/transrealm/ui/main_window.py`、`ui/pages.py`、`ui/worker.py`、`tests/test_p0_t08_m05.py`；`pyproject.toml`（PySide6>=6.8,<6.12 运行时、pytest-qt>=4.2 dev）
  - 验收证据：pytest 488 passed（M05 新增 4 项）；Ruff All checks passed；mypy Success: no issues found in 86 source files；三 Tab 主窗口经 worker 线程完成导入/Profile/翻译/导出；翻译中主线程 QTimer 触发且 progress<total 证明不阻塞；取消在 Segment 边界停止；关闭收敛无 processing 遗留、Attempt 全终态。

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
