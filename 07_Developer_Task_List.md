# 译境 / TransRealm

# Developer Task List V4

## 1. Task规范

每个未完成 Task 必须包含：

- Task 编号、Phase/Release、Priority 和状态；
- Reality Audit 结论（`KEEP / REFINE / SIMPLIFY / MERGE / SPLIT / DEFER / REMOVE / DECISION_REQUIRED`）；
- 目标、非目标和用户价值；
- 前置依赖与现有现场；
- 输入文档和权威来源；
- 硬约束与参考方案；
- 执行 Agent 可自主决定的内容；
- 修改范围上限与交付能力；
- 功能、异常、安全和兼容性验收；
- 测试证据、Code Review、文档同步和完成条件。

状态使用 `pending / in_progress / blocked / verification / completed`；Milestone 的 `ready` 和 Reality Check 结论只记录在 `DEVELOPMENT_STATE.md`。一个 Task 只完成一组内聚的用户能力，不把后续功能顺手扩入当前 Task。

### 1.1 执行解释规则

本文件定义“做成什么”，不默认垄断“内部如何实现”。所有现有和未来 Task 均按以下规则解释：

- **硬约束：** 目标、非目标、前置依赖、功能/异常验收、兼容性、安全边界，以及权威文档明确规定的公共契约和数据格式。
- **参考实现：** 内部类名、Manager/Service 名称、私有 API、文件落点、局部算法及未获架构批准的存储建议；除非明确标注为“强制契约”，否则执行 Agent 可根据现场调整。
- **修改范围：** 定义允许触碰的最大领域边界，不要求列出的每个文件都必须修改，也不授权顺手修改范围外模块。
- **交付物：** 定义必须交付的能力与证据，不自动要求创建同名类或抽象层。
- **Milestone：** 是待 Reality Check 验证的垂直切片假设，不因写入本文件就自动高于代码和测试事实。

执行 Agent 必须保持硬约束和验收不变，但对范围内最小实现拥有判断权。不得因计划提到某个 Manager、数据库、事件总线或扩展点就机械创建；也不得借“现场判断”擅自改变产品行为、公共契约、持久化格式、依赖或 Task 范围。

## 2. 自动执行规则

`07` 定义稳定 Task，`DEVELOPMENT_STATE.md` 定义当前正在执行的小目标和恢复检查点。

Agent 收到 `DEVELOPMENT_STATE.md` 后，无真实阻塞时自动读取当前 Task、加载指定文档并开始，不需要再次请求开工授权。每个 Milestone 在写测试或代码前必须按 `06_AI_Development_Guide.md` 完成 Reality Check，并在状态文件记录 `FIT`、`ADAPT` 或 `REPLAN`。

- `FIT`：直接执行。
- `ADAPT`：硬约束和验收不变，执行 Agent 自主调整内部实现并记录证据。
- `REPLAN`：停止冲突部分，记录计划假设、现场证据、最小替代方案和待裁决事项；不得硬改。

完成小目标后先更新状态文件，再进入下一小目标；只有当前 Task 的全部验收完成，才修改本文件中的 Task 状态。

## 3. 完成流程

```text
读取硬约束与验收
 -> Reality Check（FIT / ADAPT / REPLAN）
 -> 测试或验收样例
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
  -> P0-T08 TXT 翻译端到端与最小 GUI Shell
  -> P1-T01 JSON/SRT/ASS/SSA/VTT round-trip
  -> P1-T02 Project 双形态/离线迁移与安全导入
  -> P1-T04 Project Profile 选择与基础 Glossary
  -> P1-T03 自动模式与工作台模式
  -> P1-T05 V1.0 Release Candidate Gate
```

本文件预先定义已批准依赖链中的全部 Task 与垂直 Milestone。`07` 只负责稳定规划、范围、依赖和验收；`DEVELOPMENT_STATE.md` 是当前 Task、当前 Milestone、真实工作区、测试证据和恢复动作的唯一运行时来源。新增或调整未来规划不得自动推进运行指针；只有执行 Agent 验证依赖并实际开工时，才原子更新状态文件。

每个未完成 Task 下的 **Reality Audit** 是 2026-07-30 的规划取证结果，不是完成状态。分类含义：`KEEP` 保留目标；`REFINE` 修正边界/依赖/验收；`SIMPLIFY` 删除不必要抽象；`MERGE` 合并重复交付；`SPLIT` 拆成垂直检查点；`DEFER` 延后；`REMOVE` 移出范围；`DECISION_REQUIRED` 等待用户裁决。后续代码变化可使该结果陈旧，因此每个 Milestone 仍须独立执行 `FIT / ADAPT / REPLAN`。

每个 Milestone 必须交付一个可独立验证的行为，并在同一切片中包含必要测试和最小实现。Milestone 表使用“行为与完成条件”，不得采用“先写全部 DTO/Repository、再写全部 UI”的纯水平切分，也不得预填测试通过数。证据要求：代码 Task 记录实际 pytest/Ruff/mypy；Adapter 使用可控 fake transport/server；GUI 必须实际启动并执行 pytest-qt/交互验证；恢复、备份和格式 round-trip 必须有数据库或文件级显式断言。

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
- **状态：** completed
- **目标：** 实现 TXT 文件 Parser，生成稳定的 Segment 领域模型，支持导入到 Project 数据库并读取；为后续 JSON/字幕格式 parser 奠定接口。
- **非目标：** 不实现 JSON/SRT/ASS/VTT、GUI、模型调用、翻译流程、RAG/TM。
- **前置依赖：** P0-T01 已完成；Project/SQLite/Migration 基础可用。
- **输入文档：** `01_PRD.md` 第 9/10 节；`02_Development_Roadmap.md` Phase 0；`03_Technical_Design.md` 第 4/6 节；`04_Database_Schema.md` 第 3 节；`06_AI_Development_Guide.md`。
- **修改范围：** `domain/segment.py`、TXT parser、`application/import_service.py`、Segment Repository、`002_add_source_document_and_segment.sql` 与后续 P0-T02 修正 migration、pytest 测试；不修改 PySide6 页面、Prompt、Model Adapter。
- **交付物：** Segment 与 SourceDocument 领域模型、TXT parser、Import Service、Segment Repository、`002`/`003` migration、pytest 自动化测试。
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
- **测试证据：** `py -3.12 -m pytest -v` 62 passed；`py -3.12 -m ruff check src tests` All checks passed；`py -3.12 -m mypy src tests` Success: no issues found in 29 source files。覆盖同 hash 幂等、内容变化保留旧版本、空文件幂等、Segment 失败整次回滚和唯一约束 migration 冲突保留原数据。
- **文档同步项：** 若表字段或 migration 规则改变，更新 `04_Database_Schema.md`；若 Segment/Parser 契约改变，更新 `03_Technical_Design.md`；不得擅自扩大 PRD。

