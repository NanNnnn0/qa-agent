# 调研：相似软件与工具（第一版采纳记录）

三份调研文档分别覆盖商业测试管理平台、自动化工具链、AI 原生测试产品与 agent 编排：

- [`01-commercial-test-platforms.md`](./01-commercial-test-platforms.md)：TestRail、Zephyr、Qase、Allure TestOps、PractiTest、Xray、Azure Test Plans、TestLink、Kiwi TCMS、Testiny、Tuskr/TestLodge。
- [`02-automation-tooling.md`](./02-automation-tooling.md)：pytest+httpx、Schemathesis、Playwright、Cypress、Robot Framework、Hurl、Karate、Pact、Bruno、JUnit XML/CTRF/Allure、用例设计方法学、AI 生成护栏。
- [`03-ai-qa-agents.md`](./03-ai-qa-agents.md)：Testim、mabl、QA Wolf、Momentic、Reflect、Octomind、Autify、testRigor、Applitools、KaneAI、Diffblue；以及 Claude Code/Codex/Devin/OpenHands 等编排方式。

调研期间的 `web_search` 后端返回 401，作者改用 `web_fetch` 直抓官方文档；无法核实的来源（BrowserStack Test AI、Octomind、Tuskr、TestLodge、Codex 机制）已在各自文档中标注"未核实"，未编造。

## 第一版实际采纳

| 结论 | 落地位置 |
|---|---|
| 用例与执行解耦：用例是带稳定编号的对象，脚本按 `case_ids` 弱耦合 | `cases.code`、`scripts.case_ids` |
| 结构化接口用例（请求 + 断言是数据，不是自然语言） | `cases.api` 契约 + `nanobot/qa/runner.py` + `validation.validate_api_spec` |
| 接口主链路 pytest + httpx；UI 主链路 Playwright | 内置 httpx runner；pytest 脚本执行；Playwright 脚本管理与模板 |
| 报告互操作：JUnit XML 兜底 + CTRF 风格扁平 tests[] | `service.execute_script` 解析 junitxml；`runner` 报告 `{tests:[{status,message,checks}]}` |
| 失败分类必须区分环境问题，否则污染缺陷与 flake 统计 | `run.status=blocked_by_env` + `_all_environment_errors` + `qa-report` skill |
| 任务状态机与"计划即对象"：AI 任务有明确状态与产物 | `tasks` 表 + `needs_review` + `task_artifacts` + `task_events` |
| 只允许固定角色、固定工具、固定收尾格式，减少输出漂移 | `nanobot/qa/roles.py` + `nanobot/skills/qa-*` |
| 自愈/修复要设上限，禁止删断言"修绿" | `qa-automation` skill 的修复纪律（每用例 ≤2 次，超限 needs_review） |
| 竞品复杂度的分水岭：自定义字段、多级 RBAC、审批流不进 v1 | 设计文档"非目标"章节 |
| 用 run board 同时承载"AI 派单"与"测试执行"两种心智模型 | 工作台任务板 + 运行记录两 tab（数据同源） |
| nanobot 适合做执行器/工具层，不适合直接当编排层 | 任务状态机、角色、产物、UI 均自建在 `nanobot/qa/` |

## v1.1 追加采纳

| 结论 | 落地 |
|---|---|
| 运行是一等对象（Zephyr Test Cycle 的最小可用版） | `runs.name / environment / trigger`，UI 与 CLI 均可见 |
| CI 结果互操作优先 JUnit XML（所有 runner 都能产出） | `nanobot qa import-junit` + `qa_run action=import` + 工作台导入 |
| 审批必须有审计轨迹（KaneAI "先审 test plan 再执行"） | `qa.task.approve/reject` 写 `approved/rejected` 事件（评审人 + 备注） |
| 环境问题与产品缺陷分离（避免 flake 统计被污染） | `blocked_by_env` 状态 + 报告分类纪律（v1 已做，v1.1 在审批里保留） |

## 明确推迟（调研支持但第一版不做）

- **Run 升级为测试周期**（name/environment/cloneable/planned→in_progress→completed→closed）：需要 UI 与查询重构。
- **动态套件（query-based suites）**：v1 用 project+kind+搜索过滤，足够单项目回归。
- **CI 结果摄取与 unmapped results 收件箱**：Allure 的教训是全自动同步会污染用例库，所以下一步做"匹配不上进收件箱"的半自动方案，而不是直接双向同步。
- **OpenAPI 生成用例、Schemathesis 属性测试、PICT/allpairspy 组合生成**：先把结构化用例与执行打稳。
- **Playwright 执行托管、trace 归档、视觉回归**：依赖浏览器环境，放到执行栈下一阶段。
- **多租户/RBAC/审批流/BI**：属于竞品 Professional/Enterprise 档的复杂度，不进入个人/小团队版本。

## 关键风险与对策

| 风险 | 对策 |
|---|---|
| AI 生成用例重复、覆盖虚高 | 编号唯一约束 + `qa_case list` 查重 + 报告口径"只算验收标准覆盖" |
| AI 把环境问题当产品缺陷 | `blocked_by_env` 状态 + 报告失败分类强制四选一 |
| AI 修脚本时删断言让测试变绿 | skill 明文禁止 + 修复次数上限 + review 角色 |
| 模型输出格式漂移 | `api` 结构与断言类型强校验（非法直接 400/工具报错） |
| 派单任务状态失真 | 工具读任务时主动与 SubagentManager 对账；子任务收尾必须回填 |
| 大仓库改动风险 | 只新增 `nanobot/qa`、`nanobot/agent/tools/qa.py`、路由合并点与技能目录；既有测试全绿 |
