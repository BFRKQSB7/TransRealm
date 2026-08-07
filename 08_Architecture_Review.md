# 译境 / TransRealm
# Architecture Review V3

版本：V1.0

状态：正式架构审查文档

---

# 1. 文档目的


本文档用于记录：

- 项目架构风险；
- 重要技术决策；
- 设计取舍；
- 未来可能导致重构的问题。


本文档不是：

- 开发说明；
- 功能需求；
- Task列表。


---

# 2. 架构审查原则


所有重大设计必须考虑：

```
实现难度

+

长期维护成本

+

用户实际收益

+

AI开发可控性
```


禁止：

为了增加功能数量而增加复杂度。


---

# 3. 当前项目总体评价


项目目标：

开发一个：

```
本地AI翻译

+

在线API翻译

+

轻小说/文本翻译优化

+

专业翻译工作流

+

长期可扩展平台
```


---

当前架构方向：

合理。


原因：

- 模型接口独立；
- 数据保存独立；
- 翻译流程模块化；
- 支持未来扩展。


---

主要风险：

```
智能功能过早复杂化
```


尤其：

- RAG
- Translation Memory
- Workflow
- Context管理


---

# 4. 核心架构风险


# 4.1 过度设计风险


## 问题


当前规划包含：

- 多模型支持；
- 本地模型；
- 在线API；
- RAG；
- TM；
- 世界状态；
- 工作流；
- 插件；
- 模型管理。


接近商业软件规模。


---

## 决策


采用：

```
核心功能优先
+
高级功能后置
```


开发顺序：


```
基础翻译

↓

稳定保存

↓

质量增强

↓

智能工作流

↓

生态扩展
```


---

# 4.2 RAG系统风险


## 原目标


利用：

- 世界状态；
- 剧情摘要；
- 角色信息；
- 历史翻译。


提高一致性。


---

## 风险


本地翻译模型：

可能存在：

- 上下文理解有限；
- 信息过多导致注意力分散；
- Prompt过长降低翻译质量。


---

## 架构决策


RAG核心不是：

“提供更多信息”。


而是：

“筛选最相关信息”。


---

信息优先级：

| 信息 | 优先级 |
|-|-|
| 人物名称 | 极高 |
| 人物性别 | 极高 |
| 固定术语 | 极高 |
| 人物关系 | 高 |
| 当前场景 | 中 |
| 长剧情历史 | 低 |


---

# 4.3 Translation Memory风险


## 问题


自动复用翻译容易产生：

- 错误套用；
- 上下文错误；
- 人物关系错误。


---

## 架构决策


TM采用三级策略。


---

## 一级：确定复用


例如：

```
固定UI文本

固定术语
```


自动使用。


---

## 二级：AI判断


AI进行：

```
相似度

+

上下文

+

角色信息
```


评分。


---

## 三级：人工确认


重要内容：

用户确认。


---

# 4.4 Context Budget Manager风险


## 问题


如果直接加入：

```
原文

+

世界状态

+

RAG

+

TM

+

角色

+
用户Prompt
```


可能导致：

模型注意力下降。


---

## 架构决策


Context管理必须存在。


第一版本：采用规则式最小 Context Budget，并作为 Phase 0 内核能力。


例如，Phase 0 默认：

```text
当前 Segment
+
必要相邻 Segment
+
已存在且用户锁定的 Glossary（可选）
```

Phase 2 在数据存在并启用后加入：

```text
Character Data
+
RAG
+
TM
+
World State
```


---

# 5. 模型适配架构


## 问题


不同模型能力不同。


例如：

Sakura：

翻译优化。


Murasaki：

特殊思维链。


通用LLM：

理解能力强。


---

## 错误方案


所有模型使用同一个Prompt。


---

## 正确方案


采用：

Model Profile。


结构：


```
models/

├── general

├── sakura

├── murasaki
```


每个Profile保存：

- Prompt模板；
- 参数建议；
- 输出规则。


---

# 6. 文件格式支持策略


## 风险


复杂格式开发成本高。


---

## 决策


分阶段。


## V1.0

支持：

```text
TXT
JSON
SRT
ASS
SSA
VTT
```

## 远期

支持：

```text
Markdown
EPUB
HTML
Word
Ren'Py
```

具体排期以 `02_Development_Roadmap.md` 的唯一格式矩阵为准。


---

# 7. 数据库架构


## 当前方案


SQLite。


---

## 评价


适合当前目标。


原因：

- 单用户；
- 绿色版；
- 易迁移；
- 易备份。


---

## 注意


数据库结构变化：

必须：

- 版本管理；
- 数据迁移。


禁止：

直接修改旧字段。


---

# 8. 项目文件设计


## 目标


支持：

- 本机继续翻译；
- 复制到其他电脑；
- 单用户离线备份和项目转交。

不支持多人并发编辑、在线同步或自动冲突合并。


---

## 决策


采用：

项目文件。


包含：

```
配置

数据库

翻译状态

用户设置
```

P1-T02-M02 落地取舍：`.aiproject` 是开放目录的归档视图（同一 manifest/schema/hash 契约），采用标准 ZIP + `manifest.json` + 一致性 snapshot + 声明附件，内部 relpath 与 manifest 一致，解包即开放目录。数据库经 SQLite backup API 生成一致性 snapshot，不直接复制活动数据库（WAL 期间也一致）。零/多 Project 明确拒绝（契约允许"拒绝或隔离 snapshot"二选一；拒绝更简单、可测试，隔离 snapshot 可后置）。导出经临时 staging 构建一致容器并自校验后再 zip 原子写，失败不留下半成品。secret/log 结构化排除（只含受控条目，数据库只存 credential reference）。该取舍记录于 `03` §3、`04` §7。

P1-T02-M04 落地取舍：开放目录容器与 M03 staging 共用一条"备份 → 向前 migration → Project 验证 → 成功才安装/打开"链路，落地为 `migrate_container`（就地）与 `install_staging_to_target`（安装）。关键取舍：(1) 迁移后容器内瞬时 pre-upgrade 备份与 WAL 附属被清理、manifest 重算，容器只含受控条目；就地迁移失败时保留 pre-upgrade 备份作恢复物，安装失败时源归档/`.pre-replace` 备份作恢复物——不删除用户既有数据。(2) 修复 M01 已知边界"打开旧 schema 开放目录会经 `ProjectService` 迁移并留 stale manifest + 残留 `.bak`，二次打开 hash mismatch"：迁移后先关闭连接触发 WAL checkpoint，再清理并重算 manifest，再复验。(3) `ManifestInfo` 增可选 `source_id`（导入安装时记录源 Project id 供追踪）；Project ID 冲突以"新容器本地身份 + manifest `source_id` 追踪"落地，不重写 `projects.id`（受 FK CASCADE 约束，重写会级联破坏数据）。(4) 名称冲突以确定性后缀建议名（如 `Alpha (2)`），未经 `confirm_overwrite` 不覆盖既有 Project；确认覆盖把既有目标移为 `.<target>.pre-replace-<ts>.bak` 恢复备份再安装、失败还原（还原失败时错误点名恢复备份路径）。(5) 清理顺序为"先重算并写 manifest、最后删 pre-upgrade 备份"，使 manifest 写失败时备份仍在作恢复点。(6) 打开/迁移路径在 `open_open_directory_project` 与 `migrate_container` 间有少量重复的"校验→迁移→清理→重算"编排（两处返回类型不同且分别持有 service 生命周期，为避免 install↔open 循环导入未强行合并）。已知边界：开放目录 manifest 只在 create/export/migrate/install 时重算，直接改库后不重算会使下次打开 fail-closed（M01-M03 既有契约，非 M04 回归）。独立 Review（2026-08-07）无 BLOCKER；2 SHOULD-FIX（清理顺序、install 恢复失败链错误并点名恢复备份）已修复并补测试；MINOR 记录取舍：不支持版本目标在安装时以"目标非空且非项目容器"报错（fail-closed 但掩蔽真实原因）、post-migration 读失败时容器保留 pre-upgrade 备份需手动恢复、目标只读检查不做 sidecar purge（避免改动既有目标）。该取舍记录于 `03` §3、`04` §7。

