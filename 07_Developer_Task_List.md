# 译境 / TransRealm

# Developer Task List V5

所有 Task 的环境、缓存、临时数据、证据和 artifact 目录选择均受 `09_Unattended_Development_Governance.md` §6.1 的 `D:/TransRealm/` 输出边界约束。历史“仓库外归档”仅是过去事实；“可自主决定 artifact 目录”不包含项目外位置。恢复入口统一为 `D:/TransRealm/DEVELOPMENT_STATE.md`，文档裁决不授予开发或环境整理权限。

## 0. v0.2 / v0.3 当前批准任务

v0.2 是 v0.1.0 可靠内核之上的桌面可用性版本。在 V02-T05 完成前不启动 Phase 2 的 RAG、TM 或 Character Data。v0.3 只在 `DEC-V03-PROJECT-STORAGE` 裁决后实施 Project 工作区与容器 GUI。

无人值守代码阶段禁止创建、切换或删除分支，始终保持在用户当前分支；按 Milestone 形成可恢复本地 checkpoint，但本地 commit、push、merge、tag、Release 均按 `DEVELOPMENT_STATE.md` 的显式授权执行。自动测试只使用临时数据库和本地 fake endpoint，不得读取或修改真实 `~/.transrealm`、仓库内 `x.db`、用户源文件或付费模型。

统一视觉门禁：中文/英文；1280×720@100% 与 1920×1080@150%；主壳、Settings、Project、Auto、Workbench、空状态、错误状态和运行中禁用状态。结构断言、实际交互、截图和独立视觉 Review 缺一不可；不得用逐像素相等作为跨 Qt 版本的唯一门禁。

### V02-T00 — v0.2 事实基线与计划冻结

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0 planning；P0 Governance；Low；completed（2026-08-22，Markdown-only）。
- **base_commit：** `1542291ca43dd17c874b18d3c109ec34b49ae463`。
- **Reality Audit：** REFINE——v0.1 功能和发布事实保留；旧 state frontmatter 的 `3ef991d`/dirty/P1-T05 当前指针失真，必须重置。
- **目标：** 冻结 v0.2/v0.3 范围、依赖、视觉门禁、授权边界和下一 Task；使唯一交接入口与 Git 事实一致。
- **非目标：** 不改源码、测试、脚本、配置、依赖或 artifact；不运行会写缓存的质量命令；不创建、切换或删除分支，不创建外部资源；本地 planning checkpoint 仅按当前状态授权执行。
- **allowed_paths：** `01`、`02`、`03`、`06`、`07`、`08`、`09`、`DEVELOPMENT_STATE.md`。
- **完成条件：** 权威文档一致声明 v0.2 优先、V02-T01 保持 `proposed`/代码未授权、`DEC-V03-PROJECT-STORAGE` 延后至 v0.3；Git diff 仅为 Markdown。

### V02-T01 — UI 基础、视觉系统与中英文

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P1 用户可见；Medium；completed（M01–M04 全部门禁通过，M04 checkpoint `609d529960b7d47654def7a4d4b3a21fe19257b9`）。
- **base_commit：** `9c0be23e6e598939b1a672e8bed4958e7ce2cbaf`（当前分支 planning checkpoint，未 push）。
- **Reality Audit：** SPLIT——页面拆分、主题、主壳、i18n 和视觉 Gate 分成垂直 Milestone，避免一次性重写 UI。
- **目标：** 保持 Application/Domain/Infrastructure 契约，建立清晰、可维护、可本地化的桌面层和一致视觉语言。
- **非目标：** 不改 schema、Project/容器格式、翻译状态机、Prompt、模型协议；不引入第三方 UI 框架、暗色主题或动画系统。
- **现场：** `MainWindow` 720×560 默认 Qt 三 Tab；`ui/pages.py` 约 1,600 行；英文硬编码；无 `QTranslator`/语言持久化。
- **硬约束：** UI 只调用 Application Service；worker/SQLite 线程边界不变；拆分后保留兼容 re-export；语言切换不改变业务数据和 Run；英文为缺失翻译回退；翻译资源进入冻结包。
- **修改范围上限：** `src/transrealm/ui/**`、必要 UI 资源和打包收集、V02-T01 测试、受影响文档；无 migration/新运行依赖。
- **兼容性基线：** P0-T08、P1-T03、P1-T04 UI/worker/关闭恢复测试和现有程序化页面入口。
- **异常/视觉验收：** 缺资源/非法语言值安全回退；150% DPI 无截断；错误不吞；冻结场景矩阵、Tab/焦点、disabled/focus/error 状态通过独立视觉 Review。
- **Milestone：** M01 页面职责拆分且行为不变；M02 主壳/导航/token/浅色主题；M03 Qt i18n/运行时切换/持久化/打包；M04 全量回归、截图矩阵和独立 Review。
- **M01 当前证据：** `page_base.py`、`settings_page.py`、`project_page.py`、`translation_page.py` 已拆分，`pages.py` 保留兼容 re-export；新增结构验收 3 项；受影响旧回归基线保持通过，本次锁定环境定向 UI/worker/关闭回归 **131 passed**；全量 pytest **1338 passed, 5 skipped**；Ruff clean、mypy 136 files clean、GUI smoke PASS。
- **M01 门禁结果：** `DEC-V02-T01-M01-GATE-BASELINE` 已按批准方案完成：隔离 Python 3.12 精确恢复 `requirements.lock` 并 `pip check` 通过；旧 v0.1 `dist` 已连同 manifest/ZIP/EXE hash 可逆归档至仓库外；活动 `dist` 为空；所有 skip 有适用性说明；独立只读 Review `APPROVE-WITH-MINORS`，无 BLOCKER/SHOULD-FIX。M01 checkpoint 与 M02 checkpoint 均已创建，Task 后续 M02–M04 已完成并汇总为 T01 checkpoint。
- **M02 门禁结果：** `theme.py` light tokens/QSS、header shell、三 Tab scroll wrapper 和 surface palette 已实现；`MainShell` 保留已发现的旧 `QTabWidget` 查询/导航入口（`currentIndex`/`setCurrentIndex`/`count`/`widget`/`tabText`/`currentWidget`）。新增验收 **3 passed**；受影响 UI/worker/关闭回归 **134 passed**；全量 pytest **1341 passed, 5 skipped**；Ruff/mypy clean；`pip check` clean；原生 Windows Qt 100%/150% GUI 可见与关闭 smoke PASS，原生 150% 截图无文本/层级截断，离屏 1920×1080 目标截图页面 surface 正确；UI boundary/秘密/绝对路径扫描与 `git diff --check` 通过。独立 Review 复审为 `APPROVE-WITH-MINORS`，无 BLOCKER/SHOULD-FIX；M02 checkpoint 为 `165c87e4377d7e1ace119991df3e5ddc541de61c`。
- **M03 Reality Check：** 2026-08-23 **FIT**——M02 主壳/page seam 可复用；现场无 `QTranslator`/`QSettings`/i18n 资源目录，PySide6 6.11.1 已提供 Qt 原生 i18n/settings 与 `lrelease`；现有 PyInstaller 仅收集 migrations，翻译资源收集落在已批准的必要打包路径；不改 schema、Project 数据格式、业务服务、worker 线程边界或新增运行依赖，无 pending decision。
- **M03 门禁结果：** `LanguageManager`、en/zh_CN `.ts/.qm`、Settings 语言选择器、运行时重翻译、动态 Workbench editor 绑定和 PyInstaller i18n 收集/冻结守卫已实现；新增验收 **3 passed**，受影响旧回归 **137 passed**，全量 pytest **1344 passed, 5 skipped**，Ruff/mypy/pip check clean；原生 Windows Qt English→中文切换/重启持久化、100% 中文与 150% 英文截图、关闭 smoke PASS；未改 schema/业务/线程边界。独立 Review `APPROVE`，无 BLOCKER/SHOULD-FIX/MINOR；M03 checkpoint 为 `dbf31da1ad6668389cf0e453f70b93d461204a4b`。
- **M04 Reality Check：** 2026-08-23 **FIT**——M01–M03 checkpoint/依赖已满足；M04 仅做最终验证与证据收束，不引入产品行为或新依赖。
- **M04 门禁结果：** 原生 Windows Qt 已覆盖 Settings 的英文/中文 × 100%/150%，Project/Translation 空状态代表性组合，以及 Translation error/running-disabled/focus/Workbench 的英文/中文 × 100%/150% 补证；100%/150% 可见/关闭 PASS，代表性截图人工检查无重叠/截断，滚动内容可达。文档按代表性组合如实记录，不将每个状态的语言/DPI 全组合过度声明；最终全量 pytest **1344 passed, 5 skipped**、Ruff/mypy/pip check clean；资源/秘密/路径/范围检查 clean，未构建候选。首轮 Review 指出的问题已修正，第二轮独立 Review `APPROVE`，无 BLOCKER/SHOULD-FIX/MINOR；M04 checkpoint 为 `609d529960b7d47654def7a4d4b3a21fe19257b9`。
- **完成条件：** 旧 UI 回归、全量 pytest/Ruff/mypy、视觉 Gate 和文档同步全部通过。

### V02-T02 — Project 生命周期与六格式 GUI

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P0 用户数据；High；in_progress（M04 当前）。依赖 V02-T01、V02-T02-M01、V02-T02-M02、V02-T02-M03，已由 `bf13d0f85a3b5f2c0cff188e71cf4789e35b9638` 满足。
- **Reality Audit：** SPLIT——六格式 UI 是既有服务接线；Project 删除是高风险数据操作，分别实现后做联合 Gate。
- **目标：** GUI 暴露 TXT/JSON/SRT/ASS/SSA/VTT 导入/翻译/保真导出，并提供可恢复的 Project 删除。
- **非目标：** 不接 `.aiproject`/开放目录 GUI；不改变 format metadata/保真契约；不迁移为一 Project 一库。
- **硬约束：** 按 SourceDocument.format 分派且保留扩展名；失败不覆盖目标。删除前一致性备份；运行中 Run/有效 processing lease 拒绝；显示从属摘要并输入 Project 名确认；单事务删除；不删除外部文件。
- **修改范围上限：** Project/Import/Export Application Service、Project Repository 最小删除能力、UI、测试和文档；若需要 migration 则 REPLAN。
- **安全/异常验收：** 备份失败、取消、并发运行、事务故障均零删除；其他 Project/全局配置不受影响；备份可恢复。六格式分别完成 GUI fake-endpoint 旅程和 P1-T01 保真矩阵。
- **Milestone：** M01 六格式通用 GUI；M02 删除服务/备份/故障测试；M03 删除 UI/运行保护；M04 联合 GUI/视觉/回归 Review。
- **完成条件：** 数据完整性、高风险独立 Review、全量质量命令和视觉 Gate 通过。
- **M01 Reality Check：** 2026-08-23 **FIT**——V02-T01 的 shell、i18n、worker seam 与 DPI/语言视觉基础已 checkpoint；既有 `ImportService.import_file` 与六种 fidelity Exporter 可直接复用。M01 只接 UI/测试，不改 Project/format metadata/schema/migration/删除契约或新增依赖。
- **M01 当前范围/验收：** `ProjectPage` 六格式导入与 `TranslationPage` 按 `SourceDocument.format` 六格式导出；六格式 fake-endpoint 导入→翻译→保真导出旅程、扩展名/失败不覆盖、异常/关闭、旧 UI/worker/全量质量、中文/英文/DPI GUI smoke 和独立 Review；不提前进入 M02 删除服务/备份或 M03 运行保护。
- **M01 完成证据：** 新增 acceptance **12 passed**（六格式 fake-endpoint 成功旅程与六格式失败目标保留）；指定旧 UI/worker/关闭/自动旅程 **29 passed**；无 system-site-packages 的 `D:\TransRealm-v02-t02-m01-lock-venv-20260823` 按 `requirements.lock` 重建，`pip check` clean，全量 pytest **1356 passed, 5 skipped**；Ruff clean；mypy src **81 source files clean**；原生 Windows Qt 中英文 × 100%/150% Project/Translation Tab 可见/关闭 PASS，代表性截图无重叠/截断；资源/秘密/路径/范围检查 clean；共享解释器的 `packaging==25.0` 漂移及继承系统包诊断 venv 的宿主冲突均未改锁文件或共享环境；首轮 Review 的问题已修正，最终独立 Review **APPROVE**，无 BLOCKER/SHOULD-FIX；M01 checkpoint 为 `93d5e3ccb8e4fd4f4e08ed941c6dfd4d8bd35dbe`。
- **M02 Reality Check：** 2026-08-23 **FIT**——复用 `ProjectService`/`ProjectRepository`、SQLite backup API、既有 FK CASCADE 和 transaction seam；M02 只实现 Project 删除服务/仓库最小能力及备份/故障/完整性测试，不改 schema/migration/Project 数据格式/UI，不触碰外部文件或真实用户数据。无 ADAPT/REPLAN。
- **M02 当前范围/验收：** 备份失败、运行中 Run/有效 processing lease、事务故障均零删除；成功删除只影响目标 Project 及 FK CASCADE 从属行，其他 Project/全局配置保留；备份可打开恢复；新增 M02 测试、旧回归、全量质量和独立 Review 通过。删除 UI/摘要/确认交互与 M03 运行保护留后续。
- **M02 完成证据：** 新增 `tests/test_v02_t02_m02.py` **7 passed**；指定 Project/Profile/Glossary/翻译旧回归 **83 passed**；锁定无 system-site-packages 环境全量 pytest **1363 passed, 5 skipped**；Ruff clean；mypy src **81 source files clean**；pip check clean；M01 原生 Windows Qt 中英文/DPI GUI 证据继续有效，M02 未新增 UI；资源/秘密/外部文件/范围检查 clean；最终独立 Review **APPROVE**，无 BLOCKER/SHOULD-FIX；M02 checkpoint 为 `537512f56523e0ff8efa5e392d07ddb109ad3740`。
- **M03 Reality Check：** 2026-08-23 **FIT**——复用既有 `ProjectPage`/`ServiceWorker`/`WorkerPage`/i18n seam 和 M02 删除服务；M03 只接删除摘要、精确名称确认、异步删除结果/错误反馈与刷新，不改 Application/Domain/Infrastructure、schema/migration 或删除语义。无 ADAPT/REPLAN。
- **M03 当前范围/验收：** Project 页显示从属摘要，输入精确 Project 名后确认并异步删除；备份/运行保护/事务失败错误可操作，成功后刷新 Project 状态；窗口关闭/worker 收敛、中文/英文/100%/150% GUI、旧回归、全量质量和独立 Review 通过；不提前进入 M04 联合 Gate。
- **M03 完成证据：** 新增 `tests/test_v02_t02_m03.py` **3 passed**；M01/M02/既有 UI/关闭回归 **54 passed**；锁定无 system-site-packages 环境全量 pytest **1366 passed, 5 skipped**；Ruff clean；mypy src **81 source files clean**；pip check clean；原生 Windows Qt Project Tab 英文/中文 × 100%/150% 可见/关闭 PASS，placeholder 已本地化且代表性截图无重叠/截断；资源/秘密/范围检查 clean；独立 Review **APPROVE**，无 BLOCKER/SHOULD-FIX；M03 checkpoint 为 `bf13d0f85a3b5f2c0cff188e71cf4789e35b9638`。
- **M04 Reality Check：** 2026-08-23 **FIT**——M01–M03 已 checkpoint，M04 仅做联合 GUI/视觉/回归/范围 Gate，不新增行为、数据格式、依赖或发布动作。无 ADAPT/REPLAN。
- **M04 当前范围/验收：** 锁定依赖、全量 pytest/Ruff/mypy/pip、M01–M03 回归和新增验收；原生 Windows Settings/Project/Translation 代表性状态中英文 × 100%/150% 可见/关闭，Project 删除控件/placeholder 无截断/重叠；资源/秘密/路径/allowed paths、独立 Review 通过；不构建候选、不签发、不 push/merge/tag/Release。
- **M04 完成证据：** M01–M03 定向验收与指定旧回归 **57 passed**；锁定无 system-site-packages 环境全量 pytest **1366 passed, 5 skipped**；Ruff/mypy/pip check clean；原生 Windows Qt 中英文 × 100%/150% Settings/Project/Translation 代表性状态可见/关闭 PASS，Project 删除控件与 placeholder 代表性截图无重叠/截断；资源/秘密/路径/allowed paths clean；独立只读 Review **APPROVE**，无 BLOCKER/SHOULD-FIX；M04 checkpoint 待创建。

