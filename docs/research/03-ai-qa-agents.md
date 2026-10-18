# 03 · AI QA Agent 调研：产品形态、编排模式与确定性护栏

> **方法说明**：本会话的 `web_search` 后端鉴权失败（HTTP 401），全部事实来自对官方页面/文档的 `web_fetch` 一手抓取；**表格中的产品名即来源链接**。
> **未能核实、故不做机制断言**：BrowserStack Test AI（403 挑战页）、Octomind（DNS 不可达）、testRigor 细节（正文未渲染）、OpenAI Codex 具体机制（官方页 403，仅取到仓库自述）、mabl 公开价目（定价页正文被截断）。

## 1. AI 原生测试产品：AI 究竟在做什么

| 产品 | AI 做什么 | 测试表示 | 计价 | 值得借的一点 |
|---|---|---|---|---|
| [QA Wolf](https://www.qawolf.com/pricing) | 探索建覆盖、写脚本、挑 PR 相关用例、归因失败、修脚本、提 bug | 开源 Playwright / Appium 代码 | 按 run：网页 $1、移动/桌面 $2；不限席位；AI 与 3 次重试不另计费 | **按"验证过的结果"计费**：flake、修脚本、提 bug 都算一个 run |
| [Momentic](https://momentic.ai/) | 写用例、运行时重定位、产出 test-file 修复供 review、失败分类 | 仓库内 plain-English YAML | 商业套餐 + Mo credits | **测试与代码同仓、可 PR review**；CLI 退出码当必需 CI 检查 |
| [Reflect (SmartBear)](https://smartbear.com/product/reflect/) | 自然语言转动作、自愈、把手工用例转自动 | 录制 + plain-English 步骤 | [credits](https://smartbear.com/product/reflect/pricing/)：5k/20k/40k 每月，不限席位 | 从 Zephyr 等测试管理工具直接跑手工用例 |
| [Testim (Tricentis)](https://www.testim.io/) | 录制时识别元素、AI/ML 自定义 locator 自愈、自然语言建测试、根因分析 | 录制 + 可插代码 | 未核实 | 把"定位器"做成按应用类型训练的资产，而非脆弱选择器 |
| [Autify](https://autify.com/) | Aximo agent 用自然语言 + 视觉识别自主生成并执行；Genesis 从需求/源码生成用例 | 无人值守 agent 会话（可 "Save as a case"） | credits，按所选模型计（如 Claude Sonnet 1x credit） | 会话跑完可**一键沉淀为可复用 case** |
| [KaneAI (TestMu AI)](https://www.testmuai.com/kane-ai/) | 从 Jira/PRD/PDF 生成用例、自然语言授权、自愈、逐步 triage、提 ticket | 自然语言 + 可导出 Playwright | 商业套餐 / credits | **"No Agent Runs Blind"**：先审计划再执行，运行中可暂停改步 |
| [Applitools](https://applitools.com/platform/) | Visual AI 比对、Deterministic LM 执行步骤、coded locator healer、给 agent 供 pixel diff | 代码 SDK / NLP / 录制 | 未核实 | 用**专用确定性模型**替代通用 LLM 跑步骤 |
| [Diffblue](https://docs.diffblue.com/) | 分区生成 Java/Python 回归单测、验证失败即回滚 | 真实代码（临时 git worktree 内） | 企业授权（未取到公开价目） | **验证通过才 commit，失败即 rollback** |
| [mabl](https://www.mabl.com/pricing) | agentic testing、低代码自愈、API/移动覆盖 | 低代码步骤 | 企业销售洽谈 | 把自愈能力包装成"可交付的审计证据" |
| [testRigor](https://testrigor.com/) | 定位为 AI-based 无代码测试 | 未核实 | 未核实 | — |
| [BrowserStack Test AI](https://www.browserstack.com/test-ai) | 未核实（403） | 未核实 | 未核实 | — |

三个结论：

1. **没人再卖"生成"。** 卖点全部落在维护（自愈 / reviewed repair）与判断（失败归因）；生成已是基线。
2. **测试表示从"录制"迁移到"仓库内可 diff 的文本"**：Momentic 让 YAML 进 repo 以便 coding agent 也能改，KaneAI 每次改动 versioned 可回滚，QA Wolf 干脆产出标准 Playwright/Appium。
3. **席位制已不是主流**：按 run（QA Wolf）或按 credits（Reflect）计价，AI 用量打包，"不限用户"是明示卖点。

## 2. 多智能体编排：长任务工程 Agent 怎么做

| 系统 | 如何分解/派发 | 子任务状态如何暴露 | 结果如何返回与验证 | 工具如何被约束 |
|---|---|---|---|---|
| [Claude Code](https://code.claude.com/docs/en/sub-agents) | 自定义 subagents、agent teams、dynamic workflows 后台并行 | agent view、cross-session messaging | 各 subagent 自报，主 agent 汇总 | worktree 隔离；[skills](https://code.claude.com/docs/en/skills) 按需加载 |
| [Cursor Cloud Agents](https://cursor.com/docs/cloud-agent) | 一 agent 一隔离 VM；可从 Slack/Linear/API 触发；subagents | 团队共享 run URL、Builds、环境版本历史 | **产物即证据**：截图/视频/日志 + 远程桌面复核 | hooks（`preToolUse`/`beforeShellExecution`/`afterFileEdit`/`subagentStart`）+ 出网域名限制 |
| [Devin](https://devin.ai/pricing) | 云端 agent 会话，并发会话上限随套餐 | Devin Cloud 会话界面 | PR + 会话记录 | 官方未详列（仅取到定价页） |
| [OpenHands](https://docs.openhands.dev/overview/introduction) | Agent Canvas 做控制中心，可连多个 Agent Server | Canvas 中查看会话与 automations | Agent Server 经 REST/WebSocket 暴露执行与工具 | sandbox server 隔离 |
| [SWE-agent](https://swe-agent.com/latest/) | 单实例跑单 issue | trajectory 文件 + inspector 回放 | 提交 patch，靠测试判定 | **一个 yaml 管住工具/模板/解析器** |
| [Aider](https://aider.chat/docs/usage/modes.html) | 不派发，但拆成 architect（出方案）+ editor（出编辑指令）双模型 | 终端流式对话 | 直接落盘 diff，配合 lint/test | 无沙箱，靠 edit format 约束 |

值得抄的模式：

- **隔离 + 产物即证据**。Cursor 把"agent 说它验证过了"变成"看截图/视频/日志"；Diffblue 更进一步：只在临时 git worktree 里跑，验证不过就 rollback，绝不污染主分支。
- **hook 做硬约束，提示词做软约束**。"不许直接 push""跑完必须 format"这类要求，应落在 `preToolUse` 级钩子上，而不是写在提示词里祈祷。
- **双模型分工**。Aider 的 architect/editor 拆分说明：一个模型出方案、另一个只负责翻译成结构化编辑，比让一个模型一次干完更稳——这正是我们"主助手派发 + 专员执行"的微观版本。

## 3. 确定性/质量护栏：严肃团队真正在强制的

1. **结构化契约**：工具入参与产出走 JSON Schema（[Agno](https://docs.agno.com/) 把 Structured Output 做成一等 API），下游只消费 schema，不解析自然语言。
2. **技能化而非提示词化**：[Claude Code skills](https://code.claude.com/docs/en/skills) 是按需加载的指令包，天然适合把各角色作业规范固化成独立 skill（api-authoring / flaky-triage / case-from-prd），并复用 prompt cache 前缀。
3. **计划是对象**：[KaneAI](https://www.testmuai.com/kane-ai/) 的闸门不是"聊天里问一句"，而是把 test plan 渲染成可编辑、可批准的对象——这是 HITL 唯一可审计的形态。
4. **修复必须过 review**：[Momentic](https://momentic.ai/) 的永久自愈产出"待 review 的 test-file 修复"，而不是静默改文件。
5. **重试有上限**：[QA Wolf](https://www.qawolf.com/pricing) 每个 run 最多 3 次尝试清 flake，之后转 investigate——从一开始就关掉"再跑一次"。
6. **退出码是产品接口**：Momentic 的 CLI exit code 可当 CI 必需检查；Kane CLI 用 0/1/2/3 区分 pass / fail / setup error / timeout。**必须能区分"测挂了"与"环境挂了"**。
7. **可追溯链**：requirement → case → script → run 用同一组 ID 贯穿，否则上面六条都答不出"这个用例为什么存在"。

## 4. 开源框架对比与 nanobot 的判断

| 框架 | 派发 | 任务状态 | UI 可观测性 |
|---|---|---|---|
| [nanobot](https://github.com/obot-platform/nanobot) | 由 MCP server 集合定义能力 | 无内建任务状态机 | 无 |
| [OpenHands](https://docs.openhands.dev/overview/introduction) | Agent Canvas + 多后端 | 会话/automation 有 | **自带 Web 控制台，最强** |
| [CrewAI](https://crewai.com/) | 角色制 crew + 确定性 workflow，控制面在每次调用路径上 | 实时 trace、成本核算、HITL 审批闸门 | 有（企业控制面） |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | 图/子图编排 | **checkpointer、interrupts、time travel** 一等公民 | 需接 Studio / Agent Chat UI |
| [AutoGen](https://microsoft.github.io/autogen/stable/) | 多 agent 对话式协作 | 弱 | 弱 |
| [Letta](https://docs.letta.com/) | 有状态 agent、subagents、skills、schedules | 状态与记忆持久化强 | 有 App Server / Desktop |
| [Agno](https://docs.agno.com/) | 任意 SDK 建 agent，AgentOS 做服务化 | 持久执行、多副本、会话检查 | **Control Plane UI** |

**关于 fork nanobot**：`github.com/nanobot-ai/nanobot` 现重定向至 [`obot-platform/nanobot`](https://github.com/obot-platform/nanobot)，自述 "Build MCP Agents"；其背后 [Obot](https://obot.ai/) 定位 "Enterprise AI Control Plane & MCP Gateway"。这意味着 nanobot 的原生抽象就是"agent = 一组 MCP 工具"，与需求 (d)「用 MCP 工具而非自由提示换取确定性」高度同构——这是 fork 最充分的理由。

但 nanobot 不提供任务状态机、角色权限、UI、质量闸门。**所以：把 nanobot 当执行器与工具层，不要当编排层。** 编排（任务 DAG、attempt 归属、闸门）自建，框架层只借它的 MCP 装配与运行时。

## 5. 综合

### 5.1 三大 AI 测试产品范式

| 范式 | 代表 | 原理 | 对我们的代价 |
|---|---|---|---|
| A. 自愈录制器 | Testim、Reflect、Autify、KaneAI | 录制/自然语言步骤 + 智能定位器，UI 变了自动重定位 | 与"统一管理用例与脚本"冲突：资产是平台私有格式，用户被锁定；我们不做浏览器插件，短期吃不到 |
| B. 自然语言授权 | Momentic、KaneAI、Applitools | 自然语言写 YAML/步骤，模型翻译成动作，专用模型保确定性 | 最贴合需求 (c)(d)：文本可进 git、可 diff、可 review。风险是"NL→脚本"这一步质量不稳 |
| C. Agentic 找 bug | QA Wolf、Momentic Mo、Autify Aximo | 给目标不给步骤，agent 自己探索、判定、提 bug | 最像"AI QA"，但**判定不可复现**，没有严格证据链就会变成 flake 工厂 |

**取舍**：v1 以 B 为主干（可 review 的文本资产 + 确定性执行器），C 只做"探索补充"（产出候选用例，人工确认后落到 B），不碰 A。

### 5.2 我们的 v1 应该做 / 不该做

**做**
- 三个专员角色跑通闭环：`api-tester`、`functional-tester`、`automation-author`，各自只能看见自己那组 MCP 工具。
- 用例与脚本统一进项目仓库（YAML + 生成的 Playwright/pytest），PR 可 review、可回滚。
- 一张任务板：主助手拆解 → 专员领取 → 状态与产物可见。**进度粒度到"步骤"而非"任务"**（参照 Cursor 的 artifacts，每步有证据）。
- 每个 run 有结构化结果：`pass | fail | blocked_by_env | flaky`，退出码区分 setup error。
- 一个闸门：脚本入库前需人工批准（参照 KaneAI 的计划审批）。
- 全部工具走 JSON Schema 契约，拒绝自由文本解析。

**不做**
- 不做静默自愈改文件（最多产出"待 review 修复建议"）。
- 不做无步骤的纯目标式找 bug（判定不可复现）。
- 不做浏览器录制器。
- v1 不做跨项目知识库/向量检索，不做多租户计费。

### 5.3 任务 / 角色模型建议

- **角色**：`lead`（接需求、拆 DAG、汇总）、`api-tester`、`functional-tester`、`automation-author`、`reviewer`（只读工具 + 批准权）。
- **交接状态**：`draft → planned → claimed → running → needs_review → approved | rejected → done`；另有 `blocked_by_env` 独立分支——不能让环境问题伪装成测试失败。
- **进度粒度**：任务级（谁在做）+ 步骤级（当前第几步、产物链接）。
- **UI 必须显示的四件事**：任务树与依赖；每个专员当前步骤与证据（截图/日志/请求响应）；待人工批准的闸门；失败分类（产品缺陷 / 用例问题 / 环境问题）。

### 5.4 产品 × 能力矩阵（仅列已核实；来源同第 1 节链接）

| 能力 | QA Wolf | Momentic | KaneAI | Testim | Reflect | Autify | Applitools | Diffblue |
|---|---|---|---|---|---|---|---|---|
| 生成用例 | ✓ | ✓ | ✓ | ✓ | 部分 | ✓(Genesis) | 部分 | — |
| 生成脚本 | ✓(Playwright) | 部分(YAML) | ✓(可导出) | ✓ | 部分 | 部分 | ✓(SDK) | ✓(单测) |
| 执行 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 自愈 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| 失败归因 | ✓ | ✓ | ✓ | ✓ | ✓(日志) | 部分 | ✓ | 部分 |
| 仓库内文本表示 | ✓ | ✓ | 部分 | — | — | — | 部分 | ✓ |
| 人工闸门 | 部分 | ✓(review 修复) | ✓(审计划) | — | — | — | — | ✓(验证后提交) |
| 计价 | 按 run | credits | credits | 未核实 | credits | credits | 未核实 | 企业授权 |

---

**给决策者的三句话**：① 差异化不在"AI 写用例"，而在"用例—脚本—运行—证据"这条链能否被 review 和回滚；② fork nanobot 是对的选择，但必须自己补编排层与任务板，否则做出来的只是一堆不可观测的 agent；③ v1 只押 B 范式，A 与 C 都是后置能力。
