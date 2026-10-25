# QA 用例库存储与查询扩展性草案

- 状态：已实施（2026-10-25）；实施总结见 [qa-case-storage-scaling-summary.md](qa-case-storage-scaling-summary.md)
- 测量日期：2026-10-22
- 范围：`nanobot/qa/`、`qa_trace/`、`webui/src/components/qa/`、`webui/src/lib/qa-api.ts`
- 测量原则：只读复制线上 SQLite；YAML 和增长副本均在 `/tmp`；没有修改 `/opt/qa-agent`、线上库或服务

## 项目背景与材料

### 项目背景

QA-Agent 的用例库服务于接口测试、需求追溯和复核管理。一个用例不仅包含 API 请求、步骤和预期结果，还需要关联测试点和需求来源，以便回答以下问题：

- 这个用例验证了哪些测试点？
- 这些测试点来自哪些需求？
- 某个需求变更后，哪些用例需要重新检查？
- 某个测试点失败或废弃后，哪些用例会受到影响？

因此，追溯链是产品能力，不应为了性能被删除。当前问题是追溯计算和用例查询耦合在一起：请求一条用例或一页列表时，可能先加载整个项目的追溯文件，再构建项目级关系图和复核结果。

### 当前存储边界

本方案只覆盖 QA-Agent 的以下目录和模块：

```text
nanobot/qa/                         用例文件、派生索引、写入路径
qa_trace/                           追溯项目加载、关系图、复核计算
webui/src/components/qa/            用例库和 API 资产页面
webui/src/lib/qa-api.ts             WebUI QA 请求封装
```

明确不改动：

```text
nanobot agent/runtime/transcript     agent、运行时和 transcript 核心
```

### 当前材料和事实

现有设计不是“所有用例放在一个 JSON 文件”，而是：

```text
YAML 文件：用例源数据，可 review、可 diff、可提交 git
SQLite：YAML 的派生索引，用于列表、过滤和查询
追溯文件：测试点、需求来源及其关系
```

部署机只读测量材料如下：

| 材料 | 用途 |
|---|---|
| `nanobot/qa/case_files.py` | YAML 与旧 JSON 形状的映射、列表/详情读路径、写入和 reindex |
| `nanobot/qa/store.py` | SQLite `cases`、revision、列表查询和派生索引重建 |
| `qa_trace/loader.py` | 项目追溯文件加载 |
| `qa_trace/graph.py` | 追溯关系图构建 |
| `qa_trace/staleness.py` | 复核状态和 hash 变化计算 |
| `webui/src/lib/qa-api.ts` | WebUI 用例请求 |
| `webui/src/components/qa/QaCaseLibrary.tsx` | 用例列表和详情交互 |
| `tests/qa/`、`webui/src/tests/qa-*.test.tsx` | 现有兼容性和行为测试 |

已测基线：约 30 个 YAML 文件 120 KB；`cases` 表 42 行 28.8 KB；现场 `api_case_revisions.snapshot` 22 行约 15 KB。增长副本测得 `load_project` 约为 20 条 110 ms、200 条 1,004 ms、1,000 条 5,010 ms、10,000 条约 50 秒。完整列表/详情请求在 1,000 条约 5.3 秒，10,000 条单次观测约 51 秒；SQLite 单独查询只有毫秒到几十毫秒级。

本方案的判断依据是：首要瓶颈是每次请求的全项目 YAML 读取和解析，其次是完整字段传输以及写入时全量 reindex；磁盘体积暂时不是首要瓶颈。

## 结论先行

当前文件体积还不是问题。按现场 case YAML 平均约 1.07 KB 估算，10,000 条约 10.7 MB；SQLite 派生表在同一 fixture 上约 11.4 MB。真正会先失控的是读写路径：`CaseFiles.list_cases/get_case` 在查索引前后都会加载项目、构建链路、计算复核状态，并重新读取返回的 YAML。1,000 条时列表和详情约 5.3 秒；10,000 条单次观测约 51 秒。

写路径更严重。`import_cases` 循环调用 `create_case`，每条都做全项目 `reindex`。20、50、100 条导入实测分别为 1.27 秒、7.46 秒、29.09 秒，按 `O(n²)` 拟合，1,000 条约 48 分钟（这是外推，不是假装成实测）。

推荐保留“一用例一 YAML 文件 + SQLite 派生索引”，分阶段做四件事：

