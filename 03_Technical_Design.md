# 译境 / TransRealm

# Technical Design V3

## 1. 目标与范围

描述软件如何实现。V1.0 以单用户、SQLite、本地优先的基础可靠翻译为目标。

技术基线：Python 3.12、PySide6（Qt 6）、SQLite、pytest。V1.0 正式支持 Windows 11，绿色版优先；跨平台兼容仅作为架构约束，不作为 V1.0 发布承诺。

V1.0 正式支持 OpenAI-compatible HTTP。llama.cpp server 与 Ollama 优先通过兼容端点接入；不承诺首发原生厂商 API。Sakura、Murasaki 等是 Model Profile，不要求专有调用协议。

## 2. 模块与依赖

```text
GUI
  -> Project/Application Services
  -> Import/Parser -> Segment Repository
  -> Translation Orchestrator
       -> Context Composer / Budget Manager
       -> Model Profile Resolver / Prompt Renderer
       -> Model Adapter
       -> Output Parser / Validator
       -> Translation Revision / Attempt Repository
  -> Exporter
```

依赖规则：

- GUI 不直接操作 SQLite 或 Provider；
- Translation Orchestrator 负责流程编排，不负责具体 Provider 协议；
- Model Adapter 负责外部调用、能力声明和错误归一化；
- Output Parser/Validator 在译文写入前执行；
- 所有持久化通过 Repository 和事务完成。

## 3. Project、路径与配置

Project 是可迁移的单用户翻译项目。路径通过统一 Path Service 解析，业务层不得拼接 Windows 专用路径分隔符，也不得依赖当前工作目录。

绿色版目录基线：

```text
TransRealm/
  TransRealm.exe
  data/
    config/
    logs/
    cache/
    projects/
```

启动时必须验证数据目录可写。若绿色版位于只读位置（例如受保护的 `Program Files`），应停止写入并提示用户选择可写数据目录；不得静默丢失配置或回退到不明确位置。

配置分为：

- 全局配置：界面、默认路径、日志级别；
- Project 配置：语言对、文件、Workflow、Model Profile、Glossary；
- Provider Connection：endpoint、认证引用、超时和重试；V1.0 暂不把代理配置列为必需交付。未来若新增代理，必须作为非敏感受约束字段持久化并进入安全/重开测试，不能只存在于运行时；当前 `004` 无代理字段，新增时使用新 migration；
- 敏感凭据：优先使用 Windows Credential Manager（通过受维护的凭据封装），也允许环境变量引用；秘密不进入 Project、日志、绿色版数据包或 `.aiproject`。

Project active Model Profile（P1-T04-M01 落地）：每个 Project 至多一个 active ModelProfile，持久化为 `projects.active_profile_id`（`009` migration 可空列，FK `model_profiles(id) ON DELETE RESTRICT`；`projects.schema_version` 保持 1）。`ProjectService.select_active_profile(project_id, profile_id)`/`clear_active_profile(project_id)` 预检 project 与 profile 存在（缺任一抛 `ProjectError`）后保存；selection 存于共享 SQLite 载体，开放目录与 `.aiproject` 重开均自动恢复，无需额外容器逻辑。删除保护：`ModelProfileService.delete_profile` 删除前预检——被任一 Project 的 `active_profile_id` 引用（抛 `ModelProfileInUseError` 并列出项目名）或被历史 `segment_attempts.model_profile_id` 引用（抛 `ModelProfileInUseError` 并给引用计数）时拒绝，FK RESTRICT 兜底；未引用的 profile 照常删除、缺失返回 False 的既有语义不变。历史 Attempt 的 `profile_snapshot` 快照不受删除保护影响，records 保持可解释。

Project 交互模式（P1-T03-M01 落地）：模式是同一 Application Service/状态机的交互策略，不创建第二套 orchestrator。新/旧 Project 均默认安全 `auto`，持久化为 `projects.mode`（`011` migration，`NOT NULL DEFAULT 'auto'` + `CHECK (mode IN ('auto','workbench'))`，`schema_version` 保持 1）；`ProjectService.set_mode(project_id, mode)` 预检 project 存在并校验 mode（非法抛 `ProjectError`），DB CHECK 兜底直接写库；`ProjectService.get_project(project_id)` 供自动模式解析 active Profile。自动模式最小旅程（P1-T03-M01 落地）：`TranslationWorker` 新增 `start_translate_auto`/`config_missing`——worker 线程内 `ProjectService.get_project` 解析 active Profile，无 active 时发 `config_missing`（不建 Run、不发模型请求），否则复用既有逐 Segment 翻译循环；`TranslationPage` 移除手动 Profile 组合框，Translate 走自动解析，缺配置时显示可操作引导 + "设置 active Profile…"按钮（`request_project_setup` → 切到 Project Tab），`project_settings_changed` 信号在 active Profile 变更后刷新 Translation 页状态。workbench 模式（显式参数/Profile 选择）与模式切换 UI 属 P1-T03-M02/M05。

capability-aware 工作台（P1-T03-M02 落地）：`TranslationPage` 新增工作台面——workbench 模式项目显示真实 Segment/Attempt 进度与 active Profile 的 capability 摘要。真实进度经 `TranslationRunService.list_segment_progress(source_document_id)`（`application/workbench.py` 的 `SegmentProgress` DTO，按文档返回每 Segment 的 status/current_revision 与最新 Attempt 的 status/error，Attempt 经 `SegmentAttemptRepository.list_by_document` JOIN 查询、取最高 id 为最新）；进度读与参数编辑全部经 worker 线程，Qt 主线程不查库。参数编辑器 `WorkbenchParamEditor`（`ui/workbench.py`）只呈现 `capability.supported_parameters` 声明的参数——已知参数用类型化控件（float/int/bool），未知参数用文本控件，`max_tokens` 控件上限钳制到 `capability.max_output_tokens`，绝不假设某模型支持某参数；草稿参数在刷新时经编辑器 `initial` 参数保留。工作台翻译经 `TranslationWorker.start_translate_workbench` 显式传 profile + 参数，`translate_segment(extra_params=...)` 把参数作为该 Attempt 的请求参数并记录于 `profile_snapshot.request_params`（JSON 快照追加键，无 schema 变更）——参数变更只形成其后领取 Attempt 的快照、永不改写已完成 Attempt/Revision；`OpenAICompatibleAdapter.filter_params` 仍是发送前最终过滤（UI 呈现与 Adapter 过滤双保险，不支持参数不发送）。完成后 `_on_finished` 在 workbench 模式重读进度列表（显示 completed/failed 结果）。auto 模式保持 M01 最小旅程不变。

Project-scoped Glossary（P1-T04-M02 落地）：`GlossaryService`（`application/glossary_service.py`）提供 `create_entry`/`update_entry`/`get_entry`/`list_entries`/`list_locked_entries`/`delete_entry`，持久化到 `glossary_entries`（`010` migration）。设计：source_term 在同 Project 内唯一（`UNIQUE(project_id, source_term)`），重复添加/改词冲突在服务层预检给明确 `GlossaryEntryError`，DB 唯一约束兜底并发写；source_term/target_term/scope 以 strip 归一化后存储并校验非空，priority 为 0-100 整数（越高越重要，对齐 `05` §4/5 注入/裁剪方向），is_locked 布尔（V1.0 只注入 locked 项），origin ∈ ('user','import')；`list_entries`/`list_locked_entries` 按 `priority DESC, id` 排序为 M03 确定性注入提供稳定次序。service 复用 `ProjectRepository`/`create_database`/`MigrationRunner` seam，不新建第二套存储；domain 层无 SQLite 依赖。unlocked 项可保存/编辑但不进入 Prompt。

