# 2026-10-19 qa-workbench-polish

- Goal: 改进 QA 工作台界面与交互（纯前端）：1) 项目创建后可编辑；2) 主对话选择项目；3) 自动化脚本按「项目 → 模块」分层；4) QA 定时任务。
- Changed: `webui/src/components/qa/QaOverview.tsx`（项目行新增「编辑」按钮，创建/编辑共用一个 `QaProjectDialog`，补齐 description 字段）；`webui/src/lib/qa-api.ts`（新增 `QaProjectUpdateInput` 与 `updateQaProject`，走既有 `qa.project.update` WS mutation）；`webui/src/components/qa/QaScripts.tsx` + 新增 `webui/src/components/qa/qa-script-groups.ts`（脚本按项目 → `file_path` 目录分层，两级可折叠，根目录/无路径单独分组）；`webui/src/tests/qa-workbench.test.tsx`（+3 条组件测试）。
- Verified:
  - `cd webui && npx vitest run qa-` → 2 files, 19 passed。
  - `cd webui && npm test` → 2806 passed / 5 failed（两次全量分别为 2805/6 与 2806/5）。失败全部落在 `app-layout.test.tsx`（4 条）与 `temporary-chat-navigation.test.tsx`（1 条），即 `docs/STATUS.md` 已记录的 test/UI drift（hero greeting / blank start page），与 QA 无关。
  - 基线对照：在 `90c9e92` 的干净 worktree 里只跑这两个文件 → 7 failed / 115 passed，同样的 4 条 app-layout 断言 + 3 条 temporary-chat-navigation 断言。改动前就失败，不是本分支引入。
  - `npx tsc -p tsconfig.build.json --noEmit` 通过；`npx eslint`（改动文件）无输出；`npm run build` 成功。
- Not done（必须改后端契约，已停手）:
  - 需求 2「主对话选择项目」：会话没有 `qa_project_id` 元数据，聊天轮次也不携带项目，前端只能往 prompt 里拼字符串，服务端无法据此路由/默认真实项目。
  - 需求 4「QA 定时任务」：`runs.trigger` 有 `schedule` 值，但没有 `qa.schedule.*` 动作、没有 schedules 存储、没有执行钩子；现有 cron 自动化只能由 agent 的 `cron` 工具在绑定话题里创建，WebUI 无创建入口；浏览器定时器关页即停，不算真正的定时任务。
  - 两条都写进了 `docs/adr/0002-qa-schedules-and-chat-project.md`（Status: proposed），给出建议的 `qa.schedule.*` payload、`QaSchedule` 形状与 session `qa_project_id` 注入方式。
- Affects other sessions:
  - 分支 `feat/qa-workbench-polish` 基于 `feat/qa-trace` 的 `90c9e92`，不是 `origin/main`：用户描述的 6 tab（含追溯）与 `QaTrace.tsx` 只存在于 `feat/qa-trace`；`origin/main` 仍是 5 tab。没有在 `feat/qa-trace` 上提交，但 trace 分支若继续前进，本分支合并前需 rebase。
  - ADR 0002 涉及 QA 域（`nanobot/qa/store|http|service.py`）与自动化/cron 归属，需要两位 owner 同意后再实现；本分支未改任何后端文件。
  - 新增 ADR 0002 后，`docs/design/qa-webui-brief.md` 的写动作表需要等契约落地再补（本次未改）。
- Next step: 决策 ADR 0002（是否接受 `qa.schedule.*` 与 session `qa_project_id`）；然后把 `feat/qa-workbench-polish` 合入 trace 分支或等 trace 合入 main 后 rebase 再合并。