1. 列表先返回 SQLite 摘要，详情才读 YAML；链路徽标按需计算，并给链路结果加有失效条件的进程内缓存。
2. 单条写入做派生行 upsert；批量导入写 YAML 后在一个事务中批量 upsert，最后按需做一次一致性校验。
3. 给过滤列和稳定排序建索引；标题和代码使用 FTS5，tags 先保留 JSON/LIKE 兜底，确认查询语义后再拆规范化表。
4. revision 先保留最近 N 个完整快照（建议默认 20），不在第一阶段引入 diff 格式；大块 `api` 拆表或引用目录推迟到体积证据超过阈值后。

## 面向用户目标的简化方案

用户需要的是：打开任意用例时，能够看到它关联的测试点、需求来源和追溯状态，并且后续可以按模块、接口或测试点管理。这个目标应当保留。优化对象是“什么时候计算、计算多少、结果是否复用”，不是取消追溯链。

### 为什么当前追溯链会耗资源

当前列表和详情请求的路径近似如下：

```text
请求一个用例或一页列表
  -> load_project() 扫描并解析项目追溯文件
  -> build_graph() 构建项目级关系图
  -> recheck_map() 计算用例是否需要重新复核
  -> SQLite 查询用例
  -> 再读取返回用例的 YAML，组装完整响应
```

追溯关系是项目级的，所以当前实现为了判断一条用例的链路状态，会先把同一项目的追溯数据整体加载。`build_graph()` 本身目前只占毫秒级；主要耗时是前面的 YAML 文件打开、解析和对象构建。项目越大，即使页面只显示 20 条，前置工作仍可能处理几百或几千条文件。

因此要保留“每个用例可查测试点/需求”，但将链路结果拆成两类：

- 列表只读取已保存的链路摘要，例如 `needs_links`、`needs_recheck`、关联数量和 `trace_status`。
- 点击用例时读取单条 YAML，并返回完整的 `testpoints`、`sources`、`trace_testpoints`、`trace_sources` 和复核原因。

### 推荐方案

1. **YAML 继续作为真源**：一用例一 YAML，可 review、可 diff；目录可按“模块/接口/cases”组织，但查询依赖稳定的 `module_id`、`operation_id`。
2. **SQLite 只做派生查询索引**：列表只查摘要字段，详情再读取单条 YAML；不再为了列表先加载整个项目。
3. **保存追溯摘要**：在 SQLite 中保存 `needs_links`、`needs_recheck`、`recheck_reasons`、`trace_status`、`trace_input_hash`、`trace_checked_at`。列表直接读摘要，详情发现 hash 过期时再重新计算。
4. **缓存项目图和用例结果**：项目图缓存用于避免重复解析；用例级摘要用于避免重复组装。YAML、测试点、需求来源或 trace 索引变更时，只让受影响用例的摘要失效。
5. **写入增量更新**：新增或修改一条 YAML 后只 upsert 对应派生行；批量导入在一个事务中批量 upsert。保留 `reindex(project)` 作为初次建索引、手工修改后的修复和迁移工具。
6. **前端分页和详情分离**：列表默认 50 条，只返回摘要；点击后加载完整用例和链路详情。导出仍使用完整格式。
7. **按模块/接口/测试点筛选**：结构化条件走 SQLite 索引；标题和 code 后续再加 FTS5，保留 `LIKE` 兜底。这样“在某个模块内搜索”不会触发全项目 YAML 解析。

### 追溯结果的失效规则

摘要不是新的真源，只是可重建的派生数据。以下变化必须使相关摘要失效：

- 用例 YAML 被修改、新增、删除或重命名；
- 测试点、需求来源或其关联关系被修改；
- `.qa-trace/index.json` 或 review 状态变化；
- 执行 `reindex` 或 schema 版本升级。

失效时列表可以显示 `stale`/`unknown`，详情或后台任务重新计算；计算成功后写回新的 hash 和链路摘要。即使摘要损坏，也能从 YAML 和追溯文件完整重建，不影响用例数据本身。

### 实施顺序

```text
第一阶段：列表摘要与详情分离
第二阶段：单条 upsert、批量事务
第三阶段：追溯摘要、项目图缓存和失效机制
第四阶段：模块/接口筛选与前端分页
第五阶段：FTS5 搜索和 revision 保留策略
```

核心结果是：每个用例仍然可以查看完整测试点、需求和链路；但普通列表、筛选和搜索不再为每次请求重新处理整个项目。

## 目标规模与 SLO（建议）

目标规模取 10,000 条/项目，另以 1,000 条作为导入和迁移验收规模。以下是单实例、6 vCPU/8 GB 主机、热缓存、P95 的建议目标；冷启动、网络传输和真实链路数量需要在实现阶段复测。

