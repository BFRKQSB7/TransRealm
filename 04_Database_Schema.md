# Database Schema V3

## 1. 原则

- V1.0 只支持 SQLite 运行时；Schema Migration 指数据库结构演进，不代表多数据库支持。
- Project 可迁移、可备份、支持绿色版。
- 禁止直接修改已发布结构；所有变化必须新增 migration。
- 外键、状态、唯一约束和事务边界必须明确。

## 2. Schema Migration

```text
migration/
  001_init.sql
  002_add_source_document_and_segment.sql
  003_add_import_uniqueness.sql
  004_add_provider_connection.sql
  005_add_model_profile.sql
  006_add_workflow_run_attempt_revision.sql
  007_add_run_workflow_snapshot.sql
  008_add_format_fidelity.sql
  009_add_project_active_profile.sql
  010_add_glossary_entry.sql
  011_add_project_mode.sql
  012_add_prompt_override.sql
```

数据库维护 `schema_migrations`：migration_id、checksum、applied_at、app_version。`001`–`007` 已在 P0 提交（`007` 随 P0-T07 工作流 snapshot 提交），`008` 为 P1-T01-M01 新增，`009` 为 P1-T04-M01 新增（`projects.active_profile_id`），`010` 为 P1-T04-M02 新增（`glossary_entries`），`011` 为 P1-T03-M01 新增（`projects.mode`），`012` 为 P1-T03-M03 新增（`prompt_overrides`）；后续 Agent 必须先检查真实 migration 目录再选择新编号。

`projects.schema_version` 仅作为 Project/package 兼容性快照，由 migration/open 流程维护，不替代 `schema_migrations`；数据库实际已应用结构以 `schema_migrations` 为唯一权威。

规则：

- 每个 migration 在事务中原子执行；
- 该能力由 P0-T03-M00 补齐 P0-T01 未实现的异常验收；既有 `001`–`003` 不追溯改写，M00 完成后保护其后的所有升级；
- 仅当存在 pending migration 时，在第一条 migration 前用 SQLite 一致性 backup 机制创建可恢复备份；
- 备份必须可发现、可打开并保持升级前 schema/data；WAL 活动时禁止直接复制数据库文件；
- 备份失败、目标不可写、空间/路径冲突或校验失败时不得开始 migration；
- migration 失败时保留备份和原始错误；V1.0 不要求自动 downgrade；
- 升级安全备份保护当前数据库，`.aiproject` snapshot 用于离线转移和导入，两者不得混为同一生命周期；
- 失败时回滚当前事务并保留错误；
- SQLite 不支持直接变更时，使用新表、数据校验、事务切换的表重建流程；
- V1.0 不要求 downgrade，回退依赖升级前备份；
- 已发布 migration 不可重写，修复必须新增编号。

## 3. V1.0 最小实体

### Project

`projects`：id、name、source_language、target_language、created_at、updated_at、schema_version、active_profile_id（可空，`009` migration，FK RESTRICT → `model_profiles(id)`）、mode（`011` migration，`NOT NULL DEFAULT 'auto'`，`CHECK (mode IN ('auto','workbench'))`）。`active_profile_id` 保存 Project 当前选中的 active ModelProfile，重开自动恢复；`NULL` 表示未选择。`mode` 保存 Project 的交互模式（自动/工作台），新/旧 Project 均默认安全 `auto`；`schema_version` 保持 1（追加式列，不改变既有行含义）。

### SourceDocument

`source_documents`：id、project_id、path/name、format、encoding、source_hash、parser_version、raw_bytes（BLOB，可空）、format_metadata（JSON envelope，可空）、created_at。

SourceDocument 表示不可变的内容与解析版本；逻辑复用身份至少包含 Project、源 bytes hash、format 和会改变 Segment 映射的 parser identity/version。完全相同身份的重复导入返回既有版本；内容、格式或 parser contract 变化时新建 SourceDocument 和 Segment 映射，不自动删除旧版本。`003` 原提供 `(project_id, source_hash)` 唯一，`008` 已用 `(project_id, source_hash, format, parser_version)` 唯一索引替换，避免相同 bytes 的不同格式或 parser 版本错误复用；不得重写 `003`。