## 10. P0-T03 — Model Profile 与 Provider Connection

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
- **目标：** 建立 migration 安全前置、Provider Connection、Model Capability 与 Model Profile 的非敏感持久化和应用服务，为 Adapter 提供稳定输入。
- **非目标：** 不发 HTTP、不读取或保存凭据正文、不实现 Prompt、Attempt/Revision、GUI 或在线 capability discovery。
- **前置依赖：** P0-T02 完成；M00 用于补齐 P0-T01 尚未实现的升级备份验收，并在完成后约束 P0-T03 起所有新 migration。
- **输入文档：** `01` 模型配置与安全范围；`03` 第 3/5/11 节；`04` 第 2/3/5/6 节；`05` 第 2–5 节；`06`。
- **修改范围：** migration backup、领域模型、新编号 migration、Repository、Application Service、pytest；不修改 Adapter、Prompt、UI 或 Segment 状态机。
- **交付物：** SQLite 一致性升级备份；非敏感 Connection/Capability/Profile 模型、表、约束、CRUD API 和测试。
- **功能验收：** pending migration 执行前有可打开备份；Connection 保存 endpoint/provider type/timeout/retry policy/credential reference；Profile 引用 Connection 并保存 model/template/output/context/default params/capability；关闭重开语义一致。
- **异常验收：** 备份失败不迁移；WAL、权限、Unicode/长路径可验证；明文秘密不得进入模型/schema/错误；无效 timeout、配置、外键失败不污染既有数据。
- **测试证据：** backup/restore 与 migration failure fixture、Repository round-trip、secret boundary、pytest/Ruff/mypy。
- **文档同步项：** `03`、`04`；Profile 契约变化时更新 `05`；同步 `07`、索引和状态文件。

| Milestone | 范围与完成条件 |
|---|---|
| P0-T03-M00 | 仅在有 pending migration 时用 SQLite backup API 创建一致性备份；失败阻断、备份可发现/可打开；不建 Profile 表。 |
| P0-T03-M01 | Provider Connection（含 credential reference 语法与 secret 边界）领域模型、migration、Repository/Application Service 和安全测试。 |
| P0-T03-M02 | Model Capability/Profile 模型、持久化、Connection 外键与关闭重开测试。 |
| P0-T03-M03 | timeout/retry policy、JSON 配置和关闭重开的一致性验收。 |
| P0-T03-M04 | Task review、全回归、编号文档/索引/状态同步。 |

## 11. P0-T04 — OpenAI-compatible Model Adapter

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
- **目标：** 建立 Provider-neutral Adapter 协议及 OpenAI-compatible HTTP 实现，统一请求、响应、能力与错误。
- **非目标：** 不做原生多厂商 API、Prompt 渲染、输出语义校验、Attempt/Revision 或 GUI。
- **前置依赖：** P0-T03 完成，Connection/Profile 输入稳定。
- **输入文档：** `01` 模型范围；`03` 第 5/8/11 节；`05` 第 6/8/9 节；`06`。
- **修改范围：** `adapters/`、Adapter DTO/Protocol、受控 HTTP transport、fake server/transport 测试；不访问 SQLite。
- **交付物：** Adapter protocol、OpenAI-compatible 实现、request/response/usage/capability/error DTO、有限 transport retry。
- **功能验收：** 正确映射 endpoint/model/参数；返回文本/结构化结果、finish reason、usage、request ID；capability 控制可发送参数；错误统一分类。
- **异常验收：** timeout、断连、429/5xx、401/403、无效 JSON/缺字段、本地服务停止均稳定分类；永久错误不重试；Authorization/秘密不进入日志与异常。
- **测试证据：** `py -3.12 -m pytest -v` 224 passed；`py -3.12 -m ruff check src tests` All checks passed；`py -3.12 -m mypy src tests` Success: no issues found in 47 source files。覆盖 M01–M04 全部 fixture：endpoint/model/参数映射、响应/usage/错误分类、transport retry（指数退避与 Retry-After）、capability 降级、resolver 边界与错误脱敏。
- **文档同步项：** `03`、必要时 `05`、`07`、索引和状态文件。

| Milestone | 范围与完成条件 | 状态 |
|---|---|---|
| P0-T04-M01 | Adapter Protocol、DTO、capability contract 与 normalized error。 | completed |
| P0-T04-M02 | OpenAI-compatible 成功请求/响应映射。 | completed |
| P0-T04-M03 | timeout、限流、网络/服务/认证/参数错误分类与有限 transport retry。 | completed |
| P0-T04-M04 | capability 降级、credential resolver 边界与脱敏验收。 | completed |
| P0-T04-M05 | Review、全回归和文档/状态同步。 | completed |

## 12. P0-T05 — 最小 Context Budget / Prompt / 输出请求契约

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
- **目标：** 实现规则式最小 Context Budget、Profile 驱动 Prompt 渲染、Context Manifest 和机器可解析输出请求契约。
- **非目标：** 不实现 RAG、智能 TM、Character Data、网络调用、响应解析或 Attempt。
- **前置依赖：** P0-T03/P0-T04 契约稳定。
- **输入文档：** `01` Context/高级用户范围；`03` 第 4/7 节；`05` 全文；`08` 第 4.4 节。
- **修改范围：** Context composer/budget、Prompt renderer、manifest/output contract DTO 与测试。
- **交付物：** 当前/相邻 Segment 和锁定 Glossary 的预算规则、Prompt renderer、输出 schema/contract、Context Manifest。
- **功能验收：** 当前 Segment 必入且不截断；先预留固定 Prompt/输出；可选上下文按优先级裁剪；输出含稳定 Segment ID；Manifest 记录来源、估算、裁剪和 Profile/template 版本。
- **异常验收：** 预算不足时降批或明确失败；未知模板变量、无效 Profile/参数、缺 Segment 不生成请求；override 不得移除安全输出包装。
- **测试证据：** 确定性 prompt/hash、预算边界与裁剪断言、非法模板/override 测试、pytest/Ruff/mypy。
- **文档同步项：** `03`、`05`、`07`、索引和状态文件。

| Milestone | 范围与完成条件 | 状态 |
|---|---|---|
| P0-T05-M01 | Context Candidate/Manifest/预算 DTO。 | completed |
| P0-T05-M02 | 当前与相邻 Segment 的最小规则预算。 | completed |
| P0-T05-M03 | 定义已存在锁定 Glossary 时的候选接口、裁剪顺序与预算不足行为；无 Glossary 数据时以空候选完成验证。 | completed |
| P0-T05-M04 | Profile 模板渲染与不可破坏输出契约。 | completed |
| P0-T05-M05 | 可复现性 review、全回归和同步。 | completed |

## 13. P0-T06 — Output Parser / Validator

- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
- **目标：** 将模型原始输出解析为受控结构，严格验证请求 Segment 映射，并定义有限修复分类。
- **非目标：** 不发请求、不写 Attempt/Revision、不实现 JSON/字幕保真或 GUI。
- **前置依赖：** P0-T05 输出契约稳定。
- **输入文档：** `03` 第 2/8 节；`05` 第 6/9 节；`06`。
- **修改范围：** parser、validator、result/error DTO、repair descriptor 与 fixtures。
- **交付物：** 单/批量 parser、ID/数量/顺序/类型校验、可修复/不可修复错误和修复上限接口。
- **功能验收：** 仅符合契约且与请求 Segment 集合严格对应的结果成为候选译文。
- **异常验收：** fence/解释污染、无效 JSON、重复/缺失/未知 ID、错序、空/非字符串译文均拒绝；达到修复上限返回失败，不伪造结果。
- **测试证据：** 正反 fixture matrix、批量错配与污染输出断言、修复上限、pytest/Ruff/mypy。
- **文档同步项：** `03`、`05`、`07`、索引和状态文件。

| Milestone | 范围与完成条件 | 状态 |
|---|---|---|
| P0-T06-M01 | 解析/校验 DTO、错误分类和 fixture 规范。 | completed |
| P0-T06-M02 | 单 Segment parser/validator。 | completed |
| P0-T06-M03 | 批量 items 的 ID/数量/顺序交叉校验。 | completed |
| P0-T06-M04 | 有限修复分类与恶意/异常输出矩阵。 | completed |
| P0-T06-M05 | Review、全回归和同步。 | completed |

