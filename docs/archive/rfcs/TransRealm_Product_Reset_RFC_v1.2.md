# TransRealm 产品重置与架构收敛方案（RFC v1.2 — 开工候选版）

> 状态：**Implementation Candidate / 两轮反审阅后开工候选**  
> 目标读者：项目作者、后续开发 Agent、独立架构审阅模型（如 Kimi K3 等）  
> 方案目标：在尽可能复用 TransRealm 现有可靠底座的前提下，将项目从“持续扩张的 AI 翻译平台”收敛为“本地优先、UI 简洁、后端能力强、能较快完成的个人 AI 翻译工作台”。  
> 核心原则：**产品重置，不做无必要的底层推倒重写。**  
> 本文性质：架构 RFC + 产品范围冻结 + 迁移计划 + 验收规范。本文刻意包含可质疑点、假设与失败模式，供旗舰模型进行反审阅。

---

## 0. 执行摘要

TransRealm 当前的主要问题不是代码质量不足，而是**产品边界与工程治理复杂度已经超过“个人本地翻译工作台”这一真实目标所需要的程度**。

当前项目已经拥有较扎实的底座，包括：

- Python 3.12 + PySide6；
- SQLite 持久化与 Migration；
- Project / Source Document / Segment / Attempt / Revision / Translation Run 等数据结构；
- TXT / JSON / SRT / ASS / SSA / VTT 导入导出；
- 格式保真与原始 bytes / metadata 校验；
- OpenAI-compatible Model Adapter；
- Provider Connection；
- Prompt / Model Profile；
- Glossary；
- 断点恢复、失败重试、崩溃恢复；
- 绿色版发布与候选验证；
- 较高密度的自动化测试与静态检查。

现有状态记录表明，项目已经完成 V1.0 Release Candidate Gate，曾记录全量 `pytest 1339 passed`、Ruff clean、mypy clean 等结果。换言之，**TransRealm 已经有足够多值得保留的成熟基础设施，不适合为了“简化”而从零重写。**

但原规划继续向以下方向扩展：

- Character Data；
- Translation Memory；
- World State；
- Style Preference Memory；
- RAG；
- Context Budget Manager；
- 多模型工作流；
- 节点式 Workflow；
- Plugin System；
- 内置模型管理；
- GPU 检测与推荐；
- 多候选翻译比较；
- 更复杂的项目生态。

如果继续沿此路线开发，项目会越来越接近一套 AI CAT / Translation Management Platform，而不是一个个人可快速完成、日常稳定使用的翻译工具。

因此本 RFC 建议执行一次**Product Reset（产品重置）**：

> **TransRealm = 本地优先的个人 AI 长文本翻译工作台。**  
> UI 只保留用户真正需要的入口；复杂度集中在“智能分段、上下文构造、术语一致性、翻译可靠性和恢复能力”上。

目标不是“功能少”，而是**把复杂度放到真正提高翻译质量的地方**。

---


# 0.1 两轮反审阅后的最终裁定

v1.2 将前两轮反审阅合并为一套**可直接交给开发 Agent 的一致契约**。不再保留已经废止的多目标请求、旧里程碑描述或相互冲突的 DoD。

## 已确认的核心裁定

1. **不从零重写。** 继续复用 SQLite、Migration、Parser、Exporter、Fidelity、Provider、Attempt、Revision、Recovery。
2. **V1 一次模型请求只翻译一个目标 Segment。** 其他 Segment 只作为 Context，不作为本次目标。
3. **不重写现有 per-Segment Attempt 状态机。** lease、fencing、idempotency、retry、finalize 继续按单 Segment 工作。
4. **智能分段必须格式感知。** TXT 可优化；JSON value、字幕 cue、ASS/SSA Dialogue event 默认保持可安全写回的原子边界。
5. **Context Memory 先做 Neighbor + Glossary + Notes。** History Retrieval 属增强项，不阻塞首次可发布版本。
6. **History Retrieval 只承诺重复/近似重复召回。** 默认优先 FTS5 trigram；短查询和运行时不支持 trigram 时走轻量 fallback。
7. **Token 预算采用保守估算 + provider 超界恢复。** 精确 tokenizer 只作为未来可插拔优化，不是 V1 前置条件。
8. **OpenAI-compatible 采用 capability-driven 兼容。** 不把 grammar、guided decoding、reasoning wrapper 等后端私有能力当作统一标准。

## 对外部审阅意见的事实修正

### `is_locked` 已存在

真实 schema 和领域模型已经包含：

```text
translation_revisions.is_locked
```

所以 Product Reset 不为“锁定译文”新增 migration，只复用现有契约。

### API Key 存储已经落地

真实代码已经支持：

```text
env:VAR_NAME
wincred:TARGET_NAME
```

并有 Windows Credential Manager resolver。Product Reset 直接复用，不设计新的明文 secret store。

## 第二轮反审阅的两项反裁定

### Attempt 的边界不能把所有“重试”都塞在一起

现有 Attempt 有单一 `prompt_hash` / context 摘要。若因 context overflow 裁剪 Neighbor / History 后重新构造 Prompt，实际输入已经改变。

因此 v1.2 规定：

```text
同一 Attempt 内：
- transport retry
- 不改变 Prompt/Context 的协议级 capability degradation

新 Attempt：
- Context 被裁剪后重建请求
- Prompt 模板变化
- target 文本变化
- 会改变语义输入的参数变化
- 前一次失败后重新执行 Segment
```

这样审计、幂等和 `prompt_hash` 语义保持清晰。

### `stable_key` 不承担“跨修改文件自动继承历史”的职责

现有 SourceDocument 身份已经包含源文件 hash 与 parser identity。源 bytes 改变（哪怕只是 BOM / CRLF）会形成新的 SourceDocument 身份；V1 不自动把旧 Revision 映射到新文件。

因此 TXT `stable_key` 的目标是：

> 在**同一逻辑映射版本、同一解析结果**下稳定，而不是跨任意文件编辑保持永恒不变。

V1 延续现有思路：

```text
stable_key = hash(logical_sequence + normalized_segment_text)
```

明确禁止 raw byte offset 进入 `stable_key`。byte span 只用于 fidelity locator。

---


# 1. 现状诊断

## 1.1 当前项目的真实工程状态

TransRealm 已经明显不是原型项目，而是具有正式软件工程特征的桌面应用。

仓库当前大致具备：

- 多层架构：`ui → application → domain → infrastructure / adapters`；
- 87 个左右的 `src/transrealm/` 源码文件；
- 56 个左右测试文件；
- 大量 PRD、Roadmap、Technical Design、Database Schema、Prompt Architecture、Architecture Review、Development State、Release Checklist 等治理文档；
- 大量针对 migration、parser、exporter、恢复、UI gate、candidate release 的自动化测试。

这些投入有显著价值，但也说明一个事实：

> 当前主要开发成本已经不再来自“实现翻译”，而来自“维护一个完整平台的契约、迁移、工作流、模式、项目结构和发布治理”。

对于个人自用软件，这是一个需要主动收敛的信号。

---

## 1.2 当前复杂度主要来自哪里

复杂度主要可分为五类。

### A. 产品概念过多

用户需要理解或系统内部需要维护：

- Project；
- Source Document；
- Auto Mode；
- Workbench Mode；
- Provider；
- Model Profile；
- Prompt Override；
- Workflow；
- Glossary；
- Translation Run；
- Revision；
- `.aiproject`；
- Open Directory Project；
- 未来 Character / World State / TM / RAG / Plugin 等。

这些概念单独看都合理，但组合后已经开始超过个人工作台所需的认知负担。

### B. “未来扩展性”提前兑现

原设计为未来能力预留了大量接口、治理和数据模型。

这种设计适合：

- 团队长期维护；
- 明确商业化路线；
- 多人使用；
- 稳定公共 API / 插件生态。

但当前真实约束是：

- 个人项目；
- 开发资源有限；
- 已经开发较久；
- 希望尽快达到“好用且长期可用”。

因此，应优先优化**完成概率**，而不是无限扩展潜力。

### C. 工程治理已经接近正式产品

现有 Development State、Task / Milestone、Release Gate、Review、Migration Gate、保真导出 Gate 等非常严谨。

这些机制不应全部删除，因为它们保护了数据安全；但后续功能开发不应继续把每个小功能升级成一套新的治理子系统。

### D. 翻译质量核心尚未成为开发重心

真正决定个人翻译体验的能力主要包括：

- 分段是否合理；
- 一次请求中包含多少上下文；
- 前后句是否连贯；
- 人名与术语是否一致；
- 历史译法是否能被正确召回；
- Prompt 是否适配不同模型；
- 模型失败时是否能可靠重试；
- 长文本翻译中断后能否继续。

其中恢复能力已经做得较扎实；未来最应该投入的是：

> **Smart Segmenter + Request Builder + Context Memory + Retriever + Prompt Renderer**

而不是继续扩展产品壳层。

---

# 2. 新产品定义

## 2.1 一句话定位

> **TransRealm 是一个本地优先的 AI 长文本翻译工作台，通过智能分段、上下文检索、术语一致性和可靠恢复，让本地模型与在线模型稳定翻译小说、游戏文本、字幕及一般长文本。**

---

## 2.2 目标用户