Project 提供两种互通形态：普通用户使用单文件 `.aiproject`；高级用户可使用开放目录。两者共享同一 manifest、schema/version、相对路径、hash、秘密排除和 migration 契约；开放目录不是第二套业务模型或数据库。`.aiproject` 是 manifest、SQLite 一致性快照和附件的归档视图；开放目录以 `manifest.json`、`project.sqlite` 和声明附件为权威，source/translation/config 等人类可读目录只能作为 manifest 声明内容，不能绕过数据库状态、Revision 或校验。近期不支持多人并发编辑、自动合并或在线同步。

开放目录容器（P1-T02-M01 落地）：权威内容是 `manifest.json` + `project.sqlite` + manifest 声明的附件；目录中未声明文件不被当作 Project 状态。`manifest.json` 记录 `format_version`（当前 1）、`schema_version`（当前 1）、`software`（生成该容器的应用版本）与每个受控 entry 的相对路径、类型（`database`/`attachment`）、大小与 `sha256:` hash；manifest 自身不递归自哈希，且不能以任何归一化形式（含大小写/尾部点别名）声明为 entry。创建：目标目录必须为空（拒绝覆盖既有文件）；初始化 SQLite 复用 `MigrationRunner` 与 P0-T03-M00 升级备份 seam，随后清理对新建空库无保护意义的 `*.pre-upgrade-*.db.bak` 与 WAL 附属文件，原子写 manifest；创建失败清理自身产物，用户既有的空目录保留。打开：先校验 manifest（未知 format/schema 版本、缺必需字段、重复 JSON key、缺失/重名/重复关键 `project.sqlite` entry 拒绝），再逐 entry 校验相对路径与大小/hash——绝对路径、盘符/UNC、`..`、归一化逃逸、大小写或 Unicode 等价重复、Windows 尾部点/空格别名、控制字符、link/junction 类 entry 及父目录 link 逃逸均拒绝——最后才打开数据库，要求恰一个 Project 身份且 `projects.schema_version` 与 manifest 一致；任一校验失败不触碰数据库。开放目录加载与 `.aiproject` 归档共享同一路径/hash/版本校验；entry 数/单项/总大小限额与隔离 staging 属 P1-T02-M03。

`.aiproject` 单文件归档（P1-T02-M02 落地）：`application/archive_service.py` 提供 `export_open_directory_archive`（源为开放目录，先经 M01 校验 manifest/路径/hash/恰一个 Project 再导出）与 `export_database_archive`（源为裸活动数据库，`list_projects()` 恰一个才导出；零/多 Project 明确拒绝）。两者共用 `_build_archive`：经临时 staging 目录构建一致容器——`infrastructure/migrations/backup.py` 的 `create_consistent_snapshot` 用 SQLite backup API 生成一致性 snapshot（不在 WAL 写入期间直接复制活动数据库文件），复制声明附件，重新计算 manifest 条目并 `verify_entries` 自校验，最后 `infrastructure/open_directory.py` 的 `write_archive` 原子写为标准 ZIP（`manifest.json` + `project.sqlite` + 附件，内部 relpath 与 manifest 一致，解包即开放目录）。secret/log 不打包（只含受控条目，数据库只存 credential reference）；导出失败不留下半成品归档、既有目标保持不变。

`.aiproject` 隔离安全导入（P1-T02-M03 落地）：`import_archive_to_staging(archive_path, staging_dir, *, limits=None)` 把归档只解到新的隔离 staging 目录（须为空，拒绝非空；成功/失败均不触碰最终安装目标）。`extract_archive` 先读归档内 `manifest.json` 并做结构/版本/跨字段/路径校验（复用 `parse_manifest_text`/`validate_manifest`/`canonical_relpath`），再对 ZIP 头逐 entry 施加资源限额——entry 数 ≤1000、单项未压缩 ≤256 MiB、总未压缩 ≤512 MiB、压缩比 ≤5000:1（M03 fixture 固定默认值，Release Gate 定稿，调用方可传更窄 `ArchiveLimits`），并拒绝未声明成员、重复成员与目录成员；随后只解 manifest 声明的 entry（手工按 canonical relpath 写入，绝对路径/盘符/UNC/`..`/link/未声明内容均不可逃逸 staging），最后 `verify_entries` 逐项复核大小/`sha256:`/link，并以只读连接校验 staging 数据库恰含一个 Project 且 `projects.schema_version` 与 manifest 一致（不运行 migration，M04 安装时执行）。任一失败清理 staging 自身产物（调用方既有的空目录保留）；成功即得到与 M01 同一契约的开放目录，可经 `open_open_directory_project` 重开。

双形态迁移与原子安装（P1-T02-M04 落地）：`install_service.py` 提供 `migrate_container(directory, *, app_version)`（就地向前迁移开放目录容器：只读校验 manifest/路径/大小/hash 与恰一个 Project + schema 匹配 → 经 `ProjectService`/`MigrationRunner` seam 运行 pending migration（P0-T03-M00 先建一致性备份）→ 成功后清理容器内瞬时 pre-upgrade 备份与 WAL 附属、重算 manifest（新 DB 大小/hash、schema_version 取自 DB、保留附件与既有 `source_id`）并复验；无 pending 时不动容器；失败传播并保留 pre-upgrade 备份供恢复）与 `install_staging_to_target(staging_dir, target_dir, *, app_version, confirm_overwrite=False)`（迁移 M03 staging 容器 → 把源 Project id 写入 manifest `source_id` 供追踪 → 原子安装：新/空目录经同父临时目录构建+全量验证后 rename 到位；目标已含 Project 时未经 `confirm_overwrite` 拒绝——同名冲突报 `TargetConflictError` 并带确定性后缀建议名如 `Alpha (2)`，异名也需确认——确认覆盖则先把既有目标移为 `.<target>.pre-replace-<ts>.bak` 恢复备份再安装、失败还原）。`open_open_directory_project` 打开旧 schema 容器即走迁移路径并保持容器只含受控条目。版本/权限/空间/migration/名称冲突失败均保留原目标并给恢复动作。

跨机器与双形态 Gate（P1-T02-M05 落地）：开放目录 -> `.aiproject` -> 隔离"另一台 Windows" -> 开放目录 round-trip 由 `tests/test_p1_t02_m05.py` 全链路验证（独立临时根模拟目标机，只有 `.aiproject` 跨边界，不真调远程/付费服务）——核心状态（Project identity、manifest `source_id`、segments 及其 008 fidelity carrier、connection 只存 credential reference、profile、translation run、附件）跨机保留、从已安装目标可再导出再导入、旧 schema(001-007)归档在目标机经备份+migration 安装、WAL 未提交不跨机、tamper/截断/traversal/超限归档在导入前失败且 staging 清理、同名目标冲突建议名且确认覆盖保留 `.pre-replace` 恢复备份。凭据可用性（`04` §7"目标机缺凭据时必须给可操作提示"）：`adapters/credential_resolvers.py` 的 `credential_reference_is_available`（只读判 `env:` 变量存在且非空 / `wincred:` 凭据存在且非空，从不返回 secret；wincred 只查 `CredReadW` 返回 size>0 不把 blob 读入内存）与 `application/credential_status.py` 的 `report_credential_availability` 组成应用层只读表面——导入/打开后按连接列出目标机缺失/为空的被引用凭据并给可操作 hint；secret 永不进入归档、数据库或目标容器。

