# TransRealm 通用 Agent 提示词

项目目录：`D:\TransRealm`

所有模板均以 `DEVELOPMENT_STATE.md` frontmatter、当前 Task/Milestone、权威编号文档和 Git 现场为准，不依赖本文件记录具体版本或任务编号。

## 长期授权边界

- 禁止创建、切换或删除分支；始终在用户当前分支上工作。若现场分支与状态记录不一致，停止并报告，不得自行切换。
- 允许在每个 Milestone 验收通过后创建本地 checkpoint commit，包括必要的暂存；提交只能包含当前 Task 授权范围和已确认归属的既有改动。
- commit 前必须核对 staged diff、允许路径、测试/Review 证据和生效的 Git 作者身份；commit 后复核 commit 作者、文件清单和 `DEVELOPMENT_STATE.md` 指针。
- 提交信息使用 `feat` / `fix` / `docs` / `refactor` / `chore` 前缀。不得为制造进度创建未验证的空提交或混合多个 Milestone。
- 不允许覆盖、丢弃、reset、restore、clean、强制切换、amend/rebase 既有历史或删除用户改动，除非用户针对具体目标另行授权。
- push、merge、tag、GitHub Release、远程资源、真实/付费模型调用和真实用户数据操作仍需单独明确授权；本地 commit 不等于允许外部动作。

## 启动或继续当前代码 Task

粘贴本提示词表示：授权 `DEVELOPMENT_STATE.md` 当前 Task/Milestone 范围内的代码、测试和必要文档修改；同时适用上面的分支与本地里程碑提交授权。

```text
读取 D:\TransRealm\DEVELOPMENT_STATE.md，并按“唯一 Agent 交接入口”处理当前 Task/Milestone。
先核验 Git HEAD、branch、staged/unstaged/untracked、当前实现、测试证据和授权范围；保护并归属所有既有改动，不得覆盖、丢弃、reset、restore、clean 或删除。
若当前 Task 仍为 proposed：仅在依赖满足、规划文档已形成可恢复基线且没有 REPLAN 冲突时，把 code_authorized 改为 true、状态推进为 ready，并记录实际 base_commit；否则停止冲突范围并写清解除条件。
禁止创建或切换分支；保持在用户当前分支。严格按 Task 的目标、非目标、allowed_paths、兼容性基线和 Milestone 推进：Reality Check → 一个垂直测试/验收样例 → 最小实现 → 旧功能回归 → 全量质量门禁 → 实际 GUI/异常/安全验证 → 独立 Review → 文档与状态同步。
每个 Milestone 只有在验收、旧回归、全量门禁、适用的视觉/安全 Review 和状态同步全部通过后，才允许暂存当前范围文件并创建一个本地 checkpoint commit。commit 前核对 staged diff 与作者身份，commit 后复核作者、文件清单和状态指针。
同一失败重复两次后停止盲目重试，记录复现、证据、已尝试方案和解除条件。
不得 push、merge、tag、创建 Release/远程资源、调用真实或付费模型、操作真实用户数据库；这些动作必须另行取得明确授权。
```

## 继续已授权 Task

用于 `code_authorized: true` 且 Task 已为 `ready` / `in_progress` / `verification` 的现场；本提示词不扩大当前范围。

```text
读取 D:\TransRealm\DEVELOPMENT_STATE.md，核验 Git/授权/当前 Task 与 Milestone 后继续。
只实施已授权范围，先完成 FIT/ADAPT/REPLAN；保留所有既有改动，不做 reset/restore/clean/覆盖。
按垂直切片完成测试、最小实现、受影响旧回归、全量门禁、实际交互/异常验证、独立 Review 和文档同步。
Milestone 全部门禁通过后，可在用户当前分支创建一个仅含该 Milestone 的本地 checkpoint commit；提交前后核对 staged diff、作者身份、文件清单与状态指针。
不得 push、merge、tag、Release、创建远程资源、调用真实/付费模型或操作真实用户数据。
```

## 仅规划或修改 Markdown

```text
读取 D:\TransRealm\DEVELOPMENT_STATE.md。现在只允许规划、审查和修改当前请求明确涉及的 Markdown。
不得修改源码、测试、脚本、配置、依赖或 artifact，不运行会改变项目状态的命令。
核验权威文档、Git 事实、范围、依赖、验收、风险、回滚和授权是否一致；完成后确认 Git diff 只有获准 Markdown。
除非当前文档 Milestone 已完成全部验收，否则不要提交；若提交，只能使用 docs: 前缀创建本地 checkpoint，不得 push。
```

## 只读审查

```text
读取 D:\TransRealm\DEVELOPMENT_STATE.md。现在只做只读审查，不修改任何文件或 Git 状态。
核验当前 Task、授权、Git staged/unstaged/untracked、代码、测试和文档是否一致。
按严重程度报告数据损坏、安全、兼容性、验收、视觉和测试缺口；每项给出路径、触发条件、影响、证据和最小修复方向。
```

## 决策 Agent

```text
读取 D:\TransRealm\DEVELOPMENT_STATE.md 的 pending_decision 与对应权威文档。
只评估决策，不写业务代码。基于不可变约束、现场证据和候选方案输出唯一推荐或明确保留项；说明否决理由、兼容性、安全、迁移/回滚、验收、必须更新的文档和恢复 Milestone。
只在当前请求授权时更新 Markdown；不得实现、提交、push 或发布。
```

## 暂停并交接

```text
暂停继续开发，不再新增业务修改。
更新 D:\TransRealm\DEVELOPMENT_STATE.md：实际修改、命令与结果、兼容性基线、完成/未完成内容、风险、阻塞、工作树归属和下一恢复动作。
不要为了整洁而 reset、restore、clean、覆盖或删除已有工作。
仅当当前 Milestone 已通过全部门禁时，才可创建对应本地 checkpoint commit；不得 push、merge、tag 或发布。
```

通常使用“启动或继续当前代码 Task”；Task 已激活时使用“继续已授权 Task”；只想检查项目时使用“只读审查”。
