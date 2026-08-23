# TransRealm Agent 操作提示词

项目目录：`D:\TransRealm`

所有模板都以 `DEVELOPMENT_STATE.md` frontmatter、当前 Task/Milestone、权威编号文档和 Git 现场为准。本文件只定义“这一次允许 Agent 做什么”，不保存版本进度。

## 先选模式

以下十种模式一次只使用一个。角色名称本身不授予权限；权限来自你粘贴的模板和同一条消息中的补充指令。

| 你的目的 | 使用模板 | 可以写什么 | 明确不能做什么 | 成功终点 |
|---|---|---|---|---|
| 首次授权当前代码 Milestone 并完成它 | A. 授权并执行 | 当前 allowed paths 内的代码、测试、必要文档 | 扩范围、发布、远程动作 | Milestone 完成或写清真实阻塞 |
| 继续已经授权且未完成的实现 | B. 继续执行 | 既有授权范围 | 改授权、改目标、顺手处理范围外问题 | 当前 Milestone 完成或真实阻塞 |
| 只恢复测试环境、旧 artifact 等验证现场 | C. 恢复验证基线 | 环境、可逆 artifact 归档、必要 Markdown | 业务代码、测试语义、lock、构建发布 | 原 Gate 可复现执行 |
| 规划任务或维护契约文档 | D. 仅规划 Markdown | 当前请求点名或必需联动的 Markdown | 代码、测试、依赖、artifact | 方案可执行且 diff 仅含获准文档 |
| 找问题，不修、不改状态 | E. 只读 Review | 无 | 任何文件修改、验收放行 | 按严重度给出可复现 findings |
| 在候选方案中作取舍 | F. 决策 Agent | 获授权时仅裁决/契约 Markdown | 实现、测试修复、提交 | 唯一推荐或明确保留项 + 恢复提示 |
| 独立验证交付并决定是否放行 | G. 验收 Agent | 获授权时仅验收/状态 Markdown | 修业务代码、降低门禁、替开发者自证 | APPROVE 或带证据的 REJECT/BLOCKED |
| 立刻停止新增开发并留下可恢复现场 | H. 暂停交接 | `DEVELOPMENT_STATE.md` 等交接 Markdown | 新增业务修改、清理工作树 | 下一 Agent 可无猜测恢复 |
| 在当前 release 内无人值守连续推进 | I. 连续无人开发 | 逐 Task 的 allowed paths、测试、必要文档、本地 checkpoint | 越过 release、待决策节点、外部动作 | 当前 release 完成或遇到真实性阻塞 |
| 立即撤销连续推进授权并安全停下 | J. 中断连续无人开发 | 仅安全收敛与交接 Markdown | 新任务、新修复、新门禁、提交 | 保留现场并给出精确恢复点 |

若目的同时落入两个模板，先完成权限更窄的模板，再由用户发起下一种模式；不要把 Review、决策、修复和验收混在同一轮。

## 长期授权边界

- 禁止创建、切换或删除分支；始终在用户当前分支上工作。若现场分支与状态记录不一致，停止并报告，不得自行切换。
- 允许在每个 Milestone 验收通过后创建本地 checkpoint commit，包括必要的暂存；提交只能包含当前 Task 授权范围和已确认归属的既有改动。
- commit 前必须核对 staged diff、允许路径、测试/Review 证据和生效的 Git 作者身份；commit 后复核 commit 作者、文件清单和 `DEVELOPMENT_STATE.md` 指针。
- 提交信息使用 `feat` / `fix` / `docs` / `refactor` / `chore` 前缀。不得为制造进度创建未验证的空提交或混合多个 Milestone。
- 不允许覆盖、丢弃、reset、restore、clean、强制切换、amend/rebase 既有历史或删除用户改动，除非用户针对具体目标另行授权。
- push、merge、tag、GitHub Release、远程资源、真实/付费模型调用和真实用户数据操作仍需单独明确授权；本地 commit 不等于允许外部动作。

## A. 授权并执行当前代码 Milestone

用途：当前 Task/Milestone 尚未获得代码授权，你希望 Agent 在门禁满足时激活并直接完成它。本模板会授予实现权限，不适合只想看方案时使用。

