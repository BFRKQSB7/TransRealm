# TransRealm v0.2.0 候选已知问题与未覆盖项

> 本文件如实记录候选 `transrealm-0.2.0`（git `5744b9db53028c0bcbed48c37fac9fc6d3fe2d1e` + `requirements.lock` 可定位）的已知行为限制与尚未覆盖的验证项。**记录"未覆盖"不等于"通过"**；其中需要用户/外部环境处理的事项在发布前必须闭环（`RELEASE_CHECKLIST.md`、`03` §12）。

## 1. 候选身份

- 版本：0.2.0；候选 zip `transrealm-0.2.0-win-x64.zip`，sha256 `a4da4eff71facc38064b33042bae45a2ab5a578fdc679cf9c636ac001f9ca498`。
- 候选构建于 git commit `5744b9db53028c0bcbed48c37fac9fc6d3fe2d1e`（manifest `git_dirty=false`）；候选可定位性 = Git 基线 + `requirements.lock` 共同保证。

## 2. 已知问题（行为限制）

- **M02 源码阶段已补充首次配置引导。** 当前工作区的 Settings、Project、Translation 页面会说明 Connection、Model Profile 与 Project active Profile 的关系，并对重复名称和未知异常提供脱敏的恢复提示；这不是已冻结候选的签收结论。
- **本地模型服务由用户自行启动。** TransRealm 不启动或管理命令行 `llama-server`；本阶段自动闭环使用合成数据、loopback fake HTTP endpoint 和生产 transport。真实模型端点未执行，不能将其记为通过。

- **未翻译文档不能导出。** 导出要求该文档**每个段都有当前修订**（已翻译或人工保存过）；任一段缺失修订时整体导出会报错，不会用源文静默代替（这是有意的保真约束，非缺陷）。
- **项目文件（`.aiproject` / 开放目录）导入导出未暴露到界面。** 跨机器迁移能力在应用服务层已实现并验证，但候选界面没有对应入口（见 [`data-safety.md`](data-safety.md) §3）。
- **工作台的历史修订切换受当前段选择约束。** 先选中段和历史修订，再点击 "Use selected revision"；没有选中有效修订时按钮保持禁用。
- **Prompt override 需按版本保持。** 预设模板版本升级后旧 override 会标记 stale（渲染时 fail-closed，不发送请求），需重新保存或清除（界面会提示）。
- **自动翻译只处理待翻译段。** 已完成/锁定/人工修订的段不会被自动结果覆盖；人工 locked 修订受保护。

## 3. 未覆盖项（需用户/后续处理）

- **杀毒扫描未执行（`NOT_RUN-SKIPPED_BY_USER`）。** 当前 v0.2.0 候选 commit=`5744b9db53028c0bcbed48c37fac9fc6d3fe2d1e`、ZIP SHA-256=`a4da4eff71facc38064b33042bae45a2ab5a578fdc679cf9c636ac001f9ca498` 未经反病毒扫描。decision_time=`2026-09-07 Asia/Shanghai`，decision_actor=`user`，execution_actor=`none`，scan_scope/engine/signatures=`not run`。原因：本机 Windows Defender 实时保护已禁用且当前会话非管理员，既有 `MpCmdRun` 尝试返回 hr=0x80004005；用户选择把 AV 作为可跳过项。该状态本身不阻断发布，但绝不等于 `PASS`；残余风险是没有独立反恶意软件检测结论，hash、secret/hygiene 检查与功能测试不能排除此风险。若后续补扫，结果必须绑定同一候选并归档；任何 `FAIL` 都会恢复发布阻塞。2026-08-08 v0.1.0 曾在用户知情例外下未经扫描发布，作为历史事实保留。
- **冻结应用内的完整 GUI 自动化旅程未驱动。** 受 UIAutomation 驱动 Qt 的脆弱性限制，未自动化"冻结应用内创建项目→导入→翻译→导出"全旅程；当前证据 = 冻结应用的启动/迁移/关闭 smoke + 源码级真实窗口完整旅程（P1-T03/P0-T08）。发布后的最终人工 smoke 属用户后续动作。
- **长文本/性能指标只记录基线，不断言阈值。** 资源基线（120 段长文本：约 3.0s、峰值约 2.5MB）是证据记录而非门禁阈值；可比较基线需在候选归档时固化。
- **远程 CI 已接入并全绿。** `quality.yml`（pytest/Ruff/mypy）与 `security.yml`（Candidate hygiene + 迁移顺序）在 push/PR 上运行；2026-08-08 修复 CI 安装步骤（`-e ".[dev]"` 之后追加 `pip install -r requirements.lock`）使锁==安装守卫在 CI 上真实有效，Quality Test/Lint/Type check 均通过（CI 因环境差异额外 skip 符号链接相关用例，非失败）。
- **此前 GitHub Release v0.1.0 已创建（2026-08-08，用户授权）：** tag `v0.1.0`（提交 `7bf26be`），上传当时的候选 `dist/transrealm-0.1.0-win-x64.zip`（sha256 `c59b3ebbe…`）。Release 地址 https://github.com/BFRKQSB7/TransRealm/releases/tag/v0.1.0 。CI 工作流修复为后续提交 `ffb4d8c`（不影响已发布 artifact）。

## 4. 设计边界（非缺陷）

- 凭据只在 `env:`/`wincred:` 引用边界解析，密钥正文不入库/不入档/不落盘；目标机缺引用时给出可操作提示。
- 同一项目重复导入同一源文件（内容哈希一致）不会产生重复段。
- Glossary 注入只使用 locked 条目，按优先级稳定排序；同项目内同一源术语不允许重复。
- 运行中不允许切换模式/文档（需先 finish 或 Cancel），以保持 Run 的 Profile/Workflow/参数不原地改变。
- 迁移只追加不重写；删除程序目录不会删除外置数据。

## 5. 报告问题

安全敏感问题（凭据泄露、数据丢失、不安全归档导入、远程代码执行）请按 `SECURITY.md` 私下联系维护者，不要公开 issue，并提供不含真实秘密/用户数据的复现步骤。