| 操作 | 100 条 | 1,000 条 | 10,000 条 | 口径 |
|---|---:|---:|---:|---|
| 列表 P95 | ≤200 ms | ≤250 ms | ≤300 ms | 摘要字段，单页 50 条，支持 `offset` 或 cursor |
| 详情 P95 | ≤150 ms | ≤150 ms | ≤200 ms | 单条完整 YAML；不把整个项目加载作为前置 |
| 单条 create/update P95 | ≤300 ms | ≤400 ms | ≤500 ms | YAML 原子写 + 单行索引更新；链路校验不超过预算 |
| 导入 1,000 条 | - | ≤30 s | ≤30 s | 单事务批量写；失败可重试且不重复 |
| 列表响应体 | ≤120 KB | ≤120 KB | ≤120 KB | 50 条摘要；详情字段不随列表传输 |
| 活跃 YAML + 派生库 | ≤0.5 MB | ≤5 MB | ≤50 MB | 不含 runs/report 和历史归档 |

这些是工程目标，不是现状保证。若产品确认 WebUI 必须一次渲染 200 条，列表体积目标应单独放宽，但后端仍应分页，避免 10,000 条全量导出误走列表接口。

## 现状测量

### 数据体积

用户提供的线上基线为 30 个 YAML 约 120 KB、`cases` 42 行 28.8 KB、`api_case_revisions.snapshot` 22 行 15 KB、`runs.report` 5 行 33.5 KB。本次在部署机复制的 SQLite 是 307,200 bytes；其中 `cases` 42 行（20 个 YAML 派生行、20 个 legacy 行、TRY 项目 2 行）。当前工作区的 `cheyicha-api` 是未跟踪目录，20 个 case YAML 为 21,372 bytes，项目文件（不含 `.qa-trace/index.json`）为 24,136 bytes；这不是用户基线的同一份精确快照，不能混为一个数字。

用当前 YAML 模板生成唯一副本，得到以下增长曲线：

| 用例数 | case YAML | 项目文件 | `load_project` | 派生 SQLite 文件 |
|---:|---:|---:|---:|---:|
| 100 | 106.8 KB | 109.5 KB | 506 ms | 286.7 KB |
| 1,000 | 1.07 MB | 1.07 MB | 4,908 ms | 1.33 MB |
| 10,000 | 10.68 MB | 10.70 MB | 50,329 ms | 11.45 MB |

因此，按这份 fixture 的当前字段分布，100/1,000/10,000 条的活跃源文件 + 派生库约为 0.39/2.40/22.15 MB。`api_case_revisions.snapshot` 不在上述派生库增长副本中：现场 22 个快照合计 14,982 bytes，平均约 681 bytes；若每条用例只保留一个快照，额外约为 68 KB/681 KB/6.8 MB，若每条保留 20 个完整快照，则约为 1.4/13.6/136 MB。实际值取决于 `api` 请求体和断言长度；`runs.report` 也应单独按保留周期核算，不能并入用例库体积。

SQLite `dbstat` 在 10,000 条时显示：`cases` 表 10.33 MB，主键索引 0.34 MB，`idx_cases_kind` 0.34 MB，`idx_cases_project` 0.29 MB；其他空表和页约 0.15 MB。这个比例来自当前 JSON 字段分布，不能当作所有项目的上限。

当前完整列表响应约 1,862 bytes/条（用户现场测得约 2.3 KB/条）；因此 200 条约 372 KB，WebUI 当前 `limit: 200` 的请求不会随着项目到 10,000 条而变成 10,000 条，但每一页仍携带完整 `api`、steps、expected 和链路字段。

### 读路径和 profile

当前代码位置：

- `CaseFiles.get_case/list_cases`：[`nanobot/qa/case_files.py:429`](/opt/qa-agent/nanobot/qa/case_files.py:429)、[`nanobot/qa/case_files.py:453`](/opt/qa-agent/nanobot/qa/case_files.py:453)
- 链路加载和复核：[`nanobot/qa/case_files.py:351`](/opt/qa-agent/nanobot/qa/case_files.py:351)、[`nanobot/qa/case_files.py:362`](/opt/qa-agent/nanobot/qa/case_files.py:362)
- SQLite 列表：[`nanobot/qa/store.py:918`](/opt/qa-agent/nanobot/qa/store.py:918)
- 每行 YAML 文档读取：[`nanobot/qa/case_files.py:226`](/opt/qa-agent/nanobot/qa/case_files.py:226)

`cProfile` 对 1,000 条列表的结论是：1,009 个 YAML 文件读取和 YAML parser/scanner/composer 占累计时间绝大部分；`build_graph` 约毫秒级，`recheck_map` 约 159 ms；SQLite 查询不是主因。分阶段实测：

