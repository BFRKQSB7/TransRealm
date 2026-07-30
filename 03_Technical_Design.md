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

Project 提供两种互通形态：普通用户使用单文件 `.aiproject`；高级用户可使用开放目录。两者共享同一 manifest、schema/version、相对路径、hash、秘密排除和 migration 契约；开放目录不是第二套业务模型或数据库。`.aiproject` 是 manifest、SQLite 一致性快照和附件的归档视图；开放目录以 `manifest.json`、`project.sqlite` 和声明附件为权威，source/translation/config 等人类可读目录只能作为 manifest 声明内容，不能绕过数据库状态、Revision 或校验。近期不支持多人并发编辑、自动合并或在线同步。

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

## 8. 错误处理

- 网络断开、限流、临时 Provider 错误：有限次数指数退避；
- 本地模型停止：暂停队列并提示用户，不无限重试；
- 超时：标记可重试 Attempt，保留 request ID/错误信息；
- 输出格式错误：执行 Profile 指定的有限修复；仍失败则进入 failed，不直接写译文；
- 程序关闭或断电：依赖 SQLite 事务和 lease 恢复 processing；
- 认证、参数和格式等永久错误：不自动重试，显示可操作错误。

## 9. Export 与格式保真

Exporter 默认读取 Segment 的 `current_revision_id`；用户显式选择历史 Revision 时，必须验证该 Revision 属于同一 Segment 且有效，不能把 Adapter response、Validator candidate 或源文作为静默回退。解析器与 Exporter 必须共享格式专属定位元数据；缺失/错配 metadata 或 Revision 时拒绝导出，不留下半文件。

V1.0 保真基线：无翻译导出与导入 bytes 一致；翻译后只允许目标文本 span 改变，并保留原编码/BOM、换行及非目标结构。JSON 只翻译 string leaf value，保留 key、非字符串值、顺序、空白和转义；SRT/VTT 保留 cue 标识、时间轴/settings 与非目标块；ASS/SSA 根据 Events Format 只替换 Dialogue Text，保留 section、style、comment、字段顺序、标签和转义。损坏或不支持输入默认拒绝，不静默“修复”。round-trip golden tests 是 V1.0 发布门槛。

## 10. Python 工程边界

建议包结构按职责拆分：`ui`、`application`、`domain`、`infrastructure`、`adapters`。PySide6 对象和信号不得渗入 domain 层；耗时文件解析和模型请求不得阻塞 GUI 主线程；跨线程只传递可序列化 DTO 或不可变领域数据。

SQLite 访问统一由 infrastructure/repository 层管理连接与事务。测试使用 pytest；Qt 交互测试可使用 pytest-qt，但领域、migration 和 Adapter 契约不依赖 GUI 测试。

P0-T08 的 GUI 仅为核心 TXT 翻译闭环提供薄桌面入口；UI 只能调用 Application Service，解析、数据库和模型请求必须在可控 worker 中执行并返回 DTO。每个 worker/thread 拥有自己的 SQLite connection 生命周期，不跨线程传递 connection/cursor；关闭时先停止接收新工作，再通过 P0-T07 的取消/lease 语义收敛，不能以强杀线程伪装成功。P1-T04 先补齐 Project Profile 选择与基础 Glossary，P1-T03 再增加自动模式与工作台模式的默认策略、参数暴露和交互差异；两种模式继续复用同一状态机、Validator、Application Service 和 Revision 保护。运行中 Run 不因 UI 模式切换改变 Profile/Workflow/参数；用户必须选择继续当前 Run 或取消后以新配置创建后续 Run。

Windows 绿色版由独立打包任务生成，首选 PyInstaller 作为 V1.0 打包候选；Phase 0 只验证候选工具能 build/start，V1.0 Release Gate 才冻结依赖并验证启动、体积、PySide6 插件、路径/恢复/清理和杀毒扫描。打包工具属于可验证的实现选择，不改变 Project 数据格式；构建候选不代表已发布。

## 11. Attempt 可观测性与安全

每次 Attempt 在重启后至少可解释：Run/Segment/Profile、Profile/template/capability 快照或稳定版本、Prompt hash、Context/参数与 Validator 摘要、Provider request ID、模型、状态、retryable、开始/完成时间、耗时、usage 和错误。原始 Prompt/响应正文默认可配置、可脱敏、可清理；Revision 和上述最小审计字段不得随 Debug 清理消失；API Key 永不记录。

生产 HTTP transport 默认不跟随可能泄露凭据的跨 origin 重定向。若实现允许重定向，scheme/host/port 变化必须移除 Authorization，HTTPS 降级不得携带凭据；本机显式配置的兼容 HTTP endpoint 可直接使用。Provider body、错误、UI 和日志都必须经过 secret 脱敏边界。

重大变化遵循：提出修改 → Architecture Review → 更新 Technical Design → 重新规划 Task → 开发。