存在 pending migration 时，Migration Runner 必须在执行第一条 migration 前通过 SQLite backup API 创建可打开的一致性备份；无 pending migration 时不创建无意义备份。备份失败、目标不可写或校验失败时不得开始 migration。该升级安全备份不同于 `.aiproject` 的迁移包：前者保护当前数据库升级，后者用于离线转移和导入。

## 4. 核心翻译数据流

```text
导入文件
 -> 解析并生成稳定 Segment
 -> 在一个事务中保存不可变 SourceDocument 内容版本与全部 Segment
 -> 读取 Model Profile
 -> 收集角色/Glossary/相邻 Segment 等上下文
 -> 应用最小 Context Budget
 -> 渲染 Prompt 和输出契约
 -> 调用 Model Adapter
 -> 解析并验证输出
 -> 保存 Attempt 和 Translation Revision
 -> 更新 Segment 状态
 -> 导出
```

相同 Project、源 bytes hash、格式和 parser contract/version 的导入复用既有 SourceDocument；内容、格式或会改变 Segment 映射的 parser identity 变化时创建新的不可变 SourceDocument 和 Segment 映射。旧版本不自动删除，跨版本译文迁移和锁定 Revision 保护由 Revision/Attempt 阶段实现。当前 `003` 只按内容 hash 去重，P1-T01 必须用新 migration 扩展解析身份，不得重写已发布 migration。

## 5. Model Adapter

统一接口至少提供：

- 请求：model、messages/prompt、语言对、max output、超时、流式设置、结构化输出要求；
- 响应：文本或结构化结果、finish reason、usage、provider request ID、原始响应引用；
- 能力：上下文长度、最大输出、流式、结构化输出、可用参数；
- 错误：分类、Provider 错误码、可重试标志、retry-after。

OpenAI-compatible 实现支持有限 transport retry：
- 仅对网络/超时/断连/408/429/5xx 等可重试错误进行最多 `max_retries` 次重试；
- 采用指数退避（`retry_delay * 2^attempt`）；若响应头包含正数 `Retry-After`，只在其不超过当前调用策略的剩余时间预算/明确上限时采用，否则返回可重试错误交给业务层决定，不无界 sleep；
- 401/403/400/422 等永久错误不重试，直接返回归一化错误；
- 每次重试保持请求体、超时和参数不变。

支持可选 capability 降级：当 provider 返回 capability 相关错误
（如 `unsupported_parameter`、`unsupported_value`、`invalid_type`）且
`DegradationPolicy` 允许时，可重试一次无结构化输出或流式标志的请求。
声明 capability 仍作为前置校验，默认不会发送已知不支持的参数。

凭据边界：仅当 `credential_reference` 和 `CredentialResolver` 同时存在时，
adapter 才调用 resolver 获取 token 并写入 `Authorization` 请求头；
秘密不得在错误信息、日志或持久化中泄露。

具体契约实现位于 `adapters/dto.py`、`adapters/protocol.py`、`adapters/errors.py`。
`ModelAdapter` 协议通过 `CredentialResolver` 与 `Transport` 注入凭据和 HTTP 传输，
OpenAI-compatible 实现位于 `adapters/openai_adapter.py`，负责请求/响应映射、
capability 校验和错误归一化。

生产 transport 与凭据解析（P0-T08-M02）：`adapters/http_transport.py` 用 stdlib
`urllib.request`（经 `asyncio.to_thread` 满足 async `Transport` 协议）实现零运行时
依赖 transport：请求超时归为 `AdapterTimeoutError`，连接/截断响应归为
`AdapterConnectionError`；重定向由 transport 自行处理，同源（scheme/host/port 不变）
保留全部头，跨源或 HTTPS 降级剥离 `Authorization`/`Cookie`/`Proxy-Authorization`，
且只跟随 `http`/`https` 重定向。`adapters/credential_resolvers.py` 提供
`env:`（`os.environ`）与 `wincred:`（`ctypes` 调 `advapi32.CredReadW`）resolver；
错误信息只含变量/目标名或 Win32 错误号，不含 secret 值。
`application/adapter_factory.py` 的 `compose_adapter` 把持久化
`ProviderConnection`（endpoint/timeout/retry/credential_reference）与
`ModelProfile`（model/capability snapshot）组合成 adapter 实例。

UI 只显示当前 Model Capability 支持的参数；不得假设所有兼容端点支持相同参数。

## 6. Segment 状态与恢复

Segment 至少包含稳定 ID、源文、当前译文引用、状态和 revision/version。状态：

```text
pending -> processing -> completed
pending -> processing -> failed
failed -> pending      （仅可重试失败）
processing -> pending   （租约过期或安全恢复）
```

规则：

- `pending -> processing` 必须通过带当前状态、`version` 且 lease 为空或已过期的原子写完成；写入新的 owner 与未来过期时间。`processing -> pending` 的回收只匹配已过期 lease；UTC 时间由可控时钟提供；
- claim 成功后、第一次外部模型请求前建立 Attempt；claim 身份由 `lease_owner + version` 表示，不要求在 Segment 再保存一个可分叉的活动 Attempt 引用；
- 完成、失败和取消必须再次匹配 claim 时的 owner/version；lease 过期后的迟到 worker 不能覆盖新 owner（fencing）；
- 每次 Application 层逻辑模型调用记录一个 Attempt。相同逻辑请求的 Adapter transport retry 与一次 capability degradation 仍属于该 Attempt；输出 repair 再次调用模型或 Segment 重新执行时创建新 Attempt 和新幂等键；
- 响应审计、Revision、`current_revision_id`、Attempt 与 Segment 状态更新在同一完成事务内；
- 自动完成只有在 current revision 未被并发改变且不是人工/locked current 时才能更新；历史 Revision 永不覆盖；
- `idempotency_key` 必须有数据库唯一约束，重复提交复用既有 Attempt/结果且不重复调用外部模型；
- 启动只回收过期 processing；failed 只有最后 Attempt 标记 retryable 时可重新进入 pending；
- 取消保留已提交 Revision、Attempt 状态和可操作原因。

Segment 状态保持 `pending/processing/completed/failed`，取消不是第五个 Segment 状态：取消 processing 时将当前 Attempt 标为 `cancelled`，在仍持有有效 lease 时把 Segment 返回 `pending`；若该 Attempt 已原子完成，则保留 `completed`。TranslationRun 状态为 `running/completed/failed/cancelled`；SegmentAttempt 状态为 `created/succeeded/failed/cancelled`。Run 的 completed 表示其目标 Segment 都已完成，failed 表示无可自动继续的永久失败；用户取消标记 cancelled。

V1.0 不要求通用任务队列、事件总线或并行 worker 池。worker 必须能在 Adapter retry sleep、请求返回和 Segment 边界观察取消；不能取消的底层请求仍受 timeout 限制。初始 lease 必须覆盖当前调用策略的最大 timeout + 有界 retry/backoff + 完成事务余量；若真实长调用测试证明无法安全界定，执行 Agent 可按 Reality Check 增加保持相同 fencing 的最小续租，而不能让 lease 先过期后提交。