| 用例数 | `load_project` | graph | `recheck_map` | 返回 20 个 YAML 再读 |
|---:|---:|---:|---:|---:|
| 20 | 109 ms | 0.04 ms | 2.7 ms | 103 ms |
| 200 | 1,000 ms | 0.3 ms | 44.5 ms | 95.8 ms |
| 1,000 | 4,853 ms | 1.9 ms | 158.9 ms | 98.2 ms |

请求形状的现状观测（前 1,000 条有 5 个样本；10,000 条只有 1 个样本，不能称为严格统计 P95）：

| 用例数 | `list_cases` P95 | `get_case` P95 | SQLite 仅查派生索引 |
|---:|---:|---:|---:|
| 20 | 241 ms | 221 ms | 0.86 ms |
| 100 | 778 ms | 579 ms | 1.00 ms |
| 200 | 1,138 ms | 1,127 ms | 0.95 ms |
| 1,000 | 5,310 ms | 5,395 ms | 1.67 ms |
| 10,000 | 51,832 ms（单次） | 51,265 ms（单次） | 39.73 ms（单次） |

复现读路径：

```bash
cd /opt/qa-agent
.venv/bin/python /tmp/qa_case_storage_measure.py
.venv/bin/python /tmp/qa_case_read_measure.py
```

增长副本为 `/tmp/qa-growth/{20,100,200,1000,10000}`；生成方式是复制 `qa-workbench/projects/cheyicha-api`，只改写每个 YAML 的 `id/code/legacy_id`。所有副本均不写线上路径。

### SQLite 查询计划和搜索

当前只有 `idx_cases_project(project_id)`、`idx_cases_kind(project_id, kind)`。在 live 副本上：

```text
SEARCH c USING INDEX idx_cases_kind (project_id=?)
CORRELATED SCALAR SUBQUERY ... SCAN d
USE TEMP B-TREE FOR ORDER BY
```

原因是 `_CASE_VISIBLE` 的 legacy 去重用了相关 `NOT EXISTS`，且没有覆盖 `project_id/code/status` 的索引。单条主键查询使用主键索引，SQLite 查询本身不是详情瓶颈。

当前 `LIKE '%q%'` 在 10,000 条副本上的 SQLite-only 观测约 17–45 ms，1,000 条约 1.3–1.9 ms；但 `CaseFiles` 仍会先加载全项目，因此用户看到的搜索延迟仍接近列表延迟。`LIKE` 无法利用前缀索引，且 tags/expected 是 JSON/文本字段；FTS5 应作为标题/代码全文搜索的后续优化，不能替代摘要列表和分页。

### 写入、导入和写放大

写路径位置：

- `create_case/update_case` 写 YAML 后调用 `reindex`：[`nanobot/qa/case_files.py:587`](/opt/qa-agent/nanobot/qa/case_files.py:587)、[`nanobot/qa/case_files.py:674`](/opt/qa-agent/nanobot/qa/case_files.py:674)
- `import_cases` 在循环内调用 `create_case`：[`nanobot/qa/case_files.py:826`](/opt/qa-agent/nanobot/qa/case_files.py:826)
- `replace_derived_cases` 是项目级 DELETE + 全量 INSERT：[`nanobot/qa/store.py:970`](/opt/qa-agent/nanobot/qa/store.py:970)

隔离副本实测单条 update（含当前 reindex 和写后详情读取）：

| 用例数 | 初始 reindex | 3 次 update |
|---:|---:|---:|
| 20 | 105 ms | 460 / 467 / 472 ms |
| 100 | 508 ms | 2,070 / 2,091 / 2,018 ms |
| 1,000 | 5,164 ms | 20,253 / 20,685 / 19,862 ms |

隔离副本批量导入（每条都全量 reindex）：

| 导入量 | 实测耗时 | 成功 |
|---:|---:|---:|
| 20 | 1.27 s | 20 |
| 50 | 7.46 s | 50 |
| 100 | 29.09 s | 100 |

用 `t/n²` 检查三点均约 3 ms/条²，因此 1,000 条约 2,900 s，即 48 分钟量级；这是同一机器和 fixture 的工程外推，实施前要用批量方案实测替代。当前每次项目重建还会造成索引页和 SQLite WAL 写放大；不能仅用最终数据库大小衡量磁盘写入量。

revision 当前把完整 JSON 放进 `api_case_revisions.snapshot`（[`nanobot/qa/store.py:1745`](/opt/qa-agent/nanobot/qa/store.py:1745)）。这在几十条时只有 15 KB，但如果每条 10 KB 的 `api` 保存 20 个 revision，1,000 条就是约 200 MB 历史内容；这是归档策略问题，不是活跃列表的首要瓶颈。

## 方案对比