V1 重置后的核心用户只有一个：

> **软件作者本人，以及与作者使用方式相近的个人高级用户。**

不再同时优化：

- 完全不懂 AI 的普通用户；
- 企业 CAT 用户；
- 多人协作用户；
- 插件开发者；
- 工作流编排用户；
- 模型部署平台用户。

“未来可能开源给别人用”可以保留，但不能再反过来主导近期工程设计。

---

## 2.3 核心成功条件

新版本必须回答四个问题：

1. **能不能快速开始翻译？**
2. **翻译质量是否明显受益于智能分段和上下文？**
3. **长文本翻到一半崩溃后，能不能安全继续？**
4. **新增模型 / 修改 Prompt / 调整术语是否足够简单？**

如果一个功能不能显著改善以上四点之一，则默认不进入近期版本。

---

# 3. 强制范围冻结

## 3.1 V1-Release 必须实现（MUST）

V1 首次可发布版本必须具备：

- 一个统一的“翻译”工作界面；
- 一个 Job 可包含多个 SourceDocument；
- 导入现有已支持格式；
- 文本 / Segment 浏览；
- TXT 格式感知智能分段；
- JSON / 字幕格式安全边界；
- OpenAI-compatible Provider；
- 本地服务通过兼容 API 接入；
- Provider 配置；
- Prompt 模板配置；
- Glossary；
- Project/Job 级 Notes；
- Neighbor Context；
- 可执行的 Context / Token Budget 估算与超界恢复；
- 一请求一目标 Segment 的翻译执行；
- 失败重试；
- Stop；
- Resume；
- 单段重新翻译；
- 手工编辑译文；
- Revision Lock；
- 导出；
- SQLite 持久化；
- 断点恢复；
- 已有格式保真机制不得回退。

**History Retrieval 不属于 V1-Release 硬门槛。**

---

## 3.2 V1-Full 增强目标（SHOULD）

V1-Release 稳定后再完成：

- Translation History Retrieval；
- FTS5 trigram / lexical fallback；
- Context 命中预览；
- Prompt 预览；
- Debug 请求查看；
- Token 使用统计；
- 简单全文搜索；
- 批量选段重新翻译；
- 简单术语自动建议；
- 翻译进度统计；
- 自动保存 UI 布局。

---

## 3.3 V1 明确不做（WON'T）

以下能力从近期 Roadmap 删除或无限期冻结：

- 多目标 Segment batching；
- 节点式 Workflow Editor；
- 多模型自动协作；
- 自动模型路由；
- Plugin System；
- 内置模型下载器；
- 模型安装管理器；
- GPU 自动检测；
- GPU 自动推荐模型；
- Character Data 独立子系统；
- World State 独立子系统；
- Style Preference Memory 独立子系统；
- 完整 CAT 工具替代；
- 多用户；
- 在线协作；
- 云同步；
- 多候选译文对比系统；
- 自动训练模型；
- 通用知识库式 RAG；
- 面向第三方开发者的稳定 Plugin API。

其中部分能力未来可以重新提出 RFC，但不得因为“以后可能需要”而提前加入近期架构。


# 4. UI 重构

## 4.1 主导航只保留三个页面

主导航：

1. **翻译**
2. **模型提供商**
3. **提示词模板**

Glossary / Notes 不作为独立主页面，可作为翻译页内部 Tab 或侧栏。

设置项尽量放入：

- 页面局部设置；
- 高级设置折叠区域；
- 应用菜单中的少量通用设置。

---

# 5. 翻译页设计

## 5.1 页面目标

用户进入软件后，应当在极少操作内完成：

```text
拖入文件
→ 选择 Provider / Model
→ 选择 Prompt
→ 点击翻译
```

所有高级能力都服务于这条路径，不改变这条路径。

---

## 5.2 推荐布局

推荐三栏或两栏 + 底部状态区。

### 左侧：任务与 Segment

展示：

- 当前文件；
- Segment 列表；
- 状态；
- 搜索；
- 失败过滤；
- 待翻译 / 已完成 / 已修改。

避免展示内部数据库对象名。

用户看到的是：

- 文本块；
- 翻译状态；
- 简单编号。

### 中间：原文

显示当前目标 Segment 的原文，以及按需展开的 Context。

支持：

- 上下文浏览；
- 当前段高亮；
- 查看前后文。

### 右侧：译文

显示：

- 当前译文；
- 手工修改；
- 重新翻译；
- 锁定译文。

### 顶部控制条

只保留高频选择：

- Provider；
- Model；
- Prompt；
- 源语言；
- 目标语言；
- Translate；
- Stop。

### 底部状态

显示：

- 当前进度；
- 当前目标 Segment；
- 已完成 / 总数；
- 错误数量；
- 请求耗时；
- 简单 Token 使用量（如可得）。

---

# 6. 删除 Auto / Workbench 双模式

现有 Auto / Workbench 产品概念建议从 UI 和后续产品设计中删除。

原因：

- 两者本质上消费同一翻译内核；
- 差别主要是“显示多少控制项”；
- 模式切换增加 UI 状态、Project 状态与测试复杂度；
- 对个人工具的价值有限。

替代方案：

> **单一 Translation Workspace + Advanced Settings 折叠面板。**

高级用户需要的能力直接在翻译页展开，不需要切换整个产品模式。

旧数据库中的 mode 字段可以：

- 暂时保留；
- 固定映射到新默认模式；
- 不在第一阶段删除 migration 或字段。

这是典型的“UI 删除概念，底层暂不破坏”。

---

# 7. 模型提供商页面

## 7.1 Provider Connection

Provider 只负责连接信息。

建议字段：

```text
name
base_url
api_key_reference
default_model
timeout
max_retries
```

可选：

```text
organization
custom_headers
proxy
```

但第一版不应暴露过多字段。

---

## 7.2 Model Capability

模型级配置只保留真正影响翻译的参数：

```text
model_name
context_window
max_output_tokens
temperature（可选）
top_p（可选）
```

不能假设所有兼容端点支持相同参数。

参数应允许 Provider / Model 声明能力。

---

## 7.3 本地优先的定义

“本地优先”不是“内置运行模型”。

本 RFC 中：

> 本地优先 = 数据与项目默认留在本地；本地模型通过 llama.cpp / Ollama / LM Studio 等 OpenAI-compatible HTTP 服务接入。

因此 V1 **不内置模型下载、量化、运行时管理**。

这样可以避免：

- CUDA / ROCm / DirectML 兼容；
- 模型下载；
- GGUF 管理；
- 显存检测；
- Backend 生命周期；
- 平台特定问题。

---

# 8. Prompt 模板系统

## 8.1 简化目标

现有 Prompt Preset / Override / Profile 的产品概念可以逐步收敛为：

> **Prompt Template**

模板可复制、修改、重命名、删除。

---

## 8.2 推荐变量

V1 内置变量只保证：

```text
{{source_lang}}
{{target_lang}}
{{text}}
{{context}}
{{glossary}}
{{notes}}
```

可选：

```text
{{segment_id}}
{{previous_translation}}
```

避免过早设计复杂模板 DSL。

---

## 8.3 Prompt 渲染原则

Prompt Renderer 输入：

```python
PromptInput(
    source_lang,
    target_lang,
    text,
    context,
    glossary,
    notes,
)
```

输出：

```python
RenderedPrompt(
    system,
    user,
)
```

Renderer 不直接访问：

- SQLite；
- UI；
- Provider；
- Retriever。

这样可测试性最高。

---

# 9. 新核心翻译 Pipeline

建议把产品内部最重要的逻辑收敛为：

```text
Loader
  ↓
Segmenter
  ↓
Request Builder
  ↓
Context Builder
  ↓
Prompt Renderer
  ↓
Translator
  ↓
Response Normalizer / Validator
  ↓
Saver
```

这是新架构的核心。V1 的 Request Builder **不负责把多个目标 Segment 合并成一次模型请求**；它只为一个目标 Segment 组装上下文、预算和调用参数。

其他系统都应该围绕这条 Pipeline 服务，而不是反过来。

---

# 10. Loader

Loader 继续复用已有格式解析能力。

职责：

- 读取文件；
- 调用格式 parser；
- 生成 Source Document；
- 生成 Source Unit / Segment 所需的结构信息；
- 保存 fidelity metadata。

Loader **不能**负责：

- Prompt；
- RAG；
- Provider；
- 翻译；
- 多目标合并。

---

# 11. Segmenter：重点模块

## 11.1 三个必须区分的概念

### Source Unit

由格式 parser 产生的最小可安全定位单位。

例如：

- TXT 的连续文本 span / paragraph；
- SRT / VTT cue；
- ASS / SSA Dialogue Text 字段；
- JSON 中可翻译字符串 value。

### Segment

翻译持久化与恢复的最小目标单位。

要求：

- `stable_key` 稳定；
- 可独立保存状态；
- 可拥有 Attempt / Revision；
- 可映射回 Source Unit / fidelity locator；
- 自动流程始终以 Segment 为 claim / retry / finalize 单位。

### Translation Request

一次模型调用。

**V1 每个 Translation Request 恰好只有一个 target Segment。**

请求可以额外带：

- 前文原文；
- 前文译文；
- 少量后文原文；
- Glossary；
- Notes；
- History hits。

