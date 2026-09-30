# TransRealm 项目瘦身 / 复杂度削减审阅

> 审阅基准：当前工作树（2026-09-20）与 `TransRealm_Product_Reset_RFC_v1.2.md`。本报告只提出分类、边界和实施顺序，不修改源码、测试、数据库、migration、现有权威文档或 Git 历史。

## 1. Executive Summary

当前主要冗余不在 SQLite、Parser、Exporter、Attempt/Revision/Recovery，而在三个上层区域：第一，Auto / Workbench 被实现成持久化 Project 状态、两套 UI 路径、两个 Worker 入口和大量模式测试；第二，Workflow、ModelProfile、PromptOverride 等旧产品概念仍直接暴露给 UI，虽然其中部分字段又承担历史可复现和 Adapter 配置职责；第三，根目录的编号文档、Task 历史、Architecture Review 和 1050 行运行状态混合了当前契约与历史流水，使 Agent 开工必须消费约 7000 行 Markdown，且容易被 Product Reset 已推翻的路线重新污染。

值得保留的复杂度非常明确：12 个 append-only migration、SQLite 事务、SourceDocument/Segment identity、六格式 Parser/Exporter、raw bytes 与 fidelity metadata、lease/fencing/idempotency、Attempt/Revision、locked revision、凭据隔离、归档隔离导入、恢复和绿色版资源校验。这些模块虽然文件和测试很多，但分别保护旧项目可打开、译文不丢失、格式不被破坏、崩溃后可恢复、API Key 不泄漏，不能作为“代码多”而削减。

推荐使用渐进式收敛，而不是目录重写：先用单一 Translation Workspace 取代模式 UI，再让一个 TranslationService/Facade 成为 UI 高频入口；ModelProfile 暂时降级为内部兼容配置对象；Workflow 缩为 Run 创建与历史快照兼容层；最后才删除无调用的转发层和模式专属代码。预计活跃 Application surface 可从 20 个模块降到 9～12 个主要入口，主 UI 从 Settings/Project/Translation + 模式子界面收敛为 Translation/Providers/Prompts 三页，活跃权威文档从当前 01～09 + 大型状态文件收敛为 4～6 份，源代码可安全减少约 8%～15%，旧架构导向的测试维护面可减少约 15%～25%；Parser、Exporter、Migration、Recovery 的保护强度不下降。

## 2. File Inventory

### 2.1 量化基线

| 项目 | 当前数量 | 当前规模 / 说明 | 建议目标区间 |
|---|---:|---|---:|
| `src/transrealm/**/*.py` | 81 | 约 15,742 行 | 68～75 个；约减少 8%～15% LOC |
| `tests/**/*.py` | 70 | 约 28,415 行，约 1,100 个 test function | 55～62 个；约减少 15%～25% 维护面 |
| Markdown | 24 | 约 7,124 行；另有 3,377 行 Product Reset RFC 和 752 行本轮提示词 | 活跃权威 4～6 份；历史材料归档 |
| Application 模块 | 20 | 不含 `__init__.py` | 9～12 个活跃入口，另保留 3 个冻结兼容模块 |
| Domain 模块 | 10 | Project、Profile、Workflow 等均独立 | 8～10；不为数字强行合并 |
| Repository 模块 | 10 | 对应持久实体 | 9～10；Workflow repo 缩窄为兼容 API |
| Parser 模块 | 6 | registry + TXT/JSON/SRT/VTT/ASS-SSA | 6，保持不变 |
| 主 UI 页面 | 3 | Settings、Project、Translation；Translation 内再分 Auto/Workbench | 3：Translation、Providers、Prompts |
| UI Python 模块 | 10 | 含兼容 facade、workbench widgets、worker/theme/i18n | 7～9 |
| SQL migration | 12 | `001`～`012` | 12+；只追加，不删除或改写 |

上述数量来自当前工作树文件清单，不等同于已提交基线。工作树当前已有大量既有修改和未跟踪 RFC/提示词/测试文件，因此后续实施必须先建立可恢复 checkpoint，不能把本报告的估计直接当作删除授权。

### 2.2 逐目录判断

