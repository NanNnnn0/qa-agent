# 2026-10-19 qa-chat-binding

- Goal: 需求 2 的后端部分——会话显式绑定 QA 项目，绑定时产出走 QA 流程/工作台，未绑定保持普通助手。
- Changed: 新增 `nanobot/qa/chat_context.py`（绑定规范化、runtime context provider、工具默认项目）；`nanobot/webui/inbound_commands.py`（`set_qa_project` 命令 + turn metadata 注入）；`nanobot/agent/tools/qa.py`（`_project_id` 默认会话绑定）；`nanobot/cli/gateway_runtime.py`（注册 provider）；`tests/qa/test_chat_context.py`。
- Verified: `pytest tests/qa` → 149 passed；`pytest ... -k workspace_scope` → 4 passed；`ruff check` 通过。
- Not done: 主对话 composer 的 QA 项目选择器与工作台默认项目（UI）尚未接线；未合并部署。
- Affects other sessions: 新增 WebSocket 命令 `set_qa_project` 与 session metadata `qa_project`；`qa_*` 工具的 `project_id` 变为可选（有会话绑定时生效）。未绑定会话零变化。
- Next step: 会话 payload 暴露 `qa_project`；composer 选择器写入绑定；工作台按绑定默认过滤；补组件测试后部署。