```text
模式：授权并执行当前代码 Milestone。
读取 D:\TransRealm\DEVELOPMENT_STATE.md，并按“唯一 Agent 交接入口”处理当前 Task/Milestone。本消息明确授权 current_task/current_milestone 的 allowed paths 内代码、测试和必要文档修改；不授权任何范围外修复。

先核验 HEAD、branch、staged/unstaged/untracked、既有改动归属、依赖、测试证据、planning baseline 和 rollback_ref。若状态为 proposed/code_authorized:false，只有在任务定义完整、依赖满足、基线可恢复且没有 REPLAN 冲突时，才把授权状态推进为 ready 并记录实际 base_commit；否则不写业务代码，只报告缺失条件。

可执行时持续完成当前 Milestone：Reality Check → 验收样例/测试 → 最小实现 → 指定旧回归 → 全量质量门禁 → 适用的 GUI/异常/安全验证 → 独立 Review → 文档与状态同步。不得扩大目标、allowed paths、公共契约、依赖或发布范围。

全部门禁通过后，才可在当前分支创建仅含该 Milestone 的本地 checkpoint commit。若遇真实阻塞，保留现场并写清复现、影响、已排除原因、解除条件和恢复动作。

不得 push、merge、tag、Release、创建远程资源、调用真实/付费模型或操作真实用户数据。
最终必须报告：结果、修改文件、验证原始结果、兼容性/安全结论、未覆盖项、checkpoint（如有）和下一状态。
```

## B. 继续执行已授权 Milestone

用途：`code_authorized: true` 且状态为 `ready`、`in_progress` 或 `verification`。本模板不授予新权限，也不能用来解决范围外 Gate。

```text
模式：继续执行，不改变任何授权或任务定义。
读取 D:\TransRealm\DEVELOPMENT_STATE.md，核验 Git、current_task/current_milestone、authorization_scope、既有改动归属和恢复动作。

只在现有 allowed paths 内继续，从尚未完成的第一个验收点接上；不得重新激活 Task、扩大范围、修改硬约束或顺手修复范围外失败。先确认已有 FIT/ADAPT/REPLAN 是否仍与现场一致；新证据冲突时停止冲突部分并记录 REPLAN。

完成剩余测试、最小实现、指定旧回归、全量门禁、实际交互/异常验证、独立 Review 和文档同步。全部门禁通过后才可创建当前 Milestone 的本地 checkpoint commit。

不得 reset/restore/clean/覆盖既有改动，不得 push、merge、tag、Release、创建远程资源、调用真实/付费模型或操作真实用户数据。
最终只报告本轮新增结果、累计验收状态、阻塞或 checkpoint，以及准确的下一恢复点。
```

## C. 恢复验证基线（不改业务）

用途：实现本身已验证，但 Gate 被解释器、安装依赖、缓存或陈旧候选 artifact 等现场问题阻塞。它不是修 bug 或重写测试的授权。

```text
模式：恢复验证基线，不改业务实现或测试语义。
读取 D:\TransRealm\DEVELOPMENT_STATE.md 中已裁决的 Gate 阻塞、环境基线、artifact 处置、回滚要求和 resume_milestone。

允许：只读诊断；创建/重建隔离验证环境；严格按既有 lock 恢复依赖；把明确陈旧且不属于当前候选的 ignored artifact 连同 manifest/hash 可逆归档到仓库外；更新当前请求必需的 Markdown 证据。
禁止：修改源码、测试、脚本、pyproject、requirements.lock 或候选内容；删除/覆盖旧 artifact；从 dirty 工作树构建候选；暂存、commit、push、tag 或发布。

先记录操作前路径、hash、环境和 Git 状态；恢复后运行原失败 nodeid、全量 pytest、Ruff、mypy 及当前 Milestone 指定回归。skip 必须逐项说明为何不适用，不能把失败改成 skip。

成功终点仅是“Gate 可复现执行并得到可信结果”。把证据和恢复动作写入 DEVELOPMENT_STATE.md，然后停止；由开发/验收模式决定是否完成 Milestone。
```

## D. 仅规划或修改 Markdown

```text
模式：仅规划 Markdown，不授予代码开发。
读取 D:\TransRealm\DEVELOPMENT_STATE.md。只审查和修改当前请求点名的 Markdown，以及为消除直接冲突不可缺少的权威 Markdown。

不得修改源码、测试、脚本、配置、依赖或 artifact，不运行会改变产品、Git 历史、依赖环境或外部状态的命令。核验产品范围、现场事实、依赖、allowed paths、验收、兼容性、安全、迁移/回滚和授权是否一致；不得用规划声明替代测试事实。

完成后确认 diff 只含获准 Markdown，并报告新增/改变的决策、仍保留项和代码是否仍未授权。除非用户明确要求且文档 Milestone 已验收，不得提交；不得 push。
```

## E. 只读 Review Agent