| 目录 / 文件组 | 当前责任 | 结论 |
|---|---|---|
| `src/transrealm/adapters/` | OpenAI-compatible DTO、协议、HTTP transport、错误归一化、env/wincred 凭据 | KEEP；只在 capability mapping 上做小幅简化 |
| `src/transrealm/application/` | 20 个 service/helper，既含核心翻译也含归档、安装、模式 UI 支撑 | 主要瘦身区：KEEP + MERGE + FREEZE |
| `src/transrealm/domain/` | 10 个持久化相关 domain model | 大多 KEEP；Project mode 与 Workflow/Profile 做兼容降级 |
| `src/transrealm/infrastructure/migrations/` | migration discovery、backup、runner、错误 | KEEP，不合并为“简洁”而削弱故障边界 |
| `src/transrealm/infrastructure/parsers/` | 六格式解析和稳定 locator | KEEP |
| `src/transrealm/infrastructure/repositories/` | SQLite 映射与事务操作 | KEEP；只收窄无调用 API |
| `src/transrealm/infrastructure/fidelity.py` | 原始载体、hash、locator/metadata 验证 | KEEP |
| `src/transrealm/infrastructure/open_directory.py` | manifest、路径/hash/ZIP 限额和容器完整性 | FREEZE；旧 Project / `.aiproject` 兼容必需 |
| `src/transrealm/ui/` | 三页 UI、Auto/Workbench、线程 worker、i18n/theme | 最大的可见瘦身区；先替换页面，再删除旧控件 |
| `src/transrealm/migrations/*.sql` | 已发布 schema 历史 | KEEP，禁止修改或删除 |
| `tests/` | 迁移、格式、恢复、UI、release gate 等 70 文件 | 保留数据安全行为，重写/合并旧模式与旧 UI 结构测试 |
| `scripts/build_release.py` | PyInstaller onedir、migration/i18n 资源与 manifest 验证 | KEEP |
| `scripts/check_candidate_hygiene.py` | 候选敏感/禁止文件检查 | KEEP，可并入 release 命令但不应删除保护 |
| `scripts/verify_task.py` | allowed paths、删测试、指定测试门禁 | SIMPLIFY/FREEZE；随新开发流程决定是否保留独立脚本 |
| 根目录编号文档与状态文件 | 产品、架构、任务、审查、治理、历史状态混合 | ARCHIVE + 合并；这是上下文成本最大的非代码来源 |

## 3. KEEP

### 3.1 数据与可靠性底座

- `src/transrealm/infrastructure/database.py`、`src/transrealm/infrastructure/migrations/`、`src/transrealm/migrations/001_init.sql`～`012_add_prompt_override.sql`：保护旧库向前升级、事务和升级前一致性备份。`006` 建立 Run/Attempt/Revision/Workflow 外键，`007` 回填 Workflow snapshot，`008` 增加 raw bytes / format metadata，`009`～`012` 分别承载 active profile、Glossary、mode 和 PromptOverride；即使上层概念冻结，也不能修改这些历史 migration。
- `src/transrealm/domain/segment.py`、`segment_attempt.py`、`translation_revision.py`、`translation_run.py` 及对应 repository：保护逐 Segment claim、lease、fencing、idempotency、失败/重试、current revision 和历史可恢复性。Product Reset 的单 Segment 请求正是建立在这套状态机上。
- `src/transrealm/infrastructure/repositories/segment_attempt_repository.py`：759 行看似庞大，但承担 claim/finalize/recover 的事务原子性，不应为了减少 Service 数量下沉或重写。
- `src/transrealm/domain/provider_connection.py`、`adapters/credential_resolvers.py`、`adapters/http_transport.py`、`adapters/openai_adapter.py`：分别保护连接配置、secret 引用、重定向/超时安全和 capability-driven 请求映射。

### 3.2 格式与保真

- `src/transrealm/infrastructure/parsers/` 全部保留。五类格式实现和 registry 不是重复 Parser；JSON、字幕和 ASS/SSA 的安全边界不同，强行合并会增加 locator 与写回风险。
- `src/transrealm/application/exporter.py` 与 `src/transrealm/infrastructure/fidelity.py` 保留。Exporter 的 873 行来自六格式 replacement plan、编码/BOM/newline、原子写和载体验证，直接保护“非目标内容不变”。
- `src/transrealm/application/import_service.py` 保留为 Loader 入口，后续可被 Translation facade 包装，但不应重写 parser/persistence seam。

### 3.3 翻译核心

- `src/transrealm/application/translation_run_service.py` 保留。它虽然有 695 行和较多职责，但其中 Run 创建、Attempt claim/finalize、Revision edit/lock、恢复和进度读取共享同一事务状态机；第一轮只让 facade 包装，不拆底层状态机。
- `src/transrealm/application/translation_service.py` 保留并升级为主 facade。当前它已经完成一段翻译的 Context → Prompt → Adapter → Validator → Attempt/Revision 闭环，是新 Pipeline 最合适的 strangler 起点。
- `src/transrealm/application/prompt_renderer.py`、`context.py`、`context_composer.py`、`glossary_context.py`、`output_parser.py` 暂时保留行为；随后按单 Segment plain-text 默认、Notes/Neighbor/Glossary 语义做合并和缩窄。
- `src/transrealm/domain/glossary_entry.py` 与 Glossary repository/service 保留。它是 RFC 明确要求的 Job 级 Context 来源。

### 3.4 发布与安全

- `scripts/build_release.py`、`RELEASE_CHECKLIST.md` 和关键候选 hygiene 检查保留。构建脚本显式验证 12 个 migration、`.qm` 翻译资源和 Qt 插件，删除会让冻结应用无法升级旧库或启动。
- `SECURITY.md`、`docs/data-safety.md`、`docs/third-party-licenses.md` 保留其事实内容，但可以纳入新的用户/发布文档集合，避免多处重复版本信息。

## 4. SIMPLIFY

### 4.1 Auto / Workbench：移除产品概念，保留字段兼容