## 14. P0-T07 — Attempt / Revision / 恢复状态机

- **Task 编号：** P0-T07
- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** pending；当前运行指针见 `DEVELOPMENT_STATE.md`。
- **Reality Audit：** `REFINE + SPLIT + SIMPLIFY`。Segment 已有 `status/current_revision_id/version/lease_*` 占位和事务基础；WorkflowDefinition、TranslationRun、SegmentAttempt、TranslationRevision、状态迁移、lease 原子操作和恢复均不存在。保留状态机目标，改成行为切片；只实现内置只读 Workflow，不提前实现 Workflow CRUD、继承、节点引擎或队列基础设施。
- **目标：** 建立可审计、幂等、不会覆盖人工译文的翻译执行记录；在崩溃、重复提交、租约过期和取消后，使每个 Segment 保持可解释并可安全恢复。
- **非目标：** 不增加文件格式、GUI、自动/工作台模式、通用调度队列、并行 worker 池、Workflow 编辑器、RAG/TM 或项目包。
- **用户价值：** 翻译不会因程序中断或重试静默丢失、重复覆盖或伪装成完成；用户可以追踪失败原因并保护已确认译文。
- **前置依赖：** P0-T03 至 P0-T06 的当前工作树能力；开始前必须确认未提交代码和 migrations `003`–`005` 仍存在并重新运行其验证，不把 Git HEAD `P0-T02-M02` 误当作完整基线。
- **现有现场：** `segments` 已有恢复占位列；SQLite transaction、Adapter 错误分类/transport retry、Context Manifest DTO、Prompt hash 和 Output Validator 可复用。没有 T07 schema、Repository 原子状态操作、业务重试或恢复测试。
- **输入文档和权威来源：** `01` 状态/恢复与版本保护；`03` §6/8/11；`04` §3/5/6；`05` §3/6/7；`06`。用户可见恢复和锁定行为来自 `01/03`，数据格式与约束来自 `04`，Attempt 可追踪内容来自 `05`。
- **硬约束：**
  - 已发布 migration 不重写；新增结构使用新编号，并兼容 `002` 已存在的 `current_revision_id/version/lease_*`。
  - Segment 状态只允许 `pending -> processing -> completed|failed`、retryable `failed -> pending`、过期或安全恢复 `processing -> pending`；状态非 NULL。
  - lease claim 必须是 `pending + expected version + lease 为空或已过期` 的原子写，并设置新 owner/未来 expiry；回收只匹配过期 processing。完成/失败写入必须验证 claim 的 owner/version 且 lease 尚未过期，过期 worker 的迟到结果不得覆盖新 owner（fencing）。UTC 时间由可控时钟提供。初始 lease 覆盖有界 timeout/retry/backoff 与完成事务余量；worker 可在 retry sleep、响应和 Segment 边界观察取消。真实长调用若无法安全界定，才可 `ADAPT` 增加保持相同 fencing 的最小续租。
  - claim 身份由 lease owner + Segment version 表示，并持久化到对应 Attempt（或等价 claim token），使重启后可识别 stale Attempt；成功 claim 后、第一次外部模型请求前创建 Attempt，不为满足旧措辞在 Segment 再增加可分叉的 `active_attempt_id`。
  - Segment 状态保持 `pending/processing/completed/failed`；取消不新增 Segment 状态。Attempt 状态为 `created/succeeded/failed/cancelled`，Run 状态为 `running/completed/failed/cancelled`；取消仍持有效 lease 的 Attempt 后 Segment 返回 pending，已完成事务保持 completed。
  - 一次 Application 层逻辑模型调用对应一个 SegmentAttempt。Adapter 内保持相同逻辑请求的 transport retry 和一次 capability degradation 记在同一 Attempt；输出 repair 再次调用模型、或 failed Segment 重新执行时必须创建新 Attempt 和新幂等键。各层重试上限不得相乘为无限重试。
  - idempotency key 必须由数据库唯一约束保护；重复提交返回既有 Attempt/结果且不得再次调用外部模型。具体键格式属于参考方案。
  - Attempt 至少在重启后保留：Run/Segment/Profile 与 Profile/template/capability 快照或稳定版本、Prompt hash、Context/参数与 Validator 摘要、请求 ID、状态、retryable、usage/latency、错误、开始/完成时间。原始 Prompt/响应正文遵守可配置、脱敏、可清理策略；Revision 与最小审计字段不可随 Debug 清理消失。
  - 有效输出只追加 Revision；Revision 不覆盖历史。自动完成前必须确认 current revision 未被并发改变且不是 locked；人工或锁定的 current Revision 不得被自动结果替换。默认导出读取 current Revision，显式选择只能选择属于该 Segment 的有效 Revision。
  - 成功完成必须在一个事务中保存响应审计、Revision、current revision 与 completed；任一写入失败都不得留下伪 completed。Profile/Workflow 的后续修改或删除不得使历史 Attempt 无法解释。
  - 内置 WorkflowDefinition 只需不可变版本、可验证 definition hash 和 Run 引用；V1.0 本 Task 不实现用户 Workflow 副本。
- **参考方案：** 新编号 migration；声明式状态枚举；共享 `DatabaseConnection` 的原子 Repository 操作；JSON snapshot 或受控 artifact reference 保存审计信息；version 作为 optimistic fencing token。名称、表拆分和 JSON 字段布局不是唯一实现。
- **执行 Agent 可自主决定：** 私有类/文件名、Repository 数量、SQL 组织、时间与 ID 生成器注入方式、审计快照的规范化 JSON 结构、是否用 trigger 或表重建保证同 Segment revision 约束；不得改变上述持久化语义、状态、重试、锁定或安全行为。
- **修改范围上限：** 新 migrations、相关 domain/application/infrastructure 状态与持久化代码、fault/recovery 测试，以及必要的 `03/04/05/07/index/state` 同步；不得触碰 UI、格式 parser/exporter 或依赖。
- **交付能力：** 可创建内置 Workflow 与 Run；原子 claim 并先建 Attempt；成功/失败/取消持久化；Revision/current/locked 保护；过期 lease 恢复；幂等重复提交。
- **功能验收：** 正常执行产生可重开读取的 Run/Attempt/Revision；Segment 只经合法状态完成；重复幂等键不产生第二次请求或 Revision；人工 current Revision 保持；恢复后 pending/retryable 工作可继续。
- **异常验收：** lease 冲突、stale version、永久错误、可重试错误、取消、请求前后及事务各写入切点崩溃均有明确状态；无伪 completed、孤立 current revision、历史覆盖或无限重试。
- **安全与兼容性验收：** migration 升级备份规则继续生效；旧 Project 可升级；secret 不进入 Attempt、Prompt/response artifact、错误或日志；Profile/Workflow 历史引用不被破坏。
- **测试证据要求：** 可控时钟、可控 fake model/fault injection、数据库重开、并发/陈旧 owner、事务回滚、幂等和锁定测试；记录实际 pytest/Ruff/mypy 命令与结果，不预填数量。
- **Code Review 重点：** 原子条件是否真正位于 SQL/事务边界；迟到响应能否越过 fencing；transport 与业务重试是否重复；current/locked 竞态；原始响应和错误是否泄密；是否创建了空壳 Workflow/Manager。
- **文档同步项：** schema/状态/重试契约变化同步 `03/04/05`；Task、索引和运行现场同步 `07/index/state`；产品范围不变，不修改 `01`。
- **完成条件：** M01–M05 全部通过；全量回归和 Review 无未解决阻塞；文档与真实 schema/状态一致；仅此时把 Task 标为 completed。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P0-T07-M01 | **可重开执行骨架：** 新/旧 Project 应用新 migration 后都能读取一个版本化只读内置 Workflow；可创建引用它的 Run，并在第一次外部请求前持久化包含快照/审计基础的 Attempt。无效 Workflow/Profile/Segment 引用、重复定义版本或 migration 中断必须回滚。先执行 Reality Check；内部表/类拆分为参考方案。 |
| P0-T07-M02 | **原子领取与幂等：** 一个 pending Segment 只能被一个 owner 以新 version 领取并关联新 Attempt；重复幂等键返回既有记录、不重复执行；未过期 lease、错误状态和 stale version 被拒绝。以可控 UTC 时钟验证过期边界和数据库重开。 |
| P0-T07-M03 | **成功完成事务：** 对有效 Validator 结果一次性保存响应审计、追加 Revision、更新 current revision 并完成 Segment/Attempt/Run 统计；任一故障切点全部回滚或保持可恢复 processing，迟到 owner 和 locked/current 已变化时不得提交。 |
| P0-T07-M04 | **失败、取消与启动恢复：** normalized permanent/retryable/validation 错误形成可解释 Attempt；仅 retryable failed 可重新排队并创建新 Attempt；取消保留既有 Revision/原因；启动只回收过期 processing，不覆盖人工/locked current。验证 transport retry 同 Attempt、repair/业务 retry 新 Attempt。 |
| P0-T07-M05 | **恢复矩阵与 Task Gate：** 覆盖请求前、请求后、响应审计、Revision、current/status 前后崩溃，重复启动恢复、lease 冲突、锁定回归；执行全量 pytest/Ruff/mypy、规划范围 Code Review 和编号文档/索引/状态同步。不得以测试矩阵替代缺失行为。 |

