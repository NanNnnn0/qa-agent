# 2026-10-19 qa-schedules

- Goal: 实现需求 4「QA 工作台定时任务」：按 cron 定时运行自动化脚本或用例集合，浏览器关闭后仍由网关执行。
- Changed: `nanobot/qa/schedule_time.py`、`nanobot/qa/scheduler.py`（新增）；`nanobot/qa/store.py`（`schedules` 表，schema v3，CRUD/claim/record）；`nanobot/qa/http.py`（`qa.schedule.create/update/delete/run_now` 与 `GET /api/qa/schedules`）；`nanobot/cli/gateway_runtime.py`（启动/停止 `QaScheduler`）；`webui/src/components/qa/QaSchedules.tsx`（新增）、`QaWorkbench.tsx`（新增 tab）、`QaScripts.tsx`（`QaRunResult` 用正确的 `testId`）、`webui/src/lib/qa-api.ts`；测试 `tests/qa/test_schedules.py`、`webui/src/tests/qa-schedules.test.tsx`。
- Verified: `pytest tests/qa` → 124 passed；`ruff check nanobot/qa` 通过；`npx vitest run qa-` → 23 passed（3 files）；`npx tsc -p tsconfig.build.json --noEmit` 通过；改动文件 eslint 无告警；`npm run build` 通过。
- Not done: 需求 2（主对话选择 QA 项目）只完成调研与 ADR 方案，未实现；没有合并 `main`，没有改 `feat/qa-trace`。
- Affects other sessions: 新增公共契约 `qa.schedule.*`（ADR 0002 已 accepted，schema v3 自动迁移），并改了 `nanobot/cli/gateway_runtime.py` 的启动/停止钩子；自动化/cron 归属方需要知道 `QaScheduler` 与 `CronService` 并行运行。
- Next step: 需求 2 若确认走 ADR 0002 的 session `qa_project_id` 方案，再实现会话绑定与主对话项目选择器；把本分支合入部署分支并重启服务。