P1-T02-M05 落地取舍（跨机器与双形态 Gate，2026-08-07）：Reality Check **ADAPT**。M01–M04 全链路 seam 齐备且各段有单测，M05 是验证门禁：跨机 round-trip 以独立临时根模拟"另一台 Windows"（只有 `.aiproject` 跨边界，不真调远程/付费服务），核心状态/附件跨机保留、旧 schema 归档在目标机迁移、WAL 未提交不跨机、tamper/资源限额/目标冲突均目标落地前失败。新添"缺凭据可操作提示"应用层只读表面（`04` §7 契约）：`credential_reference_is_available`（env: 变量存在且非空 / wincred 凭据存在且非空，只读，从不返回 secret）与 `report_credential_availability`（按连接列出引用/available/hint，跳过无引用连接）。关键取舍：(1) 空值/空 blob 判不可用，避免目标机静默 401 无提示；(2) wincred 存在性检查经新增 `_credential_exists` 只查 `CredReadW` 的 size>0，不把 secret blob 读入内存；(3) 报告是应用层纯函数（不建新 Service/Manager），UI 落地归 P1-T04；(4) `CredentialResolver` protocol 未改，只加独立模块级函数；(5) manifest `source_id` 在 re-export 时不被带出（`_build_archive` 建新 manifest，`source_id` 属 import metadata 供追踪，非导出物）。独立 Review（2026-08-07）无 BLOCKER；1 SHOULD-FIX（空值凭据误判 available）已修复并补测试；MINOR 记录取舍。全量 pytest/Ruff/mypy 通过，P1-T02 标记 completed，指针推进至 P1-T04-M01。

P1-T04-M01 落地取舍（Project active Profile 选择，2026-08-07）：Reality Check **ADAPT**。现场复用 `ModelProfileService`/`ProviderConnectionService` CRUD、`005`/`006` FK RESTRICT 与 `profile_snapshot` 历史快照 seam（不重写已通过服务）；唯一缺口是 `projects` 无 active 字段、`delete_profile` 遇 RESTRICT 抛不透明 `SqlExecutionError`。关键取舍：(1) active selection 是 1:1 单一值 → 用 `projects.active_profile_id` 可空 FK 列（`009` migration，ON DELETE RESTRICT）而非规范化选择表；selection 存于共享 SQLite 载体，开放目录/`.aiproject` 重开自动恢复、无需容器逻辑，`projects.schema_version` 保持 1。(2) 删除保护双保险：服务层预检给明确 `ModelProfileInUseError`（区分"被 Project active 引用"并列出项目名 / "被历史 Attempt 引用"并给引用计数），DB 层 FK RESTRICT 兜底；未引用的 profile 删除与缺失返回 False 语义不变。(3) 预检与删除不在同一事务（预检读 + repository.delete 自开事务）——单用户本地应用可接受，并发最坏退化为通用 `SqlExecutionError`，无数据破坏，FK RESTRICT 保证引用完整性。(4) 被历史 Attempt 引用的删除异常类型从 `SqlExecutionError`（DatabaseError）变为 `ModelProfileInUseError`（ValueError）——in-tree 无调用方受影响，UI 落地（M04）按新类型捕获。(5) `with_active_profile` 不校验 profile_id 正负（负 id 报"ModelProfile with id -1 does not exist"）——cosmetic，保留。独立 Review（2026-08-07）**APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX）；MINOR 已处理：误导性测试改名并补仓库缺项目 ValueError 路径、补两 Project 共享删除错误列出双名、补 clear 幂等；其余 MINOR 记录取舍（预检非原子、异常类型变化、负 id 文案）。全量 pytest **1129 passed**、Ruff clean、mypy 108 files no issues；M01 标记 completed，指针推进至 P1-T04-M02。该取舍记录于 `03` §3、`04` §3/§5、`07` §18。

P1-T04-M02 落地取舍（Project-scoped Glossary，2026-08-07）：Reality Check **ADAPT**。DEC-P1-T04-GLOSSARY 判定**不触发**——(a) priority 语义已由 `05` §5 裁决（locked 按 priority+稳定次序先注入、低优先级先裁剪），数值范围在 `07` §18 明确委托执行 Agent；(b) 重复词唯一域在 `07` §18 委托，且硬约束只要求"重复/冲突术语明确结果且不污染"，实现"明确拒绝 + 无污染"满足契约；(c) scope 在 `01` §11.2 定义为用户可编辑分类（专有名词/技术词/人名/地名），`05` 注入不用 scope 过滤，无跨切片契约影响。关键取舍：(1) 唯一域 `UNIQUE(project_id, source_term)`（同 Project 内 source_term 唯一，重复明确拒绝），strip 归一化使 `" Apple "` 与 `"Apple"` 冲突判定一致；(2) 服务层预检 + DB UNIQUE 兜底并发写——预检与写入非同一事务，单用户本地应用可接受，最坏退化为通用 `SqlExecutionError` 且事务回滚无污染，与 M01 删除预检同一取舍先例；(3) `glossary_entries.project_id` 用 ON DELETE CASCADE（项目删除连带术语，与 `translation_runs`/`segments` 项目级 CASCADE 一致），历史 Attempt/Revision 引用不涉及术语表故无删除保护需求；(4) 新 Service `GlossaryService` 持有独立连接与生命周期（非转发器），复用 `ProjectRepository`/`create_database`/`MigrationRunner`，不新建第二套存储；domain 层无 SQLite 依赖；(5) `list_entries`/`list_locked_entries` 按 `priority DESC, id` 排序为 M03 提供确定稳定次序；(6) 负/零 project_id 经 service 先走 `_ensure_project_exists` 报"Project with id 0 does not exist"而非"positive integer"——cosmetic，与 M01 负 id 文案同源，保留。独立 Review（2026-08-07）**APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX）；MINOR 已处理：domain/service 对非字符串 term 给明确 `GlossaryEntryError`（原裸 AttributeError）、`GlossaryService.__init__` 迁移失败关闭连接（对齐 `ProjectService` 加固）、补 5 项测试缺口（repository 直存重复 SqlExecutionError+回滚、update 校验失败不污染、origin='import' 合法、同 priority 按 id 决胜、跨 Project 删除隔离）；其余 MINOR 记录取舍（负/零 id 文案、预检非原子）。全量 pytest **1160 passed**、Ruff clean、mypy 112 files no issues；M02 标记 completed，指针推进至 P1-T04-M03。该取舍记录于 `03` §3、`04` §3/§5、`07` §18。