数据库层保留 `projects.mode` 和 migration `011_add_project_mode.sql`，repository 继续读写该列以打开旧 Project；新建记录仍可写默认 `auto`。Domain 层第一阶段保留 `Project.mode` 作为 deprecated 载入字段，但新业务不分支读取它；新 UI 和新 facade 不调用 `with_mode()` / `set_mode()`。等至少一个稳定版本证明旧项目读取无回退后，才可删除 `MODE_AUTO`、`MODE_WORKBENCH`、`SUPPORTED_MODES`、`with_mode()` 和 `ProjectService.set_mode()` 的活跃写路径，数据库列仍不删除。

Application/UI 层的具体收敛如下：

| 路径 | 当前模式责任 | 建议 |
|---|---|---|
| `src/transrealm/ui/translation_page.py` | mode selector、Auto overview、Workbench 显隐、模式切换、工作台编辑器 | 用单一 Workspace 替换；保留段列表、手工编辑、重试、Revision lock、导出和高级设置折叠区 |
| `src/transrealm/ui/worker.py` | `translate_auto`、`translate_workbench` 两个 wrapper 最终都调用 `translate` | 合并为一个 `start_translation(job, document, model_settings)` 入口；active/default 解析放 facade，不保留模式命名 |
| `src/transrealm/application/workbench.py` | `SegmentProgress` + 参数 UI metadata | 将 `SegmentProgress` 移到翻译 read-model；参数 spec 移到 Provider/Model settings；文件随后删除 |
| `src/transrealm/ui/workbench.py` | 参数、Prompt、Revision 三组 Workbench widgets | 将仍需要的三个控件拆入 Translation/Providers/Prompts 页面，删除“Workbench”容器概念 |
| `src/transrealm/ui/i18n/*.ts/.qm` | Mode/Auto/Workbench 文案 | 新页面切换后删除旧文案并重新编译资源 |

测试方面不删除 migration/旧 Project 读取断言：保留“011 可升级并读取 `auto/workbench`”以及归档 round-trip 对未知旧值 fail-closed 的兼容测试；删除或重写仅验证模式选择器、显隐、切换中拒绝和 mode label 的测试。具体涉及 `tests/test_p1_t03_m01.py`、`test_p1_t03_m02.py`、`test_p1_t03_m05.py`、`test_v02_t04_m01.py`，但这些文件同时包含 active profile、参数快照、Stop/close、重开和进度等必要行为，不能整文件删除。

### 4.2 Workflow：从活跃领域实体降级为 Run 兼容元数据

新的一次请求一个 Segment Pipeline 不需要用户可选择的 Workflow，也不需要 Workflow UI；但当前 `translation_runs.workflow_id` 是 `NOT NULL` 外键，`translation_service.create_run()` 会查找 seeded builtin，Run 又保存 version/hash/snapshot 以解释历史执行。因此第一阶段选择 **FREEZE + SIMPLIFY**：继续 seed 唯一 builtin、继续写外键和 snapshot、继续读取旧 Run；不再公开 create/update/delete/list Workflow 能力，不再新增 user workflow 或 parent chain 功能。

逐文件建议：

| 路径 | 结论 | 最小保留面 |
|---|---|---|
| `src/transrealm/domain/translation_workflow.py` | FREEZE/SIMPLIFY | builtin 定义、canonical JSON、hash 校验；不扩展编辑模型 |
| `src/transrealm/infrastructure/repositories/translation_workflow_repository.py` | SIMPLIFY | `save`（仅 seed）、`get_by_id`、`get_by_name_and_version`；删除无生产调用的 `get_by_name`、`list_all`、`delete` |
| `src/transrealm/domain/translation_run.py` | KEEP | 旧 FK、version/hash/snapshot 与历史验证 |
| `src/transrealm/application/translation_run_service.py` | SIMPLIFY | seed 与 snapshot 建 Run 内聚；不对 UI 暴露 workflow_id |
| `src/transrealm/application/translation_service.py` | KEEP | 创建 Run 时内部选择固定 legacy builtin，UI 不知道 Workflow |
| `006`、`007` migration | KEEP | 不修改、不删除，不做破坏性 migration |

### 4.3 ModelProfile：选择 B，内部 compatibility object

选择 **B：简化为内部 compatibility object**，而不是 A 的长期原样保留，也不是 C 的立即拆表。当前 ModelProfile 同时被 Adapter、Profile repository、Attempt `profile_snapshot`、active profile FK、PromptOverride FK、Context budget 和参数过滤使用；立即拆成 Provider + ModelSettings + PromptTemplate 会引入 migration、旧 Attempt 解释、删除保护和 UI 同步风险，成本高于近期收益。

最低成本方案是保留 `model_profiles` 表、domain/repository 和历史快照格式，让新 Providers 页面把它呈现为“Provider + Model settings”，让 Prompts 页面通过现有 `prompt_overrides` 暂存可编辑模板；Translation Workspace 只使用选择结果，不显示 ModelProfile 术语。`ModelProfileService` 后续缩为内部 ModelSettings/Profile compatibility service，`template_version`、`output_protocol`、`context_budget` 和 capability snapshot 继续供旧数据与 Adapter 使用。只有新 UI 稳定并明确需要“一份 Prompt 被多个 Model 复用”时，再用追加 migration 引入独立 PromptTemplate；不能为了概念纯洁先拆现有表。

