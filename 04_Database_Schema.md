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
  002_add_translation_revision.sql
```

数据库维护 `schema_migrations`：migration_id、checksum、applied_at、app_version。

规则：

- 每个 migration 在事务中原子执行；
- 执行前创建可恢复备份；
- 失败时回滚当前事务并保留错误；
- SQLite 不支持直接变更时，使用新表、数据校验、事务切换的表重建流程；
- V1.0 不要求 downgrade，回退依赖升级前备份；
- 已发布 migration 不可重写，修复必须新增编号。

## 3. V1.0 最小实体

### Project

`projects`：id、name、source_language、target_language、created_at、updated_at、schema_version。

### SourceDocument

`source_documents`：id、project_id、path/name、format、encoding、source_hash、parser_version、created_at。

### Segment

`segments`：id、source_document_id、stable_key、source_text、sequence、status、current_revision_id、version、lease_owner、lease_expires_at、created_at、updated_at。

稳定 key 由解析器根据源文件结构生成，不能只依赖当前数组位置。源文件变化时记录新 hash，并显式重建映射。

### TranslationRevision

`translation_revisions`：id、segment_id、text、origin（ai/user/import）、attempt_id、is_locked、created_at。

一个 Segment 可有多个 Revision；当前译文通过 `current_revision_id` 引用，禁止覆盖历史 Revision。

### WorkflowDefinition

`workflow_definitions`：id、name、origin（builtin/user）、parent_workflow_id、version、definition_json、is_read_only、created_at。

V1.0 内置预设以只读、版本化定义提供；用户副本属于后期能力。`translation_runs.workflow_id` 外键引用实际执行定义，并保存运行时 version snapshot，保证结果可复现。

### TranslationRun 与 SegmentAttempt

`translation_runs`：id、project_id、workflow_id、workflow_version、workflow_definition_hash、started_at、finished_at、status。

`workflow_version` 引用不可变的 WorkflowDefinition 版本；`workflow_definition_hash` 用于检测定义被错误改写。

`segment_attempts`：id、run_id、segment_id、idempotency_key、model_profile_id、prompt_hash、request_id、status、retryable、input_tokens、output_tokens、latency_ms、error_type、error_message、created_at。

### ModelProfile 与 ProviderConnection

`model_profiles` 保存非敏感配置：id、name、provider_connection_id、model_id、template_version、output_protocol、context_budget、default_params、capability_snapshot、created_at、updated_at。

`provider_connections` 只保存 endpoint 引用、provider type、timeout、retry policy 和 credential reference；秘密不得明文入库。

### GlossaryEntry

`glossary_entries`：id、project_id、source_term、target_term、scope、priority、is_locked、origin、created_at、updated_at。

V1.0 支持用户维护和翻译时注入；自动提取属于后续增强。

## 4. 后续实体

Character Data、Translation Memory (TM)、World State、RAG 索引元数据属于 Phase 2。V1.0 不要求实现智能召回或向量索引。

## 5. 约束与索引

- 所有业务表使用稳定主键；
- 启用外键，并明确 restrict/cascade；
- `segments(source_document_id, sequence)` 唯一；
- 为 `segments(status, lease_expires_at)`、`segment_attempts(segment_id, created_at)`、`translation_revisions(segment_id, created_at)` 建索引；
- `translation_runs.workflow_id` 必须引用有效 WorkflowDefinition；
- `current_revision_id` 只能引用同一 Segment 的 Revision；
- 锁定 Revision 不得被自动流程删除或替换；
- 不使用 NULL 表示状态，枚举值必须有文档定义。

## 6. 事务与恢复

Attempt 创建、模型响应保存、Revision 创建和 Segment 状态更新必须按阶段使用事务。落库前崩溃时，遗留 `processing` 由 lease 过期回收；人工 Revision 不受影响。失败记录必须区分 retryable 与 permanent。

## 7. `.aiproject` 备份与迁移

项目包包含：

```text
manifest.json
project.sqlite
attachments/
```

manifest 至少记录 format_version、schema_version、源文件 hash、软件版本和附件 hash。导出使用 SQLite 一致性备份机制，不能在 WAL 写入期间直接复制活动数据库文件。

- 使用相对路径，不把绝对路径作为唯一引用；
- API Key、Bearer Token 等秘密绝不进入项目包；
- logs 默认不打包，Debug 导出必须由用户主动选择并脱敏；
- 导入先校验 manifest/hash，再执行 migration；
- V1.0 只支持单用户离线迁移、备份和项目转交，不支持并发协作或自动合并。
