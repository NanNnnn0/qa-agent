# 2026-10-19 qa-project-workspace

- Goal: QA 项目自动拥有并维护一个专属工作区目录（C 方案），让对话区出现对应项目。
- Changed: 新增 `nanobot/qa/workspace.py`（目录分配/维护）；`nanobot/qa/store.py`（创建时分配、清空时重分配、schema v4 迁移回填）；`nanobot/webui/inbound_commands.py`（绑定时确保目录存在）；`nanobot/qa/chat_context.py`（binding 带 repo_path）；`tests/qa/conftest.py`（用 `NANOBOT_QA_PROJECTS_ROOT` 隔离）；`tests/qa/test_project_workspace.py`。
- Verified: `pytest tests/qa` → 235 passed；`ruff check` 通过。
- Not done: 目录不随项目 key 改名移动；用户显式 repo_path 不会被自动创建。
- Affects other sessions: schema 版本升到 v4（新增回填迁移）；项目创建会自动填充 `repo_path`；新增 `NANOBOT_QA_PROJECTS_ROOT` 环境变量。
- UI：会话侧栏统一成「项目」列表（QA 项目 + 收藏目录），每个项目下直接有「新建对话」和属于它的对话；没有项目的对话归入「话题」。空项目也会显示，去掉重复的小写目录分组。
- 用例库仍是集中管理：用例/追溯产物由 QA 库（trace root 下的按项目子目录）维护，与工作区目录无关；工作区只影响对话的 sandbox 与侧栏分组。
- Next step: 部署重启后现有项目会自动回填工作区目录。
