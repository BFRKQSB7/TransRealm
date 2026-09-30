# TransRealm 架构

> 状态：当前架构方向与兼容边界的唯一权威来源。实现事实以 `src/`、migration、schema 和保护真实行为的测试为准。

## 1. 设计目标

TransRealm 继续使用 Python 3.12、PySide6、SQLite 和 OpenAI-compatible HTTP。Product Reset 不推倒已经验证的数据、格式与恢复底座，而是收敛上层产品和调用面，把复杂度集中在分段、上下文、翻译可靠性和格式保真。

依赖方向保持：

```text
UI
  → Application / Facades
    → Domain
    → Infrastructure / Adapters
```

UI 不直接访问 SQLite 或 Provider；外部调用通过 Adapter；持久化通过 Repository 与事务；Parser/Exporter 不访问 UI、Prompt 或 Provider。

## 2. 目标运行结构

```text
UI
├─ Translation
├─ Providers
└─ Prompts
        │
        ▼
Translation Facade
├─ Job / Import / Export
├─ Start / Stop / Resume / Retry / Edit / Lock
└─ Translation read models
        │
        ▼
Single-Segment Pipeline
├─ Loader / Format-aware Segmenter
├─ Request Builder
├─ Context Builder
├─ Prompt Renderer
├─ OpenAI-compatible Translator
├─ Response Normalizer / Validator
└─ Saver
        │
        ▼
Reliable Core
├─ SQLite + append-only Migration
├─ Run / Attempt / Revision / Lease / Fencing
├─ Parser / Exporter / Fidelity
└─ Credential isolation

Legacy Compatibility (不在主 UI 路径)
├─ projects.mode 读取兼容
├─ Workflow FK / hash / snapshot
├─ ModelProfile / PromptOverride 存储兼容
└─ .aiproject / Open Directory
```

新 facade 应先包装既有 Service 和 Repository，不重写可靠内核。Translation UI 的高频能力最终只经一个 facade；Providers 与 Prompts 各使用一个窄入口。

## 3. Single-Segment Pipeline

主流程为：

```text
Loader
→ Segmenter
→ Request Builder
→ Context Builder
→ Prompt Renderer
→ Translator
→ Response Normalizer / Validator
→ Saver
```

一次请求恰好包含一个 target Segment。Neighbor、Glossary、Notes 和可选 History 都只是 Context，不在本次调用中生成独立 Revision。Loader 负责格式解析、SourceDocument/Segment 与 fidelity metadata；它不负责 Prompt、Provider 或翻译。

### 3.1 格式边界

- TXT 可按段落、对话、句末标点和长度阈值确定性分段，但每个 Segment 必须映射到连续、可验证的原始 span。
- JSON 默认一个可翻译 string value 对应一个 Segment。
- SRT/VTT 默认一个 cue 对应一个 Segment。
- ASS/SSA 默认一个 Dialogue event 的 Text 字段对应一个 Segment。
- 非 TXT 原子单位过大时给出可操作失败或要求更大 context model；Exporter/metadata 未明确支持前不得硬切。

### 3.2 Context

V1-Release 的 Context 来源只有 Neighbor、Glossary 和 Notes；History 是 V1-Full 可选增强。预算必须确定性、可记录并设硬上限；优先保留目标文本、Prompt 固定开销、锁定术语和必要 Notes，再裁剪 History 与较远 Neighbor。

Provider 报 context overflow 后，若裁剪会改变 Prompt/Context，必须结束当前 Attempt 并创建新 Attempt；不能沿用旧 `prompt_hash` 冒充同一输入。

### 3.3 Prompt 与输出

Prompt Renderer 是纯函数式边界，输入语言、目标文本、Context、Glossary、Notes 和模板，输出 system/user 内容；它不访问数据库、UI、Provider 或 Retriever。V1 模板保证 `source_lang`、`target_lang`、`text`、`context`、`glossary`、`notes`，可选 `segment_id`、`previous_translation`，不建立模板 DSL。

默认响应是一段纯文本译文。结构化输出只有在 capability 明确支持时启用。Normalizer/Validator 负责空输出、回显、截断、reasoning wrapper 和协议错误；改变 Prompt/协议语义的降级使用新 Attempt。

## 4. Provider 与凭据

`ProviderConnection` 保存端点、超时、重试策略和 `credential_reference`；秘密只通过 `env:` 或 `wincred:` 在调用时解析，不进入 Project、SQLite 明文字段、日志、归档或错误消息。跨源或 HTTPS 降级重定向不得携带 Authorization 等敏感头。

`ModelProfile` 当前同时承载 model id、capability snapshot、context budget、默认参数、模板版本和输出协议。产品 UI 不再使用 “Model Profile” 作为主概念，但在拆表有明确收益且追加 migration 获批前，它继续作为内部兼容 envelope。Provider 参数必须 capability-driven；不得假设所有兼容端点支持同一参数。