### 4.4 Application Service 逐文件裁定

| 文件 | 当前责任 / 当前生产调用方 | 未来调用方 | 裁定 |
|---|---|---|---|
| `adapter_factory.py` | Connection + Profile 组合 Adapter；UI worker | Translation facade / Provider gateway | KEEP，后续可并入 provider composition |
| `archive_service.py` | `.aiproject` 导出和隔离 staging；无生产 UI caller，测试调用 | legacy import/export compatibility | FREEZE，不删除 |
| `context.py` | Budget/Candidate/Manifest/Output DTO | ContextBuilder、Validator | SIMPLIFY；移除未落地的 Character/TM/RAG/World enum 值或标 deprecated，避免未来概念继续扩散 |
| `context_composer.py` | Neighbor/Glossary budget composition；TranslationService | 新 ContextBuilder | MERGE/RENAME 渐进完成，不先搬目录 |
| `credential_status.py` | 凭据可用性提示；三页 UI | Providers page | MERGE 到 provider-facing service，但保留 secret-safe 行为 |
| `exporter.py` | 六格式 fidelity export；TranslationPage | Translation facade | KEEP |
| `glossary_context.py` | Glossary → ContextCandidate 单函数；TranslationService | ContextBuilder | MERGE 到 ContextBuilder |
| `glossary_service.py` | Glossary CRUD；三页 UI | Translation facade / workspace side panel | KEEP 或 facade 内聚，不删除 |
| `import_service.py` | Parser registry、SourceDocument/Segment 保存、fidelity backfill | Translation facade / Loader | KEEP |
| `install_service.py` | staging migration、原子安装；无生产 UI caller | legacy container compatibility | FREEZE，不删除 |
| `model_profile_service.py` | Profile + PromptOverride CRUD、引用保护；四个生产 caller | Providers/Prompts facade | SIMPLIFY 为内部 compatibility service |
| `open_directory_service.py` | 容器创建/打开/向前迁移；archive/install 调用 | legacy open/import path | FREEZE，不删除 |
| `output_parser.py` | 多 item JSON 输出解析、污染/repair | 新 Validator/Normalizer | SIMPLIFY；新增 plain-text 单段路径后再缩减旧 JSON 分支 |
| `preset_templates.py` | 当前 preset 和 override 解析；五个生产 caller | Prompts service / Renderer | MERGE 到 prompt 模块；不新增模板 DSL |
| `project_service.py` | Project CRUD、active profile、mode、删除备份 | Translation facade + legacy container | SIMPLIFY；移除 mode 写入口，保留 Job/删除安全与兼容读取 |
| `prompt_renderer.py` | 纯 Prompt 渲染和 output contract | Pipeline | KEEP，收敛为 PromptInput → RenderedPrompt |
| `provider_connection_service.py` | Connection CRUD、引用保护 | Providers page/facade | KEEP；可吸收 credential status |
| `translation_run_service.py` | Run/Attempt/Revision/Recovery 状态机和 read model | Translation facade | KEEP/SIMPLIFY；不把事务逻辑拆散 |
| `translation_service.py` | 单段端到端翻译；worker | 唯一高频 Translation facade | KEEP 并扩展 facade API |
| `workbench.py` | SegmentProgress + 参数控件 metadata；run service/三页 UI | 拆入 translation read-model 与 model settings | SPLIT 后 DELETE |

收敛后 UI 不应直接同时实例化 ProjectService、ImportService、ModelProfileService、ProviderConnectionService、GlossaryService 和 TranslationRunService。高频 Translation 页面通过一个 facade 执行 create/open job、import、start/stop/resume/retry/edit/lock/export；Providers 与 Prompts 页面各自只依赖一个窄 service。冻结的 archive/install/open-directory 仍可作为兼容模块存在，但不计入日常 UI service surface。

### 4.5 UI 页面与配置

`settings_page.py` 当前同时管理 Connection、Profile、语言和高级参数，应拆成 Providers page 与少量应用设置；`project_page.py` 当前同时管理 Project、导入、active profile 和 Glossary，应把 Job/导入/Glossary 放回 Translation Workspace；`translation_page.py` 已达 1207 行，应通过新页面替换而不是继续条件分支。目标不是立即把代码搬进新目录，而是让主窗口只构造 Translation、Providers、Prompts 三个页面，旧页面在功能迁移完成后整体删除。

## 5. FREEZE

