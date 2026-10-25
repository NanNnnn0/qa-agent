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

# 5) 追溯链演示（用例追溯，见下文「追溯链」一节；数据在 qa-workbench/projects/）
.\.venv\Scripts\python.exe -m qa_trace trace check --project qa-workbench/projects/login-lock
.\.venv\Scripts\python.exe -m pytest -p qa_trace.pytest_plugin `
  --qa-project=qa-workbench/projects/login-lock `
  qa-workbench/projects/login-lock/scripts/test_login.py -q

# 6) 用例源迁移：把第 1 步 seed 出来的 SQLite 用例导出成 YAML（只读数据库，可重复）
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite --project SHOP --root qa-workbench/projects
.\.venv\Scripts\nanobot.exe qa reindex --project SHOP --root qa-workbench/projects
```

不跑演示数据也可以用：`nanobot qa status` 查看数据库位置，`nanobot qa projects` / `qa cases` / `qa tasks` 查看内容。数据库默认在 `<配置目录>/qa/qa.sqlite3`（如 `~/.nanobot/qa/qa.sqlite3`），可用环境变量 `NANOBOT_QA_DB` 指向任意路径。

模型 provider 通过 nanobot 原有方式配置（`nanobot onboard` 或 `~/.nanobot/config.json`），详见 [`docs/quick-start.md`](./quick-start.md) 与 [`docs/providers.md`](./providers.md)。

## 架构

```text
WebUI「QA 工作台」 ──GET /api/qa/*──┐
        │                           ▼
        └─WebSocket mutation──► nanobot/qa/http.py ──┬─ cases* ──► nanobot/qa/case_files.py ─┐
                                                     └─ store.py (SQLite：projects/scripts/runs/tasks)
                                                          ▲ 派生索引（cases 表）             │
                                                          │                                  ▼
                                          /api/qa/trace/*──► nanobot/qa/trace_api.py ──► qa_trace（领域库）
                                                     ▲                                   │
对话主助理 ──qa_* tools──► nanobot/agent/tools/qa.py ─┘                                   └─qa-workbench/projects/<id>/（YAML 真源）
        │                            │
        └─ qa_task action=plan ──► SubagentManager ──► 接口 / 功能 / 自动化 / 评审 助手
                                                       （各自带角色提示与工具契约）
MCP 客户端 ──stdio──► nanobot/qa/mcp_server.py ────────┘（与内置工具同一套业务逻辑）
```

关键文件：

| 文件 | 作用 |
|---|---|
| `nanobot/qa/store.py` | SQLite 持久化：projects / scripts / runs / tasks / task_events / task_artifacts；`cases` 表是 YAML 用例库的派生索引（v3：`derived/legacy_id/yaml_path`） |
| `nanobot/qa/case_files.py` | 用例库适配器：YAML 先写、SQLite 后索引；草稿/正式库/墓碑、链路徽标、`legacy` 旧行只读 |
| `nanobot/qa/validation.py` | 用例与 API 契约校验（模型必须按此输出） |
| `nanobot/qa/runner.py` | 结构化接口用例执行器（httpx，自己解析断言，不靠模型） |
| `nanobot/qa/service.py` | 执行编排：接口用例集合 / pytest 脚本子进程，产出 run 与报告 |
| `nanobot/qa/http.py` | `/api/qa/*` 读接口 + WebSocket mutation 写接口（`/api/qa/cases*` 与 `/api/qa/trace/*`） |
| `nanobot/qa/trace_api.py` | 追溯适配器：项目根解析 + 7 个读接口 + 3 个审核 mutation，全部转调 `qa_trace` |
| `nanobot/qa/roles.py` | 四个专职角色的提示词与收尾契约 |
| `nanobot/agent/tools/qa.py` | 模型侧工具：qa_project / qa_case / qa_script / qa_run / qa_task / qa_overview |
| `nanobot/qa/mcp_server.py` | MCP stdio server，复用同一批工具 |
| `nanobot/skills/qa-*` | 五个 skill：调度、接口、功能、自动化、报告 |
| `webui/src/components/qa/` | QA 工作台页面（`QaTrace.tsx` = 「追溯」标签，`QaCaseLibrary.tsx` = 「用例库」） |
| `qa-workbench/projects/` | 追溯/用例数据目录：`login-lock` 与 `shop`（SQLite 迁移产物）两个演示项目 |
| `qa_trace/` | 追溯领域库与 `python -m qa_trace` CLI（P0–P6） |

## 数据模型与状态机

- **project**：`key`（用例编号前缀，如 SHOP）+ `name` + `base_url`（接口执行用）+ `repo_path`（脚本定位用）。
- **case**：YAML 文件是真源（`qa-workbench/projects/<key-lower>/`），字段仍是
  `kind∈api|ui|manual`（对应 trace 的 `type`，`manual↔functional`）、`priority∈P0..P3`、
  `status∈draft|reviewed|deprecated`（API 里仍叫 `draft|ready|deprecated`），api 用例带结构化
  `api.request` / `api.assertions`，ui/manual 用例带 `steps[{action,expected}]`；编号自动生成
  `KEY-API-001`（`code`），追溯 ID 是 `TC-<MODULE>-<seq>`。文件位置决定复核状态：
  `cases/` = 正式库、`draft/<batch>/cases/` = 草稿、`tombstones/<ID>.yaml` = 已归档（删除即墓碑，
  默认列表不显示，ID 不复用）。SQLite 的 `cases` 表是它重建出来的索引，旧行（未迁移）只读。
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
写：必须走已认证 WebSocket 的 `webui_request`（`qa.project.create` 等 21 个 action，含 3 个追溯审核动作），普通 HTTP 写请求返回 405——沿用 nanobot WebUI 的 CSRF 设计。完整契约见 [`docs/design/qa-platform.md`](./design/qa-platform.md)。

`/api/qa/cases*` 的读写都落在 YAML 用例库（`nanobot/qa/case_files.py`）：响应形状保持
`id/code/title/kind/priority/status/steps/api/tags/project_id`，额外带
`type/trace_status/testpoints/sources/script/needs_recheck/draft/batch/yaml_path/legacy_id/
legacy/needs_links`；写字段额外接受 `testpoints/sources/direct_reason/risk/note/batch`，
删除携带可选 `reason`。语义与页面一致：新建=草稿、`status=ready`=标记已评审、删除=归档。

追溯链（P4）在同一前缀下，鉴权与写通道完全复用：

```text
GET /api/qa/trace/projects                    项目列表（根目录下每个带 project.yaml 的目录）
GET /api/qa/trace/summary?project=<id>        四个指标 + counts + stale/drafts/runs 摘要
GET /api/qa/trace/tree?project=<id>           Source → TestPoint → Case → Script 链
GET /api/qa/trace/impact?project=&source=|case=|testpoint=
GET /api/qa/trace/stale?project=<id>          变更实体 + 待复核
GET /api/qa/trace/drafts?project=&batch=      草稿批次
GET /api/qa/trace/failure?project=&run=&case= 失败回溯
GET /api/qa/trace/runs?project=<id>           运行记录清单

mutation qa.trace.stale_write      → /api/qa/trace/stale/write      记录基线（不审核）
mutation qa.trace.review_approve   → /api/qa/trace/review/approve   晋级草稿 / 重新复核
mutation qa.trace.review_reject    → /api/qa/trace/review/reject    退回草稿（留在 draft/）
```

错误沿用 QA API 契约：404（未知项目/实体/运行）、409（草稿冲突/审核被拒）、400（参数或
项目不可用）；`summary` 对结构错误返回 `valid:false` + `metrics_suppressed` 而不是 4xx。

## 追溯链（qa-trace，P4 已接入，P5 接入 CI）

追溯链让「这条失败覆盖哪条需求、改一条需求影响哪些用例和脚本、哪些用例是死资产」变成
一次查询。领域逻辑在独立的 `qa_trace` 包里（`python -m qa_trace trace …`），工作台只是它
的一个入口，不另建页面也不做外部同步。

- **数据**：`qa-workbench/projects/<project-id>/`（`sources/`、`testpoints/`、`cases/`、
  `draft/<batch>/`、`scripts/`、`artifacts/`、`runs/`）。YAML 是真源，
  `.qa-trace/index.json`（baseline/reviews）与 `runs/` 是派生/历史。项目根默认
  `<repo>/qa-workbench/projects`，可用 `NANOBOT_QA_TRACE_ROOT` 指到别处（安装成 wheel
  部署时请显式设置，默认根指向 site-packages 下的同名字目录）。
- **工作台入口**：WebUI →「QA 工作台」→「追溯」标签。页面上：四个指标卡（需求 / 行为 /
  自动化 / 孤儿，分开显示，不合并）、链树（来源→测试点→用例→脚本，带 draft/reviewed、
  stale、needs_recheck 徽标）、影响面查询、变更/待复核 +「记录基线」、草稿「通过 / 退回」、
  失败回溯（run → case → testpoint → source）。点链上的来源/用例 ID 会直接查影响面。
- **演示项目**：`qa-workbench/projects/login-lock/` —— REQ-LOGIN-01 + UI-LOGIN-02 →
  TP-LOGIN-005 → TC-LOGIN-003 → `scripts/test_login.py`，脚本断言故意失败（产品第 5 次
  失败仍返回 401，需求要求 423），失败记录由 P2 pytest 插件真实写入 `runs/`。
- **命令**（与页面调用同一套领域逻辑）：

  ```powershell
  .\.venv\Scripts\python.exe -m qa_trace trace check  --project qa-workbench/projects/login-lock
  .\.venv\Scripts\python.exe -m qa_trace trace report --project qa-workbench/projects/login-lock
  .\.venv\Scripts\python.exe -m qa_trace trace impact --project qa-workbench/projects/login-lock --source REQ-LOGIN-01
  .\.venv\Scripts\python.exe -m qa_trace trace stale  --project qa-workbench/projects/login-lock
  .\.venv\Scripts\python.exe -m qa_trace trace review list    --project qa-workbench/projects/login-lock
  .\.venv\Scripts\python.exe -m qa_trace trace review approve --project qa-workbench/projects/login-lock --id TC-LOGIN-004 --reviewer qa.li
  .\.venv\Scripts\python.exe -m qa_trace trace failure --project qa-workbench/projects/login-lock --run <run-id>
  .\.venv\Scripts\python.exe -m qa_trace trace diff    --project qa-workbench/projects/login-lock --base origin/main
  ```

  产生新的运行记录（manifest 写进项目的 `runs/<run-id>/`）：

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -p qa_trace.pytest_plugin `
    --qa-project=qa-workbench/projects/login-lock `
    qa-workbench/projects/login-lock/scripts/test_login.py -q
  ```

- **CI 门禁（P5）**：`qa trace diff --project <path> --base <git-ref>` 把基线 commit 的
  项目子树用 `git archive` 物化到临时目录（不动工作区），两侧跑同一套校验再对比：
  新增/已消除诊断、四个指标（需求/行为/自动化/孤儿，需求与行为另给 current_valid）、
  悬空引用、孤儿用例、需求缺口与 `needs_recheck`。退出码：0 无回归、1 回归（新增
  error、覆盖率下降超过容差、新增悬空/孤儿）、2 输入失败（不是 git 仓库、ref 未知、
  项目在该 commit 不存在）。容差默认 0，可用 `--coverage-tolerance`（百分点）或
  `project.yaml` 的 `thresholds.diff_coverage_tolerance` 放宽。
  `.github/workflows/qa-trace.yml` 在 PR 上跑 `--base origin/${{ github.base_ref }}`
  并上传报告与 diff 两个 artifact；`.pre-commit-config.yaml` 用本地 hook 在提交前跑
  demo 项目的快检。两份配置都自包含（不引用远端仓库），CLI 一律显式传 `--project`，
  `NANOBOT_QA_TRACE_ROOT` 只影响工作台适配器。

设计与边界（规则码、退出码、JSON 形状、限制）见
[`docs/design/qa-trace.md`](./design/qa-trace.md)。

## 用例库（YAML 是真源，SQLite 是索引）

「QA 工作台 → 用例库」标签与 `qa_case` 工具、`/api/qa/cases*` 现在写的是同一批 YAML 文件：

- **新建**：`draft/<batch>/cases/TC-<KEY>-<seq>.yaml`（`status: draft`）。API 用例没有步骤时，
  从 `api.request` + 断言派生一条步骤（追溯模型要求用例至少一步）。
- **标记为已评审**：`update status=ready`。用例有测试点或来源时，文件移动到 `cases/` 并在
  `.qa-trace/index.json` 记一条 review；**没有链路时仍是草稿**（响应里 `needs_links: true`），
  因为正式库拒收无链路用例（规则 5）。页面上的「标记为已评审」按钮会明确告知这一点。
- **编辑**：标题/类型/优先级/状态/前置条件/预期/步骤/API 定义/标签，外加「追溯链路」区的
  测试点、来源、直挂理由、风险；保存即写 YAML。
- **归档（删除）**：写 `tombstones/<ID>.yaml`（`status: deprecated` + `tombstone` 块），
  默认列表不再出现，ID 退休不复用；`?status=deprecated` 仍可查。
- **链路徽标**：列表里每条用例显示 来源 / 测试点 / 脚本 / 需复核 / 草稿区，缺链路时显示
  缺来源/缺测试点——迁移出来的旧用例一开始就是这个状态。
- **索引**：列表/过滤/搜索走 SQLite 摘要索引（快），详情按需读取 YAML。单条写入只刷新
  对应行；手工改 YAML 或 `git pull` 之后跑 `nanobot qa reindex`。新检出/刚迁移且一条索引
  行都没有时，读路径会自愈重建一次。
- **旧 SQLite 行**：还没迁移的行仍可查看（`legacy: true`），但更新/删除会 409 并提示先迁移。

迁移命令（只读数据库，可重复执行，重跑按 `legacy_id` 跳过）：

```powershell
# SQLite 用例 → YAML 草稿（--db 省略时读 NANOBOT_QA_DB）
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite `
  --project SHOP --root qa-workbench/projects
# 1 project(s), 8 case(s): 8 draft, 0 formal, 0 tombstone, 0 already migrated

# YAML → SQLite 派生索引（迁移后、手工改文件后）
.\.venv\Scripts\nanobot.exe qa reindex --project SHOP --root qa-workbench/projects
```

SHOP 演示库已经迁移并提交在 `qa-workbench/projects/shop/`（8 条用例，`code` 保留为
`SHOP-API-001..006` / `SHOP-UI-001..002`，`legacy_id` 指回迁移那台机器上的 SQLite 行）。
链路已经补齐：`EX-SHOP-01`（历史用例库快照，证据 `artifacts/legacy/shop-cases.json`）→
5 个测试点 → 8 条 `status: reviewed` 的用例，`trace check` 干净。补链路的顺序是「来源 →
测试点 → 用例」：来源只登记基线（`confidence: confirmed` 是测试点能被批准的前提），测试点
走 `qa trace review approve`，用例在用例库里挂测试点并「标记为已评审」（`status=ready`
才会从 `draft/` 移进 `cases/`）。

注意 `EX-SHOP-01` 的类型是 `ex`（观测），不是 `req`，所以 `trace report` 会报
「8 reviewed case(s) without a REQ root」——这是事实而不是缺陷：拿到真实需求文档后应补
一层 `REQ-*`，并把该来源的 `confidence` 收回 `observed` 再重新评审下游。

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
nanobot qa reindex [--project SHOP] [--root DIR]   # YAML → SQLite 派生索引
nanobot qa run --project SHOP --kind api [--name 冒烟] [--environment staging]
nanobot qa run --project SHOP --case TC-SHOP-001
nanobot qa run --project SHOP --script scr_xxx
nanobot qa import-junit --project SHOP --file report.xml [--name ...] [--environment ...]
```

追溯/迁移侧（`qa_trace` 包）：

```text
python -m qa_trace trace migrate-sqlite [--project SHOP] [--db PATH] [--root DIR] [--json]
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
.\.venv\Scripts\python.exe -m pytest tests/qa -q                      # 132 passed（含 test_case_files.py 19 条、test_trace_api.py 27 条）
.\.venv\Scripts\python.exe -m pytest tests/qa_trace tests/qa -q       # 428 passed（P6 新增 65 条）
.\.venv\Scripts\python.exe -m pytest tests/webui -q                   # 776 passed, 18 skipped
.\.venv\Scripts\ruff.exe check qa_trace nanobot tests/qa tests/qa_trace   # All checks passed
.\.venv\Scripts\python.exe -m qa_trace trace diff --project qa-workbench/projects/login-lock --base 00bd2b4f   # 无回归, 0
.\.venv\Scripts\python.exe -m qa_trace trace diff --project qa-workbench/projects/login-lock --base 0a3cf427   # 项目在基线不存在, 2
cd webui; npm test -- qa; npm run build                               # 19 passed（含 qa-trace 8 条）
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
- 追溯页（「追溯」标签）与用例库（「用例库」标签）读同一个 YAML 库，但范围不同：用例库
  还列出草稿与未迁移的旧 SQLite 行，追溯页的链树只画正式库。迁移出来的旧用例没有链路，
  会以「缺来源/缺测试点」的草稿出现，`review list` 里是 invalid——需要人补测试点/来源后
  才能「标记为已评审」进入正式库。页面的「标记为已评审」不会替你造链路。
- 用例库的列表/搜索读 SQLite 派生索引：手工改 YAML 或 `git pull` 之后要跑
  `nanobot qa reindex`（新检出且一条索引行都没有时会自愈一次）。单条写入只更新对应派生行
  和追溯摘要，批量导入使用单事务；全量重建仅用于迁移/修复。出现异常时可设置
  `QA_CASE_TRACE_INCREMENTAL=0` 回退旧的完整列表/全量重建路径。
- 迁移只导出用例：SQLite 的 `scripts.case_ids` 仍是旧 `case_*` ID（不会自动映射成
  `<file>::<nodeid>` 脚本绑定），历史 `runs/` 里的 ID 也不回改；迁移不建需求/测试点。
- 用例 ID（`TC-<MODULE>-<seq>`）按「项目内最大号 + 1」分配，并发写同一项目可能撞号，
  会以一条写入失败告终（不会静默覆盖）；还没有分配/退休台账。
- 未迁移的旧行只读（可看、不可改），删除=墓碑（`tombstones/`），归档用例不能再执行。
- 追溯页不轮询——库被命令行改动后需要点「刷新」；草稿仍由 Agent 用
  `qa trace draft new/add` 或 `qa_case` 写入。
- CI 门禁（P5）只在本地验证了命令与退出码：`.github/workflows/qa-trace.yml` 还没有在
  真实 GitHub runner 上跑过（需要仓库启用 Actions 并配置分支保护）；PR 的 `--base`
  依赖 `fetch-depth: 0`，浅克隆会退化成 `TRACE_DIFF_BASE_UNKNOWN`。`diff` 与 `check`
  一样只做静态 marker lint，不跑 pytest collection；warn/info 变化不算回归。

详细路线与取舍（含竞品与工具调研）见 [`docs/design/qa-platform.md`](./design/qa-platform.md)、[`docs/research/`](./research/)。

