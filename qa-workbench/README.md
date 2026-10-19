# qa-workbench 数据目录（qa-trace）

这里是 `qa_trace` 的**数据**目录，不是第二套工作台：页面仍然是 nanobot 已有的
「QA 工作台」，追溯能力是它的「追溯」标签页（`nanobot/qa/trace_api.py` +
`webui/src/components/qa/QaTrace.tsx`）。

```text
qa-workbench/
└─ projects/
   └─ login-lock/                 # 演示项目：登录锁定
      ├─ project.yaml             # 项目元信息与阈值
      ├─ sources/                 # REQ-* / UI-* …（链的根，必须带证据）
      ├─ testpoints/              # TP-*（挂来源）
      ├─ cases/                   # TC-*（挂测试点，或直挂来源并写 direct_reason）
      ├─ draft/<batch>/           # 待审草稿（不参与覆盖率与 check）
      ├─ scripts/                 # pytest 脚本（脚本侧只加 marker）
      ├─ artifacts/               # 证据：需求副本、截图、抓包
      └─ runs/<run-id>/manifest.json   # 真实运行记录（pytest 插件写入）
```

YAML 是真源，`.qa-trace/index.json` 与 `runs/` 是派生/历史，均不写回 YAML。

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
