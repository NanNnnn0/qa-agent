# QA Agent 第一版设计

> 目标：在 nanobot fork 之上，做一个"测试工作 agent"：主助理接单 → 拆分 → 派给接口/功能/自动化三个专职助手；
> 一个 Web UI 能看到任务进度，并统一管理各项目的用例与自动化脚本；能力通过 skills + MCP/内置工具固化，
> 避免每次让模型自由发挥导致产物不一致。

本文档是第一版的实现契约。后续迭代以本文档为基线修改。

## 1. 产品形态

```
┌──────────────────────────── WebUI (React) ────────────────────────────┐
│  QA 工作台                                                            │
│  ├── 概览     项目健康度、任务统计、最近运行                          │
│  ├── 任务板   主助理创建的任务 + 子任务进度/事件流                     │
│  ├── 用例库   按项目浏览/编辑/导入导出 接口用例 与 功能用例            │
│  ├── 自动化   脚本列表/编辑器/运行                                    │
│  └── 运行记录 执行结果、失败断言、报告                                 │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTP GET + WebSocket mutation
┌───────────────────────────────▼───────────────────────────────────────┐
│ nanobot gateway (单进程)                                              │
│  ├── WebUI HTTP 路由  /api/qa/*  →  nanobot/qa/http.py                │
│  ├── 对话 agent（主助理 SOUL"测试总调度"）                             │
│  │     └── 工具 qa_project / qa_case / qa_script / qa_run / qa_task    │
│  │           └── qa_task(action=dispatch) → SubagentManager.spawn()    │
│  │                 ├── 角色 api-tester       （接口测试助手）          │
│  │                 ├── 角色 functional-tester（功能测试助手）          │
│  │                 └── 角色 automation-engineer（自动化助手）          │
│  └── nanobot/qa/store.py  SQLite <config>/qa/qa.sqlite3               │
└───────────────────────────────────────────────────────────────────────┘
              ▲ 同一套业务能力也通过 MCP stdio server 暴露
              │ python -m nanobot.qa.mcp_server
```

## 2. 数据模型（SQLite）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `projects` | id, key, name, description, base_url, repo_path, default_env | 一个被测项目。key 用于用例编号前缀，全库唯一 |
| `cases` | id, project_id, code, title, kind, priority, status, preconditions, steps(JSON), api(JSON), expected, tags(JSON), source, author | 用例。`kind=api/ui/manual`；api 用例带结构化请求与断言，可机器执行 |
| `scripts` | id, project_id, name, framework, language, file_path, content, case_ids(JSON), tags(JSON), status | 自动化脚本。framework: pytest/playwright/postman/http |
| `runs` | id, project_id, script_id, case_ids(JSON), status, passed, failed, errors, skipped, duration_ms, started_at, finished_at, report(JSON), log | 一次执行 |
| `tasks` | id, project_id, parent_id, role, title, prompt, status, progress, session_key, subagent_task_id, result, created_at, updated_at | 派单。role: orchestrator/api/ui/automation/review |
| `task_events` | id, task_id, at, kind, message, data(JSON) | 任务事件流（进度、产物、结果） |
| `task_artifacts` | task_id, kind, ref_id, title | 任务产出物 → 用例/脚本/运行 |

状态机：

- task: `queued → running → (done | failed | blocked | cancelled)`
- run: `running → (passed | failed | error)`
- case: `draft → ready → deprecated`

## 3. HTTP API 契约

GET（读，走普通 HTTP + token）：

| 路径 | 返回 |
|---|---|
| `GET /api/qa/overview` | 计数、项目健康度、最近任务/运行 |
| `GET /api/qa/projects` | 项目列表（含用例/脚本/任务计数） |
| `GET /api/qa/projects/{id}` | 单项目 |
| `GET /api/qa/cases?project_id=&kind=&status=&q=&limit=&offset=` | 用例分页 |
| `GET /api/qa/cases/export?project_id=` | JSON 导出（attachment） |
| `GET /api/qa/scripts?project_id=&q=` | 脚本列表（不含 content 全文） |
| `GET /api/qa/scripts/{id}` | 脚本全文 |
| `GET /api/qa/runs?project_id=&limit=` | 运行列表 |
| `GET /api/qa/runs/{id}` | 运行详情（report、断言失败） |
| `GET /api/qa/tasks?project_id=&status=&limit=` | 任务列表 |
| `GET /api/qa/tasks/{id}` | 任务 + 产物 |
| `GET /api/qa/tasks/{id}/events` | 事件流 |

写操作必须在已认证 WebSocket 上以 mutation 方式提交（沿用 nanobot WebUI 的 CSRF 设计）：
WebSocket 消息 `{"type":"webui_request","request_id":...,"action":"qa.case.create","payload":{...}}`。

动作 → HTTP 路径映射（服务端 `_WEBUI_MUTATION_PATHS`）：

| action | path |
|---|---|
| qa.project.create / update / delete | `/api/qa/projects/create` … |
| qa.case.create / update / delete / import | `/api/qa/cases/create` … |
| qa.script.create / update / delete | `/api/qa/scripts/create` … |
| qa.task.create / update / cancel / dispatch | `/api/qa/tasks/create` … |
| qa.run.start | `/api/qa/runs/start` |

统一响应：成功 `{"ok": true, ...payload}`；失败 `{"ok": false, "error": "..."}`（HTTP 4xx/5xx）。

## 4. 用例结构（确定性的关键）

API 用例的 `api` 字段（JSON）是执行契约，模型必须按此输出，runner 不解释自由文本：

