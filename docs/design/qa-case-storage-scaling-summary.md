# QA 用例库存储与查询扩展性：实施总结

- 日期：2026-10-25
- 工作区：`/opt/worktrees/qa-case-storage-scaling`
- 结论：第 1～6 步已完成。用例列表、追溯链、单条写入和批量导入已从“每次全项目 YAML 扫描/重建”拆成“SQLite 摘要 + 定向 YAML 读取 + 增量派生索引”，并补齐了模块/接口筛选和前端分页。
- 未完成：`get_case()` 详情仍走完整项目加载（10,000 条约 52 秒），本次未修复；FTS5 按计划后置。

## 1. 解决的问题

1. **列表请求代价过高**：原 `CaseFiles.list_cases()` 在返回每条 case 前都会 `load_project()`、构建追溯图、计算复核状态，并重新读取每条 YAML。1,000 条约 5.3 秒，10,000 条约 51 秒。
2. **详情与列表耦合**：列表和详情都走同一套完整 YAML/追溯组装逻辑，无法只返回轻量摘要。
3. **追溯结果无法增量复用**：修改一个测试点或需求后，只能全量 `reindex()`，无法只刷新真正引用它的 case。
4. **写入放大**：`create_case()`、`update_case()`、`delete_case()` 和批量导入都通过全量 `reindex()` 更新派生索引；导入 1,000 条按 O(n²) 外推约 48 分钟。
5. **缺少结构化检索**：只能按项目/类型/状态和 `LIKE` 搜索，不能按模块或接口过滤，也没有前端分页。
6. **迁移和派生表缺少基础**：没有追溯边、case 摘要、YAML hash/mtime 状态表，无法支撑增量路径。

## 2. 实施内容

### 2.1 索引与迁移基础（第 1 步）

- `SCHEMA_VERSION = 5`。
- 新增三张可重建派生表：
  - `trace_edges(project_id, from_type, from_id, to_type, to_id)`：子实体指向父实体，反向索引支持依赖查询。
  - `case_trace_summary`：`needs_links`、`needs_recheck`、`trace_status`、`recheck_reasons`、`testpoint_count`、`source_count`、`module_id`、`group_name`、`api_method`、`api_path`、`input_hash`、`checked_at`、`state`。
  - `trace_file_state`：YAML 文件 `path`、实体类型/ID、`content_hash`、`mtime_ns`。
- 新增索引：边反向查询、summary 按项目/模块/复核状态、文件按实体，以及 `cases(project_id, code)`、`cases(project_id, kind, code)` 等列表索引。
- 迁移使用 `CREATE TABLE/INDEX IF NOT EXISTS`；v4→v5 迁移分支重复执行 DDL，重复启动幂等。
- `case_trace_summary` 的后续列（`module_id` 等）通过打开时列检查增量补齐，避免已存在的 v5 数据库因缺少列失败。
- `CaseFiles.reindex()` 同时重建 case 行和 v5 追溯索引；派生表删除后可从 YAML 重建。
- 旧 YAML、`derived = 0` 的 legacy SQLite 行保持可读。

### 2.2 列表/详情拆分（第 2 步）

- 新增 `QaStore.list_case_summaries()`：列表只查 SQLite，不读取 YAML、不调用 `load_project()`。
- `CaseFiles.list_cases()` 返回轻量摘要，默认 50 条，保留 `limit/offset`；HTTP 列表默认也改为 50。
- 摘要包含 `code/title/module_id/group/operation_id/api_method/api_path/kind/priority/status/tags`、追溯计数/状态、时间字段和 `yaml_path`。
- 列表不返回 `api/steps/expected/preconditions/testpoints/sources/trace_testpoints/trace_sources`。
- 详情 `get_case()` 保持原有完整 JSON 契约，仍返回完整测试点、需求、链路和复核原因。
- 导出改用内部 `_list_cases_full()`，保持完整格式。
- 旧调用方适配：agent 工具列表使用 `step_count/has_api`；测试点资产页使用 `needs_links`；WebUI 列表徽标使用摘要计数，详情抽屉单独加载完整 case。