`raw_bytes` 与 `format_metadata` 是保真载体（`DEC-P1-T01-FOUNDATION` 方案 2），由 parser 生成、与源内容版本同事务写入；旧 TXT 数据迁移后为 NULL，不得从 `source_text` 猜造原始 bytes。`format_metadata` 是版本化 envelope，至少含 schema_version、format、内容 encoding、bom、newline、parser_version、source_hash 与格式专属 locator（TXT 为逐 Segment byte span；JSON 为 `json.paths`：每 Segment 的结构路径 + value token byte span；SRT 为 `srt.cues`：每 cue 的 sequence/index/start/end/settings + 文本块 byte span；VTT 为 `vtt.cues`：每 cue 的 sequence/id/start/end/settings + 文本块 byte span；ASS/SSA 为 `ass.events`/`ssa.events`：每个 Dialogue 事件的 sequence/start/end + Text 字段 byte span）。

### Segment

`segments`：id、source_document_id、stable_key、source_text、sequence、status、current_revision_id、version、lease_owner、lease_expires_at、created_at、updated_at。

稳定 key 由解析器根据源文件结构生成，不能只依赖当前数组位置。源文件变化时记录新 hash，并显式重建映射。

### TranslationRevision

`translation_revisions`：id、segment_id、text、origin（ai/user/import）、attempt_id、is_locked、created_at。

一个 Segment 可有多个 Revision；当前译文通过 `current_revision_id` 引用，禁止覆盖历史 Revision。自动流程只有在 current revision 未被并发改变且不是人工/locked current 时才能切换 current；人工编辑追加 `origin=user` Revision 并可成为 current。默认导出 current，显式选择历史 Revision 时必须验证同 Segment 归属。

### WorkflowDefinition

`workflow_definitions`：id、name、origin（builtin/user）、parent_workflow_id、version、definition_json、definition_hash、is_read_only、created_at。

V1.0 内置预设以只读、版本化定义提供；用户副本属于后期能力。`translation_runs.workflow_id` 外键引用实际执行定义，并保存运行时 version 与 definition_hash snapshot，保证结果可复现。内置 Workflow 在打开时 idempotent seed，并校验 definition_hash 以发现被错误改写。

### TranslationRun 与 SegmentAttempt

`translation_runs`：id、project_id、workflow_id、workflow_version、workflow_definition_hash、started_at、finished_at、status。

Run `status` 枚举：`running/completed/failed/cancelled`。completed 表示目标 Segment 都已完成；failed 表示存在无可自动继续的永久失败；用户取消为 cancelled。

`workflow_version` 引用不可变的 WorkflowDefinition 版本；`workflow_definition_hash` 用于检测定义被错误改写。

`segment_attempts` 至少保存：id、run_id、segment_id、claim_version、lease_owner（或等价 claim token）、idempotency_key、model_profile_id、Profile/template/capability snapshot 或稳定版本、prompt_hash、context/parameter/validator 摘要、request_id、status、retryable、input_tokens、output_tokens、latency_ms、error_type、error_message、created_at、finished_at。Attempt `status` 枚举：`created/succeeded/failed/cancelled`。claim token 必须在数据库重开后足以识别 Attempt 属于哪一代 lease；原始 Prompt/响应正文可用受控字段或 artifact reference 保存，但必须可配置、脱敏和清理，其清理不能删除 Revision 或最小审计字段。P1-T03-M02 起，实际发送的请求参数（工作台草稿或 Profile 默认参数）随 Attempt 记录于 `profile_snapshot.request_params`（JSON 快照内追加键，无 schema/migration 变更；参数变更只影响其后领取的 Attempt，已完成 Attempt/Revision 不被改写）。

一次 Application 层逻辑模型调用对应一个 SegmentAttempt；Adapter transport retry 和一次 capability degradation 属于同一 Attempt，输出 repair 或 failed Segment 重新执行创建新 Attempt。

### ModelProfile 与 ProviderConnection

`model_profiles` 保存非敏感配置：id、name、provider_connection_id（外键）、model_id、template_version、output_protocol、context_budget（JSON）、default_params（JSON）、capability_snapshot（JSON）、created_at、updated_at。

`provider_connections` 保存非敏感连接配置：id、name（唯一）、provider_type、endpoint、timeout_seconds、max_retries、retry_delay_seconds、credential_reference、created_at、updated_at。当前 `004` 只保存这些字段；V1.0 暂不把代理配置列为必需交付。未来若需要代理，必须通过新 migration 增加非敏感、受约束字段并覆盖关闭重开与秘密边界，不能只保存在 UI/进程内存。

`credential_reference` 使用受控语法，例如 `env:VAR_NAME` 或 `wincred:TARGET_NAME`，禁止直接写入 API Key、Bearer Token 等秘密值。