| 方案 | 预估收益 | 成本 | 兼容性与风险 | 建议 |
|---|---|---|---|---|
| 列表只读 SQLite 派生摘要；详情读 YAML | 1,000/10,000 条列表从秒级降到 SQL + 传输级；响应可降 5–10 倍 | 增加 summary/detail 两个内部 payload 形状；链路徽标需要按需或缓存 | 公开 JSON 契约可保持完整形状：HTTP `detail=full` 或详情接口继续返回旧形状；缓存失效必须绑定 YAML mtime/hash、reindex 和 trace 文件变化 | **第一阶段必须做** |
| 过滤/排序索引 | 项目+status/kind/code 的查询和 count 稳定；消除排序临时 B-tree | 添加复合索引、迁移和 `EXPLAIN` 验收 | SQLite 文件增加约每行几十到一百字节；legacy/derived 可见性仍需正确 | **第一阶段做** |
| FTS5 标题/代码 | 10,000 条搜索从全扫描变为索引；前缀/词搜索更可控 | 建 FTS 虚表和同步触发/批量刷新；中文分词语义需定 | `LIKE` 的任意子串语义不完全等价；保留 LIKE 兜底，不能改变旧查询结果 | 第二阶段 |
| 单条 derived upsert；批量导入单事务 | update 从 O(n) 降为 O(1)；1,000 条导入从约 48 min 降到 YAML 写入 + 一次事务，目标 ≤30 s | 处理删除/改名/手改 YAML 的一致性；批量失败要回滚并可重试 | 旧 `derived=0` 行保留；`replace_derived_cases` 继续作为全量修复命令 | **第一阶段必须做** |
| `api.request/assertions` 拆表 | 列表索引更小；大 payload 只在详情加载 | 迁移、join、导入导出和旧字段映射 | YAML 仍内嵌是源真相时，SQLite 只是派生拆表；不要改变外部 case JSON | 第三阶段，超过体积阈值再做 |
| `operation_id` 引用目录而非逐条内嵌 | 重复 API 请求可减少 YAML 和 DB 体积 | 变量覆盖、断言差异、导出必须展开；引用失效处理复杂 | 会改变 YAML review 体验和 `qa_case` 语义；需产品确认 | 暂不推荐 |
| revision 保留最近 N 个完整快照 | 历史空间线性封顶，读取简单 | 增加保留策略、清理任务和导出说明 | 旧 revision 读取兼容；若需要任意历史，不能直接删除 | 第一阶段先加保留策略 |
| revision diff/patch | 版本空间可能减少 70–95%（取决于修改类型） | patch 链恢复、校验、随机读取和损坏修复复杂 | 任何 patch 漏一版都会影响执行回溯；迁移回滚困难 | 暂不推荐，先保留完整快照 |
| 一用例一 YAML 文件 | git review、冲突范围和手工编辑最好；当前已经如此 | 10,000 个目录项和 `readdir`/备份开销 | 当前 loader 逐文件解析是性能根因，但文件体积本身不大 | **保留** |
| 按模块分块 YAML | 减少 inode 和 open 次数 | 单文件 diff 冲突、单条写放大、并发编辑复杂 | 需要稳定分块格式和迁移工具；不能解决每次全项目解析 | 不推荐当前阶段 |
| 压缩活跃 YAML | 磁盘可能减少 50–80% | 无法直接 git diff/review；每次读写解压 | 只适合导出/归档，不适合作为源文件 | 仅归档 |
| SQLite 为源，YAML 导出 | 查询和写入简单，天然可建索引 | git review、手工修复、agent 工具链和迁移都变差 | 破坏当前 YAML 真源契约；回滚成本高 | **拒绝** |

## 推荐设计

### 阶段 1：先修读写热路径

保留 YAML 真源和完整旧响应契约。`store.list_cases` 增加内部 summary 查询（id/project/code/title/kind/priority/status/tags/source/updated_at、trace 计数和 yaml_path），`CaseFiles.list_cases` 默认不调用 `load_project`，只返回摘要；详情路径继续读取一条 YAML 并返回现有完整 JSON。对必须显示的 `needs_links`、`needs_recheck`、`trace_*`，先按详情计算；列表可返回 `trace_state: unknown` 或由 `trace_cache` 给出已验证值，产品需要在拍板项中选择。

给 cases 加 `(project_id, status, code)`、`(project_id, kind, status, code)` 等经过 `EXPLAIN QUERY PLAN` 证实有用的索引，并把 legacy 可见性查询改为同项目、同 code/legacy_id 的覆盖条件。不要为了“看起来有索引”增加 tags/expected 的 B-tree：`%q%` 仍无法使用它。