## 7. Context 管理

Phase 0 必须提供规则式最小预算：当前 Segment 和必要相邻 Segment 为必入；若 Project 已存在基础 Glossary，可按锁定项优先注入。Character Data 属于 Phase 2，仅在数据已存在时作为可选来源；输出预留和 Prompt 固定部分先计入预算。RAG、TM 智能召回、World State 自动摘要属于 Phase 2。

Context Composer 必须记录 Context Manifest：来源、优先级、命中原因、估算 token/字符数、裁剪结果和 Profile 版本。

P1-T04-M03 落实确定性锁定 Glossary 注入：`TranslationService.translate_segment`
经 `GlossaryEntryRepository.list_locked_by_project(run.project_id)`（`WHERE
is_locked=1 ORDER BY priority DESC, id`）只查询当前 Project 的 locked 项，由
`application/glossary_context.py` 的 `build_glossary_candidates` 映射为
`ContextCandidate`（`content = "{source_term} -> {target_term}"`、`segment_id =
"glossary:{source_term}"`、metadata 带 entry_id/source_term/target_term/scope/
priority/origin，共享 `default_estimate` 估算，不复制估算逻辑）后传入
`ContextComposer.compose(glossary_candidates=...)`。Composer 将 glossary 候选
priority 归一化为 `_GLOSSARY_PRIORITY`（1）并以稳定次序（repository 的
`priority DESC, id` 顺序）先于邻居选择，Manifest 记录 selected/pruned；预算不足
只裁剪可选上下文、当前 Segment 超预算抛 `ContextBudgetError` 不截断。V1.0 只注入
locked 项，unlocked 项可保存/编辑但不进 Prompt；`scope` 是用户可编辑分类标签，
不参与 M03 注入过滤。

## 8. 错误处理

- 网络断开、限流、临时 Provider 错误：有限次数指数退避；
- 本地模型停止：暂停队列并提示用户，不无限重试；
- 超时：标记可重试 Attempt，保留 request ID/错误信息；
- 输出格式错误：执行 Profile 指定的有限修复；仍失败则进入 failed，不直接写译文；
- 程序关闭或断电：依赖 SQLite 事务和 lease 恢复 processing；
- 认证、参数和格式等永久错误：不自动重试，显示可操作错误。

Phase 0 的有限修复（P0-T08-M03）由 `TranslationService` 编排：模型输出无效且
首个校验问题被 `OutputParser` 标记为 `repairable`（空译文/污染）时，执行一次有界
重呼并创建新 Attempt（新幂等键，同 rendered prompt），repair 预算默认 1；重呼后仍
无效或问题不可修复则 finalize 为永久失败。repair 通过 T07 的
`finalize_failure(retryable=True)` + `retry_failed` + `start_attempt` 路径进入新
Attempt，repair 层独立记账于 Attempt 的 `validator_summary`，不与 Adapter transport
retry 形成乘法重试。

## 9. Export 与格式保真

Exporter 默认读取 Segment 的 `current_revision_id`；用户显式选择历史 Revision 时，必须验证该 Revision 属于同一 Segment 且有效，不能把 Adapter response、Validator candidate 或源文作为静默回退。解析器与 Exporter 必须共享格式专属定位元数据；缺失/错配 metadata 或 Revision 时拒绝导出，不留下半文件。

Phase 0 的 TXT 导出（P0-T08-M04）由 `application/exporter.py` 的 `TxtExporter`
实现：按 `ORDER BY sequence` 原顺序取 Segment，默认写 `current_revision_id`
对应 Revision 文本；`revision_overrides: dict[segment_id, revision_id]` 支持显式
选择，逐 Revision 校验存在且 `segment_id` 归属，未知 segment 键报错；任一 Segment
缺可用 Revision 即失败、不回退源文。写入为同目录 `tempfile.mkstemp` + `os.replace`
原子替换，编码失败或目标不可写均清理临时文件并保持目标不变；默认 UTF-8（源编码/
BOM 保真属本节约定的 V1.0 基线，P1-T01 落实）。

P1-T01-M01 起按裁决 `DEC-P1-T01-FOUNDATION`（方案 2：原始 bytes + 版本化 format
metadata envelope + 格式专属定位信息）落实 TXT 保真载体：

- **持久化：** `source_documents` 经 `008` migration 增加 `raw_bytes`（BLOB）
  与 `format_metadata`（JSON envelope）列，与源内容版本同事务写入；逻辑唯一域扩展
  为 `(project_id, source_hash, format, parser_version)`，替换 `003` 的
  `(project_id, source_hash)` 索引，避免相同 bytes 的不同格式/parser 版本错误复用。
- **envelope（版本化 format metadata）：** 至少含 `schema_version`、`format`、
  内容 `encoding`、`bom`（null/utf-8/utf-16-le/utf-16-be）、`newline`
  （crlf/lf/cr/none）、`parser_version`、`source_hash` 与格式专属 `locator`
  （TXT 为逐 Segment byte span：`sequence`/`byte_start`/`byte_end`，偏移含 BOM）。
  由 parser 生成；后续 JSON/SRT/VTT/ASS/SSA 在已批准 envelope 内保存各自安全定位
  信息，不把多字节编码、换行归一化或格式结构强压成同一 span 模型。
- **校验与替换（exporter seam）：** exporter 在替换前针对原始 bytes、`source_hash`、
  encoding/BOM/newline、span 越界/重叠/错位与解码结果逐项验证；任一校验失败、编码
  错误或目标不可写均拒绝，不污染 DB、Revision 或既有目标文件（同目录
  `tempfile.mkstemp` + `os.replace` 原子写，清理临时文件）。no-op 模式
  （`apply_revisions=False`）逐字节输出 `raw_bytes`；翻译模式仅替换目标 span，
  非目标 bytes（空白/空行/换行/行尾/BOM）保持不变。
- **旧 TXT 升级：** `008` 只加可空列，不从 `source_text` 猜造原始 bytes；缺
  raw_bytes/可验证 metadata 时保真导出安全失败并提示补齐；用户提供并校验原文件后
  经显式补齐路径写入载体（校验源 hash 与既有 Segment 映射一致后同事务落库）。

P1-T01-M02 落实 JSON 保真闭环（只实现 JSON，不实现其余格式）：

- **JSON 定位（`json.paths` locator）：** 按裁决方案 2 为 JSON 定义格式专属定位信息，
  不套用 TXT 的 flat byte span 语义。`JSONParser` 用单遍迭代 tokenizer（不依赖递归，
  深度上限 512）只把 value 位置的字符串 token 生成为 Segment；每 Segment 记录结构路径
  （JSON Pointer，`~`/`/` 经 `~0`/`~1` 转义）与 value token 的 byte span（含引号、
  含 BOM 偏移）。key、number/true/false/null、容器、空白、转义与顺序一律不翻译、逐字节
  保留。
- **校验与替换（`JsonExporter`）：** 复用 `FidelityExporter` 共享 seam（carrier 加载、
  envelope 验证、Revision 归属校验、`mkstemp`+`os.replace` 原子写）；替换前用同一
  tokenizer 重解析原始 bytes，逐 Segment 验证 path/span/value==source_text，检测 envelope
  篡改/错位；译文经 `json.dumps(ensure_ascii=False)` 转义为合法 JSON string literal 后替换
  目标 token。
