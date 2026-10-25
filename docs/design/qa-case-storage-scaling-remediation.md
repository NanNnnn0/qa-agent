# QA 用例库存储与查询扩展性：第二轮修复方案

- 日期：2026-10-25
- 工作区：`/opt/worktrees/qa-case-storage-scaling`
- 状态：**仅方案，本轮不改代码**
- 基线：当前工作区 `f1e31f9` + 未提交改动（上一轮 14 个文件，约 3981 行新增）
- 关联：`docs/design/qa-case-storage-scaling-summary.md` 第 4 节「已知限制与后续」第 1～6 条

## 0. 结论、范围与优先级

本轮把上一轮明确留下的 6 个缺口逐项补成可验收的修复，不再用「列表/单条写入已优化」代表整体完成。

| 序号 | 修复项 | 优先级 | 交付单元 | 依赖 |
|---|---|---|---|---|
| 1 | 详情改为定向读取 | P0 | 独立 PR | 无 |
| 2 | 创建编号改为索引分配 | P0 | 独立 PR（schema v6） | 无 |
| 3 | 全量重建只解析一次 | P1 | 独立 PR | 可与 2 共用 schema 事务方法 |
| 4 | 导入模式与失败恢复 | P1 | 独立 PR（schema v6/v7） | 复用 2 的编号分配 |
| 5 | 搜索独立优化 | P2 | 独立 PR | 无 |
| 6 | 分页与筛选同步 URL | P2 | 独立 PR | 需要 QaWorkbench 的 tab 配合 |

实施顺序固定为 1 → 2 → 3 → 4 → 5 → 6；其中 1、2 必须先完成并单独验收，3～6 可以并行开发但分别提交、分别验收。验收口径覆盖列表、详情、创建、更新、导入全部入口；任何一项只完成部分路径，不得判定本轮完成。

### 0.1 当前基线（本机实测，非生产）

主机：hk-206，6 vCPU / 8 GB，热缓存；数据：`/tmp/qa-growth/10000`（10,000 条用例 + 5 个测试点/来源），基准库 `/tmp/qa-growth/bench/10000/qa.sqlite3`。

| 场景 | 现状 | 证据 |
|---|---:|---|
| `CaseFiles.get_case()` 10,000 条 | **51.393 s**（单次） | 本次实测，完整 `load_project()` + 全量 `recheck_map()` |
| 现有定向 payload 构造（`_case_payload_for_write`）10,000 条 | p50 **3.25 ms**，p95 **3.66 ms** | 本次实测，20 次；只读目标 YAML + 关联实体 |
| 单用例定向摘要刷新（`refresh_trace_for_cases`）10,000 条 | **37.7 ms** | 本次实测；删掉该用例摘要后刷新一次 |
| 创建时的 code 查重（`_known_codes`）10,000 条 | **48.615 s** | 本次实测；解析全部 case YAML |
| 10,000 条 case 文件枚举 / stat | 245～296 ms / 44～67 ms | 本次实测；文件系统为当前工作区 |
| 全量 `reindex()` 10,000 条 | 约 109 s（上一轮记录） | 两次解析；本次中断时观察到 `cases=10000, summaries=0, edges=10006` 的瞬时半套索引 |
| 列表 10,000 条（50 条/页） | p50 约 21 ms（上一轮记录） | 摘要查询，未重新测 |

结论：详情目标（10,000 条 P95 ≤ 200 ms）在现有定向 payload 上已经有充足余量，主要工作是让 `get_case()` 走这条路径并处理摘要过期；创建的主要成本是 `_known_codes` 的全量 YAML 解析，索引分配后应回到百毫秒级。

## 1. 详情改为定向读取（P0，优先完成）

### 1.1 现状与根因

`nanobot/qa/case_files.py` 当前 `get_case()`（约 764～787 行）：

1. `store.get_case()` 取行；
2. `store.get_project()`；
3. `_document()` 读目标 YAML；
4. `_trace_for(project)` → `load_project(directory)`，解析**整个正式库**；
5. `_rechecks_for(trace)` → `build_graph(library)` + `recheck_map(library)`，遍历**整个项目**；
6. `_case_payload(...)` 用全量 trace 组装。

10,000 条时第 4 步约 50 s，第 5 步在全量库上再叠加成本，最终 51.4 s。定向 payload 构造已经存在（`_case_payload_for_write`，约 1952～2006 行），但只用于写响应，没有复用到详情。

### 1.2 目标行为

- 普通详情只读取：目标 YAML、该用例的摘要行、直接引用的测试点/来源 YAML，以及为计算测试点编号所需的**正式测试点 ID 列表**（SQL + 目录文件名，不解析全部 YAML）。
- 摘要缺失、`state != fresh` 或输入 hash 不一致时，只重算当前用例及其必要上游关系，并回写该用例摘要；不触碰无关用例的 `checked_at`/`input_hash`。
- 普通详情禁止调用 `load_project()`、禁止全项目 `build_graph()`/`recheck_map()`。
- 返回字段、追溯徽标、`legacy` 行、草稿/正式/归档位置、`needs_links`/`needs_recheck`/`recheck_reasons` 与旧路径一致。

### 1.3 改动设计

#### 1.3.1 抽出共享的定向 payload 构造

把 `_case_payload_for_write()` 改名为 `_case_payload_for_target()`（保留旧名别名一个版本，避免外部测试/调用断裂），职责固定为：

```python
def _case_payload_for_target(
    self,
    project: Mapping[str, Any],
    directory: Path,
    row: Mapping[str, Any],
    document: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """目标 YAML + 直接上游实体 + 摘要 → 与旧详情完全同形的 payload。"""
```

内部仍复用 `_case_reference_context()`：

- 只读 `document.testpoints` 与 `document.sources` 指向的正式/草稿文件；
- 测试点再带上其 `sources`；
- 不读其他用例，不读整个项目。

测试点编号（`TP-01` 这种 ordinal）依赖正式库全集，不能只用当前用例引用的测试点，否则编号会变。处理方式：

1. `store.list_trace_entity_ids(project_id, "testpoint")` 取已索引的正式测试点 ID（SQL，O(testpoints)）；
2. 用 `_yaml_files(directory / "testpoints")` 的文件名补上未索引的新文件（只列目录，不解析）；
3. 若某个文件名 stem 不在 ID 集合中，且该文件不在 `trace_file_state`，只解析这一个文件取声明 ID；
4. 把这些 ID 以轻量 stub 放进 `SimpleNamespace(testpoints=...)`，保证 `testpoint_codes()` 的排序/编号与全量库一致。

#### 1.3.2 `get_case()` 新流程