P1-T04-M03 落地取舍（确定性 Prompt 注入，2026-08-07）：Reality Check **ADAPT**——现场 `ContextComposer.compose`（P0-T05-M03）已实现 glossary 候选 priority 归一化 1、邻居前选择、Manifest selected/pruned、预算不足抛 `ContextBudgetError` 不截断；`list_locked_by_project`（`is_locked=1 ORDER BY priority DESC, id`）已提供确定稳定次序（M02）；唯一缺口是 `TranslationService.translate_segment` 未传 `glossary_candidates` 且无 `GlossaryEntry → ContextCandidate` 映射。DEC-P1-T04-GLOSSARY 不触发（M02 已判定，M03 只接线）。关键取舍：(1) 映射为 `application/glossary_context.py` 纯函数 `build_glossary_candidates`，而非加 GlossaryService 方法——TranslationService 已持有 `_db` 与 repository 集，追加 `GlossaryEntryRepository` 单一连接/生命周期自洽，映射函数可独立单测；composer 保持纯函数不查 SQLite（对齐 Review 重点"Composer 不直接查库"）。(2) `content = "{source_term} -> {target_term}"` 单行承载术语对，渲染为 `[locked glossary] ...` 上下文行；真实 entry priority 存入 `metadata`（Manifest 中候选 priority 被 composer 归一化为 1，排序仍由 repository 稳定次序决定）。(3) `segment_id = "glossary:{source_term}"` 复用 P0-T05-M03 既有约定，同 Project 内 source_term 唯一故确定。(4) `_default_estimate` 公开为 `default_estimate`（context_composer）供映射共享，避免复制估算逻辑；仅内部引用更新，无公共契约变化。(5) 只有 locked、仅当前 Project 的过滤放在 repository 查询（`list_locked_by_project(run.project_id)`），映射函数不做二次过滤——职责单一、可测。独立 Review（2026-08-07）**APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX）；MINOR 已处理：补 composer 同 priority 平局测试（glossary 先于 distance-0 邻居，稳定排序保证）；其余 MINOR 记录取舍：(a) composer 将 glossary 归一化为 priority 1，与 distance-0 邻居 priority 同为 1，"glossary 在前"依赖稳定排序而非优先级值——现有测试已覆盖该边界；(b) Manifest glossary 候选 priority 记录归一化值 1，条目真实 priority 仅存 `metadata`/`context_summary` 未逐条透出——§7 debug 如需按条目优先级可从 metadata 导出（当前无该消费方）。全量 pytest **1177 passed**、Ruff clean、mypy 114 files no issues；M03 标记 completed，指针推进至 P1-T04-M04。该取舍记录于 `03` §7、`07` §18。

P1-T04-M04 落地取舍（薄管理 UI，2026-08-07）：Reality Check **ADAPT**。现场核验 M01–M03 与 P0-T08-M05 UI seam 齐备（active Profile 选择/清除、Glossary CRUD、`delete_profile` 预检 `ModelProfileInUseError`、`report_credential_availability`、`ServiceWorker`/`WorkerPage` pytest-qt 模式）；缺口是 UI 无 active Profile 选择面、无 Glossary 管理面、Connection 删除对被引用抛不透明 `SqlExecutionError`、未消费凭据报告。关键取舍：(1) `ProviderConnectionService.delete_connection` 删除前预检给新增 `ProviderConnectionInUseError` 并列出引用 profile 名——镜像 M01 `delete_profile` 预检先例（同"服务层预检 + DB FK RESTRICT 兜底"模式，不重写 CRUD），使"被引用删除"在 UI 上可操作；缺失返回 False 的既有语义不变，既有 `test_service_blocks_connection_delete_when_referenced`（`pytest.raises(Exception)`）不破坏。(2) UI 只扩展现有 `SettingsPage`/`ProjectPage`（不新增顶层 Tab、不建转发型 Service/Manager），所有操作经 `ServiceWorker` 在线程内开闭 service 连接，Qt 主线程只持有 `db_path` 用于构造 service；`select_project(project_id)` 是 `import_file`/`translate` 同类的程序化入口，供 pytest-qt 无对话框驱动（`QComboBox.setCurrentIndex` 不触发 `activated`，故测试走方法而非 setIndex）。(3) 缺凭据提示复用 `report_credential_availability` 的应用层只读报告（P1-T02-M05），UI 只渲染 available/hint，永不显示 secret。(4) Glossary 的 priority 用 0-100 QSpinBox、locked 用 QCheckBox 约束输入，source/target/scope 的 strip/非空/唯一校验仍在 service 层、worker 线程回传为可操作消息——UI 层不复制领域校验。(5) 结构性守卫测试：`ui/pages.py`/`ui/main_window.py` 源码不含 repositories/sqlite 导入，固化"UI 不直接查库"契约（`ui/worker.py` 的 `TranslationWorker` 直用 `SegmentRepository` 是 P0-T08-M05 既有翻译 worker、非 M04 管理面，不在守卫范围，未扩大改动）。独立 Review（2026-08-07）**APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX）；MINOR 已处理：`SettingsPage._populate` 刷新不再把 Add-Profile 的连接下拉重置到 index 0——保存并恢复当前选中连接 id，避免用户中途选择的 Connection 被静默换掉后误绑 Profile，新增 `TestSettingsSelectionPreserved` 测试（15 项）；其余 MINOR 记录取舍：`WorkerPage` 单 pending-request 槽（快速连点删除时前一次请求的结果/错误被丢弃，但动作仍执行、随后 refresh 收敛到真实状态，UI 不产生不一致）是 P0-T08-M05 既有共享设计，修复需跨页面重构、回归风险大于收益，保留。全量 pytest **1192 passed**、Ruff clean、mypy 115 files no issues；M04 标记 completed，指针推进至 P1-T04-M05。该取舍记录于 `03` §10、`04` §3/§5、`07` §18。