这些内容全部是 Context，不产生本次 Revision。

因此 v1.1 的核心约束是：

```text
1 Request
= 1 target Segment
+ optional Context
```

而不是：

```text
1 Request
= N target Segments
```

---

## 11.2 为什么 V1 不做多目标 batching

现有 TransRealm 的：

- `SegmentAttempt`；
- lease；
- fencing；
- idempotency；
- retry；
- Revision finalize；

都是单 Segment 事务语义。

为了 V1 的短工期与可靠性，优先保留这一成熟执行模型。

如果未来 profiling 证明大量短 Segment 导致 provider round-trip 成为主要瓶颈，再单独设计：

```text
BatchRequest
BatchAttempt
Batch→Segment mapping
partial commit
batch idempotency
```

不能把这些问题隐含塞进当前 M2。

---

# 12. 智能分段算法

## 12.1 第一阶段必须确定性

第一版 Segmenter 不使用 LLM 决定分段。

原因：

- LLM 分段不稳定；
- 难以复现；
- 会增加请求成本；
- Segment identity 容易变化；
- 恢复与 Revision 映射困难。

应采用确定性、版本化、格式感知的 segmentation。

---

## 12.2 Segmentation 必须受格式保真约束

“智能分段”不是全格式统一地按标点拆句。

### TXT

允许进行较积极的规则式分段，但每个 Segment 必须对应**连续、可验证的原始 byte/character span**。

可以使用：

- 段落边界；
- 对话边界；
- 句末标点；
- 长度阈值。

不得产生无法映射回 fidelity metadata 的非连续 Segment。

### JSON

V1 默认：

> 一个被选中的可翻译 string value = 一个 Segment。

不跨 value 合并。

如果单个 value 极长，V1 优先警告 / 使用更大上下文模型；除非 exporter 与 metadata 明确支持该 value 的安全子 span，否则不自动拆成多个可写回 Segment。

### SRT / VTT

V1 强制：

> 一个 cue = 一个 Segment。

禁止因为 token 长度自动硬切 cue。

### ASS / SSA

V1 强制：

> 一个 Dialogue event 的 Text 字段 = 一个 Segment。

禁止自动拆成多个持久化 Segment。

原因：时间轴、事件序号、样式/覆盖标签以及原始 byte span 都属于该 Source Unit 的保真契约。

---

## 12.3 TXT 普通文本规则

推荐流程：

```text
连续源文本
→ 保留段落边界
→ 识别对白
→ 句末标点候选
→ 根据目标长度决定是否合并/切分
→ 生成连续 locator
→ 生成稳定 Segment
```

识别：

- `。`
- `！`
- `？`
- `!?`
- `……`
- `…`
- 引号闭合；
- 段落换行。

规则目标不是追求语言学完美，而是产生：

> 足够大、语义自然、可恢复、可稳定定位的翻译单元。

### TXT 默认段长目标

砍掉多目标 batching 后，Segment 不能退化成“每句一个请求”。

V1 初始默认值采用**软阈值**：

```text
min_target_chars = 200
target_chars = 600
max_target_chars = 1200
```

规则：

- 小于 `min_target_chars` 的相邻短句优先合并；
- 接近 `target_chars` 时优先在自然句末结束；
- 超过 `max_target_chars` 才触发更积极的安全切分；
- 引号未闭合时避免切分；
- 用户高级设置可调整，但不改变已导入 SourceDocument 的现有 Segment 映射。

这些值是初始工程默认，不是翻译质量真理；后续用真实小说样本 benchmark 调整。

---

## 12.4 对话保护

例如：

```text
「你是谁？」
少女抬起头。
「我……不记得了。」
```

Segmenter 应避免在引号未闭合处切分。

但 V1 不要求把这三句强制合并为同一个持久 Segment；即使是不同 Segment，Context Builder 仍可把相邻原文 / 已有译文提供给模型。

这样可以把“持久化边界”和“模型上下文连续性”分开。

---

## 12.5 长文本处理

只有在格式 locator 能安全表达子 span 时才允许硬切。

优先切分位置：

1. 段落；
2. 句末；
3. 分号；
4. 逗号；
5. 最后才考虑安全字符边界。

**字幕 cue / ASS event / 默认 JSON value 不进入这条硬切路径。**

如果一个不可拆 Source Unit 本身超过模型可用预算：

- 不静默截断；
- 不破坏 fidelity；
- 标记为可操作错误；
- 提示更换更大 context 模型或手工处理。

---

## 12.6 Mapping Version 与稳定身份

现有数据库具有：

```text
SourceDocument.parser_version
SourceDocument.format_metadata
Segment.stable_key
```

V1 不新增独立 `segmentation_version` 数据库列。

### Mapping version

`format_metadata` 中新增/明确记录：

```text
segmentation_rule_id
```

例如：

```text
txt.smart.v1
srt.cue.v1
ass.dialogue.v1
json.value.v1
```

`segmentation_rule_id` 用于解释“这个 SourceDocument 是按哪套 Segment mapping 规则产生的”。

如果 **Source Unit / Segment mapping 发生不兼容变化**：

- 必须提升 parser/mapping contract 版本；
- 创建新的 SourceDocument；
- 不复用旧 Segment；
- 不自动 remap 旧 Revision。

如果只是内部实现修复、性能优化，而且**输入到 Segment / locator 的公开 mapping 不变**，可以保持 mapping contract 版本不变。

如果 fidelity metadata 契约本身发生变化，则仍应按现有 parser / metadata versioning 规则升级；不要为了保留历史 Revision 而伪装成同一解析契约。

### TXT `stable_key`

TXT 禁止使用 raw `byte_start` / `byte_end` 作为稳定 key。

V1 延续现有语义：

```text
stable_key = sha256(logical_sequence + normalized_segment_text)
```

其中：

- `logical_sequence` 是当前 SourceDocument 映射内的逻辑顺序；
- `normalized_segment_text` 只做明确、版本化的文本规范化；
- byte span 仅保存在 fidelity locator 中。

这保证：

- CRLF / BOM 的 byte offset 不会直接污染 key；
- 同一 mapping 结果可重复生成相同 key；
- 不承诺在用户编辑源文件、插入/删除前文后自动继承旧 Revision。

已产生 Revision 的旧 SourceDocument：

- 不自动 resegment；
- 新规则创建新 SourceDocument；
- 不自动 remap 历史 Revision。

---


# 13. Request Builder 与 Token Budget

## 13.1 Request Builder

输入：

```text
target Segment
model capability
Prompt template
Context candidates
budget policy
```

输出：

```text
TranslationRequest
```

请求中：

```text
target_segments = 1
```

邻近 Segment 只作为 Context。

---

## 13.2 Token 计量现实

OpenAI-compatible 并不意味着存在统一 `/tokenize` API。

因此 V1 不能把“精确 tokenizer”当作硬前提。

采用分层策略：

### V1：保守通用估算

V1 不把“精确 tokenizer 注入”列为 M2b 验收项，只预留未来 seam。

默认使用两阶段估算：

```text
估算值 = script-aware heuristic
硬上界 = UTF-8 byte length
```

初始 heuristic 可按主要字符类型粗略估算：

```text
CJK-dominant: bytes / 2
Latin-dominant: bytes / 4
mixed: 两类分别累计
```

然后增加：

```text
chat/template overhead
+ safety margin（默认 >= 20%）
```

最终预算不得超过 UTF-8 byte-length 上界所允许的保守值。

这些系数只用于提高上下文利用率，不作为“真实 token 数”。若 provider 返回 context-length error，必须走 §13.3 的重建路径，因此低估不会被静默接受。

### Future Hook

未来若某 Provider / Model 有可靠 tokenizer，可在不改变 Request Builder 上层契约的前提下注入精确 estimator。

---

## 13.3 上下文超界反馈路径

即使预估通过，Provider 仍可能因为真实 tokenizer / chat template 不同返回 context-length error。

这不是 target Segment 的永久失败。

处理：

```text
Attempt A
→ provider 报 context overflow
→ Attempt A 记录失败原因
→ 缩减 History
→ 缩减 Neighbor
→ 必要时裁剪 Notes / Glossary 到各自预算上限
→ 重建 Prompt/Context
→ 创建 Attempt B
→ retry
```

**只要 Prompt / Context 内容发生变化，就必须创建新 Attempt。**

这样：

- `prompt_hash` 始终只描述一个实际逻辑输入；
- idempotency_key 不会把不同 Prompt 当成同一请求；
- audit 与恢复语义保持清晰。

若已经缩减到最小 Context 仍超界：

- 不截断 target；
- 不阻塞队列中的其他 Segment；
- 当前 Segment 标记为可操作失败；
- UI 明确提示更换更大 context 模型、调整配置或手工处理。


## 13.4 默认 context window

未知模型上下文长度时，不宣称自动探测成功。

可以使用保守默认：

```text
4096
```

但 UI 必须明确这是 fallback 值，允许用户调整。

Provider 若明确返回 context-length error，错误提示必须引导用户：

- 检查 model context 配置；
- 或降低当前配置值。

---

# 14. Response Normalizer / Validator

## 14.1 输出协议不再强制全模型 JSON