```python
def get_case(self, case_id: str) -> dict[str, Any]:
    try:
        raw = self.store.get_case(case_id)
    except QaNotFoundError:
        # 保持旧兼容：全新检出、还没有派生行时，允许一次首建索引
        self._ensure_indexed(self._all_project_ids())
        raw = self.store.get_case(case_id)
    if raw.get("derived") != 1:
        return self._legacy_payload(raw)          # 旧 SQLite 行仍走轻量路径

    row = self._row(case_id)
    project = self.store.get_project(row["project_id"])
    directory = self.project_dir(project)
    document = self._document(row, directory)     # 只读目标 YAML

    summary = self.store.get_case_trace_summary(case_id)
    if self._summary_needs_refresh(project, directory, row, document, summary):
        # 只刷新当前用例；传入已读 record，避免 refresh 内部再读一次
        self.refresh_trace_for_cases(
            row["project_id"], [case_id],
            records={case_id: self._case_record(row, document)},
        )
        summary = self.store.get_case_trace_summary(case_id) or {}

    return self._case_payload_for_target(
        project, directory, row, document, summary,
    )
```

`_summary_needs_refresh()` 的判定顺序：

1. `summary is None` 或 `summary.get("state") != "fresh"` → 需要刷新；
2. 用与 `_case_summary_row()` **同一个**输入 hash 计算函数（建议抽出 `_summary_input_hash(item, entities)`）重算当前输入：
   - 当前 case 文件 content_hash；
   - 声明的 testpoint/source 当前 content_hash；
   - 测试点再带出的 source content_hash；
3. 与 `summary["input_hash"]` 不一致 → 需要刷新；
4. 一致 → 直接使用摘要，不刷新。

注意：刷新只允许一次，不能因为刷新后仍 `stale`（例如引用缺失）而循环；第二次直接返回，payload 里保留 `needs_links`/`needs_recheck` 的真实状态。

#### 1.3.3 刷新路径复用已读文档

`refresh_trace_for_cases()` 当前通过 `_entity_candidates()` 重新探测目标 case 文件（会遍历 draft batch 目录），详情路径已经读过目标文件，应该复用。增加内部可选参数：

```python
def refresh_trace_for_cases(
    self, project_id: str, case_ids: Iterable[str], *,
    records: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
```

- `records[case_id]` 存在时直接作为目标 case record，不再 `_entity_candidates()`；
- 上游测试点/来源仍按现有定向探测读取；
- 公开调用方不传 `records` 时行为不变。

#### 1.3.4 错误与降级

| 情况 | 行为 |
|---|---|
| 目标 YAML 不可读/不存在 | 不调用 `load_project`；返回行字段 + 空链路，摘要标 `stale`；与旧路径“文档读不到时仍返回行字段”一致 |
| 引用的测试点/来源缺失 | 摘要 `stale`，`trace_testpoints` 不包含缺失项，`trace_sources` 保留直接来源；与旧全量路径一致 |
| `.qa-trace/index.json` 缺失/损坏 | `_target_recheck` 已捕获并返回 `(None, False)`；`needs_recheck` 取摘要缓存值，详情仍可用 |
| 摘要表损坏（`sqlite3.DatabaseError`） | 先 `ensure_trace_index_schema()` 修复表结构，再定向刷新；仍失败则返回明确 500，不静默回退全量 `load_project` |
| `legacy` 行 | 继续 `_legacy_payload()`，不读项目、不读 YAML |

**兼容性边界（需要验收确认）**：正常可加载的库，定向路径与旧全量路径必须逐字段完全相等。若正式库本身损坏（某个无关测试点 YAML 非法），旧路径会整体 `load_project` 失败并降级所有徽标，新路径只降级受影响的用例；这是有意的行为差异。若产品要求连损坏库也逐字段一致，需要在摘要里持久化 `library_ok` 标志（可随 v6 一起加列），详情在 `library_ok=0` 时按旧方式降级。本轮 P0 先按“正常库完全一致、损坏库记录差异”验收，不把损坏库当作阻塞项。

### 1.4 验收标准

1. **字段一致性**：对 fixture 矩阵逐字段比较旧全量 `get_case()` 与新定向 `get_case()` 的完整 dict：
   - 无链接草稿；
   - 正式且 linked（1 个测试点 + 直接来源）；
   - 测试点带来源（间接来源）；
   - 只有直接来源、无测试点；
   - 引用缺失；
   - 草稿/正式/墓碑三种位置；
   - legacy SQLite 行。
   除时间字段外必须全等；`trace_testpoints` 的 `code` 必须与旧路径一致。
2. **禁止全量加载**：monkeypatch `nanobot.qa.case_files.load_project` 抛错，普通详情仍成功；monkeypatch `CaseFiles._rechecks_for` 抛错，详情不调用它。
3. **只刷新当前用例**：准备两个无关用例，记录其 `input_hash`/`checked_at`；修改当前用例的测试点后请求详情，断言无关用例两字段不变。
4. **性能**：10,000 条项目，30 个样本（5 次预热），`CaseFiles.get_case()` p95 ≤ 200 ms；同时记录 p50/p95/max、payload 字节数、首次冷缓存一次。HTTP 端到端（WebSocket 读路由）单独记录一次。
5. **回归**：`tests/qa/test_case_files.py`、`test_trace_chain.py`、`test_trace_incremental.py`、`test_compat_rollback.py` 全绿。

### 1.5 剩余限制

- 详情成本仍与“该用例关联的测试点/来源数量”相关；一个用例挂数百个实体时会线性增加。
- 测试点编号需要拿到正式测试点全集 ID（SQL + 目录列举），是 O(测试点数)，不是 O(用例数)。
- `_target_recheck` 仍会读 `.qa-trace/index.json`；索引文件很大时这一项可能成为主要成本，需要实测。若超过预算，后续把 review baseline 落到 SQLite 或按项目缓存 index（不在本轮范围）。
- 损坏正式库的降级行为与旧路径不同，见 1.3.4；需要产品确认是否接受。

## 2. 创建编号改为索引分配（P0，与详情同批优先）

### 2.1 现状与根因

- `_known_codes()`（约 1010～1018 行）用 `iter_case_documents()` 解析**全部 case YAML**；10,000 条实测 48.6 s。
- `_resolve_code()`（约 1020～1050 行）在显式 code 分支会多次调用 `_known_codes()`，最坏解析多遍。
- `next_case_id()`（`qa_trace/caseyaml.py`，约 299～325 行）扫描 `cases/`、`draft/*/cases/`、`tombstones/` 的文件名 + `taken` 集合；只列文件名，但并发下无分配台账，可能撞号。
- `cases` 表在 v3 迁移时删掉了 `UNIQUE (project_id, code)`，因为 legacy 行与 YAML 行可以同 code；目前唯一性完全靠写路径自觉。

### 2.2 数据模型（SCHEMA_VERSION = 6）

新增“编号占用台账”，它是派生数据，可从 YAML + `cases` 表重建。legacy 行与 YAML 行允许同 code（沿用现有迁移语义），YAML 内部必须唯一。

