# QA Agent（测试工作 Agent）

QA Agent 是 nanobot 的一个 fork：保留 nanobot 的模型接入、会话、工具、技能、MCP 与 WebUI 运行时，在它之上补齐"测试工作"这一层——一个主助理接单、拆分、把接口/功能/自动化任务派给专职助手，并用一个工作台统一管理各项目的用例、自动化脚本、执行记录与任务进度。

## 为什么需要它

普通聊天 agent 做测试的通病是：产物散落在对话里、每次格式不同、不知道上次跑到哪、用例和脚本没有统一归属。QA Agent 把"测试工作"变成结构化数据：任务有状态与事件流，用例有编号与结构化请求/断言，脚本与用例弱耦合，执行有可复现报告。模型只负责设计与判断，落库与执行走固定工具契约，避免输出漂移。

## 快速开始（Windows / PowerShell）

> 界面语言：本分支默认 **简体中文**（首次打开即为中文）。需要英文或其他语言时，用界面里的语言切换器，选择会被记住（`nanobot.locale`）。

```powershell
cd F:\xiangmu\qa-agent
E:\anaconda\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 1) 写入演示数据（Demo 商城：6 条接口用例 + 2 条功能用例 + 1 个 pytest 脚本 + 派单任务）
.\.venv\Scripts\nanobot.exe qa seed

# 2) 启动演示被测服务（另开一个终端；地址 http://127.0.0.1:8799）
.\.venv\Scripts\nanobot.exe qa demo-server

# 3) 执行接口用例，看报告
.\.venv\Scripts\nanobot.exe qa run --project SHOP --kind api

# 4) 启动网关 + WebUI，浏览器打开 http://127.0.0.1:8765 → 左侧「QA 工作台」
.\.venv\Scripts\nanobot.exe gateway
```

不跑演示数据也可以用：`nanobot qa status` 查看数据库位置，`nanobot qa projects` / `qa cases` / `qa tasks` 查看内容。数据库默认在 `<配置目录>/qa/qa.sqlite3`（如 `~/.nanobot/qa/qa.sqlite3`），可用环境变量 `NANOBOT_QA_DB` 指向任意路径。

模型 provider 通过 nanobot 原有方式配置（`nanobot onboard` 或 `~/.nanobot/config.json`），详见 [`docs/quick-start.md`](./quick-start.md) 与 [`docs/providers.md`](./providers.md)。

## 架构

```text
WebUI「QA 工作台」 ──GET /api/qa/*──┐
        │                           ▼
        └─WebSocket mutation──► nanobot/qa/http.py ──► nanobot/qa/store.py (SQLite)
                                          ▲
对话主助理 ──qa_* tools──► nanobot/agent/tools/qa.py ─┘
        │                            │
        └─ qa_task action=plan ──► SubagentManager ──► 接口 / 功能 / 自动化 / 评审 助手
                                                       （各自带角色提示与工具契约）
MCP 客户端 ──stdio──► nanobot/qa/mcp_server.py ────────┘（与内置工具同一套业务逻辑）
```

关键文件：

| 文件 | 作用 |
|---|---|
| `nanobot/qa/store.py` | SQLite 持久化：projects / cases / scripts / runs / tasks / task_events / task_artifacts |
| `nanobot/qa/validation.py` | 用例与 API 契约校验（模型必须按此输出） |
| `nanobot/qa/runner.py` | 结构化接口用例执行器（httpx，自己解析断言，不靠模型） |
| `nanobot/qa/service.py` | 执行编排：接口用例集合 / pytest 脚本子进程，产出 run 与报告 |
| `nanobot/qa/http.py` | `/api/qa/*` 读接口 + WebSocket mutation 写接口 |
| `nanobot/qa/roles.py` | 四个专职角色的提示词与收尾契约 |
| `nanobot/agent/tools/qa.py` | 模型侧工具：qa_project / qa_case / qa_script / qa_run / qa_task / qa_overview |
| `nanobot/qa/mcp_server.py` | MCP stdio server，复用同一批工具 |
| `nanobot/skills/qa-*` | 五个 skill：调度、接口、功能、自动化、报告 |
| `webui/src/components/qa/` | QA 工作台页面 |