V1 每次只翻译一个目标 Segment，因此不需要通过 JSON `id → translation` 解决多目标映射。

支持两类输出协议：

### Plain Text

适合：

- Sakura / GalTransl 类翻译特化模型；
- 不稳定支持结构化输出的小模型。

Prompt 要求：

> 只输出译文。

### Structured Output

若 Provider / Model Capability 声明支持，可使用：

- `response_format=json_object`；
- JSON Schema；
- grammar / guided decoding；
- provider-specific structured output。

llama.cpp 与 vLLM 等后端可以提供更强的结构约束，但这些能力属于**可选 Capability**，不是“OpenAI-compatible”统一标准。

---

## 14.2 约束解码的定位

如果 backend 支持 schema / grammar constrained decoding，应优先用于需要机器可解析结构的任务。

但 RFC 不写：

> “使用约束解码即可 100% 保证整个翻译任务正确。”

它最多保证结构层面的约束；仍需验证：

- 内容非空；
- 未截断；
- 没有明显拒答；
- 格式专属要求；
- provider finish reason。

---

## 14.3 Reasoning / think 归一化

不得无条件用正则删除所有 `<think>...</think>`。

原因：不同 Provider 对 reasoning 的承载方式不同，而且正文也可能合法包含类似标签。

应通过 Model Capability / Response Normalizer 处理：

```text
separate reasoning field
known reasoning wrapper
plain content
```

对于明确声明“reasoning in content”的模型，才剥离已知 reasoning wrapper。

---

## 14.4 Validator

至少验证：

- 响应存在；
- target translation 非空；
- finish reason 不表示明显截断；
- structured 模式时 schema 可解析；
- plain 模式时没有把 Prompt / system instruction 大段回显；
- 特殊格式约束满足。

特殊格式至少检查：

- ASS / SSA 覆盖标签不能被意外吞掉（如项目契约要求保留）；
- JSON 写回仍通过 exporter 的转义与 locator 校验；
- SRT / VTT 序号和时间轴不由模型生成、也不能被模型修改。

---

## 14.5 Retry 与 Attempt 归属

### 同一 Attempt 内允许

- HTTP transport retry；
- provider 5xx / timeout 的同请求重发；
- 不改变 Prompt / Context 内容的协议级 capability degradation；
- 例如仅移除不支持的 `response_format` 标志，且 Prompt 本身不变。

### 必须创建新 Attempt

- Context overflow 后裁剪 Context；
- Prompt 模板变化；
- target 文本变化；
- 需要修改 Prompt 才能从 structured 改成 plain；
- 失败 Segment 的再次逻辑执行；
- 会改变语义输入的参数调整。

最终规则：

1. 可恢复 transport 错误在原 Attempt 内有限重试；
2. 输入语义变化则结束当前 Attempt，并创建新 Attempt；
3. 仍失败则 Segment 标记 failed；
4. 永不覆盖已有 locked/current 用户 Revision。

V1 一次请求只有一个 target Segment，因此不存在多目标部分提交问题。

---


# 15. Context Memory：统一替代多个未来子系统

原规划中的：

- Character Data；
- Translation Memory；
- World State；
- Style Memory；
- RAG；

不再作为五个独立系统推进。

新的统一抽象：

> **Context Memory**

Context Memory 不是一个数据库表，而是 Context Builder 可消费的统一语义层。

---

# 16. Context Memory 的 V1 数据来源

## 16.0 作用域契约

V1 用户概念中的 **Translation Job = 现有 Project**。

一个 Job 可以包含：

```text
1..N SourceDocument
```

因此：

- 一本小说的多卷 / 多章节文件可以放在同一个 Job；
- 同一游戏的多个脚本文件可以放在同一个 Job；
- Glossary / Notes 可以跨这些 SourceDocument 复用。

默认导入行为：

```text
存在当前 Job
→ 新文件默认加入当前 Job

用户显式选择“新建任务”
→ 创建新 Job / Project

无当前 Job
→ 自动创建一个 Job
```

Context 作用域：

- Glossary：Job 级（底层仍是现有 `project_id`）；
- Notes：Job 级；
- Translation History：默认仅检索同 Job；
- Neighbor Context：同 SourceDocument；
- V1 不做全局 Glossary / 全局 Notes，避免额外冲突优先级。



V1 只需要四种：

## 16.1 Neighbor Context

当前 Segment：

```text
前 N 段原文 / 译文
当前段
后 N 段原文
```

这是长文本翻译最稳定、最便宜的上下文。

默认：

```text
previous = 2
next = 1
```

具体按 token budget 裁剪。

---

## 16.2 Glossary

继续复用已有 Glossary。

结构至少：

```text
source_term
target_term
note
```

可选：

```text
case_sensitive
priority
```

Glossary 命中必须优先使用确定性匹配。

---

## 16.3 Notes

用户可以写自由文本，例如：

```text
雪乃是女性。
“先生”在本作统一译为“老师”。
主角说话较冷淡。
帝国与王国处于战争状态。
```

第一版不需要结构化 Character / World State 数据模型。

一个 Notes 文本块已经能覆盖大量个人翻译需求。

未来如果明确证明结构化数据产生显著收益，再升级。

---

## 16.4 Translation History

使用已完成 Segment 的：

```text
source_text
translation_text
```

作为历史译法候选。

V1 的 History Retrieval 目标明确限定为：

- 完全重复文本；
- 近似重复文本；
- 重复 UI / 游戏文本；
- 固定表达；
- 高词面重合的历史译法。

**不承诺可靠召回纯语义相似、词面差异很大的句子。**

如果真实 A/B 证明这类语义召回是主要缺口，再进入 Embedding RFC。

---

# 17. RAG-lite

## 17.1 第一版不要直接上向量数据库

初始 Retriever 推荐：

```text
LexicalRetriever
```

默认候选：

- **SQLite FTS5 + `trigram` tokenizer**；
- FTS5 `bm25()` 用于结果排序；
- 必要时增加轻量 n-gram / fuzzy fallback。

不能使用默认 `unicode61` 后就假设 CJK 历史译文检索可用。中文、日文核心路径必须使用适合无空格文本的 tokenizer。

---

### 17.1.1 Trigram 可用性探测

不要假设“Python 3.12 = 一定带可用 trigram FTS5”。

应用启动或首次建立 History Index 时应进行 capability probe：

```sql
CREATE VIRTUAL TABLE ... USING fts5(..., tokenize='trigram')
```

若运行时 SQLite 不支持：

- History Retrieval 降级为简单 `LIKE` + 轻量 RapidFuzz / n-gram；
- 不影响翻译主流程；
- UI / Debug 显示 retrieval backend。

### 短查询

FTS5 trigram 对少于 3 个 Unicode 字符的查询不适合作为唯一检索路径。

因此：

```text
len(query) < 3
→ exact match / normalized equality
→ SQL LIKE
→ 必要时轻量 fuzzy
```

例如两字人名、单字术语不能因为 trigram 后端而直接漏召回。

不要在 RFC 中写死 trigram 索引一定是原文的某个固定倍数；实际体积应通过项目基线 benchmark 记录。

---

# 17.2 为什么先不用 Embedding

Embedding RAG 会额外引入：

- embedding model；
- embedding provider；
- dimension；
- index schema；
- rebuild；
- embedding version；
- language model quality；
- vector DB；
- 相似但语境错误的污染；
- context stale 问题。

如果第一版没有证据证明这些复杂度能显著改善翻译，则不值得进入核心路径。

---

## 17.3 未来升级接口

保留统一接口：

```python
class Retriever(Protocol):
    def retrieve(
        self,
        query: RetrievalQuery,
        limit: int,
    ) -> list[MemoryHit]:
        ...
```

第一版：

```text
LexicalRetriever
```

未来可以：

```text
EmbeddingRetriever
HybridRetriever
```

Context Builder 不应知道 Retriever 内部使用什么搜索技术。

---

# 18. RAG 污染控制

RAG 对翻译最大的风险不是“找不到”，而是“找到错误但看起来相关的东西”。

因此 MemoryHit 必须携带：

```text
source
score
document_id
segment_id
position
```

Context Builder 应考虑：

- 当前文档优先；
- 距离当前 Segment 太近时避免与 Neighbor Context 重复；
- 完全相同文本优先；
- Glossary 优先于历史相似译法；
- 低分结果直接丢弃；
- 跨项目数据默认不检索；
- 手工锁定译文优先于模型自动译文。

---

# 19. Context Builder

统一负责组装：

```text
Neighbor
+
Glossary
+
Notes
+
Retrieved History
```

输出：

```python
TranslationContext
```

---

## 19.1 推荐优先级

建议：

```text
当前原文
> 用户锁定 Glossary
> 用户 Notes
> 邻近上下文
> 完全匹配的历史译文
> 高分历史译文
> 其他候选
```

---

## 19.2 Context Budget

不再把 Context Budget 做成大型独立系统。

V1 先保护：

```text
target Segment
output reserve
system / prompt skeleton
safety margin
```

剩余预算再给 Context。

默认上限采用**预算比例 + 绝对上限二者取较小值**：

```text
Glossary  <= min(15% of model context, 1024 estimated tokens)
Notes     <= min(15% of model context, 1024 estimated tokens)
Neighbor  <= 35% of model context
History   <= 20% of model context（V1-Full）
```

