<p align="center">
  <img src="images/nanobot_mark.svg" width="84" height="84" alt="QA Agent logo">
</p>

<h1 align="center">QA Agent</h1>

<p align="center">
  <b>把「测试工作」变成结构化数据：用例、脚本、执行、追溯、派单，一个工作台管完。</b><br>
  基于 <a href="https://github.com/HKUDS/nanobot">nanobot</a> 的测试工作分支 · 界面默认简体中文
</p>

<p align="center">
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="nanobot 0.3.5" src="https://img.shields.io/badge/upstream-nanobot%200.3.5-blueviolet">
</p>

<p align="center">
  <a href="./README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="./docs/images/qa-workbench-overview.jpg"><img src="./docs/images/qa-workbench-overview.jpg" alt="QA 工作台概览：项目、用例、脚本、运行与进行中任务的计数，以及最近任务和最近运行" width="880"></a>
</p>

## 目录

- [这是什么](#这是什么)
- [功能](#功能)
- [截图](#截图)
- [架构](#架构)
- [快速开始](#快速开始)
- [在对话里使用](#在对话里使用)
- [数据模型](#数据模型)
- [命令行](#命令行)
- [集成](#集成)
- [项目结构](#项目结构)
- [文档](#文档)
- [开发与测试](#开发与测试)
- [已知限制](#已知限制)
- [致谢与许可](#致谢与许可)

## 这是什么

QA Agent 不是一个「会聊天的测试机器人」。它保留 nanobot 的运行时（模型接入、会话、工具、技能、MCP、WebUI），在上面补一层测试工作需要的骨架：

- **接单与派活**：主助理把一句话需求拆成任务树，派给接口 / 功能 / 自动化 / 评审四个专职助手；进度、产物、评审结论落在任务板上。
- **产物落库**：用例、脚本、运行记录、测试点、需求来源都有编号、状态和项目归属，不再是散落在对话里的 Markdown。
- **执行可复现**：接口用例带结构化请求与断言，由固定执行器执行；pytest 脚本在子进程里跑。每次运行留下报告、用例快照与失败分类。
- **可追溯**：需求 → 测试点 → 用例 → 脚本是一条可查询的链，能回答「这条失败覆盖哪条需求」「改一条需求会影响哪些用例和脚本」。
- **模型只做判断**：设计用例、判读失败由模型完成；写入、执行、审核走固定工具契约，避免每次输出格式都不一样。

一句话：**模型负责想，平台负责记和跑。**

## 功能

### 一个工作台，九个标签

WebUI 左侧「QA 工作台」，按项目切换：

| 标签 | 你能做什么 |
|---|---|
| 概览 | 项目、用例、脚本、运行、进行中任务的计数；最近任务与最近运行 |
| 任务板 | 按角色分派的任务列表：状态、进度、评审（通过 / 退回） |
| 用例库 | 结构化用例的增删改查、筛选、导入导出；显示来源 / 测试点 / 脚本 / 需复核徽标 |
| 测试点 | 需求与测试点的覆盖关系、待审草稿、还没有链路的用例 |
| 接口资产 | 从 OpenAPI 或路径登记出来的接口目录：方法、路径、摘要、关联用例数、变更状态 |
| 自动化 | pytest / Playwright / Postman / HTTP / Karate 脚本与用例的绑定关系 |
| 定时任务 | cron 定时执行用例集合或脚本，支持时区与「立即执行」 |
| 运行记录 | 每次执行的通过 / 失败 / 错误 / 环境阻塞明细、用例快照、失败分类、JUnit 导入 |
| 追溯 | 覆盖率指标、覆盖缺口、影响面查询、变更与待复核、草稿审核、失败回溯 |

### 主助理拆单，专职助手干活

对话里的主助理不亲自写用例，它先拆单再派活。五个角色的提示词与收尾契约固定写在 `nanobot/qa/roles.py`（`orchestrator` 负责调度，其余四个是派活对象）：

| 角色 | 负责 | 产物 |
|---|---|---|
| `orchestrator` | 接单、拆单、派单、汇总 | 任务树、汇总结论、遗留风险 |
| `api` | 接口用例设计与执行 | 接口用例 + 运行 + 缺陷摘要 |
| `ui` | 功能测试点与步骤化用例 | UI / 手工用例 |
| `automation` | 用例 → pytest / Playwright 脚本 | 脚本 + 运行 |
| `review` | 覆盖度、断言强度、环境误判 | 评审结论 + 补充用例 |

五个内置技能随包分发，防止输出漂移：`qa-orchestrator`（拆单与派单模板）、`qa-api-testing`（接口用例矩阵与 `api` 字段写法）、`qa-functional-testing`（需求 → 测试点 → 步骤）、`qa-automation`（脚本模板与修复纪律）、`qa-report`（失败分类与缺陷摘要）。

### 用例是数据，不是聊天记录

用例库以 **YAML 文件为真源**，SQLite 只是列表和搜索用的派生索引：

- 正式库在 `qa-workbench/projects/<project>/cases/`，新建先落到 `draft/<batch>/cases/`，删除写 `tombstones/`（ID 退休不复用）。
- 用例带 `code`（如 `SHOP-API-001`）、`kind`（api / ui / manual）、`priority`（P0–P3）、`status`（draft / ready / deprecated）。
- API 用例的 `api.request` + `api.assertions` 是公开契约；新增断言类型要同时改校验、执行器、技能和编辑器。
- 列表里的徽标直接告诉你这条用例缺什么：缺来源、缺测试点、待复核、来自草稿区。

### 接口测试是一条固定流水线

接口工作不是「让模型发请求碰运气」，而是：

1. `qa_api_catalog` 登记接口资料（OpenAPI / JSON / YAML，本地文件只在 `NANOBOT_QA_SPEC_ROOTS` 下读取），并给出与上一版的 diff。
2. `qa_api_workflow` 提交候选用例批次 → 校验 → 一次性落库；每次用例写入都记录 revision。
3. `qa_api_run` 先 `preflight` 报出所有会阻塞执行的问题，再 `start`：固定模板、用例快照、超过 200 条自动分批（单次上限 2000 条）、凭据脱敏（bearer / JSON 登录 / `env:NAME` 引用）。
4. 用例之间可以用 `api.extract` + `{{run.<name>}}` 传递变量；登录失败单独分类为 `auth_failed`，清理失败记为 `cleanup_failed`，前置失败标记 `dependency_blocked`。

运行状态：`running` / `passed` / `failed` / `error` / `blocked_by_env` / `cancelled`。**`blocked_by_env` 专门表示环境问题**（连不上、超时），不会被算成产品缺陷。

### 追溯链：失败能回到需求

追溯把「这条失败覆盖哪条需求、改一条需求影响哪些用例、哪些用例是死资产」变成一次查询：

- 数据仍是 YAML 真源：`sources/`（需求、接口、UI、缺陷、标准、观测）、`testpoints/`、`cases/`、`scripts/`、`artifacts/`（证据）、`runs/`（pytest 插件写入的真实运行记录）。
- 四个指标分开报：需求覆盖率、行为覆盖率、自动化率、孤儿率；`trace check` 校验文档与图规则。
- 页面上能查影响面（按来源 / 测试点 / 用例）、看变更与待复核（`记录基线`）、审核草稿（通过 / 退回，支持整批）、从失败运行回溯到需求。
- CI 门禁：`qa trace diff --project <path> --base <git-ref>` 把基线 commit 的项目子树物化到临时目录再对比，退出码 `0` 无回归、`1` 回归、`2` 输入失败。

### 运行、报告与定时

- 运行是一等对象：带 `name`、`environment`、`trigger`（manual / ci / agent / schedule）和逐条断言明细。
- CI 结果三种方式进来：`nanobot qa import-junit`、Agent 工具 `qa_run action=import`、工作台「运行记录 → 导入 JUnit」。
- 定时任务按 cron + 时区触发用例集合或脚本，网关内调度器负责抢占与执行，`run_now` 可立即跑一次。

### 多入口，同一套逻辑

WebUI、对话工具、CLI、MCP server 共用同一个存储与执行实现：在页面上建的项目，在对话里能查到；在 CLI 里跑的执行，页面上能看到报告。

## 截图

<p align="center">
  <img src="./docs/images/qa-workbench-cases.jpg" width="880" alt="用例库：结构化用例，带来源、测试点、优先级与标签">
</p>

<p align="center"><sub>用例库：结构化用例与链路徽标（来源 / 测试点 / 脚本 / 需复核）</sub></p>

<p align="center">
  <img src="./docs/images/qa-workbench-trace.jpg" width="880" alt="追溯：需求覆盖率、行为覆盖率、自动化率、孤儿率，以及覆盖缺口、影响面查询和草稿审核">
</p>

<p align="center"><sub>追溯：四个覆盖率指标、覆盖缺口、影响面查询与草稿审核</sub></p>

<p align="center">
  <img src="./docs/images/qa-workbench-tasks.jpg" width="680" alt="任务板：编排、接口、界面三个角色的任务，带状态、进度与通过 / 退回按钮">
</p>

<p align="center"><sub>任务板：角色、状态、进度与人工评审</sub></p>


## 架构

```text
WebUI「QA 工作台」
  │  读：GET /api/qa/*          写：WS qa.* mutation
  ▼
nanobot/qa/http.py
  ├─ 用例 / 脚本 / 运行 / 任务 / 定时 ──► store.py（SQLite）
  │                                          └─► case_files.py ──► YAML 用例库
  └─ 追溯 ─────────────────────────────► trace_api.py ──► qa_trace
                                                          └─► qa-workbench/projects/

主助理（对话）── qa_* 工具 ──► nanobot/agent/tools/qa.py ──► 同一批服务
      └─ qa_task action=plan ──► SubagentManager ──► 接口 / 功能 / 自动化 / 评审助手
MCP 客户端 ── stdio ──► nanobot/qa/mcp_server.py ──► 同一批工具实现
```

| 关注点 | 代码 |
|---|---|
| QA 持久化（projects / scripts / runs / schedules / tasks / 事件流） | `nanobot/qa/store.py` |
| YAML 用例库适配器（先写文件、再建索引、墓碑、链路徽标） | `nanobot/qa/case_files.py` |
| 用例与 API 契约校验 | `nanobot/qa/validation.py` |
| 结构化接口用例执行器（httpx，自解析断言，不靠模型） | `nanobot/qa/runner.py` |
| 固定流水线执行（预检、快照、分批、脱敏、分类） | `nanobot/qa/execution.py`、`nanobot/qa/service.py` |
| `/api/qa/*` 读接口 + WebSocket 写通道 | `nanobot/qa/http.py` |
| 追溯适配器（读接口 + 3 个审核 mutation） | `nanobot/qa/trace_api.py` |
| 接口资产目录与候选批次 | `nanobot/qa/catalog.py`、`nanobot/qa/api_tools.py` |
| 测试点 / 来源草稿写入 | `nanobot/qa/testpoints.py` |
| 后台调度（定时任务、后台运行） | `nanobot/qa/scheduler.py`、`nanobot/qa/run_queue.py` |
| 角色提示词与收尾契约 | `nanobot/qa/roles.py` |
| 模型侧工具 | `nanobot/agent/tools/qa.py`、`qa_api.py`、`qa_testpoint.py` |
| MCP stdio server | `nanobot/qa/mcp_server.py` |
| 追溯领域库与 CLI | `qa_trace/` |

更细的边界与取舍见 [`docs/design/qa-platform.md`](./docs/design/qa-platform.md)、[`docs/design/qa-trace.md`](./docs/design/qa-trace.md) 和 [`docs/adr/`](./docs/adr/)。

## 快速开始

### 环境要求

- **Python 3.11+**（部署机为 3.12）
- **Node.js 22 + npm**：仅构建 WebUI 时需要（`nanobot/web/dist` 不进 git）
- 一个可用的模型 provider（OpenAI 兼容 API、Anthropic、本地模型等，见 [`docs/providers.md`](./docs/providers.md)）

### 安装（源码）

```bash
git clone git@github.com:NanNnnn0/qa-agent.git    # 私有仓库，需要对应的 SSH key
cd qa-agent

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1

pip install -e ".[dev]"

# 构建 WebUI（只做一次，改了前端再跑）
cd webui && npm install && npm run build && cd ..
```

> `pip install -e` 会跳过前端构建；`.venv/` 和 `nanobot/web/dist/` 都不在 git 里，所以**新克隆不等于可运行**，上面两步缺一不可。

### 五分钟跑通演示

```bash
# 1) 写入演示数据：Demo 商城项目 + 6 条接口用例 + 2 条功能用例 + 1 个 pytest 脚本 + 派单任务
nanobot qa seed

# 2) 终端 A：启动被测的演示商城 API（http://127.0.0.1:8799）
nanobot qa demo-server

# 3) 终端 B：执行接口用例并看报告
nanobot qa run --project SHOP --kind api

# 4) 启动网关，浏览器打开 http://127.0.0.1:8765 → 左侧「QA 工作台」
nanobot gateway
```

配置模型：`nanobot onboard`，或在 WebUI **设置 → 模型** 里填。

不跑演示数据也能用：`nanobot qa status` 看数据库位置，`nanobot qa projects` / `qa cases` / `qa tasks` 看内容。数据库默认在 `<配置目录>/qa/qa.sqlite3`，用 `NANOBOT_QA_DB` 指到别处。

### 追溯链演示

```bash
# 校验演示项目（login-lock：需求 → 测试点 → 用例 → 脚本，脚本断言故意失败）
python -m qa_trace trace check  --project qa-workbench/projects/login-lock
python -m qa_trace trace report --project qa-workbench/projects/login-lock

# 跑一次真实 pytest，运行记录写进项目的 runs/
python -m pytest -p qa_trace.pytest_plugin \
  --qa-project=qa-workbench/projects/login-lock \
  qa-workbench/projects/login-lock/scripts/test_login.py -q

# 失败回溯 / 影响面 / 变更 / 草稿
python -m qa_trace trace failure --project qa-workbench/projects/login-lock --run <run-id>
python -m qa_trace trace impact  --project qa-workbench/projects/login-lock --source REQ-LOGIN-01
python -m qa_trace trace stale   --project qa-workbench/projects/login-lock
python -m qa_trace trace review list --project qa-workbench/projects/login-lock
```

追溯项目根默认是仓库里的 `qa-workbench/projects`，可用 `NANOBOT_QA_TRACE_ROOT` 指向别处（装成 wheel 部署时请显式设置）。

## 在对话里使用

打开一个话题，直接描述测试目标：

> 对 SHOP 项目做下单接口回归：覆盖正常下单、库存不足、参数非法、未知 SKU，执行后给结论。

主助理会：`qa_overview` → `qa_project action=get` → `qa_task action=plan`（给接口 / 功能 / 自动化各派一个角色）→ 后台助手落用例、跑执行、回填结论。你在工作台看到任务从 `queued` → `running` → `needs_review` / `done` 的流转和产物。

需要人工把关时，任务停在 `needs_review`，在任务板点「通过 / 退回」并填备注：通过 → `done`，退回 → `failed`，评审人和结论写进任务结果与事件流。

## 数据模型

| 对象 | 关键字段 |
|---|---|
| project | `key`（用例编号前缀）、`name`、`base_url`、`repo_path` |
| case | `code`、`kind`、`priority`、`status`、`steps`、`api{request,assertions}`、`testpoints`、`sources` |
| script | `framework`、`file_path`、`content`、`case_ids` |
| run | `status`、`trigger`、`environment`、逐条用例断言明细、用例快照 |
| task | `role`、`status`、`progress`、`subagent_task_id`、事件流（created / status / dispatched / artifact / plan） |
| schedule | `cron`、`timezone`、`target`（用例集合或脚本）、`next_run_at`、`last_status` |
| trace | `source`（req / api / ui / bug / std / ex）、`testpoint`、`case`、`script`、`evidence` |

追溯数据目录（YAML 是真源，索引与运行记录是派生）：

```text
qa-workbench/projects/<project>/
├── project.yaml            # 项目元信息与阈值
├── sources/                # REQ-* / API-* / UI-* …（链的根，必须带证据）
├── testpoints/             # TP-*
├── cases/                  # TC-*（挂测试点，或直挂来源并写 direct_reason）
├── draft/<batch>/          # 待审草稿，不参与覆盖率
├── tombstones/             # 删除即墓碑
├── scripts/                # pytest 脚本
├── artifacts/              # 需求副本、截图、抓包
└── runs/<run-id>/manifest.json
```

## 命令行

| 命令 | 作用 |
|---|---|
| `nanobot qa status` | 数据库路径与计数 |
| `nanobot qa seed` | 写入演示项目、用例、脚本、派单任务 |
| `nanobot qa demo-server` | 启动演示商城 API（含库存不足 / 参数错误分支） |
| `nanobot qa projects` / `cases` / `tasks` | 查看项目 / 用例 / 任务 |
| `nanobot qa run --project SHOP --kind api` | 执行用例集合（也可 `--case`、`--script`） |
| `nanobot qa import-junit --project SHOP --file report.xml` | 导入 CI 的 JUnit 报告为一次运行 |
| `nanobot qa reindex [--project SHOP]` | 用 YAML 重建 SQLite 派生索引 |
| `nanobot qa mcp` | 以 stdio 启动 MCP server |

追溯与迁移（`qa_trace` 包）：

| 命令 | 作用 |
|---|---|
| `python -m qa_trace trace check` | 校验项目库的文档与图规则 |
| `python -m qa_trace trace report` | 覆盖率、缺口、死资产 |
| `python -m qa_trace trace diff --base <git-ref>` | 与基线对比，做 CI 门禁 |
| `python -m qa_trace trace impact` | 影响面：来源 / 测试点 / 用例之下的所有资产 |
| `python -m qa_trace trace stale` | 内容与依赖哈希对比，列出待复核 |
| `python -m qa_trace trace failure --run <id>` | 失败回溯到链上 |
| `python -m qa_trace trace draft new/add` | 写草稿（Agent 面向） |
| `python -m qa_trace trace review list/approve/reject` | 审核草稿 |
| `python -m qa_trace trace migrate-sqlite` | 把旧 SQLite 用例导出成 YAML 草稿（只读、可重复） |

## 集成

### MCP

外部 MCP 客户端可以复用同一套工具和同一个数据库：

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

### HTTP / WebSocket

- 读：`GET /api/qa/{health,overview,projects,cases,testpoints,api-operations,scripts,runs,schedules,tasks}`，需要 Bearer token；追溯在 `/api/qa/trace/*`（summary / tree / impact / stale / drafts / failure / runs）。
- 写：必须走已认证 WebSocket 的 `webui_request`（`qa.project.create` 等 25 个 action，含 3 个追溯审核动作）；普通 HTTP 写请求返回 405，沿用 nanobot WebUI 的 CSRF 设计。
- 契约细节：[`docs/design/qa-platform.md`](./docs/design/qa-platform.md)、[`docs/design/qa-trace.md`](./docs/design/qa-trace.md)。

### CI

把 JUnit 结果推给平台：

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

追溯门禁（`.github/workflows/qa-trace.yml`）：

```bash
python -m qa_trace trace diff --project qa-workbench/projects/login-lock --base origin/main
# 0 无回归 / 1 回归 / 2 输入失败；容差用 --coverage-tolerance 或 project.yaml 的 thresholds
```

## 项目结构

```text
nanobot/qa/                 QA 领域层：存储、校验、执行、HTTP/WS、角色、调度、MCP
nanobot/agent/tools/        模型侧工具（qa.py / qa_api.py / qa_testpoint.py）
nanobot/skills/qa-*         五个 QA 技能
webui/src/components/qa/    QA 工作台（九个标签）
qa_trace/                   追溯领域库与 python -m qa_trace CLI
qa-workbench/projects/      追溯与用例数据（YAML 真源，含 login-lock / shop 演示）
tests/qa/  tests/qa_trace/  Python 测试
webui/src/tests/qa-*.test.tsx  WebUI 测试
docs/                       产品文档、设计、ADR、部署与状态
```

## 文档

| 想看什么 | 读这个 |
|---|---|
| 产品说明、快速开始、已知限制 | [`docs/qa-agent.md`](./docs/qa-agent.md) |
| 平台设计契约（数据模型、API、状态机） | [`docs/design/qa-platform.md`](./docs/design/qa-platform.md) |
| 追溯链设计（规则码、退出码、JSON 形状） | [`docs/design/qa-trace.md`](./docs/design/qa-trace.md) |
| WebUI 集成说明 | [`docs/design/qa-webui-brief.md`](./docs/design/qa-webui-brief.md) |
| 竞品与工具调研 | [`docs/research/`](./docs/research/) |
| 架构决策记录 | [`docs/adr/`](./docs/adr/) |
| 部署、回滚、主机事实 | [`docs/deploy.md`](./docs/deploy.md) |
| 当前验证状态与已知缺口 | [`docs/STATUS.md`](./docs/STATUS.md) |
| 路线图与里程碑 | [`docs/ROADMAP.md`](./docs/ROADMAP.md) |
| 多人多会话协作规则 | [`docs/COLLABORATION.md`](./docs/COLLABORATION.md) |
| nanobot 上游能力（模型、渠道、记忆、WebUI、部署） | [`docs/README.md`](./docs/README.md) |

## 开发与测试

```bash
# Python
python -m pytest tests/qa -q
python -m pytest tests/qa_trace tests/qa -q
python -m ruff check nanobot/qa qa_trace

# WebUI
cd webui && npm test           # 全量
cd webui && npx vitest run qa- # 只跑 QA 工作台

# 追溯
python -m qa_trace trace check --project qa-workbench/projects/login-lock
```

CI 是 `.github/workflows/fork-gate.yml`：`ruff check nanobot/qa` + `pytest tests/qa` + WebUI 测试，文档类改动不触发。上游的 `ci.yml`（Docker / TUI / 全量 WebUI）在本分支手动禁用，需要时再开。

改 QA 层之前先读 [`AGENTS.md`](./AGENTS.md)：`case.api` 契约是公开 API，写操作必须走 WebSocket mutation，环境失败不能算缺陷，角色提示词只能写在 `roles.py`。提交前还可以装本地钩子：`git config core.hooksPath scripts/hooks`。

## 已知限制

- **执行**：内置只有 pytest 执行；Playwright 脚本可以管理和生成，但执行依赖外部浏览器环境。
- **CI**：目前是 JUnit XML 导入，没有 webhook 与结果回写 CI。
- **索引**：用例列表读 SQLite 派生索引，手工改 YAML 或 `git pull` 之后要跑 `nanobot qa reindex`；每次写都重建该项目派生行，万级用例需要增量方案。
- **编号**：用例 ID 按「项目内最大号 + 1」分配，并发写同一项目可能撞号（会失败，不会静默覆盖）。
- **旧数据**：未迁移的旧 SQLite 用例只读，需要 `qa trace migrate-sqlite`；迁移不自动造需求与测试点。
- **流程**：有单级评审（通过 / 退回 + 事件流），没有多级审批流；运行记录还没有可克隆的测试周期与动态套件。

更完整的清单见 [`docs/qa-agent.md`](./docs/qa-agent.md) 与 [`docs/STATUS.md`](./docs/STATUS.md)。

## 致谢与许可

本项目是 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的分支，沿用其 MIT 许可与第三方声明（[`LICENSE`](./LICENSE)、[`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)）。上游的模型接入、会话、记忆、渠道、WebUI 与部署能力没有改动，相关文档见 [`docs/`](./docs/README.md)。

贡献流程见 [`CONTRIBUTING.md`](./CONTRIBUTING.md)；本分支的协作与合并规则见 [`docs/COLLABORATION.md`](./docs/COLLABORATION.md)。