## 15. P0-T08 — TXT 翻译端到端与最小 GUI Shell

- **Task 编号：** P0-T08
- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SPLIT + SIMPLIFY`。TXT 导入、Profile/Connection、Context、Prompt、Adapter 协议、Validator 可复用；生产 HTTP transport/credential resolver、Application 层闭环、TXT exporter、PySide6/UI worker 均不存在，`pyproject.toml` 也未声明运行时或 Qt 测试依赖。保留薄 GUI，但先完成无 UI 闭环，不建立通用队列/事件总线。
- **目标：** 让用户在 Windows 桌面入口中完成 Project 打开、TXT 导入、Profile 选择、受控翻译、进度/错误查看和 Revision 导出，并验证真实 Application Service 与 worker 边界。
- **非目标：** 不实现自动/工作台产品模式、JSON/字幕、复杂批量调度、多 Profile/Glossary 管理、高级 Prompt 编辑或正式发布包。
- **用户价值：** 第一次得到可实际操作且重启后可解释的 TXT 翻译闭环，而非孤立组件集合。
- **前置依赖：** P0-T07 完成；现有 P0-T03–T06 现场先纳入可恢复 Git 基线并重新验证。PySide6、pytest-qt、生产 HTTP/凭据实现及依赖锁定必须在相应 Milestone Reality Check 中基于现实需要引入和审查。
- **现有现场：** `ui` 为空；只有抽象 `Transport/CredentialResolver`，无生产 transport；没有 exporter/orchestrator。`dependencies=[]`，只有 pytest/Ruff/mypy 开发依赖。
- **输入文档和权威来源：** `01` 核心流程/UI/凭据；`02` Phase 0；`03` §2/3/4/5/9/10/11；`05`；`06`。
- **硬约束：** GUI 只调用 Application Service；SQLite connection/cursor、Provider、Parser 和长操作不在主线程；跨线程传 DTO/不可变数据。一个 worker/thread 拥有其数据库连接和任务生命周期，不跨线程共享连接。关闭时停止接收新工作并按 T07 取消/lease 语义收敛，不靠强杀线程伪完成。生产 transport 必须有 timeout、重定向/Authorization 边界和 secret 脱敏；本机兼容 HTTP endpoint 可用，跨主机重定向不得携带凭据。TXT 导出默认使用 current Revision，显式选择必须验证归属；缺 Revision 不回退到源文或未验证响应。新增依赖必须解决本 Task 的可验证问题、固定兼容范围并进入可重复环境；不得仅为未来扩展引入框架。
- **参考方案：** 一个面向用例的翻译应用服务、受维护 HTTP client 或满足测试的标准库 transport、环境变量与 Windows Credential resolver、Qt worker object/thread、临时文件后原子替换导出。具体组件名、页面文件和信号命名可调整。
- **执行 Agent 可自主决定：** 在已批准 PySide6/pytest-qt 边界内落地 Qt 依赖、选择 HTTP client、组织 Qt worker、设计进度 DTO/页面布局/批大小和内部组合方式；所有依赖须记录版本、许可、安全、锁定与打包影响。只有选择当前 Task/技术栈未授权的依赖时才按 `REPLAN` 处理。
- **修改范围上限：** translation application orchestration、生产 adapter composition、TXT exporter、最小 `ui/`、依赖/锁定与 E2E/Qt tests；不增加其他格式或模式。
- **交付能力：** 无 UI 与 GUI 两条入口共享同一核心翻译用例；成功/失败进入 T07；受控 TXT 导出；非阻塞、可关闭的薄桌面 shell。
- **功能验收：** fake 与本地受控 HTTP endpoint 均可完成至少一个 TXT Segment；Attempt/Revision/Segment 可重开；GUI 完成核心操作且状态真实；导出文本来自有效 Revision。
- **异常验收：** 缺 Profile/凭据、endpoint 断开/超时/停止、无效输出、不可写导出、窗口关闭和重启均给可操作错误；GUI 不冻结；T07 数据不被绕过或破坏。
- **安全与兼容性验收：** token 不进入 Project/UI/日志/异常；重定向不泄露 Authorization；Unicode/长路径/只读目录可验证；旧 Project migration 后可操作。
- **测试证据要求：** 无 UI E2E、fake/local HTTP server、pytest-qt、实际启动和交互 smoke、关闭/reopen、pytest/Ruff/mypy；Phase 0 只做候选打包工具的 build/start 可行性 smoke，不宣称正式绿色版。
- **Code Review 重点：** UI 是否直接访问 infrastructure；连接/worker 线程所有权；取消竞态；生产 transport 安全；导出是否绕过 Revision；依赖是否必要；错误 DTO 是否泄密。
- **文档同步项：** `02/03/07/index/state`；依赖和启动命令同步项目配置/README；只有产品承诺变化才修改 `01`。
- **完成条件：** M01–M06 通过，无 UI 和实际 GUI 证据齐全，Phase 0 build/start 可行性已记录，核心数据可重开且无未解决 P0 缺陷。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P0-T08-M01 | **无 UI 成功闭环：** 给定已导入 TXT、Profile 和 fake Adapter，一个应用用例完成 compose/render/call/validate/T07 finalize，生成可重开 Revision；空 Segment、缺 Profile、预算不足不发请求。 |
| P0-T08-M02 | **生产调用边界：** 通过受控本地 HTTP server 验证真实 transport 与配置 composition；环境变量及已支持的 Windows credential reference 可解析，timeout/redirect/认证/响应错误稳定归类且不泄密。新增依赖先做 Reality Check 和打包影响记录。 |
| P0-T08-M03 | **失败与有限修复 E2E：** Adapter 错误、无效输出和一次 repair 进入正确 Attempt/Segment；永久错误不业务重试，repair 新建 Attempt，窗口/进程重启后仍可解释并按 T07 恢复。 |
| P0-T08-M04 | **Revision 驱动 TXT 导出：** 当前或显式有效 Revision 按原 Segment 顺序导出；缺失/跨 Segment/无效 Revision、编码和不可写目标失败时不留下半文件，不回退未验证文本。 |
| P0-T08-M05 | **非阻塞桌面闭环：** 最小主窗口与 Settings/Project/Translation 入口通过同一 Application Service 导入、选择 Profile、启动/取消翻译、显示进度/错误并导出；pytest-qt 和人工操作证明主线程可响应、关闭可恢复。 |
| P0-T08-M06 | **Phase 0 Gate：** 对成功/失败/关闭/reopen 做 E2E 与 GUI review；运行全量质量命令；用一个候选打包工具完成本机 build/start 可行性 smoke 并记录依赖/Qt 插件问题，不冻结最终工具或发布 artifact；同步文档与状态。 |

## 16. P1-T01 — JSON / SRT / ASS / SSA / VTT round-trip

- **Task 编号：** P1-T01
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SPLIT`。Parser Protocol/Registry、稳定 Segment 和 TXT seam 可复用；format metadata 持久化、Exporter contract 和五类格式均不存在。先以 TXT 证明通用保真载体，再逐格式垂直交付，不重写 registry。
- **目标：** 导入并翻译 JSON 与字幕文件，同时精确保留不可翻译结构和格式元数据，使导出可由 golden fixture 判定。
- **非目标：** 不支持 Markdown/EPUB/HTML/Word/Ren'Py，不自动修复损坏格式，不改变核心翻译状态机。
- **用户价值：** 用户可安全处理 V1.0 承诺格式，不必手工还原 JSON 结构、字幕时间轴或 ASS/SSA 样式。
- **前置依赖：** P0-T08；T07 Revision/export 选择语义稳定。
- **现有现场：** SourceDocument/Segment 无格式 metadata；TXT parser 丢弃空行/首尾空白，尚无通用 round-trip 能力或 fixture 目录。
- **输入文档和权威来源：** `01` §5/21；`02` §7；`03` §4/9；`04` §3/5；`06`。
- **硬约束：** SourceDocument 逻辑复用身份包含 Project、源 bytes hash、format 和会改变 Segment 映射的 parser identity/version；P1-T01 用新 migration 扩展 `003` 的内容 hash 唯一性，不重写 `003`。stable key 来自格式结构而非仅数组下标；格式 metadata 与源内容版本同事务保存。无翻译导出必须字节一致；翻译导出必须保留原编码/BOM、换行风格和所有非目标字节或经该格式明确允许的等价表示。JSON 只翻译 string leaf value，key、非字符串值和容器不翻译；可配置路径选择若需要后置为明确能力，不在 V1.0 猜测智能字段。SRT/VTT 保留 cue 时间、标识、settings 和非目标行；ASS/SSA 仅替换 Dialogue 的 Text 字段，保留 section、Format、style、event 字段顺序、注释、标签和转义。损坏/不支持输入默认拒绝且不污染 Project，不做静默修复。
- **参考方案：** 保存原始 bytes + 可定位的替换 span/结构路径；Parser/Exporter registry；每格式 golden fixture。具体 metadata schema、解析库或手写 parser 由 Reality Check 决定；新依赖必须证明比最小实现更安全并评估打包。
- **执行 Agent 可自主决定：** metadata 编码、解析算法、fixture 组织、JSON path 表示和 ASS/SSA 共用程度；不得放宽格式保真、目标选择或错误原子性。
- **修改范围上限：** Parser/Exporter contracts、format metadata 的新 migration/领域持久化、五格式实现和 fixtures；不修改翻译/模型业务语义。
- **交付能力：** 六种 V1.0 格式使用同一 Revision-based export seam；每格式有明确可翻译单元和 round-trip 证据。
- **功能验收：** 每格式 no-op byte identical；替换后只目标 span 改变；重新解析导出文件得到同一结构/时间轴/样式并包含选定 Revision。
- **异常验收：** malformed、编码、重复/缺失 stable key、metadata 丢失、Revision 错位和不可写目标均失败且不污染 Project/目标文件。
- **安全与兼容性验收：** 不执行 JSON/字幕内容；限制极端嵌套/文件大小的可操作失败；新 migration 升级旧 TXT Project，旧 TXT 行为不回归。
- **测试证据要求：** 每格式多组 golden/no-op/translated/error fixture，字节 diff 与语义重解析断言，pytest/Ruff/mypy。
- **Code Review 重点：** 是否重序列化并破坏格式；stable key 是否稳定；metadata 与源文是否可错配；第三方 parser 依赖与恶意输入；是否复制五套无共用价值的框架。
- **文档同步项：** `02/03/04/07/index/state`；若用户可见格式语义与上述契约冲突则 `REPLAN`，不直接改 `01`。
- **完成条件：** M01–M06 全部通过，六格式矩阵与错误矩阵可重复，TXT 既有测试无回归。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P1-T01-M01 | **保真载体与 TXT 证明：** 在旧 Project 可升级前提下持久化格式 metadata，并由通用 Exporter seam 让 TXT no-op 字节一致、Revision 替换只改目标 span；metadata 缺失/错配安全失败。 |
| P1-T01-M02 | **JSON 垂直闭环：** string leaf value 生成稳定结构路径 Segment，no-op 字节一致，翻译仅替换 value token；保留 key/order/number/escape/whitespace，malformed/深度或错位 Revision 不污染数据。 |
| P1-T01-M03 | **SRT 垂直闭环：** cue text 可翻译，序号/标识/时间轴/空行/换行保真；非法时间轴、重复定位和多行文本异常有 fixture。 |
| P1-T01-M04 | **VTT 垂直闭环：** 保留 WEBVTT header、cue ID、timing settings、NOTE/STYLE/REGION 和文本标签；非法 cue 或 metadata 不静默降级为 SRT。 |
| P1-T01-M05 | **ASS/SSA 垂直闭环：** 依据 Events Format 只替换 Dialogue Text，保留 section/style/comment/tag/escape/逗号字段；两格式各有 golden 与 malformed fixture，不创建两套无必要框架。 |
| P1-T01-M06 | **全格式 Gate：** 统一执行 no-op/translated/error/不可写/旧库升级矩阵、全回归和 Code Review；同步格式契约、索引和状态，不预填通过数。 |