剩余空间保留给 target / output / overhead / safety margin。

规则：

- Glossary 先按命中与 priority 选择，不是把整个术语表塞进去；
- Notes 按段落边界裁剪；
- Notes / Glossary 超限必须在 UI / Debug 给出警告；
- Neighbor 不得被无限挤压到 0，除非 target 本身已经逼近上下文极限；
- History 永远是第一批可裁剪项；
- Context overflow 重建遵循 §13.3。

这些默认值允许后续调参，但 V1 必须有硬上限，不能让用户 Notes 自身撑爆 context window。

---


# 20. 数据持久化策略

## 20.1 不推倒现有 SQLite

现有 SQLite 应继续作为系统核心。

原因：

- 已经过大量测试；
- 已有 Migration；
- 已有恢复能力；
- 已有 Revision；
- 已有 Project / Document / Segment 关系；
- 重写成本与风险过高。

---

## 20.2 Project 概念“内部保留，UI 降级”

用户概念改为：

> **翻译任务 / Translation Job**

底层直接复用现有：

```text
Job = Project
Project 1:N SourceDocument
```

一个 Job 不是“一个文件”。

推荐用户路径：

```text
创建/打开 Job
→ 连续导入多个章节 / 卷 / 字幕文件
→ 共用 Provider / Prompt / Glossary / Notes
→ 每个 SourceDocument 保持自己的 Segment / fidelity mapping
```

“拖入文件”不自动强制创建新 Project：

- 已有当前 Job：默认加入当前 Job；
- 无当前 Job：自动创建；
- 用户需要隔离上下文时：显式新建 Job。

这样既避免数据库大迁移，也保留跨文件长期翻译上下文。


## 20.3 第一阶段禁止做数据库瘦身

Product Reset 第一阶段：

**不得因为字段“看起来不再需要”就删除数据库字段或旧 Migration。**

应：

- 停止使用；
- 标记 deprecated；
- 保持读取兼容；
- 待新版本稳定后再决定是否清理。

---

# 20.4 Notes 最小持久化

Notes 是 V1 新增的唯一简单 Context Memory 数据实体之一。

推荐最小表：

```text
project_notes
- project_id  PK/FK -> projects(id) ON DELETE CASCADE
- text
- updated_at
```

V1 只支持每 Project 一个自由文本 Notes 文档。

不拆：

- Character；
- World State；
- Style；

三套结构化表。

---

# 21. Revision 继续保留

Revision 是值得保留的复杂度。

真实 TransRealm schema 已有：

```text
translation_revisions.is_locked
```

因此 Product Reset **直接复用 existing lock contract，不新增 locked migration**。自动流程必须继续遵守：current revision 为 locked / user-protected 时不得自动替换。

用途：

- 自动翻译；
- 手工修改；
- 重新翻译；
- 回滚；
- 锁定优秀译文；
- 不覆盖旧结果。

推荐来源：

```text
model
manual
retry
import
```

---

# 22. 断点恢复继续作为核心能力

必须保留：

```text
pending
processing
completed
failed
```

程序异常关闭后：

- `processing` 能被安全回收；
- 已完成 Revision 不丢失；
- 手工修改不被覆盖；
- 已完成 Segment 不自动重复请求；
- 用户可以继续未完成部分。

这是个人长文本翻译工具非常高价值的能力，不属于“应删复杂度”。

---

# 23. 文件格式与 Fidelity

现有 TXT / JSON / SRT / ASS / SSA / VTT 支持应该全部保留。

特别是已经完成的：

- 原始 bytes；
- encoding；
- BOM；
- newline；
- format metadata；
- source hash；
- span / locator；
- byte identity；
- 非目标内容不变；

不允许为了“代码简单”退回到：

```text
parse → rebuild whole file
```

格式保真是 TransRealm 已经付出高成本换来的资产。

---

# 24. 现有能力处理矩阵

## 24.1 KEEP：明确保留

- SQLite；
- Migration；
- Source Document；
- Segment；
- Translation Run；
- Revision；
- Attempt；
- Provider Connection；
- OpenAI-compatible Adapter；
- Parser；
- Exporter；
- Fidelity metadata；
- Glossary；
- Recovery；
- Retry；
- Prompt rendering 中可复用部分；
- Green portable build；
- 关键测试。

---

## 24.2 SIMPLIFY：简化

- Model Profile；
- Prompt Override；
- Context Composer；
- Project UI；
- Translation Workflow；
- Debug；
- Application Service 数量；
- 用户设置。

---

## 24.3 FREEZE：停止新增

- `.aiproject` 高级生态；
- Open Directory 双形态继续扩展；
- Auto / Workbench mode；
- Workflow abstraction 扩展；
- Plugin 预留；
- Character / World / Style 独立系统；
- Model Recommendation；
- 多模型 orchestration。

冻结意味着：

- 不再投入新功能；
- 现有代码暂时保留；
- 不影响新核心路径即可；
- 不立刻删除。

---

## 24.4 REMOVE FROM UI：从产品层删除

- Auto / Workbench 模式选择；
- 对普通用户无价值的内部状态；
- 过多 Profile 概念；
- 开放目录内部细节；
- migration / revision 等实现术语。

---

# 25. 为什么不建议从零重写

从零重写的诱惑来自：

> “现在架构太复杂，不如重新做个简单版。”

但这是高风险路线。

你会重新失去：

- 格式保真；
- recovery；
- migration；
- revision；
- parser/exporter；
- provider；
- build；
- 已验证测试。

最终可能经历：

```text
旧项目太复杂
→ 新建简化项目
→ 补功能
→ 补恢复
→ 补格式
→ 补错误处理
→ 再次复杂
```

因此推荐：

> **Strangler Pattern：新 Translation Core 逐渐取代旧 orchestration，而不是重写基础设施。**

---

# 26. 推荐的新模块边界

理想目标，不要求第一天重排目录：

```text
transrealm/
  core/
    segmentation/
      segmenter.py
      request_builder.py

    context/
      builder.py
      budget.py
      retriever.py
      lexical_retriever.py

    translation/
      pipeline.py
      prompt_renderer.py
      validator.py

  providers/
    openai_compatible.py

  persistence/
    repositories.py
    database.py

  formats/
    txt.py
    json.py
    subtitles.py

  ui/
    translation_page.py
    providers_page.py
    prompts_page.py
```

但迁移应渐进。

**禁止为了目录“好看”先做全仓库移动。**

---

# 27. 核心接口边界

V1 不为“架构好看”给每个单实现组件额外套 Protocol。

## 27.1 普通类即可

第一版直接使用普通类：

```text
Segmenter
RequestBuilder
ContextBuilder
PromptRenderer
TranslationValidator
TranslationService
```

只有出现第二个真实实现，或测试替身无法通过现有依赖注入完成时，再抽 Protocol。

## 27.2 保留真实多实现 seam

现有 `ModelAdapter` Protocol 保留，因为 Provider/Adapter 天然存在多实现可能。

Retriever 也保留最小 Protocol，因为 V1-Full 已明确存在：

```text
FTS5TrigramRetriever
FallbackLexicalRetriever
```

未来还可能增加：

```text
EmbeddingRetriever
HybridRetriever
```

参考：

```python
class Retriever(Protocol):
    def retrieve(
        self,
        query: RetrievalQuery,
        limit: int,
    ) -> list[MemoryHit]:
        ...
```

不要为尚不存在的实现预先抽象更多接口。

---


# 28. 依赖方向

建议：

```text
UI
 ↓
Translation Application Service
 ↓
Pipeline
 ├─ Segmenter
 ├─ RequestBuilder
 ├─ ContextBuilder
 ├─ PromptRenderer
 ├─ Translator
 └─ Validator

Pipeline
 ↓
Repository Interfaces

Infrastructure
 ├─ SQLite
 ├─ HTTP Adapter
 └─ Parsers / Exporters
```

必须禁止：

```text
UI → SQLite
UI → HTTP
Prompt Renderer → Repository
Retriever → UI
Parser → Translator
```

---

# 29. 新 Translation Application Service

UI 最好只调用一个主要翻译门面：

```python
TranslationService
```

高层接口类似：

```text
create_job()
import_file()
start()
stop()
resume()
retry_failed()
retranslate_segment()
edit_translation()
export()
```

内部再协调各种现有 Service。

这样可以减少 UI 对大量 application service 的耦合。

---

# 30. Provider 与 Prompt 解耦

Provider 负责：

> 怎么调用模型。

Prompt Template 负责：

> 给模型说什么。

Model 配置负责：

> 模型上下文与采样限制。

不要再次把它们合成一个巨型 Model Profile。

可以提供“Preset”，但 Preset 本质是配置引用，不应成为新的领域模型。

---

# 30.1 OpenAI-compatible 的兼容边界

“OpenAI-compatible”不是“所有参数完全相同”。

现有 Adapter 已具有：

- `ModelCapability`；
- supported parameter filtering；
- structured-output capability；
- capability degradation；
- `extra_params`。

Product Reset 应继续沿用 capability-driven mapping。

至少处理：

```text
max_tokens
max_completion_tokens
```

等已知输出 token 参数差异。

内部建议使用统一语义：