```json
{
  "request": {
    "method": "POST",
    "path": "/api/orders",
    "headers": {"Content-Type": "application/json"},
    "query": {"page": "1"},
    "body": {"sku": "A-1", "qty": 2}
  },
  "assertions": [
    {"type": "status", "expect": 200},
    {"type": "json_path", "path": "$.code", "expect": 0},
    {"type": "json_path", "path": "$.data.orderId", "op": "exists"},
    {"type": "header", "name": "content-type", "contains": "application/json"},
    {"type": "response_time_ms", "max": 2000}
  ],
  "variables": {"sku": "A-1"}
}
```

支持断言：`status`、`json_path`（op: equals/exists/contains/gt/lt）、`header`、`response_time_ms`、`body_contains`。
用例建议编号：`<PROJECT_KEY>-<API|UI|MAN>-<三位序号>`，由工具在校验后落库。

功能用例 `steps`：

```json
[{"action": "打开购物车页", "expected": "展示 2 件商品"}, {"action": "点击结算", "expected": "进入订单确认页"}]
```

## 5. Agent 工具（模型侧的确定性契约）

内置工具在 `nanobot/agent/tools/qa.py`，自动被 ToolLoader 发现；同名能力也在 MCP server 中暴露。

| 工具 / action | 作用 |
|---|---|
| `qa_project` list/create/get/update | 项目 |
| `qa_case` list/create/bulk_create/update/delete/import | 用例（bulk_create 上限 50/次，逐条校验） |
| `qa_script` list/get/create/update | 自动化脚本 |
| `qa_run` start/list/get | 执行 API 用例集合或 pytest 脚本，返回结构化结果 |
| `qa_task` list/get/create/update/plan/dispatch/event | 派单与进度 |
| `qa_overview` — | 全局概览（给主助理做决策） |

`qa_task plan` 是主助理的核心动作：一次给出 `tasks: [{role, title, prompt}]`，工具负责
创建父任务+子任务，并按 `dispatch=true` 为每个子任务调用 `SubagentManager.spawn`。
子任务的系统提示由 `nanobot/qa/roles.py` 中的角色模板生成，包含：
角色职责 → 可用工具与调用顺序 → 产物格式（必须落库）→ 收尾必须 `qa_task update`。

## 6. Skills（避免输出漂移）

内置 skills（`nanobot/skills/`，随包分发，Agent 可按需加载）：

| skill | 内容 |
|---|---|
| `qa-orchestrator` | 如何把一段测试需求拆成接口/功能/自动化三类任务，角色边界，验收标准 |
| `qa-api-testing` | OpenAPI/接口文档 → 用例矩阵（等价类/边界/异常/权限）→ 结构化 api 用例 → 执行 → 报告 |
| `qa-functional-testing` | 需求 → 测试点 → 步骤化用例（前置/步骤/预期），优先级规则 |
| `qa-automation` | 用例 → pytest/Playwright 脚本模板，命名与目录规范，禁止硬编码等待 |
| `qa-report` | 执行结果 → 缺陷摘要 + 覆盖率口径 |

## 7. 角色

| role | 职责 | 产物 |
|---|---|---|
| orchestrator（主助理） | 接需求、建项目/拆分任务、派单、汇总 | task 树、汇总报告 |
| api | 接口用例设计与执行 | cases(kind=api)、run、缺陷摘要 |
| functional（ui） | 功能用例设计、UI 脚本 | cases(kind=ui/manual)、scripts(playwright) |
| automation | 用例 → 自动化脚本、修复失败脚本 | scripts、run |
| review | 交叉检查用例覆盖与脚本质量 | review 结论、补充用例 |

## 8. 第一版范围 / 非目标

做：
- 项目 / 用例 / 脚本 / 运行 / 任务五类数据的持久化与 API；
- 内置 HTTP API runner（httpx 同步执行结构化用例，产出 JUnit 风格报告）；
- pytest 脚本执行（子进程 + junitxml 解析）；
- 主助理派单工具 + 三个角色模板 + 5 个 skills；
- MCP stdio server（同一业务层）；
- WebUI QA 工作台（概览/任务板/用例库/自动化/运行）；
- 演示数据 seed 与快速开始文档。

不做（后续迭代）：
- 多租户与权限体系；CI webhook；OpenAPI 自动导入全量生成；Playwright 运行时托管；
- 与 Jira/TestRail 双向同步；缺陷管理；测试计划/里程碑。

## 9. 验收标准（v1）

1. `pytest tests/qa` 全绿（store / api / runner / tools）。
2. `cd webui && npm test -- qa` 与 `npm run build` 通过。
3. 启动 gateway 后：`GET /api/qa/overview` 返回 200；WebUI 出现"QA 工作台"，能新建项目、用例、脚本，能发起运行并看到结果。
4. 对话里说"对 demo 项目做下单接口测试"，主助理能通过 `qa_task plan` 派出子任务，任务板出现 running → done 的状态流转，产物挂到任务上。
5. MCP server 能被 MCP 客户端列出工具并成功调用 `qa_case list`。

## 10. v1.1 增补（已实现）

- **运行一等对象**：`runs` 增加 `name` / `environment` / `trigger`（manual|ci|agent|schedule），`qa_run start` 与 CLI 均可写入；数据库 `user_version=2` 自动迁移。
- **CI 结果接入**：`service.ingest_junit` 解析 JUnit XML → run + report；入口有三：`nanobot qa import-junit`（CI 首选）、`qa_run action=import`（Agent）、工作台「导入 JUnit」（mutation `qa.run.import`）。XML 上限 2 MB，用 defusedxml 解析。
- **评审闸门**：`store.decide_task` + mutation `qa.task.approve|reject` + 工具 `qa_task action=approve|reject`。通过 → `done`，退回 → `failed`，结果追加 `[approved]/[rejected] reviewer: note`，并写 `approved`/`rejected` 事件。
- **测试**：`tests/qa` 83 passed（新增迁移、导入、审批、HTTP/工具动作覆盖）。