## 5. Reliable Core

SQLite、append-only migration、升级前一致性备份、事务、foreign key、WAL、Attempt/Revision 和格式保真都属于保留底座。数据库完整契约见 `docs/DATABASE.md`。

Segment claim 使用状态、`lease_owner`、`lease_expires_at` 与 `version` 原子取得。完成、失败、取消均须匹配 owner/version 且 lease 未过期；迟到 worker 不能覆盖新 owner。每次改变语义输入的模型调用都创建新 Attempt；同一逻辑请求的有限 transport retry 可留在同一 Attempt。成功写入 Revision、更新 `current_revision_id` 和释放 lease 必须原子完成。

手工 Revision 与 `is_locked` 是数据契约。自动翻译不得覆盖 locked current Revision；恢复必须保留已经完成的 Revision，并把安全可重试的过期 processing 状态收敛回 pending。

## 6. Parser、Exporter 与 Fidelity

现有 TXT、JSON、SRT、VTT、ASS、SSA Parser 保留。Parser 负责安全定位单位、稳定 identity 与 fidelity carrier；Exporter 只替换已验证的目标 span，保留 encoding、BOM、newline、非目标 bytes 与格式 metadata，并通过同目录临时文件和原子替换避免半成品。

`SourceDocument` 的复用身份至少包含 Project、source hash、format 与 parser version。`raw_bytes` 和 `format_metadata` 是格式保真契约，不因上层 UI 概念删除而移除。

## 7. Legacy Compatibility

### 7.1 Project mode

`projects.mode` 与 `auto/workbench` 值继续读取，以打开旧数据库和归档；新产品不显示模式选择器，也不根据 mode 建立第二套业务路径。移除活跃写路径是后续实现任务，数据库列和 migration 不在此次 Product Reset 中删除。

### 7.2 Workflow

`translation_runs.workflow_id` 是 `NOT NULL` FK，历史 Run 还保存 version、definition hash 与 snapshot。因此继续 seed 和读取固定 builtin Workflow，但不向用户公开创建、编辑、删除、节点图或 parent chain。Workflow 是 Run 兼容元数据，不是活跃产品能力。

### 7.3 ModelProfile 与 PromptOverride

保留现有表、FK、active profile、Attempt `profile_snapshot` 与 stale override fail-closed 语义。Providers/Prompts 页面可以换产品用语，但不得破坏历史 Attempt 的解释能力或 Adapter capability。

命名 Prompt 副本使用数据库同目录的私有 `.prompts.json` 设置文件，原子替换保存，不新增公共数据库表。应用副本时仍把有效文本写入既有 PromptOverride，并验证 preset parent version；库中的改名、编辑、删除不会回写已应用的 override 或历史 Attempt。归档仍以已应用的 override 为翻译输入，命名库本身属于本机设置。

### 7.4 `.aiproject` 与 Open Directory

保留 manifest、路径/hash 校验、资源限制、隔离 staging、SQLite 一致性 snapshot、迁移、原子安装、秘密排除与旧项目打开。该路径被冻结为兼容能力，不扩展附件生态、同步、多人编辑或新容器形态。

## 8. 当前 Reality Check

Product Reset 描述的是接下来要实现的唯一方向，但当前代码仍包含 Auto/Workbench UI、多个 UI 直接 Service 依赖、Workflow/Profile 产品用语和旧 Prompt/输出路径；Notes 表、新 Translation Workspace、格式感知 TXT 智能分段和可选 History Retriever 尚未全部落地。

这是需要后续 Tasks 逐步收敛的 **REALITY CONFLICT**，不是删除数据库或重写基础设施的授权：

```text
NEW PLAN:
单一 Translation Workspace，Translation / Providers / Prompts 三页，单 Segment Pipeline。

CURRENT REALITY:
可靠底座已存在，但旧 Auto/Workbench、Workflow/Profile 兼容调用面仍有真实 caller；Notes 与部分新 Pipeline 能力尚未实现。

RECOMMENDED RESOLUTION:
先以新 UI/facade 替代 caller，再在独立可回滚 Tasks 中删除失去调用方的旧上层代码；schema 与 migrations 保持追加兼容。
```

## 9. 变更规则

- 不为目录纯洁或命名统一进行大规模重写。
- 不修改或删除已发布 migration；数据库变化只能追加。
- 新依赖必须解决当前可验证问题，并审查版本、许可、安全、lockfile 和打包影响。
- 新 Workspace 与 facade 应先建立替代调用方；旧代码只有在无 UI caller、无数据兼容职责且有回归证据后才能删除。
- Parser、Exporter、Migration、Recovery、凭据和归档兼容的保护强度不得为了减少文件数而降低。
