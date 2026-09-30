# TransRealm 产品定义

> 状态：当前产品范围的唯一权威来源。实现进度只记录在 `tasks/README.md`，当前代码事实以代码、migration、schema 与测试为准。

## 1. 产品定位

TransRealm 是一个本地优先的个人 AI 长文本翻译工作台。它通过格式感知分段、上下文构造、术语一致性和可靠恢复，让本地模型与在线模型稳定翻译小说、游戏文本、字幕及一般长文本。

“本地优先”表示项目数据默认保留在本地；本地模型通过 llama.cpp、Ollama、LM Studio 等 OpenAI-compatible HTTP 服务接入。TransRealm 不内置模型下载、量化、运行时或 GPU 管理。

## 2. 目标用户与成功条件

V1 只面向软件作者本人及使用方式相近的个人高级用户，不同时优化企业 CAT、多人协作、工作流编排或第三方插件开发场景。当前交付只保证用户本机可用，以本机 EXE/ZIP 绿色版完成核心流程为验收，不要求纯净系统或其他电脑兼容性证明。

产品成功必须体现为：能快速开始翻译；智能分段与上下文能改善长文本质量；中断或崩溃后能安全继续；新增 Provider、调整 Prompt 和维护术语足够简单。不能明显改善翻译质量、速度、稳定性或日常便利性的能力，不进入 V1。

## 3. V1-Release MUST

- 一个统一的翻译工作界面；一个 Job 可包含多个 SourceDocument。
- 导入和导出 TXT、JSON、SRT、VTT、ASS、SSA，已有格式保真不得回退。
- TXT 使用确定性、版本化、格式感知的智能分段；JSON string value、字幕 cue、ASS/SSA Dialogue event 保持安全原子边界。
- OpenAI-compatible Provider；本地和在线兼容端点共用 capability-driven 接入。
- Provider 配置、模型设置与可编辑 Prompt 模板。
- Job 级 Glossary 与 Notes，以及 Neighbor Context。
- 可执行的 Context/Token Budget 估算；Provider 超界后可安全裁剪并以新 Attempt 重建请求。
- 一次模型请求恰好翻译一个目标 Segment；其他 Segment 只能作为 Context。
- 失败重试、Stop、Resume、单段重译、手工编辑、Revision Lock 与导出。
- SQLite 持久化、断点恢复、lease/fencing/idempotency、Attempt/Revision 审计。
- 旧 Project、`.aiproject` 与 open-directory 兼容路径仍可打开。
- Windows EXE/ZIP 绿色版在用户本机可启动并完成核心流程，关键 regression 通过。

## 4. V1-Full SHOULD

V1-Release 稳定后，再按真实使用证据增加：

- Translation History Retrieval；优先 SQLite FTS5 trigram，短查询或运行时不支持时使用轻量 lexical fallback。
- Context 命中与 Prompt 预览、Debug 请求查看、Token 使用统计。
- 简单全文搜索、批量选段重译、简单术语建议、进度统计和 UI 布局自动保存。

History Retrieval 只承诺重复或近似重复译法召回，不是 V1-Release 发布门槛。没有固定样本 A/B 价值证据，不引入 embedding 或通用 Vector RAG。

## 5. V1 WON'T

- 多目标 Segment batching。
- 节点式 Workflow Editor、多模型自动协作或自动模型路由。
- Plugin System 或面向第三方开发者的稳定 Plugin API。
- 内置模型下载、安装、运行时、GPU 检测或模型推荐。
- Character、World State、Style Preference、Translation Memory 等独立子系统。
- 完整 CAT 替代、通用知识库 RAG、多候选译文比较或自动训练模型。
- 多用户、在线协作或云同步。

这些能力只有在真实使用痛点和独立 RFC 支持时才可重新提出；“未来可能需要”不是提前实现的理由。

## 6. 页面与用户路径

主导航最多三个页面：

1. **翻译**：Job、SourceDocument、Segment、Glossary、Notes、上下文、翻译、编辑、锁定、恢复与导出。
2. **模型提供商**：Provider Connection、模型和 capability-driven 参数。
3. **提示词模板**：复制、修改、重命名与删除模板。

Glossary 与 Notes 位于翻译页内部，不作为主页面。Auto/Workbench 不再是产品概念；高级能力通过翻译页的折叠设置提供。

高频路径固定为：

```text
拖入文件
→ 选择 Provider / Model
→ 选择 Prompt
→ 点击翻译
```

翻译页应展示 Segment 状态、原文、当前译文、必要 Context、进度和可操作错误；不得要求用户理解 Workflow、Attempt、Revision 等内部数据库对象。

## 7. 核心产品约束

- 一个 Translation Request 只有一个 target Segment；Context 不产生本次 Revision。
- Segment 是持久化、claim、retry、finalize 和恢复的最小单位。
- `stable_key` 不包含 raw byte offset；它只在同一逻辑映射版本与同一解析结果下稳定。
- 源 bytes、格式或 parser identity 改变时，可形成新的 SourceDocument；V1 不自动把旧 Revision 映射到新文件。
- 已有 Revision 的文档不得自动重新分段；需要新分段版本时创建新的 SourceDocument/映射，禁止猜测式 remap。
- 同一 Attempt 内只能做不改变 Prompt/Context 的 transport retry 或协议级 capability degradation。Context、Prompt、目标文本或语义参数改变时必须创建新 Attempt。
- 默认输出可为单段纯文本；结构化输出仅在 Provider capability 明确支持时启用。
- 默认单并发以获得最可复现的 Neighbor/History 上下文；提高并发必须有明确一致性语义与测试。

## 8. 完成定义

V1-Release 完成时，新用户无需阅读架构文档即可完成导入、配置、翻译、停止/恢复、编辑/锁定和保真导出；崩溃不会丢失已完成译文；旧项目兼容路径仍可打开；主导航不超过三个页面；非目标明确，且不会因“以后还能加功能”而延期。