```text
max_output_tokens
```

再由 Adapter / Capability 映射到 provider 实际字段。

同样：

- `temperature`；
- `top_p`；
- `response_format`；
- streaming；

只有 Capability 声明支持时才发送。

不能把某个后端私有的 `grammar` / guided decoding 参数当成所有 OpenAI-compatible 服务的公共字段。

---

# 31. 错误模型

错误至少分为：

```text
ImportError
SegmentationError
ProviderConnectionError
ModelRequestError
ModelTimeoutError
ResponseParseError
ResponseValidationError
PersistenceError
ExportError
```

UI 需要显示用户可理解的错误。

日志保留详细异常。

---

# 32. Debug 设计

Debug 不需要成为复杂系统。

第一版允许用户打开：

- Rendered Prompt；
- 请求参数；
- Raw Response；
- Context hits；
- Validator Error。

API Key 必须始终脱敏。

---

# 33. 安全与隐私

本地优先的最低要求：

- API Key 不进入 Project；
- API Key 不进入 Debug log；
- 复用现有 `credential_reference`：`env:` / `wincred:`；
- Windows 默认优先使用 Windows Credential Manager，不新增明文 secret 配置格式；
- Project 默认本地；
- 不自动上传源文件；
- 在线 Provider 只发送当前请求需要的文本与 Context；
- Debug 明确提示可能包含原文和译文；
- 删除 Debug 时可彻底清理。

---

# 34. AITranslator 借鉴边界

参考 AITranslator 的：

- UI 简单；
- 翻译路径直接；
- Provider 配置直观；
- 功能集中；
- 不让复杂底层概念主导 UI。

但不建议直接复制其源码。

原因：

- AITranslator 使用 GPL-3.0；
- TransRealm 当前许可证策略不同；
- 直接复制 GPL 代码会产生许可证传播问题。

因此采用：

> **借鉴产品理念与交互模式，不复制实现。**

---

# 35. Milestone 规划

整个 Product Reset 采用六个阶段：M0、M1、M2a、M2b、M3、M4。

---

# M0：Freeze & Baseline

## 目标

冻结旧 Roadmap，建立改造安全基线。

## 工作

- 标记原 Phase 2 / 3 / 4 为 archived；
- 新建 Product Reset RFC；
- 创建 Git tag / branch；
- 记录全量测试结果；
- 记录当前数据库 schema；
- 记录当前格式 round-trip；
- 记录现有 UI 功能；
- 不删代码。

## 验收

- baseline 可恢复；
- 原有测试仍通过；
- 现有用户数据可正常打开；
- Product Reset 范围正式冻结。

---

# M1：Unified Translation Workspace

## 目标

把 UI 收敛为：

```text
Translation
Providers
Prompts
```

## 工作

- 新 Translation Page；
- 移除 UI Auto / Workbench；
- Provider Page；
- Prompt Template Page；
- Glossary / Notes 集成；
- Job 1:N SourceDocument 导入行为；
- 无当前 Job 时自动创建，已有 Job 时默认加入；
- Project 内部化。

## 不做

- 新 Segmenter；
- RAG；
- embedding。

## 验收

用户可以：

```text
打开软件
→ 导入文件
→ 选模型
→ 选 Prompt
→ 翻译
→ 修改
→ 导出
```

不需要理解 Project / Workflow / Mode。

---

# M2a：Format-aware Smart Segmentation

## 目标

在不破坏 fidelity / recovery 的前提下改善持久 Segment 边界。

## 工作

- Source Unit / Segment / Translation Request 语义明确；
- TXT deterministic、dialog-aware segmentation；
- JSON / 字幕格式冻结安全边界；
- mapping/parser version 升级规则；
- stable_key fixture；
- 旧 SourceDocument 不自动 resegment。

## 验收

至少覆盖：

- 中文；
- 日文；
- 英文；
- 对话；
- 长段落；
- 极长文本；
- JSON；
- SRT/VTT；
- ASS/SSA。

要求：

- 相同输入 + 相同 mapping version 生成稳定 `stable_key`；
- fidelity locator 仍可验证；
- 已有 Revision 文档不被静默 resegment；
- 新 segmentation 通过新 mapping/parser version 建立新 SourceDocument；
- 重启可恢复。

---

# M2b：Single-Segment Request / Budget / Validation

## 目标

让新的翻译请求在不同 Provider / Model 上可靠执行，而不重写现有 per-Segment Attempt 状态机。

## 工作

- `1 Request = 1 target Segment`；
- Request Builder；
- conservative token estimator；
- context overflow shrink/retry；
- plain-text output；
- optional structured-output capability；
- reasoning normalization；
- validator；
- retry；
- Stop 契约。

## Stop 契约

默认采用 graceful stop：

```text
用户 Stop
→ 不再 claim 新 Segment
→ 已经 in-flight 的请求允许返回
→ 有效结果正常 finalize
→ 未开始 Segment 保持 pending
```

不要求 V1 提供“强杀 HTTP 请求并撤销计费”。

## 并发

- 默认 `max_in_flight = 1`；
- Provider 可选设置有限并发；
- 并发请求之间仍保持“一请求一 Segment”；
- 每个 Segment 独立 lease / Attempt / Revision；
- 落库顺序不要求等于 source sequence；
- exporter 仍按 Segment sequence 读取最终 Revision。

### Neighbor 译文的确定性

Neighbor Source Text 始终可以确定性读取。

Previous Translation 只读取 **Request 构建时已经 commit 的 current Revision**。

因此：

```text
concurrency = 1
→ 可获得最稳定、最可复现的 previous translation context

concurrency > 1
→ previous translation context 为 best-effort
→ Prompt 可能因调度顺序不同而不同
```

实际发送的 Prompt / context summary / hash 继续随 Attempt 记录，保证事后可审计。

如果用户要求严格可复现，使用 `max_in_flight = 1`。

## 验收

- unknown tokenizer 不导致静默截断；
- context overflow 能自动缩减 Context 后重试；
- structured unsupported 可按 policy 降级；
- reasoning model 输出可归一化；
- Stop 后不再产生新 claim；
- completed / locked Revision 不被重试覆盖。

---

# M3：Context Memory / RAG-lite

## 目标

提高长文本一致性。

**M3 是 V1 的增强里程碑，不是首次“可发布/可长期使用”版本的硬阻塞。**

V1-Release 已包含：

```text
Neighbor + Glossary + Notes
```

M3 主要增加：

```text
Translation History Retrieval
+ retrieval debug / A-B evidence
```

因此 M3 未完成时仍可发布 V1-Release；完成 M3 后达到 V1-Full。

## 工作

- Neighbor Context；
- Glossary；
- Notes；
- Translation History；
- SQLite FTS5 trigram（运行时探测）/ lexical fallback；
- Context Builder；
- Budget；
- Debug Context Preview。

## 验收

真实长文本 A/B：

```text
无 Context
vs
Neighbor only
vs
Neighbor + Glossary + History
```

至少观察：

- 人名一致性；
- 术语一致性；
- 指代；
- 对话连续性；
- 模型错误率；
- token 开销。

只有 A/B 证明有价值，才继续增加复杂检索。

---

# M4：Polish & Finish

## 目标

宣布一个“功能完成”的版本。

## 工作

- UI 清理；
- 翻译进度；
- 单段重译；
- 批量 retry；
- 搜索；
- 错误提示；
- Debug；
- 文档；
- 绿色版；
- Regression；
- Release。

## 硬规则

M4 后不允许因为“还可以再加”延迟发布。

---

# 36. 工期控制规则

为避免再次无限延期，采用以下规则：

### Rule 1

任何新增功能必须回答：

> 它会提高翻译质量、速度、稳定性或日常便利性中的哪一项？

无法回答则不进入 V1。

### Rule 2

估计超过一个 Milestone 才能完成的功能必须拆分。

### Rule 3

不能因为“架构更漂亮”进行大规模重写。

### Rule 4

没有真实 A/B 收益证据，不增加 embedding / agent / multi-model 等复杂能力。

### Rule 5

V1 发布后才能重新讨论 Plugin、Workflow Editor 等平台化功能。

---

# 37. 测试策略

## 37.1 保留现有回归测试

重点保留：

- Migration；
- SQLite；
- Parser；
- Exporter；
- Fidelity；
- Recovery；
- Revision；
- Provider；
- Prompt；
- Build。

---

## 37.2 新增 Segmenter Fixture

建议建立：

```text
tests/fixtures/segmentation/
```

包含：

- zh novel；
- ja light novel；
- en prose；
- dialogue；
- mixed punctuation；
- ellipsis；
- quotes；
- subtitle；
- huge paragraph；
- malformed text。

测试：

```text
input
expected_segments
```

---

## 37.3 Request Budget / Context 测试

验证：

- 一次 Request 恰好一个 target Segment；
- token/context budget；
- Notes / Glossary hard cap；
- Neighbor 裁剪；
- context overflow 后新建 Attempt；
- oversized atomic Segment 的可操作失败；
- provider context error 不阻塞队列其他 Segment；
- 并发下只读取已 commit 的 previous translation。

---

## 37.4 Response Normalizer / Validator 测试

模型模拟：

