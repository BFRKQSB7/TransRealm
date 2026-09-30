# TransRealm 用户指南（v0.2.0 候选）

本文档面向使用绿色版候选的最终用户，覆盖安装、使用、模式、Profile/Glossary 配置与清理。数据迁移/备份/恢复见 [`data-safety.md`](data-safety.md)；已知问题与未覆盖项见 [`known-issues.md`](known-issues.md)；第三方依赖许可见 [`third-party-licenses.md`](third-party-licenses.md)。

## 1. 支持环境

- Windows 11（x64，build ≥ 22000）。当前候选在 Windows 11 Pro 10.0.26100（AMD64）构建并验证。
- 绿色版是自包含的可执行程序，**不需要**安装 Python 或任何运行时。

## 2. 安装（绿色版）

1. 下载候选压缩包 `transrealm-0.2.0-win-x64.zip`（sha256 `a4da4eff71facc38064b33042bae45a2ab5a578fdc679cf9c636ac001f9ca498`）。
2. 解压到任意位置（`Program Files`、移动硬盘、网络盘均可）。程序目录放在**只读位置也能运行**——应用数据写入用户目录，不写入程序目录。
3. 双击 `transrealm\transrealm.exe` 启动。

首次启动会在用户目录创建数据目录并自动应用数据库迁移（12 个迁移），无需任何手工步骤。

## 3. 数据目录

- 全部数据（项目、文档、连接、Profile、Glossary、翻译结果）存放在 **`%USERPROFILE%\.transrealm\project.sqlite`**（单个 SQLite 文件）。
- 项目不会保存在程序目录内，因此删除或移动程序目录不会影响你的数据（卸载与清理见 §8）。
- 升级旧版本时，应用打开项目会自动迁移数据库，并在迁移前生成备份文件（见 [`data-safety.md`](data-safety.md)）。

## 4. 界面总览

窗口包含三个标签页：

- **Settings（设置）**：管理模型端点连接与模型 Profile，查看凭据可用性。
- **Project（项目）**：创建/打开项目、导入源文件、设置 active Profile、维护 Glossary。
- **Translation（翻译）**：选择交互模式、翻译、取消、导出译文。

## 5. Settings：连接与 Profile

应用假设本地模型服务已经由用户自行启动；TransRealm 不负责启动或管理 `llama-server`，只保存用户填写的 API 地址并通过现有 OpenAI-compatible HTTP transport 调用。

### 5.1 Connection（模型端点连接）

- 字段：**Name**（名称）、**Endpoint**（端点基础 URL，OpenAI-compatible HTTP）、**Credential ref**（凭据引用）。例如命令行 `llama-server` 已运行在本机时，填写 `http://127.0.0.1:<port>/v1`；`<port>` 使用你实际启动服务时的端口。
- Endpoint 只填写 API 地址，不填写聊天路径；应用会通过 `/v1/chat/completions` 调用 OpenAI-compatible 服务。若命令行启动时设置了 `--alias`，Model Profile 的 **Model id** 填该 alias。
- 凭据引用**不保存密钥正文**，只保存引用，两种格式：
  - `env:MY_API_KEY` —— 从环境变量读取；
  - `wincred:TARGET` —— 从 Windows 凭据管理器读取。
- 下方列表列出已建连接；选择后可用 "Delete Selected Connection" 删除（被某个 Profile 引用时会给出明确提示并拒绝删除）。

### 5.2 Model Profile（模型配置）

- 字段：**Name**（名称）、**Model id**（模型标识，例如命令行 `llama-server` 的 `--alias`）、**Connection**（必须选择已有连接）。
- 一个 Model Profile 绑定一个 Connection + 模型及翻译参数；它不保存或启动模型服务。下方列表显示已建 Profile；选择后可用 "Delete Selected Profile" 删除（被项目设为 active 或被历史翻译引用时会给出明确提示并拒绝删除）。
- 凭据可用性提示显示在连接列表下方：某个引用在当前机器解析不到时给出可操作提示（"设置环境变量 / 建立 Windows 凭据项"），**永不显示密钥正文**。

## 6. Project：项目与 Glossary

### 6.1 创建与打开项目

- 填写 **Name**、**Source lang**（源语言）、**Target lang**（目标语言），点 "Create Project"。
- "Open project" 下拉框列出当前数据库中的全部项目，选择即切换。
- 项目内可以导入多个源文档，分别翻译。

### 6.2 导入源文件