- **拒绝策略：** malformed（未闭合/尾逗号/非法数字/非法转义/字符串内控制字符/根值后尾随
  token/空文件）、重复对象 key（结构路径歧义）、超 512 深度、未配对 `\u` 代理项均在导入期
  拒绝且不污染 Project；空字符串 value 仍是 Segment（延续"任一 Segment 缺 Revision 即
  失败"契约）。
- **实现结构：** `TxtExporter` 的共享 seam 提取为 `FidelityExporter` 基类；
  `TxtExporter`/`JsonExporter` 继承并各自实现 `_build_replacement_plan`；`TxtExporter`
  公共 API 与字节行为不变（M01 35 项 + 受影响旧测试全绿）。

P1-T01-M03 落实 SRT 保真闭环（只实现 SRT，不实现 VTT/ASS/SSA）：

- **SRT 定位（`srt.cues` locator）：** 按裁决方案 2 为 SRT 定义格式专属定位信息，不套用 TXT 的
  flat byte span 或 JSON 的 path 语义。`SRTParser` 单遍扫描物理行，把每个 cue 的文本块（timing
  行后的非空行直到空行，内部换行原样保留）生成为一个 Segment；每 cue 记录 `sequence`、打印序号
  （`index`，index-less cue 为 null）、原样 `start`/`end` 时间串（逗号/点分隔符保留）、可选
  `settings`（`X1:...` 等，strip 后保存）与文本块 byte span（含 BOM 偏移）。cue 序号行、timing
  行、settings、空行分隔与行尾换行一律不翻译、逐字节保留；多行文本块内部换行属目标 bytes，可随
  译文改变，块边界换行保持原编码换行风格。
- **校验与替换（`SrtExporter`）：** 复用 `FidelityExporter` 共享 seam；替换前用同一
  `extract_cues` 重解析原始 bytes，逐 Segment 验证 sequence/index/start/end/settings/byte
  span/文本==source_text，检测 envelope 篡改/错位；译文以内容编码直接替换目标文本块（SRT 无转义
  机制）。
- **拒绝策略：** 非法时间轴（缺 `-->`、坏分隔、分钟/秒 >59、毫秒位数错误）、重复 cue 时间轴
  （相同规范化 start/end，含逗号/点分隔符差异）、空 cue 文本、缺失空行分隔（文本行形似下一 cue
  的序号+timing）、序号行后缺失 timing 均在导入期拒绝且不污染 Project；形似 timing 的文本行按
  规范视为文本（timing 行后空行之前皆文本），不静默重排 cue。
- **实现结构：** `infrastructure/parsers/srt_parser.py`（`SRTParser`/`extract_cues`/
  `SRTParseError`）、`fidelity.py` `build_srt_envelope`/`LOCATOR_TYPE_SRT_CUES`、
  `application/exporter.py` `SrtExporter`、`default_registry()` 注册 `SRTParser`；
  全量回归 679 passed（基线 604 + M03 新增 75）、Ruff clean、mypy 93 files no issues。

P1-T01-M04 落实 VTT 保真闭环（只实现 VTT，不实现 ASS/SSA）：

- **VTT 定位（`vtt.cues` locator）：** 按裁决方案 2 为 VTT 定义格式专属定位信息，不套用 TXT 的 flat
  byte span、JSON 的 path 或 SRT 的 index 语义。`VTTParser` 单遍扫描物理行：先校验文件签名——解码文本必须以
  `WEBVTT` 开头（可带 BOM，后随空格标题或行尾），否则拒绝（SRT 等其他内容不得静默降级为 VTT/重排为 cue）；
  `NOTE`/`STYLE`/`REGION` 块按规范消费到空行为止，作为结构性 bytes 永不生成 Segment。每个 cue 的文本块
  （timing 行后的非空行直到空行或含 `-->` 的行，内部换行原样保留）生成为一个 Segment；每 cue 记录
  `sequence`、cue 标识（`id`，无标识为 null）、原样 `start`/`end` 时间串与可选 `settings`
  （`align:start` 等，strip 后保存）及文本块 byte span（含 BOM 偏移）。签名行、cue 标识行、timing 行、
  settings、NOTE/STYLE/REGION 块、空行分隔与行尾换行一律不翻译、逐字节保留；多行文本块内部换行属目标
  bytes 可随译文改变。
- **时间戳规则：** 按 W3C 规范接受完整 `HH:MM:SS.mmm`（小时 1+ 位）与省略小时 `MM:SS.mmm`（点分隔，
  非 SRT 逗号），毫秒必须恰好 3 位，分钟/秒必须在 00-59（超范围拒绝，与 SRT 先例一致）；小时位数不限。
- **校验与替换（`VttExporter`）：** 复用 `FidelityExporter` 共享 seam；替换前用同一 `extract_cues`
  重解析原始 bytes，逐 Segment 验证 sequence/id/start/end/settings/byte span/文本==source_text，
  检测 envelope 篡改/错位；译文以内容编码直接替换目标文本块（VTT 无转义机制，内联 `<b>/<v>` 等标签属
  目标 span，no-op 逐字节保留、翻译由译文整体替换）。
- **拒绝策略：** 缺 `WEBVTT` 签名、签名后非空格/行尾、非法时间轴（缺 `-->`、坏分隔、毫秒位数错误、分钟/秒
  超 59）、重复 cue 时间轴（规范化 start/end，含完整/省略小时等价）、空 cue 文本、标识行后缺失 timing、
  正文裸文本行（bad cue 标识）、含 `-->` 但非合法 timing 的文本行均在导入期拒绝且不污染 Project；cue 文本
  含 `-->` 时按规范结束上一 cue 并以该行开启新 cue（VTT 不要求 cue 间空行分隔）。
- **实现结构：** `infrastructure/parsers/vtt_parser.py`（`VTTParser`/`extract_cues`/`VTTParseError`）、
  `fidelity.py` `build_vtt_envelope`/`LOCATOR_TYPE_VTT_CUES`、`application/exporter.py` `VttExporter`、
  `default_registry()` 注册 `VTTParser`；全量回归 765 passed（基线 679 + M04 新增 86）、Ruff clean、
  mypy 95 files no issues。已记录取舍：`Kind:`/`Language:`/`X-TIMESTAMP-MAP` 等扩展 metadata 头与缩进
  `STYLE` 按 fail-safe 拒绝（保留项，不属 M04 范围）；`-->` 周围空白宽容（`\s*`，与 SRT 一致）；
  `locator.type` 与 envelope `encoding` 篡改校验为共享 seam 行为，与 TXT/JSON/SRT 一致。

P1-T01-M05 落实 ASS/SSA 保真闭环（只实现 ASS/SSA，不实现其他格式）：

- **ASS/SSA 定位（`ass.events` / `ssa.events` locator）：** 按裁决方案 2 为 ASS
  （ScriptType `v4.00+`）与 SSA（`v4.00`）定义格式专属定位信息，不套用 TXT 的 flat
  byte span、JSON 的 path 或 SRT/VTT 的 cue 语义。两种格式共享一个解析引擎
  （`infrastructure/parsers/ass_ssa_parser.py` 的 `extract_events`），`AssParser`/
  `SsaParser` 只差 `format` 与期望 ScriptType，不创建两套无必要框架。每个
  `Dialogue:` 事件的 Text 字段（按 `[Events] Format:` 字段数 split 后的最后一段，
  逗号、行内 override 标签、`\N`/`\h` 等转义与首尾空格原样保留）生成为一个
  Segment；每事件记录 `sequence`、原样 `start`/`end` 时间串与 Text 字段 byte span
  （含 BOM 偏移）。section 头、`[Events] Format:` 行、`Comment:` 与其他事件类型
  （Picture/Sound/Movie 等）、Style 定义、`;` 注释、所有非 Text 字段与行尾换行一律
  不翻译、逐字节保留；Text 字段内换行不适用（ASS/SSA 事件是单物理行，换行经
  `\N`/`\h` 转义）。
