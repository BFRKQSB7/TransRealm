# 译境 / TransRealm

# Project Manager Guide V3

## 1. 文档职责

本文件面向项目负责人，负责：

- 管理 AI Agent；
- 分配和验收开发任务；
- 判断 Agent 需要读取哪些编号文档；
- 维护文档之间的一致性。

本文件不负责：

- 编码规范（见 `06_AI_Development_Guide.md`）；
- 技术实现细节（见 `03_Technical_Design.md`）；
- Prompt 具体模板（见 `05_Prompt_Architecture.md`）；
- 任务明细（见 `07_Developer_Task_List.md`）。

## 2. Agent 自动开工入口

日常开发时，项目负责人只需把 `DEVELOPMENT_STATE.md` 交给 Agent，并要求“按文件执行”。该文件是运行入口和检查点，不是产品需求或架构来源。

Agent 读取后必须：

1. 自动识别当前 Task 和小目标；
2. 按文件列出的顺序读取必要编号文档；
3. 检查工作区是否与检查点一致；
4. 无真实阻塞时直接标记 `in_progress` 并开工，不再询问“是否开始”；
5. 完成一个小目标后运行测试并更新检查点；
6. 中断前留下下一 Agent 可直接执行的恢复动作。

只有产品/架构变更、破坏性或对外操作、用户专属凭据或无法自行消除的实质歧义才询问用户。

## 3. 文档读取规则

### 完整接手项目
按以下顺序阅读：

1. `项目文档维护交接指令.md`；
2. `初订项目名字.md`；
3. `00_Project_Manager_Guide.md` 至 `08_Architecture_Review.md`，按文件名前数字顺序；
4. 最后读取 `DEVELOPMENT_STATE.md`，以恢复当前 Task、检查点和工作区状态。

### 普通开发任务
先读取 `07_Developer_Task_List.md` 中对应任务，再读取该任务列出的输入文档。不得凭印象跳过任务指定的文档。

### 需求或范围变化
读取 `01_PRD.md`、`02_Development_Roadmap.md`，先确认是否属于已批准范围；未确认前不实现新增功能。

### 架构变化
读取 `03_Technical_Design.md`、`08_Architecture_Review.md`、`01_PRD.md`。先记录原方案、新方案、收益、缺点、风险和迁移成本，等待确认后再开发。

### 数据库、Prompt 或 Agent 规则变化
分别读取：

- 数据库：`04_Database_Schema.md`；
- Prompt：`05_Prompt_Architecture.md`；
- Agent 规则：`06_AI_Development_Guide.md`。

## 4. 当前范围基线

- V1.0 是基础可靠版：Project、Segment、TXT/JSON/字幕、恢复、多模型配置和基础 Glossary。
- V1.0 不包含 RAG、智能 TM、World State、节点式 Workflow 编辑器、插件、内置模型下载器或多人协作。
- `.aiproject` 只承诺单用户离线迁移、备份和项目转交，不承诺并发协作或自动合并。
- 首发 Model Adapter 正式支持 OpenAI-compatible HTTP；llama.cpp 与 Ollama 优先使用兼容端点；Sakura/Murasaki 是 Model Profile，不代表专有协议支持。
- Phase 0 必须具备最小 Context Budget、机器可解析输出契约、解析校验和有限重试。

## 5. 任务验收

任务完成必须同时具备：

1. 需求范围已确认；
2. 实现完成；
3. 功能测试通过；
4. 异常测试通过或明确记录未覆盖原因；
5. Code Review 完成；
6. 相关编号文档已同步；
7. 结果、测试证据、风险和后续任务已记录。

测试失败时不得标记为完成；应标记为进行中或阻塞，并写明恢复条件。

## 6. 文档维护规则

- 需求变化 → `01_PRD.md`；
- 计划、阶段或版本变化 → `02_Development_Roadmap.md`；
- 技术实现变化 → `03_Technical_Design.md`；
- 数据结构或迁移变化 → `04_Database_Schema.md`；
- Prompt、Context 或输出协议变化 → `05_Prompt_Architecture.md`；
- Agent 开发规则变化 → `06_AI_Development_Guide.md`；
- 任务变化 → `07_Developer_Task_List.md`；
- 设计理由、取舍和风险变化 → `08_Architecture_Review.md`；
- 当前 Task、小目标、测试证据和中断恢复点 → `DEVELOPMENT_STATE.md`。

不新增编号文档，除非确认现有职责无法承担。