### 2.3 增量追溯链（第 3 步）

- 新增 `CaseFiles.affected_cases_for_entity()`：
  - 修改 case → 该 case。
  - 修改 testpoint → 直接引用它的 case。
  - 修改 requirement/source → 直接引用它的 case，以及引用它的 testpoint 下的 case。
- 新增 `CaseFiles.refresh_trace_for_cases()`：只读取目标 case 和关联 testpoint/source，不调用全项目 `load_project()`；更新边、文件状态和 summary。
- 新增 `CaseFiles.refresh_trace_entity()` / `refresh_trace_for_entity()`：更新实体边/文件状态，再刷新受影响 case。
- `needs_recheck` 通过只包含目标 case 及其上游实体的最小 `Project` + `recheck_map()` 计算，避免全项目加载。
- 缺失实体/文件时标记 `state = stale`，不静默当作“没有关联”。
- 全量 `reindex()` 保留为修复工具。
- 增量结果与全量重建在 summary（除 `checked_at`）、`trace_edges`、`trace_file_state` 三项上逐项一致。

### 2.4 增量写入和批量导入（第 4 步）

- 新增 `QaStore.upsert_derived_case()` / `upsert_derived_cases()`：单行 `INSERT ... ON CONFLICT(id) DO UPDATE`，更新时保留 `created_at`。
- `create_case()`：YAML 写入 → 单行 upsert → 增量追溯刷新，不再全量 `reindex()`。
- `update_case()`：只更新对应派生行，并只刷新该 case 的追溯摘要/边。
- `delete_case()`：写 tombstone 后单行更新派生行，不重建项目索引。
- `update_case()` 改 code 时旧 code 从索引中消失，新 code 生效。
- 写入响应使用定向 payload 构造，不调用完整 `get_case()`；响应字段与详情保持一致性测试。
- `_check_promotable()` 和 `_record_review()` 改为按引用实体定向校验/计算指纹，不再 `load_project()`。
- `import_cases()` 改为批量路径：
  - 先校验/分配 code 和 ID；
  - 写 YAML；
  - 调用 `QaStore.apply_case_batch()` 在**一个 SQLite 事务**中完成 case 行、summary、edges、file state；
  - 写入或事务失败时删除本次已写 YAML，SQLite 回滚；
  - 支持导入 `testpoints/sources/direct_reason/risk`，并生成/去重关系；
  - 重复 code 跳过，重复导入不产生重复 case 或关系。
- HTTP trace review approve/reject 改为按被审核实体调用 `refresh_trace_entity()`，失败才回退全量 reindex。

### 2.5 搜索、模块筛选和前端分页（第 5 步）

- 列表新增 `module_id` / `operation_id` 筛选，保留 `project_id/kind/status/query/limit/offset`。
- HTTP 兼容别名：`module_id`/`module`、`operation_id`/`operation`、`q`/`query`。
- 新增 `QaStore.list_case_facets()` 和 `/api/qa/cases/facets`，返回模块/接口选项及计数。
- 新增索引：`idx_cases_project_code`、`idx_cases_project_kind_code`、`idx_api_case_metadata_operation`、`idx_case_trace_summary_project_module`。
- WebUI 用例库默认每页 50 条，增加模块/接口下拉、上一页/下一页和页码信息。
- 列表仍只请求摘要；点击 case 后由详情抽屉单独调用 `loadQaCase()`。
- 搜索继续使用 `LIKE`，FTS5 按计划后置；标题/code 的 FTS5 不改变旧 `q` 搜索语义。

### 2.6 兼容与回滚（第 6 步）

- 新增环境开关 `QA_CASE_TRACE_INCREMENTAL`（默认 `1`）。设为 `0` 后：
  - 列表回到旧完整 payload 路径；
  - create/update/delete 写 YAML 后回到全量 `reindex()`；
  - import 回到逐条 `create_case()` 的旧路径；
  - trace review 回到全量 `reindex()`；
  - `refresh_trace_for_cases()` / `refresh_trace_entity()` 直接执行全量 `reindex()`。