```sql
CREATE TABLE IF NOT EXISTS case_code_claims (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    case_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'reserved',  -- reserved|draft|reviewed|deprecated
    source TEXT NOT NULL DEFAULT 'yaml',     -- yaml|legacy
    number INTEGER,                          -- 自动编号的数字后缀；自定义 code 为 NULL
    conflict INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, code, source, case_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_case_code_claims_yaml
    ON case_code_claims(project_id, code)
    WHERE source = 'yaml' AND conflict = 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_case_code_claims_case
    ON case_code_claims(project_id, case_id)
    WHERE source = 'yaml' AND case_id != '';
CREATE INDEX IF NOT EXISTS idx_case_code_claims_number
    ON case_code_claims(project_id, kind, number)
    WHERE number IS NOT NULL;

CREATE TABLE IF NOT EXISTS case_id_claims (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    module TEXT NOT NULL,
    seq INTEGER,
    state TEXT NOT NULL DEFAULT 'reserved',
    source TEXT NOT NULL DEFAULT 'yaml',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, case_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_case_id_claims_seq
    ON case_id_claims(project_id, module, seq)
    WHERE seq IS NOT NULL AND source = 'yaml';
CREATE INDEX IF NOT EXISTS idx_case_id_claims_module
    ON case_id_claims(project_id, module, seq);

CREATE TABLE IF NOT EXISTS case_claim_conflicts (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity TEXT NOT NULL,        -- code|id|path
    value TEXT NOT NULL,
    case_ids TEXT NOT NULL,      -- JSON 数组
    reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    PRIMARY KEY (project_id, entity, value)
);
```

要点：

- `case_code_claims` 的主键包含 `source` 与 `case_id`，允许 legacy 重复 code；YAML 唯一性由部分唯一索引保证。
- `number` 只对 `<PROJECT>-<KIND>-<数字>` 形式赋值，`MAX(number)` 走索引，O(log n)。
- `case_id_claims.seq` 为数字；UUID 形式的 ID 不参与数字分配（`seq = NULL`）。
- 冲突不阻塞重建：重复 code/ID 标记 `conflict=1` 并写 `case_claim_conflicts`，列表/详情仍可读；新建/改 code 遇到冲突直接 409。

### 2.3 同步过程（手工 YAML 的冲突保护）

不能只删掉 `_known_codes()`，否则手工新增但未索引的 YAML 会失去冲突保护。新增：

```python
def sync_case_claims(self, project_id: str) -> dict[str, Any]:
    """把磁盘上的 case 文件同步进编号台账，只解析新增/变化的文件。"""
```

流程：

1. 从 `store.list_trace_file_states(project_id)` 取已记录的文件 `path/mtime_ns/content_hash`；
2. 对每个已记录路径 `stat()`：
   - mtime 未变 → 跳过解析；
   - mtime 变 → 解析该文件，更新 claim 与 file state；
3. 用目录签名判断是否有新增/删除：
   - `cases/`、`tombstones/`、`draft/` 以及每个 draft batch 目录的 `mtime_ns` 组成签名；
   - 签名未变 → 不再列目录；
   - 签名变 → `case_file_paths()` 列出全部路径，只解析不在 file state 的新文件，处理删除；
4. 解析结果写 `case_code_claims`/`case_id_claims`：新增/更新/删除（删除只删除对应 claim，不删除 tombstone 的占用）；
5. 检测冲突：
   - 两个 YAML 声明同一 code；
   - 两个 YAML 声明同一 ID；
   - 文件名 stem 与声明 ID 不一致；
   - 同一路径声明不同实体；
   写入 `case_claim_conflicts`，返回 `{scanned, parsed, added, updated, removed, conflicts}`；
6. 同步不重建 cases/summary；列表内容仍由 reindex/增量刷新负责。同步只保证“编号占用”正确。

调用时机：

- `create_case()`、`update_case()`（code 变化时）、`import_cases()` 开始前；
- `reindex()` 内部重建 claim（与 cases/trace 同一事务，见第 3 节）；
- 进程内按 `(project_id, 目录签名)` 缓存同步结果，避免每次写都重复 stat 10,000 个文件；目录签名不变时只做 DB 查询。
- 首次/重启后第一次写会做一次 O(n) stat（10,000 条约 44～67 ms）和少量解析，仍远低于 500 ms 目标。

### 2.4 事务内分配

新增 store 方法：

```python
def allocate_case_identity(
    self, project_id: str, *, kind: str, code: str | None = None, count: int = 1,
) -> list[dict[str, Any]]:
    """在 BEGIN IMMEDIATE 内预留 N 个 code/ID；返回 case_id/code/claim 信息。"""
```

规则：

1. `BEGIN IMMEDIATE`（`busy_timeout` 建议 5 s），串行化同库写者；
2. 自动 code：
   - `SELECT MAX(number) FROM case_code_claims WHERE project_id=? AND kind=? AND number IS NOT NULL`；
   - 下一个 `number+1`，格式 `f"{PROJECT}-{KIND}-{number:03d}"`；
   - 插入 claim（`state='reserved'`）；`IntegrityError` → 重试整个分配，最多 5 次；仍冲突则 409；
3. 显式 code：
   - 校验 `CASE_CODE_RE`；
   - 查 `case_code_claims` 中任意 source 是否已占用（legacy 也阻止新建，保持当前行为）；
   - 插入；唯一冲突 → `QaConflictError`，错误信息带 code、已有 case_id、source；
4. 自动 ID：
   - `SELECT MAX(seq) FROM case_id_claims WHERE project_id=? AND module=? AND seq IS NOT NULL`；
   - 下一个 `TC-<MODULE>-<seq:03d>`；插入；唯一冲突重试；
5. 批量（导入）一次事务内分配 N 个，返回列表；任何一项失败整批回滚。

写文件后的确认：

- 文件写成功 → 在同一个 SQLite 事务里把 claim 从 `reserved` 改为 `draft`/`reviewed`，并 upsert 派生行/摘要；
- 文件写失败 → 删除刚预留的 claim（补偿事务）；
- 进程崩溃 → 留下 `reserved` claim；下次 `sync_case_claims()` 看到对应文件则确认，没有文件且超过 TTL（建议 10 分钟）则释放。

### 2.5 创建/更新/删除路径

- `create_case()`：
  1. `sync_case_claims(project_id)`；
  2. `allocate_case_identity(...)`；
  3. 校验/构造文档（不变）；
  4. 目标路径已存在 → **拒绝覆盖**，释放 claim，`QaConflictError` 带 `path`、已有 case 的 `id/code`（409）；
  5. 写入使用“不覆盖”语义：临时文件 + `os.link()`/`O_EXCL` 落最终路径；不要直接 `os.replace()` 覆盖已有文件；
  6. 确认 claim + `upsert_derived_case` + `refresh_trace_for_cases`；失败时保留 YAML/claim，返回可重试错误，下一次 sync/reindex 修复。
- `update_case()`：
  - code 未变：不查 `_known_codes()`，不分配；
  - code 变：`replace_code_claim(project_id, case_id, new_code)` 在事务内完成，唯一冲突 409；旧 code 立即释放（归档/墓碑仍保留占用，不释放）；
  - 状态变化导致路径移动时，目标路径已存在 → 拒绝覆盖，保持原文件不动。
- `delete_case()`：墓碑写入后把 claim `state` 改为 `deprecated`，code/ID 继续占用，永不重新分配。
- `import_cases()`：校验后批量 `allocate_case_identity(count=len(prepared))`；不再扫描 `case_file_paths()` 生成 ID。

### 2.6 迁移 v5 → v6