### V02-T03 — Connection/Profile 管理体验

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P1 用户可见；Medium；completed。依赖 V02-T01、V02-T02，已由 `e2560bff53e90f4094dcc97a00c5fc32ae7d7e5b` 满足；M01 checkpoint=`1ecca03e6187f157c9a1051dbcc78abc43869590`，M02 checkpoint=`17b865be808aba935e5118a56eea9338512de84c`。
- **Reality Audit：** REFINE——保留现有领域/安全校验，补齐编辑、分组和可操作反馈，不新建配置系统。
- **目标：** Connection/Profile 新建、编辑、删除、引用保护和重开恢复；普通字段默认简洁，高级 capability/参数折叠显示。
- **非目标：** 不保存原始 API Key、不自动调用真实端点、不增加原生多厂商 API、代理 schema 或模型下载器。
- **硬约束：** 凭据仅 `env:`/`wincred:`；历史 Attempt snapshot 不改；删除 RESTRICT；测试连接只由用户触发，自动矩阵使用 fake server。
- **验收：** endpoint/timeout/retry/model/default params/capability 修改后重开一致；非法值不落库；提示不泄密；中英文和视觉矩阵通过。
- **完成条件：** 配置 CRUD、秘密边界、旧 Profile/Run 兼容、全量质量和 GUI Gate 通过。
- **Reality Check：** 2026-08-23 **FIT**——既有 Connection/Profile service、repository 和 schema 已提供全字段 update、JSON capability/default/context 持久化、凭据 reference 校验与删除保护；Settings 页已有 worker seam、创建/删除/凭据提示，缺编辑表单与高级字段折叠。M01 只补 UI/测试/i18n，不改 Application/Domain/Infrastructure、schema/migration、历史 Attempt snapshot、真实端点或依赖。无 ADAPT/REPLAN。
- **M01 当前范围：** Connection/Profile 编辑与重开回显最小闭环：Connection 的 endpoint/timeout/retry/credential reference，Profile 的 model/connection 与 template/output/context/default params/capability 高级字段；高级字段默认折叠；非法值不落库、凭据只存 `env:`/`wincred:` reference、删除 RESTRICT、测试连接仅用户触发；不提前进入下一 Milestone 的分组/可操作反馈扩展。
- **M01 完成证据（2026-08-23）：** 新增 `tests/test_v02_t03_m01.py` **4 passed**；Connection/Profile 定向旧回归 + 新验收 **157 passed**；锁定环境全量 pytest **1370 passed, 5 skipped**；Ruff clean；mypy src **81 source files no issues**；pip check clean；Windows Qt 隔离数据根目录 English/zh_CN × 100%/150% 及高级展开状态无重叠/截断，关闭收敛 PASS；超预算 context、非法 endpoint 与原始 credential 均不落库/不泄密；未改 service/repository/domain/schema/migration/依赖，未调用真实端点或操作真实用户数据。独立只读 Review 首轮 SHOULD-FIX 已修复（保存前校验 `reserved_output + reserved_prompt <= total` 并补不落库测试），复核 **APPROVE**，无 BLOCKER/SHOULD-FIX/MINOR。
- **M01 checkpoint：** `1ecca03e6187f157c9a1051dbcc78abc43869590`，作者 `BFRKQSB7 <226671264+BFRKQSB7@users.noreply.github.com>`，9 个文件均在 allowed paths，未 push/merge/tag/Release；当前进入 M02。
- **M02 当前范围：** 在 Settings UI 内以 Connections/Profiles 分组重组现有控件，并把成功、校验失败、引用保护删除失败、缺少 credential reference 的既有结果呈现为可定位下一动作的状态反馈；高级 Profile 设置仍默认折叠。只改 Settings UI、必要 i18n、M02 测试和状态/契约 Markdown；不改 service/repository/domain/schema/migration/依赖、删除/校验/凭据语义、历史 Attempt snapshot、真实端点或真实用户数据。
- **M02 Reality Check（2026-08-23）：** **FIT**——现有 service/worker seam 已提供结果与错误语义，`SettingsPage` 仅缺结构化分组和集中反馈展示；可在 UI 层最小重组，不需要新抽象、迁移、依赖或公共契约变更。无 ADAPT/REPLAN。
- **M02 完成证据（2026-08-23）：** Settings UI 已以 Connections/Profiles 分组重组现有控件，集中 status banner 呈现新增/编辑/删除成功、校验失败、引用保护和缺 credential reference 的下一动作；删除成功分别显示 Connection/Profile deleted，Profile advanced 仍默认折叠。新增 `tests/test_v02_t03_m02.py` **1 passed**；指定旧回归 + M01/M02/UI/i18n 回归 **164 passed**；锁定环境全量 pytest **1371 passed, 5 skipped**；Ruff/mypy/pip check/git diff check clean；Windows Qt 隔离临时 DB English/zh_CN × 100%/150% 与高级展开截图无重叠/截断、进程关闭 PASS；未改 i18n/service/repository/domain/schema/migration/依赖，未调用真实端点或操作真实用户数据。独立 Review 首轮 SHOULD-FIX（删除成功未更新 status banner）已修复并复核 **APPROVE**，无 BLOCKER/SHOULD-FIX/MINOR。M02 checkpoint=`17b865be808aba935e5118a56eea9338512de84c`。
- **Task 完成证据：** M01/M02 已分别 checkpoint，Connection/Profile CRUD、重开一致性、引用保护/秘密边界、普通/高级字段层级、可操作反馈、中英文/DPI GUI、旧 Profile/Run 兼容和全量质量门禁均通过；V02-T03 Task 标记 `completed`，对外发布动作仍不在授权范围。

### V02-T04 — Translation/Workbench 体验

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P1 核心体验；Medium；in_progress（M04 当前，M01–M03 已完成）。依赖 V02-T02、V02-T03；V02-T03 checkpoint=`17b865be808aba935e5118a56eea9338512de84c`。
- **Reality Audit：** REFINE——复用既有 Run/Attempt/Revision 服务，重组交互；不复制 orchestrator/状态机。
- **目标：** Auto 最短旅程；Workbench 提供 Segment 状态过滤、源文/译文双栏、Revision 历史/current 切换、锁定、失败详情和受控重试。
- **非目标：** 不做多候选、QC Engine、节点式 Workflow、RAG/TM 或新重试语义。
- **硬约束：** 人工/locked current 不被自动覆盖；运行中切换继续拒绝；Revision 不覆盖；重试沿用 retryable/fencing；UI 不查库。
- **异常/视觉验收：** 大量 Segment 不阻塞；取消/关闭/断网/timeout/retry/重启可解释；未保存草稿不静默丢失；各状态和双栏层级在中英文/DPI 下清晰。
- **Milestone：** M01 Auto 总览；M02 Workbench 列表/筛选；M03 Revision/history/lock/retry；M04 恢复/长文本/视觉 Gate。
- **完成条件：** 核心旅程、旧状态机回归、全量质量和独立视觉/行为 Review 通过。
- **M01 Reality Check（2026-08-23）：** **FIT**——既有 TranslationPage/TranslationWorker、ProjectService/TranslationRunService 已提供 Auto 的 project/document/active Profile/进度/取消/导出 seam；M01 只补 Translation UI/测试/必要 i18n 的 Auto 总览层级与反馈，不改 service/domain/schema/migration、Run/Attempt/Revision/重试/锁定契约、真实端点或依赖。无 ADAPT/REPLAN。
- **M01 当前范围/验收：** Auto 模式清晰呈现 active Profile/配置引导、文档、Translate/Cancel/Export、进度和成功/失败/取消状态；Workbench 列表/筛选、Revision/history/lock/retry 和恢复/长文本留给后续 M02–M04；大量 Segment 不阻塞，关闭/取消/缺配置可恢复，中英文/DPI、旧状态机回归、全量质量、GUI 与独立 Review 必须通过。
- **M01 完成证据：** 新增 `tests/test_v02_t04_m01.py` **2 passed**；T04 指定旧状态机/GUI 回归 **114 passed**；全量 pytest **1373 passed, 5 skipped**；Ruff clean；mypy src **81 source files no issues**；pip check clean；Windows Qt 隔离 English/zh_CN × 100%/150% Translation 截图与关闭 smoke PASS，无截断/重叠；未改 service/repository/domain/schema/migration/依赖，未调用真实端点或操作真实用户数据；独立只读 Review 首轮要求修正两处过时状态文档事实，已同步并复核 **APPROVE**，无 BLOCKER/SHOULD-FIX/NICE-TO-HAVE。
- **M01 checkpoint：** `6680516afbae2b716b25567b588721b529d0a4b9`（`feat(ui): add auto translation overview`），作者 `BFRKQSB7 <226671264+BFRKQSB7@users.noreply.github.com>`；9 个文件均在 M01 allowed paths，未 push/merge/tag/Release。
- **M02 Reality Check（2026-08-23）：** **FIT**——M01 已将 Auto 主旅程与 Workbench 容器边界 checkpoint；现有 `TranslationRunService.list_segment_progress` 已提供按文档读取 Segment/Attempt/Revision 摘要的只读 seam，`TranslationPage` 已有 Workbench `QListWidget` 和内存中的 `SegmentProgress` 列表。M02 只补 Workbench 列表的状态筛选与源文/当前译文可读层级及验收证据，不改 service/domain/schema/migration、Revision/history/lock/retry 语义、真实端点或依赖。无 ADAPT/REPLAN。
- **M02 当前范围/验收：** Workbench 显示 Segment 状态过滤、源文与当前译文摘要，筛选前后选中项/现有编辑行为不静默丢失；Auto 模式不受影响；Revision/history/lock/retry 留给 M03；大量 Segment 不阻塞，中英文/DPI、旧状态机回归、全量质量、GUI 与独立 Review 必须通过。
- **M02 完成证据（2026-08-24）：** 新增 `tests/test_v02_t04_m02.py` **2 passed**；指定旧 Workbench/状态机 + M01/M02 回归 **88 passed**；锁定环境全量 pytest **1375 passed, 5 skipped**；Ruff clean；mypy src **81 source files no issues**；pip check clean；Windows Qt 隔离 Workbench English/zh_CN × 100%/150% 顶部与滚动到底部截图、筛选/源文/当前译文可达、关闭 PASS，无重叠/截断；未改 service/repository/domain/schema/migration/依赖，未调用真实端点或操作真实用户数据；独立只读 Review **APPROVE**，无 BLOCKER/SHOULD-FIX。
- **M02 checkpoint：** `87c6899a4c627d8ade8d2e20b986a0d15e43b22c`（`feat(ui): add workbench segment filtering`），作者 `BFRKQSB7 <226671264+BFRKQSB7@users.noreply.github.com>`；9 个文件均在 M02 allowed paths，未 push/merge/tag/Release。
- **M03 Reality Check（2026-08-24）：** **FIT + ADAPT**——既有 `TranslationRevisionRepository.list_by_segment` 保留不可变历史，`TranslationRunService` 已提供 `get_revision`/`set_current_revision`/`lock_current_revision`/`unlock_current_revision`/`retry_failed`，`TranslationPage` 已有选中 Segment 的编辑与锁定接线。范围内 ADAPT 仅新增 `TranslationRunService.list_revisions_for_segment` 只读 seam，并在 UI 接入历史/current 切换和受控 retry；不改 schema/migration、Revision/lock/retry 语义、真实端点或依赖。无 REPLAN/待决策。
- **M03 当前范围/验收：** Workbench 显示选中 Segment 的 Revision history/current，切换 current 经 ServiceWorker 且保留不可变 Revision；复用现有 lock/unlock，失败 Segment 只经既有 retryable 规则 requeue；Auto/运行中切换/取消/关闭/状态机不变；筛选、草稿、源文/当前译文不静默丢失；中英文/DPI、旧回归、全量质量、GUI 与独立 Review 必须通过。M04 再负责恢复/长文本/最终视觉 Gate。
- **M03 完成证据：** 新增 `TranslationRunService.list_revisions_for_segment` 只读 seam、TranslationPage history/current/受控 retry UI 与必要 en/zh_CN `.ts/.qm`；新增 `tests/test_v02_t04_m03.py` **2 passed**；指定旧 Workbench/状态机 + M01/M02/M03 回归 **95 passed**；全量 pytest **1377 passed、5 skipped**；Ruff clean；mypy src **81 source files no issues**；pip check clean；Windows Qt 隔离 en/zh_CN × 100%/150% GUI、历史列表/切换按钮/滚动/关闭 PASS，代表性截图无重叠/截断；未改 schema/migration/其他 service/domain/repository/依赖，未调用真实端点或操作真实用户数据；独立 Review 首轮文档事实修正后复审 **APPROVE**，无 BLOCKER/SHOULD-FIX/MINOR；M03 checkpoint=`7c54efeaf73019e97691c6d714fa680c28666ef1`。
- **M03 checkpoint：** `7c54efeaf73019e97691c6d714fa680c28666ef1`（`feat(ui): add revision history controls`），作者 `BFRKQSB7 <226671264+BFRKQSB7@users.noreply.github.com>`；10 个文件均在 M03 allowed paths，未 push/merge/tag/Release。
- **M04 Reality Check（2026-08-24）：** **FIT**——M01–M03 checkpoint/依赖、既有 `TranslationService`/`TranslationWorker`/lease-recovery/fake-adapter seam、P1-T05 翻译/恢复/长文本 Gate 与 T04 GUI 状态均齐备；M04 仅做验证型 Gate，不新增产品行为、schema/migration、公开契约或依赖，无 ADAPT/REPLAN。
- **M04 当前范围/验收：** 固定长文本 fake-endpoint 翻译/重开/恢复/导出或等价 Gate 证据；current/locked/retry/取消/关闭状态可解释且不覆盖已完成 Revision；Auto/Workbench 状态机、筛选/草稿/源文/当前译文不回退；Settings/Project/Translation 代表性空/错/禁用/Workbench/history 状态在 en/zh_CN × 100%/150% 可见、滚动和关闭无截断/重叠；指定旧回归、全量质量、适用安全/异常/回滚检查和独立 Review。allowed paths 仅为 `tests/test_v02_t04_m04.py` 与必要状态/契约 Markdown；若发现范围内可复现 UI/i18n 缺陷，才使用既有 T04 UI/i18n allowed paths 做最小修复；不构建候选、不签发、不 push/merge/tag/Release。
- **M04 完成证据：** 新增 `tests/test_v02_t04_m04.py` **2 passed**；指定 T04 + 既有恢复/长文本 matrix **178 passed**；全量 pytest **1379 passed、5 skipped**；Ruff/mypy/pip check clean；Settings/Project/Translation × en/zh_CN × 100%/150% 顶部/底部共 24 张 GUI 截图，Workbench/history/error/disabled 代表状态、滚动、关闭与线程停机 PASS，抽查无截断/重叠；allowed paths、秘密、迁移未触碰、回滚 ref 与 `git diff --check` clean；未构建候选、未调用真实端点或操作真实用户数据；独立 Review **APPROVE**，无 BLOCKER/SHOULD-FIX/MINOR；M04 checkpoint 待创建。

### V02-T05 — v0.2 Release Candidate Gate

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P0 Release-blocking；High；blocked（2026-08-28 REPLAN：新增 M02，等待独立代码/测试授权；内部候选 Gate 历史完成保留，人工 smoke 未通过、AV 未执行，当前候选不可正式发布）。依赖 V02-T01 至 T04；M02 为 proposed。
- **Reality Audit：** REFINE——复用 P1-T05 并增加视觉/i18n/六格式 GUI/删除恢复门禁。
- **目标：** 形成可定位、可恢复、可人工签核的 Windows 11 v0.2 候选。
- **硬约束：** 从 clean commit 构建，manifest `git_dirty=false` 且 commit==HEAD；中英文资源、Qt 插件和 migration 全收集；自动旅程仅 fake endpoint；未经授权不 push/tag/Release。
- **Gate：** 全量 pytest/Ruff/mypy、candidate hygiene、六格式冻结 GUI、删除备份恢复、Connection/Profile、Auto/Workbench、中英文+DPI 截图、旧 v0.1 数据升级、zip/manifest/hash、干净 Windows 启动/关闭/清理、独立 Review。
- **完成条件：** release-blocking 项全部布尔通过、证据归档且无 P0/P1；AV、真实端点、正式发布缺外部环境时保持未通过或提交用户明确裁决。
- **历史内部候选完成证据（不覆盖新增 M02/人工签收）：** 首轮 Review 的 clean-source、manifest ZIP 选择和候选文档漂移问题已在允许范围内修复；checkpoint=`5744b9db53028c0bcbed48c37fac9fc6d3fe2d1e`，候选 `0.2.0` manifest `git_dirty=false` 且 commit==HEAD，12 migrations、双语资源、Qt 插件、EXE/ZIP hash/size 与文档一致；候选/文档/版本专项 `10 passed`，指定 V1.0 T05 M01–M05 + v0.2 M01 回归 `43 passed`，最终全量 pytest `1385 passed, 1 skipped`，Ruff/mypy/pip check/candidate hygiene/manifest/hash 均通过；Windows 冻结启动、迁移、关闭、外置数据保护与删除程序目录 smoke 通过。未覆盖项如实保留：symlink 权限 skip、AV 扫描、冻结应用完整人工旅程、真实端点和正式发布。

#### V02-T05-M01 — 候选版本身份与版本基线

- **恢复范围：** 延续 2026-08-24 交接中尚未开始的 M01，不在环境整理轮执行。开发 Agent 先核对 `pyproject.toml`、`src/transrealm/__init__.py` 与候选构建读取的版本来源，按既定 v0.2.0 目标消除版本身份不一致；不改变产品行为、数据库、依赖锁或构建输出契约。
- **允许路径：** `pyproject.toml` 的版本元数据、`src/transrealm/__init__.py` 的版本元数据、`src/transrealm/ui/main_window.py` 中仅 `APP_VERSION` 到 `transrealm.__version__` 的版本来源接线、直接相关的版本验收测试，以及本 Milestone 必需的状态/版本文档。此前用户批准的目录治理 Markdown 与 `.gitignore` 改动作为受保护的既有基线逐项核对，不得 reset、删除或覆盖。
- **门禁与边界：** 版本来源/目标一致性、相关旧回归、全量 pytest、Ruff、mypy、pip check 和独立 Review；环境整理的通过结果不代替版本修改后的验证。M01 不构建候选、不启动冻结 EXE、不做 AV/真实端点/发布，不把后续 T05 Gate 标记通过。
- **交接：** 完成当前单次 M01 后停止并更新状态；本地 checkpoint 是否允许以当次状态授权为准，不恢复连续无人开发。后续候选构建仍须 clean commit 与明确构建授权。

#### V02-T05-M02 — 候选签收前：首次配置、闭环与错误脱敏

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5A / v0.2.0；P0 Release-blocking（首次翻译/完整人工 smoke 未完成），错误信息暴露为 P1 安全；High；`verification`（源码实现与自动化门禁完成；目标 GUI 矩阵、候选、AV 与签发仍未授权/未验证）。
- **decision_id / decision_result / Reality Audit：** `DEC-V02-T05-M02-SIGNOFF-REPAIR` / **REPLAN** / REFINE。内部 Gate 的通过证据不覆盖首次使用失败；新增一个受限修复 Milestone，不扩大 release 或重开整个 UI 架构。决策理由与不变契约见 `08_Architecture_Review.md` §35；即时指针/授权只在 `DEVELOPMENT_STATE.md`。
- **输入与事实依据：** 本次只使用 `DEVELOPMENT_STATE.md`、本文件、`08_Architecture_Review.md`、`09_Unattended_Development_Governance.md`、`RELEASE_CHECKLIST.md`、`.local/verification/manual-signoff/SIGNOFF.md`、`AGENTS.md` 和本轮用户事实。人工 create/import 仅可能成功、translate 未完成；原记录的 GUI PASS 不构成完整旅程通过。未查代码根因，不能预称“配置流程已修复”。
- **base_commit / rollback_ref：** 均固定为 `5744b9db53028c0bcbed48c37fac9fc6d3fe2d1e`；内部候选 Gate 是历史依赖，不是 M02 验收结果。保持用户当前 `master`，不创建/切换/删除分支。
- **目标：** 首次用户通过应用可见入口和简短说明，理解并完成 Connection、Model Profile 与 Project active Profile 配置；能填写 llama.cpp 的 OpenAI-compatible API 所需连接与模型信息。本轮后续验证仅以本地 fake HTTP endpoint 模拟该兼容接口，不启动真实 llama.cpp 模型。用合成数据从空状态完成 create → import → translate → export → close/reopen；保留既有六格式和 Auto/Workbench 能力；错误可理解、可恢复且脱敏。
- **非目标 / 变更预算：** 不做通用向导框架、全局导航/主题重写、配置系统重建、模型下载/管理或自动探测；不涉及 v0.3/`DEC-V03-PROJECT-STORAGE`、ProjectSession/一项目一库/容器 GUI；schema/migration、公共契约、依赖新增/升级、Prompt/输出契约、重试策略变更预算均为零。无真实模型/端点/用户数据、外部目录整理、签发或任何远程动作。若最小修复需要上述变化，停止冲突部分另作明确决策，不借本 M02 扩权。
- **前置依赖：** 复用 T01 的 shell/i18n、T02 的六格式/数据保护、T03 的 CRUD/引用保护、T04 的 Auto/Workbench/恢复，以及 T05-M01 和内部候选 Gate；旧完成记录只作可定位基线。开始前获独立代码/测试授权，核对实际 seam、指定旧测试与锁定环境，记录运行命令、原始结果及全部受保护改动；无法复现的依赖先标缺口，不降门禁。环境修复、额外文件或新依赖不得顺带执行。
- **数据与网络前置：** 合成源文件、数据库、导出、日志、缓存、用户配置隔离、临时文件全部在项目内；fake server 仅绑定 loopback，使用生产 transport 与既有兼容协议，固定成功/故障响应，记录脱敏请求计数。不能只用绕过 HTTP/GUI 的 service mock 证明完整旅程。不得读取真实用户目录数据库、`x.db`、真实源文件或凭据；若既有测试/GUI 无法隔离输出位置，停止该验证并报告，不默许写到项目外。