- 列表摘要缺失（derived case 的 `state = unknown`）或摘要表损坏（`sqlite3.DatabaseError`）时，自动回退旧完整列表路径；只影响当前请求，不写 YAML。
- 派生索引损坏或缺失时，执行全量 `reindex()` 即可重建；三张派生表删除后重跑也可恢复。`reindex()` 不修改 YAML 源文件。
- 旧 YAML、legacy SQLite 行、`qa-agent.cases.v1` export/import 继续兼容。
- 具体迁移/回滚步骤见第 7 节。

## 3. 验证

### 3.1 自动化测试

| 范围 | 结果 |
|---|---|
| `pytest tests/qa -q` | 298 passed |
| `pytest tests/qa_trace -q --ignore=tests/qa_trace/test_pytest_plugin.py` | 286 passed |
| WebUI `npx vitest run qa-` | 49 passed |
| `npx tsc -p tsconfig.build.json --noEmit` | 通过 |
| ESLint / Ruff / `py_compile` / `git diff --check` | 通过 |

`tests/qa_trace/test_pytest_plugin.py` 有 10 个既有环境失败（共享 venv 中 `qa_trace` 插件重复注册）；在干净 HEAD 副本上复现，与本次改动无关。

### 3.2 基准结果

| 场景 | 结果 |
|---|---|
| 列表 1,000 条（50 条/页） | p50 约 2.7 ms |
| 列表 10,000 条（50 条/页） | p50 约 21 ms，max 约 47 ms |
| 50 条列表响应体 | 48,648 bytes，低于 120 KB 目标 |
| 单条 update 1,000 条项目 | p50 约 60 ms |
| 单条 update 10,000 条项目 | p50 约 89 ms，未随 YAML 数量线性增长 |
| 导入 1,000 条 | 4.32 s，低于 30 s 目标 |
| 重复导入 1,000 条 | 0.04 s，`created = 0`，`skipped = 1000` |

### 3.3 关键行为验证

- v2/v4/v5 数据库迁移保留 case 数量、legacy 行和索引；重复打开不重复建表/数据。
- 删除三张 v5 派生表后 `reindex()` 可从 YAML 恢复边、摘要和文件状态。
- 列表不调用 `load_project()`；带 `module_id` + 关键词的列表也不读取 YAML。
- 详情仍返回完整 `api/steps/expected/testpoints/sources/trace_testpoints/trace_sources`。
- 修改一个 testpoint 只刷新引用它的 case；修改一个 requirement 只刷新关联 testpoint 下的 case 及直接引用 case；无关 case 的 `input_hash` 和 `checked_at` 不变。
- 增量刷新后的 summary、edges、file states 与全量 `reindex()` 结果一致。
- 删除 testpoint 后对应 case 标记 `stale`，数量归零。
- 单条 update/create 在 monkeypatch 掉 `reindex`/`load_project` 后仍成功。
- 批量导入通过 SQLite trigger 注入失败时，case 行和本次写入的 YAML 文件都回滚。
- 重复导入不产生重复 case；带 testpoint 的重复导入不产生重复关系。

## 4. 已知限制与后续

1. **详情仍走完整项目加载（本次未修复）**：`get_case()` 为保持完整契约，仍会 `load_project()`；10,000 条项目实测约 52 秒。下一步应改为“目标 YAML + summary + 定向上游实体”的详情路径，或加项目图缓存。
2. **FTS5 未实施**：当前搜索是 SQLite `LIKE`，保留兼容回退；标题/code 的 FTS5 可在后续增加。
3. **全量 `reindex()` 仍是 O(n)**：10,000 条约 109 秒，定位为迁移/手工修复工具；日常写入已不调用。
4. **create_case 的 code/ID 分配仍会扫描已有 YAML**：单条 update 已不随项目规模线性增长，但超大项目首次创建仍可优化为基于派生索引分配。
5. **WebUI 分页状态未写入 URL**：当前页/筛选在组件状态中，刷新页面回到第一页。
6. **导入校验采用逐项错误**：单个非法条目会记录到 `errors`，合法条目仍可导入；SQLite/YAML 的“批量失败回滚”覆盖写入或事务异常。

