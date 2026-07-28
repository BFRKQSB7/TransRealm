# 译境 / TransRealm
# Development Roadmap V3

版本：V1.0 Baseline

状态：开发与发布规划基线

---

# 1. 开发原则


## 1.1 核心原则

项目采用：

```
先核心能力

↓

再专业能力

↓

最后生态扩展
```


---

禁止：

一开始开发：

- 内置模型下载器
- 完整工作流编辑器
- 复杂格式解析
- 多人协作（近期非目标）


原因：

这些功能会消耗大量开发资源，但不会验证核心价值。


---

# 2. 总体阶段


项目分为：

```
Phase 0

基础框架


↓

Phase 1

可用翻译工具


↓

Phase 2

专业翻译能力


↓

Phase 3

高级生态


↓

Phase 4

V2.x 远期扩展
```


---

# Phase 0：基础框架（V0.x 技术内测）


目标：

建立基于 Python 3.12、PySide6 和 SQLite 的 Windows 11 可运行软件骨架。


## 必须实现


### 项目管理

支持：

- 创建 Project
- 保存 Project
- 加载 Project
- SQLite 初始化与编号 Schema Migration


---

### GUI 框架

使用 PySide6（Qt 6），实现：

- 主窗口
- 设置页面
- 项目页面
- 翻译页面


---

### 工程与测试基础

- Python 3.12；
- `src/` 布局与明确的包边界；
- pytest 自动化测试；
- Windows 路径、Unicode 文件名和只读目录测试；
- 依赖锁定与可重复开发环境；
- Windows 绿色版打包的最小 smoke test。

---

### 基础文件读取


支持：

- TXT


---

### 模型接口


实现：

统一接口：

```
Model Adapter
```


支持：

- OpenAI-compatible HTTP
- llama.cpp server 兼容端点
- Ollama 兼容端点

Sakura、Murasaki 作为 Model Profile，不要求专有调用协议。


---

### 基础翻译流程

流程：

```text
导入 -> 稳定 Segment -> 最小 Context Budget -> Model Profile -> Model Adapter -> 输出解析/校验 -> Attempt/Revision 保存
```

Phase 0 即实现机器可解析输出契约、有限修复/重试和崩溃后 processing 回收。


---

# Phase 0 不实现


暂不开发：

- RAG
- Translation Memory
- 工作流编辑器
- 内置模型加载


---

# Phase 1：基础可靠版（V1.0 GitHub 公开）


目标：

个人可以实际使用。


---

## 文本支持


增加：

- JSON
- SRT
- ASS
- SSA
- VTT


---

## 分句系统


实现：

Segment ID。


支持：

- 断点恢复
- 错误定位


---

## 项目文件


实现：

```
.aiproject
```


支持：

- 迁移
- 备份


---

## 工作模式


实现：

两种模式：

### 自动模式

简单翻译。


### 工作台模式

显示：

- 状态
- 参数
- 进度


---

## 模型管理

支持：

- 多模型配置
- 参数保存

---

## V1.0 Release Gate

在 Phase 1 完成后、GitHub 公开前必须完成：

- GitHub 仓库与许可；
- 安装、使用、迁移和恢复文档；
- 支持系统上的打包与启动验证；
- 已知问题、备份和回滚说明；
- V1.0 格式 round-trip、异常恢复和长文本验收。

通过 Release Gate 后才可发布 V1.0。

平台门槛：在受支持的 Windows 11 环境完成绿色版解压启动、创建/迁移 Project、调用兼容端点、关闭后恢复和卸载清理测试。


---

# Phase 1 不实现


暂缓：

- 世界记忆
- RAG
- TM智能复用


---

# Phase 2：专业翻译能力（V1.x）


目标：

达到轻小说/Galgame专业使用水平。


---

# Memory System


实现：

## Character Data


支持：

- 人名
- 性别
- 关系
- 说话方式


---

## Glossary


支持：

- 自动提取
- 用户修改


---

## Translation Memory


实现：

基础版本。


包括：

- 原文
- 译文
- 上下文关联


---

# RAG系统


实现：

基础：

```
检索

↓

排序

↓

加入Prompt
```


---

# Context Composer


实现：

统一管理：

```
原文

角色

术语

记忆

RAG
```


---

# Context Budget Manager（动态扩展）


实现：

在 Phase 0 最小规则式预算上，加入 TM/RAG 候选评分、去重和动态分配。


功能：

- 控制上下文数量
- 根据模型大小调整


---

# Phase 2 不实现


暂缓：

- 自动工作流编辑
- 高级插件系统


---

# Phase 3：高级功能（V2.0）


目标：

成为完整AI翻译平台。


---

# 工作流编辑器


支持：

节点化流程。


例如：

