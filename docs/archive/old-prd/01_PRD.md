# 译境 / TransRealm V1.0
# Product Requirement Document (PRD)

版本：V1.0 Baseline  
状态：已批准的基础可靠版需求基线  
目标：作为AI辅助开发与项目维护基础文档

---

# 1. 项目概述

## 1.1 项目名称

译境 / TransRealm

产品类型：AI 本地翻译工作台。

---

## 1.2 项目定位

本项目是一款面向：

- 轻小说翻译
- Galgame文本翻译
- 小说翻译
- 游戏文本翻译
- 多语言文章翻译

的AI辅助翻译工作平台。

项目并非单纯的自动翻译工具，而是：

> 一个支持本地模型、在线API、多模型工作流、长期项目记忆管理的AI翻译生产工具。

---

## 1.3 核心理念

传统AI翻译的问题：

1. 单次请求，没有长期记忆。
2. 长文本容易丢失人物关系。
3. 不同章节人物称呼容易变化。
4. 本地模型上下文有限。
5. 用户无法控制AI翻译流程。


本项目解决：

通过 Project 管理、Segment 持久化、Model Profile、基础 Glossary 和可恢复翻译建立可靠内核；后续版本再加入 Character Data、Translation Memory (TM)、World State、RAG、Context Budget 扩展和 Workflow 系统，让 AI 成为长期翻译助手。

---

# 2. 产品目标

## 2.1 第一目标

实现一个个人可长期使用的AI翻译工具。

要求：

- 稳定
- 可恢复
- 可迁移
- 支持本地模型
- 支持在线API


---

## 2.2 第二目标

经过完善后开源至GitHub。

要求：

- 架构清晰
- 文档完整
- 插件化设计
- 易维护


---

## 2.3 非目标

V1.0 不追求：

- 在线协作平台
- 商业级翻译管理系统
- 完整CAT工具替代
- 自动训练模型


---

# 3. 用户类型

## 3.1 普通用户

特点：

- 不懂AI配置
- 不懂模型参数
- 希望自动翻译


需求：

提供：

- 预设自动 Workflow
- 简单设置

模型自动推荐属于远期能力；V1.0 允许选择预设 Model Profile。


---

## 3.2 高级用户

特点：

- 使用本地模型
- 了解Prompt
- 追求翻译质量


需求按版本开放：

- V1.0：Prompt/Profile 查看与 Override、支持参数控制、Debug；
- V1.x：RAG/TM 命中查看；
- V2.0：节点式 Workflow 调整。


---

# 4. 核心工作模式

软件支持两种模式。

---

# 4.1 自动翻译模式

目标：

减少用户操作。


流程：

```
导入文件

↓

生成稳定 Segment

↓

应用基础 Glossary / 最小 Context

↓

自动调用模型

↓

解析并校验输出

↓

自动保存

↓

输出译文

Phase 2 可选增加 Character Data 自动分析、TM 与 RAG。
```


适合：

- 大量文本
- 快速翻译
- 普通用户


---

# 4.2 工作台模式

目标：

提高翻译质量。


流程按版本启用：V1.0 可跳过尚未实现的 Character Data 自动分析、RAG 和智能 TM；这些能力在 Phase 2 / V1.x 加入。

```text
文本导入
 -> Segment
 -> 基础 Glossary / 最小 Context
 -> 翻译
 -> 输出校验
 -> 人工辅助与质量检查
```


支持：

- 选择预设 Workflow
- 选择 Model Profile
- 调整允许暴露的参数

节点式自定义 Workflow 后置到 V2.0。


---

# 5. 支持文件格式

## Phase 0 / V0.x

必须支持：

- TXT

## Phase 1 / V1.0

增加：

- JSON
- SRT
- ASS
- SSA
- VTT

## Phase 4 远期

- Markdown
- EPUB
- Ren'Py
- HTML
- Word


---

# 6. 翻译目标范围

严格来说：

软件支持：

> 多语言小说/文章翻译。


轻小说特化体现在：

- V1.0：基础 Glossary、可控 Model Profile、可恢复 Segment；
- V1.x：Character Data、人物关系、角色语气、World State 和 Galgame 深度优化。


---

# 7. 模型支持

## 7.1 首发模型接入

正式支持 OpenAI-compatible HTTP。

- llama.cpp server：通过兼容端点接入；
- Ollama：优先通过兼容端点接入；
- Sakura、Murasaki：作为 Model Profile；
- 其他兼容服务：遵循能力声明后接入。

不承诺首发原生多厂商 API；Model Adapter 保留后续扩展接口。

---