P1-T04-M05 落地取舍（持久化/双形态/GUI Gate，2026-08-07）：Reality Check **ADAPT**——这是验证型 Gate 里程碑，唯一改动是新增 `tests/test_p1_t04_m05.py`（2 项），无 src/migration/依赖改动。现场核验 M01–M04 落地与 P1-T02-M05 双形态链路齐备；唯一缺口是 `009`/`010` 新增数据（`projects.active_profile_id`、`glossary_entries`）在双形态 round-trip 与同形态重启重开中的持久化证据（P1-T02-M05 round-trip 早于 P1-T04 编写，只断言 connection reference/profile/run/segments/attachments）。关键取舍：(1) Gate 测试只补证据、不改实现——`009`/`010` 是追加式 migration，归档经 SQLite backup API 携带整个 DB，active_profile/glossary 随载体自动跨机/跨重开保留，测试断言其确实如此（实测删除 `select_active_profile` 或 glossary 创建即断言失败，证明不误报通过）；(2) 测试用 `_checkpoint_clean` + `_refresh_manifest` 复刻"服务写库后重算 manifest"的生产 seam，单 Project 身份、凭据只存 reference，不复制 P1-T02-M05 的 tamper/限额矩阵（该矩阵已覆盖且与 P1-T04 数据无交互）；(3) `list_entries` 的 `priority DESC, id` 稳定次序在 round-trip 后仍保留，验证 M02/M03 确定性注入的基础未因双形态流动破坏。独立 Review（2026-08-07）**APPROVE-WITH-MINORS**（无 BLOCKER/SHOULD-FIX）；MINOR 已处理：active profile 断言改按 id 精确比较（`assert project.active_profile_id == profile_id`，原按 `model_profiles.name` 比较，单 profile 容器下充分但不够精确）；其余 MINOR 记录取舍：(a) `_checkpoint_clean`/`_refresh_manifest`/`_db_rows`/`_cross_machine_round_trip` 与 test_p1_t02_m05.py 同构重复——测试文件按约定自包含、跨文件 import 脆弱，`_refresh_manifest` 自实现而非复用 `regenerate_manifest`（本容器无附件，行为等价），保留；(b) 双形态测试未断言 manifest `source_id`——P1-T02-M05 已覆盖，此处断言 `project.id` 一致足够。全量 pytest **1194 passed**、Ruff clean、mypy 116 files no issues；M05 标记 completed，P1-T04 标记 completed，指针推进至 P1-T03-M01。该取舍记录于 `07` §18。

P1-T03-M01 落地取舍（自动模式最小旅程，2026-08-07）：Reality Check **ADAPT**。现场核验 active Profile（`009`）、内置只读 Workflow（`TranslationRunService` seed + hash 防篡改）、ImportService 六格式、`TranslationWorker` 逐 Segment 循环、`TxtExporter`、P1-T04-M05 双形态持久化 seam 齐备；缺口是 mode 概念缺失、自动模式无"解析 active Profile"路径、缺配置无一步引导。DEC-P1-T03-OVERRIDE 不触发（该节点由 `07` 定义于 M03）。关键取舍：(1) mode 持久化为 `projects.mode`（`011`，`NOT NULL DEFAULT 'auto'` + `CHECK`），镜像 `009` 追加式迁移先例、`schema_version` 保持 1——SQLite `ALTER TABLE ADD COLUMN` 的 CHECK 对既有行以 default 回填且不触发（default 满足 CHECK），DB CHECK 作直接写库兜底，非法写抛 `SqlExecutionError`，服务层 `with_mode`/`set_mode` 预检给明确 `ProjectError`；(2) 自动模式不复制 orchestrator——`TranslationWorker.translate_auto` 在 worker 线程内 `ProjectService.get_project` 解析 active Profile 后直接复用既有 `translate` 核心循环，缺 active 时发 `config_missing`（不建 Run、不发模型请求），满足"两种形态共享同一状态机/Service/Validator/Attempt/Revision/worker"硬约束；(3) UI 移除 TranslationPage 手动 Profile 组合框——自动模式用 active Profile 且"隐藏高级配置"，组合框是 workbench（M02）交互面，M01 不保留无效控件；`project_settings_changed` 信号在 active 变更后刷新 Translation 页状态，避免标签陈旧；(4) `_on_finished` 在配置引导显示时提前返回（不覆盖"需要配置"状态），无 pending Segment 时把占位 "Translating…" 替换为 "Translation finished."；(5) `translate_auto` 的 ProjectService 解析块整体 try/except 发 `failed`+`finished`——避免 worker 槽内未捕获异常被 Qt 吞掉导致 UI 卡在 Translating…。独立 Review（2026-08-07）首轮 **REQUEST-CHANGES**：2 SHOULD-FIX——(a) 恢复后引导横幅未清除（refresh 只更新标签不隐藏横幅，会出现"无 active"与"Active profile: …"同时显示的矛盾），已在 refresh 处理器中 active profile 解析时 `_hide_config_missing()` 修复；(b) `translate_auto` 的 ProjectService 块在 try/except 外，异常逃逸后无信号、UI 卡死，已整体包裹修复；零 pending 状态 MINOR 一并修复。两项各补测试（`test_guidance_clears_after_setting_active_profile`、`test_auto_translate_service_error_emits_failed`、`test_auto_translate_missing_project_emits_config_missing`），复核通过。测试注意：缺项目测试预初始化 DB schema 再启动窗口（translation worker 的 ProjectService 会与 service worker 的 migration 步骤在全新 DB 上竞争），引导清除测试在读 active-profile 组合框前先 `project.refresh()`（create-project 的 refresh 结果被后续 import 请求经 WorkerPage 单 pending-request 槽丢弃）。已知边界：(1) 切换 Project 后 TranslationPage 保留旧 `_document_id`（预存在、非 M01 引入，M02/M05 的 document 列表落地时处理）；(2) `set_mode` 尚无 UI 调用方（供测试与未来 M05 模式切换）；(3) 结构守卫只覆盖 pages/main_window 不直接查库，worker 直用 `ProjectService`/`SegmentRepository` 是既有 worker 线程模式。全量 pytest **1209 passed**（基线 1194 + M01 15）、Ruff clean、mypy 117 files no issues；M01 标记 completed，指针推进至 P1-T03-M02。该取舍记录于 `03` §3、`04` §3/§5、`07` §19。