**本轮源码阶段结果（2026-08-28，Asia/Shanghai；不等同候选签收）**

- 实施范围保持在本 M02 allowed paths：首次配置提示明确 Connection / Model Profile / Project active Profile 依赖；用户自行启动命令行 `llama-server`，应用仅填写/保存 API base URL；补充缺配置导航、重开项目/文档恢复、完成状态稳定显示和 UI 错误脱敏。
- 设计参考已保存至 `D:/TransRealm/.local/verification/v02-t05-m02/20260828-145021/design-reference.md`；命令原始结果、合成旅程、安全范围、GUI 矩阵和 Review 见同目录 `commands.log`、`journey.md`、`security-scope.md`、`gui-matrix.md`、`review.md`。
- 最终自动化结果：M02 `6 passed`；指定旧回归 `25 passed`；全量 pytest `1391 passed, 1 skipped`；Ruff、mypy（151 source files）、pip check、`git diff --check` 均通过；Qt en/zh_CN `.qm` 各生成 114 条完成翻译。
- 源码 Review 无 P0/P1 blocker；Windows GUI 工具在目标窗口选择前初始化失败，English/zh_CN × `1280x720 @100%`、`1920x1080 @150%` 的实际交互/截图/DPR/视觉 Review 均保持未验证。真实 llama-server、冻结候选、AV 和外部签收不继承旧证据，仍未执行。
- 当前状态仅推进为 `verification`；不标记 `completed`，不推进 Task/Milestone，不暂存或提交。下一步需独立 checkpoint/候选构建授权，再对同一候选执行人工 GUI/AV 签收。

**GUI 设计方法：优先参考成熟设计（用户补充要求）**

- 后续先选取 1–2 个成熟应用公开的连接管理/模型配置/首次使用流程作为参考，复用可识别的分组、字段说明、依赖提示、主操作与错误反馈模式，只做与现有三页、数据模型及双语/DPI 约束相容的最小调整；不凭个人偏好重新设计整套交互，不复制品牌资产或引入新框架。
- 本轮已在授权范围内选定并记录官方 `llama.cpp` `llama-server` 文档与 Open WebUI OpenAI-compatible 文档；来源/访问日期、借鉴点、适配差异、最短流程与页面草案见 `D:/TransRealm/.local/verification/v02-t05-m02/20260828-145021/design-reference.md`。参考设计不能替代用户可理解性和实际 GUI 验收，也不形成新的架构/数据契约。

**交互语义与最短路径（交付验收目标，非已实现声明）**

1. Settings 显示“连接 / Connection”：说明“服务在哪里、怎样连接”，承载 API base URL、超时/重试和可选的 `env:`/`wincred:` 凭据引用；明确 llama.cpp 使用现有 OpenAI-compatible 方式，base URL 与 API 路径如何填写、模型标识由何处获得。示例只能是受控 loopback fake endpoint/合成模型名，确切 URL 拼接须由后续实际 transport 测试核对，不新增猜测协议。
2. 显示“模型配置 / Model Profile”，避免孤立的“配置”：说明“用哪个模型、按什么参数/模板翻译”；必须选择已有 Connection。一个 Connection 可被多个 Profile 使用；保存连接不等于选好模型，保存 Profile 不等于已给当前 Project 启用。高级字段仍折叠，普通路径不要求理解 capability/JSON。
3. 最短可见路径：Project 创建项目并导入 → 缺配置提示直接到 Settings 的目标区域 → 新建 Connection → 新建并关联 Model Profile → 回到该 Project 选择 active Profile → Translation 翻译 → 导出 → 关闭重开。已有配置时复用，不强迫重复创建；无 Connection/无 Profile/无 active Profile 分别说明缺哪一步和下一动作，不允许绕过依赖的开始操作。
4. Project 与 Translation 显示当前 active Profile 及关联 Connection 的可理解摘要，返回配置后刷新可见状态；不显示秘密/系统路径。连接测试若沿用现有能力，只能由用户显式触发；保存、切页、启动不得隐式发送探测请求。配置存在/连接测试成功均不等同于完整翻译成功。
5. 重复连接名称等错误说明对象/原因/下一动作（例如换名或编辑已有连接），不能直接展示异常字符串、SQL、数据库绝对路径或用户名；未知错误给安全通用说明和恢复动作，不吞错、不报成功。只改变呈现/就近引导，不改变唯一性、RESTRICT、凭据引用或历史快照语义。

**allowed_paths（未来独立授权后的上限；本轮仅三个计划文件）**

- UI：`src/transrealm/ui/settings_page.py`、`src/transrealm/ui/project_page.py`、`src/transrealm/ui/translation_page.py`，仅本旅程的标签、说明、入口、依赖/状态呈现与错误反馈；`src/transrealm/ui/main_window.py` 仅页面跳转/上下文接线；`src/transrealm/ui/page_base.py`、`src/transrealm/ui/worker.py` 仅既有错误传递/呈现边界的最小脱敏。不得改变线程、状态机、服务调用契约或版本来源；不为此次修复拆分所有页面。
- i18n：`src/transrealm/ui/i18n/**`，仅本次新改文案及对应 en/zh_CN `.ts/.qm`，资源编译需包含于新授权，不能顺带修改无关翻译。
- 测试：优先扩展 `tests/test_v02_t03_m01.py`、`tests/test_v02_t03_m02.py`、`tests/test_v02_t04_m01.py` 和 `tests/test_v02_t02_m01.py`；跨页面新旅程确无自然归属时才增 `tests/test_v02_t05_m02.py`，复用已有 pytest-qt/fake server fixture，不建平行测试框架。不放宽旧断言或隐藏失败。
- 必要文档：`docs/user-guide.md`（双语最短步骤/字段语义/失败恢复）、`docs/known-issues.md`（如实更新未覆盖/签收阻塞）、`DEVELOPMENT_STATE.md`、`07_Developer_Task_List.md`；仅决策发生变化时改 `08_Architecture_Review.md`。所有路径相对于 `D:/TransRealm/`，已有 dirty 内容只可在核对归属后增量编辑，不覆盖。
- 验证输出：`D:/TransRealm/.local/verification/v02-t05-m02/<run-id>/`、`D:/TransRealm/.local/tmp/`、`D:/TransRealm/.local/cache/` 和既有项目内质量缓存；只可用于本 M02。后续候选人工/AV 证据路径见下表，但不因列出就授权执行。
- **forbidden_paths：** 上述之外的源码（含 Application/Domain/Infrastructure/repositories/migrations）、依赖锁/项目配置、构建脚本、活动 `dist/`/`build/`、现有签收原件、真实数据、项目外目录。若错误分类无法在既有 UI/worker 边界安全完成，先记录最小 service seam 需求和兼容性影响，另行决策并授权；不能直接放大到 `src/**`。

**验收矩阵（全部为待执行；源码验证与冻结候选签收分别记录）**

| 类别 | 必须观察的结果、数据状态与恢复要求 |
|---|---|
| 首次配置/自动 GUI 测试 | 从空合成库经可见控件完成 Connection → Profile → active Profile；缺项分别提示/禁用，返回后正确刷新；已有配置可复用，编辑重开保持值，切换语言不改数据。不得用直接写库/调用私有页面入口替代入口可发现性测试。至少新增对应的引导与脱敏回归用例。 |
| 完整闭环 | 使用真实应用服务、worker、生产 HTTP transport 与 loopback fake server，从 GUI create/import 到 translate/export，再实际关闭/重开；验证输出为预期译文、不是源文回退，Project/文档/Connection/Profile/active 关联、Revision/current/lock 保留，无重复翻译已完成段或残留 processing。自动复跑 TXT/JSON/SRT/ASS/SSA/VTT 六格式成功与保真/失败保护，人工至少用固定 TXT 合成样本完成全旅程。 |
| 异常/数据恢复 | 重复 Connection/Profile 名称、非法 endpoint/model/参数、缺 Connection/Profile/active/凭据引用、引用保护删除；无效输入不落库、不误切 active、不改既有记录。fake server 注入 connection refused、timeout、401、429/5xx、截断/无效响应，保持既有 retryable 规则；错误可恢复，取消/关闭/重开不挂死，不覆盖 completed/locked Revision；不可写导出和未完成译文导出均不覆盖目标，修正后可重试。 |
| 安全 | 用合成用户名、绝对 DB 路径、原始 SQL、假 token 的异常注入，检查状态横幅/对话框/tooltip/可复制详情及新日志/截图无敏感回显；未知异常有安全兜底。不得复制原始 error.png 到公开文档。保留凭据引用、UI 不直接查库、worker/SQLite 线程边界和输出目录限制；检查 fake server 仅 loopback 且无真实端点调用。 |
| 双语 GUI/视觉 | Windows 11 x64 下 English/zh_CN × `1280x720 @100%` / `1920x1080 @150%` 四组合；覆盖主壳、Settings、Project、Auto、Workbench 的适用空/缺配置、运行/禁用、错误、成功及关闭重开状态。每格有实际交互与截图，检查截断/重叠、滚动可达、Tab/焦点、标签语义、禁用原因与恢复动作。无适用场景的格须给理由并由独立 Review 确认；不得用代表图宣称全组合通过。记录屏幕/窗口像素与有效 DPR，离屏截图只能补充；无目标显示环境记为未验证。既有 `2560x1440 @150%` 不能替代。 |
| 人工签收 | 新用户/原测试人员仅按修订后的应用提示与用户文档操作，无开发者临时口头指路，能说明 Connection/Profile/active 的区别并完成配置和完整闭环；逐步记录实际结果、失败/未覆盖、环境、时间、执行者及证据。无真实 llama.cpp 调用，不声称验证了真实模型质量/兼容性。冻结候选须重新跑该项和目标视觉矩阵，不能套用源码截图。 |
| 质量/旧回归/Review | 受影响旧测试及全量 pytest、Ruff、mypy、pip check、范围/秘密/输出路径检查通过；独立行为、安全与视觉 Review 无未解决 P0/P1。测试未跑/skip 不等于通过；每项 skip 必须说明适用性，当前核心闭环/脱敏/GUI 缺证据不得豁免。旧“1385 passed”只作历史，不预填新结果。 |
| 独立外部 AV | 不属于代码修复结果；用户在具备 AV 能力的环境对最终同一候选 ZIP 和解压 onedir 扫描，保存引擎/病毒库版本、时间、候选 hash、扫描范围、原始结果与执行者。AV 不可用保持 BLOCKED，不能用 hash、安全单测、fake endpoint 或启动成功替代，也不授权更改本机防护。 |

- **兼容性基线/命令：** 后续先核对文档所列测试是否存在及 nodeid；旧回归至少包括 `tests/test_v02_t03_m01.py`、`tests/test_v02_t03_m02.py`、`tests/test_v02_t02_m01.py`、`tests/test_v02_t04_m01.py` 至 `test_v02_t04_m04.py`、`tests/test_p0_t08_m05.py`、`tests/test_p1_t03_m04.py`、`tests/test_p1_t03_m05.py`、`tests/test_p1_t04_m04.py`、`tests/test_p1_t04_m05.py`、`tests/test_model_profile.py`、`tests/test_p0_t03_m03.py` 与 `tests/test_p1_t05_m02.py`/`test_p1_t05_m03.py`。按实际存在的路径记录定向 `python -m pytest -q <明确文件/nodeid列表>` 命令及结果；缺失项不悄悄跳过，先报告并核对等价旧覆盖。全量门禁用 `D:/TransRealm/.venv/Scripts/python.exe -m pytest -q`、同解释器 `-m ruff check src tests`、`-m mypy src tests`、`-m pip check`，加 `git diff --check`；全量不能替代上述受影响旧回归。运行前隔离缓存/临时/用户配置输出，不改机器设置。
- **冻结候选依赖与停止点：** M02 源码验证后，另获 checkpoint 和构建授权，才能将已验证的限定变更形成 clean commit，并用既有构建流程重新进入 `V02-T05-CANDIDATE-GATE`。构建前可逆保留旧候选及其 manifest/hash 到项目内归档（仅后续获准时）；新 manifest `git_dirty=false`、目标 commit 与构建源 HEAD 一致，重跑候选专项/版本/插件/资源/六格式/迁移恢复/安全等适用 Gate。不得用旧 ZIP 验证新 UI，旧 hash/AV 结果不得继承；构建或旧回归失败立即停止签收推进。候选构建不属于 M02 代码授权自动附带的动作。

**证据文件（本轮只规划，不创建、不覆盖原始签收记录）**

| 位置 | 必须内容 |
|---|---|
| `D:/TransRealm/.local/verification/v02-t05-m02/<run-id>/baseline.md` | HEAD/base/固定 rollback、受保护 dirty 清单、允许路径、环境/锁版本、旧测试 nodeid、fixture 与输出隔离路径。 |
| 同目录 `design-reference.md` | 本轮已实际记录的成熟设计来源、借鉴点/差异、最短流程与范围内页面草案。 |
| 同目录 `commands.log`、`results.md`、`journey.json` | 实际命令/退出码/原始测试结果、缺口；合成输入与预期导出、请求计数、各步前后状态、关闭重开证据；记录源码身份，不伪称候选结果。 |
| 同目录 `negative-security.md`、`gui-matrix.md`、`screenshots/<language>/<display>/<page>-<state>-<step>.png` | 故障注入/恢复/脱敏结果；逐格证据索引、系统/显示/DPR/窗口尺寸、截图对应源码身份；成功与失败图都先检查敏感信息。 |
| 同目录 `review.md`、`recovery.md` | 独立行为/安全/视觉 Review 的发现与复核；失败恢复步骤、合成数据/备份核对、未覆盖项及下一授权，不预写 APPROVE。 |
| `D:/TransRealm/.local/verification/manual-signoff/v02-t05-m02/<candidate-id>/RESULT.md`、`gui-matrix.md`、`screenshots/`、`candidate-identity.json` | 后续重建候选的实际 commit/ZIP/EXE hash/manifest、逐步人工与目标双语显示矩阵、签收人/时间/失败项。candidate-id 必须绑定实际构建身份；原 `SIGNOFF.md` 与 `error.png` 只保留内部原件。 |
| `D:/TransRealm/.local/verification/manual-signoff/av/<candidate-id>/RESULT.md`、`scan.log` | 后续由用户提供的独立 AV 证据；明确候选身份和原始结果，未执行不生成 PASS。 |

- **解除条件与下一状态：** 新代码/测试授权 + 现场/环境准入后才进入 M02 实施；源码/GUI/异常安全/旧回归/独立 Review 完成后只记“源码验证完成，冻结候选签收待完成”，停止请求 checkpoint/构建授权。重建候选 Gate 及同候选人工闭环/视觉证据通过，才可将本修复交付记 completed 并推进外部 AV/最终签收；缺 AV 不改写为代码失败，也不放行 T05。真实端点仍是未执行且范围外的独立待裁决项，不能作为本地修复阻塞或已通过证据。
- **失败恢复/升级：** 先保留失败证据与合成数据，暂停本次进程；不改写原签收证言，不删除日志来获得通过。只在明确授权后撤销本 M02 可识别改动，或在项目内隔离复现固定 checkpoint；保留原候选、数据库/备份和全部既有 dirty，不做整树 reset/restore/clean。若发现业务核心/公共契约/新依赖/路径隔离超界需求，停冲突部分 REPLAN，附最小额外路径和影响，未获新决策不实现。
- **最终停止点：** 本轮计划文档修改后立即停止；后续不得自动沿用旧连续开发或本地提交权限。AV/人工签收/真实端点适用性/正式签发各自未决即如实记录；即使全部适用门禁通过，也只交用户做签发决策，绝不自动发布、push、merge、tag、Release、创建远程资源或进入 v0.3。

### V03-T00 — `DEC-V03-PROJECT-STORAGE` 决策门禁

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0 planning；P0 Architecture；High；completed（2026-09-07）。本节点只完成提前决策与文档，实施仍依赖 V02-T05 完成和新的 v0.3 开发授权。
- **问题：** GUI 全局 SQLite 可含多个 Project，而开放目录/`.aiproject` 要求数据库内恰有一个 Project；必须统一 ProjectSession、应用配置、受管目录、导入语义和旧库迁移。
- **不可变约束：** 不丢数据；旧库先备份并保留只读恢复点；六格式载体、Revision/current/lock、Attempt、Profile/Connection 和秘密边界不退化；不原地编辑 `.aiproject`；不静默删除外部文件。
- **唯一裁决：** `APPROVE_ONE_PROJECT_ONE_WORKSPACE`。一次一个活动 ProjectSession + 一 Project 一 SQLite 工作区；应用级语言/最近 Project 独立保存；`.aiproject` 导入可写工作区；旧库按关联闭包拆分并逐库验证。否决“全局库 + 克隆/ID 重映射”（双身份和覆盖/删除/恢复语义持续冲突）与“全局索引库 + Project 库”（新增跨库一致性和恢复故障域）。完整契约见 `03` §10.2、`04` §7.1、`08` §17。
- **兼容性/安全/迁移：** 复用现有以 `db_path` 为入口的 Application Service 和容器/归档/SQLite Backup API；Profile/Connection 非敏感配置保留在 Project 库，secret 只保留引用。旧库先只读盘点和一致性备份，在 staging 逐 Project 拆分；全部目标通过前不切换入口、不删除旧库。UNC/网络盘不作为活动写工作区。
- **完成证据与停止点：** 已输出唯一推荐、否决理由、portable/data-dir、Application/UI seam、迁移/回滚、验收矩阵和 V03-T01～T06。当前恢复点仍为 `V02-T05-M02`，不得因 T00 completed 自动开工；V02-T05 完成并获得代码/测试授权后才进入 `V03-T01-M01`。