```text
模式：独立只读 Review；不修复、不放行、不改状态。
读取 D:\TransRealm\DEVELOPMENT_STATE.md 和当前 Task 的目标、非目标、硬约束、allowed paths 与验收。核验 Git staged/unstaged/untracked、实现 diff、测试和文档声明。

不得修改任何文件、依赖、artifact 或 Git 状态，不得替开发 Agent 补实现，也不得把 Task/Milestone 标为 completed。

只报告可复现 findings，按 BLOCKER / SHOULD-FIX / MINOR 排序。每项必须包含：文件与位置、触发条件、实际影响、违反的契约、证据、最小修复方向和需要补的测试。没有 finding 时明确写 APPROVE，并列出实际检查范围和未检查项。
```

## F. 决策 Agent

```text
模式：架构/产品/门禁决策，不做实现或验收。
读取 D:\TransRealm\DEVELOPMENT_STATE.md 的 pending_decision；若 pending_decision:none，仅在用户本条消息明确提出决策问题时继续，否则报告“没有待决策节点”并停止。

核验不可变约束、现场证据、待确认事实和 2-3 个可行候选。输出一个唯一推荐；只有证据不足且现在选择会造成不可逆风险时，才允许列出明确保留项和解除条件。逐项说明否决理由、兼容性、安全、迁移/回滚、验收、必须更新的权威文档和 resume_milestone。

不得写业务代码、测试或脚本，不得运行实现/构建/发布动作，不得提交。只有本条用户消息明确授权修改 Markdown 时，才可把 decision_result、契约变更和开发恢复提示写回获准文档。

最终必须给出供开发 Agent 使用的恢复提示；不得自行切换为开发模式实施裁决。
```

## G. 独立验收 Agent

```text
模式：独立验收并决定是否放行；不修业务代码。
读取 D:\TransRealm\DEVELOPMENT_STATE.md、当前 Milestone 验收、Review findings、兼容性基线和原始测试证据。重新核验实际 diff、allowed paths、关键命令和适用的 GUI/安全/迁移/回滚证据，不接受仅由开发 Agent 写出的完成声明。

不得修改源码、测试、脚本、依赖或 artifact，不得降低、删除或改写失败门禁。发现缺陷时输出 REJECT/BLOCKED 及最小返工范围，不代替开发 Agent 修复。

仅当本条消息授权 Markdown 更新且全部门禁真实通过时，才可把状态改为 completed、推进下一 Milestone，并按长期授权边界创建本地 checkpoint；任一适用 Gate 未通过时不得提交。

最终输出且只能选择一个结论：APPROVE、REJECT 或 BLOCKED；同时列出复核证据、未覆盖项、状态/commit 动作和下一角色。
```

## H. 暂停并交接

```text
模式：立即暂停并形成可恢复交接，不再新增业务修改。
读取并更新 D:\TransRealm\DEVELOPMENT_STATE.md，记录实际修改、命令与原始结果、兼容性基线、完成/未完成内容、风险、阻塞、工作树归属、解除条件和下一条可直接执行的恢复动作。

不得新增或修复业务实现，不得为了整洁 reset、restore、clean、覆盖、移动或删除已有工作。仅当暂停前当前 Milestone 已通过全部门禁时，才可按既有授权创建对应本地 checkpoint；否则保持工作树原样。不得 push、merge、tag 或发布。

最终报告当前精确状态、未提交文件归属、最后可信证据和下一次应使用本文件中的哪个模板。
```

## I. 连续无人开发

用途：你希望开发 Agent 从当前恢复点开始，在没有真实性阻塞时自行完成当前 release 内连续的 Milestone 和 Task，而不是每完成一个小目标就等待新的“继续”消息。粘贴本模板即授予这种跨 Milestone 连续执行权限，但不授权跨 release、改变产品方向或任何外部动作。