P1-T03-M02 落地取舍（capability-aware 工作台，2026-08-08）：Reality Check **ADAPT**。现场核验 active Profile（`009`）、capability snapshot seam（`profile.get_capability()`/`compose_adapter`/`OpenAICompatibleAdapter.filter_params` 终滤）、`TranslationWorker.translate` 循环、`WorkerPage` pytest-qt 模式齐备；缺口是 `translate_segment` 无参数透传、Attempt 快照无实际请求参数、无按文档 Attempt 只读、无工作台 UI 面。关键取舍：(1) **参数快照不引入 migration**——`start_attempt` 在既有 `profile_snapshot` JSON 内追加 `request_params` 键（该列本就是 Profile/template/capability 快照的自由 JSON），`translate_segment(extra_params=None)` 把工作台草稿或 `profile.default_params` 作为该 Attempt 的实际请求参数写入；参数变更只形成其后领取 Attempt 的快照，已完成 Attempt/Revision 永不改写（既有 Attempt 快照键读取测试不受影响）。评审确认该追加键与 P0-T07 attempt 可解释性契约（"参数可解析"）自洽。(2) **UI 呈现与 Adapter 过滤双保险**：`WorkbenchParamEditor` 只呈现 `capability.supported_parameters` 声明的参数，且 `filter_params` 仍在发送前过滤——不支持参数不可能经工作台路径发出。`max_tokens` 控件上限钳制到 `capability.max_output_tokens`（评审 SHOULD-FIX：初始值已钳制但编辑范围未限，用户可旋到 1e6 发出 provider 拒绝的请求；已把 int 控件 high 钳制到 capability 上限并补"编辑后仍钳制"测试）。(3) **不复制 orchestrator**：`translate_workbench` 显式传 profile + 参数后委托既有 `translate` 循环，进度/取消/关闭收敛复用 P0-T08 语义；`_refresh_task` 与翻译都经 worker 线程，Qt 主线程不查库（进度读 `list_segment_progress` 在 refresh 任务内开闭 `TranslationRunService`）。(4) **并发 seed 加固**：`_refresh_task` 新增 `TranslationRunService` 读使 refresh 与 translate 两线程可能并发构造该服务，`_seed_builtin_workflow` 的 check-then-insert 会输给并发兄弟产生 UNIQUE 冲突——改为捕获 `SqlExecutionError` 后重读并校验 hash/read_only（仅该竞态错误被吞，非竞态失败在重读为 None 时重抛）。(5) **未知能力参数文本回退**：`ParamSpec` 注册表只覆盖常见采样参数（temperature/top_p/top_k/max_tokens/frequency_penalty/presence_penalty），capability 声明但不在注册表的参数以文本控件呈现（不假设数值语义），Adapter 仍终滤。(6) **草稿保留**：完成后 `_on_finished` 在 workbench 模式重读进度列表，`_populate_workbench` 经编辑器 `initial` 参数保留用户当前参数草稿，避免刷新重置编辑。独立 Review（2026-08-08）**无 BLOCKER**；1 SHOULD-FIX（max_tokens 编辑超 capability 上限）已修复并补测试；MINOR 已处理：(a) 翻译完成后进度列表不刷新（`_on_finished` 工作台模式重读 + 草稿保留，测试断言 completed 显示与 0.9 草稿保留）；(b) `list_segment_progress` 的"取最高 id 为最新 Attempt"逻辑仅单 Attempt 测试覆盖（补 repair 路径双 Attempt 测试）。另对 M01 既有 `test_auto_translate_service_error_emits_failed` 做测试加固——该测试 worker 瞬间失败（BoomService），`_wait_finished` 在 emit 后才连接 `finished`，直连 callable 场景下信号可能先于连接发出而超时；改为先连接 `finished` 再 emit（行为断言不变）。已知边界：工作台参数草稿仅会话内存（M03 Override/M05 重开一致持久化落地）；进度列表是打开/文档选择/翻译完成时的快照，非实时订阅。全量 pytest **1229 passed**（基线 1209 + M02 20）、Ruff clean、mypy 120 files no issues；M02 标记 completed，指针推进至 P1-T03-M03。该取舍记录于 `03` §3、`04` §3、`05` §7、`07` §19。

P1-T03-M03 落地取舍（受控 Prompt Override，2026-08-08）：Reality Check **ADAPT**。现场核验 M02 落地与 Prompt 模板 seam（`PromptRenderer.render(template=...)`/`RenderedPrompt`/`template_version`/`output_contract`，`test_p0_t05_m04` 已证未知变量拒绝 + 输出契约不可移除）；唯一缺口是预设模板无稳定身份/版本、override 无持久化/校验/渲染接入。**DEC-P1-T03-OVERRIDE 判定不触发**——决策范围（编辑边界/拒绝规则/父版本失效策略）三个子项均已由权威文档给出唯一策略：(a) 编辑边界：`01` §16"预设模板不可修改，用户修改保存为 Override"、`05` §2"预设不可直接修改 + 记录父模板版本"、`07` §19"override 不能移除 Segment ID/output wrapper/格式保护/Validator/安全限制"；(b) 拒绝规则：M03 目标文本明确"未知变量、失效父版本和试图移除输出/格式/校验边界时拒绝，不执行模板代码"；(c) 父版本失效策略：M03 目标文本明确"失效父版本…拒绝"（fail-closed）。余下为可逆内部实现（注册表组织/SQL 组织/校验机制/UI 布局），按 `09` §7"开发 Agent 必须继续自主处理私有类/文件组织、SQL 组织、fixture、控件布局、已批准依赖内的实现和可逆 ADAPT；不得把普通实现分歧升级为节点"，与 P1-T04-M02/M03 的 DEC 不触发先例一致。关键取舍：(1) **预设注册表最小引入**——`application/preset_templates.py` 只登记一个 `general` v1.0.0（文本 = 既有 `PromptRenderer._DEFAULT_TEMPLATE`），`PromptRenderer` 默认模板改为从注册表读取（行为不变，`test_p0_t05_m04` 全绿）；`ALLOWED_PLACEHOLDERS` 与 renderer `_build_placeholders` 键一致（有测试断言对齐），避免校验与替换占位符漂移。(2) **父版本语义**——override 的 `parent_template_version` 在保存时 = 当前预设版本，独立于 `profile.template_version`（后者仍只是审计元数据，保留既有"v1"/"1.0.0"等任意字符串语义）；渲染时 `parent != 当前预设版本` fail-closed 拒绝，且对持久化文本重校验（防 DB 篡改/绕过保存校验）。该失效只在应用升级更新预设后出现，符合"父版本失效"生命周期。(3) **边界结构性不可移除**——Output Contract wrapper 由渲染器固定追加（override 只替换模板正文），格式保护/校验/安全限制是独立流水线阶段，无模板特性可关闭；M03 不新增任何 eval/exec（`string.Template` 纯替换），并有源码结构守卫测试。(4) **不复制 orchestrator**——override 解析在 `TranslationService.translate_segment` 内、claim 前完成（stale 时无 Attempt、无请求），`translate_auto`/`translate_workbench` 共用该路径。(5) **审计**——使用 override 的 Attempt 在 `context_summary` 追加 `override_parent_version`（与 M02 `request_params` 同"JSON 追加键无 migration"先例），使实际渲染模板可解释。(6) **UI 草稿保留**——`WorkbenchPromptEditor` 只读预设预览 + 可编辑拷贝 + Save/Clear（页面经 worker 线程调 service），`_rebuild_prompt_editor` 用 `initial` 保留未保存草稿跨 refresh；预设只读由 widget 强制（preview `setReadOnly`），不提供任何预设写路径。已知限制：`string.Template` 把裸 `$` 后接非标识符（如 `$5`）视为非法占位符，override 文本中的字面美元需 `$$` 转义（与现有 renderer 自定义模板行为一致，保存时提前拒绝且错误消息提示以 `$$` 转义，测试固化）。独立 Review（2026-08-08）**无 BLOCKER**，2 SHOULD-FIX 已修复并补测试：(a) stale override 在 UI 不可见（父版本错配时工作台仍显示健康、翻译才会全段失败）——`_rebuild_prompt_editor` 在 `parent_template_version != 当前预设版本` 时给 `WorkbenchPromptEditor(stale=True)`，状态栏显示 "no longer matches the current preset…Re-save or clear" 并保留 Clear 恢复路径，补 widget 级 + pytest-qt 级测试；(b) 字面 `$` 报错 "Invalid template syntax." 无引导——错误消息改为 "a literal dollar must be written as '$$' (e.g. '$$5')"，测试断言消息含 `$$` 引导。全量 pytest **1267 passed**（基线 1229 + M03 38）、Ruff clean、mypy 124 files no issues；M03 标记 completed，指针推进至 P1-T03-M04。该取舍记录于 `03` §3、`04` §2/§3/§5、`05` §2/§7/§9、`07` §19。