## 17. P1-T02 — Project 双形态、离线迁移、备份与安全导入

- **Task 编号：** P1-T02
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SPLIT + SIMPLIFY`。WAL-safe migration 备份已存在且不得重写；`.aiproject`/开放目录、manifest、安全导入隔离均不存在。复用一致性 snapshot seam，以一个 Project 模型支持两种互通视图，并保持“升级备份”和“离线项目转移”两个 use case。
- **目标：** 让同一逻辑 Project 可在单文件 `.aiproject` 与高级用户开放目录之间安全导入/导出，并在跨电脑、损坏、恶意条目或 migration 失败时保护目标数据。
- **非目标：** 不做多人协作、增量同步、自动合并、目录实时 watcher、双向文件热同步、云存储、加密容器或自定义压缩框架。
- **用户价值：** 普通用户可用单文件备份/转交；高级用户可检查和管理开放目录；两者不复制不一致 WAL 数据、不泄露凭据或覆盖现有项目。
- **前置依赖：** P1-T01 完成；migration backup 与 Project/附件/格式 metadata 稳定。
- **现有现场：** SQLite backup API、migration history/checksum 和失败备份可复用；没有 Project manifest、开放目录 contract、归档、安全路径校验、附件 hash 或双形态 fixtures。
- **输入文档和权威来源：** `01` Project/迁移/秘密；`03` §3；`04` §2/7；`08` §7/8；`06`。
- **硬约束：** 两种形态共享同一 Project 身份、manifest、SQLite schema、hash、相对路径、秘密排除和 migration 契约；开放目录不是第二套存储，也不靠文件 watcher 与数据库双向热同步。其 `manifest.json + project.sqlite + attachments` 为权威，其他 source/translation/config 目录只有经 manifest 声明才是附件/导出物。单文件归档只包含这些受控条目。若源数据库包含零个或多个 Project，导出不得静默选第一个或夹带其他 Project，实施可选择明确拒绝或生成隔离 snapshot。manifest 版本、schema、软件版本、文件大小/hash 和相对路径必须在打开/落地前验证。开放目录加载也必须执行与归档相同的路径、hash、秘密和版本校验；`.aiproject` 导入先进入新隔离 staging。拒绝绝对路径、盘符/UNC、`..`、路径归一化逃逸、重复/大小写或 Unicode 等价冲突、link/junction 类 entry、重复关键 entry，以及 entry 数/单项/总大小或压缩比超限。校验与 migration 全通过后才原子安装到新目标；失败不覆盖现有 Project，也不自动删除唯一可诊断备份。秘密、默认日志、credential value 不进入任何形态；credential reference 可保留但目标机缺凭据时给可操作提示。只支持文档列出的 `format_version`，未知新版本明确拒绝；schema 仅向前 migration，不 downgrade。
- **参考方案：** 目录为 canonical staging、标准 ZIP + JSON manifest 作为单文件视图、SQLite backup API、原子 rename；具体阈值在 fixture 和 release matrix 中固定，归档库选择属实现决定。
- **执行 Agent 可自主决定：** manifest 扩展字段、staging 清理策略、过滤 snapshot 或拒绝多 Project、开放目录中可读导出物布局、压缩级别和内部错误表示；不得自行选择会产生明显不同结果的用户行为。V1.0 统一采用：导入时 Project ID 冲突则创建新的本地 Project 身份并保留 manifest 中的 source/origin ID 供追踪；名称冲突以确定性后缀建议新名称，未经用户显式确认不覆盖既有目标。不得削弱双形态互通、路径/hash/秘密、原子安装和兼容性约束。
- **修改范围上限：** Project manifest/双形态 use case、path validation、snapshot/import orchestration、附件处理和 tests；不改翻译核心、在线同步或现有 migration backup 语义。
- **交付能力：** 可创建/打开开放目录，可 pack/unpack `.aiproject`，可在两种形态间 round-trip、migration 并继续核心工作；可解释拒绝恶意/损坏/不兼容 Project。
- **功能验收：** 开放目录创建/重开保持同一 Project；开放目录 pack 为 `.aiproject` 再导入后核心状态和附件一致；WAL 写入场景 snapshot 数据一致；跨临时“机器”导入并完成核心读取/导出。
- **异常验收：** 两种形态中的 tamper、truncation、缺 manifest/db/附件、版本不兼容、空间/权限/migration/目标冲突，以及归档 path traversal/link/zip bomb 均在目标落地前失败且原数据保持。
- **安全与兼容性验收：** 两种形态 secret scan 零命中；归档不能写出 staging，开放目录不能引用根外路径；旧受支持 schema 经备份/migration 打开；未知未来 format/schema 不猜测。
- **测试证据要求：** pack/import E2E、WAL、跨目录、tamper、path normalization/traversal/link/bomb、secret、失败隔离、pytest/Ruff/mypy。
- **Code Review 重点：** zip-slip 和资源耗尽；先写后验；多 Project 夹带；直接复制 WAL DB；临时目录权限/清理；manifest 双重权威；复写 migration backup。
- **文档同步项：** `02/03/04/07/index/state` 及用户迁移/恢复草稿；产品承诺变化才更新 `01`。
- **完成条件：** M01–M05 全部通过，安全导入 matrix 无未解决高风险，原始数据与备份可恢复。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P1-T02-M01 | **共享 manifest 与开放目录：** 建立一个可创建/重开、可验证的开放目录 Project；manifest 固定 format/schema/software/file/hash/size/relative path，未知版本、根外路径、link 和重复关键 entry 被拒绝。 |
| P1-T02-M02 | **一致性单文件导出：** 从一个逻辑 Project 的开放目录/活动数据库用 SQLite backup 和附件清单生成 `.aiproject`，manifest/hash 可复验，secret/log 不入包；零/多 Project 不被静默打包。 |
| P1-T02-M03 | **隔离安全导入：** `.aiproject` 只解到 staging，逐 entry 限额与 hash 校验；tamper、缺附件、大小写/Unicode 冲突、traversal/link/bomb 不触碰最终目标，成功得到同契约开放目录。 |
| P1-T02-M04 | **双形态迁移与原子安装：** 开放目录或 staging snapshot 备份后执行向前 migration 和 Project 验证，成功才安装/打开；版本、权限、空间、migration、名称冲突失败保留原目标并给恢复动作。 |
| P1-T02-M05 | **跨机器与双形态 Gate：** 开放目录 -> `.aiproject` -> 隔离“另一台 Windows” -> 开放目录 round-trip，验证缺 credential 的恢复、核心状态/附件、篡改/secret matrix、全回归和文档同步。 |

## 18. P1-T04 — Project Profile 选择与基础 Glossary

- **Task 编号：** P1-T04
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SIMPLIFY + SPLIT`。Connection/Profile CRUD、外键/RESTRICT、capability snapshot 和 locked Glossary context seam 已部分提前完成；不得重写“Profile 管理服务”。主要缺口是 Project 级选择、历史引用保护、Glossary 持久化/注入和管理 UI。为使自动/工作台模式有真实配置和 Glossary 输入，本 Task 调整到 P1-T03 之前。
- **目标：** 让用户在 Project 中安全选择和管理多个 Connection/Profile，并维护 Project-scoped 基础 Glossary，使锁定术语确定性进入现有 Context Manifest。
- **非目标：** 不做自动术语提取、智能 TM、RAG、Character Data、Profile 插件、原生 Provider 协议或批量导入高级术语工具。
- **用户价值：** 用户可切换模型配置并保持重启状态；重要术语在不同 Project 间隔离且不会被上下文裁剪策略静默忽略。
- **前置依赖：** P1-T02；P0-T08 GUI 核心；现有 Profile/Connection 服务经 Reality Check 确认。
- **现有现场：** ProviderConnection/ModelProfile 模型、Repository/Service、共享 Connection 和删除 RESTRICT 已有；ContextComposer 接受 `glossary_candidates` 并将其视为 locked，但没有 GlossaryEntry/schema/UI/Project 选择。
- **输入文档和权威来源：** `01` 模型/Glossary/Context；`03` §3/5/7/10；`04` §3/5；`05` §2/4/5/9；`06`。
- **硬约束：** Project 的 active Profile 选择重启保持且必须引用有效 Profile；历史 Attempt 保存快照并保持可解释，被历史或当前 Project 引用的 Profile 删除不得级联破坏记录。Glossary 以 Project 隔离；source/target 非空，scope/priority 有稳定验证；V1.0 只自动注入 locked 项，unlocked 项可保存/编辑但不进入 Prompt，避免未经确认术语影响翻译。locked 项在当前 Segment 之后、邻居之前按 priority 和稳定次序注入；超预算时不截断当前源文，Manifest 记录 selected/pruned。秘密仍只存在 resolver 边界。
- **参考方案：** 新 migration、Glossary Repository/use case、Project active profile FK 或受约束配置、将 locked entries 映射为现有 `ContextCandidate`；具体表/类名和 UI 布局可变。
- **执行 Agent 可自主决定：** active selection 的规范化表或 Project 字段、同词唯一域、priority 数值范围、UI 控件和删除错误表示；须保持 Project 隔离、历史保护和注入顺序。
- **修改范围上限：** Project/Profile selection、Glossary schema/domain/application/repository、现有 composer 集成、薄管理 UI 与 tests；不实现模式策略或新 Adapter。
- **交付能力：** 多 Connection/Profile 管理与 Project 选择；基础 Glossary CRUD/lock/priority/scope；Context 注入和 Manifest；重启恢复。
- **功能验收：** active Profile 和 Glossary 重开一致；不同 Project 同词互不影响；locked 高优先级确定性注入；Profile 参数仍经过 capability 过滤。
- **异常验收：** 无效/被引用 Profile 删除、缺 Connection、空/重复/冲突术语、跨 Project ID、非法 scope/priority、预算不足均有明确结果且事务不污染数据。
- **安全与兼容性验收：** migration 升级旧 Project；删除策略不破坏 Attempt/Run；secret 不显示/导出；Project 双形态都包含非敏感 Profile/Glossary/选择并通过 P1-T02 校验。
- **测试证据要求：** 复用/扩展现有 Profile tests，Project selection 重开、Glossary CRUD/隔离/锁定/预算/manifest、pytest-qt UI、pytest/Ruff/mypy。
- **Code Review 重点：** 是否重复 Profile Service；FK/delete 历史；跨 Project 查询；Composer 是否直接查 SQLite；术语排序是否确定；UI 是否泄密。
- **文档同步项：** `03/04/05/07/index/state`；Roadmap 依赖顺序同步 `02`；范围不变。
- **完成条件：** M01–M05 通过，已有 Profile/Context 测试无回归，P1-T03 可只消费稳定 use case 而无需补数据模型。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P1-T04-M01 | **Project Profile 选择：** 复用现有 CRUD，使 Project 可选择/更换 active Profile 并重开恢复；无效引用和被 Project/历史 Attempt 使用的删除给明确错误，不重写已通过的服务。 |
| P1-T04-M02 | **Project-scoped Glossary：** 新旧库 migration 后可 CRUD source/target/scope/priority/lock/origin；跨 Project、空值、重复策略和事务回滚可验证。 |
| P1-T04-M03 | **确定性 Prompt 注入：** 只查询当前 Project locked entries，映射到现有 ContextCandidate；按 priority/稳定次序在邻居前选择，Manifest 记录 selected/pruned，预算不足不截断当前源文。 |
| P1-T04-M04 | **薄管理 UI：** 通过 Application use case 管理 Connection/Profile 选择和 Glossary lock/priority/scope；被引用删除、缺凭据和验证错误可操作，UI 不直接查库。 |
| P1-T04-M05 | **持久化/双形态/GUI Gate：** 验证重启、Project 隔离、开放目录与 `.aiproject` round-trip、预算与 UI 回归，执行全量质量命令、Review 和文档同步。 |

