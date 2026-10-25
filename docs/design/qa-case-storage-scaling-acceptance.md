# QA 用例库存储与查询扩展性：第二轮验收记录

- 日期：2026-10-26
- 工作区：`/opt/worktrees/qa-case-storage-scaling`
- 实施基线：`18c5dab`（上一轮检查点）+ 本轮 6 项修复
- 结论：**整轮通过（带明确剩余限制）**。列表、详情、创建、更新、导入五个入口均有测试和实测数据；不再以“部分路径已优化”替代整体完成。

## 1. 验收环境

- 主机：hk-206，6 vCPU / 8 GB，Ubuntu 24.04，热缓存。
- Python：`/opt/qa-agent/.venv/bin/python`（3.12.3，SQLite 3.45.1）。
- 数据：`/tmp/qa-growth/10000`（10,000 条用例 + 5 个测试点/来源），基准库 `/tmp/qa-growth/bench/10000/qa.sqlite3`；导入性能使用隔离临时项目。
- WebUI：复用 `/opt/qa-agent/webui/node_modules` 软链；验收后删除。
- 不触碰 `/opt/qa-agent` 生产库和 YAML，不重启、不部署。

## 2. 自动化测试

| 范围 | 命令 | 结果 |
|---|---|---|
| QA 后端 | `pytest tests/qa -q` | **316 passed** |
| qa_trace | `pytest tests/qa_trace -q --ignore=tests/qa_trace/test_pytest_plugin.py` | **286 passed** |
| WebUI | `npx vitest run qa-` | **52 passed** |
| WebUI 类型 | `npx tsc -p tsconfig.build.json --noEmit` | 通过 |

`tests/qa_trace/test_pytest_plugin.py` 的既有环境失败（共享 venv 插件重复注册）不在本轮范围；在干净 HEAD 副本上同样复现。

## 3. 性能实测（10,000 条）

| 场景 | p50 | p95 | max | 目标 | 结论 |
|---|---:|---:|---:|---:|---|
| 详情 `get_case()` | 27.94 ms | **52.83 ms** | 52.97 ms | ≤200 ms | 通过 |
| 列表（50 条/页） | 8.15 ms | 34.52 ms | - | ≤300 ms | 通过 |
| 搜索中文 2 字 `登录` | 30.53 ms | 54.79 ms | - | ≤300 ms | 通过 |
| 搜索 code 子串 | 22.31 ms | 49.50 ms | - | ≤300 ms | 通过 |
| 创建（5 次预热 + 10 次采样） | 347.83 ms | **379.95 ms** | 379.95 ms | ≤500 ms | 通过 |
| 更新 title（3 次预热 + 10 次） | 390.43 ms | 414.39 ms | 414.39 ms | ≤500 ms | 通过 |
| 更新 code（10 次） | 390.98 ms | 408.38 ms | 408.38 ms | ≤500 ms | 通过 |
| 导入 1,000 条 | - | 5.43 s | - | ≤30 s | 通过 |
| 全量重建 10,000 条 | - | 60.88 s（解析 53.72 s） | - | 只要求单次解析 + 原子 | 通过 |

说明：

- 详情在旧实现下为 **51.393 s**（本次复测），修复后 p95 **52.83 ms**；现有定向 payload 原型在 10,000 条下 p50 3.25 ms，单用例摘要刷新 37.7 ms。
- 创建在进程启动后的第一次请求仍有一次全量编号同步（实测约 1.8～2.7 s，取决于文件系统缓存）；预热后 p95 379.95 ms。首次冷启动成本作为剩余限制记录。
- 全量重建从约 109 s 降到 60.88 s，但仍是 O(n)；耗时主要来自一次 YAML 解析（53.72 s），不承诺固定降幅。

## 4. 功能验收

### 4.1 详情

- `tests/qa/test_case_files.py::test_get_case_does_not_load_the_project`：monkeypatch `load_project` 与 `_rechecks_for` 抛错，详情仍返回完整链路。
- `test_get_case_refreshes_only_the_target_summary`：修改当前用例后只刷新当前摘要，无关用例 `input_hash`/`checked_at` 不变。
- 定向详情与旧全量 `_case_payload` 在 1,000 条 fixture 的 linked/unlinked/recheck 场景逐字段相等（本次对比脚本）。
- 摘要输入 hash 不一致、review baseline 变化（`no_review_baseline`）都会触发当前用例定向刷新；详情不信任过期 `needs_recheck`。

### 4.2 创建/更新编号

- `test_create_does_not_parse_every_case_document`：monkeypatch `iter_case_documents`/`_scan_project_documents` 抛错，创建仍成功。
- `test_a_manual_yaml_code_blocks_create_before_reindex`：未 reindex 的手工 YAML 也能阻止重复 code，自动编号继续到 `SHOP-API-002`/`TC-SHOP-002`。
- `test_concurrent_creates_share_one_allocation_ledger`：两个 `QaStore` 连接并发创建 10 条，ID/code 全部唯一。
- `test_write_document_refuses_to_overwrite_an_existing_file`：目标路径存在时 409，文件内容不变。
- `test_archived_case_keeps_its_code_occupied`：归档后 code/ID 仍占用。
- 迁移测试覆盖 v5→v6：重复 code 标记冲突、legacy + YAML 同 code 共存、重复打开幂等。