1. 打开库时先备份 `qa.sqlite3`/WAL（沿用现有运维建议；代码只做 additive DDL）；
2. `SCHEMA_VERSION = 6`；`_migrate()` 增加 `if version < 6:` 分支，执行 `V6_SCHEMA`（`IF NOT EXISTS`，重复启动幂等）；
3. 回填：
   - `case_code_claims`：从 `cases` 全部行回填；`derived=1` → `source='yaml'`，`derived=0` → `source='legacy'`；`state` 由 `status` 映射；`kind` 取 `cases.kind`；`number` 用正则从 code 提取；
   - `case_id_claims`：只回填 `derived=1` 且 ID 匹配 `TC-<MODULE>-<数字>` 的行；module/seq 用 `parse_id()`；
4. 重复 code 处理：
   - 回填时检测 `(project_id, code)` 的 YAML 重复；
   - 保留确定的一条（按 `case_id` 排序最小），其余 `conflict=1`，写 `case_claim_conflicts`；
   - 再创建 `WHERE conflict=0` 的部分唯一索引；这样迁移不会因历史脏数据失败；
5. 迁移不扫描 YAML。首次 create/import 的 `sync_case_claims()` 会把未索引的手工文件补进来；`reindex()` 会完整重建 claim；
6. 回滚：删除三张新表即可回到 v5 行为；`SCHEMA_VERSION` 只影响迁移分支，旧代码不读新表也能运行（但不要在生产回滚后继续用新写路径）。

### 2.7 验收标准

1. **不再解析全项目 YAML**：monkeypatch `iter_case_documents`/`_scan_project_documents` 抛错，10,000 条项目 `create_case()` 仍成功；`_known_codes` 不再被 create/update 调用。
2. **编号唯一**：两个 `QaStore` 连接（模拟两个进程）并发各创建 20 条，最终 40 条 ID/code 全部唯一，无覆盖；失败请求返回 409 而不是静默重号。
3. **手工 YAML 冲突保护**：在 `draft/other/cases/TC-...yaml` 手工放一个使用 `SHOP-API-001` 的文件，不 reindex；`create_case(code="SHOP-API-001")` 必须 409，且错误里能看出冲突文件/ID。
4. **路径已存在拒绝覆盖**：预置目标路径文件，`create_case()` 返回 409，文件内容不变。
5. **code 修改**：update 改 code 后旧 code 可被新用例使用（如果旧用例已归档则不可），新 code 立即可查；并发改同一 code 只有一个成功。
6. **归档占用**：delete 后 code/ID 仍被占用，新建同 code/同 ID 被拒绝。
7. **迁移**：v5 库（含 legacy 行 + 同 code YAML 行）升级 v6 成功；重复打开幂等；重复 code 被标记冲突而不是迁移失败；迁移后 claim 数量与 `cases` 行数一致。
8. **性能**：10,000 条项目 `create_case()` p95 ≤ 500 ms（设计目标；首次同步可单独记录），update 改 code p95 ≤ 500 ms；不再随 YAML 数量线性增长。
9. **回归**：`test_case_files.py`、`test_db_migration.py`、`test_store.py`、`test_compat_rollback.py` 全绿。

### 2.8 剩余限制

- `sync_case_claims()` 首次仍要 stat O(n) 个文件；目录签名只省掉“无变化时”的重复枚举，不能省掉内容变更检测的 stat。10,000 条约 50 ms，可接受；更大规模可再做 per-directory 缓存。
- claim 是派生台账，手工删除/移动 YAML 后需要 sync/reindex 才能释放；在同步前，旧 code 仍被占用（宁可多占用，不可重号）。
- legacy 行继续阻止新 YAML 使用同 code（保持当前语义）；如果产品希望 legacy code 可复用，需要单独确认。
- 多进程同时写同一目标路径的极端竞态，靠 `O_EXCL`/`link` 兜底；跨 NFS 等文件系统不保证原子性，本项目按本地盘验收。

## 3. 全量重建只解析一次（P1）

### 3.1 现状与根因

`CaseFiles.reindex()`（约 1737～1808 行）：

1. `_scan_project_documents(directory)` 解析所有 YAML（第 1 次）；
2. `_derived_rows()` 用扫描结果；
3. `store.replace_derived_cases()` 单独事务提交 cases；
4. `_trace_index_rows()` 内部 `load_project(directory)` 再解析正式库（第 2 次）；
5. `build_graph()` + `recheck_map()`；
6. `store.replace_trace_index()` 第二个事务提交 trace 表。

问题：

- 第 4 步是纯重复解析；
- 第 3、6 步两个事务，第二个失败/进程中断会留下 cases 新、summaries/edges 旧或空的半套索引。本次中断实测就出现过 `cases=10000, summaries=0, edges=10006` 的瞬时状态（进程继续跑完后恢复，但窗口真实存在）。

### 3.2 改动设计

#### 3.2.1 qa_trace 增加“已解析实体”入口

在 `qa_trace/loader.py` 增加（名字可调整）：

```python
def load_project_from_documents(
    root: str | Path,
    documents: Iterable[tuple[str, Path, Mapping[str, Any]]],
) -> ScanOutcome:
    """用已解析的 (entity_type, path, document) 构造 Project，不重新读文件。"""
```

- `documents` 只包含正式库实体（`batch is None`，不含 `tombstones/`、`draft/`）；
- 复用 `Source.from_dict`/`TestPoint.from_dict`/`Case.from_dict`、`_check_file_name()`、重复 ID 检查、`ProjectConfig` 校验；
- 任何实体错误 → `ScanOutcome(project=None, errors=...)`，与 `load_project()` 的失败语义一致；
- 成功 → `ScanOutcome(project=Project(...), errors=())`；
- `_load_config()` 抽出 `config_from_mapping()`，供 project.yaml 的已解析文档复用。

`_trace_index_rows()` 改为接收 `scanned` 与可选的 `project`：

```python
outcome = load_project_from_documents(
    directory,
    [
        (item["entity_type"], item["path"], item["document"])
        for item in scanned
        if item["entity_type"] in {"source", "testpoint", "case"}
        and item["batch"] is None
        and not item["relative"].startswith("tombstones/")
    ],
)
library = outcome.project if outcome.ok else None
```

这样 `reindex()` 只调用一次 `_scan_project_documents()`；`load_project()` 仍保留给其他调用方（trace API、CLI），但 reindex 不再调用。

#### 3.2.2 单事务写完整项目索引

`QaStore` 增加：

```python
def replace_project_index(
    self,
    project_id: str,
    case_rows: Iterable[Mapping[str, Any]],
    *,
    edges: Iterable[Any] = (),
    summaries: Iterable[Mapping[str, Any]] = (),
    files: Iterable[Mapping[str, Any]] = (),
    code_claims: Iterable[Mapping[str, Any]] = (),
    id_claims: Iterable[Mapping[str, Any]] = (),
    conflicts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, int]:
    """在一个 SQLite 事务里替换 cases + trace + claims，失败全部回滚。"""
```

事务内顺序：

1. `DELETE FROM trace_edges/case_trace_summary/trace_file_state WHERE project_id=?`；
2. `DELETE FROM cases WHERE project_id=? AND derived=1`（避免 FK 级联在错误时机删摘要）；
3. `INSERT` 新 cases；
4. `INSERT` 新 trace 行；
5. 重建/更新 claims 与 conflicts；
6. commit。

