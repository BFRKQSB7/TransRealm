# TransRealm 数据库契约

> 状态：数据库、migration、备份与恢复规则的唯一文档权威。发生差异时，真实 migration、运行 schema、Repository 和数据安全测试优先；先标记冲突，不修改历史 migration 迁就文档。

## 1. 存储基线

TransRealm 使用单用户 SQLite。连接必须启用：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
```

应用写操作使用事务；正常退出提交，异常回滚。Repository 是业务持久化入口，UI 不直接执行 SQL。

## 2. Append-only Migration

真实 migration 位于 `src/transrealm/migrations/`，当前已发布序列为：

| ID | 契约 |
|---|---|
| `001_init` | `projects` |
| `002_add_source_document_and_segment` | `source_documents`、`segments` |
| `003_add_import_uniqueness` | SourceDocument/Segment 唯一性 |
| `004_add_provider_connection` | `provider_connections` |
| `005_add_model_profile` | `model_profiles` |
| `006_add_workflow_run_attempt_revision` | Workflow、Run、Attempt、Revision |
| `007_add_run_workflow_snapshot` | Run 的 Workflow definition snapshot |
| `008_add_format_fidelity` | `raw_bytes`、`format_metadata` 与解析身份 |
| `009_add_project_active_profile` | Project active profile FK |
| `010_add_glossary_entry` | Project-scoped Glossary |
| `011_add_project_mode` | 旧 Auto/Workbench 读取兼容 |
| `012_add_prompt_override` | Profile-bound Prompt override |

规则：

- 已发布 migration 永不改写、重排、删除或复用编号；变化只能增加下一个编号文件。
- `schema_migrations` 记录 id、checksum、时间和应用版本；已应用 checksum 不一致必须失败。
- 每个 migration 的 DDL 与 history insert 在显式事务中原子执行；失败不得记录为已应用。
- 有 pending migration 时，在第一条执行前使用 SQLite backup API 创建同目录、可打开的一致性备份；备份失败则不得开始升级。无 pending 时不创建无意义备份。
- 升级测试必须覆盖旧库、WAL、一致性备份、失败回滚、checksum、foreign keys 和重开。

## 3. 当前 Schema

以下是 `001`–`012` 叠加后的逻辑契约；类型和约束以 SQL 文件为准。

### 3.1 `projects`

- 身份与语言：`id`、`name`、`source_language`、`target_language`。
- 版本与时间：`schema_version`、`created_at`、`updated_at`。
- `active_profile_id`：可空 FK → `model_profiles(id)`，`ON DELETE RESTRICT`。
- `mode`：非空，默认 `auto`，只允许 `auto`/`workbench`。它是旧项目读取兼容字段，新产品不把它作为 UI 模式或新业务分支。

Project 删除会级联 SourceDocument、Run 和 Glossary；实现还必须在持有有效 lease 等阻塞条件下 fail closed，并按任务验收提供备份/恢复路径。

### 3.2 `source_documents`

- `project_id` FK → Project，删除级联。
- `name`、`format`、`encoding`、`source_hash`、`parser_version`。
- `raw_bytes` 与 `format_metadata` 保存格式保真载体。
- 逻辑复用唯一性：`(project_id, source_hash, format, parser_version)`。

源 bytes、format 或 parser identity/version 改变时创建新的不可变 SourceDocument 映射；不得原地改写旧映射并猜测迁移 Revision。

### 3.3 `segments`

- `source_document_id` FK → SourceDocument，删除级联。
- `stable_key`、`source_text`、`sequence`；文档内 sequence 与 stable key 均唯一。
- `status` 默认 `pending`；运行时状态为 `pending`、`processing`、`completed`、`failed`。
- `current_revision_id` 指向当前选择的 Revision（历史 schema 未声明 FK，Repository 必须验证归属）。
- `version`、`lease_owner`、`lease_expires_at` 支持 claim 与 fencing。

`stable_key` 用逻辑 sequence 与规范化源文形成稳定身份，不包含 raw byte offset；byte span 只属于 fidelity locator。

### 3.4 `provider_connections`

- `name` 唯一；保存 `provider_type`、`endpoint`、timeout、有限 retry 与 delay。
- `credential_reference` 可空，只允许受验证的 `env:` 或 `wincred:` 引用；不得保存 secret 正文。

### 3.5 `model_profiles`

- FK `provider_connection_id` → ProviderConnection，`ON DELETE RESTRICT`。
- 保存 `model_id`、`template_version`、`output_protocol`、`context_budget`、`default_params`、`capability_snapshot`。
- 当前作为内部兼容 envelope，保护 active profile、PromptOverride、Adapter 组合和历史 Attempt snapshot。UI 产品概念收敛不等于可以拆表或删除字段。

### 3.6 `workflow_definitions`

- `(name, version)` 唯一；保存 origin、parent、definition JSON/hash、read-only。
- 历史兼容需要 builtin definition 与 hash 可重现。新产品不提供 Workflow 编辑器，但表和 fixed builtin seed 保留。

### 3.7 `translation_runs`

- FK `project_id` → Project，删除级联。
- 非空 FK `workflow_id` → WorkflowDefinition，`ON DELETE RESTRICT`。
- 保存 workflow version、definition hash、definition snapshot、运行状态与时间。
- 状态只允许 `running`、`completed`、`failed`、`cancelled`。

### 3.8 `segment_attempts`

- FK → Run、Segment、ModelProfile；Run/Segment 删除级联，Profile 删除受限。
- claim identity：`claim_version` + `lease_owner`。
- `idempotency_key` 全局唯一。
- 保存 `profile_snapshot`、`prompt_hash`、`context_summary`、`validator_summary`、provider `request_id`、token、latency 与脱敏错误。
- 状态只允许 `created`、`succeeded`、`failed`、`cancelled`；`retryable` 是明确布尔值。

同一 Attempt 只允许不改变语义输入的 transport retry 和协议级 capability degradation。Context、Prompt、target 或语义参数改变时新建 Attempt。

### 3.9 `translation_revisions`

- FK `segment_id` → Segment，删除级联；可空 `attempt_id` → Attempt，Attempt 删除时置空。
- `origin` 只允许 `ai`、`user`、`import`。
- `is_locked` 保护人工确认结果；自动 finalize 不得覆盖 locked current Revision。
- Revision 是 append-style 历史。切换 current 不删除旧 Revision。

### 3.10 `glossary_entries`

- FK `project_id` → Project，删除级联；`(project_id, source_term)` 唯一。
- `priority` 为 0–100，越高越先注入；`is_locked` 是布尔值。
- `origin` 只允许 `user`、`import`。当前翻译上下文只注入锁定项。

### 3.11 `prompt_overrides`

- 与 ModelProfile 1:1，Profile 删除时级联。
- 保存 `parent_template_version` 与模板文本；preset 版本变化导致 stale 时必须 fail closed，不静默套用。

## 4. Attempt、Lease、Fencing 与恢复

Segment 的最小状态机：

```text
pending → processing → completed
pending → processing → failed
failed → pending
processing → pending  (lease 过期或安全恢复)
```

- claim 必须用当前状态、version 与 lease 条件进行原子写，并生成新的 owner 与未来过期时间。
- 第一次外部模型请求前创建 Attempt，保存 claim identity、idempotency、Profile/Prompt/Context 摘要。
- finalize success、failure、cancel 必须再次验证 Segment 仍由同 owner/version 持有且 lease 未过期。
- success 在一个事务中新增 Revision、设置 `current_revision_id`、更新 Segment 状态/version、清除 lease 并终结 Attempt。
- 迟到 worker、过期 lease 或并发变更必须被 fencing 拒绝。
- 恢复时终结过期的活动 Attempt，并根据 locked/current Revision 保留已完成结果或把 Segment 收敛为安全可重试状态。

## 5. 备份、归档与容器

### 5.1 Migration 备份

升级前备份通过 `sqlite3.Connection.backup` 创建，适用于 WAL；备份必须重新打开并执行基本 schema/integrity 验证。它保护数据库升级，不是 Project 交换格式。

### 5.2 `.aiproject` 与 Open Directory

两种形态共享 manifest、schema/version、canonical relative path、size/hash、秘密排除和 migration 契约。Open Directory 的权威内容是 `manifest.json`、`project.sqlite` 与 manifest 声明附件；未声明文件不是 Project 状态。

`.aiproject` 是标准 ZIP 归档视图。导出必须通过 SQLite backup API 生成一致性 snapshot，并原子写目标；导入先进入全新隔离 staging，限制 entry 数、单项/总大小与压缩比，拒绝 absolute/drive/UNC/`..`、重复/未声明成员、link/junction 与归一化逃逸。验证完成后才允许 migration 和原子安装；覆盖既有目标需要显式确认及可恢复备份。

数据库和归档只保存 `credential_reference`，不包含凭据正文、日志或未声明用户文件。

## 6. Format Fidelity

`raw_bytes` 和 `format_metadata` 保存编码、BOM、newline、locator 与格式特定信息。Exporter 必须：

- 验证 Segment、Revision 和 locator 归属。
- 默认导出 `current_revision_id`；显式 override 也必须逐 Revision 验证。
- 任一 Segment 缺可用 Revision 时失败，不回退源文冒充完成。
- 只替换目标 span，保持非目标 bytes 与结构不变。
- 在同目录写临时文件并原子替换；编码、权限或验证失败时保持既有目标不变并清理临时文件。

## 7. Product Reset 的数据库边界

- 删除 Auto/Workbench UI 不删除 `projects.mode`。
- 冻结 Workflow UI 不删除 Workflow 表、Run FK 或 snapshot。
- 简化 Model/Profile 用语不删除 ModelProfile、active profile、Attempt snapshot 或 PromptOverride。
- Revision Lock 已存在，不新增重复字段。
- Notes 尚无当前表；实现时必须使用新的追加 migration，不得塞入旧 migration 或复用无关字段。
- 智能分段不得原地重写已翻译 SourceDocument/Segment；需要版本化新映射。
- History Retrieval 若落地，索引能力必须运行时探测，并在 migration、备份、fallback 与 Windows 构建中验证。

## 8. 数据变更门禁

任何 schema、Project 格式、恢复或删除变更都必须在对应 Task 中列出旧数据 fixture、前向升级、失败回滚、备份恢复、FK/integrity、秘密边界和导入导出影响。Unknown/未运行不等于 Passed；不得把 UI 删除与 schema 清理放在同一实现切片。