P1-T05-M01 落地取舍（冻结可判定矩阵，2026-08-08）：Reality Check **FIT**——现场核验 P1-T03/P1-T04 全链路落地（migrations 001–012 齐全、关键模块存在），全量基线复现（pytest **1298 passed**/1 skip、Ruff clean、mypy 126 files）与交接一致；环境实测 Python 3.12.10 / Windows 11 Pro 10.0.26100 / AMD64。**DEC-P1-T05-RELEASE 判定不触发**——(a) 打包工具：PyInstaller 已由 P0-T08-M06 build/start smoke 验证可行、`03` §10 确定首选、`07` §20 参考方案授权"可验证的实现选择"，无"权威文档尚未给出唯一答案"；(b) 支持环境：`01` §21.1 + `02` Release Gate + `07` §20 唯一确定"Windows 11 x64（当前环境 AMD64）"，扩展 ARM64 或缩窄已批准兼容性承诺才需 DECISION_REQUIRED（本 M01 不扩展）；(c) lockfile：存在性是 `07` §20 硬约束，形式（pip freeze 快照）是可逆内部实现选择，用户不可见、不改持久化/安全契约，按 `09` §7"不得把普通实现分歧升级为节点"与 P1-T04-M02/M03、P1-T03-M03 先例一致。关键取舍：(1) 矩阵落点为 `03` §12（判定原则/支持环境/依赖锁定/质量命令表/公共矩阵规范/P0-P1 release-blocking 等级），是 M02–M05 共用的布尔 Gate 底座；`02` V1.0 Release Gate 为高层声明、`07` §20 为任务契约、`03` §12 承载可执行细节。(2) 依赖锁 `requirements.lock` = `pip freeze` 全量快照（排除 `transrealm` editable 与 `pip`），与 pyproject 声明范围一致且等于安装版本；`test_p1_t05_m01` 断言"锁==安装、锁满足 pyproject runtime+dev 范围、工具链入锁、支持环境 Windows 11 build≥22000+x64+py3.12"——锁/环境漂移即 Gate 失败（不把已知失败标通过）。(3) 支持环境断言补 Windows 11 build≥22000（Review SHOULD-FIX：原只判 `system=='Windows'` 无法区分 10/11）。(4) 质量命令表含 `scripts/verify_task.py`（需 Git 基线形成后生效）与 `scripts/check_candidate_hygiene.py`（实测 exit 0）。(5) 候选可定位性 = Git 基线 commit + 锁文件共同保证（`09` §6）。MINOR 处理：dev 工具版本范围补校验（Review MINOR 2）；`03` §12 的 `08 §8` 引用改为"落地取舍记录"（Review MINOR 4——`08` §8 实为项目文件设计，引用语义错位）。MINOR 记录取舍：(a) 单向漂移检测（只检"锁==安装"，不检"已安装未入锁"——环境含 pip/setuptools 等引导包，反向检测会噪音；M04 用 `pip install -r requirements.lock` 复现验证兜底）；(b) `test_lock_file_exists` 冗余但含再生成命令提示，保留。独立 Review（2026-08-08）**APPROVE-WITH-MINORS**（无 BLOCKER；1 SHOULD-FIX 已修复；MINOR 2/4 已处理、3/5 记录取舍）。全量 pytest **1305 passed**（基线 1298 + M01 7，1 skipped 本环境无符号链接创建权限）、Ruff clean、mypy 127 files no issues；M01 标记 completed，指针推进至 P1-T05-M02。**解除条件：P1-T05 前置"工作树先形成可恢复 Git 基线"未满足（governance_commit_pending，需用户授权 commit），M02 开工前必须先授权 Git 基线形成，或用户明确允许在未提交工作树上继续。**该取舍记录于 `03` §12。

P1-T03-M05 落地取舍（模式切换与 GUI Gate，2026-08-08）：Reality Check **ADAPT**。现场核验 M01–M04 落地与 seam（mode 持久化 `set_mode`/`get_project`、`translate_auto`/`translate_workbench` 共用 `translate` 循环 + `request_stop` 取消、closeEvent 有界 wait 收敛、`list_segment_progress`、`list_source_documents_by_project`）；唯一缺口是模式切换 UI 无调用方、运行中切换无提示、无文档列表 + 切换 Project 保留旧 `_document_id`（M01 已知边界）、重启结果/锁定证据缺位。关键取舍：(1) **模式切换不复制 orchestrator**——`TranslationPage` 模式选择器经 `ServiceWorker` 调既有 `ProjectService.set_mode` 持久化 `projects.mode`，运行中切换以"提示 finish or Cancel + 选择器恢复"拒绝（`_running` 标志在主线程 `_on_translate` 前置 True、`finished` 队列信号后置 False，守卫无 TOCTOU、最坏为无害误拒），满足"运行中 Run 不原地改变 Profile/Workflow/参数"硬约束；(2) **文档选择器经 Application Service**——`TranslationRunService.list_source_documents` 只读转发 `SegmentRepository.list_source_documents_by_project`，使 `ui/pages.py` 不含 repositories/sqlite 导入（结构性守卫），与 `list_segment_progress` 同一 service 同一 `with` 块复用连接；(3) **不做自动选中文档**——`_refresh_task` 提交时捕获 `current`/`project_id`（无跨线程 UI 读），任务内判定"当前文档属于该 Project 则沿用、否则清空"，切换 Project 不泄漏另一 Project 的陈旧 `_document_id`（M01 已知边界消除）；组合框无有效文档时 `setCurrentIndex(-1)` 不高亮首项避免"高亮但未加载"矛盾；(4) **运行中上下文守卫**——`_set_running` 集中管理 `_running` 与 Translate/Cancel/Export/文档选择器按钮态，运行中切文档被拒（Review SHOULD-FIX 1）；(5) **set_mode 成功路径同步 `_mode`** 再 refresh，refresh 失败不致选择器显示旧 mode（Review SHOULD-FIX 2）；(6) 取消/关闭/重启门禁复用既有 seam（`request_stop` Segment 边界取消、closeEvent 收敛、共享 SQLite 重开恢复），不新增第二套存储/状态机。已知边界/取舍：Project 切换后不自动选中文档（用户从选择器显式选择，恢复可接受）；workbench 缺 active Profile 在主线程同步短路由（`_active_profile_id` 来自 refresh），与 auto 的 worker 长路由（`translate_auto` 解析）语义一致但路径不同；运行中跨 Tab 切 Project 仍可使页面上下文变化（在途 Run 的 DB 结果安全，仅页面视图受影响，文档选择器锁定已防可见切换）。独立 Review（2026-08-08）**无 BLOCKER**；2 SHOULD-FIX 已修复并补测试（运行中文档切换无守卫——选择器运行中禁用 + `_on_document_selected` 拒绝，补 `test_document_switch_refused_while_running`；set_mode 成功但 refresh 失败 UI/DB 失同步——成功路径同步 `_mode`）；MINOR 已处理（组合框无有效文档不高亮首项、`_on_translate` 加 `_running` 守卫、refresh None 清空陈旧文档状态）；MINOR 记录取舍（无 Project 切换报错并恢复、workbench 缺 active 同步短路由）。全量 pytest **1298 passed**（基线 1288 + M05 10）、受影响旧测试子集 461 passed、Ruff clean、mypy 126 files no issues；实际可用性 smoke（真实窗口 + 完整旅程驱动）SMOKE PASS；M05 标记 completed，P1-T03 标记 **completed**。该取舍记录于 `03` §10、`07` §19。