`reindex()` 在 `trace=True` 时调用它；`trace=False` 时仍只替换 cases（或走同一方法、trace 参数为空），保持现有首建索引行为。保留 `replace_derived_cases()`/`replace_trace_index()` 作为内部/测试兼容方法，但 reindex 不再分两次提交。

#### 3.2.3 报告与失败语义

`reindex()` 报告增加：

```json
{
  "parse": {"files": 10009, "seconds": 0.0},
  "trace": {"edges": 0, "summaries": 0, "files": 0},
  "claims": {"codes": 0, "ids": 0, "conflicts": 0},
  "atomic": true
}
```

- 任一写入失败 → 整个事务回滚，cases/trace/claims 保持旧状态；YAML 不被修改；
- 如果解析阶段有坏文件，仍按现有语义跳过并记录 warning；正式库验证失败时 `library_ok=False`，摘要标 stale，但不阻断 cases/claims 重建。

### 3.3 验收标准

1. **只解析一次**：monkeypatch `qa_trace.loader.load_project` 抛错，`reindex()` 成功；用计数器包住 `load_yaml_document`/`_load_yaml_file`，每个文件只读一次（正式实体不再被第二次读取）。
2. **原子性**：在 trace 插入阶段注入 `sqlite3.OperationalError`（trigger 或 monkeypatch），`reindex()` 失败后 cases 行数、summaries、edges 与失败前一致；不允许出现 cases 新/summaries 空。
3. **结果一致**：同一 fixture 上，reindex 后的 cases/summaries/edges/file_state 与逐条增量刷新结果逐项一致（排除 `checked_at`）。
4. **性能**：10,000 条项目记录 reindex 总耗时、解析耗时、graph/recheck 耗时、DB 写入耗时；与基线 109 s 对比并报告，不承诺固定降幅。验收只要求“只解析一次 + 原子 + 结果一致”，时间作为实测数据。
5. **回归**：`test_case_files.py::test_reindex_*`、`test_trace_incremental.py`、`test_db_migration.py` 全绿。

### 3.4 剩余限制

- 全量重建仍是 O(n)：`build_graph`、`recheck_map`/`fingerprint_project` 仍遍历全项目；解析只省掉一次重复读，不会把 109 s 直接减半。
- 没有增量 reindex；日常写入仍走定向刷新，全量重建只用于首次初始化、迁移、人工修复。
- `load_project_from_documents` 的校验必须与 `load_project()` 完全同语义，否则 reindex 和 trace API 会得出不同的库状态；需要一致性测试。

## 4. 导入模式与失败恢复（P1）

### 4.1 现状与根因

`CaseFiles.import_cases()`（约 1356～1680 行）：

- 逐项校验，非法项进 `errors`，合法项继续（兼容模式）；
- 校验通过后直接写最终 YAML 文件；
- 所有文件写完后调用 `store.apply_case_batch()` 单事务提交索引；
- 写文件或事务异常时删除本次已写文件（Python 异常清理）。

问题：

1. 没有“严格整批”模式；存在校验错误时仍会落盘合法项。
2. 不是先写临时文件再提交；进程在写文件过程中被强杀会留下部分最终文件。
3. 没有批次操作记录；断电/强杀后无法判断“文件已写、索引未写”的批次，无法自动恢复。
4. 文档/总结把“YAML 与 SQLite 一起回滚”说得过满；SQLite 事务 + Python 异常清理覆盖不了进程中断。

### 4.2 模式定义

`import_cases(project_id, payload, *, mode="compat")`，HTTP/WebSocket 的 `qa.case.import` 接受 `mode`：

| 模式 | 校验失败 | 重复 code | 落盘 | 返回 |
|---|---|---|---|---|
| `compat`（默认） | 记录 `errors`，合法项继续 | 记录 `skipped`，继续 | 只落合法项 | `created/skipped/errors` |
| `strict` | 任意一项错误 → 整批不落盘 | 视为冲突错误 → 整批不落盘 | 全有或全无 | `committed=false, created=[], errors=[...]` |

建议 `strict` 仍返回 HTTP 200 + 结构化结果（`committed=false`），而不是 409/400，便于 WebUI 展示逐项错误；`mode` 非法 → 400。

### 4.3 三阶段流程

#### 阶段 A：校验（不写文件）

- 全部条目先完成字段校验、code/ID 分配预检、链接存在性检查、目标路径检查；
- `strict`：收集所有错误；只要 `errors` 非空或出现重复/冲突 → 直接返回，不创建 journal、不写临时文件；
- `compat`：非法项进 `errors`，重复 code 进 `skipped`，其余进入 `prepared`；
- 编号分配在第 2 节的 `allocate_case_identity(count=len(prepared))` 中一次事务预留；strict 失败时释放预留。

#### 阶段 B：临时文件

- 在项目目录下建 staging：`<project>/.qa-import/<batch_id>/`（不在 `cases/`、`draft/`、`tombstones/` 扫描范围内）；
- 每个条目写 `<staging>/<case_id>.yaml`，`flush` + `fsync`；
- 写 journal（见 4.4），状态 `preparing`，manifest 记录 `case_id/code/target/temp/content_hash`；
- 任一条目写临时文件失败 → 删除 staging，释放 claim，标记 aborted，返回错误。

#### 阶段 C：提交文件 + 索引

1. 逐个检查 `target` 不存在；用 `os.replace(temp, target)`（或 `os.link` + 删除 temp）提交；
2. 所有文件提交后，`fsync` 目标目录；journal 状态 `files_committed`；
3. `store.apply_case_batch()` 在一个事务内写 cases/summaries/edges/file states + claims + journal 状态 `index_committed`；
4. 成功 → `complete`；失败 → journal 保持 `files_committed`，进入补偿/恢复（见 4.5）。

### 4.4 批次 journal（schema v6 或 v7）

如果与第 2 节同批交付，放进 v6；否则单独 v7。表：

```sql
CREATE TABLE IF NOT EXISTS case_import_batches (
    batch_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,  -- preparing|files_committed|index_committed|complete|aborting|aborted|failed
    manifest TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_import_batches_project
    ON case_import_batches(project_id, status, updated_at);
```

`manifest` 至少包含：

```json
{
  "files": [
    {"case_id": "...", "code": "...", "target": "draft/workbench/cases/TC-...yaml",
     "temp": ".qa-import/<batch>/TC-...yaml", "content_hash": "..."}
  ],
  "counts": {"prepared": 0, "skipped": 0, "errors": 0}
}
```

### 4.5 恢复规则

恢复入口：`CaseFiles._ensure_recovered(project_id)`，在 list/detail/create/update/delete/import/reindex 的入口按项目执行一次（进程内缓存）；另提供 `nanobot qa cases recover --project <KEY>` 供运维手动触发。