- **签名与格式判别：** 文件必须以 `[Script Info]` 开头（SRT/其他内容不得静默降级），
  且 `ScriptType:` 必须匹配 format（ass=`v4.00+`、ssa=`v4.00`），错配即拒绝
  （ASS 内容不会误读为 SSA，反之亦然）。
- **Events Format 校验：** `[Events]` 必须声明标准 `Format:` 字段表（v4：
  `Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text`；
  v4+：`Layer, Start, End, ...`；大小写不敏感、按逗号 strip 后比较）；缺 Format、
  重复 Format 或非标准字段表均拒绝，避免猜测 Text 字段的分割逗号数。Dialogue 行必须
  恰有该字段数（Text 是最后一个、可含逗号的字段），Start/End（字段 1/2）必须符合
  `h:mm:ss.cc` 时间戳（小时 1+ 位、分钟/秒 00-59、百分秒恰 2 位，SRT/VTT 的
  毫秒 3 位在此不适用），Text 字段 strip 后非空（纯空白视为空文本拒绝，与 SRT/VTT
  一致）。与 SRT/VTT 不同，重复 start/end 时间轴允许（ASS/SSA 中多行同时对话按样式
  区分是合法结构），stable key 含 sequence 保证不碰撞。
- **校验与替换（`AssExporter`/`SsaExporter`）：** 复用 `FidelityExporter` 共享
  seam；两 exporter 共享 `_AssSsaExporter` 基类（`_build_replacement_plan` 用
  `self.format` 选择 locator/重解析），`AssExporter`/`SsaExporter` 只设 `format`。
  替换前用同一 `extract_events` 重解析原始 bytes，逐 Segment 验证
  sequence/start/end/Text byte span/文本==source_text 与 parser_version，检测
  envelope 篡改/错位；译文以内容编码直接替换目标 Text 字段（ASS/SSA 无转义机制，
  行内 override 标签属目标 span，no-op 逐字节保留、翻译由译文整体替换，包括 Text
  字段原有首尾空格）。
- **拒绝策略：** 缺 `[Script Info]`、ScriptType 缺失/错配、缺/重复/非标准 Events
  Format、Dialogue 字段数不足、空/纯空白 Text、非法时间轴（坏分隔/分钟秒超 59/
  百分秒位数错误）均在导入期拒绝且不污染 Project。
- **实现结构：** `infrastructure/parsers/ass_ssa_parser.py`
  （`AssSsaParseError`/`AssSsaEvent`/`extract_events`/`AssParser`/`SsaParser`）、
  `fidelity.py` `build_ass_envelope`/`build_ssa_envelope`/`LOCATOR_TYPE_ASS_EVENTS`/
  `LOCATOR_TYPE_SSA_EVENTS`、`application/exporter.py` `_AssSsaExporter`/
  `AssExporter`/`SsaExporter`、`default_registry()` 注册 `AssParser`/`SsaParser`。
  已记录取舍：严格 `[Script Info]` 开头与 ScriptType 匹配（VTT 签名先例，防静默降级）；
  仅标准 Events Format 可解析（非标准字段表 fail-safe 拒绝）；Dialogue Text 含首尾空格
  时按整字段替换（目标 span，允许改变）；`locator.type` 与 envelope `encoding` 篡改
  校验为共享 seam 行为，与 TXT/JSON/SRT/VTT 一致。

V1.0 保真基线：无翻译导出与导入 bytes 一致；翻译后只允许目标文本 span 改变，并保留原编码/BOM、换行及非目标结构。JSON 只翻译 string leaf value，保留 key、非字符串值、顺序、空白和转义；SRT/VTT 保留 cue 标识、时间轴/settings 与非目标块；ASS/SSA 根据 Events Format 只替换 Dialogue Text，保留 section、style、comment、字段顺序、标签和转义。损坏或不支持输入默认拒绝，不静默”修复”。round-trip golden tests 是 V1.0 发布门槛。

## 10. Python 工程边界

建议包结构按职责拆分：`ui`、`application`、`domain`、`infrastructure`、`adapters`。PySide6 对象和信号不得渗入 domain 层；耗时文件解析和模型请求不得阻塞 GUI 主线程；跨线程只传递可序列化 DTO 或不可变领域数据。

SQLite 访问统一由 infrastructure/repository 层管理连接与事务。测试使用 pytest；Qt 交互测试可使用 pytest-qt，但领域、migration 和 Adapter 契约不依赖 GUI 测试。

P0-T08 的 GUI 仅为核心 TXT 翻译闭环提供薄桌面入口；UI 只能调用 Application Service，解析、数据库和模型请求必须在可控 worker 中执行并返回 DTO。每个 worker/thread 拥有自己的 SQLite connection 生命周期，不跨线程传递 connection/cursor；关闭时先停止接收新工作，再通过 P0-T07 的取消/lease 语义收敛，不能以强杀线程伪装成功。P1-T04 先补齐 Project Profile 选择与基础 Glossary，P1-T03 再增加自动模式与工作台模式的默认策略、参数暴露和交互差异；两种模式继续复用同一状态机、Validator、Application Service 和 Revision 保护。运行中 Run 不因 UI 模式切换改变 Profile/Workflow/参数；用户必须选择继续当前 Run 或取消后以新配置创建后续 Run。

P1-T03-M03 落地受控 Prompt Override（2026-08-08）：预设 Prompt 模板是应用常量（`application/preset_templates.py`：`general` v1.0.0 = 既有默认模板文本，`ALLOWED_PLACEHOLDERS` = renderer 的 current/context/output_schema/source_language/target_language），只读不可改。用户在工作台把预设拷贝编辑后保存为 Override（`prompt_overrides` 表 1:1 with profile，FK CASCADE，`012` migration），记录父预设版本。领域校验（`domain/prompt_override.py`，Qt-free）拒绝未知变量、非法 `$` 语法、空文本；渲染解析（`preset_templates.resolve_override_template`）在 `parent_template_version ≠ 当前预设版本` 时 fail-closed 拒绝（不 claim Attempt、不发送请求），并重校验持久化文本防 DB 篡改。`TranslationService.translate_segment` 有 override 时用它渲染并追加 `override_parent_version` 到 Attempt `context_summary`；无 override 用预设，行为不变。输出边界结构性不可移除：Output Contract wrapper 由 `PromptRenderer` 固定追加，格式保护/校验/安全限制是独立流水线阶段，任何 Override 文本都无法关闭。UI：`WorkbenchPromptEditor` 展示只读预设预览 + 可编辑拷贝 + Save/Clear（页面经 worker 线程调用 `ModelProfileService.set_prompt_override`/`clear_prompt_override`，草稿跨 refresh 保留）。模板只做占位符替换（`string.Template`），不执行任何模板代码。