| 冻结对象 | 只保留的 compatibility seam | 禁止继续扩展 |
|---|---|---|
| `.aiproject` / Open Directory | 旧归档校验、隔离 staging、旧 schema 向前迁移、可写工作区安装、secret 排除 | 新附件生态、同步、多人编辑、更多容器形态 |
| Workflow | 固定 builtin seed、Run FK、version/hash/snapshot 读取 | 编辑器、用户 workflow、节点图、parent/version 产品功能 |
| `projects.mode` | migration 011、repository/domain 读取、旧 archive round-trip | UI selector、新业务分支、新模式 |
| ModelProfile 旧字段 | 旧表、active_profile FK、Attempt snapshot、Adapter capability | 新 Profile 产品概念、更多职责堆叠 |
| PromptOverride 旧绑定 | 旧 profile-bound override 读取与 fail-closed stale 检查 | 复杂 DSL、多级继承、工作流绑定 |
| v0.2 Release / Gate 历史 | 候选身份、回滚和安全证据 | 作为 Product Reset 的活跃产品需求 |
| 复杂治理扩展 | migration/安全/发布等高风险门禁 | 为每个普通小功能新增一套角色、状态和重复文档 |

Archive、Install 和 Open Directory 当前没有生产 UI caller，但拥有大量兼容/安全测试，而且 RFC 的 V1-Release DoD 明确要求旧 `.aiproject` / open directory 可打开。因此它们是典型 FREEZE，不是 DELETE-CANDIDATE。

## 6. DELETE-CANDIDATE

当前能满足“无生产调用且无数据库兼容职责”的候选很少。下列对象也只能在独立删除切片中执行；本报告不授权删除。

### 6.1 `src/transrealm/ui/pages.py`

- **无调用证据：** 当前生产代码由 `main_window.py` 直接 import `project_page`、`settings_page`、`translation_page`；仓库中只有 `tests/test_v02_t01_m01.py` 与 `tests/test_p1_t04_m04.py` 引用 `transrealm.ui.pages`。
- **依赖分析：** 文件只重导出四个类，没有状态、逻辑、migration、Project 读取、format fidelity 或 recovery 职责。
- **删除风险：** 可能破坏仓库外仍使用旧 import path 的脚本；项目尚未承诺稳定 Python API，风险低但需在 release notes 说明。
- **需要修改的测试：** 两个测试改为从责任模块导入，并把“兼容 facade 无 Qt 副作用”的断言改到实际模块。
- **回滚方式：** 恢复 17 行 re-export facade；不涉及数据回滚。

### 6.2 `WorkflowDefinitionRepository.get_by_name()`

- **无调用证据：** 全仓库只有方法定义，无源码或测试调用；运行时使用 `get_by_name_and_version()`。
- **依赖分析：** 不影响 builtin seed、Run FK、snapshot、migration 或历史 Project 读取。
- **删除风险：** 仅潜在仓库外 Python 调用；无产品 UI 暴露。
- **需要修改的测试：** 无现有测试依赖；增加/保留 `get_by_name_and_version` 的 seed/compat 测试即可。
- **回滚方式：** 恢复单个 SELECT 方法。

### 6.3 `WorkflowDefinitionRepository.list_all()`

- **无调用证据：** 无生产 caller；仅 `tests/test_p0_t07_m01.py` 与 `tests/test_p1_t02_m05.py` 用它检查 seed/跨机状态。
- **依赖分析：** 可用 `get_by_name_and_version()` 或直接兼容 fixture 查询表达相同用户行为；运行时无需列出 Workflow。
- **删除风险：** 若未来恢复 Workflow UI 会缺列表 API，但“未来也许”不是保留理由。
- **需要修改的测试：** 把 seed 唯一性与归档保留断言改为按固定 builtin name/version 读取；不降低 snapshot/hash 断言。
- **回滚方式：** 恢复 repository 查询；无数据迁移。

### 6.4 `WorkflowDefinitionRepository.delete()`

- **无调用证据：** 全仓库只有定义，无生产或测试调用。
- **依赖分析：** Workflow FK 为 `ON DELETE RESTRICT`，且 builtin 标记 read-only；活跃产品不应删除 Workflow。保留该方法反而扩大误用面。
- **删除风险：** 仓库外脚本若调用会失效；数据本身不受影响。
- **需要修改的测试：** 无；应继续保留 FK RESTRICT 和 builtin read-only 测试。
- **回滚方式：** 恢复单方法。

### 6.5 `00_Project_Manager_Guide.md` 与 `AI_CONTEXT_INDEX.md`

这两个文件已明确标注“已废弃”，而 `DEVELOPMENT_STATE.md` 还要求不要读取它们。它们更适合先移入 `docs/archive/legacy-entrypoints/`，待内部链接和外部 README 检查后再作为删除候选；由于仍承担旧链接重定向说明，本轮将它们列为 **ARCHIVE-first**，不是立即删除。

### 6.6 暂不进入 DELETE 的对象

`ui/workbench.py`、`application/workbench.py`、mode 常量/方法和旧 UI 测试目前都有真实调用；它们只能在新 Workspace 替代调用方后进入 DELETE。`archive_service.py`、`install_service.py`、`open_directory_service.py` 虽无 UI caller，却承担 RFC 明确要求的旧 Project/归档兼容；不能因“只被测试调用”删除。Workflow domain/repository 文件整体也不能删除，因为 Run 创建和历史 snapshot 仍依赖它们。

## 7. ARCHIVE

以下文件应退出“每次开工的活跃权威集”，迁入 `docs/archive/` 并保留只读历史：

