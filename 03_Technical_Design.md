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
- Provider Connection：endpoint、认证引用、代理、超时和重试；
- 敏感凭据：优先使用 Windows Credential Manager（通过受维护的凭据封装），也允许环境变量引用；秘密不进入 Project、日志、绿色版数据包或 `.aiproject`。

`.aiproject` 是包含 manifest、SQLite 一致性快照、附件和相对路径的项目包。近期不支持多人并发编辑、自动合并或在线同步。

## 4. 核心翻译数据流

```text
导入文件
 -> 解析并生成稳定 Segment
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

## 5. Model Adapter

统一接口至少提供：

- 请求：model、messages/prompt、语言对、max output、超时、流式设置、结构化输出要求；
- 响应：文本或结构化结果、finish reason、usage、provider request ID、原始响应引用；
- 能力：上下文长度、最大输出、流式、结构化输出、可用参数；
- 错误：分类、Provider 错误码、可重试标志、retry-after。

Provider Connection、Model Capability 和 Model Profile 分离：

- Connection 处理连接与凭据；
- Capability 描述模型实际能力；
- Profile 保存任务用途、Prompt 模板、默认参数、Context 配额和输出规则。

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

- 领取 processing Segment 时写入 attempt ID、lease owner 和过期时间；
- 启动时回收过期 processing，不覆盖人工 revision；
- 每次模型调用先记录 Attempt，再写入响应和 Revision；
- 响应、Revision 和状态更新在同一事务内完成；
- 人工确认或锁定的 Revision 不得被自动翻译覆盖；
- 同一 Segment 的重试必须使用唯一 attempt/idempotency key；
- 取消任务保留已有结果和失败原因。

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

Exporter 只读取已选 Translation Revision。解析器必须保留格式专属元数据，如 JSON 结构、字幕时间轴、ASS/SSA 样式和转义；round-trip 测试作为 V1.0 发布门槛。

## 10. Python 工程边界

建议包结构按职责拆分：`ui`、`application`、`domain`、`infrastructure`、`adapters`。PySide6 对象和信号不得渗入 domain 层；耗时文件解析和模型请求不得阻塞 GUI 主线程；跨线程只传递可序列化 DTO 或不可变领域数据。

SQLite 访问统一由 infrastructure/repository 层管理连接与事务。测试使用 pytest；Qt 交互测试可使用 pytest-qt，但领域、migration 和 Adapter 契约不依赖 GUI 测试。

Windows 绿色版由独立打包任务生成，首选 PyInstaller 作为 V1.0 打包候选；正式锁定前必须以启动耗时、体积、PySide6 插件收集和杀毒软件误报测试验证。打包工具属于实现选择，不改变 Project 数据格式。

## 12. 可观测性与安全

每次 Attempt 可记录 Profile 版本、Prompt hash、参数、模型、耗时、usage 和错误。原始 Prompt/响应默认可配置、可脱敏、可清理；API Key 永不记录。

重大变化遵循：提出修改 → Architecture Review → 更新 Technical Design → 重新规划 Task → 开发。