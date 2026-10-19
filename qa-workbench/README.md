# qa-workbench 数据目录（qa-trace）

这里是 `qa_trace` 的**数据**目录，不是第二套工作台：页面仍然是 nanobot 已有的
「QA 工作台」，追溯能力是它的「追溯」标签页（`nanobot/qa/trace_api.py` +
`webui/src/components/qa/QaTrace.tsx`）。

```text
qa-workbench/
└─ projects/
   ├─ login-lock/                 # 演示项目：登录锁定
   │  ├─ project.yaml             # 项目元信息与阈值
   │  ├─ sources/                 # REQ-* / UI-* …（链的根，必须带证据）
   │  ├─ testpoints/              # TP-*（挂来源）
   │  ├─ cases/                   # TC-*（挂测试点，或直挂来源并写 direct_reason）
   │  ├─ draft/<batch>/           # 待审草稿（不参与覆盖率与 check）
   │  ├─ scripts/                 # pytest 脚本（脚本侧只加 marker）
   │  ├─ artifacts/               # 证据：需求副本、截图、抓包
   │  └─ runs/<run-id>/manifest.json   # 真实运行记录（pytest 插件写入）
   └─ shop/                       # 演示项目：Demo 商城（由 SQLite 用例迁移而来）
      ├─ project.yaml
      ├─ sources/EX-SHOP-01.yaml         # 历史用例库快照（证据：artifacts/legacy/shop-cases.json）
      ├─ testpoints/TP-SHOP-001..005.yaml # 按业务能力分组的测试点
      ├─ cases/TC-SHOP-001..008.yaml     # 8 条迁移用例（已挂测试点，status: reviewed）
      ├─ artifacts/legacy/shop-cases.json # 迁移前 SQLite 用例原文（导出快照）
      └─ tombstones/               # 删除即墓碑（status: deprecated + tombstone 块）
```

YAML 是真源，`.qa-trace/index.json`、SQLite 的 `cases` 表与 `runs/` 都是派生/历史，
均不写回 YAML。SQLite 用例用 `qa trace migrate-sqlite` 一次性导出：

```powershell
# 只读导出（--db 省略时读 NANOBOT_QA_DB）：
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite --project SHOP --root qa-workbench/projects
# 重建 SQLite 派生索引（YAML 改完或迁移之后）：
.\.venv\Scripts\nanobot.exe qa reindex --project SHOP --root qa-workbench/projects
```

导出只搬用例本身，不替你造需求或测试点：迁移出来的 8 条用例一开始是
`draft/sqlite-migration/cases/` 下的无链草稿（`trace check --include-draft` 会报
`TRACE_LINK_MISSING`）。补齐链路要按 review 门禁走一遍：

```powershell
# 1) 把上层来源与测试点作为草稿加进来（--batch 与用例同一批）
.\.venv\Scripts\python.exe -m qa_trace trace draft add --project qa-workbench/projects/shop --file sources/EX-SHOP-01.yaml --batch sqlite-migration --kind source
.\.venv\Scripts\python.exe -m qa_trace trace draft add --project qa-workbench/projects/shop --file testpoints/TP-SHOP-001.yaml --batch sqlite-migration --kind testpoint

# 2) 先接受来源（来源只登记基线，不算评审），再逐个批准测试点
#    注意：来源 confidence 必须是 confirmed，否则测试点批不了
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project qa-workbench/projects/shop --id EX-SHOP-01 --batch sqlite-migration
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project qa-workbench/projects/shop --id TP-SHOP-001 --batch sqlite-migration

# 3) 在用例库里把用例挂到测试点并“标记为已评审”（status=ready 才会进 cases/）
#    走 HTTP/UI：PATCH /api/qa/cases/{id} body {"status":"ready","testpoints":["TP-SHOP-001"]}
.\.venv\Scripts\nanobot.exe qa reindex --project SHOP --root qa-workbench/projects
```

`shop` 当前的链路是 1 个来源（`EX-SHOP-01`，历史用例库快照）→ 5 个测试点 → 8 条用例，
`trace check` 干净，只剩一条 `TRACE_P0_RATIO_HIGH` 警告（P0 占 37.5%，超过项目阈值），
以及 `report` 里的 “8 reviewed case(s) without a REQ root”：根节点是 `ex` 观测而不是
需求，拿到真实需求文档后应补一层 `REQ-*` 并把 `EX-SHOP-01` 的 `confidence` 收回
`observed` 再重新评审下游。

## 演示命令

```powershell
# 1) 校验（0 = 干净；只扫正式库，草稿默认不参与）
.\.venv\Scripts\python.exe -m qa_trace trace check --project qa-workbench/projects/login-lock

# 2) 四个指标分开报（需求 / 行为 / 自动化 / 孤儿）
.\.venv\Scripts\python.exe -m qa_trace trace report --project qa-workbench/projects/login-lock

# 3) 跑一次真实 pytest，写 run manifest（--qa-project 决定写进项目的 runs/）
.\.venv\Scripts\python.exe -m pytest -p qa_trace.pytest_plugin `
  --qa-project=qa-workbench/projects/login-lock `
  qa-workbench/projects/login-lock/scripts/test_login.py -q

# 4) 失败回溯：run -> case -> testpoint -> source
.\.venv\Scripts\python.exe -m qa_trace trace failure --project qa-workbench/projects/login-lock --run <run-id>

# 5) 影响面 / 变更 / 草稿
.\.venv\Scripts\python.exe -m qa_trace trace impact  --project qa-workbench/projects/login-lock --source REQ-LOGIN-01
.\.venv\Scripts\python.exe -m qa_trace trace stale   --project qa-workbench/projects/login-lock
.\.venv\Scripts\python.exe -m qa_trace trace review list --project qa-workbench/projects/login-lock
```

工作台入口：启动网关后打开 WebUI → 左侧「QA 工作台」→「追溯」标签页。项目根默认
`<repo>/qa-workbench/projects`，可用环境变量 `NANOBOT_QA_TRACE_ROOT` 指到别处。

演示脚本里的断言**故意失败**（产品第 5 次失败后仍返回 401，需求要求 423），
所以 `trace failure` 有内容可看；修复产品后脚本自然转绿，用例不需要改。
