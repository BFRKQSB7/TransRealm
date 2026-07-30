# 译境 / TransRealm

# Prompt Architecture V3

## 1. 原则

Prompt 不是堆叠信息，而是：

```text
筛选正确来源 -> 应用 Context Budget -> 渲染 Model Profile -> 调用并验证
```

Prompt 组装必须可追踪、可复现。用户 Override 不能破坏机器可解析输出协议或格式保护规则。

## 2. Model Profile

每个 Model Profile 独立保存：

- profile id/name 与适用任务；
- provider/model 引用；
- Prompt 模板及版本；
- 默认参数建议；
- Model Capability 约束；
- Context Budget；
- 输出协议；
- parser、validator 和有限修复策略。

首发 Profile 可包含 `general`、`sakura`、`murasaki`。它们是不同提示与输出策略，不代表专有 API 协议。

预设模板不可直接修改；用户修改保存为 Override，并记录父模板版本。

## 3. Phase 0 翻译 Prompt 流程

```text
Project + Segment + Workflow Step
 -> Resolve Model Profile
 -> Gather Context Candidates
 -> Rank/deduplicate/apply minimum budget
 -> Render Prompt
 -> Call Model Adapter
 -> Parse output
 -> Validate
 -> Persist Attempt and Translation Revision
```

## 4. Context 组成与权威顺序

Phase 0 必需：

- 当前 Segment 原文；
- 必要相邻 Segment。

Phase 0 可选：

- Project 已存在且用户锁定的 Glossary。

Character Data、RAG、TM 智能召回和 World State 自动摘要属于 Phase 2；若数据尚不存在，不得伪造为必需输入。

冲突优先级：

```text
用户锁定/人工审核
 > 项目级明确规则
 > 当前文件/章节上下文
 > 已验证 TM/RAG
 > AI 自动提取
 > Profile 默认值
```

## 5. 最小 Context Budget

Phase 0 必须存在规则式预算管理：

1. 先预留 Prompt 固定部分和输出空间；
2. 当前 Segment 为必入；
3. 若 Project 已存在基础 Glossary，只将用户锁定项按 priority 和稳定顺序优先加入；未锁定项可保存/编辑，但 V1.0 不自动注入；
4. 再按同一 SourceDocument 内与当前 `sequence` 的距离、其次 sequence 的确定顺序加入相邻 Segment；选择规则和边界进入 Manifest；
5. Phase 2 启用后，再按优先级加入确认的 Character Data；
6. 超出预算时按低优先级、较旧、未确认来源顺序裁剪；
7. 不截断 Segment 原文；无法满足预算时降低批量大小或标记错误；
8. 记录估算 token/字符数和裁剪结果。

Phase 2 只扩展候选召回、相似度评分和动态预算，不改变基础流程契约。

## 6. 输出契约

内部输出采用与 Provider 无关的结构：

```json
{
  "segment_id": "stable-id",
  "translation": "目标译文",
  "warnings": [],
  "notes": []
}
```

批量请求使用 `items` 数组，每项必须包含对应 Segment ID。输出 Parser/Validator 必须检查：

- Segment ID 存在且匹配请求；
- 翻译字段存在且为字符串；
- 数量、顺序和源 Segment 对应；
- 格式码、变量、时间轴或结构约束未被破坏；
- 无额外解释文本污染译文。

校验失败时执行 Profile 规定的有限修复/重试；达到上限后保存失败 Attempt，不写入当前译文。Output Parser 在同一响应内进行 fence 提取等确定性解析修复，不等同于持久化 SegmentAttempt。再次调用模型的 repair 必须创建新 Attempt；Adapter transport retry 与一次 capability degradation 保持在原 Attempt 内。各层上限必须独立记录且不能形成无限或未界定的乘法重试。

## 7. Context Manifest 与 Debug

每次 Attempt 在重启后记录或可解析到：Profile/template/capability snapshot 或稳定版本、Context 来源、命中原因、优先级、预算、估算、裁剪结果、Prompt hash、参数、输出协议和 Validator 结果。Model Profile 中的 parser/validator/repair 字段只保存声明式协议选择与上限，不复制可执行实现。

原始 Prompt/响应默认可配置、可脱敏、可清理；API Key 不得出现。清理 Debug 正文后，Revision、请求 ID、hash、版本、状态、usage、错误与 Validator 摘要等最小审计字段仍须保留。

## 8. Provider 差异

Model Profile 声明模型能力和输出协议；Model Adapter 负责实际 Provider 请求。不得假设所有 OpenAI-compatible 服务支持相同 JSON mode、temperature、top_p、流式或上下文长度。能力不支持时使用 Profile 的降级协议，不无限重试。

## 9. 质量边界

普通用户使用预设 Profile/Workflow；高级用户可修改指令、风格和参数，但不能关闭 Segment ID、输出包装、格式保护、校验和安全限制。