```text
模式：当前 release 内连续无人开发。
读取 D:\TransRealm\DEVELOPMENT_STATE.md，并从 current_task/current_milestone 的精确恢复点开始。本消息授权你连续实施 DEVELOPMENT_STATE.md.current_release 内已经由权威文档定义、依赖满足且没有待决策节点的 Task/Milestone；每个 Task 仍只能修改其自身 allowed paths 和必要状态文档。为满足既有独立审查门禁，本模板同时明确授权你为每个 Milestone 调用只读 Review Agent，但 Review Agent 不得参与实现或代替验收。不得把本授权延伸到下一 release、未批准构想或范围外清理。

首次和每次推进指针后都重新核验 HEAD、branch、staged/unstaged/untracked、既有改动归属、base_commit、rollback_ref、authorization_scope、依赖和当前验收，记录 FIT/ADAPT/REPLAN。普通私有实现选择、可逆 ADAPT、测试 fixture、文件组织和范围内缺陷由你自行决定，不询问用户。

对每个 Milestone 连续完成：验收样例/测试 → 最小实现 → 指定旧回归 → 全量 pytest/Ruff/mypy → 适用的 GUI/异常/安全/迁移/回滚验证 → 独立 Review → 文档和状态同步。门禁全部通过后，在用户当前分支创建一个只含该 Milestone 的本地 checkpoint commit，复核作者、文件清单和状态指针，然后自动进入下一个依赖满足的 Milestone/Task，不等待用户确认。

测试失败、实现困难、需要调查、可复现的范围内 bug、可重建缓存/隔离环境或一次工具故障都不是真实性阻塞。不得因这些情况提前结束，也不得盲目重复同一命令：定位根因，采用范围内最小修复或安全替代路径，补证据后继续。

只有以下情况才停止：
1. pending_decision 非 none，或 REPLAN 会改变产品行为、公开契约、Project/数据格式、已批准架构、依赖/安全边界或当前 release 范围；
2. 缺少只能由用户提供的凭据、付费额度、真实文件、外部服务权限或法律/发布签发；
3. 继续会覆盖归属不明的既有改动、破坏用户数据，且无法通过只读核验、隔离或可逆方案消除风险；
4. 当前 release 的所有 Task 已完成，下一步是候选签发、push、merge、tag、Release、远程资源或下一 release。

停止时必须先完成所有不受阻部分，并把真实性阻塞写入 DEVELOPMENT_STATE.md：复现、现场证据、已尝试且互不重复的方案、不可自行解除的原因、最小用户动作、受影响范围、回滚/恢复动作和 resume_milestone。若触发决策节点，写出完整 decision package 和可直接粘贴的“F. 决策 Agent”恢复提示。

始终禁止创建/切换/删除分支、reset/restore/clean/覆盖用户改动、amend/rebase、push、merge、tag、Release、创建远程资源、真实/付费模型调用和真实用户数据操作。连续无人开发不降低任何测试、Review、迁移、秘密、数据或发布门禁。

持续工作期间定期给出简短进度；只在当前 release 完成或真实性阻塞成立时结束。最终报告每个 checkpoint、累计测试证据、未覆盖项、停止原因和下一精确动作。
```

## J. 中断连续无人开发

用途：连续无人开发正在进行时，你希望它立即停止自动推进，同时保住当前工作和可恢复性。本模板优先于此前的“继续”“连续”“完成整个 release”要求；它撤销继续开发权限，不把用户主动中断伪报成 `blocked`。

```text
模式：中断连续无人开发并安全交接。
本消息立即撤销此前“连续无人开发”及任何自动进入下一 Milestone/Task 的授权。收到后不得启动新的实现、修复、测试矩阵、构建、Review、暂存或提交；不得为了完成原计划而继续推进。

若一个命令或进程已经在途，只做防止数据损坏所需的最小安全收敛：优先使用既有取消/正常关闭机制；允许读取其最终状态或等待一个有界安全点；不得强杀可能正在写数据库、artifact 或用户文件的进程。若无法安全停止，立即说明在途动作、可能影响和最小用户操作，不再发起其他动作。

保护当前 Git staged/unstaged/untracked 和所有既有改动。不得 reset、restore、clean、覆盖、删除、移动、格式化或顺手修复；不得补跑全量门禁。已经完成的命令结果如实记录，未完成/被取消的验证不得写成 passed。

只允许更新 D:\TransRealm\DEVELOPMENT_STATE.md 及直接必需的交接 Markdown，记录：
1. 用户主动中断时间与原因（未提供原因时写“user_requested_interrupt”）；
2. 最后完成的 Milestone/checkpoint 和当前精确 Task/Milestone；
3. 当前状态、plan_alignment、已改文件归属和 staged/unstaged/untracked；
4. 最后可信测试/Review 证据，以及正在运行、取消或未执行的命令；
5. 未完成的第一项工作、风险、恢复前检查和 resume_milestone；
6. 下次应使用“B. 继续执行”还是“I. 连续无人开发”。

除非中断消息到达前 checkpoint 已经完整创建成功，否则不得因中断补建 commit。用户主动中断不是技术阻塞：没有独立外部解除条件时保持实际的 ready/in_progress/verification 状态，并把停止原因单独记录为 user_requested_interrupt。

不得 push、merge、tag、Release、创建远程资源、调用真实/付费模型或操作真实用户数据。完成安全收敛与交接后立即结束，不自行恢复连续开发。
```

## 常用选择

- 新 Task 第一次开工：A。
- 已经在实现或验证中：B。
- 功能测试通过但被本机环境/陈旧 `dist` 阻塞：C。
- 只想改计划：D。
- 只想找问题：E。
- 需要在多个方案中裁决：F。
- 开发完成后由另一 Agent 放行：G。
- 需要立刻停手并留现场：H。
- 希望不再逐 Milestone 手动回复“继续”：I。
- 需要立即叫停正在运行的 I 模式：J。
