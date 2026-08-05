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
```

数据库维护 `schema_migrations`：migration_id、checksum、applied_at、app_version。上表截至 P0-T07-M01 已包含 `001`–`006`；后续 Agent 必须先检查真实 migration 目录再选择新编号。

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

`projects`：id、name、source_language、target_language、created_at、updated_at、schema_version。

### SourceDocument

`source_documents`：id、project_id、path/name、format、encoding、source_hash、parser_version、created_at。

SourceDocument 表示不可变的内容与解析版本；逻辑复用身份至少包含 Project、源 bytes hash、format 和会改变 Segment 映射的 parser identity/version。完全相同身份的重复导入返回既有版本；内容、格式或 parser contract 变化时新建 SourceDocument 和 Segment 映射，不自动删除旧版本。当前已发布 `003` 只有 `(project_id, source_hash)` 唯一，P1-T01 必须通过新 migration 扩展身份/去重结构，不得重写 `003`。

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

`segment_attempts` 至少保存：id、run_id、segment_id、claim_version、lease_owner（或等价 claim token）、idempotency_key、model_profile_id、Profile/template/capability snapshot 或稳定版本、prompt_hash、context/parameter/validator 摘要、request_id、status、retryable、input_tokens、output_tokens、latency_ms、error_type、error_message、created_at、finished_at。Attempt `status` 枚举：`created/succeeded/failed/cancelled`。claim token 必须在数据库重开后足以识别 Attempt 属于哪一代 lease；原始 Prompt/响应正文可用受控字段或 artifact reference 保存，但必须可配置、脱敏和清理，其清理不能删除 Revision 或最小审计字段。

一次 Application 层逻辑模型调用对应一个 SegmentAttempt；Adapter transport retry 和一次 capability degradation 属于同一 Attempt，输出 repair 或 failed Segment 重新执行创建新 Attempt。

### ModelProfile 与 ProviderConnection

`model_profiles` 保存非敏感配置：id、name、provider_connection_id（外键）、model_id、template_version、output_protocol、context_budget（JSON）、default_params（JSON）、capability_snapshot（JSON）、created_at、updated_at。

`provider_connections` 保存非敏感连接配置：id、name（唯一）、provider_type、endpoint、timeout_seconds、max_retries、retry_delay_seconds、credential_reference、created_at、updated_at。当前 `004` 只保存这些字段；V1.0 暂不把代理配置列为必需交付。未来若需要代理，必须通过新 migration 增加非敏感、受约束字段并覆盖关闭重开与秘密边界，不能只保存在 UI/进程内存。

`credential_reference` 使用受控语法，例如 `env:VAR_NAME` 或 `wincred:TARGET_NAME`，禁止直接写入 API Key、Bearer Token 等秘密值。

`model_profiles.provider_connection_id` 外键引用 `provider_connections(id)`，删除被引用的 Connection 时被阻止（RESTRICT），保证 Profile 与 Connection 的引用完整性。

### GlossaryEntry

`glossary_entries`：id、project_id、source_term、target_term、scope、priority、is_locked、origin、created_at、updated_at。

V1.0 支持用户维护和翻译时注入；自动提取属于后续增强。

## 4. 后续实体

Character Data、Translation Memory (TM)、World State、RAG 索引元数据属于 Phase 2。V1.0 不要求实现智能召回或向量索引。

## 5. 约束与索引

- 所有业务表使用稳定主键；
- 启用外键，并明确 restrict/cascade；
- `003` 当前提供 `source_documents(project_id, source_hash)` 唯一；P1-T01 新 migration 必须把 format/parser identity 纳入逻辑唯一域并安全迁移既有索引，避免相同 bytes 的不同格式或 parser 版本错误复用；
- `segments(source_document_id, sequence)` 唯一；
- `segments(source_document_id, stable_key)` 唯一，解析器 key 碰撞必须使整次导入失败；
- 为 `segments(status, lease_expires_at)`、`segment_attempts(segment_id, created_at)`、`translation_revisions(segment_id, created_at)` 建索引；
- `segment_attempts.idempotency_key` 必须由数据库唯一约束保护；唯一域可为全局，或包含 Run/Segment，但重复键行为必须确定且不得再次发起模型调用；
- lease claim 使用 `status = pending + expected version + (lease_owner IS NULL 或 lease_expires_at <= now)` 条件写并设置新 owner/未来 expiry；回收只匹配已过期 processing；finalize 必须匹配 claim 的 owner/version 且 lease 尚未过期，`version` 作为 fencing token；
- `translation_runs.workflow_id` 必须引用有效 WorkflowDefinition；
- `current_revision_id` 只能引用同一 Segment 的 Revision；
- 锁定 Revision 不得被自动流程删除或替换；
- 不使用 NULL 表示状态，枚举值必须有文档定义。

## 6. 事务与恢复

一次源文件导入的 SourceDocument 与全部 Segment 必须在同一事务中落库；任一 Segment 失败时整次导入回滚。唯一约束 migration 遇到既有冲突数据时必须失败并保留原数据，不得在没有升级前备份的情况下自动选择或删除版本。

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

- 一个逻辑 Project 只能包含一个 Project 身份；从含零个或多个 Project 的源数据库导出时不得静默选择或夹带其他 Project，实施必须明确拒绝或生成隔离 snapshot；
- 使用相对路径；拒绝绝对路径、盘符/UNC、`..`、归一化后逃逸、大小写或 Unicode 等价重复路径、重复关键 entry 以及 link/junction 类 entry；
- 导入前限制 entry 数、单项大小、总解压大小和压缩比，防止资源耗尽；具体阈值由 P1-T02 fixture 与 Release Gate 固定；
- 只解到新的隔离 staging；在 manifest、版本、路径、大小和所有 hash 校验通过后才运行 migration，全部成功后原子安装为新目标；失败不得覆盖已有 Project；
- 导入目标存在 Project ID 冲突时创建新的本地 Project identity，并在 manifest/import metadata 保留 source/origin ID；名称冲突使用确定性后缀生成建议名称，未经用户显式确认不得覆盖既有 Project；
- API Key、Bearer Token 等秘密绝不进入项目包；credential reference 可保留，但目标机缺凭据时必须给可操作提示；
- logs 默认不打包，Debug 导出必须由用户主动选择并脱敏；
- `format_version` 使用显式兼容矩阵；未知未来版本拒绝，不猜测读取；schema 只向前 migration，不自动 downgrade；
- V1.0 只支持单用户离线迁移、备份和项目转交，不支持并发协作或自动合并。