写 YAML 成功后，只 upsert 受影响的 derived 行；删除/重命名先删除旧行再 upsert。`reindex(project)` 继续作为 git 手改、启动修复和迁移工具。批量导入先写全部 YAML，再在一个 `BEGIN IMMEDIATE` 事务中批量 upsert，任何校验或索引失败都回滚 SQLite，并将不完整 YAML 移入临时目录后再原子 rename。

缓存不能用无期限 TTL：key 至少包括 project、case id、YAML `mtime_ns/size` 或 content hash、`.qa-trace/index.json` mtime/hash、schema version；手改 YAML、`reindex`、trace review 和进程重启都必须失效。缓存只优化链路徽标，不作为真源。

### 阶段 2：搜索和前端分页

`webui/src/lib/qa-api.ts` 与 `QaCaseLibrary.tsx` 改为服务端分页，默认 50 条；详情抽屉单独加载完整数据。新增 FTS5 只覆盖 title/code（中文 tokenizer 需要用真实中文查询验收），搜索失败或 FTS 不可用回退到旧 LIKE。过滤维度 `project/kind/status` 仍走结构化 SQL；tags 先保留 LIKE 语义，避免 JSON 迁移同时改变结果。

### 阶段 3：历史和大 payload

给 `api_case_revisions` 增加保留策略（默认最近 20 个，删除前先记录审计/备份）；导出仍可显式请求完整历史。只有当 10,000 条真实项目的 `api`/assertions 使 SQLite 或 YAML 超过 50 MB，才评估 `api_case_payloads` 拆表；拆表必须继续由 YAML 派生、能从旧行重建，外部 `/api/qa/cases*` 和 `export/import` 形状不变。

## 迁移、版本和回滚

建议将真正的 schema 变更升到 `SCHEMA_VERSION = 5`，但把 FTS 虚表和新索引设计成可重建的派生对象。迁移步骤：

1. 打开数据库时备份 `qa.sqlite3` 和 WAL；检查 `PRAGMA user_version`、`cases` 列、`derived/legacy_id/yaml_path`，旧格式识别沿用现有 v3/v4 逻辑。
2. 添加索引、summary/FTS 表和迁移标记，使用 `CREATE INDEX IF NOT EXISTS`/批量重建，确保重复启动幂等。
3. 以 YAML 扫描结果重建 derived 行和 FTS；失败时保留旧索引、记录错误并继续用 `replace_derived_cases`/LIKE 兜底，不能把空索引当成空用例库。
4. 新旧读路径双读一个发布周期：新 summary 缺列或 hash 不匹配时回退现有完整路径；旧 `derived=0` 行仍可读，YAML 仍可被 `reindex` 认领。
5. 观察列表/详情/写入 SLO、索引计数和 YAML hash；确认后再删除临时表或旧缓存。

回滚只需停用新查询路径并恢复数据库备份/删除新派生表；YAML 不回滚、不覆盖。若单条写已写 YAML 但索引事务失败，响应返回可重试错误，后台 `reindex(project)` 修复；若批量导入部分 YAML 已落盘，使用批次 manifest 清理或重放，不能静默留下不可见文件。

## 分阶段实施与验收

| 阶段 | 主要文件 | 测试与验收 | 回滚 |
|---|---|---|---|
| 1A 读路径 | `nanobot/qa/case_files.py`、`store.py`、相关 `tests/qa/test_case_files.py`/`test_store.py` | 100/1,000/10,000 fixture：列表 P95 ≤目标、详情 ≤目标；字段和 trace 徽标与旧响应逐项相等；`EXPLAIN` 无无界 legacy 扫描 | feature flag 回到旧 `list_cases/get_case` |
| 1B 写路径 | `case_files.py`、`store.py`、`tests/qa/test_case_files.py`、`test_db_migration.py` | 单条 update 不随项目大小线性增长；导入 1,000 条 ≤30 s；中断/重复导入幂等；`reindex` 结果一致 | 保留全量 `reindex`，禁用 upsert/import fast path |
| 2 搜索/UI | `store.py`、`webui/src/lib/qa-api.ts`、`webui/src/components/qa/QaCaseLibrary.tsx`、`webui/src/tests/qa-*.test.tsx` | 过滤/FTS/LIKE 结果兼容；50 条分页响应 ≤120 KB；滚动和详情抽屉无重复请求；旧 `limit/offset` 参数仍有效 | FTS/分页 feature flag 回到 LIKE 和现有列表 |
| 3 历史/大块 | `store.py`、`case_files.py`、迁移测试 | revision 保留 N 版、hash 校验、旧 revision 可读；拆表前后 export/import JSON 完全一致；真实 10k fixture 体积低于阈值 | 保留完整 snapshot 和旧派生列，删除新 payload 表 |

每阶段都必须跑：