| 当前文件 | 原因 | 建议归档位置 |
|---|---|---|
| `01_PRD.md` | 仍定义 Auto/Workbench、复杂 Workflow、Character/TM/World/Style/RAG/GPU 等被 RFC 推翻的产品方向 | `docs/archive/old-prd/PRD-v1.md` |
| `02_Development_Roadmap.md` | Phase 2～4 大量冻结平台能力仍以未来计划呈现 | `docs/archive/old-roadmaps/Roadmap-v3.md` |
| `07_Developer_Task_List.md` | 802 行混合已完成 P0/P1、v0.2/v0.3 与旧模式任务；应作为历史 ledger，不再是新路线任务入口 | `docs/archive/task-ledgers/Developer-Task-List-v5.md` |
| `08_Architecture_Review.md` | 1175 行包含大量历史 Reality Check/Gate 记录；当前稳定决策应提炼进 Architecture | `docs/archive/historical-reviews/Architecture-Review-v3.md` |
| `00_Project_Manager_Guide.md` | 已废弃旧入口 | `docs/archive/legacy-entrypoints/` |
| `AI_CONTEXT_INDEX.md` | 已废弃旧入口 | `docs/archive/legacy-entrypoints/` |
| 当前 `DEVELOPMENT_STATE.md` 的历史 checkpoint 段 | 1050 行中大量已完成 P0/P1 checkpoint 不属于当前运行状态 | `docs/archive/state-ledgers/`，状态文件只留当前窗口与最近 checkpoint |
| `TransRealm_Product_Reset_RFC_v1.2.md` | 在 Product Reset 获正式采纳并提炼后，RFC 本身转为设计历史 | `docs/archive/rfcs/`；采纳前仍是当前产品依据 |
| `TransRealm项目缩减提示词.md` | 本轮执行提示，不是长期产品/架构契约 | `docs/archive/review-prompts/` 或完成后不纳入活跃集 |

`03_Technical_Design.md`、`04_Database_Schema.md`、`05_Prompt_Architecture.md`、`06_AI_Development_Guide.md`、`09_Unattended_Development_Governance.md` 的有效内容不应直接归档丢失，而应分别合并进新的 Architecture、Database、Development 文档；迁移完成且交叉链接更新后，原编号文件再归档。

## 8. Proposed Minimal Architecture

建议的最小架构不是立即移动目录，而是先建立以下责任边界：

```text
UI
├─ Translation Workspace
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
├─ Segmenter / Request Builder
├─ Context Builder (Neighbor + Glossary + Notes)
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

Legacy Compatibility (not on the main UI path)
├─ projects.mode read compatibility
├─ Workflow FK + snapshot
├─ ModelProfile / PromptOverride storage compatibility
└─ .aiproject / Open Directory import-open path
```

新 facade 应先包装现有 service，而不是重写 repository。推荐第一阶段 API 为 `create_or_open_job`、`import_file`、`start`、`stop`、`resume`、`retry_failed`、`retranslate_segment`、`edit_translation`、`set_locked`、`export_document` 和只读进度查询；Providers/Prompts CRUD 保持独立窄入口。Archive/Open Directory 不进入主 facade 的日常依赖图，只作为显式兼容流程调用。

## 9. Proposed Minimal Documentation Set

建议活跃文档集合为：

```text
README.md
DEVELOPMENT_STATE.md

docs/
  PRODUCT.md
  ARCHITECTURE.md
  DATABASE.md
  DEVELOPMENT.md
  RELEASE.md
  user-guide.md
  archive/
```

- `docs/PRODUCT.md`：由 Product Reset RFC 提炼当前定位、MUST/SHOULD/WON'T、三页 UI 和里程碑；替代活跃的 `01`/`02`。
- `docs/ARCHITECTURE.md`：合并 `03`、`05` 与 `08` 中仍有效的接口、依赖方向和 ADR；历史 Gate 不进入正文。
- `docs/DATABASE.md`：从 `04` 提炼 schema、append-only migration、兼容字段和数据不变量，独立保留是因为数据安全风险高。
- `docs/DEVELOPMENT.md`：合并 `06`、`09`、`CONTRIBUTING.md` 的开发流程、Reality Check、输出目录和权限边界，删除重复段落。
- `docs/RELEASE.md`：吸收 `RELEASE_CHECKLIST.md`、构建命令、候选身份和 AV 三态政策；版本特定结果留在 release notes/state ledger。
- `DEVELOPMENT_STATE.md`：仅保留 frontmatter、当前 Task/Milestone、当前授权/阻塞、受保护 dirty、最近一次 checkpoint、下一步和归档索引；目标 150～250 行。

普通 Agent 开工只需读 3 份：`AGENTS.md`、`DEVELOPMENT_STATE.md`、`docs/PRODUCT.md`。涉及代码时再按状态文件精确路由到 `docs/ARCHITECTURE.md` 或 `docs/DATABASE.md`；涉及发布才读 `docs/RELEASE.md`。不再默认读取 01～09 全套，也不把历史 Task ledger 放在启动上下文。

## 10. Database / Migration Safety Review