| journal 状态 | 恢复动作 |
|---|---|
| `preparing` | 删除 staging；删除 manifest 中 content_hash 匹配的 target（防止提交阶段中途崩溃）；释放 claim；标记 `aborted` |
| `files_committed` | 所有 target 存在且 hash 匹配 → 从 target YAML 重建 rows/summaries，执行索引事务，标记 `complete`（roll forward）；任一缺失/不匹配 → 只删除 hash 匹配的 target，标记 `aborted`（roll back） |
| `index_committed` | 标记 `complete`（文件已提交、索引已提交） |
| `aborting` | 继续删除 hash 匹配的 target 与 staging；标记 `aborted` |
| `complete`/`aborted`/`failed` | 不处理；定期清理旧记录 |

关键约束：

- 只删除 `content_hash` 与 manifest 一致的文件；用户手工改过的文件绝不删除，记录冲突并保持 `failed`。
- `files_committed` 的 roll forward 优先于 roll back：文件已经完整落盘时，重建索引比删用户文件更安全。
- 恢复本身要幂等；恢复过程中再次崩溃，下次继续。

### 4.6 三种失败要分开写文档

更新 `docs/qa-agent.md` 与 `docs/design/qa-case-storage-scaling-summary.md`，明确区分：

| 失败类别 | 保证 | 不保证 |
|---|---|---|
| 条目校验失败 | strict：本批零落盘；compat：合法项落盘、非法项返回 errors | 不涉及进程/磁盘异常 |
| 执行异常（Python 异常、SQLite 错误） | 尽力补偿删除本批文件；journal 可恢复；响应返回可重试错误 | 不保证异常发生在任意指令时都立即回到原状 |
| 进程中断（kill -9、断电） | journal + 恢复流程收敛到全有或全无；可能有一个恢复窗口 | 不保证中断瞬间文件系统与 SQLite 原子一致；不承诺“跨文件系统事务” |

禁止再写“批量导入全部原子回滚”这类笼统表述。

### 4.7 验收标准

1. **compat**：10 条中 1 条非法 → 9 条 created，1 条 errors，文件/索引一致；重复 code 进 skipped。
2. **strict**：10 条中 1 条非法 → `committed=false`，`created=[]`，磁盘无新文件、无新 cases 行；重复 code 同样整批失败。
3. **执行异常**：在写第 3 个临时文件/提交第 3 个文件/索引事务注入异常，分别验证：无最终残留文件（或 journal 标记可恢复）、cases 无半批、下次恢复收敛。
4. **进程中断模拟**：手工构造 `preparing`/`files_committed`/`aborting` 的 journal + 文件，调用恢复：
   - 全文件存在 → 索引补齐、`complete`；
   - 部分文件 → 删除本批文件、`aborted`；
   - 用户改过文件 → 不删除、记录冲突。
5. **幂等**：同一批重复导入不产生重复 case/关系；恢复重复执行无副作用。
6. **性能**：1,000 条导入 ≤ 30 s（沿用设计目标），strict 失败路径 < 1 s。
7. **写路径**：仍通过 WebSocket `qa.case.import`，HTTP dispatch 测试覆盖 `mode` 传递；UI 导入对话框可加“严格模式”开关（默认关）。
8. **文档**：三种失败类别、恢复命令、剩余窗口写清楚。

### 4.8 剩余限制

- 文件系统与 SQLite 无法组成真正的分布式事务；恢复只能保证“最终收敛”，不能保证中断瞬间的强原子性。
- `fsync` 目录在部分文件系统/容器上可能无效；验收以本地 ext4/overlay 为准。
- 恢复窗口内列表可能看不到已写文件（索引未提交），或看到 journal 未完成的批次；需要文档说明，不能把窗口内状态当作数据丢失。
- 单条 create/update 不走批次 journal（只复用 claim 确认）；如果要求单条写也覆盖断电恢复，需要把 4.4 的 journal 扩展到单条写，另行评估。

## 5. 搜索独立优化（P2，不阻塞前四项）

### 5.1 现状与根因

`QaStore._case_list_filters()`（约 1130～1175 行）的 `q`：

```sql
(c.title LIKE ? OR c.code LIKE ? OR c.tags LIKE ? OR c.expected LIKE ?)
```

四个 `%q%` 前导通配符，B-tree 索引无法使用；但列表已经只查 SQLite，文件加载的秒级延迟在上一轮已消除（10,000 条列表 p50 约 21 ms）。因此本轮先做查询计划审计和必要索引，不先上 FTS5。

### 5.2 改动设计

#### 5.2.1 查询计划审计

在 10,000 条基准库上对以下组合跑 `EXPLAIN QUERY PLAN`，记录到验收报告：

1. `project_id`；
2. `project_id + kind`；
3. `project_id + status`（含 `status != 'deprecated'`）；
4. `project_id + module_id`；
5. `project_id + operation_id`；
6. `project_id + module_id + q`；
7. `project_id + operation_id + q`；
8. `project_id + q`；
9. 分页 `ORDER BY code LIMIT 50 OFFSET N`。

判定：项目内查询不得出现 `SCAN cases`（全表扫描）；`EXISTS` 子查询必须走索引；分页排序尽量走索引，避免临时 B-tree。

#### 5.2.2 按计划补索引（候选）

现有：`idx_cases_project`、`idx_cases_kind`、`idx_cases_project_status_code`、`idx_cases_project_kind_status_code`、`idx_cases_project_code`、`idx_cases_project_kind_code`。

候选新增（以实测计划为准，不盲加）：

```sql
CREATE INDEX IF NOT EXISTS idx_case_trace_summary_project_module
    ON case_trace_summary(project_id, module_id, case_id);
CREATE INDEX IF NOT EXISTS idx_api_case_metadata_operation
    ON api_case_metadata(operation_id, case_id);
CREATE INDEX IF NOT EXISTS idx_trace_edges_source
    ON trace_edges(project_id, to_type, to_id, from_type);
```

注意：`module_id`/`operation_id` 目前用 `EXISTS` 过滤，索引应建在子查询表上；`cases(project_id, status, code)` 对 `status != 'deprecated'` 只能部分利用，必要时改成 `status IN (...)` 或接受小范围扫描。

#### 5.2.3 保留 q 语义

- 不改 `%q%` 子串语义；
- 不把 `q` 拆成多个字段的 AND/OR 变化；
- 不改变大小写、标签 JSON 文本、expected 的匹配行为；
- 结果排序仍按 `code`。

#### 5.2.4 FTS5 单独实施（有门槛）

只有在 5.2.1/5.2.2 完成后，10,000 条 `q` 查询仍超过列表目标（建议 P95 ≤ 300 ms）才实施 FTS5，且单独 PR、默认关闭（`QA_CASE_FTS=1` 开启）。规则先定死：

| 查询形态 | 处理 |
|---|---|
| 查询字符数 < 3 | 走 LIKE（trigram 无法覆盖短串） |
| 含 FTS5 操作符/引号/纯标点/空白 | 走 LIKE |
| 中文 ≥3 字 | trigram FTS；与 LIKE 结果集逐条对比 |
| code 子串 ≥3 字符 | trigram FTS；与 LIKE 对比 |
| tags/expected 子串 | 若 FTS 只索引 title/code，则这些字段仍走 LIKE 并 union；不能保证等价就整体回退 LIKE |
| FTS 表缺失/版本不匹配/损坏 | 自动回退 LIKE，不报错 |