## 5. 主要变更文件

```text
nanobot/qa/store.py                          schema v5、摘要查询、增量行 upsert、批量事务、facets
nanobot/qa/case_files.py                     列表/详情拆分、增量追溯、增量写入、批量导入、定向 payload
nanobot/qa/http.py                           列表默认 50、模块/接口参数、facets、review 增量刷新
nanobot/qa/testpoints.py                     list_assets 使用 needs_links
nanobot/agent/tools/qa.py                    agent 列表使用 step_count/has_api
webui/src/lib/qa-api.ts                      模块/接口参数、facets 类型与请求
webui/src/components/qa/QaCaseLibrary.tsx    50 条分页、模块/接口筛选、详情抽屉
webui/src/components/qa/QaApiAssets.tsx      接口资产页按 operation_id/api_method/api_path 分组并加载详情
tests/qa/test_case_files.py                  迁移、列表、写入、导入、筛选、回滚测试
tests/qa/test_trace_incremental.py           增量追溯与全量一致性测试
tests/qa/test_store.py                       摘要/边/文件状态/操作关联测试
tests/qa/test_db_migration.py                 v4/v5 迁移与索引测试
tests/qa/test_trace_chain.py                 列表摘要与详情链路测试
tests/qa/test_compat_rollback.py             flag 关闭、摘要缺失回退、删表重建、YAML 不被重写
webui/src/tests/qa-workbench.test.tsx        50 条分页测试
docs/design/qa-case-storage-scaling-summary.md 本文
docs/qa-agent.md                             产品文档同步增量写入/回滚说明
```

## 6. 复现命令

```bash
cd /opt/worktrees/qa-case-storage-scaling

.venv/bin/python -m pytest tests/qa -q
.venv/bin/python -m pytest tests/qa_trace -q \
  --ignore=tests/qa_trace/test_pytest_plugin.py

cd webui
npx vitest run qa-
npx tsc -p tsconfig.build.json --noEmit
```

本工作区没有独立 `.venv` 时，可用部署机共享解释器：

```bash
/opt/qa-agent/.venv/bin/python -m pytest tests/qa -q
```

WebUI 测试需要 `webui/node_modules`；工作区未安装时可临时复用部署机依赖，验证后删除符号链接。

## 7. 迁移与回滚

### 7.1 一键关闭新路径

默认开启增量/摘要路径。需要回退时设置：

```bash
export QA_CASE_TRACE_INCREMENTAL=0
```

然后重启 gateway/服务进程。关闭后：

- `CaseFiles.list_cases()` 回到旧的完整列表路径，返回完整 `api/steps/expected` 和链路；
- `create_case()` / `update_case()` / `delete_case()` 写 YAML 后调用全量 `reindex()`；
- `import_cases()` 回到逐条 `create_case()` 的旧导入路径；
- trace review approve/reject 回到全量 `reindex()`；
- `refresh_trace_for_cases()` / `refresh_trace_entity()` 直接执行全量 `reindex()`；
- `_ensure_indexed()` 首次索引时重建 trace 表。

恢复新路径：

```bash
unset QA_CASE_TRACE_INCREMENTAL
# 或
export QA_CASE_TRACE_INCREMENTAL=1
```

同样需要重启进程。环境变量每次调用时读取，但服务进程需要重启才能稳定应用。

### 7.2 摘要缺失/索引损坏时的读取回退

- 列表摘要查询遇到 `sqlite3.DatabaseError`（例如 `case_trace_summary` 被删除或损坏）时，自动回退到旧完整列表路径。
- 摘要表存在但某个 derived case 没有 summary 行（`state = unknown`）时，同样回退旧完整列表路径。
- 回退只影响当前请求；不会写入 YAML，也不会自动删除数据。
- 回退路径较慢且响应更大，适合临时排障，不应作为长期运行状态。