### 4.3 全量重建

- `test_reindex_does_not_load_the_project`：monkeypatch `load_project` 抛错，reindex 成功。
- `test_reindex_rolls_back_cases_and_trace_together`：注入 summary 插入失败，cases/summaries 与失败前一致。
- 10,000 条重建只解析一次；结果与增量刷新一致（现有 `test_trace_incremental.py`）。

### 4.4 导入

- `test_import_strict_rejects_the_whole_batch`：strict 下 1 条非法 → 零落盘、零 cases。
- `test_import_compat_keeps_the_valid_items`：compat 下合法项落盘、非法项进 errors。
- `test_import_strict_duplicate_code_aborts_and_releases_claims`：strict 冲突整批失败并释放预留 claim。
- `test_import_recovery_rolls_forward_files_committed`：`files_committed` journal + 完整文件 → 索引补齐、`complete`。
- `test_import_recovery_rolls_back_a_preparing_batch`：`preparing` → 删除本批文件、`aborted`。
- `test_import_recovery_does_not_delete_a_user_edited_file`：用户改过的文件不删除，journal `failed`。
- `test_http.py::test_import_mode_is_forwarded_through_the_websocket_route`：WebSocket mutation 正确传递 `mode`。
- 1,000 条导入 5.43 s；重复导入不产生重复 case/关系。

### 4.5 搜索与前端

- `EXPLAIN QUERY PLAN`：module 过滤使用 `idx_case_trace_summary_module`，operation 过滤使用 `idx_api_case_metadata_operation_case`；项目内查询不再全表 `SCAN cases`。
- `q` 仍保留 `%q%` 子串语义；中文/code 查询实测 p95 < 60 ms。
- FTS5 未默认启用；按方案保留“实测必要后单独实施”的门槛。
- WebUI 测试覆盖：URL 恢复筛选、越界页码纠正、popstate 恢复、搜索防抖写 URL；刷新 `#/qa?tab=cases&...` 回到用例库。

## 5. 剩余限制（必须随交付说明）

1. **FTS5 未启用**：搜索仍是 SQLite `LIKE`；前导通配符无法走 B-tree。当前 10,000 条实测在目标内，未引入 FTS5 的中文分词/短串兼容风险。
2. **首次创建冷启动**：进程启动后第一次 `create_case` 需要一次全量编号同步（约 1.8～2.7 s）；预热后 p95 379.95 ms。目录签名缓存只省重复枚举，不省内容变更检测的 stat。
3. **全量重建仍 O(n)**：10,000 条约 60.88 s，主要是一次 YAML 解析 + 全量 `build_graph`/`recheck_map`；只用于迁移/修复，不是日常路径。
4. **详情与损坏库**：正常库逐字段一致；正式库本身损坏时旧路径整体降级、新路径只降级受影响用例。若要求损坏库也完全一致，需要摘要持久化 `library_ok`。
5. **导入恢复窗口**：文件系统与 SQLite 无法组成跨系统事务；journal 保证最终收敛，不保证中断瞬间强原子。单条 create/update 没有批次 journal，只有 claim 补偿。
6. **跨文件系统/NFS**：`os.replace`/`O_EXCL` 的原子性按本地盘验收；NFS 等部署形态需单独确认。
7. **legacy code 占用**：legacy SQLite 行继续阻止新 YAML 使用同 code；迁移场景由 reindex 直接写 YAML 绕过 create。
8. **URL 历史**：筛选/翻页使用 `pushState`，浏览器历史会变长；详情抽屉选中项不写入 URL。
9. **QaWorkbench tab 依赖**：刷新恢复用例库需要同时改 `QaWorkbench` 的 `tab` URL 状态；本轮已改。

## 6. 复现命令

```bash
cd /opt/worktrees/qa-case-storage-scaling
/opt/qa-agent/.venv/bin/python -m pytest tests/qa -q
/opt/qa-agent/.venv/bin/python -m pytest tests/qa_trace -q \
  --ignore=tests/qa_trace/test_pytest_plugin.py

cd webui
ln -s /opt/qa-agent/webui/node_modules node_modules
npx vitest run qa-
npx tsc -p tsconfig.build.json --noEmit
rm node_modules
```

性能脚本为一次性 `/tmp` 脚本，不提交仓库；fixture 与基准库路径见第 1 节。

## 7. 结论

六项修复均已落地并通过对应测试；列表、详情、创建、更新、导入五个入口在同一轮验收中通过。剩余限制已逐项记录，其中 FTS5、首次创建冷启动、全量重建 O(n) 和导入恢复窗口属于明确保留项，不影响本轮“整体完成”的判定。
