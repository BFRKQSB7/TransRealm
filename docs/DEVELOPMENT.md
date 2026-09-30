# TransRealm 开发规则

> 状态：开发流程的唯一长期规则。当前执行状态只在 `tasks/README.md`；每个实现 Task 的范围、非目标、依赖、验证和交付只在自己的 `tasks/Txx-*.md`。

## 1. 环境与运行

基线为 Python 3.12、PySide6、SQLite 与 pytest。仓库根目录安装和启动：

```powershell
py -3.12 -m pip install -e ".[dev]"
transrealm
# 或
py -3.12 -m transrealm.ui
```

项目开发输出只能写入 `D:/TransRealm/`。虚拟环境使用 `.venv/`；验证数据、截图、临时文件和缓存分别使用 `.local/verification/`、`.local/tmp/`、`.local/cache/`；历史候选使用 `.local/archive/`。不得用 link/junction 把这些输出转移到项目外，也不得自动整理真实用户数据。

## 2. Agent 阅读策略

普通 Coding Task 默认只读：

```text
tasks/Txx-*.md
+ Task 明确指定的源码
```

只有在需要时增读：

- 架构或兼容边界：`docs/ARCHITECTURE.md`
- Database、migration、恢复、Project 容器：`docs/DATABASE.md`
- 产品/UI 范围不清：`docs/PRODUCT.md`
- 构建、候选、签发：`docs/RELEASE.md`

不得默认要求 Agent 阅读全部 docs 或 `docs/archive/`。历史 RFC、Review、Roadmap、Task ledger 和状态 ledger 只用于追溯，不是当前指令。

## 3. Task 执行

每个 Task 文件必须自包含：目标、非目标、依赖、允许修改范围、风险、验收、交付物、回滚/恢复和 Definition of Done。一次只执行一个 Task；完成或真实阻塞后停止，再由 `tasks/README.md` 指向下一项。

执行顺序：

```text
读取 Task
→ 核对 Git/工作树与授权
→ 运行 Task 指定的旧行为测试
→ Reality Check: FIT / ADAPT / REPLAN
→ 新增或更新验收测试
→ 最小实现
→ targeted test
→ milestone regression
→ full regression（Task 要求时）
→ Review / 文档同步
→ 更新 Task 与 tasks/README.md
```

- **FIT**：计划与现场一致。
- **ADAPT**：目标、硬约束与验收不变，只调整内部实现，并记录依据。
- **REPLAN**：会改变用户行为、数据/Project 格式、公共契约、已批准架构、依赖或 Task 范围；停止冲突部分并请求裁决。

规划、Review 或 Markdown 授权不自动成为代码、构建、提交或外部动作授权。用户当前指令优先；不明确时保持只读并报告差异。

## 4. 验证层级

Targeted test 验证当前变化及其直接旧行为；Milestone regression 覆盖同一用户旅程或风险域；Full regression 用于 Task 完成、共享基础设施、高风险变化或候选门禁。

当前全量质量命令：

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

全量 pytest 是底线，不替代 Task 声明的 targeted/旧行为测试。新增能力至少有一条测试；删改旧测试必须说明对应行为如何继续受保护。

附加门禁：

- GUI：实际启动和操作；按 Task 指定语言、分辨率、DPI 和场景保存项目内证据，并检查截断、重叠、焦点及空/错/禁用状态。
- Migration、删除、导入导出、恢复、凭据、HTTP：对应 E2E 或故障注入。
- 新依赖：理由、版本、许可、安全、lockfile 和打包影响。
- 数据/公开契约：迁移与回滚或前向修复说明。

## 5. Migration 与数据安全

数据库只允许追加编号 migration，永不修改已发布 SQL。相关 Task 必须验证旧库升级、升级前一致性备份、失败回滚、foreign keys、重开和受影响的格式/恢复路径。详细不变量见 `docs/DATABASE.md`。

API Key、token、凭据正文、用户数据库、备份、导出、日志、`.aiproject` 与构建输出不得提交。凭据只使用现有 `env:`/`wincred:` 引用。发现真实凭据证据时停止传播并报告；撤销或替换需要用户权限。

## 6. Git 与权限边界

- 保留用户既有修改；不得使用 reset/clean 覆盖工作树。
- 只暂存 Task 明确允许的路径；不得使用 `git add .`、`git add -A` 或强制添加被忽略内容。
- 创建/切换/删除分支、commit、push、merge、tag、PR、Release、上传、付费请求和远程资源均需当次明确授权；一种授权不蕴含另一种。
- 提交前后核对 diff、staged 文件、作者、允许路径和状态指针；不得改写既有历史。
- 项目外既有目录不因本规则获得移动或删除授权。

## 7. Review 与完成

Review 以可复现行为、数据安全、兼容性和测试缺口为准，不以实现者的完成声明代替证据。当前仅供用户本机使用的 V1 候选以本轮源码审阅和实际本机验收为准，不要求额外独立评审；数据保护、凭据隔离、格式保真及恢复检查仍须执行。将来扩大到其他电脑或对外发布时，另行确定审阅和验收范围。

Task 只有在目标、异常路径、适用回归、Review、文档与状态入口全部同步后才能完成。未运行、Unavailable 或 Unknown 不能写为 Passed；真实外部阻塞应记录复现、已完成部分、解除条件、恢复动作和下一检查点。

## 8. Release 前检查

涉及候选构建或发布时，额外执行 `docs/RELEASE.md`。构建候选不等于提交、推送或正式发布。