`model_profiles.provider_connection_id` 外键引用 `provider_connections(id)`，删除被引用的 Connection 时被阻止（RESTRICT），保证 Profile 与 Connection 的引用完整性。P1-T04-M04 起服务层 `ProviderConnectionService.delete_connection` 删除前预检——被任一 profile 引用时抛 `ProviderConnectionInUseError` 并列出 profile 名（镜像 M01 `delete_profile` 预检先例），DB RESTRICT 兜底并发写；未引用的 connection 照常删除、缺失返回 False 的既有语义不变。

### GlossaryEntry

`glossary_entries`（`010` migration）：id、project_id、source_term、target_term、scope、priority（0-100，默认 50）、is_locked（0/1，默认 0）、origin（'user'/'import'）、created_at、updated_at。

`UNIQUE(project_id, source_term)`（`010`）：同 Project 内 source_term 唯一，重复添加在服务层给出明确 `GlossaryEntryError` 并拒绝（事务不污染），DB 唯一约束兜底并发写。`scope` 是用户可编辑分类标签（`01` §11.2：专有名词/技术词/人名/地名等），V1.0 仅做非空稳定校验，不参与 M03 注入过滤；`priority` 越高越重要（`05` §4/5：locked 项按 priority+稳定次序先注入、低优先级先裁剪），数值范围 0-100 由执行 Agent 自决项固化。V1.0 只自动注入 locked 项，unlocked 项可保存/编辑但不进入 Prompt。

V1.0 支持用户维护和翻译时注入；自动提取属于后续增强。

### PromptOverride

`prompt_overrides`（`012` migration，P1-T03-M03）：id、model_profile_id（外键）、parent_template_version、template_text、created_at、updated_at。

`prompt_overrides` 与 `model_profiles` 1:1（`UNIQUE(model_profile_id)`）：预设模板只读（`05` §2），用户修改保存为 override 并记录父预设模板版本。`parent_template_version` 在保存时 = 当前预设版本；预设版本更新（应用升级）后旧 override 失效，渲染时 fail-closed 拒绝（不发送请求），用户需基于新预设重建 override。`model_profile_id` 引用 `model_profiles(id) ON DELETE CASCADE`——删除 profile 连带删除其 override（Profile 是 Override 的从属资源）。`schema_version` 保持 1（追加式表，不改变既有行含义）。

## 4. 后续实体

Character Data、Translation Memory (TM)、World State、RAG 索引元数据属于 Phase 2。V1.0 不要求实现智能召回或向量索引。

## 5. 约束与索引

- 所有业务表使用稳定主键；
- 启用外键，并明确 restrict/cascade；
- `projects.mode` CHECK ('auto','workbench')（`011`，P1-T03-M01）：DB 层拒绝非法交互模式写；服务层 `Project.with_mode`/`ProjectService.set_mode` 预检给出明确 `ProjectError`；
- `projects.active_profile_id` 引用 `model_profiles(id) ON DELETE RESTRICT`（P1-T04-M01）：被任一 Project active 选中的 Profile 不可删除；服务层删除预检给明确 `ModelProfileInUseError`（区分"被 Project active 引用"与"被历史 Attempt 引用"），DB 层 RESTRICT 兜底；
- `model_profiles.provider_connection_id` 引用 `provider_connections(id) ON DELETE RESTRICT`（P1-T04-M04 服务层预检）：被任一 profile 引用的 Connection 不可删除；服务层 `delete_connection` 删除前预检给明确 `ProviderConnectionInUseError`（列出引用 profile 名），DB 层 RESTRICT 兜底；
- `008` 提供 `source_documents(project_id, source_hash, format, parser_version)` 唯一（替换 `003` 的 `(project_id, source_hash)` 索引），把 format/parser identity 纳入逻辑唯一域，避免相同 bytes 的不同格式或 parser 版本错误复用；唯一域冲突 migration 失败并保留升级前备份；
- `segments(source_document_id, sequence)` 唯一；
- `segments(source_document_id, stable_key)` 唯一，解析器 key 碰撞必须使整次导入失败；
- 为 `segments(status, lease_expires_at)`、`segment_attempts(segment_id, created_at)`、`translation_revisions(segment_id, created_at)` 建索引；
- `segment_attempts.idempotency_key` 必须由数据库唯一约束保护；唯一域可为全局，或包含 Run/Segment，但重复键行为必须确定且不得再次发起模型调用；
- lease claim 使用 `status = pending + expected version + (lease_owner IS NULL 或 lease_expires_at <= now)` 条件写并设置新 owner/未来 expiry；回收只匹配已过期 processing；finalize 必须匹配 claim 的 owner/version 且 lease 尚未过期，`version` 作为 fencing token；
- `translation_runs.workflow_id` 必须引用有效 WorkflowDefinition；
- `current_revision_id` 只能引用同一 Segment 的 Revision；
- 锁定 Revision 不得被自动流程删除或替换；
- `glossary_entries(project_id, source_term)` 唯一（`010`，P1-T04-M02）：同 Project 内 source_term 唯一，服务层预检给明确 `GlossaryEntryError`，DB UNIQUE 兜底并发写（预检与写入非同一事务，单用户本地应用可接受，最坏退化为通用 `SqlExecutionError` 且无数据污染，与 M01 删除预检同一取舍）；`priority` CHECK 0-100、`is_locked` CHECK 0/1、`origin` CHECK ('user','import')；`glossary_entries.project_id` 引用 `projects(id) ON DELETE CASCADE`（项目删除连带删除其术语，与 `translation_runs`/`segments` 项目级 CASCADE 一致）；为 `glossary_entries(project_id, priority)` 建索引；
- `prompt_overrides(model_profile_id)` 唯一（`012`，P1-T03-M03）：每个 Profile 至多一个 override，重复保存为更新同一行（`PromptOverrideRepository.save` 先查后改/插）；`prompt_overrides.model_profile_id` 引用 `model_profiles(id) ON DELETE CASCADE`（删除 profile 连带删除其 override）；override 校验（未知变量/非法 `$` 语法/空文本/父版本失效）在领域层与渲染解析层做双保险，DB 只保证 1:1 与级联；
- 不使用 NULL 表示状态，枚举值必须有文档定义。