```
文本输入

↓

AI分析

↓

人工确认

↓

翻译

↓

检查
```


---

# 多模型协作


支持：

例如：

```
模型A：

翻译


模型B：

检查


模型C：

术语生成
```


---

# Translation Candidate Mode


支持：

多个结果比较。


例如：

```
结果A

结果B

结果C
```


用户选择。


---

# Quality Control Engine


实现：

自动检查：

- 漏翻
- 格式错误
- 人名变化
- 风格变化


---

# Plugin System


支持：

扩展：

- 文件格式
- 模型
- 工作流


---

# Phase 4：远期扩展

目标：

仅规划 V1.0 之后的独立扩展，不承担 V1.0 发布门禁。

# 远期：内置模型管理器


支持：

- 模型下载
- 模型安装
- 启动管理


---

# 远期：GPU 检测


检测：

- 显存
- 内存
- CPU


---

# 远期：模型推荐


根据：

```
硬件

↓

推荐模型

↓

推荐参数
```


---

例如：

RTX5070Ti Laptop：

推荐：

14B模型。


---

低配置：

推荐：

小模型/API。


---

高配置：

推荐：

32B模型。


---

# 远期：格式扩展


支持：

- EPUB
- HTML
- Word
- Ren'Py


---

# 3. 测试策略


# 单元测试


测试：

- 文件解析
- 数据库
- 分句


---

# AI 流程测试

测试：

- Model Profile 与 Prompt 生成；
- 最小 Context Budget；
- 输出解析与校验；
- Phase 2 后再加入 Character Data、TM 与 RAG 结果。


---

# 长文本测试


测试：

例如：

10万字小说。


检查：

- 内存峰值有记录；
- 所有 Segment 最终状态可解释；
- 重启后数据丢失为零；
- 已完成 Segment 不被重复覆盖；
- 恢复后的重复外部调用数量有记录。


---

# 崩溃恢复测试

模拟切点：

- 模型请求前；
- 请求发出后、响应写入前；
- Revision 写入前后；
- Segment 状态更新前后；
- 强制关闭、网络中断和本地模型停止。

验收：Project 可重新打开，SQLite 可用，数据丢失为零，人工锁定 Revision 不被覆盖，遗留 processing 可安全回收。


---

# 4. 发布前检查


必须满足：

## 稳定性

- 不丢数据
- 可恢复


---

## 易用性

普通用户：

无需理解：

- Prompt
- 参数
- RAG


---

## 高级能力

专业用户：

可以：

- 修改Prompt
- 调整参数
- 查看日志


---

# 5. 版本规划


## V0.x

内部测试版本。


目标：

自己使用。


---

## V1.0

GitHub公开版本。


包含：

- Project 与 SQLite Migration
- 稳定 Segment、Attempt/Revision 和恢复
- TXT、JSON、SRT、ASS、SSA、VTT
- OpenAI-compatible Model Adapter
- 多 Model Profile 配置
- 最小 Context Budget 与输出校验
- 基础 Glossary

不包含：RAG、智能 TM、World State、节点式 Workflow 编辑器、插件、内置模型管理、多人协作或原生多厂商 API。


---

## V1.x


增加：

- RAG
- TM优化
- 工作流增强


---

## V2.0


目标：

完整AI翻译工作平台。


包含：

- 工作流编辑器
- 插件
- 高级模型管理


---

# 6. Phase 与版本映射

| 开发阶段 | 发布目标 | 范围 |
|---|---|---|
| Phase 0 | V0.x 技术内测 | Project/SQLite、TXT、Segment、Adapter/Profile、最小 Context 与输出校验 |
| Phase 1 | V1.0 GitHub 公开 | JSON/字幕、恢复、`.aiproject`、多 Profile、基础 Glossary、发布验收 |
| Phase 2 | V1.x | Character Data、基础 TM、RAG、动态 Context Budget |
| Phase 3 | V2.0 | 节点式 Workflow、多模型协作、候选译文、QC、插件 |
| Phase 4 | V2.x 远期 | 模型管理、GPU 推荐和复杂格式按独立任务推进，不承担 V1.0 发布门禁 |

# 7. 唯一格式矩阵

| 格式 | 阶段 | 要求 |
|---|---|---|
| TXT | Phase 0 | 导入、Segment、导出 |
| JSON | Phase 1 / V1.0 | 保留结构、key、顺序和转义 |
| SRT/ASS/SSA/VTT | Phase 1 / V1.0 | 保留时间轴、样式、标签和行结构 |
| Markdown/EPUB | Phase 4 远期 | 不阻塞 V1.0 |
| HTML/Word/Ren'Py | Phase 4 远期 | 单独评审格式保真与解析复杂度 |

# 文档结束