P1-T03-M04 落地人工 Revision 与锁定（2026-08-08）：工作台编辑追加 `origin=user` TranslationRevision 并成为 current（`TranslationRunService.append_user_revision`——单事务 INSERT user revision + `UPDATE segments SET status='completed', current_revision_id=?, version=version+1 ... WHERE status != 'processing'`，processing 段明确拒绝，version bump 使捕获的 stale claim 失效）；`set_current_revision` 把 current 切换到任一属于该 segment 的有效 revision（AI/user/import），同样拒绝 processing 并校验 revision 归属；`lock_current_revision`/`unlock_current_revision` 用单条 `UPDATE ... WHERE id = (SELECT current_revision_id FROM segments WHERE id = ?)` 原子切换 current 的 `is_locked`。无新 migration（`006` 已定义 `translation_revisions.origin CHECK('ai','user','import')` 与 `is_locked`）。锁定/人工 current 的自动覆盖保护由既有 seam 兜底：`finalize_success` 校验 expected current 未变 + 非 locked（locked 或已变化即拒绝迟到自动结果），`recover_expired_leases` 对 locked current 的 processing 段转 completed 不重建 revision，auto worker 循环只翻译 pending 段（append/set 置 completed 后不再被 claim）——锁定后自动迟到结果和重译不能覆盖 locked current。`list_segment_progress` 经 `TranslationRevisionRepository.get_many_by_ids` 为 `SegmentProgress` 填充 `revision_text`/`revision_locked`（供工作台显示当前译文与锁态，向后兼容带默认值）。UI：`WorkbenchRevisionEditor`（`ui/workbench.py`，只发信号不碰 DB：source 只读 + 译文可编辑 + Save/Lock/Unlock）接入 `TranslationPage` 工作台——`_segment_progress` 选中重建编辑面、Save/Lock/Unlock 经 `ServiceWorker` 线程调 service、刷新记录选中 segment 并恢复、`initial` 保留未保存草稿跨 refresh。导出遵循选择语义（P0-T08-M04 既有）：默认读 `current_revision_id`，`revision_overrides` 显式选择历史 revision 并逐项校验存在/归属；锁定不改变导出（锁定保护的是"不被自动覆盖"，而非"不可导出"）。

P1-T03-M05 落地模式切换与文档选择（2026-08-08）：`TranslationPage` 新增交互模式选择器（Auto/Workbench `QComboBox`）——经 `ServiceWorker` 调 `ProjectService.set_mode` 持久化 `projects.mode`（`011`），模式标签与工作台面随 refresh 同步；运行中（`_set_running` 集中管理 `_running` 与 Translate/Cancel/Export/文档选择器按钮态）激活切换被拒绝并提示"finish or Cancel"，选择器恢复当前持久化 mode——运行中 Run 保持其 Profile/Workflow/参数，不原地改变（`03` §10 硬约束）。`set_mode` 成功路径同步 `_mode` 再 refresh，refresh 失败不致 UI/DB 失同步。新增每 Project 文档选择器：`TranslationRunService.list_source_documents(project_id)`（只读转发 `SegmentRepository.list_source_documents_by_project`，UI 经 Application Service 访问、不违反结构性守卫）供 `_refresh_task` 按当前 Project 填充组合框；有效文档逻辑——提交时捕获的当前文档属于该 Project 则沿用、否则清空（不做自动选中，切换 Project 不泄漏另一 Project 的陈旧 `_document_id`；组合框在无有效文档时不高亮首项），文档选择经 `_on_document_selected` 重读进度；运行中文档切换同样被拒绝。切换 Project 后 TranslationPage 重置文档上下文（M01 已知边界消除）。取消/关闭/重启门禁由既有 seam 承载：`request_stop` Segment 边界取消（auto/workbench 共用 `translate` 循环）、closeEvent 有界 wait 收敛、mode/active/文档/结果/锁定随共享 SQLite 载体重开自动恢复。

P1-T04-M04 落地薄管理 UI（2026-08-07）：`SettingsPage` 增加 Connection/Profile 删除与凭据可用性提示，`ProjectPage` 增加项目选择、active Profile 选择/清除与 Glossary 增改删（lock/priority/scope）。所有操作仍经 `ServiceWorker` 调 Application Service（`WorkerPage._submit` → worker 线程内开闭 service 连接），UI 不直接查库；Qt 主线程只持有 `db_path` 用于构造 service。`ProviderConnectionService.delete_connection` 删除前预检——被任一 `model_profiles.provider_connection_id` 引用时抛 `ProviderConnectionInUseError` 并列出 profile 名（镜像 M01 `delete_profile` 预检先例；DB FK RESTRICT 兜底并发写，不重写 CRUD）。缺凭据提示经 `credential_status.report_credential_availability` 显示每个缺失引用的可操作 hint（设环境变量/建 Windows 凭据项），永不显示 secret。Glossary 的 source/target/scope 以 strip 归一化校验，priority 用 0-100 旋钮、locked 用复选框；重复/空术语、被引用删除等验证错误经 worker 回传显示为可操作消息。active Profile 与 Glossary 持久化于共享 SQLite 载体，重开窗口经 `ProjectService`/`GlossaryService` 自动恢复。`ProjectPage.select_project(project_id)` 与既有 `import_file`/`translate` 同类程序化入口，供 pytest-qt 无对话框驱动。

Phase 0 桌面壳（P0-T08-M05）：`ui/main_window.py`（三 Tab：Settings/Project/Translation）、`ui/pages.py`（三个页面）、`ui/worker.py`（`ServiceWorker` 通用任务执行器 + `TranslationWorker` 逐 Segment 翻译循环）。worker 槽通过信号排队到各自线程（直接调用 `moveToThread` 对象的槽会在调用线程执行，故用 `start_translate`/`run_requested` 信号触发），每个 worker 线程内创建的 Service 连接只在创建线程内开闭；取消经主线程直接置位的 `request_stop` 标志在 Segment 边界生效，关闭时 `request_stop` + `thread.quit()` + 有界 `wait()` 收敛，在途模型调用受 timeout 约束，遗留 processing 由 T07 lease 恢复。

Windows 绿色版由独立打包任务生成，首选 PyInstaller 作为 V1.0 打包候选；Phase 0 只验证候选工具能 build/start，V1.0 Release Gate 才冻结依赖并验证启动、体积、PySide6 插件、路径/恢复/清理和杀毒扫描。打包工具属于可验证的实现选择，不改变 Project 数据格式；构建候选不代表已发布。

Phase 0 build/start smoke（P0-T08-M06，PyInstaller 6.21.0 验证）：`--onedir --windowed` 可行，PyInstaller 内置 PySide6 hook（`pyi_rth_pyside6` + QtCore/Gui/Widgets）自动收集 `platforms/qwindows.dll`、styles、iconengines、imageformats 等 Qt 插件；应用只用 stdlib `sqlite3`、不导入 QtSql，故 `sqldrivers` 插件缺失属预期。**关键发现：** 迁移 SQL 数据文件（`transrealm/migrations/*.sql`）不会被 PyInstaller 自动收集——冻结应用仅建空 `schema_migrations`、无法应用迁移；必须显式 `--add-data "src/transrealm/migrations;transrealm/migrations"`（迁移目录经 `Path(__file__).parent.parent / "migrations"` 在 `_internal` 下解析），补上后 6 个迁移全部应用、全部业务表可创建。构建 ~1 分钟、onedir 体积约 123 MB（PySide6 主导），正式依赖锁/体积/UPX/图标/签名/杀毒属 V1.0 Release Gate。