## 6. 事务与恢复

一次源文件导入的 SourceDocument 与全部 Segment 必须在同一事务中落库；任一 Segment 失败时整次导入回滚。唯一约束 migration 遇到既有冲突数据时必须失败并保留原数据，不得在没有升级前备份的情况下自动选择或删除版本。

保真载体（`raw_bytes`/`format_metadata`）与源内容版本同事务写入，不单独提交半载体。`008` migration 只加可空列，不从 `source_text` 猜造原始 bytes；旧 TXT 数据缺载体时保真导出安全失败并保留既有 Project/目标文件。用户提供并校验原文件后经显式补齐路径写回载体：校验源 hash 与既有 Segment 映射（数量、stable_key、source_text、sequence）一致后在同一事务更新 `raw_bytes`/`format_metadata`；hash 或映射不一致拒绝且不落库。

Attempt 创建、最小响应审计、Revision 创建和 Segment/Attempt 状态更新必须按 P0-T07 契约使用事务：外部请求不持有数据库事务；成功完成的响应审计、Revision、current revision 和 completed 写入同一完成事务，并再次校验 lease owner/version 与 current/locked 前置条件。落库前崩溃时，遗留 `processing` 由 lease 过期回收；迟到 worker 不得越过 fencing；人工 Revision 不受影响。失败记录必须区分 retryable 与 permanent。某 Segment 的“最后有效 Attempt”定义为 claim token 与该 Segment 当前或最近已完成 claim generation 匹配的 Attempt；不得仅按时间戳猜测。只有该 Attempt 为 `failed` 且 `retryable = true` 时才允许 `failed -> pending`。取消 Attempt 后，若仍持有效 lease 则 Segment 返回 pending；已完成事务不回滚为 pending。

## 7. Project 双形态、`.aiproject` 备份与迁移

V1.0 支持同一逻辑 Project 的两种互通形态：

```text
单文件：project.aiproject
开放目录：
  manifest.json
  project.sqlite
  attachments/
```

开放目录与单文件使用同一 manifest/schema/hash/相对路径契约；它不是第二套数据库或并发工作区。`.aiproject` 是上述受控条目的归档视图。`source/translation/config` 等可读目录若由实现提供，必须在 manifest 中声明并视为附件/导出物，不能绕过 `project.sqlite` 的 Segment/Revision 状态。

manifest 至少记录 format_version、schema_version、源文件 hash、软件版本，以及除 `manifest.json` 自身外每个归档/目录受控 entry 的相对路径、类型、大小和 hash；manifest 自身不做递归自哈希，若需验证其真实性由包外 artifact hash 或后续签名机制处理。导出使用 SQLite 一致性备份机制，不能在 WAL 写入期间直接复制活动数据库文件。