## 19. P1-T03 — 自动模式与工作台模式

- **Task 编号：** P1-T03
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SPLIT + SIMPLIFY`。翻译核心、Profile/capability 和薄 GUI 将由前序提供；缺模式持久化、自动默认策略、工作台人工 Revision/锁定、override 和模式恢复。模式是同一 Application Service 的交互策略，不创建第二套 orchestrator/state machine。
- **目标：** 为普通用户提供最少操作的自动路径，为高级用户提供受 capability/Validator/Revision 保护的参数、Prompt override、人工编辑与锁定工作台。
- **非目标：** 不做节点 Workflow、自动模型推荐/调参、RAG/TM/World State、Profile 插件或候选多模型比较。
- **用户价值：** 普通用户无需理解 Prompt/参数即可翻译；高级用户可在不破坏输出和恢复安全的前提下控制模型和确认译文。
- **前置依赖：** P1-T04 完成；P0-T08 GUI/worker/T07 核心稳定。
- **现有现场：** Model Profile/capability filtering、PromptRenderer 不可移除输出 wrapper、Validator 与 Revision 锁定 seam 可复用；无 mode/override/UI 行为。
- **输入文档和权威来源：** `01` §3/4/16/17/18/21；`02` Phase 1；`03` §2/10；`05` §2/8/9；`06`。
- **硬约束：** 两种形态共享同一状态机、Application Service、Validator、Attempt/Revision 和 worker。自动模式使用 Project active Profile、只读内置 Workflow 和保守默认参数，隐藏高级配置但不隐藏错误/恢复。工作台只展示 capability 支持参数，Adapter 仍做最终过滤；不支持参数不发送。预设模板只读，用户修改保存为带 parent template version 的 Override；override 不能移除 Segment ID、output wrapper、格式保护、Validator 或安全限制。人工编辑追加 `origin=user` Revision 并成为 current；锁定 current 后自动翻译不能替换。模式切换只改变后续 UI/策略展示：若当前有运行中 Run，先提示用户继续当前 Run 或取消，不能在运行中原地改变其 Profile/Workflow/参数；不丢配置或 Project，关闭遵守 T07/P0-T08 取消恢复。
- **参考方案：** Project mode/config + override 表或受约束 JSON、共享 view model/use cases、capability-driven controls。具体 widget、状态管理和持久化布局为参考实现。
- **执行 Agent 可自主决定：** 自动批大小/默认顺序、参数控件布局、mode 配置 schema 细节、进度刷新机制和 override 编辑体验；不得改变用户可见安全边界。
- **修改范围上限：** mode/override 持久化、Application 策略、现有 GUI/worker 扩展、manual Revision/lock use case、Qt/E2E tests；不改格式/package 或模型协议。
- **交付能力：** 自动批量路径；工作台进度/参数/Profile/Prompt override/人工 Revision/锁定；模式和配置重启恢复。
- **功能验收：** 新 Project 默认进入简单可用模式；自动模式从导入到导出；工作台显示真实状态和受支持参数；人工修订/锁定生效；配置与 override 重开一致。
- **异常验收：** 无 active Profile/capability、unsupported param、invalid override、运行中切换、取消/关闭、failed Segment 和 stale Revision 均有明确行为；任何模式不能绕过校验或 locked current。
- **安全与兼容性验收：** override/debug 不含 secret；旧 Project 获得安全默认模式；Project 双形态都保留 mode/override 非敏感配置；不可执行用户模板代码。
- **测试证据要求：** pytest-qt 两模式、配置/override 重开、capability filtering、manual/lock、切换/中断恢复、实际交互 smoke、pytest/Ruff/mypy。
- **Code Review 重点：** 是否复制 orchestrator；UI 参数与 Adapter filter 双保险；override 是否可破坏 contract；锁定竞态；模式状态是否散落多处；主线程阻塞。
- **文档同步项：** `02/03/05/07/index/state`；用户行为与 `01` 冲突才 `REPLAN`。
- **完成条件：** M01–M05 通过，普通/高级用户核心旅程和恢复均可实际操作，无第二套状态机或未批准高级功能。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P1-T03-M01 | **自动模式最小旅程：** 新/旧 Project 有安全默认 mode；使用 active Profile/内置 Workflow 完成导入、pending 翻译、状态反馈和导出，缺配置时给一步可恢复引导，重启保持。 |
| P1-T03-M02 | **capability-aware 工作台：** 显示真实 Segment/Attempt 进度和 Profile；仅呈现/发送支持参数，参数变更形成下一 Attempt 的快照，不影响已完成历史。 |
| P1-T03-M03 | **受控 Prompt Override：** 预设只读，override 记录 parent version 并可重开；未知变量、失效父版本和试图移除输出/格式/校验边界时拒绝，不执行模板代码。 |
| P1-T03-M04 | **人工 Revision 与锁定：** 工作台编辑追加 user Revision、切换 current 并 lock/unlock；自动迟到结果和重译不能覆盖 locked current，导出遵循选择语义。 |
| P1-T03-M05 | **模式切换与 GUI Gate：** 自动/工作台切换、运行中取消、窗口关闭和重启不丢 Project/配置/结果；完成 pytest-qt、实际可用性 smoke、全回归、Review 和同步。 |

## 20. P1-T05 — V1.0 异常恢复与 Release Candidate Gate

- **Task 编号：** P1-T05
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** pending
- **Reality Audit：** `REFINE + SPLIT + SIMPLIFY`。底层已有部分 migration/adapter/validator 异常测试，但没有跨 Task release matrix、长文本、正式 dependency lock、Windows artifact 或用户文档。该 Task 只收口和修复阻塞缺陷，不新增产品能力；GitHub 创建/推送/发布是单独的用户授权操作，不作为本次自动动作。
- **目标：** 用可判定证据证明 V1.0 在支持的 Windows 11 环境中可安装/解压、启动、翻译、迁移、恢复和清理，并产出尚未对外发布的 release candidate。
- **非目标：** 不新增功能、不开始 V1.x、不自动创建 GitHub 资源、不提交/推送/发布、不用真实付费 API 跑自动矩阵。
- **用户价值：** 用户获得可复现、可恢复、有已知限制和校验 hash 的绿色版候选，而不是“测试跑过”但无法判断能否发布的工程快照。
- **前置依赖：** P1-T03、P1-T04 及所有前序 Task 完成；工作树先形成可恢复 Git 基线；发布候选版本、依赖和文档冻结。
- **现有现场：** pytest/Ruff/mypy 配置和历史测试声明存在；没有 runtime dependencies/lock、PyInstaller 配置/artifact、Qt tests、release fixtures、远程仓库或发布证据。
- **输入文档和权威来源：** `01` §17/20/21；`02` 测试策略/Release Gate；`03` §3/6/8/10/11；`04`；`05`；`06`；`08`。
- **硬约束：** Gate 是布尔判定，不以“执行过”替代通过。自动测试不用真实秘密/付费端点；生产 transport 用本地受控兼容 server，另做用户授权的真实 endpoint 手工 smoke。数据损失、Project/格式损坏、secret 泄露、locked Revision 覆盖、无法启动/迁移/恢复/完成核心旅程、未解决 P0/P1 缺陷均阻止候选通过。长文本基准固定输入/环境并记录内存、耗时、最终状态和重复外部调用；要求数据丢失为零、所有 Segment 状态可解释、completed 不重复覆盖，性能仅记录基线而不虚构无依据阈值。绿色版必须在受支持 Windows 11 架构实际构建、解压、启动和操作；只读目录要求选择可写数据目录。依赖锁定、许可证、artifact version/hash、secret scan、backup/rollback/known issues 和未覆盖项必须随候选保存。删除程序目录不得静默删除外置 Project/备份或凭据；清理行为由文档和显式操作说明。
- **参考方案：** PyInstaller 候选、hash manifest、固定 fixture matrix、人工 checklist。打包工具仍是可验证的实现选择；若 Phase 0 smoke 证明不适合，可 `REPLAN` 选择另一成熟工具。
- **执行 Agent 可自主决定：** fixture 大小、性能采样工具、artifact 目录、checklist 格式和打包 flags；必须记录实际 Windows 11 build 与 CPU 架构。正式支持范围暂按权威“Windows 11”解释为本项目当前开发/测试环境的 x64，扩展 ARM64 或缩窄其他已批准兼容性承诺需 `DECISION_REQUIRED`；不得降低阻塞条件或把未验证项写成通过。
- **修改范围上限：** release/E2E/recovery tests、依赖锁/构建配置、用户文档、LICENSE/notice/known issues/checklist 和仅为 Gate 所需的阻塞缺陷修复；缺陷若扩大范围则回流原 Task。
- **交付能力：** 完整证据矩阵、Windows 绿色版 release candidate、恢复/迁移/使用/清理文档、可审计 sign-off；不对外发布。
- **功能验收：** 六格式、Project create/开放目录/package/import、Profile/Glossary/modes、兼容 endpoint、locked/current Revision、关闭恢复和导出在候选中完成。
- **异常验收：** crash cut、断网/model stop/timeout、lease、无效输出、只读/Unicode/长路径、migration/backup/package/tamper/空间失败均零数据损失并有可操作恢复。
- **安全与兼容性验收：** secret scan、依赖/许可审查、archive safety、旧 Project/package 升级、artifact hash/version、支持环境记录；默认 Debug/log/package 无秘密。
- **测试证据要求：** 自动 matrix 的实际命令/结果与环境、Windows GUI/绿色版手工 smoke 记录、长文本指标、真实 endpoint smoke（用户提供且授权时）、未覆盖项和 sign-off；不预填数量。
- **Code Review 重点：** Gate 是否可复现且布尔；失败是否被隐藏；artifact 是否来自已验证源码/锁；打包是否漏 Qt 插件/资源；安全扫描范围；文档是否与实际路径/行为一致。
- **文档同步项：** `00`–`08`、索引、state、README、用户安装/使用/迁移/恢复/清理文档；只记录“候选通过/未通过”，未经授权不写“已发布”。
- **完成条件：** 只有 M01–M05 的全部 release-blocking 项通过、候选 hash/证据归档且最终独立 Review 无未解决阻塞时，Task 才可 `completed`；否则保持 `blocked` 或 `verification` 并列出解除条件。对外发布仍等待用户明确授权。

| Milestone | 可独立验证的行为与完成条件 |
|---|---|
| P1-T05-M01 | **冻结可判定矩阵：** 固定版本、依赖锁、支持 Windows 11 环境、fixture、命令、期望状态、允许重复调用、零数据损失和证据位置；建立 P0/P1 release-blocking 等级，不把已知失败标通过。 |
| P1-T05-M02 | **翻译/恢复/长文本 Gate：** 自动覆盖请求与事务崩溃切点、断网/model-stop/timeout、lease/retry/cancel/locked；固定长文本用 fake/local server 跑完整旅程，状态全可解释、数据损失零、completed 不重复覆盖并记录资源基线。 |
| P1-T05-M03 | **格式/迁移/Project 双形态/security Gate：** 六格式 golden、旧库 migration backup/restore、开放目录/`.aiproject` 跨机/tamper/path/resource limits、secret scan 和失败隔离全部通过；演练文档中的恢复步骤。 |
| P1-T05-M04 | **Windows 绿色版候选：** 从锁定环境构建，记录工具/version/hash/size；在干净 Windows 11 解压启动、选择可写目录、创建/导入 Project、调用本地兼容 endpoint、关闭恢复、导出和清理；记录 Qt 插件、启动、杀毒扫描结果及阻塞项。 |
| P1-T05-M05 | **文档与最终 Sign-off：** 安装/使用/模式/Profile/Glossary/迁移/备份/恢复/清理/known issues/许可文档与候选一致；独立 Code Review 和全量命令通过；state 只在证据齐全时标 Gate 完成，不创建远程或发布。 |