实现要点：

- `case_search_fts` 用 `fts5(..., tokenize='trigram')`（本机 SQLite 3.45.1 已支持）；`case_id UNINDEXED` 保留映射；
- 在 reindex/upsert/delete/import 的同一事务维护；提供重建入口；
- 固定查询集对比：中文 1/2/3/4 字、code 前缀/中缀、标签、expected、标点、空串，要求 FTS 与 LIKE 的 ID 集合完全一致；不一致的查询回退 LIKE；
- 搜索始终查 SQLite，不触发 YAML 解析（测试 monkeypatch `_scan_project_documents`/`load_project` 抛错）。

### 5.3 验收标准

1. `EXPLAIN QUERY PLAN` 记录完整；项目内查询无 `SCAN cases`；新增索引确实被使用。
2. 固定查询集（≥30 条）在旧 LIKE 与新路径下结果集完全一致（FTS 开启时）。
3. 10,000 条列表：project-only、module、operation、q（中文 2 字/3 字、code 子串）各 20 个样本，p95 记录；不劣于当前 p50 21 ms 的一个合理上限（建议 ≤300 ms）。
4. 搜索路径不读 YAML：monkeypatch 全量扫描/`load_project` 抛错，列表/搜索成功。
5. FTS5 若未实施，明确写“本轮不启用”，不能以“已加索引”暗示搜索问题全部解决。

### 5.4 剩余限制

- 前导通配符 LIKE 仍无法用 B-tree；无 FTS 时，大项目内的 `q` 仍是项目子集扫描。
- tags 是 JSON 文本，LIKE 可能匹配到 JSON 标点/键名；这是现有语义，FTS 不能悄悄改变。
- trigram 对 1～2 字中文、emoji、组合字符的覆盖有限；不能保证与 LIKE 完全等价时继续用 LIKE。
- FTS 索引会增加写放大和库体积，必须单独度量后再决定是否默认开启。

## 6. 分页与筛选同步 URL（P2，最后完成）

### 6.1 现状与根因

`webui/src/components/qa/QaCaseLibrary.tsx`（约 320～388 行）用组件 state 保存 `projectId/kind/status/moduleId/operationId/page/search`；搜索已有 250 ms 防抖，筛选变化会回第一页，但：

- 刷新页面回到默认；
- 浏览器前进/后退不恢复；
- 无效参数/越界页码没有 URL 级纠正；
- `QaWorkbench` 的 tab 也不在 URL，刷新后即使 URL 带筛选也回不到用例库。

### 6.2 URL 契约

```text
#/qa?tab=cases&project=<project_id>&module=<module_id>&operation=<operation_id>
     &kind=<api|ui|manual>&status=<draft|ready|deprecated>&q=<text>&page=<1-based>
```

规则：

- 默认值省略：`project=all`、`module=all`、`operation=all`、`kind=all`、`status=all`、`q` 空、`page=1`；
- 内部 `page` 仍 0-based，URL 用 1-based；
- 保留 hash 中未知参数，不覆盖 `chat`/`section` 等其他键；
- 写入用 `history.pushState`（筛选/页码变化）与 `history.replaceState`（初始化纠正、越界回第一页/末页）；不触发整页导航。

### 6.3 改动设计

1. **抽纯函数**（建议 `webui/src/components/qa/qa-case-url.ts`）：
   - `readCaseLibraryUrl(hash)` → 原始参数；
   - `validateCaseLibraryUrl(raw, projects, facets, pageCount)` → 合法状态 + 纠正列表；
   - `writeCaseLibraryUrl(state, {replace})` → 更新 hash query，保留其他键。
2. **QaCaseLibrary 初始化**：从 URL 读状态；project 不在项目列表 → `all`；module/operation 不在 facets → `all`；kind/status 非法 → `all`；page 非正整数 → 1；q 超长（建议 200 字符）截断；纠正后用 `replaceState` 写回。
3. **状态 → URL**：筛选/页码变化时 `pushState`；搜索只在 `debouncedSearch` 变化后写一次，输入过程不写 URL、不发请求。
4. **URL → 状态**：监听 `popstate`/`hashchange`，解析并 `setState`；用 `suppressUrlWrite` ref 防止“读 URL → 写 URL”回环。
5. **页码纠正**：`total` 变化后 `page >= pageCount` → 设为 `pageCount-1`，`replaceState`；`total=0` → page 1。
6. **筛选重置**：project 变化清空 module/operation/page；kind/status/module/operation/q 变化回 page 1。
7. **QaWorkbench tab**：`tab` 写入同一 hash query；初始化时从 URL 读 `tab`，默认 `overview`；这样刷新 `#/qa?tab=cases&...` 能直接回到用例库。`App.tsx` 的 `readShellRoute()` 已忽略未知 query 参数，不需要改路由类型；但 `writeShellRoute()` 不能覆盖 QaWorkbench 写的参数，QaWorkbench 直接操作 history。
8. **无效参数**：不抛错、不白屏；纠正到默认并 `replaceState`，在 URL 中留下合法值。

### 6.4 验收标准

1. **刷新恢复**：带 `project/module/operation/kind/status/q/page` 的 URL 刷新后，筛选、页码、请求参数一致；`tab=cases` 时直接显示用例库。
2. **前进/后退**：连续改筛选/页码后，浏览器后退恢复上一组筛选和页码；前进恢复；不产生重复请求。
3. **筛选回第一页**：从第 3 页改 kind/status/module/operation/q，页码回 1，URL 同步。
4. **无效参数**：`project=不存在`、`kind=xxx`、`page=0/-1/abc`、`module=不存在` 均纠正为合法值并 `replaceState`，页面正常。
5. **越界页码**：`page=999` 且总数只有 2 页 → 自动落到第 2 页并改写 URL。
6. **搜索防抖**：快速输入 5 个字符只发 1 次请求（250 ms 后），URL 只在防抖值提交时更新。
7. **测试**：vitest + jsdom 覆盖上述场景；`npx tsc -p tsconfig.build.json --noEmit` 通过。

### 6.5 剩余限制

- 每次筛选/翻页都 `pushState` 会让浏览器历史变长；如果产品不喜欢，可改成 replaceState，但会牺牲“后退恢复上一组筛选”。本轮按需求保留 push。
- 详情抽屉的选中用例不写入 URL（需求未要求）；刷新后详情关闭。
- QaWorkbench 的 tab 必须一起改，否则刷新无法回到用例库；这是 `QaCaseLibrary.tsx` 之外的必要的配套改动。
- 多标签页同时改同一 hash 时以最后写入为准，不做跨标签同步。

## 7. 跨入口验收矩阵（本轮完成的判定）