### V03-T01 — 数据根与应用配置分离

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0；High；proposed。`base_commit` 待 V02-T05 正式签收 checkpoint 固定；代码未授权。
- **目标/用户价值：** 实现 `--data-dir` → Portable `data/` → 本机自定义指针 → `%LOCALAPPDATA%/TransRealm` 的唯一解析；把语言、最近/上次 Project、受管根和日志级别写入 data-root 的应用配置。程序目录不可写时给可操作选择，不把业务数据静默写到未知位置。
- **范围上限：** 启动/配置基础设施、最小 Settings/启动错误 UI、对应测试、i18n、用户/安全文档和状态；不创建 ProjectSession、不迁移旧库、不接容器 GUI、不构建候选。优先复用 Qt/stdlib，不新增依赖。
- **验收/回滚：** 覆盖四级优先级、Windows Unicode/长路径、不可写/非目录/磁盘满、配置原子保存、旧 QSettings 语言兼容读取、Portable 移动；失败不改旧设置。回滚删除新建的空配置载体即可，旧值保留。完成后停在 `V03-T02-M01` 前。

### V03-T02 — 单活动 `ProjectSession` 生命周期

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0；High；proposed；依赖 V03-T01。
- **目标/用户价值：** 用一个 Session 统一当前工作区、数据库路径、单 Project 身份、写会话锁和打开/关闭/切换；现有 Service 继续消费 `db_path`，UI 不直接访问数据库。
- **范围上限：** Application session seam、MainWindow/page/worker 的当前 Session 接线、会话锁、行为/线程/GUI 测试及必要文档；不做旧库拆分和 `.aiproject` GUI。
- **验收/回滚：** 运行中切换要求完成或取消；worker/lease/connection 有界收敛；非法/损坏目标不替换当前 Session；双实例写入被拒绝；切换后无前一 Project 的文档/Profile/Revision/草稿泄漏。保留旧固定 `db_path` 兼容 seam 直到本 Task 验收，失败可回退路由。完成后停在 `V03-T03-M01` 前。

### V03-T03 — 旧全局数据库拆分迁移

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0 Data Migration；Critical；proposed；依赖 V03-T01～T02。
- **目标/用户价值：** 将旧 `~/.transrealm/project.sqlite` 安全拆成一 Project 一工作区，用户无需手工导出重建且可恢复。
- **范围上限：** 只读预检、SQLite 一致性备份、隔离 staging 拆分、迁移映射/报告、原子入口切换、故障注入测试与恢复文档；不删除或原地修改旧库，不处理真实用户库，除非另获具体授权。
- **验收/回滚：** 固定多 Project/shared Profile/Connection/Workflow fixture，逐目标核对行数、外键闭包、Run/Attempt/Revision/current/lock、Glossary、六格式载体和 credential reference；备份/权限/空间/崩溃/校验失败均不切换入口且可幂等重试。零 Project 有配置、未知 schema、孤立记录或外键损坏 fail closed/REPLAN。旧库、快照和映射长期保留；完成后停在 `V03-T04-M01` 前。

### V03-T04 — Project Manager 与工作区 GUI

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0 UX/Data Safety；High；proposed；依赖 V03-T01～T03。
- **目标/用户价值：** 提供最近 Project、新建、打开、定位移动目录、移除最近记录、受管工作区和外部开放目录入口。
- **范围上限：** Project Manager/导航 UI、既有 open-directory service 接线、worker、i18n、行为/GUI/异常测试和用户文档；不实现只读编辑、网络共享写入、自动扫描整盘或删除外部目录。
- **验收/回滚：** “移除最近记录”与“删除 Project 数据”分离；缺失路径可定位且不重建；外部目录先校验 manifest/hash/schema/单身份并验证可写，不可写只提供导入副本；中英文/DPI/键盘/错误状态可达。失败保持当前 Session 和目标目录不变。完成后停在 `V03-T05-M01` 前。

### V03-T05 — `.aiproject` 导入导出 GUI

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0 Security/Data Portability；High；proposed；依赖 V03-T04。
- **目标/用户价值：** 将已有归档、隔离导入、向前迁移和原子安装服务接入桌面；明确归档是传输快照而非活动文件。
- **范围上限：** 导入/导出/冲突/进度/凭据缺失 UI 与对应 Application glue、测试、i18n、文档；不改变 manifest format/schema/资源限额或秘密边界，若确需改变则另行决策。
- **验收/回滚：** 开放目录 → `.aiproject` → 新数据根工作区 → 重开/再导出闭环；tamper、路径穿越、压缩炸弹、未知版本、未声明成员、目标冲突和迁移失败均在安装前拒绝；源归档和既有目标不变，覆盖前保留 `.pre-replace` 恢复副本。完成后停在 `V03-T06-M01` 前。

### V03-T06 — 集成恢复与候选门禁

- **Phase/Release / Priority / Risk / 状态：** Phase 1.5B / v0.3.0；P0 Release Gate；High；proposed；依赖 V03-T01～T05。
- **目标/用户价值：** 收束数据根、迁移、Project 切换、容器、跨机和恢复为可签收 v0.3 候选。
- **范围上限：** 旧/新回归、端到端/故障注入、Windows GUI 中英文 × 目标 DPI/分辨率、Portable 候选数据目录、文档、独立 Review；候选构建、AV、外部签收、commit/push/tag/Release 分别遵守当次授权。
- **完成条件：** 全量质量门禁与专项矩阵通过；安装/删除程序目录不误删外置 Project；网络盘明确不支持；真实端点不作前置（使用本地 fake endpoint）；AV 和人工签收如未完成保持 blocked/incomplete。全部适用门禁齐备后停在用户签发决定前。

## 1. Task规范

每个未完成 Task 必须包含：

- Task 编号、Phase/Release、Priority、风险等级和状态；
- `base_commit`、`allowed_paths`、`forbidden_paths` 与工作树归属；
- Reality Audit 结论（`KEEP / REFINE / SIMPLIFY / MERGE / SPLIT / DEFER / REMOVE / DECISION_REQUIRED`）；
- 目标、非目标、用户价值和不可破坏的不变量；
- 前置依赖、可复现基线和现有现场；
- 输入文档和权威来源；
- 硬约束、参考方案与执行 Agent 可自主决定的内容；
- 修改范围上限、交付能力和不得触碰的边界；
- 功能、异常、安全、兼容性和可观测性验收矩阵（场景、预期持久化状态、恢复动作、测试证据）；
- **兼容性基线：** `base_commit`、受影响既有能力、不可破坏不变量、对应旧测试文件/nodeid、旧测试命令与预期；
- **新增能力测试：** 至少一个新增测试文件/nodeid，以及新能力的验收证据；
- 依赖、迁移、外部调用、GUI 和公开兼容性的变更预算；
- 可选 `Decision Gate`：`decision_id`、触发条件、不可变约束、现场证据、候选方案/推荐、需更新文档、验收/回滚条件与 `resume_milestone`；
- 风险等级对应的质量门禁、独立 Review 和例外升级条件；
- 测试证据、回滚点、文档同步和完成条件。

任务单模板与风险/例外规则以 `09_Unattended_Development_Governance.md` 为准；本文件不记录即时工作树、测试数量或当前指针。

状态使用 `proposed / pending / in_progress / blocked / verification / completed`；`proposed` 表示方案已记录但尚未取得执行授权或可复现基线，不得自动开工。Milestone 的 `ready` 和 Reality Check 结论只记录在 `DEVELOPMENT_STATE.md`。一个 Task 只完成一组内聚的用户能力，不把后续功能顺手扩入当前 Task。

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

Agent 收到 `DEVELOPMENT_STATE.md` 后，只有当前状态为 `ready`/`in_progress`/`verification`、`code_authorized: true` 且授权范围覆盖目标文件时，才自动读取当前 Task、加载指定文档并开始。`proposed`、`code_authorized: false` 或仅授权 Markdown 时不得写测试、代码、脚本或配置。每个 Milestone 在写测试或代码前必须按 `06_AI_Development_Guide.md` 完成 Reality Check，并在状态文件记录 `FIT`、`ADAPT` 或 `REPLAN`。

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

测试失败、证据缺失、兼容性基线未运行、受影响旧测试失败或文档未同步时，不得标记 `completed`。每个新增能力至少有一条新增测试；删改既有测试必须记录理由并经独立 Review，不能用“全量 pytest 通过”替代旧功能回归清单。

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
  -> V02-T00 v0.2 事实基线与计划冻结
  -> V02-T01 UI 基础与中英文
  -> V02-T02 Project 生命周期与六格式 GUI
  -> V02-T03 Connection/Profile 管理体验
  -> V02-T04 Translation/Workbench 体验
  -> V02-T05 v0.2 Release Candidate Gate
  -> V03-T00 Project 存储决策门禁