第一阶段数据库策略是 **零瘦身**：12 个 migration 原样保留，schema 字段原样读取，新逻辑停止依赖 deprecated 概念但不删除列/表。`projects.mode` 保持默认与 CHECK，旧 `auto/workbench` 均能载入；新 UI 忽略其产品语义。`workflow_definitions`、`translation_runs.workflow_id`、version/hash/snapshot 全部保留，使历史 Run 可重开和审计。`model_profiles` 与 `prompt_overrides` 保持 FK 和历史 snapshot 语义，避免 active profile、Attempt 以及 archive/open-directory 断裂。

任何后续追加 migration 必须先通过：旧 001～012 库升级、升级前 backup、失败回滚、foreign key check、旧 `.aiproject`/open-directory 导入、六格式 round-trip、Run/Attempt/Revision/locked current、credential reference 不泄漏。不得把 mode/workflow/profile 的 UI 删除与 schema 清理放在同一 Milestone；至少跨一个稳定 release 观察真实旧数据兼容后，才可另开数据库 RFC。

Product Reset 新增 Notes 时使用独立追加 migration；智能分段不得重写旧 SourceDocument 或 remap Revision，而应通过 parser/mapping identity 创建新 SourceDocument。删除代码前必须用真实的旧 schema fixture 和当前 schema fixture 各跑一次打开、翻译/恢复、导出路径。

## 11. Test Reduction Plan

### 11.1 必须保留

- `test_migrations.py`、数据库/异常测试，以及 P0-T07 M01～M05 中 migration backup、claim、lease/fencing、finalize、failure/retry、crash/reopen 的核心断言。
- P1-T01 系列六格式 parser/exporter/fidelity/round-trip 测试；这些测试量大但保护 raw bytes、locator、BOM/newline、非目标内容不变。
- Adapter/transport/credential/provider、Prompt renderer、Context budget、输出 validator 的行为测试。
- Revision 手工编辑、current 切换、lock/unlock、自动结果不得覆盖 locked current、export 使用 current revision 的测试。
- `.aiproject` / open-directory 的 path traversal、hash、资源限额、隔离 staging、迁移、secret 排除和旧项目打开测试；可以降低执行频率，但不能删除行为覆盖。
- 构建脚本包含 migration/i18n/Qt 资源、候选无用户数据和解压启动的 release 测试。

### 11.2 删除或重写

- 删除仅断言 `Mode: auto/workbench` 文案、mode selector 当前值、Auto/Workbench 显隐和切换反馈的 UI 测试；改为单一 Workspace 的用户旅程测试。
- `tests/test_p1_t03_m01.py` 中 011 migration、旧 mode 读取与 archive round-trip 保留；`set_mode` CRUD 和 Auto 专属 UI 旅程在新页面切换后删除。
- `tests/test_p1_t03_m02.py` 中参数 capability、Attempt snapshot、进度读取保留并迁移到 Providers/Workspace；仅 Workbench widget/显隐测试重写。
- `tests/test_p1_t03_m03.py` 的 PromptOverride domain/repository/security 测试保留；WorkbenchPromptEditor 测试迁到 Prompts page 后删除旧 widget 结构断言。
- `tests/test_p1_t03_m04.py` 的 Revision/lock/export/recovery 测试保留；WorkbenchRevisionEditor 的控件结构测试改为 Workspace 用户行为。
- `tests/test_p1_t03_m05.py` 中 mode switch 测试删除；document switch、Stop、close convergence、restart、project switch 等行为改写为统一 Workspace 测试。
- `tests/test_v02_t01_*`、`test_v02_t04_*` 中只保护具体页面层级、旧文案或 legacy facade import 的测试，在新 UI 行为测试覆盖后删除。

### 11.3 合并策略

当前测试按历史 Milestone 命名，导致同一用户行为跨多个大文件重复建库、建 Profile、导入 TXT。建议在不降低断言的前提下重组为行为域：`test_migrations_compat.py`、`test_formats_<format>.py`、`test_translation_recovery.py`、`test_revision_workflow.py`、`test_provider_adapter.py`、`test_workspace_ui.py`、`test_legacy_project_compat.py`、`test_release_build.py`。先建立共享 fixture 与行为覆盖矩阵，再删除历史文件；不能先按文件名批量删除。

目标不是把约 1,100 个 test function 机械砍半，而是把用户行为与数据不变量保留、把旧 UI 形状和 Milestone 重复 setup 移除。合理目标是 test 文件 70 → 55～62，测试 LOC 约减少 15%～25%，核心 migration/format/recovery 用例数量基本不减。

## 12. Reduction Estimate