```bash
cd /opt/worktrees/qa-case-storage-scaling
.venv/bin/python -m pytest tests/qa/test_case_files.py tests/qa/test_case_revisions.py \
  tests/qa/test_store.py tests/qa/test_db_migration.py tests/qa/test_http.py \
  tests/qa/test_trace_chain.py -q
cd webui && npx vitest run qa-
```

## 可直接执行的实施说明

以下内容可以作为开发任务单或实施 PR 的验收说明。实施顺序必须保持不变：先保证读路径和增量索引正确，再做搜索和前端体验优化。

### 任务目标

在保持 YAML 为真源、保留每个用例完整测试点/需求查询能力、保持现有 `qa_case` 和 HTTP/导入导出 JSON 契约的前提下，实现：

```text
列表只读轻量摘要
详情读取单条完整 YAML 和追溯链
修改一个实体只刷新受影响用例
批量导入只进行一次事务更新
全量 reindex 继续作为修复和迁移工具
```

### 允许修改的文件

```text
nanobot/qa/case_files.py
nanobot/qa/store.py
qa_trace/loader.py
qa_trace/graph.py
qa_trace/staleness.py
webui/src/lib/qa-api.ts
webui/src/components/qa/QaCaseLibrary.tsx
tests/qa/*
webui/src/tests/qa-*.test.tsx
```

不得修改 agent、runtime、transcript 核心，不新增 HTTP 写入路由，不直接修改部署机 `/opt/qa-agent`。

### 1. 新增派生表和接口

在 `nanobot/qa/store.py` 中新增可重建的派生表：

```sql
trace_edges(
  project_id,
  from_type,
  from_id,
  to_type,
  to_id,
  PRIMARY KEY(project_id, from_type, from_id, to_type, to_id)
)

case_trace_summary(
  case_id PRIMARY KEY,
  needs_links,
  needs_recheck,
  trace_status,
  recheck_reasons,
  testpoint_count,
  source_count,
  input_hash,
  checked_at
)

trace_file_state(
  project_id,
  path,
  entity_type,
  entity_id,
  content_hash,
  mtime_ns,
  PRIMARY KEY(project_id, path)
)
```

增加以下 store 方法：

```python
replace_trace_edges(project_id, from_type, from_id, edges)
get_dependents(project_id, entity_type, entity_id)
get_case_trace_summary(case_id)
upsert_case_trace_summary(summary)
mark_case_trace_stale(case_ids)
```

新表和索引必须幂等创建。`SCHEMA_VERSION` 升级到 5；这些表属于派生数据，删除后必须能从 YAML 和追溯文件重建。

### 2. 实现受影响用例计算

在 `case_files.py` 或 `qa_trace` 中实现：

```python
affected_cases_for_entity(
    project_id: str,
    entity_type: str,
    entity_id: str,
) -> set[str]
```

规则：

```text
修改 case：返回该 case
修改 testpoint：通过 trace_edges 找直接引用它的 case
修改 requirement/source：沿 testpoint -> case 关系找到受影响 case
```

再实现：

```python
refresh_trace_for_cases(
    project_id: str,
    case_ids: Iterable[str],
) -> None
```

该函数只读取目标用例及其关联测试点、需求，不调用全项目 `load_project()`。它必须更新 `case_trace_summary` 中的：

```text
needs_links
needs_recheck
trace_status
recheck_reasons
testpoint_count
source_count
input_hash
checked_at
```

如果单条实体缺失或无法解析，标记为 `stale`，不能静默当成“没有关联”。

### 3. 修改读路径

`CaseFiles.list_cases()`：

```text
删除普通列表请求中的全项目 load_project/build_graph/recheck_map
从 SQLite 查询摘要
默认 limit=50
保留 limit/offset 参数兼容
```

列表返回 `id/code/title/module_id/operation_id/kind/status/priority/tags`、追溯摘要和时间字段，不返回完整 `api/steps/expected`。

`CaseFiles.get_case()`：

```text
只读取目标 YAML
读取该 case 的 trace summary
summary 有效则复用
summary 过期则刷新目标 case
返回原有完整 JSON 结构
```

详情必须继续返回完整 `testpoints`、`sources`、`trace_testpoints`、`trace_sources` 和 `recheck_reasons`。

### 4. 修改写路径

新增、更新、删除用例或追溯实体时，统一执行：

```text
原子写入 YAML
更新当前实体的 trace_edges
计算 affected case_ids
在一个 SQLite 事务中标记并刷新这些 case
提交
```

禁止普通单条写入调用项目级 `replace_derived_cases()`。该函数保留给：

```text
首次索引、迁移、手工修复、索引损坏恢复
```