```

本文件预先定义已批准依赖链中的全部 Task 与垂直 Milestone。`07` 只负责稳定规划、范围、依赖和验收；`DEVELOPMENT_STATE.md` 是当前 Task、当前 Milestone、真实工作区、测试证据和恢复动作的唯一运行时来源。新增或调整未来规划不得自动推进运行指针；只有执行 Agent 验证依赖并实际开工时，才原子更新状态文件。

每个未完成 Task 下的 **Reality Audit** 是 2026-07-30 的规划取证结果，不是完成状态。分类含义：`KEEP` 保留目标；`REFINE` 修正边界/依赖/验收；`SIMPLIFY` 删除不必要抽象；`MERGE` 合并重复交付；`SPLIT` 拆成垂直检查点；`DEFER` 延后；`REMOVE` 移出范围；`DECISION_REQUIRED` 等待用户裁决。后续代码变化可使该结果陈旧，因此每个 Milestone 仍须独立执行 `FIT / ADAPT / REPLAN`。

每个 Milestone 必须交付一个可独立验证的行为，并在同一切片中包含必要测试和最小实现。Milestone 表使用“行为与完成条件”，不得采用“先写全部 DTO/Repository、再写全部 UI”的纯水平切分，也不得预填测试通过数。证据要求：代码 Task 记录实际 pytest/Ruff/mypy；Adapter 使用可控 fake transport/server；GUI 必须实际启动并执行 pytest-qt/交互验证；恢复、备份和格式 round-trip 必须有数据库或文件级显式断言。

### 4.1 已计划的 Decision Gate

仅以下 P1 节点默认需要开发/决策 Agent 切换；其余 Milestone 按既有硬约束直接执行，除非新证据造成契约冲突：

| decision_id | 触发点 | 决策范围 | 恢复点 |
|---|---|---|---|
| DEC-P1-T01-FOUNDATION | P1-T01-M01 | format metadata、原始 bytes/span、TXT 旧库升级底座 | P1-T01-M01 |
| DEC-P1-T02-CONTAINER | P1-T02-M01/M03 | manifest 权威边界、开放目录安全模型、资源限额、Unicode/link 冲突 | P1-T02-M01 |
| DEC-P1-T04-GLOSSARY | P1-T04-M02 | Glossary scope、重复词冲突、priority 语义 | P1-T04-M02 |
| DEC-P1-T03-OVERRIDE | P1-T03-M03 | Prompt Override 编辑边界、拒绝规则、父版本失效策略 | P1-T03-M03 |
| DEC-P1-T05-RELEASE | P1-T05-M01/M04 | lockfile、支持环境、打包工具、Windows 架构范围 | P1-T05-M01 |
| DEC-V03-PROJECT-STORAGE | V03-T00 | 全局多 Project DB 与一 Project 一容器的统一契约、旧库拆分、portable/data-dir | V03-T01（裁决后创建） |


## 5. 治理准入 Task

### GOV-BASELINE-01 — P0-T07/T08 候选现场审查与可复现基线

- **Phase/Release：** 治理准入 / V1.0 前置
- **Priority：** P0 / Release-blocking
- **风险等级：** High
- **状态：** completed
- **目标：** 在不覆盖、丢弃或混入用户数据的前提下，审计并保护未提交的 P0-T07 至 P0-T08 staged、unstaged 与 untracked 候选现场，重新取得可复现质量证据，并形成可恢复的开发基线。
- **非目标：** 不新增 P1 功能；不擅自提交、暂存、推送、创建远程资源或删除工作树；不把历史测试记录重新表述为本次结果。
- **前置基线：** `master` 的 `e3cf48e` 已包含 P0-T03 至 P0-T06；当前候选现场含 P0-T07/T08 源码、测试、migration `006` 和文档，必须按 Git 实际状态核验。
- **修改范围上限：** Git 状态证据、治理/状态文档、忽略规则及经用户授权的基线保护动作；不得改业务代码，除非验证发现可独立复现的 P0 缺陷并由技术负责人拆分为单独修复切片。
- **功能验收：** 完整区分 staged/unstaged/untracked/用户运行数据；确认 migration `006`、后续源码和测试的归属；执行并记录当前工作树的 pytest/Ruff/mypy 结果；记录恢复方式、已知缺口和可定位的基线标识。
- **异常/安全验收：** `*.db`、`*.db.bak`、凭据、日志和导出物不进入候选；不使用 reset/restore/clean/覆盖操作；质量失败时保持 `blocked` 或 `verification`，不得推进 P1。
- **独立 Review：** 检查候选 P0 实现、migration `006`、状态文档和测试证据的一致性。
- **完成条件：** 技术负责人确认候选现场可恢复并具有本次可复现门禁证据；需要提交、隔离分支或远程备份时取得用户的明确授权；随后才将 P1-T01-M01 恢复为 `ready`。

## 6. 当前可执行 Task

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
- **状态：** completed
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

| Milestone | 可独立验证的行为与完成条件 | 状态 |
|---|---|---|
| P0-T07-M01 | **可重开执行骨架：** 新/旧 Project 应用新 migration 后都能读取一个版本化只读内置 Workflow；可创建引用它的 Run，并在第一次外部请求前持久化包含快照/审计基础的 Attempt。无效 Workflow/Profile/Segment 引用、重复定义版本或 migration 中断必须回滚。先执行 Reality Check；内部表/类拆分为参考方案。 | completed |
| P0-T07-M02 | **原子领取与幂等：** 一个 pending Segment 只能被一个 owner 以新 version 领取并关联新 Attempt；重复幂等键返回既有记录、不重复执行；未过期 lease、错误状态和 stale version 被拒绝。以可控 UTC 时钟验证过期边界和数据库重开。 | completed |
| P0-T07-M03 | **成功完成事务：** 对有效 Validator 结果一次性保存响应审计、追加 Revision、更新 current revision 并完成 Segment/Attempt/Run 统计；任一故障切点全部回滚或保持可恢复 processing，迟到 owner 和 locked/current 已变化时不得提交。 | completed |
| P0-T07-M04 | **失败、取消与启动恢复：** normalized permanent/retryable/validation 错误形成可解释 Attempt；仅 retryable failed 可重新排队并创建新 Attempt；取消保留既有 Revision/原因；启动只回收过期 processing，不覆盖人工/locked current。验证 transport retry 同 Attempt、repair/业务 retry 新 Attempt。 | completed |
| P0-T07-M05 | **恢复矩阵与 Task Gate：** 覆盖请求前、请求后、响应审计、Revision、current/status 前后崩溃，重复启动恢复、lease 冲突、锁定回归；执行全量 pytest/Ruff/mypy、规划范围 Code Review 和编号文档/索引/状态同步。不得以测试矩阵替代缺失行为。 | completed |

## 15. P0-T08 — TXT 翻译端到端与最小 GUI Shell

- **Task 编号：** P0-T08
- **Phase/Release：** Phase 0 / V0.x
- **Priority：** P0
- **状态：** completed
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
| P0-T08-M01 | **无 UI 成功闭环：** 给定已导入 TXT、Profile 和 fake Adapter，一个应用用例完成 compose/render/call/validate/T07 finalize，生成可重开 Revision；空 Segment、缺 Profile、预算不足不发请求。 | completed |
| P0-T08-M02 | **生产调用边界：** 通过受控本地 HTTP server 验证真实 transport 与配置 composition；环境变量及已支持的 Windows credential reference 可解析，timeout/redirect/认证/响应错误稳定归类且不泄密。新增依赖先做 Reality Check 和打包影响记录。 | completed |
| P0-T08-M03 | **失败与有限修复 E2E：** Adapter 错误、无效输出和一次 repair 进入正确 Attempt/Segment；永久错误不业务重试，repair 新建 Attempt，窗口/进程重启后仍可解释并按 T07 恢复。 | completed |
| P0-T08-M04 | **Revision 驱动 TXT 导出：** 当前或显式有效 Revision 按原 Segment 顺序导出；缺失/跨 Segment/无效 Revision、编码和不可写目标失败时不留下半文件，不回退未验证文本。 | completed |
| P0-T08-M05 | **非阻塞桌面闭环：** 最小主窗口与 Settings/Project/Translation 入口通过同一 Application Service 导入、选择 Profile、启动/取消翻译、显示进度/错误并导出；pytest-qt 和人工操作证明主线程可响应、关闭可恢复。 | completed |
| P0-T08-M06 | **Phase 0 Gate：** 对成功/失败/关闭/reopen 做 E2E 与 GUI review；运行全量质量命令；用一个候选打包工具完成本机 build/start 可行性 smoke 并记录依赖/Qt 插件问题，不冻结最终工具或发布 artifact；同步文档与状态。 | completed |

## 16. P1-T01 — JSON / SRT / ASS / SSA / VTT round-trip

- **Task 编号：** P1-T01
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** completed
- **Reality Audit：** `REFINE + SPLIT`。Parser Protocol/Registry、稳定 Segment 和 TXT seam 可复用；format metadata 持久化、Exporter contract 和五类格式均不存在。先以 TXT 证明通用保真载体，再逐格式垂直交付，不重写 registry。
- **目标：** 导入并翻译 JSON 与字幕文件，同时精确保留不可翻译结构和格式元数据，使导出可由 golden fixture 判定。
- **非目标：** 不支持 Markdown/EPUB/HTML/Word/Ren'Py，不自动修复损坏格式，不改变核心翻译状态机。
- **用户价值：** 用户可安全处理 V1.0 承诺格式，不必手工还原 JSON 结构、字幕时间轴或 ASS/SSA 样式。
- **前置依赖：** P0-T08；T07 Revision/export 选择语义稳定。
- **现有现场：** SourceDocument/Segment 无格式 metadata；TXT parser 丢弃空行/首尾空白，尚无通用 round-trip 能力或 fixture 目录。
- **输入文档和权威来源：** `01` §5/21；`02` §7；`03` §4/9；`04` §3/5；`06`。
- **硬约束：** SourceDocument 逻辑复用身份包含 Project、源 bytes hash、format 和会改变 Segment 映射的 parser identity/version；P1-T01 用新 migration 扩展 `003` 的内容 hash 唯一性，不重写 `003`。stable key 来自格式结构而非仅数组下标；格式 metadata 与源内容版本同事务保存。无翻译导出必须字节一致；翻译导出必须保留原编码/BOM、换行风格和所有非目标字节或经该格式明确允许的等价表示。JSON 只翻译 string leaf value，key、非字符串值和容器不翻译；可配置路径选择若需要后置为明确能力，不在 V1.0 猜测智能字段。SRT/VTT 保留 cue 时间、标识、settings 和非目标行；ASS/SSA 仅替换 Dialogue 的 Text 字段，保留 section、Format、style、event 字段顺序、注释、标签和转义。损坏/不支持输入默认拒绝且不污染 Project，不做静默修复。
- **已裁决契约（`DEC-P1-T01-FOUNDATION`，方案 2）：** 持久化原始 bytes，并在同一版本化 `format metadata envelope` 中保存 encoding、BOM、newline、parser/metadata version、源 hash 与格式专属定位信息；TXT 使用受验证的 byte/character replacement mapping，JSON/SRT/VTT/ASS/SSA 各自保存其安全定位 metadata，但共用 envelope、Revision 校验与原子 exporter seam；不得把多字节编码、换行归一化或格式结构强行压成统一 span 模型（方案 1/3 已否决）。旧 TXT 数据缺少可验证原始 bytes/metadata 时安全拒绝保真导出，不得猜测恢复或静默重序列化；用户提供并校验原文件后才允许显式补齐载体。
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
| P1-T01-M01 | **保真载体与 TXT 证明：** 在旧 Project 可升级前提下持久化格式 metadata，并由通用 Exporter seam 让 TXT no-op 字节一致、Revision 替换只改目标 span；metadata 缺失/错配安全失败。`008` migration 加 `raw_bytes`/`format_metadata`（版本化 envelope：encoding/BOM/newline/parser_version/source_hash + TXT byte span locator）并把逻辑唯一域扩展为 `(project_id, source_hash, format, parser_version)`；exporter 替换前逐项验证 hash/encoding/BOM/newline/span 越界/重叠/解码，no-op 逐字节输出、翻译仅改目标 span；旧 TXT 缺载体拒绝导出，用户提供原文件且 hash+Segment 映射一致后显式补齐载体；目标不可写/编码错误/任一校验失败不污染 DB、Revision 或既有目标文件。 |
| P1-T01-M02 | **JSON 垂直闭环（completed，2026-08-06）：** string leaf value 生成稳定结构路径 Segment，no-op 字节一致，翻译仅替换 value token；保留 key/order/number/escape/whitespace，malformed/深度或错位 Revision 不污染数据。新增 `infrastructure/parsers/json_parser.py`（`JSONParser` + 单遍迭代 tokenizer：只把 value 位置字符串生成为 Segment，记录 JSON Pointer 结构路径 + value token byte span，深度上限 512；拒绝 malformed/重复对象 key/超深度/未配对 `\u` 代理项）、`infrastructure/fidelity.py` `build_json_envelope`（`json.paths` locator）、`application/exporter.py` 提取 `FidelityExporter` 基类（共享 carrier/envelope 验证/Revision 校验/原子写）并新增 `JsonExporter`（替换前重解析原始 bytes 逐项验证 path/span/value，译文经 `json.dumps(ensure_ascii=False)` 转义替换）；`default_registry()` 注册 `JSONParser`。新增 `tests/test_p1_t01_m02.py` **71 项**（no-op 字节一致含嵌套/转义/非 ASCII/UTF-8 BOM/UTF-16 LE/BE/CRLF/空容器/无字符串文档；翻译仅改 value token 保留 key/order/number/whitespace/转义；UTF-16 替换；Revision override；语义 round-trip 重导入；malformed/深度/重复 key/未配对代理项拒绝无污染；envelope 篡改拒绝；编码失败/不可写目标不污染；真实 TranslationService 垂直闭环 round-trip）。受影响旧测试 230 项 + 全量 604 passed、Ruff clean、mypy 91 files no issues；独立 Review Agent 验收（发现根值后单尾随 token 误接受，已修复并加 6 用例）。Reality Check 结论 **ADAPT**（JSON 定位不套用 TXT byte span，共享 seam 提取为基类）。 |
| P1-T01-M03 | **SRT 垂直闭环（completed，2026-08-06）：** 每个 cue 的文本块生成为稳定 Segment，no-op 字节一致，翻译仅替换目标文本块，保留序号/标识/timing/settings/空行/换行。新增 `infrastructure/parsers/srt_parser.py`（`SRTParser` + 单遍物理行扫描 `extract_cues`：可选 index 行 + timing 行 + 非空文本行直到空行；`srt.cues` locator 记录 sequence/index/原样 start/end/可选 settings/文本块 byte span；拒绝非法时间轴/重复 cue 时间轴/空 cue 文本/缺失空行分隔/序号后缺失 timing）、`fidelity.py` `build_srt_envelope`（`srt.cues` locator）、`application/exporter.py` `SrtExporter`（复用 `FidelityExporter` seam，替换前用同一 `extract_cues` 重解析验证 sequence/index/timing/settings/span/text，译文直接编码替换）；`default_registry()` 注册 `SRTParser`。新增 `tests/test_p1_t01_m03.py` **75 项**（no-op 字节一致含 LF/CRLF/UTF-8 BOM/UTF-16 LE/BE/多行/首尾空行/settings/点分隔/index-less；翻译仅改 cue text 保留结构，多行块/换行/CRLF/UTF-16/Revision override/round-trip 重导入；非法时间轴/重复定位/空文本/缺分隔拒绝无污染；envelope 篡改（index/timing/settings/span/sequence/source_text/hash/BOM/newline/schema/parser version/format/raw bytes/locator/数量）拒绝；编码失败/不可写目标不污染；真实 TranslationService 垂直闭环 round-trip + adapter 失败 finalize）。受影响旧测试 301 项 + 全量 679 passed、Ruff clean、mypy 93 files no issues。Reality Check 结论 **ADAPT**（SRT 定位不套用 TXT/JSON 语义，复用共享 seam）。 |
| P1-T01-M04 | **VTT 垂直闭环（completed，2026-08-06）：** 保留 WEBVTT header、cue ID、timing settings、NOTE/STYLE/REGION 和文本标签；非法 cue 或 metadata 不静默降级为 SRT。新增 `infrastructure/parsers/vtt_parser.py`（`VTTParser` + 单遍物理行扫描 `extract_cues`：先校验 `WEBVTT` 签名，`NOTE`/`STYLE`/`REGION` 块消费到空行为结构性 bytes；每 cue 文本块生成 Segment，`vtt.cues` locator 记录 sequence/id/原样 start/end/可选 settings/文本块 byte span；W3C 时间戳规则——完整 `HH:MM:SS.mmm` 与省略小时 `MM:SS.mmm`（点分隔），毫秒恰 3 位，分钟/秒 00-59，小时位数不限；拒绝缺签名、坏时间轴、重复 cue 时间轴、空 cue 文本、bad cue 标识、含 `-->` 但非 timing 的文本行，SRT 内容不静默降级）、`fidelity.py` `build_vtt_envelope`（`vtt.cues` locator）、`application/exporter.py` `VttExporter`（复用 `FidelityExporter` seam，替换前用同一 `extract_cues` 重解析验证 sequence/id/timing/settings/span/text，译文直接编码替换目标文本块）；`default_registry()` 注册 `VTTParser`。新增 `tests/test_p1_t01_m04.py` **86 项**（no-op 字节一致含 LF/CRLF/CR/UTF-8 BOM/UTF-16 LE/BE/header+NOTE/STYLE/REGION/内联标签/部分+完整时间戳/无空行分隔 cue；翻译仅改 cue 文本块保留 header/ID/timing/settings/blocks，多行/换行/CRLF/UTF-16/Revision override/round-trip；缺签名/逗号时间戳/SRT 内容/坏时间轴/重复定位/空文本/bad cue/越界分钟秒拒绝无污染；envelope 篡改（id/timing/settings/span/sequence/source_text/hash/BOM/newline/schema/parser version/format/raw bytes/locator/数量/re-parse 失败）拒绝；编码失败/不可写目标/缺载体不污染；真实 TranslationService 垂直闭环 round-trip + adapter 失败 finalize）。受影响旧测试 376 项 + 全量 765 passed、Ruff clean、mypy 95 files no issues；独立 Review Agent 验收 **APPROVE-WITH-MINORS**（1 项 SHOULD-FIX 时间戳分钟/秒超 59 已修复并补测试；其余 MINOR 为已记录取舍/共享 seam 行为）。Reality Check 结论 **FIT**（VTT 定位按裁决定义，复用已批准 envelope/唯一域/exporter seam）。 |
| P1-T01-M05 | **ASS/SSA 垂直闭环（completed，2026-08-07）：** 依据 Events Format 只替换 Dialogue Text，保留 section/style/comment/tag/escape/逗号字段；两格式共享一个解析引擎，各有 golden 与 malformed fixture，不创建两套无必要框架。新增 `infrastructure/parsers/ass_ssa_parser.py`（`AssSsaParseError`/`AssSsaEvent`/`extract_events` 单遍扫描：`[Script Info]` 开头签名 + `ScriptType` 必须匹配 format（ass=`v4.00+`、ssa=`v4.00`），`[Events]` 必须声明标准 `Format:` 字段表（缺/重复/非标准拒绝），每个 `Dialogue:` 事件按字段数 split 后取最后 Text 字段（逗号/标签/`\N` 转义/首尾空格原样保留）生成 Segment，`ass.events`/`ssa.events` locator 记录 sequence/start/end/Text byte span，Start/End 按 `h:mm:ss.cc` 校验（分钟/秒 00-59、百分秒 2 位），空/纯空白 Text 拒绝，重复时间轴允许；`Comment:` 与其他事件类型为结构性 bytes）；`fidelity.py` `build_ass_envelope`/`build_ssa_envelope`（`ass.events`/`ssa.events` locator）；`application/exporter.py` `_AssSsaExporter`（复用 `FidelityExporter` seam，替换前用同一 `extract_events` 重解析验证 sequence/start/end/span/text，译文直接编码替换目标 Text 字段）+ `AssExporter`/`SsaExporter`；`default_registry()` 注册 `AssParser`/`SsaParser`。新增 `tests/test_p1_t01_m05.py` **155 项**（no-op 字节一致含 LF/CRLF/CR/UTF-8 BOM/UTF-16 LE/BE/全文件含 section/style/comment/Comment 事件/标签/转义/逗号文本/EOF 无尾换行；翻译仅改 Dialogue Text 保留结构含多 Dialogue/Comment 不译/逗号/标签转义/首尾空格整字段替换/CRLF/UTF-16/Revision override/round-trip 重导入；缺签名/错配 ScriptType/缺 ScriptType/缺或非标准或重复 Format/字段数不足/空或纯空白文本/非法时间轴（含坏分隔/分钟秒超 59/百分秒位数错）拒绝无污染；envelope 篡改（start/end/sequence/span/source_text/hash/BOM/newline/schema/parser version/format/raw bytes/locator/数量/re-parse 失败）拒绝；encoding override 匹配/错配；编码失败/不可写目标/缺载体不污染；真实 TranslationService 垂直闭环 round-trip + adapter 失败 finalize；同身份幂等 + 同 bytes ass/ssa/txt 分离）。受影响旧测试 462 项 + 全量 920 passed、Ruff clean、mypy 97 files no issues。Reality Check 结论 **FIT**（ASS/SSA 按裁决定义共享引擎与 locator，复用已批准 envelope/唯一域/exporter seam）。 |
| P1-T01-M06 | **全格式 Gate（completed，2026-08-07）：** Reality Check **FIT**。复核 M01–M05 六格式 no-op/translated/error/不可写/旧库升级矩阵证据、共享 `FidelityExporter` seam 与 envelope 一致性（TXT byte span / JSON path / SRT·VTT cue / ASS·SSA events 各 locator 字段与 parser 重解析逐项一致）；统一执行矩阵：全量 pytest **920 passed**（M01 TXT=35、M02 JSON=71、M03 SRT=75、M04 VTT=86、M05 ASS/SSA=155，合计 422 + P0 基线 498）、受影响旧测试子集 617 passed、Ruff All checks passed、mypy Success no issues in 97 source files；独立 Review Agent 验收（无 BLOCKER/SHOULD-FIX；4 MINOR 为已记录取舍：TXT exporter 不校验 parser_version——TXT span 经越界/重叠/decode==source_text 逐项校验、无损坏路径，与其他五格式的 fail-closed 不一致但非安全缺口；Revision 解析/编码块在五子类重复为维护取舍；导出文件 0600 权限为 Windows 既有行为；backfill 不更新行 parser_version/encoding 为潜在重复导入隐患——当前全版本 1.0.0 无实际路径）。同步格式契约、索引和状态，未预填通过数。 |

## 17. P1-T02 — Project 双形态、离线迁移、备份与安全导入

- **Task 编号：** P1-T02
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** completed（M01–M05 全部 completed，2026-08-07）
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
| P1-T02-M01 | **共享 manifest 与开放目录（completed，2026-08-07）：** 建立一个可创建/重开、可验证的开放目录 Project；manifest 固定 format/schema/software/file/hash/size/relative path，未知版本、根外路径、link 和重复关键 entry 被拒绝。新增 `infrastructure/open_directory.py`（manifest schema/结构校验/路径安全/`is_link`（symlink + Windows reparse point）/逐 entry 大小+`sha256:` hash 校验/原子写；`load_manifest` 拒绝重复 JSON key）、`application/open_directory_service.py`（`create_open_directory_project`：目录必须为空、初始化 SQLite 复用 `ProjectService`/`MigrationRunner`/P0-T03-M00 备份 seam 后清理新建空库 `*.pre-upgrade-*.db.bak` 与 WAL 附属文件、原子写 manifest、失败清理自身产物；`open_open_directory_project`：先校验 manifest（未知 format/schema 版本、缺字段、重复 key、缺失/重名/重复关键 `project.sqlite` entry、entry 别名 manifest 拒绝）再校验相对路径（绝对/盘符/UNC/`..`/归一化逃逸/大小写或 Unicode 等价重复/尾部点空格别名/控制字符/link/junction/父目录 link 逃逸均拒绝）与大小/hash，最后打开数据库并要求恰一个 Project 身份且 schema_version 与 manifest 一致，任一失败不触碰数据库）。`ProjectService` 增只读 `list_projects()`。新增 `tests/test_p1_t02_m01.py` **76 项**（create 产出干净容器、manifest 字段/hash 正确、重开保持同一 Project、非空目录/文件路径拒绝、失败清理含既有空目录保留；open 缺目录/文件路径/多 Project/篡改 db 拒绝、附件声明可打开、重开保持容器清洁、篡改 format_version round-trip 拒绝；manifest 缺文件/非法 JSON/未知 format·schema 版本/缺字段/files 非对象/entry 结构错误/顶层与嵌套重复 key 拒绝；critical entry 缺失/重复/改名、manifest 自别名（含尾部点）、大小写·Unicode·尾部点等价重复拒绝；13+3 种根外路径与控制字符拒绝；缺文件/大小/hash 错/目录 entry/junction/symlink/父目录 junction 逃逸拒绝；`is_link` reparse point 单测）。受影响旧测试子集 193 passed + 全量 pytest **996 passed**、Ruff clean、mypy 100 files no issues。独立 Review Agent 验收无 BLOCKER；1 SHOULD-FIX（NUL 字节路径经 `canonical_relpath` 拒绝 + `is_link` 捕获 ValueError）与 2 项 MINOR 加固（Windows 尾部点/空格别名折入 identity、checkpoint 失败不删 WAL 附属）已修复并补测试；其余 MINOR 为已记录取舍（`software` 不比对开放版本属 M01 范围、大写 hash fail-closed、reopen 在 create 尾部的失败保留完整容器）。Reality Check 结论 **ADAPT**（现场 seam 齐备；容器化需清理新建空库备份；manifest JSON 字段名在 `04` §7 强制字段内自定并版本化）。不触发 DEC-P1-T02-CONTAINER：M01 范围已在 `04` §7 裁决，资源限额/隔离 staging 属 M03。 |
| P1-T02-M02 | **一致性单文件导出（completed，2026-08-07）：** 从一个逻辑 Project 的开放目录/活动数据库用 SQLite backup 和附件清单生成 `.aiproject`，manifest/hash 可复验，secret/log 不入包；零/多 Project 不被静默打包。新增 `application/archive_service.py`（`export_open_directory_archive`：源开放目录经 M01 校验 manifest/路径/hash/恰一个 Project 后导出；`export_database_archive`：源裸活动数据库 `list_projects()` 恰一个才导出，零/多 Project 明确拒绝 `ArchiveExportError`）、`infrastructure/migrations/backup.py` `create_consistent_snapshot`（SQLite backup API 一致性 snapshot，不直接复制活动数据库，失败清理半成品、缺失源拒绝）、`infrastructure/open_directory.py` `write_archive`（临时 staging 一致容器 `verify_entries` 自校验后 zip 原子写：`manifest.json` + `project.sqlite` + 声明附件，内部 relpath 与 manifest 一致、解包即开放目录；拒绝 link/junction 目录、OSError 包装 `OpenDirectoryError`）。新增 `tests/test_p1_t02_m02.py` **23 项**（开放目录导出 zip 含 manifest/snapshot/附件、manifest 逐 entry 大小+`sha256:` hash 可复验、round-trip 解包重开同一 Project、附件子目录保留、成功原子覆盖既有目标、未声明 log/secret 文件不入包且归档 bytes 无原始 secret、打包 DB 只保留 credential reference 无原始值、WAL 未提交事务排除/已提交数据包含、篡改附件 `FileIntegrityError` 拒绝、多 Project 容器拒绝、缺源目录/缺目标目录拒绝、失败无半成品归档/既有目标保留、裸 DB 导出/空库/多 Project 拒绝、snapshot 失败清理/缺源拒绝/target 为目录 OSError 包装/link 条目拒绝）。受影响旧测试子集 193 passed + 全量 pytest **1019 passed**、Ruff clean、mypy 102 files no issues。Reality Check 结论 **ADAPT**（`.aiproject` = 标准 ZIP + manifest + 一致性 snapshot + 声明附件，stdlib `zipfile` 零新依赖；导出用临时 staging 一致容器；零/多 Project 明确拒绝；`create_consistent_snapshot` 复用 backup API seam）。独立 Review Agent 验收无 BLOCKER；1 SHOULD-FIX（snapshot 失败残留半成品 target）与 MINOR 加固（错误文案漂移还原、junction 目录洞改逐层 link 拒绝、`write_archive` OSError 包装、缺源静默建空快照拒绝）已修复并补测试；其余 MINOR 为已记录取舍。 |
| P1-T02-M03 | **隔离安全导入（completed，2026-08-07）：** `.aiproject` 只解到新的隔离 staging（目录须为空，拒绝非空；成功/失败均不触碰最终安装目标，M04 才执行 migration 与原子安装）。新增 `infrastructure/open_directory.py` `parse_manifest_text`（`load_manifest` 复用）、`ArchiveLimits`（fixture 固定默认值：entry 数 ≤1000、单项未压缩 ≤256 MiB、总未压缩 ≤512 MiB、压缩比 ≤5000:1；Release Gate 定稿，调用方可传更窄限额）、`ArchiveError`/`ArchiveLimitError`、`extract_archive`（先读归档内 manifest 并 `parse_manifest_text`+`validate_manifest`+`canonical_relpath` 校验——重复 key/未知 format·schema 版本/traversal/绝对路径/盘符/UNC/`..`/控制字符/大小写·Unicode·尾部点别名/manifest 自别名均拒绝；`_check_member_duplicates`/`_check_undeclared_members` 拒绝重复/未声明/目录成员；`_check_size_limits`+`_check_compression_ratio` 对 ZIP 头在写盘前施加限额；只解声明 entry（手工 canonical relpath，zip-slip/link/未声明内容不可逃逸 staging）；`verify_entries` 逐项复核大小/`sha256:`/link）；`application/archive_service.py` 新增 `ArchiveImportError`/`import_archive_to_staging`——隔离 staging 生命周期（失败清理自身产物、保留既有空目录）、`_verify_staging_database` 只读校验恰一个 Project + `projects.schema_version` 与 manifest 一致（非整数 schema_version 也报 `ArchiveImportError`）、成功后清理 WAL 附属保持容器干净。新增 `tests/test_p1_t02_m03.py` **37 项**（成功 round-trip 同契约可重开/嵌套附件/隔离干净/既有空 staging/手筑合法归档/高压缩附件非误伤；缺归档/非空 staging/非 zip/缺 manifest/非法 JSON/重复 key/未知 format·schema 版本/超大 manifest 拒绝；缺附件/tamper/未声明成员/重复成员/目录成员拒绝；traversal/绝对路径/大小写·Unicode 冲突/manifest 自别名/未声明 traversal 成员拒绝；entry 数/单项/总大小/压缩比超限拒绝；零/多 Project/schema 错配/非整数 schema/非 SQLite 拒绝；失败清理与既有空目录保留）。受影响旧测试子集 216 passed + 全量 pytest **1056 passed**（基线 1019 + M03 37）、Ruff clean、mypy 103 files no issues。独立 Review Agent 验收无 BLOCKER；1 SHOULD-FIX（`projects.schema_version` 非整数时原始 `ValueError` 逃逸，改报 `ArchiveImportError`）已修复并补测试；其余 MINOR 记录取舍（`namelist` 先物化后限数、`extract_archive` 不自行判空由 app 层保证、`_purge_sqlite_sidecars` 无条件删空 WAL 附属、只读 DB 校验不查其余表属 M04 范围）。Reality Check 结论 **ADAPT**（M01/M02 seam 齐备；DEC-P1-T02-CONTAINER 不触发——限额维度已在 `04` §7 裁决、具体数值由 M03 fixture 固定）。 |
| P1-T02-M04 | **双形态迁移与原子安装（completed，2026-08-07）：** 开放目录容器经 `migrate_container` 就地向前迁移——只读校验 manifest/路径/大小/hash 与恰一个 Project + schema 匹配 → `ProjectService`/`MigrationRunner` seam 跑 pending migration（P0-T03-M00 先建一致性备份）→ 成功后清理容器内瞬时 `*.pre-upgrade-*.db.bak` 与 WAL 附属、重算 manifest（新 DB 大小/hash、schema_version 取 DB、保留附件与 `source_id`）并复验，容器只含受控条目；无 pending 不动容器。修复 `open_open_directory_project` 打开旧 schema 容器后 stale manifest + 残留 `.bak` 致二次打开 hash mismatch 的缺陷（迁移后先关闭连接 checkpoint 再清理/重算/复验）。新增 `application/install_service.py`：`InstallError`/`TargetConflictError`（带 `suggested_name`）、`migrate_container`、`install_staging_to_target`（迁移 staging → 把源 Project id 写 manifest `source_id` 供追踪 → 新/空目标原子安装：同父临时目录构建+全量验证+rename；目标已含 Project 时未经 `confirm_overwrite` 拒绝，同名冲突给确定性后缀建议名如 `Alpha (2)`；确认覆盖把既有目标移为 `.<target>.pre-replace-<ts>.bak` 恢复备份再安装、失败还原）。`open_directory.py` 增可选 `ManifestInfo.source_id` 与共享 helpers（`check_container_identity`/`purge_sqlite_sidecars`/`remove_pre_upgrade_backups`/`regenerate_manifest`/`cleanup_after_container_migration`）；`ProjectService` 增 `applied_migrations` 并在 init 失败关闭连接；`archive_service` 复用共享 purge helper。新增 `tests/test_p1_t02_m04.py` **29 项**（旧 schema 容器打开迁移+保持干净+二次重开、数据保留、无 pending 不动容器、migration 执行失败保留旧 DB + pre-upgrade 备份、备份失败阻断迁移、迁移清理（manifest 重算）失败保留备份、打开后二次迁移可重开；旧归档导入→staging→安装到新目标含 008+干净+重开、空目标、`source_id` 记录与重开保留、非目录/非容器 staging 拒绝、非空非容器目标拒绝、同名冲突建议名+拒绝、异名冲突拒绝、确认覆盖替换+保留 `.pre-replace` 恢复备份、install 替换 rename 失败还原目标、install 双重失败点名恢复备份、迁移失败目标不动、版本不兼容目标拒绝、install 创建失败领域错误+目标不动；manifest `source_id` round-trip/可选/非法拒绝）。受影响旧测试子集 253 passed + 全量 pytest **1085 passed**（基线 1056 + M04 29，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 105 files no issues；手工 smoke 验证 create→export→import→install→open round-trip（project identity/source_id/segment 数据/008 全保留、目标容器干净）。Reality Check 结论 **ADAPT**（现场 seam 齐备且确认旧 schema 容器打开缺陷；`source_id` 可选字段入 manifest；ID 冲突以新容器本地身份 + manifest `source_id` 追踪落地，不重写 FK 约束的 project id）。独立 Review 验收**无 BLOCKER**；2 SHOULD-FIX（`cleanup_after_container_migration` 先删备份后重算 manifest 会把容器卡死，改为先重算 manifest 再最后删备份；install 恢复失败分支未测且双重失败会掩蔽原错误并丢恢复指针，改为链原错误+点名恢复备份）已修复并补 3 项测试；其余 MINOR 记录取舍（只读检查不再 purge 目标 sidecars、`sqlite3.connect` 越界改报领域错误、`suggest_available_name` 简化内联、不支持版本目标报 "not empty" 掩蔽真实原因、post-migration 读失败保留备份需手动恢复）。 |
| P1-T02-M05 | **跨机器与双形态 Gate（completed，2026-08-07）：** Reality Check **ADAPT**——M01–M04 全链路 seam 齐备且各段有单测，缺口是 `04` §7”目标机缺凭据时必须给可操作提示”缺应用层只读表面。新增 `adapters/credential_resolvers.py` 模块级 `credential_reference_is_available(reference: str\|None)`（只读判 `env:` 变量存在且非空 / `wincred:` 凭据存在且非空，从不返回 secret；wincred 经新增 `WindowsCredentialResolver._credential_exists` 只查 CredReadW 返回 size>0、不把 secret blob 读入内存）与 `application/credential_status.py`（`CredentialStatus` + `report_credential_availability(connections)`：按连接列出引用/available/可操作 hint，跳过无引用连接，永不解析 secret）。新增 `tests/test_p1_t02_m05.py` **26 项**：跨机 round-trip 核心状态（开放目录 -> `.aiproject` -> 独立临时根模拟”另一台 Windows” -> 安装 -> 重开：project identity/manifest `source_id`/segments+008 fidelity carrier/connection 只存引用/profile/translation run/附件字节一致；从已安装目标再导出再导入到”机器 C”）；旧 schema(001-007)归档在目标机经备份+migration 安装且容器干净；缺 env/wincred credential 报告与可操作 hint（present/absent/空值/None/未知 scheme/secret 不泄）；secret 不入归档与已安装目标、未声明 secret/log 文件不跨机；tamper 矩阵（篡改开放目录拒绝导出；篡改附件/缺附件/篡改 manifest hash/截断/未声明成员/traversal/超限额拒绝导入且 staging 清理；篡改已安装目标拒绝打开）；同名目标冲突建议名+确认覆盖保留 `.pre-replace` 恢复备份；WAL 未提交不跨机。受影响旧测试子集 384 passed + 全量 pytest **1111 passed**（基线 1085 + M05 26，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 107 files no issues。独立 Review 无 BLOCKER；1 SHOULD-FIX（空值凭据被误判 available 致目标机静默 401 无提示，改空值/空 blob 判不可用并补测试）与 MINOR 加固（签名 `str\|None`、wincred 存在性检查不读 blob、补 None/未知 scheme/空值用例）已修复；其余 MINOR 记录取舍（报告为应用层纯函数，UI 落地归 P1-T04；`CredentialResolver` protocol 未改只加独立函数）。 |

## 18. P1-T04 — Project Profile 选择与基础 Glossary

- **Task 编号：** P1-T04
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** completed（M01–M05 completed，2026-08-07）
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
| P1-T04-M01 | **Project Profile 选择（completed，2026-08-07）：** Reality Check **ADAPT**——现场复用 `ModelProfileService`/`ProviderConnectionService` CRUD（不重写）；`005`/`006` FK RESTRICT 与 `profile_snapshot` 历史快照 seam 齐备，唯一缺口是 `projects` 无 active 字段、`delete_profile` 对 RESTRICT 抛不透明 `SqlExecutionError`。新增 `009_add_project_active_profile.sql`：`projects.active_profile_id`（可空，FK `model_profiles(id) ON DELETE RESTRICT`，`projects.schema_version` 保持 1）；`Project` 领域模型加 `active_profile_id`/`ProjectError`/`with_active_profile`；`ProjectRepository` 读写新列并新增 `list_by_active_profile`；`ProjectService.select_active_profile`/`clear_active_profile`（预检 project/profile 存在给 `ProjectError`）；`ModelProfileService.delete_profile` 删除前预检——被 Project active 引用或历史 `segment_attempts.model_profile_id` 引用 → `ModelProfileInUseError`（区分两类、给出项目名/引用计数），FK RESTRICT 兜底，未引用删除与缺失返回 False 语义不变；`SegmentAttemptRepository.count_by_model_profile`。新增 `tests/test_p1_t04_m01.py` **18 项**（新建默认无 active、select/更换/clear 重开恢复、clear 幂等、跨 Project 隔离、缺失 project/profile 明确错误、仓库缺项目 ValueError、被 Project active 删除明确错误含项目名（含两 Project 共享列出双名）、被历史 Attempt 引用删除明确错误、clear 后释放删除保护、未引用可删、DB 级 FK 兜底、旧库(001-008)升级 009 加列 NULL + 升级后可选）。受影响旧测试子集 393 passed + 全量 pytest **1129 passed**（基线 1111 + M01 18，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 108 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX，见 `08` §8）。 |
| P1-T04-M02 | **Project-scoped Glossary（completed，2026-08-07）：** Reality Check **ADAPT**——`04` §3 已列 `glossary_entries` schema、`05` §4/5 已裁决 locked 注入按 priority+稳定次序、`07` §18 硬约束（Project 隔离/source·target 非空/scope·priority 稳定验证/V1.0 只注入 locked）与执行 Agent 自决（同词唯一域/priority 数值范围）齐备，故 **DEC-P1-T04-GLOSSARY 不触发**（priority 语义已裁决+范围已委托；重复词唯一域已委托+要求明确结果且不污染；scope 是用户可编辑分类标签、M03 注入不用 scope 过滤）。新增 `010_add_glossary_entry.sql`（`glossary_entries`：project_id FK CASCADE、source_term、target_term、scope、priority 0-100 默认 50、is_locked 0/1 默认 0、origin ('user','import')、UNIQUE(project_id, source_term)、索引 (project_id, priority)）；`domain/glossary_entry.py`（`GlossaryEntryError` + `GlossaryEntry`，strip 归一化 + 非空/范围/布尔/受控 origin 校验，非字符串给明确错误）；`infrastructure/repositories/glossary_entry_repository.py`（save/get_by_id/find_by_project_and_source/list_by_project(priority DESC, id)/list_locked_by_project/delete）；`application/glossary_service.py`（`GlossaryService`：create/update/get/list/locked/delete，构造跑 migration，create/update 前预检 project 存在 + 同 Project source_term 重复给明确错误，DB UNIQUE 兜底，`__init__` 迁移失败关闭连接）。新增 `tests/test_p1_t04_m02.py` **36 项**（旧库(001-009)升级 010 建表/数据保留/升级前无表、DB 级 UNIQUE+CHECK 兜底、CRUD+重开+repository 直读、origin='import'、priority/id 排序、update 校验失败不污染、锁定切换、跨 Project 同词隔离与删除隔离、空/非法值（空 term/scope、priority 越界与非整数、is_locked 非布尔、origin 非法、负 id）、重复策略（同词拒绝无污染、空白归一化冲突、删后重加、update 冲突、自保 source_term 允许）、repository 直存重复 SqlExecutionError+回滚、缺 Project 预检）。受影响旧测试子集 442 passed（411 基线 + M02 36）+ 全量 pytest **1160 passed**（基线 1129 + 36，1 skipped）、Ruff clean、mypy 112 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX；MINOR 已处理：非字符串 term 防御 + service `__init__` 迁移失败关连接 + 5 项测试缺口补齐；其余记录取舍：负/零 id 经 service 报"Project does not exist"、预检非原子由 DB UNIQUE 兜底）。指针推进至 P1-T04-M03。 |
| P1-T04-M03 | **确定性 Prompt 注入（completed，2026-08-07）：** Reality Check **ADAPT**——现场核验 `ContextComposer.compose`（P0-T05-M03）已实现 glossary 候选 priority 归一化 1、邻居前选择、Manifest 记录 selected/pruned、预算不足对当前 Segment 抛 `ContextBudgetError` 不截断；`GlossaryService.list_locked_entries` → `GlossaryEntryRepository.list_locked_by_project`（`WHERE is_locked=1 ORDER BY priority DESC, id`）已提供确定稳定次序（M02）；唯一缺口是 `TranslationService.translate_segment` 调用 `compose` 未传 `glossary_candidates` 且无 `GlossaryEntry → ContextCandidate` 映射。**DEC-P1-T04-GLOSSARY 不触发**（priority 语义已由 `05` §5 裁决、scope 不参与注入过滤、重复词唯一域已委托——M02 已判定，M03 只接线不引入新决策）。**新增 `application/glossary_context.py`**：`build_glossary_candidates` 纯函数（`content = "{source_term} -> {target_term}"`、preserve 输入顺序、`segment_id = "glossary:{source_term}"`、`reason="locked glossary"`、metadata 带 entry_id/source_term/target_term/scope/priority/origin；共享 `default_estimate` 不复制估算逻辑，`estimate_method`/`estimator` 可注入）；`context_composer.py` 私有 `_default_estimate` 公开为 `default_estimate`（唯一引用更新，公共行为不变）。**`TranslationService`** 增持 `GlossaryEntryRepository`，`translate_segment` 查询 `run.project_id` 的 `list_locked_by_project` 经 `build_glossary_candidates` 传入 `compose(glossary_candidates=...)`，`close()` 关闭新 repository；不新建 Service/Manager、不新增依赖/schema、不改 composer 选择规则。新增 `tests/test_p1_t04_m03.py` **12 项**（映射单测 6：映射/保序/空/默认估算/自定义估算/元数据；注入垂直闭环 3：locked 按 priority+id 稳定次序先于邻居且跨 Project 隔离 + unlocked 不泄漏 + Manifest selected_sources/pruned_count 记录、同 priority 按 id 决胜、无 locked 项不注入回归；预算行为 2：低优先级 glossary 裁剪且当前源文不截断 + 超预算当前段抛 `ContextBudgetError` 且不发请求；composer 同 priority 平局 1：glossary 先于 distance-0 邻居）。受影响旧测试子集 **344 passed**（332 旧 + M03 12）+ 全量 pytest **1177 passed**（基线 1165 + 12，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 114 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX，见 `08` §8）。指针推进至 P1-T04-M04。 |
| P1-T04-M04 | **薄管理 UI（completed，2026-08-07）：** Reality Check **ADAPT**——现场核验 M01–M03 与 P0-T08-M05 UI seam 齐备（`ProjectService.select_active_profile`/`clear_active_profile`/`list_projects`、`GlossaryService` CRUD、`ModelProfileService.delete_profile` 预检 `ModelProfileInUseError`、`credential_status.report_credential_availability`、`ServiceWorker`/`WorkerPage` pytest-qt 模式）；唯一缺口：UI 无 active Profile 选择面、无 Glossary 管理面、Connection 删除对被引用抛不透明 `SqlExecutionError`、未消费凭据报告。ADAPT：(1) `ProviderConnectionService.delete_connection` 删除前预检——被任一 `model_profiles.provider_connection_id` 引用时抛新增 `ProviderConnectionInUseError` 并列出 profile 名（镜像 M01 `delete_profile` 预检先例，DB FK RESTRICT 兜底并发写，不重写 CRUD，缺失返回 False 语义不变）；(2) UI 落地于既有 `SettingsPage`（Connection/Profile 删除按钮 + 凭据可用性提示经 `report_credential_availability`，缺引用显示可操作 hint 永不泄 secret）与 `ProjectPage`（项目选择 `select_project(project_id)` 程序化入口、active Profile 选择/清除、Glossary 增改删/lock/priority/scope 表单），不新增顶层 Tab、不新建转发型 Service/Manager（沿用 `ServiceWorker`+`WorkerPage`），UI 不直接查库。新增 `tests/test_p1_t04_m04.py` **15 项**：active Profile 设置/清除/重开恢复、Glossary add→select 回填→update(priority/scope/lock)→delete round-trip、重复 source_term 与空 term 可操作验证错误且不污染、仅 locked 项可注入、被引用 Profile（active）删除可操作错误 + clear 后释放、被引用 Connection 删除可操作错误（含 profile 名）、未引用 Connection/Profile 删除成功、缺 env 凭据可操作 hint、available/无凭据不警告且 secret 不显、UI 模块不直接导入 repositories/sqlite（结构性守卫）、`ProviderConnectionInUseError` 服务层单测（列出 profile 名/未引用成功/缺失 False）、Add-Profile 连接下拉刷新保留选择（Review MINOR 已处理）。受影响旧测试子集 185 passed + 全量 pytest **1192 passed**（基线 1177 + M04 15，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 115 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX；MINOR 已处理：Add-Profile 连接下拉刷新保留选择 + 补测试；其余记录取舍：WorkerPage 单 pending-request 槽，见 `08` §8）。指针推进至 P1-T04-M05。 |
| P1-T04-M05 | **持久化/双形态/GUI Gate（completed，2026-08-07）：** Reality Check **ADAPT**——现场核验 M01–M04 落地（`select_active_profile`/`clear_active_profile`/`list_projects`、`GlossaryService` CRUD + `list_locked_entries`、`build_glossary_candidates` + `TranslationService` 注入、`ProviderConnectionInUseError` + `delete_connection` 预检、`SettingsPage`/`ProjectPage`/`select_project`）与 P1-T02-M05 双形态链路齐备；基线复现全量 pytest **1192 passed, 1 skipped**。唯一缺口：`009`/`010` 新增数据（`projects.active_profile_id`、`glossary_entries`）在双形态 round-trip 与同形态重启重开中的持久化证据——P1-T02-M05 的 round-trip 测试早于 P1-T04 编写，只断言 connection reference/profile/run/segments/attachments，未覆盖这两个新数据。**新增 `tests/test_p1_t04_m05.py` 2 项**：(1) `test_dual_form_round_trip_preserves_selection_and_glossary`——开放目录 -> `.aiproject` -> 隔离"第二台 Windows" -> 安装 -> 重开：`active_profile_id` 保留且指向正确 profile（按 id 精确断言，profile 行仍在）、glossary source/target/scope/priority/is_locked 逐字段保留、`list_entries` 稳定 `priority DESC, id` 次序保留、`list_locked_entries` 仅 locked 项可注入、凭据只存 `env:` reference、segments 存活；(2) `test_open_directory_reopen_preserves_selection_and_glossary`——同形态重启重开恢复 active Profile + Glossary。测试经 `create_open_directory_project`/`_checkpoint_clean`/`_refresh_manifest` 模拟"服务写库后重算 manifest"的生产 seam，单 Project 身份、零新依赖、无 src/migration 改动。受影响旧测试子集 **187 passed**（185 旧 + M05 2）+ 全量 pytest **1194 passed**（基线 1192 + 2，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 116 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX，实测删除 `select_active_profile` 或 glossary 创建即断言失败，证明不误报通过；MINOR 已处理：active profile 改按 id 精确断言；其余记录取舍：helpers 与 test_p1_t02_m05 同构重复、未断言 manifest `source_id`，见 `08` §8）。重启、Project 隔离、预算与 UI 回归由 M01–M04 套件 + 全量 pytest 覆盖（M03 预算裁剪/`ContextBudgetError`、M04 15 项 pytest-qt 薄管理 UI、P0-T08-M05 UI 闭环）。指针推进至 P1-T03-M01。 |

## 19. P1-T03 — 自动模式与工作台模式

- **Task 编号：** P1-T03
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** completed（M05 完成于 2026-08-08，P1-T03 全部里程碑通过）
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
| P1-T03-M01 | **自动模式最小旅程（completed，2026-08-07）：** Reality Check **ADAPT**——active Profile（`009`）、内置只读 Workflow（`TranslationRunService` seed + hash 防篡改）、ImportService 六格式、`TranslationWorker` 逐 Segment 循环、`TxtExporter` 与 P1-T04-M05 双形态持久化 seam 齐备；缺口是 mode 概念缺失、自动模式无"解析 active Profile"路径、缺配置无引导。DEC-P1-T03-OVERRIDE 不触发（属 M03）。新增 `011_add_project_mode.sql`：`projects.mode`（`NOT NULL DEFAULT 'auto'` + `CHECK ('auto','workbench')`，`schema_version` 保持 1，旧行回填 'auto'）；`Project` 加 `MODE_AUTO`/`MODE_WORKBENCH`/`SUPPORTED_MODES`/`mode` 字段/`with_mode()` 校验（非法 `ProjectError`），`create`/`with_active_profile`/`with_updated_name` 透传；`ProjectRepository` 读写新列；`ProjectService.set_mode`（预检 project + mode 校验）+ `get_project`；`TranslationWorker` 加 `start_translate_auto`/`config_missing`——worker 内 `ProjectService.get_project` 解析 active Profile，缺 active 发 `config_missing`（不建 Run、不发请求），异常兜底发 `failed`，否则复用既有 `translate` 循环（不复制 orchestrator）；`TranslationPage` 移除手动 Profile 组合框，Translate 走自动解析，加 mode/active-profile 状态标签 + 缺配置可操作引导（"设置 active Profile…"按钮 → `request_project_setup` → 切 Project Tab），active Profile 解析后自动隐藏引导；`ProjectPage` 加 `project_settings_changed` 信号（active 变更后刷新 Translation 页）。新增 `tests/test_p1_t03_m01.py` **15 项**（新 Project 默认 'auto'、set_mode 重开持久化、非法/缺失 project 拒绝、旧库(001-010)升级 011 回填 + 数据保留 + 历史记录、DB CHECK 兜底非法 mode、双形态 round-trip 保留 mode + active Profile、自动旅程 import→translate(解析 active)→progress→export、无 pending 重翻终态、缺 active Profile → config_missing + 无 Run + 引导可见 + 一键跳 Project Tab、恢复后引导自动清除、缺 project → config_missing、服务异常 → failed 不卡 UI、窗口重启后 mode/active Profile 仍解析可翻译）；`test_p0_t08_m05.py` 更新 helper（设置 active Profile——自动模式行为变化）。受影响旧测试子集 **83 passed**（68 旧 + M01 15，其中含 P1-T04-M01/M04/M05 与 project/migrations/UI）+ 全量 pytest **1209 passed**（基线 1194 + 15，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 117 files no issues；独立 Review 复核 2 SHOULD-FIX（引导未自动清除、`translate_auto` 异常未兜底会卡 UI）已修复并各补测试，零 pending 终态修复补测试，见 `08` §8。指针推进至 P1-T03-M02。 |
| P1-T03-M02 | **capability-aware 工作台（completed，2026-08-08）：** Reality Check **ADAPT**——现场核验 active Profile（`009`）、capability snapshot seam（`profile.get_capability()`/`compose_adapter`/`OpenAICompatibleAdapter.filter_params` 终滤）、`TranslationWorker.translate` 循环、`WorkerPage` pytest-qt 模式与 P1-T03-M01 自动模式齐备；缺口是 `translate_segment` 无参数透传、Attempt 快照无实际请求参数、无按文档 Attempt 只读、无工作台 UI 面。DEC-P1-T03-OVERRIDE 不触发（属 M03）。新增 `application/workbench.py`（`SegmentProgress`/`ParamSpec`/`presented_parameters`/`initial_param_values`，Qt-free 纯策略：只呈现 capability.supported_parameters、未知参数文本回退、`max_tokens` 钳制 capability.max_output_tokens）；`TranslationService.translate_segment(extra_params=None)`（缺省用 profile.default_params，参数作为该 Attempt 请求参数，`start_attempt(request_params=...)` 记录于 `profile_snapshot.request_params`——JSON 快照追加键，无 schema/migration 变更）；`SegmentAttemptRepository.list_by_document`（JOIN segments 限定列）+ `TranslationRunService.list_segment_progress(source_document_id)`（每 Segment 最新 Attempt 的 status/error + current_revision）；并发加固 `TranslationRunService._seed_builtin_workflow`（refresh 与 translate 两线程并发构造时捕获内置 workflow 唯一冲突、重读并校验 hash/read_only）；`TranslationWorker` 加 `start_translate_workbench(project_id, document_id, profile_id, params)` 复用既有 `translate` 循环（不复制 orchestrator）；`ui/workbench.py` `WorkbenchParamEditor`（每 capability 支持参数一个控件，float/int/bool 类型化、未知参数文本，`max_tokens` 上限钳制 capability.max_output_tokens，可注入 `initial` 保留草稿）；`TranslationPage` 工作台面（真实 Segment/Attempt 进度 QListWidget + Profile/capability 摘要 + 参数编辑器，仅 workbench 模式显示，auto 模式不变；`set_document` 触发 refresh；`_on_finished` 在 workbench 模式重读进度并保留参数草稿）。新增 `tests/test_p1_t03_m02.py` **20 项**（service：参数透传 + Attempt 快照记录、参数变更只影响下一 Attempt 不改历史 Revision、缺省用 profile.default_params、真实 adapter 过滤不支持参数不发送、`list_segment_progress` 无 Attempt/成功+失败/repair 多 Attempt 取最新；纯策略：presented 排序、initial 值/spec 默认、max_tokens 钳制、未知参数；widget：只呈现支持参数、max_tokens 编辑钳制、未知参数文本、`initial` 注入；pytest-qt：工作台显示真实进度+Profile+仅支持参数、翻译用编辑器值+快照+完成后进度刷新且草稿保留、auto 模式隐藏工作台、workbench 无 active Profile 引导）。受影响旧测试子集 **225 passed**（旧）+ 全量 pytest **1229 passed**（基线 1209 + M02 20，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 120 files no issues；独立 Review **无 BLOCKER**，1 SHOULD-FIX（max_tokens 编辑超 capability 上限会发出 provider 拒绝的请求）已修复并补测试，2 MINOR（完成后进度列表不刷新——已修 `_on_finished` 重读且保留草稿；多 Attempt 每段选择未测——已补 repair 测试）处理，见 `08`。另对 M01 既有 `test_auto_translate_service_error_emits_failed` 做测试加固（先连接 `finished` 再 emit，避免瞬间失败时信号先于连接发出）。指针推进至 P1-T03-M03。 |
| P1-T03-M02 | **capability-aware 工作台：** 显示真实 Segment/Attempt 进度和 Profile；仅呈现/发送支持参数，参数变更形成下一 Attempt 的快照，不影响已完成历史。 |
| P1-T03-M03 | **受控 Prompt Override（completed，2026-08-08）：** Reality Check **ADAPT**——现场核验 M02 落地（`WorkbenchParamEditor`/`translate_segment extra_params`/`start_attempt request_params` 快照/`list_segment_progress`/`start_translate_workbench`）与 Prompt 模板 seam（`PromptRenderer.render(template=...)`/`RenderedPrompt`/`template_version`/`output_contract`，`test_p0_t05_m04` 已证未知变量拒绝 + 输出契约不可移除）齐备；唯一缺口是预设模板无稳定身份/版本、override 无持久化/校验/渲染接入。DEC-P1-T03-OVERRIDE **不触发**——决策范围（编辑边界/拒绝规则/父版本失效策略）已由 `01` §16（预设不可修改、修改存为 Override）、`05` §2/§9（预设只读 + 父模板版本 + 不可关闭 Segment ID/输出包装/格式保护/校验/安全限制）、`07` §19 与 M03 目标文本（未知变量/失效父版本/边界移除拒绝、不执行模板代码）全部裁决，余下为可逆内部实现（`09` §7：私有文件组织/SQL 组织/校验机制/控件布局自主处理），与 P1-T04-M02/M03 先例一致。新增 `application/preset_templates.py`（`PresetTemplate` 注册表：`general` v1.0.0 = 既有默认模板文本，`ALLOWED_PLACEHOLDERS` = renderer 的 current/context/output_schema/source_language/target_language，`get_preset_template`/`current_preset`/`resolve_override_template`——父版本错配或持久化文本失效时 fail-closed 拒绝且重校验）；`domain/prompt_override.py`（`PromptOverrideError`/`PromptOverride`/`validate_override_template`——Qt-free，拒绝未知变量/非法 `$` 语法/空文本，`string.Template.is_valid()`+`get_identifiers()` 只做占位符替换、不执行模板代码）；`migrations/012_add_prompt_override.sql`（`prompt_overrides` 1:1 with profile，`UNIQUE(model_profile_id)`，FK `model_profiles(id) ON DELETE CASCADE`，`schema_version` 保持 1）；`infrastructure/repositories/prompt_override_repository.py`（save 先查后改/插不重复、get_by_profile/delete_by_profile）；`ModelProfileService.set_prompt_override`/`get_prompt_override`/`clear_prompt_override`（保存时 parent = 当前预设版本，未知变量拒绝不持久化）；`PromptRenderer` 默认模板改从预设注册表读取（行为不变）；`TranslationService.translate_segment` 有 override 时解析渲染、失效先于 claim 拒绝，`_context_summary` 追加 `override_parent_version` 供 Attempt 审计；`ui/workbench.py` 新增 `WorkbenchPromptEditor`（只读预设预览 + 可编辑拷贝 + Save/Clear 信号 + 草稿 `initial` 保留）；`TranslationPage` 工作台面接入 prompt 编辑器（`_refresh_task` 返回 4 元组含 override，save/clear 经 worker 线程调 service，错误经 status 显示）。新增 `tests/test_p1_t03_m03.py` **38 项**（预设注册表/renderer 默认一致/占位符对齐；领域校验未知变量/空/非字符串/非法 `$`/字面 `$` 需 `$$` 转义且报错含 `$$` 引导/父版本必填/正 id/with_text 重校验；repository save 更新同一行/删除/旧库(001-011)升级 012 保留数据+历史；service 保存/重开/清除幂等/未知变量不持久化/缺 profile/删除级联；渲染解析 stale 拒绝/篡改文本拒绝/输出契约始终追加/无 override 用预设；TranslationService override 进 prompt+审计标记/stale 不发请求不建 Attempt/无 override 无标记回归；widget 只读预览/override 种子/信号/草稿/stale 警告；pytest-qt 工作台显示 prompt 编辑器/保存持久化+状态/未知变量错误+不持久化/清除回预设+按钮态/stale 覆盖刷新后显示警告）。受影响旧测试子集 **322 passed**（含 M01/M02 全绿）+ 全量 pytest **1267 passed**（基线 1229 + M03 38，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 124 files no issues；独立 Review **无 BLOCKER**，2 SHOULD-FIX 已修复并补测试（stale override 在 UI 不可见——工作台 prompt 编辑器在父版本错配时显示"no longer matches current preset"警告并保留 Clear 恢复路径；字面 `$` 报错无 `$$` 引导——错误消息改为提示以 `$$` 转义字面美元），见 `08`。指针推进至 P1-T03-M04。 |
| P1-T03-M03 | **受控 Prompt Override：** 预设只读，override 记录 parent version 并可重开；未知变量、失效父版本和试图移除输出/格式/校验边界时拒绝，不执行模板代码。 |
| P1-T03-M04 | **人工 Revision 与锁定（completed，2026-08-08）：** Reality Check **ADAPT**——现场核验 M03 落地与 Revision/lock seam（`TranslationRevision.origin ∈ {ai,user,import}` + `is_locked` 在 `006` 即定义，`finalize_success` 已校验 current 未变 + 非 locked，`recover_expired_leases` 对 locked current 转 completed 不重建，exporter 默认读 current + `revision_overrides` 显式选择）；唯一缺口是工作台编辑追加 user Revision、lock/unlock、切换 current 的 use case 与 UI 编辑面。新增 `TranslationRunService.append_user_revision`（单事务 INSERT origin=user Revision + `UPDATE segments SET status='completed', current_revision_id=?, version=version+1 ... WHERE status != 'processing'`，processing 段拒绝，version bump 使 stale claim 失效）、`set_current_revision`（切换到任一属于该 segment 的有效 revision，拒绝 processing 并校验归属）、`lock_current_revision`/`unlock_current_revision`（单条 `UPDATE ... WHERE id=(SELECT current_revision_id FROM segments WHERE id=?)` 原子切换 `is_locked`，无新 migration）；`SegmentProgress` 增 `revision_text`/`revision_locked`（`list_segment_progress` 经 `get_many_by_ids` 填充，向后兼容）；`ui/workbench.py` 新增 `WorkbenchRevisionEditor`（只发信号：source 只读 + 译文可编辑 + Save/Lock/Unlock），`TranslationPage` 工作台接入（选中重建、Save/Lock/Unlock 经 ServiceWorker 线程调 service、刷新恢复选中并 `initial` 保留草稿）。锁定保护由既有 seam 兜底：`finalize_success` 拒绝 locked/current 已变的迟到自动结果、`recover_expired_leases` 对 locked current 转 completed 不重建、auto worker 只翻译 pending 段（append/set 置 completed 后不再被 claim）——自动迟到结果和重译不能覆盖 locked current；导出遵循选择语义（默认 current、`revision_overrides` 显式历史、逐项校验归属）。新增 `tests/test_p1_t03_m04.py` **21 项**（append user 成为 current + 保留 ai 历史 + 缺段/processing 拒绝 + 空文本；set_current 切换历史/跨段拒绝/缺 revision 拒绝/processing 拒绝；lock/unlock + 无 current 拒绝 + 缺段拒绝；finalize 拒绝 locked current + auto 重译跳过 completed locked 段（无新 request）+ recover 对 locked current 转 completed 不重建 + recover 对未锁 user current 回 pending（崩溃边界固化）；导出默认 locked user current + override 选历史不改变 current；pytest-qt 编辑保存 user revision + lock/unlock + 草稿跨 refresh 保留）。受影响旧测试子集 **413 passed** + 全量 pytest **1288 passed**（基线 1267 + M04 21，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 125 files no issues；独立 Review **无 BLOCKER**，1 SHOULD-FIX（草稿保留死代码——`set_revision` 无条件覆盖 `initial`）已修复并补测试，MINOR 已处理（lock TOCTOU 原子化、补 recover-unlocked-user-current 边界测试），MINOR 记录取舍（UI 暂无历史 revision 切换入口，`set_current_revision` 服务层可用、归 M05 或后续），见 `08`。指针推进至 P1-T03-M05。 |
| P1-T03-M05 | **模式切换与 GUI Gate（completed，2026-08-08）：** Reality Check **ADAPT**——现场核验 M01–M04 落地与 seam（`projects.mode`/`011`/`ProjectService.set_mode/get_project`、`TranslationWorker.translate_auto`/`translate_workbench` 共用 `translate` 循环 + `request_stop` 取消 + `finish_run(cancelled)`、`MainWindow.closeEvent` `_shutdown_workers` request_stop + 有界 wait、`list_segment_progress`、`SegmentRepository.list_source_documents_by_project`）；唯一缺口是模式切换 UI 不存在（`set_mode` 无调用方）、运行中切换无提示、TranslationPage 无文档列表且切换 Project 后保留旧 `_document_id`（M01 已知边界）、重启后文档/结果/锁定证据缺位。DEC-P1-T03-OVERRIDE 不触发（属 M03 已裁决）。**ADAPT（范围内可逆调整，硬约束/验收不变，不创建第二套 orchestrator/状态机）**：(1) `TranslationPage` 新增交互模式选择器（Auto/Workbench `QComboBox`）——经 `ServiceWorker` 调 `ProjectService.set_mode` 持久化；运行中（`_set_running` 集中管理 `_running` 与 Translate/Cancel/Export/文档选择器按钮态）激活切换被拒绝并提示"finish or Cancel"、选择器恢复当前持久化 mode（运行中 Run 不原地改变 Profile/Workflow/参数）；`set_mode` 成功路径同步 `_mode` 再 refresh（refresh 失败不致 UI/DB 失同步）。(2) 新增每 Project 文档选择器——`TranslationRunService.list_source_documents(project_id)`（只读转发，UI 经 Application Service 不违反结构性守卫）供 `_refresh_task` 填充组合框；有效文档逻辑：提交时捕获的当前文档属于该 Project 则沿用、否则清空（不做自动选中，消除跨 Project 陈旧 `_document_id`；无有效文档时组合框不高亮首项）；`_on_document_selected` 重读进度，运行中文档切换同样被拒绝。(3) `_refresh_task` 捕获 `current`/`project_id` 于主线程提交时、任务体只读不可变属性（无跨线程 UI 访问）。(4) 取消/关闭/重启门禁由既有 seam 承载（`request_stop` Segment 边界取消、closeEvent 有界 wait 收敛、共享 SQLite 载体重开自动恢复 mode/active/文档/结果/锁定）。新增 `tests/test_p1_t03_m05.py` **10 项**（service：`list_source_documents` 按 Project 有序/隔离；pytest-qt：模式切换持久化 + 工作台面显隐 + 选择器同步、运行中切换拒绝并恢复、无 Project 切换报错 + 选择器恢复、workbench 无 active Profile 引导（主线程同步、无 Run 无请求）、workbench 取消 + Run cancelled、workbench 关闭收敛无 processing + Run cancelled + Attempt 全终态、重启保留 mode/active/文档选择器/翻译结果/锁定 Revision、跨 Project 切换重置文档上下文 + 组合框重选加载、运行中文档切换被拒绝 + 选择器锁定）。受影响旧测试子集 **461 passed**（M04 子集 413 + P1-T03-M04/P1-T04-M04/M05 关联）+ 全量 pytest **1298 passed**（基线 1288 + M05 10，1 skipped 因本环境无符号链接创建权限）、Ruff clean、mypy 126 files no issues；实际可用性 smoke：真实窗口启动 + 驱动完整旅程（建 Project/active Profile/导入/切 workbench/文档选择/workbench 翻译/切回 auto/窗口关闭收敛）SMOKE PASS；独立 Review **无 BLOCKER**，2 SHOULD-FIX 已修复并补测试（运行中文档切换无守卫——选择器运行中禁用 + `_on_document_selected` 拒绝并补测试；set_mode 成功但 refresh 失败 UI/DB 失同步——成功路径同步 `_mode`），MINOR 已处理（组合框无有效文档时不高亮首项、`_on_translate` 加 `_running` 守卫、refresh None 清空陈旧文档状态），MINOR 记录取舍（Project 切换后不自动选中文档，需从选择器显式选择；workbench 缺 active 主线程同步短路由与 auto 的 worker 长路由差异），见 `08`。P1-T03 全部 M01–M05 完成，Task 标记 **completed**。 |

## 20. P1-T05 — V1.0 异常恢复与 Release Candidate Gate

- **Task 编号：** P1-T05
- **Phase/Release：** Phase 1 / V1.0
- **Priority：** P0
- **状态：** completed（M01–M05 completed，2026-08-08——可恢复 Git 基线 `3ef991d` 已于 2026-08-08 经用户授权形成；M04 候选构建于 `dist/`；工作树改动与候选均未提交/推送。对外发布仍等待用户单独授权：杀毒扫描需用户 AV 环境执行、冻结 GUI 最终手工 smoke 需用户授权发布时执行）
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
| P1-T05-M01 | **冻结可判定矩阵（completed，2026-08-08）：** Reality Check **FIT**——现场核验 P1-T03/P1-T04 全链路落地与基线复现（pytest 1298 passed/1 skip、Ruff clean、mypy 126 files）一致；环境实测 Python 3.12.10 / Windows 11 Pro 10.0.26100 / AMD64。**DEC-P1-T05-RELEASE 不触发**（打包工具 PyInstaller 已 smoke 验证并被 `03` §10 定首选；支持环境 Windows 11 x64 唯一确定；lockfile 形式属可逆内部实现）。交付：(1) `03` §12 新增 V1.0 Release Gate 冻结矩阵——判定原则（布尔 Gate、不把"执行过"当通过）、支持环境（Windows 11 build≥22000 x64、Python 3.12、绿色版可写数据目录）、依赖锁定（`requirements.lock` = pip freeze 快照排除 transrealm/pip，与 pyproject 一致且等于安装版本；更新规则）、质量命令表（pytest/ruff/mypy/verify_task.py/check_candidate_hygiene.py 及期望状态）、公共矩阵规范（fixture/允许重复调用/零数据损失/证据位置）、P0/P1 release-blocking 等级；(2) `requirements.lock`（24 项精确版本，含 PySide6 6.11.1、pytest 9.1.1、pytest-qt 4.5.0、ruff 0.16.0、mypy 2.3.0、pyinstaller 6.21.0）；(3) `tests/test_p1_t05_m01.py` 7 项——锁文件存在/格式/排除 transrealm 与 pip、锁版本==安装、锁满足 pyproject runtime+dev 范围、dev/打包工具链入锁、支持环境 Windows 11 build≥22000+x64+py3.12。全量 pytest **1305 passed**（基线 1298 + M01 7，1 skipped 本环境无符号链接创建权限）、Ruff clean、mypy 127 files no issues；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER，1 SHOULD-FIX Windows 11 build 判定已修复，MINOR 2/4 已处理、3/5 记录取舍）见 `08`。**基线已形成（2026-08-08 用户授权本地 commit `3ef991d`，78 files，未 push）：P1-T05 前置"工作树先形成可恢复 Git 基线"满足，M02 ready。** |
| P1-T05-M02 | **翻译/恢复/长文本 Gate（completed，2026-08-08）：** Reality Check **ADAPT**——验证型 Gate，目标/硬约束/验收不变；现场核验（全量 pytest 1305 passed/1 skip、Ruff clean、mypy 127 files 复现一致）：T07 lease/fencing/recover/retry seam（P0-T07-M05 服务级崩溃矩阵）、T08 生产 transport + 本地 ThreadingHTTPServer（超时/断连/截断→timeout/connection_error 均 retryable，`compose_adapter` 可注入）、`TranslationService` 旅程编排（`SimulatedCrashError` 透传）、`TranslationWorker` 逐 Segment 循环 + `request_stop` 边界取消、locked/current fencing（P1-T03-M04/T07-M05）齐备。**DEC-P1-T05-RELEASE 不触发**（本 M 不涉及打包/支持环境/lockfile）。交付 `tests/test_p1_t05_m02.py` **11 项**：旅程级（TranslationService + 真实 adapter + 本地 server）覆盖请求切点（claim 后请求前崩溃→lease 回收、请求中断网 connection refused→connection_error retryable、响应写中途截断→connection_error retryable、model-stop/挂起→timeout_error retryable）、事务切点（finalize 三写入点 CrashInjector 崩溃回滚→lease 回收）、恢复语义（retry_failed 重排在新 run 中成功、locked current 不被自动覆盖、completed 重译被 not-pending 拒绝且外部调用次数不变）；固定长文本 fixture = 模块级 `_LONG_TEXT`（120 行 / 21,743 字符），计数式本地 server 逐 Segment 回显，完整旅程（import→translate→restart→recover→export round-trip），资源基线（tracemalloc 峰值 / perf_counter 耗时 / Segment 数 / 外部调用次数）打印为 `LONG_TEXT_RESOURCE_BASELINE` 并写 JSON 证据，只记录不虚构阈值（`02` §3）；实测 120 calls / 120 segments / ~3.0s / ~2.5MB peak。lease/retry/cancel/locked 服务级矩阵与 GUI 取消/关闭/重启门禁复引既有 nodeid（verify_task --baseline-test：P0-T07-M05/P0-T08-M02/P0-T08-M03/P0-T08-M05/P1-T03-M04/P1-T03-M05/P1-T05-M01，101 passed）。全量 pytest **1316 passed**（基线 1305 + M02 11，1 skipped 本环境无符号链接创建权限）、Ruff clean、mypy 128 files no issues、verify_task exit 0（outside_scope 空）、check_candidate_hygiene passed；独立 Review **APPROVE**（无 BLOCKER/SHOULD-FIX；MINOR 处理：platform.python_version 诚实记录、误导注释修正、补 mid-response 截断旅程测试；MINOR 记录取舍：资源基线证据临时性、超时测试余量、私有属性耦合、connection-refused 为"断连"主切点）见 `08`。fixture/允许重复调用/证据位置已同步 `03` §12.5。 |
| P1-T05-M03 | **格式/迁移/Project 双形态/security Gate（completed，2026-08-08）：** Reality Check **ADAPT**——验证型 Gate，目标/硬约束/验收不变，不新增产品能力；现场核验（全量 pytest 1316 passed/1 skip、Ruff clean、mypy 128 files 复现一致）：六格式 parser+`FidelityExporter` seam 齐备（TXT/JSON/SRT/VTT/ASS/SSA）、旧库 migration 备份（`test_migrations.py` 矩阵 + `migrate_container`）、开放目录/`.aiproject` 跨机/tamper/path/resource-limit（P1-T02-M01..M05）、secret 不泄（P0-T08-M02/P1-T02-M02/M05 + `check_candidate_hygiene`）、失败隔离（P1-T01-M01..M05 `TestFailuresDoNotPollute`）均已存在，M03 只补旅程级复合证据。**DEC-P1-T05-RELEASE 不触发**（本 M 不涉及打包/支持环境/lockfile）。交付 `tests/test_p1_t05_m03.py` **15 项**：六格式 golden 固定 fixture（模块常量，`test_golden_fixtures_are_fixed_and_recorded` 断言精确字节大小 + sha256 防漂移，段数 txt 3/json 3/srt 2/vtt 2/ass 1/ssa 1）+ 单一 Project 导入全部六格式 no-op 导出逐字节一致 + 每段 `append_user_revision` 后导出仅改目标 span（字幕时间轴/结构保留）且 round-trip 可重导入 + 单格式缺载体/不可写失败不影响其余五格式与 DB（backfill 后可恢复）；旧库（001-007 带真实数据）迁移至最新 pre-upgrade 备份先于 008 且可打开、用备份替换活库重开数据保留且回到 008 前 schema、再向前迁移可打开（演练文档中的恢复步骤）、备份失败阻断迁移（历史仍仅 001-007）；六格式容器跨机 round-trip（开放目录 → `.aiproject` → 第二台机 → 安装 → 重开）六格式 fidelity carrier + segments + 连接只存 `env:` 引用 + profile + manifest `source_id` 追踪；篡改 hash/越界 `..`/超限额归档均在目标落地前拒绝且 staging 无产物；`src`/配置内容扫描无硬编码凭据、archive/目标只含引用永不泄 secret；失败隔离（无 revision 导出失败不写目标、补 user revision 后可导出；各段 status/current revision 全可解释）。受影响旧测试子集 **699 passed**（684 旧 + M03 15，1 skipped 本环境无符号链接创建权限）+ 全量 pytest **1331 passed**（基线 1316 + 15，1 skipped）、Ruff clean、mypy 129 files no issues、verify_task exit 0（baseline 684 + new 15，outside_scope 空）、check_candidate_hygiene passed；独立 Review **APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX；MINOR 已处理：补 traversal 越界用例、死代码循环清理、`"Hello world" not in out` 收窄到实际含该串的字幕格式、防漂移守卫由字节大小升级为大小+sha256；MINOR 记录取舍：secret 负向断言针对从未落盘的串平凡成立（真实断言是引用只存 `env:`，强证据在 P1-T02-M02/M05）、hash 防漂移仍未防同尺寸内容替换——与 M02 单向漂移取舍一致）见 `08`。fixture/允许重复调用/证据位置已同步 `03` §12.5。指针推进至 P1-T05-M04。 |
| P1-T05-M04 | **Windows 绿色版候选（completed，2026-08-08）：** Reality Check **FIT**——现场核验（全量 pytest 1331 passed/1 skip、Ruff clean、mypy 129 files 复现与交接一致；锁定环境 Python 3.12.10 / PyInstaller 6.21.0 / PySide6 6.11.1 均等于 `requirements.lock`）打包 seam 齐备：迁移目录经 `Path(__file__).parent.parent / "migrations"` 解析需 `--add-data`（P0-T08-M06 已知）、入口 `transrealm.ui.main_window:main`、无既有 `.spec`/构建脚本。**DEC-P1-T05-RELEASE 不触发**（打包工具/支持环境/lockfile 已由 M01 裁决；本 M 只执行构建与验证）。交付：新增 `run.py`（PyInstaller 入口脚本）+ `scripts/build_release.py`（从锁定环境构建 onedir+zip+`build_manifest.json`：记录 tool/version/git/hash/size、校验 12 迁移与 Qt 平台插件、生成 `transrealm-0.1.0-win-x64.zip`）+ `tests/test_p1_t05_m04.py` **4 项**（构建工具不变量、manifest-artifact 一致+冻结 12 迁移+Qt 平台插件、绿色 artifact 无用户数据、**冻结候选 unzip→launch→数据目录→12 迁移→WM_CLOSE 优雅退出→数据完好→删除程序目录不删外置数据**完整 smoke）。实测候选：`dist/transrealm-0.1.0-win-x64.zip` 51,676,076 字节 / sha256 `c59b3ebbe2fe3d4d139fd787a6df28bfad18256274d974658375bcbe9fb5ae44`、onedir 128,322,729 字节、exe sha256 `cffc576f1a026c26d347620c67582ce78d46f49b7dee2e93484fc275bc78a728`、PyInstaller 6.21.0、git `110dea9`（worktree dirty=M03 未提交）、12 迁移、Qt 插件 8 类（generic/iconengines/imageformats/networkinformation/platforminputcontexts/platforms/styles/tls）+ `platforms/qwindows.dll`；冻结应用独立手动核验 0.61s 内启动出窗口 + 12 迁移 + 12 业务表、WM_CLOSE 优雅退出数据完好。**杀毒扫描未覆盖**（本机 Windows Defender 实时保护禁用 `AntivirusEnabled=False` 且非管理员，`MpCmdRun -Scan -ScanType 3` hr=0x80004005 Product/Feature disabled——如实记为未覆盖项，需用户在 AV 环境扫描候选后归档）。全量 pytest **1335 passed**（基线 1331 + M04 4）、Ruff clean、mypy 130 files no issues、verify_task exit 0（baseline 136 + new 4）、check_candidate_hygiene passed；独立 Review **无 BLOCKER**，2 SHOULD-FIX 已修复并补测试（green artifact 被 `make_archive(root_dir=dist)` 污染——含 `.work/` 构建残留、陈旧 `build_manifest.json` 与 758B 自引用截断嵌套 zip 条目，改 `base_dir="transrealm"` 只打 onedir，zip 51.7MB 且顶层仅 `transrealm/`；纯净性测试原仅查数据后缀，强化为"顶层仅 onedir + 无 `.work/`/嵌套 zip/陈旧 manifest"，并补 PID 窗口定位（`EnumWindows`+`GetWindowThreadProcessId`）、`WM_CLOSE` 后 `returncode==0`、manifest zip hash/size 校验）见 `08`。指针推进至 P1-T05-M05。 |
| P1-T05-M05 | **文档与最终 Sign-off（completed，2026-08-08）：** Reality Check **FIT**——文档交付型 Milestone，现场核验（Git 状态、M04 候选证据 `dist/build_manifest.json` 与 zip sha256/size 一致、M01–M03 矩阵）无产品代码改动。交付：新增 `docs/` 用户文档（`user-guide.md` 安装/使用/模式/Profile/Glossary/导出/清理、`data-safety.md` 迁移/备份/恢复/回滚/凭据、`known-issues.md` 候选已知问题与未覆盖项、`third-party-licenses.md` 24 项依赖许可取自冻结环境元数据与 `requirements.lock` 对应）+ `README.md` 用户文档小节 + `tests/test_p1_t05_m05.py` **4 项文档一致性守卫**（文档存在非空、README 链接、数据目录与 `main_window.py` 一致、known-issues zip sha256/版本与 `build_manifest.json` 一致，缺候选 skip）。**未覆盖项承接 M04（如实记录不标通过）：** 杀毒扫描需用户 AV 环境执行；冻结应用内 create/import/translate/export 的最终手工 smoke 需用户授权发布时执行。全量 pytest **1339 passed**（基线 1335 + M05 4，1 skipped 本环境无符号链接创建权限）、Ruff clean、mypy 131 files no issues、verify_task exit 0（baseline 7 + new 4，outside_scope 空）、check_candidate_hygiene passed；独立 Review 首轮 **REQUEST-CHANGES**（1 SHOULD-FIX 导出条件措辞——实际 exporter 要求每个段都有 current revision、任一缺失整体失败，"至少一个"是误导，已在 user-guide/known-issues 统一改为"每个段"）+ MINOR（格式计数/工作树表述/测试脆弱点）全部修复，复核 **APPROVE**（无 BLOCKER/SHOULD-FIX/MINOR）见 `08`。P1-T05 全部 M01–M05 完成，Task 标记 **completed**（对外发布仍等待用户单独授权）。 |