P1-T03-M04 落地取舍（人工 Revision 与锁定，2026-08-08）：Reality Check **ADAPT**。现场核验 M03 落地与 Revision/lock seam：`TranslationRevision`（`domain/translation_revision.py`）已有 `origin ∈ {ai,user,import}` 与 `is_locked`（`006` migration 的 CHECK 即支持，**无需新 migration**）、`TranslationRevisionRepository.save` 已持久化两者、`finalize_success`（`segment_attempt_repository.py`）已在自动完成前校验"expected current 未变 + 非 locked"（fencing + is_locked 拒绝）、`recover_expired_leases` 对 locked current 的 processing 段转 completed 不重建、exporter 默认读 `current_revision_id` + `revision_overrides` 显式选择历史 revision；**唯一缺口**是工作台编辑追加 user Revision 的 use case、lock/unlock、切换 current、UI 编辑面。关键取舍：(1) **新增 use case 而非第二套状态机**——`TranslationRunService` 增加 `append_user_revision`/`set_current_revision`/`lock_current_revision`/`unlock_current_revision`（`_set_current_locked`），全部复用既有 atomic-guard + fencing seam：append/set 在单事务内 INSERT + UPDATE（`WHERE status != 'processing'` 原子守卫 + version bump 使捕获的 stale claim 失效），rowcount 0 即回滚无孤儿 Revision；processing 段编辑明确拒绝（有 in-flight attempt 时避免与迟到 finalize 竞态，finalize 的 current-changed/locked fencing 为并发兜底）。(2) **人工 current 的结构性保护**——append/set 把段置 completed，auto worker 循环只翻译 pending 段，故 user current 不可能被自动 claim；锁定语义由 `is_locked` 承载，`finalize_success` 拒绝、`recover_expired_leases` 转 completed 双路兜底"锁定后迟到结果/重译不能覆盖"。(3) **lock 原子化**——`_set_current_locked` 用单条 `UPDATE ... WHERE id = (SELECT current_revision_id FROM segments WHERE id = ?)` 原子锁定 current，避免读-写窗口锁到用户未见的陈旧 revision（Review MINOR 加固）。(4) **`list_segment_progress` 增字段向后兼容**——`SegmentProgress`（`application/workbench.py`）追加 `revision_text: str | None` / `revision_locked: bool`（带默认值、仅关键字构造处更新），经 `TranslationRevisionRepository.get_many_by_ids` 批量填充（无 N+1），供工作台编辑面显示当前译文与锁态。(5) **UI 编辑面**——`ui/workbench.py` 新增 `WorkbenchRevisionEditor`（只发信号不碰 DB：source 只读 + 译文可编辑 + Save/Lock/Unlock），`TranslationPage` 工作台接入（`_segment_progress` 选中 → `_rebuild_revision_editor`，Save/Lock/Unlock 经 ServiceWorker 线程调 service、`_handle_action` 刷新；`_populate_workbench` 记录选中 segment 并在刷新后恢复、`initial` 保留未保存草稿跨 refresh——Review 发现草稿保留原为死代码，`set_revision` 无条件覆盖 `initial`，已修复并补 `test_workbench_revision_draft_preserved_across_refresh`）。已知边界：(1) 切换 current 的 use case `set_current_revision` 服务层可用且有测试，但工作台 UI 暂未提供"从历史 revision 下拉切换 current"的入口——Save 编辑即追加 user Revision 并成为 current，选择历史 AI 结果作 current 的 UX 归 M05 或后续（Review MINOR，符合所列 UI 范围）；(2) 崩溃/损坏现场若把"未锁 user current"段变 processing，recover 仍按非 locked 回 pending 可重译（P0-T07 既有语义），正常流不可达（append 置 completed），已补 `test_recover_returns_unlocked_user_current_to_pending` 固化该边界；(3) 追加空文本 user Revision 允许（与 `finalize_success` 不拒空译文一致），UI 层未强制非空（最小实现）。独立 Review（2026-08-08）**无 BLOCKER**；1 SHOULD-FIX（草稿保留死代码）已修复并补测试；MINOR 已处理：lock TOCTOU 原子化（见取舍 3）、补 recover-unlocked-user-current 边界测试；MINOR 记录取舍：UI 暂无历史 revision 切换入口。全量 pytest **1288 passed**（基线 1267 + M04 21）、受影响旧测试子集 413 passed、Ruff clean、mypy 125 files no issues；M04 标记 completed，指针推进至 P1-T03-M05。该取舍记录于 `03` §10、`07` §19。


---

# 9. 工作流系统


## 风险


完整工作流编辑器复杂。


---

## 决策


第一版本：

预设 Workflow 模板。


例如：

```
普通翻译

高质量翻译

小说翻译

字幕翻译
```


---

后期：

支持：

复制模板

↓

用户修改

↓

保存自定义流程


---

# 10. 技术栈与绿色版设计

## 决策

- Python 3.12：文本处理、AI 接口和本地工具生态成熟，适合当前单人长期开发；
- PySide6（Qt 6）：提供成熟桌面控件、模型视图、线程/信号机制和后续跨平台可能性；
- SQLite：适合单用户、绿色版、迁移和备份；
- Windows 11 优先：先缩小正式测试矩阵，避免 V1.0 同时承担三平台发布成本；
- 绿色版优先：满足解压即用与数据可控目标。

## 取舍

Python/PySide6 的启动速度、包体和打包插件收集需要通过实际构建验证；不以未来跨平台可能性为由提前增加平台抽象。业务层仍禁止写死 Windows 路径，避免形成不必要的迁移障碍。

绿色版仅能在可写目录中保存默认数据。若用户放入受保护目录，程序必须明确提示选择可写数据目录，不能假设所有程序目录都可写。

默认数据结构：

```text
config
cache
logs
projects
```


---

# 11. AI开发风险


## 风险


AI Agent容易：

- 把规划假设当成代码事实；
- 让规划模型垄断实现决策，或让执行模型机械服从；
- 自行重构；
- 添加不必要依赖；
- 过早优化；
- 为未来可能性提前建立插件、事件总线、队列、微服务或第二套存储。


---

## 决策


计划不是不可质疑的实现命令。规划 Agent 负责目标、边界与验收，执行 Agent 负责核验真实代码并选择范围内的最小实现；代码和可复现测试可以推翻规划中的现场假设，但不能自行推翻已批准产品范围和架构约束。