### 7.3 重建索引

推荐命令：

```bash
cd /opt/worktrees/qa-case-storage-scaling
.venv/bin/nanobot qa reindex --project SHOP
```

或从 Python：

```python
from nanobot.qa import shared_store
from nanobot.qa.case_files import reindex_cases

reindex_cases(shared_store(), project_key="SHOP")
```

全量 `reindex()` 会：

- 重新扫描 YAML，重建 `cases` 的 `derived = 1` 行；
- 重建 `trace_edges`、`case_trace_summary`、`trace_file_state`；
- 不修改 YAML 源文件；
- 不删除 legacy（`derived = 0`）行。

如果派生表结构本身损坏，可直接删除三张派生表后重跑 reindex；`QaStore` 打开时会用 `IF NOT EXISTS` 重建表，`reindex()` 会补回数据：

```sql
DROP TABLE IF EXISTS trace_edges;
DROP TABLE IF EXISTS case_trace_summary;
DROP TABLE IF EXISTS trace_file_state;
```

不要删除 `cases` 表中的 legacy 行，也不要把空索引解释成空用例库；先确认 YAML 文件仍在，再执行 reindex。

### 7.4 数据库备份与恢复

- 迁移前备份 `qa.sqlite3` 及 WAL/SHM 文件。
- SQLite 只是派生索引；YAML 是源数据。恢复旧数据库不会覆盖 YAML，但新 YAML 可能尚未进入旧库，需要 reindex 重新认领。
- 如果新索引异常但 YAML 正常，优先 reindex；只有数据库本身损坏时才恢复备份。
- 回滚不需要回滚 YAML 文件；YAML 始终由人工 review 和 git 管理。

### 7.5 兼容性边界

- 旧 YAML 文件：继续由 `qa_trace.loader` 读取，格式未变。
- legacy SQLite 行：仍可读，`derived = 0` 行不会在 reindex 中被删除。
- export/import：`qa-agent.cases.v1` 格式保持不变；导入支持完整字段和关系，重复 code 跳过。
- 列表旧参数：`q`、`limit`、`offset` 继续有效；`module_id`/`operation_id` 是新增可选参数。
- 前端：默认 50 条分页；详情仍单独请求完整 case；关闭新路径时列表回到旧完整 payload（含 `api/steps` 等，新增摘要字段可能缺失），仍满足旧字段契约。

### 7.6 验证覆盖

- `tests/qa/test_compat_rollback.py`：flag 关闭后的列表/创建/更新/导入/刷新、摘要缺失回退、删表回退、reindex 修复、YAML 不被重写。
- `tests/qa/test_db_migration.py`：v2/v4/v5 迁移、索引、重复打开、派生列补齐。
- `tests/qa/test_case_files.py`：旧 YAML/legacy 行、export/import、列表/详情、筛选和批量导入。


## 8. 当前交付状态

- 新路径开关：`QA_CASE_TRACE_INCREMENTAL=0` 可关闭摘要列表、增量写入、批量导入和增量 review 刷新，回退旧完整路径；默认开启。
- 摘要缺失/索引损坏：列表自动回退旧完整列表；不把空摘要解释成空用例库。
- 索引重建：执行全量 `reindex()`；删除三张派生表后重跑也可恢复。
- YAML：`reindex()` 不写 YAML；只有显式 create/update/delete/import 会按业务语义写 YAML。
- 兼容：旧 YAML、legacy SQLite 行、`qa-agent.cases.v1` export/import 保持可用。
- 详情：`get_case()` 仍返回完整测试点/需求/链路，但加载性能未优化；这是明确保留的后续项。

## 9. 第二轮修复方案

第 1～6 项后续修复（详情定向读取、编号索引分配、重建单次解析、导入模式与恢复、搜索、URL 状态）的方案见
[`qa-case-storage-scaling-remediation.md`](./qa-case-storage-scaling-remediation.md)。本轮只给方案，未改代码。