- 选中项目后点 "Import source…" 选择 `.txt`、`.json`、`.srt`、`.vtt`、`.ass` 或 `.ssa` 文件。导入按内容哈希去重：同一项目里重复导入同一文件不会产生重复段。
- **v0.2.0 候选的图形界面提供上述六种格式的导入与导出**；导出时选择与源文档相同的格式，以保留格式结构。

### 6.3 Active Profile

- 从下拉框选择 Profile 后点 "Set Active Profile" 设为项目当前激活的 Profile；"Clear Active Profile" 清除。
- 首次配置顺序是：Settings 中保存 Connection → 创建 Model Profile 并选择该 Connection → 回到 Project 设置 active Profile。Project 和 Translation 页面会显示下一步操作入口。
- **自动模式的翻译必须依赖 active Profile**。未设置时，翻译页会显示引导，引导你回到本项目页设置。

### 6.4 Glossary（术语表）

- 条目字段：**source**（源术语）、**target**（目标术语）、**scope**（分类标签，用户自定义）、**priority**（优先级 0–100，越大越优先）、**locked**（锁定）。
- 翻译时，**仅 locked 条目**会按 `priority` 从高到低的稳定顺序注入提示上下文（同项目内同一源术语不允许重复）。非锁定条目只作管理记录，不参与注入。

## 7. Translation：翻译

### 7.1 交互模式（Interaction mode）

每个项目独立持久化的模式选择器：

- **Auto（自动）**：使用 active Profile，按文档顺序翻译全部待翻译段；无需逐段干预。
- **Workbench（工作台）**：逐段查看进度与结果，可调参数、编辑提示词、手工保存/锁定译文。

运行中不允许切换模式或切换文档（需先 "finish or Cancel"）。

### 7.2 文档选择

- "Document" 下拉框选择要翻译的项目文档（只显示当前项目已导入的文档）。

### 7.3 翻译与取消

- 点 **Translate** 开始。翻译在后台逐段进行，进度实时显示。
- 点 **Cancel** 在**当前段结束后**停止（不在请求中途打断）；取消后已完成的段保留结果，剩余段保持待翻译。
- 关闭窗口会先等待在途段收敛，重启后自动恢复模式/active/文档/结果/锁定（见 [`data-safety.md`](data-safety.md)）。

### 7.4 工作台

- 段进度列表：每个段显示状态/错误与当前译文。
- 参数编辑器：只显示当前模型能力支持的参数（`temperature`、`top_p`、`top_k`、`max_tokens`、`frequency_penalty`、`presence_penalty` 等）；`max_tokens` 会被钳制到模型能力上限。参数变更只影响其后新建的翻译尝试，不回改历史结果。
- Prompt 编辑器：只读展示预设模板，可拷贝后编辑保存为 override（保存时校验占位符合法、未知变量会被拒绝）；当应用预设模板版本更新后旧 override 会标记 stale，需重新保存或清除。
- 译文编辑器：选中段后可直接编辑译文，点 **Save** 保存为人工修订（user Revision）；**Lock/Unlock** 锁定/解锁当前译文。**锁定的译文不会被自动翻译结果覆盖。**

### 7.5 导出

- 点 **Export…** 选择保存路径，把当前文档按当前修订导出为对应格式。
- 导出需要该文档**每个段都有当前修订**（已翻译或人工保存过）；任一段缺失修订时整体导出会报错，**不会用源文代替或跳过未翻译段**。

## 8. 卸载与清理

- **删除程序目录不会删除你的数据**（数据在 `%USERPROFILE%\.transrealm`）。
- 若希望完全移除：删除程序目录，并（在确认不再需要数据与备份后）删除 `%USERPROFILE%\.transrealm` 整个目录。应用不会在执行卸载时自动删除用户数据。

## 9. 常见问题

- **翻译报 "Translation needs configuration"**：当前项目没有 active Profile——按引导依次在 Settings 保存 Connection、创建 Model Profile，再在 Project 页设置 active Profile。连接/凭据不可用时，按 Settings 页的提示修复引用。
- **导出报错**：确认该文档**每个段**都已翻译（或人工保存过）；任一段未完成时导出会整体报错，不会用源文代替。
- **机器重启后翻译停在半途**：这是正常状态。重启后应用会自动回收超时租约并继续/重试待翻译段（见 [`data-safety.md`](data-safety.md)）。

更多边界与限制见 [`known-issues.md`](known-issues.md)。