- 正常 plain-text 译文；
- 空译文；
- Prompt 大段回显；
- finish_reason 截断；
- reasoning 独立字段；
- 已知 reasoning wrapper；
- structured JSON 正常；
- structured JSON 非法；
- provider 不支持 structured 后 capability degradation；
- structured→plain 需要改 Prompt 时创建新 Attempt。

---

## 37.5 Recovery 测试

故障点：

```text
请求前
请求中
响应后
validator 前
revision 写入前
revision 写入后
segment 状态更新前
```

要求：

- 无数据损坏；
- 已完成不丢；
- 未完成可重试；
- manual locked revision 不被覆盖。

---

# 38. 性能与吞吐基线

不制定跨硬件的绝对 SLA，例如“4000 cue 必须 <2 小时”。

原因：

- GPU 差异；
- 模型大小；
- 量化；
- context 长度；
- 解码参数；
- 后端实现；

都会显著改变绝对耗时。

V1 建立**可重复的参考基线**：

## 38.1 数据集

至少记录：

```text
10 万字 TXT
4000 cue SRT
```

记录：

- Segment 数；
- 平均 / P50 / P95 段长；
- 请求数；
- 平均 provider latency；
- model tokens/s（若可得）；
- wall-clock；
- SQLite 大小；
- import 时间；
- UI 内存峰值。

## 38.2 两类 benchmark

### Fake Provider

固定响应延迟，用于测：

- scheduler；
- SQLite；
- lease；
- concurrency；
- UI；

本身的开销。

### Real Local Model

在**明确记录硬件 / 模型 / 量化 / backend / concurrency** 的环境下测真实吞吐。

结果用于建立项目基线，不作为跨机器统一 SLA。

## 38.3 Multi-Segment Batching RFC 的 Go/No-Go

只有 profiling 满足以下之一，才允许重新讨论 batching：

- 在安全并发已经调到合理值后，provider round-trip / orchestration 等待仍占 wall-clock 的显著比例（建议观察阈值 >30%）；
- 模型/GPU 明显空闲，而单目标请求调度是主要瓶颈；
- batching 的预期收益足以覆盖 BatchAttempt / partial commit / batch idempotency / recovery 的复杂度。

在此之前，不因为“理论吞吐更高”提前重写执行状态机。

---


# 39. RAG 的 Go / No-Go 条件

只有出现以下真实问题之一，才升级 embedding：

- FTS / lexical 明显召回不了语义相近历史译法；
- 人名或固定表达之外存在大量“语义相似上下文”需求；
- A/B 测试显示 embedding retrieval 能稳定改善翻译；
- token 成本与延迟可接受。

否则：

> Lexical RAG 保持默认实现。

---

# 40. 最重要的风险

## 风险 A：Product Reset 变成“大重构”

症状：

- 大量 rename；
- 大量目录移动；
- 删除旧 schema；
- 重写 repository；
- 重写 parser。

缓解：

> 新 Pipeline 先适配旧基础设施。

---

## 风险 B：智能分段变得过度智能

症状：

- 规则越来越多；
- 每种语言独立算法；
- 依赖 NLP 大模型；
- Segment ID 不稳定。

缓解：

> deterministic + minimal heuristic。

---

## 风险 C：RAG 引入错误上下文

症状：

- 找到旧角色；
- 相似句但不同场景；
- 历史错误译法反复传播。

缓解：

- 同文档优先；
- score threshold；
- 用户锁定优先；
- Debug 显示命中；
- 默认 limit 很小。

---

## 风险 D：Prompt 模板无限复杂

缓解：

> 不建立 DSL；只做变量替换。

---

## 风险 E：为了支持所有模型损失可维护性

缓解：

> V1 只保证 OpenAI-compatible。

---

## 风险 F：旧代码永久堆积

Product Reset 初期允许旧代码冻结。

但在稳定版本后，可以根据覆盖率删除：

- 无 UI 调用；
- 无数据依赖；
- 无 migration 兼容依赖；
- 已被新 pipeline 完全替代；

的旧模块。

删除必须单独进行，不与功能开发混在同一个 Milestone。

---

# 41. 关键架构决策记录（ADR）

## ADR-001：不从零重写

**Decision:** 保留现有数据库、parser、exporter、recovery、provider。

**Reason:** 已验证资产价值远高于重写收益。

---

## ADR-002：一个 Request 只翻译一个 Segment

**Decision:** V1 每个模型请求恰好一个 target Segment；邻近 Segment 只作为 Context。

**Reason:** 直接复用现有 per-Segment Attempt / lease / fencing / idempotency / Revision 契约，避免为了 batching 重写恢复内核。

---

## ADR-003：统一 Context Memory

**Decision:** 不在近期实现 Character / World / Style / TM 多套系统。

**Reason:** 用户真正需要的是“正确上下文”，不是多个领域对象。

---

## ADR-004：RAG 先 lexical

**Decision:** V1-Full 默认 SQLite FTS5 trigram；短查询与运行时不支持时走轻量 lexical fallback。

**Reason:** 低复杂度、可解释、易维护。

---

## ADR-005：单一翻译工作台

**Decision:** 删除产品层 Auto / Workbench。

**Reason:** 两种模式的真实价值不足以支撑额外状态与测试复杂度。

---

## ADR-006：Provider 只做 OpenAI-compatible

**Decision:** 不首发原生多厂商 SDK。

**Reason:** 大幅减少 Adapter 数量。

---

# 42. 建议的开发顺序

严格顺序：

```text
1. Freeze old roadmap
2. Baseline test
3. New Translation Workspace
4. Prompt Template simplification
5. Translation facade
6. Format-aware Smart Segmenter
7. Single-Segment Request Builder
8. Token Budget + overflow recovery
9. Response Normalizer / Validator
10. Context Builder
11. Notes
12. Lexical Retriever（可延后）
13. Real-world A/B
14. Polish
15. Release
```

Embedding、Character Data、Workflow 等不得插队。

---

# 43. Definition of Done

## 43.1 V1-Release DoD

满足以下条件即可发布 Product Reset 的首个正式可用版本：

- 一个新用户不用读架构文档即可翻译文件；
- UI 主导航不超过三个核心页面；
- Job 1:N SourceDocument 可正常使用；
- 可以使用本地 OpenAI-compatible 服务；
- 可以使用在线 OpenAI-compatible 服务；
- 可以编辑 Prompt；
- 可以维护 Job 级 Glossary；
- 可以维护 Job 级 Notes；
- Neighbor Context 可用；
- TXT 智能分段稳定且有默认段长目标；
- JSON / SRT / VTT / ASS / SSA 保持格式安全边界；
- `stable_key` 不依赖 raw byte offset；
- Request Builder 一次只构造一个 target Segment；
- Provider 超界时可以安全重建新 Attempt；
- Stop / Resume 语义明确；
- 默认单并发可获得最稳定的上下文复现；
- 手工 / locked Revision 不会被自动覆盖；
- 程序崩溃后不会丢失已完成翻译；
- TXT / JSON / SRT / ASS / SSA / VTT 导出不发生格式保真回退；
- 旧 Project / `.aiproject` / open directory 兼容路径仍可打开；
- 全量关键 regression 通过；
- Windows 绿色版能启动；
- 文档明确写出非目标；
- 不以“未来还能加功能”为理由延期。

## 43.2 V1-Full DoD

在 V1-Release 基础上增加：

- Translation History Retrieval；
- CJK 使用 FTS5 trigram 或明确 fallback；
- `<3` 字符 query 有 exact / LIKE 路径；
- History 只承诺重复 / 近似重复召回；
- retrieval hit 可在 Debug / Context Preview 中解释；
- 固定样本 A/B 证明 History 不显著增加术语/指代错误；
- 有真实 retrieval / index 性能基线。

V1-Full 未完成不阻塞 V1-Release。

---


# 44. 明确待审阅的问题

以下问题故意保留给反审阅模型。

## Q1

Auto / Workbench 是否真的应该彻底移除，还是只应该隐藏？

请审阅：

- 是否存在不可替代的 mode semantic；
- mode 是否影响已有数据库行为；
- 去除后是否破坏 workflow / profile contract。

---

## Q2

现有 Segment / SourceDocument schema 是否足以支持新的格式感知智能分段？

请审阅：

- ID 稳定策略；
- re-segmentation；
- 原 Revision 的迁移；
- format locator；
- subtitle cue 的特殊性。

---

## Q3

重新分段是最危险的数据迁移之一。

必须明确：

> 文档已经产生 Revision 后，是否允许改变 Segment boundary？

候选策略：

A. 永不自动 resegment 已翻译文档。  
B. 新建 segmentation version。  
C. 尝试 revision remap。  

本 RFC 倾向：

> **A + B，禁止自动 remap。**

请重点攻击这一选择。

---

## Q4

v1.2 已决定 V1 不做多目标 Segment batching。

请反审阅：

- 这个取舍是否过度牺牲吞吐；
- 真实 10 万字小说 / 数千条字幕是否会因 round-trip 数过多而不可接受；
- 有限并发能否足够缓解；
- 在什么 profiling 证据下应该重新引入 BatchRequest。

---

## Q5

Neighbor Context 应发送原文还是译文？

候选：

- previous source；
- previous translation；
- 两者都发。

