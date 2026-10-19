# 2026-10-19 qa-chat-binding

- Goal: 需求 2 的后端部分——会话显式绑定 QA 项目，绑定时产出走 QA 流程/工作台，未绑定保持普通助手。
- Changed: 新增 `nanobot/qa/chat_context.py`（绑定规范化、runtime context provider、工具默认项目）；`nanobot/webui/inbound_commands.py`（`set_qa_project` 命令 + turn metadata 注入）；`nanobot/agent/tools/qa.py`（`_project_id` 默认会话绑定）；`nanobot/cli/gateway_runtime.py`（注册 provider）；`tests/qa/test_chat_context.py`。
- Verified: `pytest tests/qa` → 149 passed；`pytest ... -k workspace_scope` → 4 passed；`ruff check` 通过。
- UI：会话行/线程响应带 `qa_project`（未绑定不带）；`nanobot-client.setQaProject`；composer 的 `QaProjectControl`（原生 select，懒加载项目列表）；组件测试 `qa-project-control.test.tsx`。
- 工作台：新增「当前项目」scope（默认全部项目），从绑定会话打开时默认该项目，并把 scope 传给用例库/自动化/定时任务/运行记录四个 tab（各 tab 本地筛选与 scope 同步）。
- Verified: `vitest run qa-` → 30 passed；全量 `npm test` 的既有 5 条 drift 不变；`tsc`、eslint 通过。
- Not done: 无（需求 2 完成）；未合并 `main`。
- Affects other sessions: 新增 WebSocket 命令 `set_qa_project` 与 session metadata `qa_project`；`qa_*` 工具的 `project_id` 变为可选（有会话绑定时生效）。未绑定会话零变化。
- Next step: 会话 payload 暴露 `qa_project`；composer 选择器写入绑定；工作台按绑定默认过滤；补组件测试后部署。