## 7.2 Provider 与 Model Profile

Provider Connection 保存 endpoint、超时、重试和认证引用；Model Profile 保存 Prompt 模板、参数建议、能力约束、Context 配额和输出规则。API Key 不进入 Project、备份或日志。


---

## 7.3 模型职责分离

不同任务可以使用不同模型：

例如：

```
翻译：

Sakura 14B


术语提取：

在线大模型


检查：

小模型
```


---

# 8. 工作流系统

## 8.1 V1.0

使用预设模板。


例如：

```
普通翻译流程

↓

专业轻小说流程

↓

Murasaki流程

↓

Sakura流程
```


---

## 8.2 后期

支持：

复制预设 Workflow 后自定义并保存个人副本；节点式 Workflow 编辑器后置到 V2.0。


要求：

用户可以：

- 复制预设流程
- 修改副本
- 保存个人流程


预设模板不可直接修改。


---

# 9. 项目管理系统

## 9.1 项目保存

支持：

项目文件迁移。


用户可以：

电脑A：

```
保存项目
```

复制：

```
project.aiproject
```

电脑B：

```
加载继续翻译
```


---

## 9.2 双模式项目文件


### 简易模式

单文件：

```
project.aiproject
```


本质：包含 manifest、SQLite 一致性快照和附件的压缩项目包。API Key 等秘密永不进入项目包。


---

### 高级模式

开放目录：

```
project/

├── source/

├── translation/

├── memory/

├── workflow/

├── logs/

└── config/
```


---

# 10. 断点恢复

必须支持：

- 翻译中断
- 程序关闭
- 断电


机制：

每个文本片段拥有：

```
Segment ID
```


状态：

```
pending

processing

completed

failed
```


---

# 11. 专业记忆系统（Phase 2 / V1.x）

系统包含：

---

## 11.1 Character Data

保存：

- 人物名称
- 性别
- 身份
- 关系
- 说话风格


用户可以修改。


优先级：

```
用户确认

>

AI生成
```


---

## 11.2 Glossary

保存：

- 专有名词
- 技术词
- 人名
- 地名


支持：

用户编辑。


---

## 11.3 Translation Memory

上下文感知翻译记忆。


保存：

- 原文
- 译文
- 场景
- 角色
- 置信度


避免：

简单文本匹配导致误复用。


---

## 11.4 World State

保存：

影响翻译的信息：

例如：

- 人物关系
- 已发生事件
- 世界规则


不保存：

大量无关剧情。


---

## 11.5 Style Preference Memory

记录：

用户修改形成的风格偏好。


默认：

在线AI启用。


本地模型：

默认关闭。


---

# 12. RAG 系统（Phase 2，V1.x）

目标：

让模型获得正确背景。


原则：

禁止：

```
全部记忆发送给模型
```


必须：

```
检索

↓

评分

↓

预算限制

↓

上下文组合

↓

模型
```


---

# 13. Context Budget Manager

Phase 0 即存在最小规则式版本；Phase 2 扩展为专业模式的动态预算模块。


作用：

控制：

```
原文

+

角色

+

术语

+

TM

+

世界状态

+

风格
```

进入模型的数量。


根据：

- 模型上下文长度
- 当前任务
- 用户模式


动态调整。


---

# 14. 参数管理

普通模式隐藏复杂参数，允许选择预设 Model Profile。

专业模式仅显示 Model Capability 声明支持的参数，例如最大输出、上下文限制或兼容端点接受的采样参数。不得假设所有模型都支持 `temperature`、`top_p` 或相同参数范围。


---

# 15. GPU 检测与模型推荐（远期）

目标设备：

优先适配：

```
i7-14650HX

32GB RAM

RTX5070Ti Laptop

12GB VRAM
```


推荐：

14B级模型。


---

支持：

低配置：

推荐：

- 小模型
- 在线API


高配置：

例如：

5090：

推荐：

32B模型。


---

# 16. Prompt系统

支持：

## 普通用户

自动生成。


---

## 专业用户

支持：

- 查看
- 修改
- 自定义Prompt


原则：

预设模板不可修改。

用户修改保存为：

Override。


---

# 17. Debug 系统

保存（可配置、可脱敏）：

- Prompt
- 参数
- 模型响应
- 错误日志


普通模式：

自动清理。


Debug模式：

用户主动开启后保存；支持脱敏、保留期限和一键清理。API Key 不得记录。


---

# 18. 版本管理

翻译结果支持版本。

例如：

```
Chapter1_v1

Chapter1_v2
```


避免：

重新翻译覆盖优秀版本。


---

# 19. 高级功能规划