需要通过 token / quality A/B 决定。

---

## Q6

FTS5 trigram + lexical fallback 是否足以支撑 V1 的“重复/近似重复历史译文召回”目标？

请寻找：

- runtime SQLite 无 trigram 时的降级；
- 少于 3 字符查询的行为；
- CJK BM25 排名质量；
- 索引体积与更新成本；
- 何种证据足以触发 embedding RFC。

---

## Q7

Glossary + Notes + History 是否会造成 Prompt token 膨胀？

请检查 Context Budget 方案是否足够严格。

---

## Q8

现有 Model Profile 是否真的应该简化？

可能存在已经依赖：

- capability；
- parser；
- prompt preset；
- output contract。

需要确认不能因 UI 简化而破坏 Adapter 行为。

---

## Q9

旧 `.aiproject` / open directory 是否应该继续完整支持？

本 RFC 倾向：

> 保留兼容，但停止扩展。

请审阅维护成本是否仍然过高。

---

## Q10

当前 UI 改造是否应该复用现有 `pages.py`，还是建立新 page 再切换？

本 RFC 倾向：

> 新建简化页面，逐步替换，不在 `pages.py` 内继续堆逻辑。

---

# 45. 反审阅任务说明

将本 RFC 提交给 Kimi K3、Claude、GPT、Gemini 等模型时，不要只问：

> “这个方案怎么样？”

推荐使用以下任务：

---

## Review Prompt A：架构漏洞

> 你是资深桌面应用 / AI 翻译系统架构师。请对这份 TransRealm Product Reset RFC 进行敌对式架构审阅。不要总结文档。重点寻找：隐藏耦合、错误抽象、迁移风险、Segment/Request 设计漏洞、SQLite schema 不兼容、RAG 污染、Prompt 输出可靠性、格式保真回归、崩溃恢复漏洞。每一个问题必须说明触发条件、影响、严重级别、建议修复方式。优先寻找会导致返工超过一周的问题。

---

## Review Prompt B：过度设计

> 请从“个人开发者、希望尽快完成产品”的角度审阅此 RFC。专门寻找仍然存在的过度设计。指出哪些模块、接口、数据模型、测试或兼容策略其实仍然可以删除或延后。不要因为架构优雅而保留功能。

---

## Review Prompt C：过度简化

> 请反过来审阅：这份 RFC 是否为了缩短工期而错误删除了真正重要的能力？重点检查长篇小说、Galgame、字幕、本地小模型、断点恢复、术语一致性、格式导出和历史翻译上下文。

---

## Review Prompt D：数据安全

> 只审阅数据生命周期：import、segment、translate、revision、manual edit、retry、crash、resume、resegment、export。找出任何可能导致译文丢失、错误覆盖、Segment 对不上原文、导出污染原文件的路径。

---

## Review Prompt E：RAG

> 只审阅 Context Memory / RAG-lite。判断 Neighbor + Glossary + Notes + Lexical Translation History 是否合理。列出 embedding 应提前引入和不应提前引入的证据标准，并分析 CJK 检索问题。

---

# 46. 要求审阅模型输出的固定格式

建议要求审阅者使用：

```text
BLOCKER
- ...

SHOULD-FIX
- ...

MAY-FIX
- ...

OVERENGINEERED
- ...

MISSING
- ...

WRONG ASSUMPTIONS
- ...

PROPOSED PATCH
- ...
```

这样便于多模型审阅结果合并。

---

# 47. 审阅裁定规则

收到模型审阅意见后，不应“全部接受”。

每条问题必须分类：

```text
ACCEPT
PARTIAL
REJECT
NEEDS-EVIDENCE
```

只有以下情况修改 RFC：

- 能证明存在数据安全风险；
- 能证明实现成本被明显低估；
- 能证明设计破坏旧项目兼容；
- 能证明某复杂度实际上是必要复杂度；
- 有真实 benchmark / A/B 支持。

不得因为：

> “未来可能需要”

重新引入被砍掉的平台能力。

---

# 48. 开发阶段禁止事项

在 Product Reset 完成前：

- 不新增 Plugin；
- 不新增 Workflow Editor；
- 不新增 Character DB；
- 不新增 World State；
- 不新增 embedding vector DB；
- 不新增模型下载；
- 不更换 GUI 技术栈；
- 不从 Python 改 C#；
- 不重写 SQLite；
- 不重写 parser/exporter；
- 不做大规模目录搬迁；
- 不做无用户价值的架构“纯化”。

---

# 49. 最终目标状态

最终 TransRealm 应该给人的感觉不是：

> “这是一个能配置复杂 AI 翻译 workflow 的平台。”

而是：

> “把小说/字幕/游戏文本拖进去，选择自己的本地模型或 API，它会合理分段、带上正确上下文、保持术语一致，然后稳定地翻完；中途关机也没关系。”

这就是新的产品完成定义。

---

# 50. 最终建议

本 RFC 的最终建议可以浓缩成一句话：

> **保留 TransRealm 已经付出高成本验证过的可靠底座，停止继续平台化；重做上层产品边界，把未来开发资源集中到 Smart Segmentation、Single-Segment Request、Context Memory 和 Translation Reliability 四个真正影响个人翻译体验的核心能力上。**

这样做的目的不是降低技术水平，而是把工程复杂度从：

```text
产品平台复杂度
```

转移到：

```text
翻译质量复杂度
```

后者才是 TransRealm 作为个人 AI 翻译工作台真正需要拥有的技术壁垒。

---

# Appendix A：当前资产与新架构映射

```text
Current Project
→ Internal Translation Job

Current SourceDocument
→ Keep

Current Segment
→ Keep, clarify semantic

Current TranslationRun
→ Keep

Current SegmentAttempt
→ Keep

Current TranslationRevision
→ Keep

Current ProviderConnection
→ Keep

Current ModelProfile
→ Simplify / compatibility layer

Current PromptOverride
→ Migrate toward editable PromptTemplate

Current TranslationWorkflow
→ Freeze

Current ContextComposer
→ Refactor toward new ContextBuilder

Current Glossary
→ Keep

Current Parser
→ Keep

Current Exporter
→ Keep

Current Fidelity
→ Keep

Auto / Workbench
→ Remove from product UI

Future CharacterData
→ Notes / future optional structured memory

Future WorldState
→ Notes

Future StyleMemory
→ Notes / Prompt

Future TranslationMemory
→ Translation History Retriever

Future RAG
→ Retriever interface

Future ContextBudgetManager
→ lightweight Context Budget

Future PluginSystem
→ Freeze

Future ModelManager
→ Freeze
```

---

# Appendix B：最小实现的单 Segment Context 示例

V1 默认允许 plain-text translation，不要求所有模型输出 JSON。

```text
[SYSTEM]

你是一名专业日译中翻译模型。
将日文翻译为简体中文。
保持人名、术语和上下文一致。
只输出当前目标段的中文译文，不要解释，不要输出原文。

[GLOSSARY]

雪乃 -> 雪乃
先生 -> 老师

[NOTES]

雪乃为女性。
主人公说话风格偏冷淡。

[PREVIOUS CONTEXT]

JP: 彼女は窓の外を見ていた。
ZH: 她望着窗外。

[RELATED HISTORY - optional / V1-Full]

JP: 先生はまだ来ていない。
ZH: 老师还没有来。

[TARGET SEGMENT]

「先生は？」

[EXPECTED RESPONSE]

“老师呢？”
```

如果某 Provider / Model 明确支持 structured output，可以选择结构化协议；但它不是 V1 默认路径，也不能改变“一次请求只有一个 target Segment”的契约。

---


# Appendix C：Product Reset 完成后的 Roadmap 原则

未来版本只能从真实使用痛点产生。

例如：

如果实际使用发现：

> “历史译文 lexical search 总搜不到语义相近内容。”

才建立：

> Embedding Retrieval RFC。

如果实际使用发现：

> “Notes 太长，人物设定难维护。”

才建立：

> Structured Character Memory RFC。

如果实际使用发现：

> “不同模型需要不同后处理。”

才扩展：

> Model Capability / Output Strategy。

不要提前实现。

---

# Appendix D：第二轮反审阅后的剩余验证项

v1.2 不要求第三轮全量架构审阅。开工前只需做一次**实现前 Reality Check**，确认真实代码没有与 RFC 新契约冲突。

重点核验：

1. 当前 TXT parser 的 `stable_key` 与新 smart segmentation 的迁移方式；
2. `format_metadata` 增加 `segmentation_rule_id` 是否需要 metadata schema version bump；
3. Notes 新表的 migration 编号与备份路径；
4. Context overflow error 的 provider 分类能否稳定识别；
5. `max_tokens` / `max_completion_tokens` capability mapping；
6. concurrency >1 时 lease / SQLite 写入是否已有足够测试；
7. FTS5 trigram 在实际 Windows 构建产物中的 capability probe；
8. M1 新 UI 是否完全绕开 Auto / Workbench 产品概念，而不破坏旧项目读取。

若 Reality Check 出现真实代码证据与 RFC 冲突，使用：

```text
FIT
ADAPT
REPLAN
```

处理；不得因为“可能以后需要”重新打开已经冻结的平台功能。

---

**End of RFC v1.2**
---

**End of RFC v1.1**