每个 Milestone 开工前必须按 `06_AI_Development_Guide.md` 给出 `FIT`、`ADAPT` 或 `REPLAN`。局部、私有、可逆且不改变用户行为、持久化、公共契约、依赖和 Task 范围的调整属于 `ADAPT`，执行 Agent 可自主决定。

所有 `REPLAN` 或重大修改必须输出：

```
计划假设

代码/测试证据

冲突原因

最小替代方案

影响与收益

风险

迁移和回滚成本

待裁决事项
```

等待用户确认或规划重新审查后再修改冲突部分。禁止为了服从计划而硬建空壳组件、污染无关模块职责或复制第二套存储。

### 最小设计门禁

- 没有当前验收需要的第二个真实实现或调用方，不建立插件式抽象。
- 没有可复现的异步协作、吞吐或进程隔离需求，不引入事件总线、任务队列或微服务。
- 现有存储满足原子性、恢复、隔离和查询验收时，不增加第二套存储。
- 新 Manager/Service 必须具有独立状态、策略或生命周期；纯转发层不创建。
- 新依赖必须解决当前 Task 的现实问题，不能只服务于“以后可能需要”。
- 扩展点在第二个真实用例出现后再提取，优先完成最小垂直闭环。


---

# 12. 当前必须保持的设计


以下模块不要删除：


## Model Adapter


原因：

支持：

- 本地模型；
- 在线API；
- 多厂商。


---

## Segment系统


原因：

支持：

- 断点恢复；
- 精准重译。


---

## Debug系统


原因：

AI翻译系统必须可追踪。


---

## Project文件


原因：

支持迁移、备份和项目转交。


---

# 13. 暂缓开发功能


以下功能不应该进入早期版本。


## 插件系统


原因：

需求未验证。


---

## 内置模型下载器


原因：

兼容性复杂。


---

## 自动参数优化


原因：

收益有限。


---

## 完整工作流编辑器


原因：

开发成本高。


---

# 14. 架构修改流程


任何以下变化必须重新审查：

- 用户可见行为或已批准产品范围改变；
- 数据库更换、现有持久化格式或 migration 兼容性改变；
- GUI 框架或运行/部署拓扑改变；
- 翻译核心流程或跨模块公共契约改变；
- 当前 Task 或已批准技术栈未授权的新增外部依赖、基础设施或独立进程；已明确要求的 PySide6/pytest-qt 等依赖落地只需完成版本、许可、安全、锁定和打包影响审查，不重复申请技术栈裁决；
- RAG 方案或 Project 文件格式改变；
- 修改范围显著越出当前 Task。

私有类名、私有函数、内部文件组织、范围内局部算法和可逆复用选择，在硬约束与验收不变时属于 `ADAPT`，不进入本流程。


流程：


```
提出修改

↓

Architecture Review

↓

Technical Design更新

↓

Task重新规划

↓

开发
```


---

# 15. 最终架构原则


本项目遵守：

```
简单可靠

优先于

复杂智能
```


```
真正提高翻译质量

优先于

增加AI功能数量
```


```
可维护

优先于

快速实现
```


---

# 16. 已确认的范围决策

- Migration 安全备份是后续 schema 演进的前置能力：P0-T03 内先完成 M00，仅在有 pending migration 时创建 SQLite 一致性备份，失败则阻断升级；Project 双形态的离线转移和安全导入仍由 P1-T02 负责。
- Phase 0 的 P0-T08 包含最小 PySide6 GUI shell，用于操作和验证 TXT 核心闭环；Phase 1 的 P1-T03 才实现自动模式与工作台模式。无需新增独立 GUI-only Task，也不把两种工作模式提前到 Phase 0。
- P0-T07 使用 SQLite 事务、Segment version/lease fencing 和幂等唯一约束完成单用户恢复；没有可复现的跨进程吞吐需求，不引入任务队列、事件总线或第二套状态存储。
- transport retry、capability degradation、输出 repair 和 Segment 业务重试属于不同层：前两者保留在一次逻辑 Attempt 内，任何再次模型调用的 repair/业务重试创建新 Attempt；不得无限重试。
- Revision 是不可覆盖历史，current Revision 是默认导出选择；人工或 locked current 不得被自动或迟到 worker 替换。
- P1-T04 的 Project Profile 选择与基础 Glossary 调整到 P1-T03 模式 UI 之前，使自动/工作台模式只消费已存在的稳定配置和 Context 输入；这是依赖顺序修正，不扩大范围。
- `.aiproject` 与高级用户开放目录是同一逻辑 Project 的两种互通视图，共享 manifest、SQLite、hash、相对路径、秘密排除和 migration 契约；开放目录不是第二套存储，也不引入 watcher/双向热同步。归档导入采用隔离 staging、完整校验后原子安装，拒绝路径逃逸、link、重复关键 entry 和资源耗尽；不为此引入自定义归档格式或在线同步。
- Phase 0 绿色版仅做候选工具 build/start 可行性 smoke；P1-T05 才冻结依赖并形成 Windows release candidate。构建候选、创建远程仓库和对外发布是不同动作，后两者始终需要用户单独授权。
- V1.0 是基础可靠版，不包含 RAG、智能 TM、World State、节点式 Workflow 编辑器、插件或多人协作。
- Project 只承诺单用户离线迁移、备份和转交。
- 首发正式支持 OpenAI-compatible HTTP；llama.cpp/Ollama 走兼容端点；Sakura/Murasaki 是 Model Profile。
- Phase 0 即提供规则式最小 Context Budget、机器可解析输出契约、解析校验与有限重试。
- 技术栈采用 Python 3.12 + PySide6 + SQLite；V1.0 正式支持 Windows 11，并以绿色版为主要发布形态。
- 这些能力前置是为了保证 Segment 可恢复、跨模型一致和后续 RAG/TM 不重构核心链路，并不代表提前实现高级智能功能。
- `DEC-P1-T01-FOUNDATION`（2026-08-06）：保真载体采用方案 2——持久化原始 bytes + 版本化 format metadata envelope（encoding/BOM/newline/parser&metadata version/source hash）+ 格式专属定位信息，TXT 用受验证的 byte span replacement mapping。理由：满足 TXT no-op byte identity、仅替换目标 span、原编码/BOM/换行可恢复，且不强迫多字节编码、换行归一化、格式结构各异的 JSON/字幕与 TXT 共享同一 span 模型。方案 1（统一原始 bytes + 每 Segment byte span 作为基础契约）否决：多字节编码、换行归一化、格式结构和跨 token 边界使统一 span 规则无法安全覆盖五类后续格式，易把“可定位”误化为“可替换”；各格式仍可在 envelope 内使用 spans。方案 3（重序列化格式对象）否决：会改变空白、转义、字段/标签或换行，无法满足 byte identity。边界保留：JSON path 用户可配置选择、各格式 metadata 最终字段、第三方 parser 依赖和 ASS/SSA parser 实现由各垂直 Milestone 在已批准 envelope/保真约束内用证据决定；旧 TXT 数据缺原始 bytes/可验证 metadata 时安全失败并保留旧 Project/目标文件，用户提供并校验原文件后才显式补齐。

---

# 文档结束