开放目录容器与 manifest（P1-T02-M01 落地）：`manifest.json` 具体为 `{"format_version": 1, "schema_version": 1, "software": "<app version>", "files": {"<relative path>": {"type": "database"|"attachment", "size": <int>, "hash": "sha256:<hex>"}}}`（可选 `source_id`：导入安装时记录源 Project id 供追踪，P1-T02-M04）；`project.sqlite` 是唯一 `database` 型关键 entry（恰一个、重名/重复/缺失拒绝），manifest 自身不可被声明（含大小写/尾部点别名）。打开容器前先做 manifest 结构/版本校验，再逐 entry 校验相对路径（绝对路径、盘符/UNC、`..`、归一化逃逸、大小写或 Unicode 等价重复、Windows 尾部点/空格别名、控制字符、link/junction 及父目录 link 逃逸均拒绝）与大小/hash，最后打开数据库并要求恰一个 Project 身份且 `projects.schema_version` 与 manifest 一致；任一失败不触碰数据库。创建容器要求目录为空并清理新建库产生的空库 `*.pre-upgrade-*.db.bak` 与 WAL 附属文件，保证容器只含受控条目。entry 数/单项/总大小限额与隔离 staging 属 P1-T02-M03。

`.aiproject` 单文件归档视图（P1-T02-M02 落地）：从一个开放目录容器或裸活动数据库导出单文件归档，是上述受控条目的归档视图——标准 ZIP（stdlib `zipfile`，deflate），根含 `manifest.json`（同一 schema）+ `project.sqlite`（经 SQLite backup API 生成的一致性 snapshot，不在 WAL 写入期间直接复制活动数据库文件）+ 声明附件（内部 relpath 与 manifest relpath 一致，解包即开放目录）。manifest 逐 entry 记录相对路径/类型/大小/`sha256:` hash，可复验。日志与秘密不打包：归档只含 manifest 声明条目，日志/未声明文件不进入，数据库只存 credential reference（原始凭据值不落库）。导出源含零个或多个 Project 时明确拒绝，不静默选择或夹带。归档写入原子（同目录临时文件 + `os.replace`），失败不留下半成品归档、既有目标保持不变。

`.aiproject` 隔离安全导入（P1-T02-M03 落地）：`import_archive_to_staging` 把归档只解到新的隔离 staging 目录（须为空，拒绝非空；成功/失败均不触碰最终安装目标）。`extract_archive` 先读归档内 manifest 做结构/版本/跨字段/路径校验，再对 ZIP 头逐 entry 施加资源限额（见"导入前限制"条目）并拒绝未声明成员、重复成员与目录成员，随后只解声明 entry 并逐项复核大小/hash/link，最后以只读连接校验 staging 数据库恰含一个 Project 且 `projects.schema_version` 与 manifest 一致；任一失败清理 staging 自身产物（保留调用方既有空目录）。导入不运行 migration（M04 安装时执行），成功即得到同契约开放目录。

双形态迁移与原子安装（P1-T02-M04 落地）：开放目录容器经 `migrate_container` 就地向前迁移——先只读校验 manifest/路径/大小/hash 与恰一个 Project + `projects.schema_version` 与 manifest 一致，再经 `ProjectService`/`MigrationRunner` seam 运行 pending migration（P0-T03-M00 先在容器内建一致性备份），成功后清理瞬时 `*.pre-upgrade-*.db.bak` 与 WAL 附属并重算 manifest（新 DB 大小/hash、schema_version 取自 DB、保留附件与既有 `source_id`），容器只含受控条目且可重开；无 pending migration 时不动容器。`open_open_directory_project` 打开旧 schema 容器即走此迁移路径。`install_staging_to_target` 把 M03 staging 容器先迁移，再把源 Project id 写入 manifest `source_id`（import metadata，供追踪），最后原子安装到目标：新/空目录经同父临时目录构建+验证后 rename 到位；目标已含 Project 时未经 `confirm_overwrite` 拒绝（同名冲突报 `TargetConflictError` 并带确定性后缀建议名如 `Alpha (2)`，异名也需确认），确认覆盖则先把既有目标移为 `.<target>.pre-replace-<ts>.bak` 恢复备份再安装、失败还原。migration/版本/权限/空间/名称冲突失败均保留原目标并保留恢复物（就地迁移的 pre-upgrade 备份、安装的源归档或 `.pre-replace` 备份）。