批量导入必须先写临时目录，全部校验成功后原子移动 YAML，再用一个事务批量 upsert 和刷新受影响用例；任何失败都回滚事务并清理临时文件。

### 5. 缓存和外部手工修改

项目图缓存和用例摘要缓存不能使用无期限 TTL。缓存输入至少包含：

```text
project_id
相关 YAML content_hash
相关 trace 文件 content_hash
schema_version
```

通过 WebSocket 写入时直接更新摘要。检测到 git checkout、手工修改或 mtime/hash 不一致时，只标记对应实体和受影响用例为 `stale`；显式 `reindex(project)` 负责全量修复。不能把缓存缺失解释为空用例或无追溯关系。

### 6. 测试、基准和交付门槛

必须新增或修改测试，验证：

```text
修改一个测试点只刷新引用它的用例
修改一个需求只刷新受影响用例
无关用例的 input_hash/checked_at 不改变
列表不读取所有用例 YAML
详情仍返回完整测试点和需求
增量结果与全量 reindex 结果一致
迁移可重复执行且不产生重复边
批量导入失败可回滚、重试不重复
旧 YAML、legacy SQLite 行和 export/import 继续兼容
```

使用 `/tmp/qa-growth/{100,1000,10000}` 做基准，验收目标为：列表 P95 ≤300 ms、详情 P95 ≤200 ms、单条写入不随项目规模线性增长、1,000 条导入 ≤30 s、50 条摘要响应 ≤120 KB。

### 7. 回滚步骤

实现阶段保留 feature flag：

```text
QA_CASE_TRACE_INCREMENTAL=0
```

出现问题时，关闭增量路径，恢复旧列表和全量 `reindex`；YAML 不回滚、不覆盖。新增 SQLite 派生表可删除后从 YAML 重建。任何迁移失败都不能把空索引展示成空用例库。

## 风险清单

- **索引陈旧**：手改 YAML、git checkout 和 trace review 后摘要或徽标落后。用 mtime/hash、启动校验和显式 `reindex` 修复；读到 hash 不一致必须降级到 YAML。
- **并发写**：两个 WebSocket mutation 同时写同一 case 时可能互相覆盖。按 project/case 加锁，YAML 用临时文件 + `fsync` + rename，SQLite 用事务；冲突返回可识别错误。
- **迁移中断**：FTS/索引只完成一半会产生“空列表”错觉。迁移状态必须可见，读路径在状态非 ready 时用旧路径。
- **YAML 手改不同步**：SQLite 不是真源；启动或请求发现 hash 变化后只刷新对应行，项目级 `reindex` 仍提供全量修复。
- **搜索语义变化**：FTS 不等价于 `%q%`，中文分词和标点尤其明显。保留 LIKE 兜底并用固定查询集对比结果。
- **链路徽标陈旧**：缓存的 `needs_links/needs_recheck/trace_*` 不能阻止详情重新核验；缓存必须带 trace 文件版本。
- **大 payload 重复**：拆表或引用目录若不展开，会破坏 `qa_case`、HTTP 和 export/import 契约；任何拆分都只做 SQLite 内部派生形状。
- **revision 空间失控**：完整 snapshot 比 diff 简单但会线性增长；先限最近 N 版并监控 `api_case_revisions`，达到阈值再讨论 diff。

## 需要用户拍板（不超过 5 项）

1. 目标是否按“每项目 10,000 条、列表单页 50、上述 P95/SLO”执行？若 WebUI 必须固定 200 条，需要接受约 4 倍响应体目标。
2. 列表上的 `needs_recheck/trace_*` 是否允许短时间缓存或显示 `unknown`，详情再强校验？若不允许，列表仍需加载链路，第一阶段收益会下降。
3. revision 默认是否保留最近 20 版完整快照？需要任意历史版本的项目应改成只归档不清理。
4. 是否接受新增 `SCHEMA_VERSION = 5` 的派生索引/FTS 表，并保留 LIKE 兼容回退？
5. 是否把“按 operation_id 引用共享 API 请求”明确列为后续优化，而当前继续要求每个 YAML 自包含、可 review？

## 本轮不做

- 不改 `/opt/qa-agent`、线上 `qa.sqlite3`、线上 YAML，不重启、不部署。
- 不改 `nanobot` agent/runtime/transcript 核心，不新增 HTTP 写路由。
- 不把 SQLite 改为真源，不改变 `qa_case`、`/api/qa/cases*`、export/import 的 JSON 契约。
- 不在没有真实体积和查询证据前拆 YAML 文件、压缩活跃文件或引入 operation 引用。
- 不把 FTS、缓存或 diff 作为“加上就会快”的无指标结论；每项都必须有失效策略和回退路径。