## 数据模型与状态机

- **project**：`key`（用例编号前缀，如 SHOP）+ `name` + `base_url`（接口执行用）+ `repo_path`（脚本定位用）。
- **case**：`kind∈api|ui|manual`，`priority∈P0..P3`，`status∈draft|ready|deprecated`；api 用例带结构化 `api.request` 与 `api.assertions`，ui/manual 用例带 `steps[{action,expected}]`。编号自动生成 `KEY-API-001`。
- **script**：`framework∈pytest|playwright|postman|http|karate`，`file_path` + `content` + `case_ids`（用例↔脚本可追溯）。
- **run**：`status∈running|passed|failed|error|blocked_by_env|cancelled`，报告含每条用例的断言明细。`blocked_by_env` 专门表示"全部用例连不上/超时"，避免环境问题被算成产品缺陷。
- **task**：`role∈orchestrator|api|ui|automation|review`，`status∈queued|running|needs_review|blocked|done|failed|cancelled`，`progress` 0-100，`subagent_task_id` 关联后台助手；事件流记录 created/status/dispatched/artifact/plan 等。

## 在对话里怎么用

主助理被要求先拆单，再派活。一句典型输入：

> 对 SHOP 项目做下单接口回归：覆盖正常下单、库存不足、参数非法、未知 SKU，执行后给结论。

主助理会：`qa_overview` → `qa_project action=get` → `qa_task action=plan`（tasks 里给接口/功能/自动化各一个角色）→ 后台助手落用例、跑执行、回填结论。用户在工作台的任务板看到 queued → running → needs_review/done 的流转与产物。

角色边界：

| role | 负责 | 产物 |
|---|---|---|
| orchestrator | 接单、拆单、派单、汇总 | 任务树、汇总结论 |
| api | 接口用例设计与执行 | cases(kind=api) + run + 缺陷摘要 |
| ui | 功能测试点与步骤化用例 | cases(kind=ui/manual) |
| automation | 用例 → pytest/Playwright 脚本 | scripts + run |
| review | 覆盖度、断言强度、环境误判 | pass/needs_revision + 补充用例 |

## Skills（防止输出漂移）

内置技能随包分发，模型按需加载：

- `qa-orchestrator`：拆单规则、派单模板、收尾口径。
- `qa-api-testing`：接口用例矩阵（正常/必填/类型/边界/业务异常/权限/幂等）与 `api` 字段写法。
- `qa-functional-testing`：需求 → 测试点清单 → 步骤化用例。
- `qa-automation`：pytest/Playwright 模板、命名规范、只允许修定位器与等待条件的修复纪律。
- `qa-report`：失败分类（产品缺陷 / 用例问题 / 环境问题 / 待确认）与缺陷摘要模板。

## MCP 接入

外部 MCP 客户端可以复用同一套工具与同一个数据库：

```json
{
  "tools": {
    "mcpServers": {
      "qa": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "nanobot.qa.mcp_server"],
        "env": {"NANOBOT_QA_DB": "~/.nanobot/qa/qa.sqlite3"},
        "tool_timeout": 120
      }
    }
  }
}
```

启动方式：`nanobot qa mcp`（等价于 `python -m nanobot.qa.mcp_server`）。已验证 initialize / tools/list / tools/call（`qa_case`、`qa_overview`）。

## HTTP / WebSocket 契约

读：`GET /api/qa/{overview,projects,cases,scripts,runs,tasks,health}`，Bearer token。
写：必须走已认证 WebSocket 的 `webui_request`（`qa.project.create` 等 15 个 action），普通 HTTP 写请求返回 405——沿用 nanobot WebUI 的 CSRF 设计。完整契约见 [`docs/design/qa-platform.md`](./design/qa-platform.md)。