跨机器与双形态 Gate（P1-T02-M05 落地）：全链路 round-trip（开放目录 -> `.aiproject` -> 隔离"另一台 Windows" -> 开放目录）验证核心状态与附件跨机保留、WAL 未提交不跨机、旧 schema 归档在目标机迁移、tamper/资源限额/目标冲突均目标落地前失败且原数据保持。凭据可用性：`credential_reference_is_available`（`adapters/credential_resolvers.py`，只读判 `env:` 变量存在且非空 / `wincred:` 凭据存在且非空，从不返回 secret）+ `report_credential_availability`（`application/credential_status.py`）组成应用层只读报告——目标机缺被引用凭据（含空值/空 blob）时按连接给出可操作 hint（设环境变量/建 Windows 凭据项）；secret 永不进入归档、数据库或目标容器，数据库只存 credential reference。

### 7.1 v0.3 一 Project 一工作区与旧库拆分

`DEC-V03-PROJECT-STORAGE`（2026-09-07）批准一次一个活动 `ProjectSession`、一 Project 一 `project.sqlite`。Project 工作区继续使用本节既有 `manifest.json` + `project.sqlite` + 声明附件契约；`projects` 表在一个活动工作区中必须恰有一行。应用级界面语言、最近/上次 Project、数据根和日志级别不进入 Project SQLite；不得为最近列表增加全局业务 SQLite 或跨库外键。

为了保持 Project 的完整审计和可转移性，`provider_connections`、`model_profiles`、`prompt_overrides` 与 `workflow_definitions` 继续位于 Project SQLite。它们只含非敏感配置或凭据引用，实际 secret 仍禁止进入数据库、manifest 和 `.aiproject`。这允许 `projects.active_profile_id`、`segment_attempts.model_profile_id`、`model_profiles.provider_connection_id` 和历史 Attempt 在单库内继续由外键/快照解释。

旧全局多 Project 库拆分必须保持源库只读不变：先用 SQLite Backup API 建一致性快照；每个 Project 在独立 staging 中复制该 Project 从属闭包，并复制全部非敏感 Connection/Profile/Prompt Override/Workflow 以保持旧版可选配置；目标库可保留旧整数 ID，因为 ID 的唯一域变为该 Project 数据库。每个目标写入 manifest `source_id=<旧 project id>`，随后校验 `PRAGMA integrity_check`/foreign-key、表级行数、引用闭包、Revision/current/lock、Attempt、六格式 fidelity carrier 和 credential reference。全部目标验证成功前不得更新应用入口、删除旧库或覆盖任何既有工作区；失败目标不得成为最近 Project。若旧库零 Project 但存在配置、外键损坏、未知 schema 或孤立业务记录，迁移必须停在预检并要求 REPLAN，不得静默丢弃或猜测归属。

- 一个逻辑 Project 只能包含一个 Project 身份；从含零个或多个 Project 的源数据库导出时不得静默选择或夹带其他 Project，实施必须明确拒绝或生成隔离 snapshot；
- 使用相对路径；拒绝绝对路径、盘符/UNC、`..`、归一化后逃逸、大小写或 Unicode 等价重复路径、重复关键 entry 以及 link/junction 类 entry；
- 导入前限制 entry 数、单项大小、总解压大小和压缩比，防止资源耗尽；P1-T02-M03 固定 fixture 默认值：entry 数 ≤1000、单项未压缩 ≤256 MiB、总未压缩 ≤512 MiB、压缩比 ≤5000:1（Release Gate 定稿，调用方可传更窄限额）；
- 只解到新的隔离 staging；在 manifest、版本、路径、大小和所有 hash 校验通过后才运行 migration，全部成功后原子安装为新目标；失败不得覆盖已有 Project；
- 导入目标存在 Project ID 冲突时创建新的本地 Project identity，并在 manifest/import metadata 保留 source/origin ID；名称冲突使用确定性后缀生成建议名称，未经用户显式确认不得覆盖既有 Project；
- API Key、Bearer Token 等秘密绝不进入项目包；credential reference 可保留，但目标机缺凭据时必须给可操作提示；
- logs 默认不打包，Debug 导出必须由用户主动选择并脱敏；
- `format_version` 使用显式兼容矩阵；未知未来版本拒绝，不猜测读取；schema 只向前 migration，不自动 downgrade；
- V1.0 只支持单用户离线迁移、备份和项目转交，不支持并发协作或自动合并。