| 入口 | 必测场景 | 通过标准 | 证据 |
|---|---|---|---|
| 列表 | 10,000 条，project/module/operation/kind/status/q/分页 | P95 ≤ 300 ms；50 条响应 ≤ 120 KB；不读 YAML；字段/徽标与旧摘要契约一致 | pytest + 基准脚本 + `EXPLAIN` |
| 详情 | 草稿/正式/墓碑、linked/unlinked、直接/间接来源、引用缺失、legacy | 与旧全量 `get_case()` 逐字段一致（正常库）；P95 ≤ 200 ms；不调用 `load_project` | 对比测试 + 基准 |
| 创建 | 自动 code/ID、显式 code、并发、路径已存在、手工 YAML 冲突 | 10,000 条 p95 ≤ 500 ms；编号唯一；不解析全项目 YAML；冲突 409 不覆盖 | pytest + 并发测试 + 基准 |
| 更新 | 改 title/status/code/links；code 冲突；状态移动路径 | 改 code 不扫描 YAML；响应与详情一致；并发唯一；路径冲突不覆盖 | pytest + 基准 |
| 导入 | compat/strict、非法项、重复 code、执行异常、崩溃恢复、1,000 条 | strict 零落盘；compat 合法项落盘；恢复收敛；≤30 s；幂等 | pytest + 故障注入 + 基准 |
| 重建 | 10,000 条 reindex、解析次数、事务失败回滚、增量一致性 | 只解析一次；单事务全回滚；结果一致；报告实测耗时 | pytest + 计数 + 基准 |
| 搜索 | 查询计划、固定查询集、中文/code/短串、FTS 开关 | 语义不变；无 `SCAN cases`；不读 YAML；FTS 不一致回退 LIKE | `EXPLAIN` + 对比测试 |
| 前端 | 刷新/前进/后退/无效参数/越界/防抖 | 状态与 URL 一致；无重复请求；tsc/vitest 通过 | vitest + 手工浏览器 |

硬性判定：

- 同一轮验收必须同时覆盖列表、详情、创建、更新、导入；任何一项未通过，本轮不完成。
- 不能用“详情已优化，创建下一轮”作为整体完成结论；允许分 PR，但最终验收按整轮。
- 每项都要有可复现命令和输出，不以口头描述替代。

## 8. 验收执行方式（我负责）

### 8.1 前置

1. 实施方先把当前工作区（`f1e31f9` + 未提交改动）提交为基线，或在验收报告中记录 `git diff` 的 SHA-256；避免本轮改动与上一轮混在一起。
2. 只在 `/opt/worktrees/qa-case-storage-scaling` 操作；不碰 `/opt/qa-agent` 生产库和 YAML，不重启、不部署。
3. 使用 `/opt/qa-agent/.venv/bin/python`；WebUI 依赖临时软链 `/opt/qa-agent/webui/node_modules`，验收后删除软链。

### 8.2 自动化回归

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

另跑 Ruff / ESLint / `git diff --check`（沿用仓库现有命令）。

### 8.3 性能验收（一次性脚本，不建平台）

使用 `/tmp/qa-growth` 现有 fixture 和 `/tmp/qa-growth/bench` 基准库；脚本放 `/tmp`，不提交仓库：

- 详情：10,000 条，5 次预热 + 30 次采样，输出 p50/p95/max；
- 创建：10,000 条，10 次采样（每次用独立新 code/ID），输出 p50/p95/max；
- 更新：改 title / 改 code 各 10 次；
- 列表/搜索：project-only、module、operation、q 中文 2/3 字、code 子串各 20 次；
- 导入：1,000 条 compat/strict 各一次；
- 重建：10,000 条 reindex 3 次，记录总耗时/解析耗时/事务耗时；
- 冷缓存单独记录一次（重启 Python 进程，不清 OS cache）。

脚本只做测量，不写生产路径；输出 JSON + 表格，作为验收证据。

### 8.4 入口级验收

- 读路径：HTTP GET `/api/qa/cases`、`/api/qa/cases/<id>`（通过 `QaApi.dispatch` 测试辅助）。
- 写路径：必须走 WebSocket mutation 路径（`qa.case.create/update/delete/import`），不能只测 `CaseFiles` 直调；用 `tests/qa/test_http.py` 的 `make_request`/dispatch helper。
- 每个入口至少覆盖成功、校验失败、冲突三类；导入额外覆盖执行异常和恢复。

### 8.5 验收输出

一份验收记录（可追加到本文或单独 `docs/design/...-acceptance.md`）包含：

- 环境、commit/diff hash、fixture 路径；
- 每个矩阵项的通过/失败、证据命令与关键输出；
- 性能表（p50/p95/max、payload 字节、解析次数、事务次数）；
- 剩余限制与未覆盖项；
- 结论：整轮通过 / 不通过（不允许“部分通过”作为完成）。

## 9. 实施方交付要求

每个 PR/提交必须附一段说明，至少包含：

1. **改动文件与函数**：具体到 `case_files.py`/`store.py`/`qa_trace/loader.py`/`http.py`/`QaCaseLibrary.tsx` 的函数名；
2. **数据迁移**：schema 版本、回填、幂等、失败处理；
3. **测试**：新增/修改的测试名与覆盖场景；
4. **实测数据**：改动前/后的 p50/p95、解析次数、事务次数、导入耗时；
5. **剩余限制**：不能只说“已优化”，要写清楚哪些路径仍慢、哪些异常不覆盖；
6. **回滚**：feature flag / 删除派生表 / 恢复 DB 的步骤。

建议提交拆分：

```text
PR1  detail: get_case targeted read + shared payload + tests + benchmark
PR2  allocation: schema v6 claims + sync + transactional allocation + create/update/import
PR3  reindex: parse once + single transaction + tests
PR4  import: compat/strict + journal + recovery + docs
PR5  search: query plan audit + indexes (+ FTS5 only if gated in)
PR6  webui: URL state + tab + tests
```

PR2 与 PR4 的 schema 可以合并为一个 v6；如果分开交付，PR2 = v6（claims），PR4 = v7（import batches），两者都必须幂等。

## 10. 风险与需要确认的点

1. **strict 的重复 code 语义**：本文按“冲突错误、整批失败”处理；如果产品希望 strict 下重复 code 也 skip，需要改判定。
2. **strict 的响应形态**：本文建议 HTTP 200 + `committed=false`；如果调用方期望 409，需要统一。
3. **legacy code 占用**：本文保持“legacy 行阻止新 YAML 使用同 code”；迁移场景由 reindex 直接写 YAML 绕过 create，不受影响。若希望 legacy code 可复用，需单独确认。
4. **损坏正式库的详情一致性**：旧路径整体降级、新路径只降级受影响用例；若必须逐字段一致，需在摘要加 `library_ok` 并按旧方式降级。
5. **FTS5 是否本轮启用**：本文建议先测后定；若启用，必须接受 trigram 对短中文/标点/组合字符的兼容规则和 LIKE 回退。
6. **URL 历史长度**：pushState 每次筛选/翻页都留历史；如果产品要求短历史，改为 replaceState 会牺牲“后退恢复筛选”。
7. **多进程写**：SQLite `BEGIN IMMEDIATE` + 唯一索引可以防重号；跨进程文件覆盖靠 `O_EXCL`/`link`，NFS 等文件系统不保证，需确认部署形态。
8. **性能目标**：详情 10,000 条 P95 ≤ 200 ms 是用户明确目标；创建/更新沿用设计文档 500 ms；列表 300 ms。若实测超标，按项报告，不用平均值掩盖。