后期：

- 多结果比较
- 工作流编辑器
- 插件系统
- Ren'Py深度支持
- 内置模型管理器


---

# 20. 开发原则

1. 第一版优先稳定。
2. 高级功能预留接口。
3. 不允许破坏项目兼容性。
4. 所有AI能力模块化。
5. 用户数据必须可控。
6. 默认简单，专业模式开放。


---

# 21. V1.0 边界

V1.0 基础可靠版包含：Project、Segment、SQLite Migration、TXT/JSON/SRT/ASS/SSA/VTT、断点恢复、OpenAI-compatible Model Adapter、多 Model Profile 配置、最小 Context Budget、机器可解析输出、解析校验和基础 Glossary。

V1.0 不包含：RAG、智能 Translation Memory (TM)、World State、节点式 Workflow 编辑器、插件、内置模型下载器、原生多厂商 API 或多人协作。

Project 近期只承诺单用户、离线、跨电脑迁移、备份和项目转交。

## 21.1 技术与平台基线

- 核心语言：Python 3.12；
- GUI：PySide6（Qt 6）；
- 数据库：SQLite；
- V1.0 正式支持 Windows 11；
- 架构避免写死 Windows 路径和平台行为，为后续 Linux/macOS 评估保留边界，但 V1.0 不承诺跨平台发布；
- Windows 发布以绿色版为主：解压即用，应用、Project、配置和日志默认位于可写的绿色版数据目录；
- 不承诺把程序放入 `Program Files` 后仍向安装目录写数据，若目录不可写必须在启动时提示并允许选择新的数据目录。

## 21.2 v0.2.0 可用性补全边界

v0.1.0 已证明翻译、持久化、恢复和六格式保真底座可用；v0.2.0 优先把这些既有能力交付为普通用户可完成的桌面旅程，不提前进入 RAG、智能 TM 或节点式 Workflow。

v0.2.0 包含：

- 重构 PySide6 桌面信息架构与视觉层级，形成一致的颜色、字号、间距、状态和错误反馈；
- 中文/英文界面切换，语言选择可持久化，英文作为缺失翻译的安全回退；
- TXT、JSON、SRT、ASS、SSA、VTT 六种格式在 GUI 中完成导入、翻译和保真导出；
- Project 删除入口：运行中保护、删除前一致性备份、明确确认、事务级联和失败回滚；
- Connection、Model Profile 的新增、编辑、删除和可操作校验；
- Workbench 的 Segment 状态过滤、源文/译文编辑、Revision 历史选择、锁定和失败恢复入口；
- Windows 11 下中英文、DPI/分辨率矩阵的实际启动、交互与截图验收。

v0.2.0 不包含：

- `.aiproject` / 开放目录 GUI 接线；其服务层能力保留，但当前 GUI 的多 Project 全局数据库与容器“一库一个 Project”契约必须先经 `DEC-V03-PROJECT-STORAGE` 裁决；
- RAG、智能 TM、Character Data、Glossary 自动提取、暗色主题、插件系统或新的 UI 框架依赖；
- 自动调用真实或付费模型端点、自动推送、合并、打 tag 或发布。

删除 Project 只删除当前应用数据库内的 Project 及其从属数据；不得删除用户原始源文件、既有导出、外部 `.aiproject` 或开放目录。删除前备份失败、Project 有运行中 Run/有效 processing lease 或事务校验失败时必须拒绝删除且不改变数据。

## 21.3 v0.3.0 Project 工作区边界

v0.3.0 采用一次一个活动 Project 的桌面模型：每个 Project 对应一个开放目录工作区和一份 `project.sqlite`，应用通过 Project Manager 创建、打开、定位和切换最近 Project。受管工作区与用户选择的外部开放目录共享同一 manifest/schema/hash/秘密排除契约；应用设置与 Project 数据分离，界面语言、最近路径和数据根不进入 Project 数据库。

`.aiproject` 是跨电脑迁移、备份和转交用的传输快照，不是活动工作区。用户打开归档时，应用必须先隔离解包、验证、迁移并安装到可写工作区；源归档保持不变。外部开放目录不可写时不得假装成功编辑，只允许选择其他数据目录或导入副本。

v0.3.0 不承诺网络共享盘、云盘多端同时编辑、多人协作、Project 自动合并或只读编辑模式。活动 SQLite 工作区默认位于本地可写文件系统；跨机器通过 `.aiproject` 交换。旧全局多 Project 数据库必须先做一致性备份，再逐 Project 拆分并完整验证；全部新工作区通过前不得改写或删除旧库。

---

# 文档结束