## 11. Attempt 可观测性与安全

每次 Attempt 在重启后至少可解释：Run/Segment/Profile、Profile/template/capability 快照或稳定版本、Prompt hash、Context/参数与 Validator 摘要、Provider request ID、模型、状态、retryable、开始/完成时间、耗时、usage 和错误。原始 Prompt/响应正文默认可配置、可脱敏、可清理；Revision 和上述最小审计字段不得随 Debug 清理消失；API Key 永不记录。

生产 HTTP transport 默认不跟随可能泄露凭据的跨 origin 重定向。若实现允许重定向，scheme/host/port 变化必须移除 Authorization，HTTPS 降级不得携带凭据；本机显式配置的兼容 HTTP endpoint 可直接使用。Provider body、错误、UI 和日志都必须经过 secret 脱敏边界。

## 12. V1.0 Release Gate 冻结矩阵

（P1-T05-M01 冻结，2026-08-08 实测；M02–M05 各 Gate 以本矩阵为共用底座。矩阵/锁/环境变化必须重跑全量质量命令并同步 `requirements.lock`、`07` §20、`08` 落地取舍记录与本文件。）

### 12.1 判定原则

Gate 是布尔判定，不把"执行过"当通过（对齐 `02` V1.0 Release Gate）。每项记录固定场景、故障切点、预期持久化状态、允许数据损失/重复外部调用、恢复动作、通过条件与证据位置；已知失败、未覆盖项、未验证项必须如实记录，不得标通过。

### 12.2 支持环境（V1.0 候选）

- Windows 11（x64，build ≥ 22000）。当前构建/验证环境实测：Windows 11 Pro 10.0.26100，`PROCESSOR_ARCHITECTURE=AMD64`。
- Python 3.12（`py -3.12`，实测 3.12.10）。
- 绿色版数据目录默认可写（`01` §21.1）；程序目录只读时必须启动提示并允许选择可写数据目录；清理不得静默删除外置 Project/备份/凭据（`02` Release Gate）。
- 架构范围按 `07` §20：正式支持 = 本环境 x64；扩展 ARM64 或缩窄已批准兼容性承诺需 `DECISION_REQUIRED`。

### 12.3 依赖锁定

- 运行时（`pyproject` `dependencies`）：`PySide6>=6.8,<6.12`；实测锁定 PySide6 6.11.1（+ PySide6_Addons/Essentials/shiboken6 6.11.1）。
- dev/工具链（`pyproject` `dev`）：pytest 9.1.1、pytest-qt 4.5.0、ruff 0.16.0、mypy 2.3.0。
- 打包工具：PyInstaller 6.21.0 + pyinstaller-hooks-contrib 2026.6（`03` §10 首选候选；正式构建在 M04）。
- 锁文件 `requirements.lock`：`pip freeze` 全量快照（排除 `transrealm` editable 与 `pip`），与 `pyproject` 声明范围一致且等于当前安装版本（`test_p1_t05_m01` 断言）。候选可定位性 = Git 基线 commit + 锁文件共同保证（`09` §6）。
- 更新规则：任何依赖版本变化必须同步 `requirements.lock`、`pyproject` 范围与本节记录，并重跑全量质量命令；`test_p1_t05_m01` 在锁/环境漂移时失败即 Gate 判定候选不通过。

### 12.4 质量命令与期望状态

| 命令 | 期望状态 | 证据位置 |
|---|---|---|
| `py -3.12 -m pytest -q` | exit 0；全量 passed + 仅已知 skip | pytest 输出；M 完成报告 |
| `py -3.12 -m ruff check src tests` | exit 0（All checks passed） | ruff 输出 |
| `py -3.12 -m mypy src tests` | exit 0（no issues in N source files） | mypy 输出 |
| `py -3.12 scripts/verify_task.py --task <T> --base-commit <基线> --allow <路径>… --baseline-test <nodeid>… --new-test <nodeid>…` | exit 0；无 outside_scope/移除测试 | verify_task.py JSON 报告 |
| `py -3.12 scripts/check_candidate_hygiene.py` | exit 0（无被禁 tracked 文件） | 脚本输出 |

（Git 基线形成后 `verify_task.py`/`check_candidate_hygiene.py` 才对 P1-T05 改动生效；基线形成前以本地全量命令为门禁。）

### 12.5 公共矩阵规范

- fixture：固定输入基准的规范由各自 M 定义（M02 长文本/崩溃切点、M03 六格式/旧库/容器、M04 绿色版）；M01 冻结其命名与证据位置约定，不预置未验证数据。
  - **M02（P1-T05-M02，2026-08-08 实测）**：长文本 fixture = 模块级固定 `_LONG_TEXT`（120 行 / 21,743 字符，`tests/test_p1_t05_m02.py` 内常量，测试 `test_fixture_is_fixed_and_recorded` 断言精确大小防漂移），用计数式本地 `ThreadingHTTPServer` 逐 Segment 回显译文（每 Segment 恰一请求）；崩溃切点 = `CrashInjector`（finalize 三个写入 SQL needle）+ 可控 server 行为注入（挂起→`timeout_error`、连接拒绝/截断→`connection_error`，均 retryable）+ 请求前崩溃（`CrashBeforeRequestAdapter` 抛 `SimulatedCrashError`，该切点请求按定义从未发出）。旅程级矩阵与资源基线记录见 `tests/test_p1_t05_m02.py`（11 项：claim 后请求前、断网、mid-response 截断、model-stop/超时、finalize 三写入点、locked 保留、completed 不重调、长文本基线、fixture 防漂移）。
- 允许重复调用：每项记录固定场景允许的重复外部调用次数（transport retry、repair 次数以 `07`/P0-T04/P0-T08-M03 契约为准）；矩阵不新增调用。M02 长文本 clean journey 允许次数 = Segment 数（120），clean 输出无 repair/transport retry；网络/超时场景允许一次 retryable 失败 + 一次成功重译（`retry_failed` 新 run）。
- 零数据损失：任何故障注入不得丢失/损坏既有 Project、Revision、Segment、备份或目标文件；失败不得污染 DB 或目标；不得静默删除外置数据。
- 证据位置：每 Gate 通过证据落点 = 测试 nodeid、smoke 目录、`requirements.lock`、本文件、`08` 落地取舍记录、`DEVELOPMENT_STATE.md`。M02 资源基线（内存峰值/耗时/Segment 数/外部调用次数）打印为 `LONG_TEXT_RESOURCE_BASELINE` 并写入 JSON 证据（tmp），只记录不断言虚构阈值（`02` §3 长文本测试）。

### 12.6 P0/P1 release-blocking 等级

- **P0（release-blocking）：** 数据丢失/损坏、Project/格式损坏、secret 泄露、locked Revision 被覆盖、无法启动/迁移/恢复/完成核心旅程、依赖锁不一致、P0 缺陷。
- **P1（候选不通过直到解决）：** 严重功能缺陷、文档与候选实际路径/行为不一致、artifact 非来自已验证基线、打包漏 Qt 插件/资源、已知项未覆盖。
- 未解决 P0/P1 缺陷均阻止候选通过（`07` §20 硬约束）；不把已知失败标通过。

重大变化遵循：提出修改 → Architecture Review → 更新 Technical Design → 重新规划 Task → 开发。