## 评审与 CI 接入

- **评审闸门**：子任务可以停在 `needs_review`。工作台里点「通过 / 退回」并填备注，会调用 `qa.task.approve` / `qa.task.reject`：通过 → `done`，退回 → `failed`，两者都会把 `[approved]` / `[rejected]` 和评审人写进任务结果，并留下 `approved` / `rejected` 事件（审计轨迹）。Agent 侧对应 `qa_task action=approve|reject`。
- **CI 结果接入**：运行是"一等对象"，带 `name` / `environment` / `trigger`（manual / ci / agent / schedule）。CI 把 JUnit XML 交给平台有三种方式：
  - CLI：`nanobot qa import-junit --project SHOP --file report.xml --name "pipeline #42" --environment staging`；
  - Agent：`qa_run action=import xml="<testsuite>..."`（用户把 CI 报告粘进对话时）；
  - 工作台：「运行记录 → 导入 JUnit」粘贴 XML。
  导入会解析每条 `testcase`，失败信息进报告，状态按失败数自动判定。

## CLI

```text
nanobot qa status                 # 数据库路径 + 计数
nanobot qa seed [--base-url URL]  # 演示项目、用例、脚本、任务
nanobot qa demo-server            # 演示商城 API（含库存不足/参数错误等分支）
nanobot qa mcp                    # MCP stdio server
nanobot qa projects | cases | tasks
nanobot qa run --project SHOP --kind api [--name 冒烟] [--environment staging]
nanobot qa run --project SHOP --case case_xxx
nanobot qa run --project SHOP --script scr_xxx
nanobot qa import-junit --project SHOP --file report.xml [--name ...] [--environment ...]
```

## CI 接入示例（GitHub Actions）

```yaml
- name: Run API tests
  run: pytest tests/ -q --junitxml=report.xml
- name: Publish result to QA Agent
  if: always()
  run: |
    python -m pip install -e .
    nanobot qa import-junit --project SHOP --file report.xml \
      --name "pipeline #${{ github.run_number }}" --environment ci
```

前提：runner 能访问 QA Agent 的数据库（自托管 runner 与网关同机，或把 `NANOBOT_QA_DB` 指向共享路径）。远程场景可以用 SSH 执行同一条命令。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/qa -q      # 83 passed
.\.venv\Scripts\ruff.exe check nanobot/qa nanobot/agent/tools/qa.py nanobot/cli/qa.py tests/qa
cd webui; npm test -- qa; npm run build
```

真实浏览器验证（Chrome headless，网关 + 构建产物）：

```powershell
cd webui; npm run build
.\.venv\Scripts\nanobot.exe gateway --foreground --port 8777
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
  --virtual-time-budget=15000 --dump-dom "http://127.0.0.1:8765/#/qa"
```

渲染结果见 [`docs/images/qa-workbench.png`](./images/qa-workbench.png)：概览卡片、项目表、最近任务（Queued / Needs review / Done / Running）与运行记录都来自 `/api/qa/*` 实时数据。

## 已知限制（第一版）

- 运行记录支持 `name` / `environment` / `trigger`，但还没有可克隆的测试周期（planned → in_progress → completed）与套件（动态查询）。
- CI 接入目前是 JUnit XML 导入（CLI / Agent 工具 / 工作台），尚未提供 webhook 与结果回写 CI。
- Playwright 脚本可以管理与生成，但执行仍依赖外部浏览器环境；本版只内置 pytest 执行。
- 用例套件是静态筛选（项目 + kind + 查询），尚未支持"活查询"式的动态套件。
- 任务进度由工具回填 + 子任务状态对账；审批记录已持久化（事件流），但没有多级审批流。
- 导入导出只支持 QA Agent 自己的 JSON 格式（后续补 TestRail/Qase 兼容与 OpenAPI 生成）。

详细路线与取舍（含竞品与工具调研）见 [`docs/design/qa-platform.md`](./design/qa-platform.md)、[`docs/research/`](./research/)。