| 项目 | 估计变化 | 依据 |
|---|---:|---|
| 直接删除文件 | 6～12 个 | legacy UI facade、替换后的 workbench/mode 模块、少量过渡文件；兼容模块不计入 |
| 冻结文件 | 8～14 个 | archive/open-directory/install、Workflow/Profile compatibility、历史 release 路径 |
| 合并/收窄模块 | 8～12 个 | context/glossary helper、provider credential status、prompt preset、UI service 调用面 |
| 源码规模 | 约 -8%～-15% | 主要来自 mode UI、旧页面、转发层与重复 orchestration，不动 parser/exporter/recovery |
| 测试维护量 | 约 -15%～-25% LOC | 删除旧 UI 形状和 Milestone 重复 setup；核心可靠性用例保留 |
| 活跃 Application surface | 20 → 9～12 | 高频 facade + Providers + Prompts；3 个 legacy compatibility 模块仍存在但冻结 |
| 主 UI | 3 页 + 双模式子界面 → 3 页单路径 | Translation / Providers / Prompts |
| 活跃权威文档 | 01～09 + State/Guide/Checklist → 4～6 | 历史迁入 `docs/archive/` |
| Agent 默认必读 | 十余份 → 3 份，按风险增读 1 份 | AGENTS + State + Product；代码/数据任务按需加读 |

这些数字是完成新 Workspace、facade 和文档迁移后的区间，不是本轮立即可删数量。当前立即可证明的代码删除候选只有一个 17 行 UI facade 和三个 Workflow repository 方法；大部分收益必须先通过替换调用方获得。

## 13. Implementation Order

1. **Baseline / Freeze：** 先采纳 Product Reset，建立可恢复 commit、旧库 fixtures、六格式 round-trip 和核心恢复测试清单；不删代码。
2. **UI / dead caller：** 新建单一 Workspace、Providers、Prompts 页面；迁移段列表、手工编辑、lock、参数、Prompt、Glossary、导入/导出；主窗口切换到新页面后证明旧 Auto/Workbench UI 无 caller。
3. **Application dead code：** Worker 合并为单入口，Translation facade 包装 Project/Import/Run/Export；收窄 UI 直接 service 依赖；再删除 mode-specific wrapper 和 `application/workbench.py` 的残余。
4. **Workflow/Profile compatibility cleanup：** UI 不再暴露 Workflow/ModelProfile 术语后，删除 Workflow repo 无调用方法，固定 builtin compatibility；ModelProfile 继续作为内部 envelope，不做 schema 拆分。
5. **Domain compatibility cleanup：** 新业务完全不读取 mode 后，删除 mode 常量、validation、`with_mode` 和 service setter，但保留数据库列读取；跨一个稳定 release 后才评估 schema RFC。
6. **Tests：** 新行为测试先到位，再删除旧模式/旧 widget 结构测试；最后按行为域合并历史 Milestone 文件。
7. **Docs：** 生成 Product/Architecture/Database/Development/Release，缩短 State，更新所有链接后把 01/02/07/08 和旧入口移入 archive。
8. **最后验证：** 全量 pytest/Ruff/mypy、旧 001～012 数据库、六格式 fidelity、crash/recovery、credential、archive/open-directory compatibility、Windows build/launch；任何 Unknown 都不是 Passed。

这个顺序遵循 `UI / dead caller → application dead code → domain compatibility cleanup → tests → docs`，同时把 database/migration/fidelity 排除在前期删除范围之外。

## 14. BLOCKER

- **Product Reset 尚未成为现有状态入口中的已激活实施 Task。** 当前 `DEVELOPMENT_STATE.md` frontmatter 仍指向 `V02-T05-M02` verification，Product Reset RFC 也处于未跟踪工作树状态。可以用 RFC 做本次审阅依据，但不能据此自动开始删除或改写现有路线。
- **工作树不是干净可恢复基线。** 当前已有 01～09、README、用户文档、UI/i18n、测试等大量既有修改和未跟踪文件；后续不能用 reset/clean，也不能把用户改动与瘦身提交混合。实施前必须先确认这些改动的归属并建立明确 checkpoint/rollback ref。
- **Auto/Workbench 仍有真实调用方。** `translation_page.py`、`worker.py`、`ProjectService`、Project domain/repository、i18n 和 14 个测试文件仍依赖 mode；在新 Workspace 接管前不能删除。
- **Workflow 仍是强 schema 依赖。** `translation_runs.workflow_id NOT NULL` + FK、`007` snapshot、builtin seed 和 `TranslationService.create_run()` 均在使用；只能先冻结和缩窄，不能整实体删除。
- **ModelProfile 仍是 Adapter 与历史 Attempt 契约。** active profile、PromptOverride、capability、context budget、default params 和 `profile_snapshot` 均依赖现有形状；不能立即拆表。
- **Legacy Project compatibility 尚无正式支持窗口裁决。** RFC 要求旧 `.aiproject` / open directory 可打开，但尚未规定支持到哪个版本、何时允许退役。未裁决前 archive/install/open-directory 只能 FREEZE。
- **测试不能按历史文件整批删除。** P1-T03 和 V02-T04 文件把旧 UI 断言与 Revision、Stop、close、reopen、参数 snapshot 等核心行为混在一起，必须先按行为拆分。
- **文档迁移需要一次原子链接切换。** 01～09 之间存在多处互相引用，状态入口和治理文档又声明它们为权威；新文档未落地、链接未更新前不能把旧文件直接移动。

解除这些阻塞后的第一个安全实施切片应是：只建立 Product Reset 的文档/基线 Task 与兼容测试矩阵，不改数据库；第二个切片才实现新 Translation Workspace 并切断模式 UI caller。任何删除都应成为独立、可回滚的后续切片。
