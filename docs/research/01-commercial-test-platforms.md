# 商业/严肃测试管理平台调研

> 目标：为开源 AI「QA Agent」产品（主 Agent 接活 → 派发专家 Agent 干活 → 一个 Web UI 看进度 + 管理用例与自动化脚本）提取可复用的成熟设计。
> 抓取时间：2026 年，均为厂商官网/官方文档/官方发行页当期内容。

---

## 1. TestRail（Sembi）

**模型**：Project → Suite（树）→ Case（含 steps）→ Plan / Run → Result。分层能力体现在售价分层里：Essentials 就有「不限项目、用例、Plan 和 Run」、共享步骤（Shared Steps）与自定义字段；Professional 加「自定义用例模板」；Enterprise 才有「用例版本化 + 审阅审批」与「用例参数化 + datasets」（[定价页](https://www.testrail.com/pricing/)）。

**用例 ↔ 自动化**：case-first。用例是主数据，自动化结果靠「与 Jira、GitHub、GitLab、Azure DevOps 以及任意测试自动化工具集成」回写，并开放 REST API（100/180/300 次每分钟，按套餐）与 webhooks（[定价页](https://www.testrail.com/pricing/)）。

**最值得抄的一点**：**共享步骤（Shared Steps）**。把「登录/下单」这类前置步骤抽成可复用对象，用例引用它而不是复制它——这是控制用例库腐烂最便宜的手段，且 v1 就能做（`shared_step` 表 + `step_ref`）。

**授权**：按用户订阅，Essentials $22（仅云，≤5 人）、Professional $38、Enterprise $78 /用户/月，年付（[定价页](https://www.testrail.com/pricing/)）。

**UI/UX**：左侧树形套件 + 右侧用例表格；Run 视图按状态着色的一览表；报表以「追溯性 + 缺陷」为主线。

---

## 2. Zephyr Scale（SmartBear）

**模型**：Folder → Test Case → **Test Cycle**（一次执行）→ Test Plan。用例有 steps、参数、版本控制、Gherkin/BDD、数据集（Datasets），并支持 "Call to Test" 做**模块化用例复用**；环境（Environments）、标签（Labels）、迭代（Iterations）可配；自定义字段可下到「用例/周期/计划/步骤/执行」五级（[Test Cases 文档](https://support.smartbear.com/zephyr/docs/en/test-cases.html)、[Test Cycles 文档](https://support.smartbear.com/zephyr/docs/en/test-cycles.html)）。

**用例 ↔ 自动化**：双向。既有 JUnit / NUnit / Pytest / TestNG / Robot Framework / Cucumber 的结果上报集成，也有 CI（Jenkins、Bamboo）对接；还有「record and play 自动生成用例」与无代码自动化，但后者只在中高档「Zephyr / Zephyr Advanced」版本提供（[版本对比](https://support.smartbear.com/zephyr/docs/en/zephyr-editions-feature-comparison.html)）。

**最值得抄的一点**：**Test Cycle 这个概念**。执行不是「跑一下」，而是一个有名字、有环境、可克隆、可重复的实体；把「第 3 轮回归 / staging 环境」这类语义放进对象，比在 Run 上塞一堆标签干净得多（[Test Cycles 文档](https://support.smartbear.com/zephyr/docs/en/test-cycles.html)）。

**授权**：Atlassian Marketplace 上的付费 Jira app，按用户按版本分层（Zephyr Essential / Zephyr / Zephyr Advanced），数据驻留与跨空间报表属付费档能力（[版本对比](https://support.smartbear.com/zephyr/docs/en/zephyr-editions-feature-comparison.html)）。

**UI/UX**：深度嵌入 Jira——用例和执行都挂在 Jira issue 侧栏，好处是零迁移心智，坏处是离开 Jira 就没有产品。

---

## 3. Qase

**模型**：Workspace → Projects；「Tests」下分 Repository（套件树）、Shared Steps、Review、Traceability reports；「Execution」下分 Test plans、Test runs、Environments；另有 Issues / Backlog / Board 与 Dashboards、Queries（[首页导航](https://www.qase.io/)）。即：**用例库与执行域在信息架构上是两块**，而不是混在一棵树里。

**用例 ↔ 自动化**：CI/CD 直连，「CI 结果、自动化测试、手动执行汇到一处」；Free 档就给 5k/月的 API 结果上报量，Teams 档给 35+ 集成与 MCP Server（[定价页](https://www.qase.io/pricing/)）。

**最值得抄的一点**：**Test case review（类 PR 的用例评审）** + **Qase Query Language**。前者让用例库像代码一样走 review；后者把测试数据变成可查询数据集，Dashboard 由查询驱动而非固定图表（[定价页](https://www.qase.io/pricing/)）。

**授权**：Free $0（2 个项目、500MB、30 天历史）；Teams $35/用户/月（年付，月付 $42）；Enterprise 议价；只读协作者 $10/席；AI credits 2000/月，超额 $0.40/credit（[定价页](https://www.qase.io/pricing/)）。

**UI/UX**：Run 页面直接标「240 cases | 59 suites」，右侧列出每个用例的负责人头像与状态——**执行页的第一屏是「谁欠多少活」**，这个信息密度值得照抄（[首页](https://www.qase.io/)）。

---

## 4. Allure TestOps（Qameta）

**模型**：以 **Launch（一次 CI 运行）** 为结果单位，聚合出报告；用例分 manual 与 automated，共存于同一 test base，并用 **Allure ID** 把代码里的测试与用例文档绑定（[首页](https://qameta.io/)、[Smart Test Cases](https://qameta.io/smart-test-cases)）。

**用例 ↔ 自动化**：**code-first 的反向解法**。`allurectl upload ./allure-results` 把已有自动化测试导入，自动生成/更新「可读场景」，测试再次运行时文档随结果更新；反向则由手动用例的 steps **生成 Playwright/TypeScript 代码骨架**，并在生成物里保留 Allure ID 以便结果回流（[Smart Test Cases](https://qameta.io/smart-test-cases)）。支持 37 个测试框架、10 个 CI、10 个 issue tracker，另有 REST API 与 MCP（[首页](https://qameta.io/)）。

**最值得抄的一点**：**「不让人二次录入自动化用例」**——测试名不等于测试意图，所以它用结果反推可读场景，并给出「按 feature 的自动化覆盖率」（不是整体自动化率），指出哪些高优特性还在靠手工（[Smart Test Cases](https://qameta.io/smart-test-cases)）。

**授权**：Cloud $39/用户/月起（1 人起，含 60GB），也提供 on-premise（[首页](https://qameta.io/)）。

**UI/UX**：把多次 run 聚合成一份 release 报告；用 AQL（Allure Query Language）自定义 KPI。

---

## 5. PractiTest

**模型**：把 requirements、tests、automation results、defects 连成**一张可查询的图**，而不是四张互不相干的表；对外主张是「把 QA 数据变成可回答的业务结论」，并单列 Release readiness index（[产品页](https://www.practitest.com/product/)）。

**用例 ↔ 自动化**：自动化结果与手工结果同层并入，供需求级追溯使用（[产品页](https://www.practitest.com/product/)）。

**最值得抄的一点**：**统一过滤层（multi-layer filter）**。需求/用例/运行/缺陷共用一套筛选器语汇，任何视图都是「同一份数据的切片」——这是「追溯矩阵」能自动生成的前提。

**授权**：Team 档 $47/用户/月（年付）；多数据中心（US / EU / AU）（[定价页](https://www.practitest.com/pricing/)）。

**UI/UX**：没有独立的 run board，主界面是仪表盘 + 「同一套筛选器贯穿需求/用例/运行/缺陷」的视图页，以及 Release readiness 视图（[产品页](https://www.practitest.com/product/)）。

---

## 6. Xray（Jira）

**模型**：**用例就是 Jira issue**。测试对象以 Jira issue 形式存在，带自定义字段、富文本、图片、附件，并通过 issue link 关联到需求与缺陷；迁移工具因此必须搬运「自定义字段 + 格式 + 图片 + 附件 + 与 Jira 工作项的链接」（[Testiny 的 Xray 迁移文档](https://www.testiny.io/xray-migration/)）。以 Marketplace app 形式售卖，另有 Xray Enterprise 版本（[Marketplace 页面](https://marketplace.atlassian.com/apps/1211769/xray-test-management-for-jira)）。

**用例 ↔ 自动化**：追溯完全由 issue link 承担（用例 ↔ 需求 ↔ 缺陷）；自动化结果需由外部 CI 上报后挂到用例上，具体框架清单本次未取得官方文档佐证（[Testiny 的 Xray 迁移文档](https://www.testiny.io/xray-migration/)、[Marketplace 页面](https://marketplace.atlassian.com/apps/1211769/xray-test-management-for-jira)）。

**最值得抄的一点**：**零新工具的训练成本**——测试数据直接寄生在团队已有的 issue 系统里，采纳阻力最小。但这也是它最大的枷锁。

**授权**：Atlassian Marketplace 付费 app，按用户数分层订阅。

**UI/UX**：用例详情就是一张 Jira issue 面板（自定义字段 + 富文本 + 附件 + 链接区），追溯矩阵直接读 issue link，不另建 run board——体验完全由 Jira 决定（[Testiny 迁移文档](https://www.testiny.io/xray-migration/)）。

---

## 7. Azure Test Plans

**模型**：Test Plans → Test Suites → Test Cases；Suite 有三种：**static / requirement-based / query-based**（即套件可以是「活的查询」，随需求或查询条件自动增减条目）；用例含 steps + expected results，可引用 Shared Steps 与 Shared Parameters；另有 Configurations hub 管理 OS/浏览器/变量，Plan 可绑定 build（[官方概览](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops)）。结果三层很清晰：Test case（场景）→ Test run（一次执行，含多个用例）→ Test result（每条用例的结果）（[官方概览](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops)）。

**用例 ↔ 自动化**：与 Azure Pipelines 绑定，用 Publish Test Results / VSTest 等任务上报；可把自动化测试与用例关联；纯 pipeline 场景甚至不需要建 Plan/Suite（[官方概览](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops)）。

**最值得抄的一点**：**动态套件 + 执行证据**。套件是查询而非快照，用例永远不会「漏加进回归集」；Test Runner 采集截图、图像操作日志、录屏，建 bug 时**自动带上**全部证据（[官方概览](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops)）。

**授权**：靠 Azure DevOps 访问级别——Test Plans 能力需要 **Basic + Test Plans** 这一档；Stakeholder/Basic 不能建计划与套件（[官方概览](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops)）。

**UI/UX**：Progress report（还剩多少、按天速率）、Runs hub、Requirements quality widget（哪些需求没有测试、通过率多少）、看板内联测试。

---

## 8. TestLink

**模型**：Requirements（带版本/修订）→ Test Specification（用例分组进 Test Suite）→ Test Plan → Build → 在「平台 + Build + Plan」三元组上执行；支持自定义字段与 XML-RPC API（[SourceForge 项目页](https://sourceforge.net/projects/testlink/)）。

**用例 ↔ 自动化**：基本没有原生结果回写，靠 XML-RPC 自己接。

**最值得抄的一点**：**需求的版本化与「证明每条需求都被测过」**——这是它至今仍被引用的原因（[SourceForge 项目页](https://sourceforge.net/projects/testlink/)）。

**授权**：开源，GPLv2，自托管 PHP；最新稳定版 1.9.20（[官网](https://testlink.org/)、[SourceForge](https://sourceforge.net/projects/testlink/)），SourceForge 显示最后更新为 2020-01-19，社区活跃度已很低，用户评论亦直言「项目已停滞、界面过时」（[SourceForge 评论](https://sourceforge.net/projects/testlink/reviews/)）。

**UI/UX**：表格 + 表单式后台，没有现代 run board。

---

## 9. Kiwi TCMS

**模型**：四个一等对象 **TestPlan / TestCase / TestRun / TestExecution**，每个都带 history、tags、attachments；TestCase 与 TestRun 支持 parameters，TestRun 还能 **test matrix generation**（按参数组合自动展开）；用例支持 review（[特性矩阵](https://kiwitcms.org/features/)）。

**用例 ↔ 自动化**：插件式收集结果，官方列了 JUnit 5、junit.xml、pytest、PHPUnit、Robot Framework、TestNG、TAP、Django（[特性矩阵](https://kiwitcms.org/features/)）；对外 API 是 JSON-RPC 与 XML-RPC（[官网](https://kiwitcms.org/)）。

**最值得抄的一点**：**test matrix generation**——参数化用例自动展开成矩阵，一行数据驱动多个执行项；配合「一键报 bug + 自动回写 bug 状态」（集成 12 种以上缺陷跟踪系统）非常省事（[特性矩阵](https://kiwitcms.org/features/)）。

**授权**：上游 GPL-2.0+ 开源；商业侧是订阅制——Self Support $35/月、Private Tenant $150/月、Enterprise $600/月、Managed Hosting $2000/月/实例（[官网订阅](https://kiwitcms.org/)）。

**UI/UX**：中央 dashboard 显示「今天要跑什么」，是纯手动测试队最省心的首页范式（[官网](https://kiwitcms.org/)）。

---

## 10. 新一代轻量工具：Testiny、Tuskr、TestLodge

**Testiny**：把 manual run 与自动化结果**放在同一个 project 里并排展示**，用 Milestones 把两者滚进同一个发布目标；自动化侧「不锁框架」——直接吃 JUnit XML / Playwright JSON / Mochawesome 等标准报告，支持 20+ 框架，CI 不限，失败附带截图、视频、trace 与环境信息（[Features](https://www.testiny.io/features/)）。按席位：Free ≤3 人；Starter $15.42/用户/月（≤25 人）；Business $17.08；Enterprise $25（5 席起），另有自托管 Testiny Server（[定价](https://www.testiny.io/pricing/)）。**最值得抄的**：标准报告直接导入 + 自托管同款，这两点对开源产品是硬要求。

**Tuskr / TestLodge**：本次无法核实——`tuskr.app` DNS 解析失败，`www.testlodge.com` 返回 Cloudflare 挑战页（403），仅 `app.testlodge.com` 登录页可达。两者通常被归为「轻量低价」档，但价格与数据模型**未取得可引用的一手来源**，故不做断言；这本身也说明小厂文档可评估性差（[TestLodge](https://www.testlodge.com/)、[Tuskr](https://tuskr.app/)）。

---

## 综合一：最值得借鉴的 10 个设计（面向 v1）

1. **四层对象，字段写死**：`project` → `suite(parent_id, path)` → `case` → `run` / `run_item`。`case` 关键字段：`key`（稳定人类 ID，如 `QA-123`，全生命周期不变）、`title`、`priority`、`type`、`tags[]`、`steps[{idx, action, expected, data}]`、`preconditions[]`、`shared_step_refs[]`、`params`、`automation_ref`、`status`。
2. **用例与脚本「弱耦合 + 稳定 ID」**（学 Allure + Kiwi）：`case.automation_ref = {kind: repo_path|test_id|external, value}`，另存 `last_result_id`。CI 上传结果时按稳定 ID 匹配；**匹配不上不自动建用例**，而是进 `unmapped results` 收件箱等人工确认——全自动建用例会污染用例库。
3. **结果必须三层**：`run`（批次：环境、build、触发者、起止）→ `run_item`（用例 × 配置）→ `step_result`。绝不允许把「结果」字段写回 `case` 表。
4. **Run 是一等对象而不是「一次点击」**（学 Zephyr 的 Test Cycle）：`run.name`（如「v1.4 回归 / staging」）、`environment`、`cloneable`、`assignee`、`state: planned → in_progress → completed → closed`。
5. **动态套件（query-based）**（学 Azure）：`suite.rules`（jsonb）保存筛选条件，套件只读渲染；v1 只需支持 `tag`、`priority`、`automation` 三个维度。
6. **用例评审 + 版本**（学 Qase / TestRail Enterprise）：`case_revision(case_id, rev, snapshot, author)`，状态 `draft → in_review → approved`，UI 给 diff 视图；只有 `approved` 的版本可进正式 run。
7. **共享步骤**（学 TestRail）：`shared_step(id, name, steps[])`，用例按引用插入，改动全库同步。
8. **参数化 → 自动展开执行矩阵**（学 Kiwi）：`case.params` 定义数据组合，生成 `run_item` 时展开，UI 上折叠成一行「×6 组合」。
9. **执行证据挂在 step 级**（学 Azure + Testiny）：`step_result.attachments[{type: screenshot|video|trace|log|har]}`；失败时自动附最近一次运行的证据，并支持「一键建 issue」把证据带过去。
10. **AI 任务即 Run**：这是我们要新增的维度——`task(agent_job)` 与 `run` 共用一套展示与状态机（`queued → running → needs_review → done/failed`），专家 Agent 的每一步输出 = `step_result`，人看到的进度条就是 run board。这样「派活给 AI」和「跑测试」在 UI 上是同一个心智模型。

**v1 需要的 5 个界面**：① 项目内用例树 + 用例编辑器（步骤表格 + 附件 + 自动化绑定）；② Run board（左：套件/筛选；右：网格化状态与负责人）；③ 执行详情（步骤级 pass/fail + 证据 + 建 issue）；④ Traceability（需求 ↔ 用例 ↔ 最近结果，同一筛选器语汇）；⑤ Agent 任务页（同 run board 组件，显示子任务与专家 Agent 产出）。

---

## 综合二：应该避免的坑

- **别在 v1 做自定义字段 + 多级 RBAC + 审批流**：TestRail 把这些明确摆在 Professional/Enterprise 档（[定价](https://www.testrail.com/pricing/)），它们是复杂度的分水岭，不是标配。
- **别把执行状态做成十几种**：`passed / failed / blocked / skipped / not_run` 五态 + `reason` 文本足够；状态机一膨胀，每个报表都要重写一遍映射。
- **别用静态套件手工维护回归集**：靠复制粘贴，用例库必然出现双份；用查询式套件（学的 Azure）替代。
- **别强迫人二次录入自动化用例**：这是此类工具最大的隐性成本，Allure 整套产品就建立在「消灭这份重复」上（[Smart Test Cases](https://qameta.io/smart-test-cases)）。
- **别把树做成任意深度**：四五层目录在小团队里只会让人找不到用例；3 层封顶，靠 tag 与搜索补。
- **别把产品绑死在某个 issue 系统上**：Xray 的能力上限就是 Jira 的上限（[Marketplace](https://marketplace.atlassian.com/apps/1211769/xray-test-management-for-jira)）。
- **别先做需求管理**：TestLink 的需求版本化很强，却没换来留存（[项目页](https://sourceforge.net/projects/testlink/)）；v1 只需一个可链接的外部需求 key。
- **别先做查询语言/BI**：Qase 的 Query Language 与 Allure 的 AQL 都很强，但要等数据量与使用习惯起来后才有价值。

---

## 综合三：横向对比

| 平台 | 模型核心 | 自动化接入方式 | 单点最值得抄 | 授权/价格 |
|---|---|---|---|---|
| [TestRail](https://www.testrail.com/pricing/) | Project→Suite→Case→Plan/Run | 任意工具 + REST/webhook 回写，case-first | 共享步骤（Shared Steps） | $22 / $38 / $78 每人每月（年付） |
| [Zephyr Scale](https://support.smartbear.com/zephyr/docs/en/test-cycles.html) | Folder→Case→**Test Cycle**→Plan | JUnit/Pytest/TestNG/Robot/Cucumber + Jenkins/Bamboo | Test Cycle 作为可克隆执行实体 | Marketplace app，三档订阅 |
| [Qase](https://www.qase.io/pricing/) | 用例库（Repository）与执行域（Plans/Runs）分离 | CI 直连 + 35 集成 + MCP | 用例 PR 式评审 + 查询语言 | Free；Teams $35/席/月；协作者 $10 |
| [Allure TestOps](https://qameta.io/smart-test-cases) | Launch 聚合结果 + Allure ID 绑定 | allurectl 导入结果，反向生成代码骨架 | 结果驱动自动维护用例（Smart Test Cases） | Cloud $39/席/月起，亦支持私有化 |
| [PractiTest](https://www.practitest.com/product/) | 需求/用例/结果/缺陷一张可查询图 | 结果并入统一层 | 统一过滤层 → 自动追溯 | Team $47/席/月 |
| [Xray](https://marketplace.atlassian.com/apps/1211769/xray-test-management-for-jira) | 用例 = Jira issue | issue link + CI 上报 | 零新工具心智/原生追溯 | Marketplace 付费 app |
| [Azure Test Plans](https://learn.microsoft.com/en-us/azure/devops/test/overview?view=azure-devops) | Plan→Suite(静态/需求/查询)→Case→Run→Result | Pipelines 任务上报，可关联用例 | 动态套件 + 证据自动附 bug | 需 Basic + Test Plans 档 |
| [TestLink](https://sourceforge.net/projects/testlink/) | 需求→用例(套件)→Plan→Build→执行 | 仅 XML-RPC，弱 | 需求版本化与覆盖证明 | GPLv2 开源，已停更 |
| [Kiwi TCMS](https://kiwitcms.org/features/) | TestPlan/TestCase/TestRun/TestExecution | 插件式（JUnit/pytest/Robot…） | 参数展开 test matrix | GPL-2.0+；订阅 $35–$2000/月 |
| [Testiny](https://www.testiny.io/features/) | 项目内手工与自动化并排 + Milestones | 标准报告文件直传，20+ 框架，CI 无关 | 不锁框架的自托管同款 | Free ≤3 人；$15.42–$25/席/月 |

**结论一句话**：v1 抄 **Zephyr 的 Test Cycle 模型** + **Azure 的动态套件与 step 级证据** + **Allure 的稳定 ID / 结果驱动同步思路** + **Kiwi 的参数展开**，但把「AI 专家 Agent 的任务」直接建模成 Run——这是我们相对上述所有产品的结构性差异点。
