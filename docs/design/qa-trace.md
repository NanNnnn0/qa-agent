# qa-trace 设计说明（P0 模型冻结 + P1 图校验与指标 + P2 执行闭环 + P3 复核与入库 + P4 工作台接入 + P5 Git/CI 门禁 + P6 用例源迁移）

> 依据 `qa-trace-spec.md`（测试用例追溯链规范 v1）与 `qa-trace-implementation-plan.md`
> （实施与派发方案），以方案第 2 节（规范修订）、第 3 节（模型）、第 4 节（校验器）、
> 第 5 节（指标）、第 3.4 节（审核与有效性）、第 6 节（查询和变更传播）、第 7 节（命令接口）
> 与第 8 节（P3 复核与入库、P4 工作台接入、P5 CI）为准。这两份文档在实施工作区保存，
> 不在本仓库内。本文记录 **P0、P1、P2、P3、P4、P5 与 P6** 的落地决定、规则码、退出码、
> 索引/manifest/diff 形状、HTTP 接口、CI 接入与边界。

## 1. 交付内容

### 1.1 P0（模型与规则冻结）

| 位置 | 内容 |
|---|---|
| `qa_trace/ids.py` | ID 语法、前缀/类型映射、`parse_id` / `normalize_id` / `new_id` |
| `qa_trace/models.py` | Source / TestPoint / Case / ScriptBinding / Automation / Run / CaseResult |
| `qa_trace/loader.py` | 读取 `projects/<proj>/{project.yaml,sources,testpoints,cases}` 并收集诊断 |
| `qa_trace/errors.py` | `QaTraceError` 体系，每条错误带 `code` + `path` + `field` |
| `qa_trace/cli.py` | `qa trace check --project <path>` |
| `tests/qa_trace/` | 有效/无效 fixtures 与 ids、models、loader 测试 |
| `pyproject.toml` | `[project.scripts] qa = "qa_trace.cli:main"`，qa_trace 进入 wheel/sdist |

### 1.2 P1（追溯校验与报告）

| 位置 | 内容 |
|---|---|
| `qa_trace/graph.py` | `TraceGraph`：正/反向邻接、`case → source` BFS、下游查询 |
| `qa_trace/bindings.py` | `automation.script` 目标解析（存在、`.py`、不越出项目根） |
| `qa_trace/rules.py` | 引用完整性、孤儿、规范第 3 节规则 10/11/12/13 |
| `qa_trace/metrics.py` | 方案第 5 节的四个指标 + 需求缺口 + 死资产 + `needs_recheck` |
| `qa_trace/diagnostics.py` | `Severity` / `Diagnostic`、稳定排序、退出码映射 |
| `qa_trace/check.py` | `run_check()`：一次扫描 → 诊断 + 图（CLI 与 P4 工作台共用） |
| `qa_trace/report.py` | 稳定 JSON 报告 + 文本渲染 |
| `qa_trace/cli.py` | `qa trace check`、`qa trace report [--json]` |
| `qa_trace/__main__.py` | `python -m qa_trace` |
| `tests/qa_trace/` | 断链、孤儿、stale 传播、指标精确值、退出码 0/1/2 的测试与 fixtures |

### 1.3 P2（执行闭环）

| 位置 | 内容 |
|---|---|
| `qa_trace/markers.py` | 用 `ast` 读脚本里的 `@pytest.mark.case(...)`；规则 9 双向对照（不导入、不执行测试代码） |
| `qa_trace/pytest_plugin.py` | pytest 插件：marker 校验 + 会话结束后写 run manifest |
| `qa_trace/runs.py` | manifest 组装、参数实例聚合、错误摘要截断、原子写入 |
| `qa_trace/check.py` | `run_check()` 在 P1 图规则之后追加 marker lint |
| `pyproject.toml` | `[project.entry-points.pytest11] qa_trace = "qa_trace.pytest_plugin"` |
| `tests/qa_trace/test_markers.py` | AST 扫描单测 + `marker_ok` / `marker_missing` / `marker_extra` fixtures |
| `tests/qa_trace/test_pytest_plugin.py` | `pytester` 驱动真实嵌套会话：通过/失败/跳过/error/xfail/xpass、参数聚合、未知 ID、只收集模式 |
| `tests/qa_trace/test_runs.py` | 截断、聚合、`Run.from_dict` 回读、原子替换 |

### 1.4 P3（复核与入库）

| 位置 | 内容 |
|---|---|
| `qa_trace/hashing.py` | 内容摘要与依赖指纹（业务字段白名单、canonical JSON、`FINGERPRINT_VERSION`） |
| `qa_trace/index.py` | 派生索引 `<project>/.qa-trace/index.json`：baseline、reviews、草稿驳回记录；原子写入 |
| `qa_trace/staleness.py` | 变更对比、`needs_recheck` 派生、`qa trace stale` 报告与文本渲染 |
| `qa_trace/impact.py` | `qa trace impact`：反向索引查询受影响的 TP / Case / 脚本与 nodeid |
| `qa_trace/drafts.py` | `draft/` 批次扫描、候选图校验、`draft new/add`、`review list/approve/reject`、原子晋级 |
| `qa_trace/failure.py` | `qa trace failure`：从 manifest 失败结果回溯 case → TP → Source，并对比当前资产 |
| `qa_trace/loader.py` | 新增 `scan_collection()`（候选图复用）、`load_yaml_document()`、`DRAFT_DIRNAME` |
| `qa_trace/graph.py` | 新增 `cases_of_testpoint()` / `cases_of_source()` 反向查询 |
| `qa_trace/check.py` | `run_check(..., include_drafts=True)`：默认不扫 `draft/` |
| `qa_trace/pytest_plugin.py` | manifest 快照追加 `testpoint_sources`（失败回溯用） |
| `qa_trace/cli.py` | `impact`、`stale [--write]`、`draft new/add`、`review list/approve/reject`、`failure`、`check --include-draft` |
| `tests/qa_trace/` | `test_hashing.py`、`test_stale.py`、`test_impact.py`、`test_drafts.py`、`test_failure.py` 与 `impact_project` / `draft_review` / `draft_invalid` fixtures |

### 1.5 P4（nanobot 工作台接入）

| 位置 | 内容 |
|---|---|
| `nanobot/qa/trace_api.py` | 工作台适配器：项目根解析（`NANOBOT_QA_TRACE_ROOT`，默认 `<repo>/qa-workbench/projects`）、7 个只读接口 + 3 个审核动作、`QaTraceError → QaNotFoundError/QaConflictError/QaValidationError` 映射 |
| `nanobot/qa/http.py` | `QA_MUTATION_PATHS` 增加 `qa.trace.stale_write` / `qa.trace.review_approve` / `qa.trace.review_reject`；`/api/qa/trace/*` 复用同一 `QaApi` 与同一 token 校验，不新建服务 |
| `webui/src/lib/qa-api.ts` | `QaTrace*` 类型、8 个读函数、3 个 mutation 函数与防御式归一化 |
| `webui/src/components/qa/QaTrace.tsx` | 「追溯」标签页：四个指标卡、Source→TP→Case→Script 链、影响面查询、变更/待复核 + 记录基线、草稿通过/退回、失败回溯 |
| `webui/src/components/qa/QaWorkbench.tsx` | 新增 `trace` 标签（`QA_TABS`、`QaTab`、文案） |
| `webui/src/components/qa/qa-ui.tsx` | `QaPanel` 增加可选 `testId`（其余原子组件复用） |
| `qa-workbench/projects/login-lock/` | 真实演示项目：2 Source、1 TP、1 Case、1 pytest 脚本、证据 artifacts、1 个待审草稿、1 次真实失败运行 manifest |
| `qa-workbench/README.md` | 数据目录说明与演示命令 |
| `tests/qa/test_trace_api.py` | 27 条：项目列举/隔离、四个指标、链、影响面、stale/基线、草稿通过/退回、失败回溯、错误映射、HTTP 鉴权与 mutation 通道 |
| `webui/src/tests/qa-trace.test.tsx` | 8 条：指标渲染、链渲染、影响面请求、通过/退回/记录基线 mutation、错误态、工作台标签 |
| `docs/qa-agent.md` | 工作台入口、接口清单、演示命令 |

### 1.6 P5（Git/CI 门禁）

| 位置 | 内容 |
|---|---|
| `qa_trace/diff.py` | `qa trace diff`：`git rev-parse` 解析基线 → `git archive` 物化项目子树到临时目录 → 两侧 `run_check` + `build_report` → 诊断/六个比率/悬空/孤儿/需求缺口/`needs_recheck` 对比；稳定 JSON + 文本渲染 |
| `qa_trace/errors.py` | 5 个 diff 输入错误码（`TRACE_DIFF_*`） |
| `qa_trace/diagnostics.py` | 上述码加入 `INPUT_ERROR_CODES`（映射退出码 2） |
| `qa_trace/cli.py` | `qa trace diff --project <path> --base <ref> [--coverage-tolerance <pt>] [--json]` |
| `.github/workflows/qa-trace.yml` | 安装包 → `pytest tests/qa_trace` → demo 项目 `check` → 上传报告 artifact → PR 上 `diff --base origin/<base_ref>`（回归即失败），上传 diff artifact |
| `.pre-commit-config.yaml` | 本地 hook（`language: system`）：提交前对 demo 项目跑快检，不依赖远端仓库 |
| `tests/qa_trace/test_diff.py` | 临时 git 仓库两个 commit：无改动 0、新悬空引用 1、覆盖率下降 1、未知 ref 2、非 git 2、基线缺项目 2、JSON 形状、容差、工作区不被改写 |

### 1.7 P6（用例源迁移：YAML 是真源，SQLite 是索引）

| 位置 | 内容 |
|---|---|
| `qa_trace/compat.py` | SQLite ↔ trace 词汇映射：`kind↔type`（`manual→functional`，反向收敛到 `manual`）、`status↔reviewed/ready`、`automation` 派生；唯一翻译点 |
| `qa_trace/yamlfile.py` | 全库共用的原子 YAML 写入（临时文件 + fsync + `os.replace`，保留键序） |
| `qa_trace/caseyaml.py` | 用例文档形状与文件布局：`case_document()`、`cases/`、`draft/<batch>/cases/`、`tombstones/`、`TC-<MODULE>-<seq>` 分配（含墓碑，ID 不复用）、`iter_case_documents()` |
| `qa_trace/models.py` | `Case` 新增 `code`/`expected`/`api`/`legacy_id`（工作台业务字段，仍由 YAML 真源承载）；`api` 块形状在加载期校验 |
| `qa_trace/hashing.py` | `FINGERPRINT_VERSION = 2`：摘要纳入上述四个字段，索引配方不匹配即拒绝（写入路径用 `load_index_for_write` 视为空索引重建） |
| `qa_trace/drafts.py` | 写入统一走 `yamlfile.write_yaml`；`read_draft_entity` 公开（产品层读草稿复用） |
| `qa_trace/index.py` | `load_index_for_write()`：读索引遇到旧配方按空索引处理（派生数据，写入不必失败） |
| `qa_trace/migrate.py` | `qa trace migrate-sqlite`：只读打开 SQLite → 逐项目写 YAML 草稿（`legacy_id` 回指、`code` 保留、`TC-*` 新 ID）→ 计数报告 |
| `nanobot/qa/case_files.py` | 用例库适配器：`qa_case` 工具与 `/api/qa/cases*` 的唯一实现；YAML 先写、再重建派生索引；删除=墓碑；无链路的「已评审」仍是草稿 |
| `nanobot/qa/store.py` | `SCHEMA_VERSION = 3`：`cases` 增加 `derived/legacy_id/yaml_path`，去掉 `UNIQUE(project_id, code)`，新增 `replace_derived_cases()` / `case_codes()` / `derived_case_ids()` / `derived_case_count()`，可见性规则（被 YAML 认领的旧行隐藏） |
| `nanobot/qa/http.py` | `/api/qa/cases*` 全部改走 `CaseFiles`；响应形状不变，新增链路徽标字段；写字段增加 `testpoints/sources/direct_reason/risk/note/batch` |
| `nanobot/agent/tools/qa.py` | `qa_case` 改走 `CaseFiles`（list/get/create/bulk_create/update/delete），工具契约不变 |
| `nanobot/cli/qa.py` | `nanobot qa reindex [--project KEY] [--root DIR]`：从 YAML 重建 SQLite 派生索引（等价于方案里的 `qa trace reindex`） |
| `webui/src/lib/qa-api.ts` | `QaCase` 增加 `type/trace_status/testpoints/sources/script/needs_recheck/draft/legacy` 等只读徽标字段；`markQaCaseReviewed()`、`archiveQaCase()` |
| `webui/src/components/qa/QaCaseLibrary.tsx` | 「用例库」：链路徽标列（来源/测试点/脚本/需复核）、追溯链路编辑区、显式「标记为已评审」、删除改为「归档」 |
| `qa-workbench/projects/shop/` | SHOP 演示库：8 条 SQLite 用例迁移成的 YAML 草稿（`draft/sqlite-migration/`） |
| `tests/qa_trace/test_compat.py`、`test_yamlfile.py`、`test_case_fields.py`、`test_caseyaml.py`、`test_migrate.py` | 词汇映射、原子写入、新字段/摘要/索引配方、文档布局、迁移（只读、幂等、计数、退出码） |
| `tests/qa/test_case_files.py` | 用例库契约：草稿默认、链接后才能晋级、墓碑与 ID 退休、索引重建、旧行只读、HTTP 写入 YAML、词汇漂移守卫 |

## 2. 关键决定

### 2.1 P0（不变）

1. **模型用 dataclass + 显式字段读取器，不用 pydantic。** 诊断必须同时带
   `code`、文件 `path` 和字段路径（如 `steps[1].expected`），而 pydantic 的
   `ValidationError` 需要二次翻译才能得到稳定规则码；P0 的目标只是冻结字段规则，
   领域错误模型比通用校验框架更直接。
2. **所有 Source 都要 evidence**（方案 §2 的修订优先于原规范“req/std 免证据”）。
   evidence 条目统一为 `{type, locator, ...}`，`type ∈ document|openapi|ui_capture|issue|standard|exploration`；
   req 的“文档+章节号”、std 的“条款号”由 `locator` 承载。UI 来源额外强制
   `url`、`app_version`、`observed_at`（路径/版本/日期）。`sha256` 可选但必须是
   64 位小写十六进制；`verified ∈ verified_local|external_unverified`。
3. **ID 语法 `<PREFIX>[-<MODULE>]-<SEQ>`。** module 可省略以兼容规范里的 `REQ-12`；
   SEQ 是 1–6 位数字或完整 UUID4；`parse_id` 严格（只收规范大写形式），
   `normalize_id` 宽松（大小写、首尾空白）。新 ID 默认 UUID4
   （方案 §3.1 禁止“最大号+1”），计数器形式补零到 3 位（`TC-LOGIN-003`）。
   Source 的 `type` 必须与 ID 前缀一致，引用位置也按类型校验（TP 只能引用
   REQ/API/UI/BUG/STD/EX）。
4. **Case 关联规则**：`testpoints` 与 `sources` 至少一项非空；直接声明 `sources`
   必须写 `direct_reason`；没有 testpoints 的 Case 必须自己声明 `risk`
   （有 TP 时风险从 TP 展示，不重复维护）。
5. **脚本绑定**：`automation.status=done` 必须有 `<file>::<nodeid>` 绑定，支持类方法
   与参数化 nodeid（`tests/x.py::TestLogin::test_lock[1]`）。
6. **loader 结构规则**：一个实体一个文件，文件名必须等于其 ID；重复 ID 直接报错；
   用 `SafeLoader` 子类拒绝重复 YAML key（PyYAML 默认静默丢弃后者）；未知字段保留在
   `extra`；一次扫描收集全部错误，只有一条错误时直接抛出该错误，多条时抛
   `QaTraceGroupError`（`.codes` 按发现顺序）。
7. **打包**：`qa_trace` 同时加入 hatch 的 `build.include`、wheel `packages` 与 sdist，
   否则 `qa` 入口在安装产物里指向不存在的模块。

### 2.2 P1（新增）

8. **诊断统一成一种形状。** P0 的 loader 抛 `QaTraceError`，P1 的图规则产出
   `Diagnostic(severity, code, path, field, entity_id, message, suggestion)`；loader
   错误由 `diagnostics.from_error()` 转换，两条来源最终合成同一份列表。`path` 一律
   **相对项目根、POSIX 分隔**，排序键为 `severity → path → code → field`，因此
   Windows 与 Linux 的输出逐字节一致。方案 §4 里的 “rule” 字段就是 `code`。
9. **引用校验分三类。** 目标集合里找不到 → `TRACE_REF_MISSING`；ID 存在但属于别的
   集合 → `TRACE_REF_TYPE_MISMATCH`（ID 前缀已保证正常不会发生，这是纵深防御）；
   脚本目标越出项目根 → `TRACE_REF_OUTSIDE_PROJECT`；脚本目标存在但不是 `.py` →
   `TRACE_REF_TYPE_MISMATCH`。`automation.script` 只要声明了就校验，不限于 `done`。
10. **孤儿 = BFS 到不了任何“已存在”的 Source。** 悬空引用不建边，所以断链的 case 会
    同时报 `TRACE_REF_MISSING` 和 `TRACE_CASE_ORPHAN`——两个都报，不掩盖任何一侧。
    孤儿判定是结构性的：经过 deprecated Source 也算“链上”，覆盖率才是另一套口径。
11. **覆盖口径（方案 §5）。** 分母只用正式库：active Source、非 deprecated Case，
    `draft/` 与 deprecated Source 不进分母。分子只认 reviewed Case，且整条路径必须
    合法：Source `active` + `confirmed`；路径上的 TP 必须 reviewed；直挂 Source 的
    Case 必须有 `direct_reason`。未确认（observed）的 Source 仍留在分母并单列
    `unconfirmed_sources`，不能靠降低置信度隐藏缺口。
12. **reviewed 与 current_valid 分开报。** `reviewed` 是“曾审核过的合法路径”，
    `current_valid` 再额外剔除经过 `stale` Source 的路径。内容摘要/依赖摘要（方案
    §3.4 的完整 valid 定义）要等 P3，因此 P1 的 `current_valid` 只表示“路径上没有
    stale 来源”。
13. **自动化率**：分子 = reviewed 且 `automation.status=done` 且脚本目标可解析的 Case。
    marker 双向对照（规则 9）需要 pytest collection，属于 P2，所以报告固定
    `provisional: true` 并写明原因；无法解析的脚本单列 `unresolved_scripts`。
14. **规则 13 的双层实现。** 规范把“直挂 Source 无 `direct_reason`”列为 warn，P0 模型
    层已经把它当 error（`TRACE_DIRECT_REASON_MISSING`，`Case.from_dict` 直接拒收）。
    P1 保留 P0 的严格度（`qa trace check` 走不到图规则），同时在 `rules.py` 里按规范
    再实现一次 warn 级检查，用“直接构造实体”的单测覆盖。这是纵深防御，也是 P3 草稿
    批次注入实体后的兜底；不是死代码，但不改变 CLI 的现有表现。
15. **结构错误时抑制指标。** 只要有 error，报告 `valid: false`，
    `coverage`/`requirement_gaps`/`dead_assets` 全部为 `null`，用
    `metrics_suppressed` 说明原因（方案 §4：结构错误时不得输出带成功含义的覆盖率）。
    诊断、`dangling_count`、`needs_recheck` 照常输出。
16. **派生状态不落盘。** `needs_recheck`、覆盖率、缺口清单全部运行时计算，报告与
    校验都不修改 YAML（规范 §3 末句）。测试用整棵目录的 SHA-256 对比来证明这一点。
17. **strict 与阈值。** `project.yaml` 的 `strict: true` 让 warn 也失败（退出码 1）；
    `thresholds.p0_ratio_max` 默认 `0.2`，非法值（非数字、越出 0–1）按输入/配置错误
    处理（退出码 2）。`thresholds.manual_p0_max_days` 被读取并校验，但 P1 用不上（见
    限制）。

### 2.3 P2（新增）

18. **marker 对照是静态的，`qa trace check` 不导入测试代码。** 方案 §4 要求快速检查
    只做“可识别的静态 pytest 装饰器与 AST 检查”，因此 P2 用 `ast.parse` 读被
    `automation.script` 绑定的文件，不 import、不 collect、不执行。`ast` 只认
    `pytest.mark.case`（含 `@pytest.mark.case` 裸装饰器、关键字参数、非字面量参数，
    后三者都按非法 marker 报出），别名导入（`import pytest as pt`）和模块级
    `pytestmark` 不在静态识别范围内，见限制。
19. **双向对照拆成三个码，不合成一个“mismatch”。** 方案 §4 举例的
    `TRACE_MARKER_MISMATCH` 在这里落成三个可区分的错误：用例侧缺 marker
    （`TRACE_MARKER_MISMATCH`）、脚本侧 marker 没有用例认领
    （`TRACE_MARKER_ORPHAN`）、marker 里的 ID 非法或不是本项目的用例
    （`TRACE_MARKER_UNKNOWN`）；目标文件读不了或语法错误是
    `TRACE_MARKER_UNREADABLE`。诊断仍带 `path` + `field`：用例侧 `path` 是用例
    YAML、`field=automation.script`；脚本侧 `path` 是脚本文件、`field` 是装饰到的
    nodeid，行号写在 message 里。
20. **nodeid 也对照，但只在能静态确定时。** marker 必须出现在绑定文件里；如果绑定
    nodeid 是该文件里一个真实函数（去掉参数化后缀 `[...]` 后匹配），marker 还必须
    挂在这个函数上，否则仍是 `TRACE_MARKER_MISMATCH`（message 指出 marker 实际挂在
    哪个 nodeid）。绑定 nodeid 在文件里找不到对应函数（动态生成、插件提供的 item）
    时退回文件级判断，不误报；真正的 nodeid 存在性要靠 pytest collection。
21. **悬空脚本不重复报。** `automation.script` 解析失败（P1 的 `TRACE_REF_MISSING` /
    `TRACE_REF_OUTSIDE_PROJECT` / `TRACE_REF_TYPE_MISMATCH`）时 marker lint 跳过该
    用例，避免一个断链产生两条错误。
22. **插件默认惰性。** 没给 `--qa-project` 也没有 `--qa-run-dir` 时，插件只注册
    marker 并校验 ID 语法，不写任何文件；给了 `--qa-project` 时默认写到
    `<project>/runs/<run_id>/manifest.json`，给了 `--qa-run-dir` 时写到该目录。
    没有 `--qa-project` 就无法判断“未知用例”，只校验 ID 语法（文档写明这一点）。
23. **marker 错误让 collection 直接失败（pytest 退出码 4）。** 未知 ID、非法 ID、
    非字符串参数、无法加载的项目库都在 collection 阶段抛 `pytest.UsageError`，
    错误写进 stderr 并中止本次会话；此时不写 manifest——没有可信的 run 可记。
24. **manifest 复用 P0 的 `Run` 形状。** 顶层 `run_id` / `project_id` /
    `started_at` / `finished_at` / `results` / `environment` / `tool_version` /
    `code_commit` / `asset_snapshot` 与 `models.Run` 对齐，`Run.from_dict(manifest)`
    能回读（测试断言）；P2 追加的 `status`、`summary`、`cases`、
    `script_digest`、`pytest` 落在 `Run.extra`。结果行是 `CaseResult` 形状：
    `case_id` / `nodeid` / `attempt` / `outcome` / `started_at` / `finished_at` /
    `failure_stage` / `error_summary`，`duration_ms` 是追加字段。
25. **参数实例单独成行，用例汇总是最差实例。** 每个 pytest nodeid 一条结果
    （多 marker 的 node 按 case 展开成多条，`attempt` 按用例递增）；`cases[]` 按
    `case_id` 聚合，`outcome` 取最差（error > failed > xpassed > passed > xfailed >
    skipped > cancelled），并给出各 outcome 计数。一个参数实例失败时用例不可能显示
    全绿（方案 §3.5）。
26. **快照在跑之前冻结，没有 Git 也不编造 commit。** `pytest_sessionstart` 记录
    run_id、UTC 开始时间、`code_commit`（`git rev-parse HEAD` 成功且是 40 位十六进制
    才填，否则 `null`）和 `asset_snapshot`：每个 Source/TP/Case 文件的 SHA-256 加
    Case→TP/Source 关系。`script_digest` 在 collection 结束后、执行开始前计算
    （收集到的测试文件按相对路径排序后合成摘要）。
27. **manifest 原子写入，中断标记 incomplete。** 先写同目录隐藏临时文件、`fsync`、
    再 `os.replace` 覆盖目标；异常时删除临时文件。`pytest_sessionfinish` 按退出码
    决定 `status`：0/1/5 为 `complete`，2（Ctrl-C）/3（internal error）为
    `incomplete`，`--collect-only` 为 `collect_only`；`--collect-only` 时
    `results` 为空但 `summary.collected` 是真实收集数。写文件失败只打印一行红字
    （不篡改测试退出码，也不伪装成已记录）。
28. **插件与 lint 共用同一套 marker 读取规则。** `qa_trace.markers` 负责 AST 扫描与
    规则 9；插件只负责 `pytest.mark.case` 的运行时校验和结果记录。两边共用
    `MARKER_NAME` 与 `TC-*` ID 语法（`ids.ensure_kind(..., IdKind.CASE)`）。

### 2.4 P3（新增）

29. **摘要只覆盖“声明的业务字段”，且分内容摘要与依赖指纹两层。**
    `hashing.py` 用白名单把每个实体拼成 dict，再用 canonical JSON（键排序、无空格、
    UTF-8）做 SHA-256。**排除**审核元数据（`reviewed_by`/`reviewed_at`/摘要字段）、
    人工 `stale` 标记、派生字段与未知字段（`extra`）。所以：改排版/改 key 顺序/加
    `reviewed_by` 不触发复核；改标题、证据、脚本绑定、步骤预期都会触发。依赖指纹 =
    `sha256(id + kind + content_hash + 上游各实体的依赖指纹)`，因此是**传递**的：
    Source 一改，经过 TP 传到 Case；直挂 Source 的 Case 同样能感知。上游引用悬空时
    记 `null`，不会与“没有这条引用”撞成同一个指纹。配方版本写在
    `FINGERPRINT_VERSION`，变更后旧索引会被拒绝（提示 `stale --write` 重建）。
30. **索引是派生物，YAML 是真源，`needs_recheck` 不落盘。** 索引固定放在
    `<project>/.qa-trace/index.json`，可删除、可重建（删掉后 `stale` 会报告
    `baseline: missing`，其余命令照常工作）。`stale`、`impact`、`failure`、`check`
    都不改 YAML；只有 `review approve` 晋级草稿时才会写正式实体文件（这是晋级本身）。
31. **baseline 与 reviews 分开，`--write` 不会替人审核。** `baseline` 回答“自上次记录
    以来变了什么”，`reviews` 回答“审核还有效吗”。`stale --write` 只写 baseline，
    并给**还没有 review 记录**的 reviewed TP/Case 补一条 `adopted: true`、
    `reviewed_by: null` 的“采纳”记录（P3 之前的老库因此可用，但报告里明确显示
    “0 named, N adopted”）。已存在的 review 记录永远不会被 `--write` 覆盖，所以
    `--write` 不能把未复核的变更变成已审核。
32. **`needs_recheck` 的四个理由。** `content_changed`（Case 自身内容变了）、
    `dependency_changed`（上游内容/依赖变了，附具体 upstream ID）、`source_stale`
    （上游 Source 带人工 `stale: true`）、`no_review_baseline`（有 baseline 之后新
    出现、却没有任何 review 记录的 reviewed Case）。在第一次 `--write` 之前整库都是
    “P3 之前的库”，此时不把“没有 review 记录”算成待复核，只报 `baseline: missing`。
33. **人工 stale 必须显式清除，复核不能替代。** `review approve` 遇到上游 Source
    `stale: true` 会拒绝（`TRACE_REVIEW_BLOCKED`），提示先显式清掉来源的 stale 标记；
    只重跑测试通过、只复核用例都不能清它（方案 §3.4）。`stale` 标记本身不进内容摘要，
    所以“清除 stale”不会再次触发一轮依赖变更。
34. **草稿批次独立成图，晋级只搬一个实体。** 草稿在
    `draft/<batch-id>/{sources,testpoints,cases}/<ID>.yaml`；`check --include-draft`
    逐批用“正式库 + 本批”的候选图校验（不同批之间互相不可见，依赖别的未晋级批次会报
    悬空）。`review approve --id` 只晋级**一个**实体，候选图也只加这一个，因此
    “Case 依赖同批 TP”会明确报“approve it first”，而不是先晋级出一个断链。晋级顺序
    天然是 Source → TP → Case。草稿文件里 TP/Case 保持 `status: draft`（诚实反映它
    住在 `draft/`），晋级时改写为 `reviewed`；晋级写 YAML 会经过 `safe_dump`，
    **会丢注释与原有排版**（见限制 18）。
35. **更新草稿必须带 `base_content_hash`。** 新草稿占用正式库已有 ID 会被拒绝
    （`TRACE_DRAFT_ID_CONFLICT`）；更新草稿必须声明 `base_content_hash`，且等于当前
    正式实体的内容摘要，否则 `TRACE_DRAFT_BASE_MISMATCH`（方案 §3.1：不能默默覆盖
    别人的修改）。草稿 ID 在所有批次内也必须唯一。
36. **审核记录写在索引里，不写回 YAML。** 方案 §3.4 原本建议把 `reviewed_by`/
    `reviewed_at`/`reviewed_content_hash` 存进实体；本次按任务约定统一放进索引
    （`reviews`），因为内容摘要排除了审核元数据，两种位置对有效性计算等价，而索引
    不会污染 YAML diff。`review approve` 记录 reviewer（可空）、UTC 时间、内容摘要、
    依赖指纹与备注；对**已存在的正式 TP/Case** 调用即“重新复核”（不写文件，只更新
    索引），这正是清除 `needs_recheck` 的正规入口。Source 没有审核状态：晋级 Source
    草稿只写 baseline，不写 review 记录。
37. **驳回留在 `draft/`，按文件摘要失效。** `review reject` 在索引里记
    `drafts["<batch>/<id>"] = {file_hash, status: rejected, reviewer, at, note}`，文件
    原地不动；只要文件内容不变就一直显示 rejected 且拒绝晋级，改过内容就自动回到
    pending。`check --include-draft` 跳过 rejected 草稿（它们已被明确否决）。
38. **`impact` 复用既有图与同一份 stale 判定。** 查询走 `TraceGraph` 的反向索引
    （不重新遍历文件），`needs_recheck` 走 `staleness.recheck_map()`，因此
    `impact`、`stale`、`failure` 三处结论不会互相漂移。脚本条目给出
    `binding`/`file`/`nodeid`/`resolves`。删除/重命名后的“旧图影响面”不在 P3（见限制 20）。
39. **`failure` 用运行快照回溯，并说明与当前资产的差异。** 失败结果从 manifest 的
    `asset_snapshot.relations`（case → TP/Source）与 P3 新增的
    `asset_snapshot.testpoint_sources`（TP → Source）还原**当时**的链；快照缺失时才
    退回当前库，并在 `chain.origin` 里写明 `snapshot`/`current`/`missing`。再对比
    `asset_snapshot.cases[<id>]` 与当前文件 SHA-256 给出 `changed_since_run`，并附
    当前 `needs_recheck` 与“最近一次运行”（扫描 `runs/*/manifest.json` 取最新）。
40. **晋级是“先校验、再单文件原子替换、再记索引”。** 校验失败时正式库一个字节都不
    改（测试用目录摘要对比证明）；文件写入用同目录临时文件 + `os.replace`。多实体
    事务、写锁与中断恢复不在 P3 范围（见限制 19），但单实体晋级不会留下半截文件。

### 2.5 P4（新增）

41. **接进已有工作台，不另建页面。** 「追溯」是 `QaWorkbench` 的第 6 个标签，路由挂在
    已有 `/api/qa/*` 前缀下，鉴权复用 `QaApi._authorized` 与同一个
    `check_api_token`；写入仍然只走已认证 WebSocket 的 mutation 通道
    （`QA_MUTATION_PATHS` 自动并入 `WebUIMutationPaths`，普通 POST 一律 405）。
    没有新的进程、端口、数据库或前端依赖。
42. **适配器只做选择与塑形，不算指标。** `nanobot/qa/trace_api.py` 的每个接口都是
    `qa_trace` 库函数的一层薄封装：`summary` = `run_check` + `build_report`，
    `tree` = `load_project` + `TraceGraph` + `recheck_map`，`impact`/`stale`/`drafts`/
    `failure` 直接调用同名领域函数。四个指标、`needs_recheck`、链回溯、审核规则只有
    一份实现，工作台与 CLI 不会给出两个答案。
43. **项目根由环境变量决定，项目 ID 只允许目录名。** `NANOBOT_QA_TRACE_ROOT` 优先，
    默认 `<repo>/qa-workbench/projects`（每次调用时求值，测试与演示可以指到临时目录）。
    `?project=<id>` 只接受 `^[A-Za-z0-9][A-Za-z0-9._-]*$` 且必须是根下的真实目录，
    不允许 `..` 或绝对路径；不传时取排序后的第一个项目，绝不跨项目读取。
44. **错误映射沿用 QA API 契约。** 库里的 `EntityNotFoundError`/`DraftNotFoundError`/
    `RunNotFoundError` → 404，`DraftIdConflictError`/`DraftBaseMismatchError`/
    `ReviewBlockedError` → 409，其余 `QaTraceError`（项目/YAML/schema/索引/manifest
    不可用、缺参数）→ 400。适配器用装饰器统一翻译，所以路由里看不到
    `try/except QaTraceError` 的重复代码；`summary` 对**结构错误**不抛异常，而是照
    `build_report` 的约定返回 `valid: false` + `metrics_suppressed`，页面才能显示诊断
    而不是白屏（`tree` 需要可加载的库，结构错误时是 400）。
45. **三个动作与它们的边界。** `qa.trace.stale_write` = `compute_stale(write=True)`：
    只推进 baseline（并“采纳”尚无审核记录的老库），不产生 review；`review_approve`
    = 晋级一个草稿或重新复核一个正式 TP/Case（清除 `needs_recheck` 的正规入口）；
    `review_reject` 只记驳回，文件留在 `draft/`。工作台不提供“跳过校验直接入库”的按钮，
    Agent 也没有晋级工具。
46. **页面不轮询。** 一次 `summary` 会跑完整库校验，按 3 秒轮询代价过高；追溯页只
    在挂载、切换项目、点「刷新」或动作成功后重新拉取。四个指标卡分开渲染，页面上
    没有任何“总覆盖率”合并数字；`percent: null`（分母 0）显示 `N/A` 而不是 100%。
47. **演示项目是真实资产。** `qa-workbench/projects/login-lock/` 用 `qa_trace` 自己的
    规则校验通过（`trace check` 退出 0），脚本里的断言**故意失败**（产品第 5 次失败
    仍返回 401，需求要求 423），失败运行由 P2 插件真实产生并写进 `runs/<run-id>/`，
    因此 `trace failure` 的 `case → TP → Source` 回溯是真实数据而不是手写 JSON。

### 2.6 P5（新增）

48. **基线来自 git，不来自工作区。** `--base <ref>` 先 `git rev-parse --verify
    <ref>^{commit}` 解析成完整 SHA，再用 `git archive --format=tar <commit> --
    <project-path>` 把项目子树物化到 `tempfile.TemporaryDirectory()`，两侧都跑同一个
    `run_check` + `build_report`。工作区只读：不 checkout、不 stash、不写
    `.qa-trace/`；未提交的改动永远是 head 侧，不可能冒充基线。归档流用 `tarfile`
    解析，逐个成员校验不越出临时目录（`filter="data"`），归档路径不会污染报告
    （文档里不出现临时目录）。
49. **比较只读两份 report，不重算指标。** 诊断按
    `(severity, code, entity_id, path, field, message)` 求差集（new / resolved）；
    六个比率逐项比较（需求 reviewed、需求 current_valid、行为 reviewed、行为
    current_valid、自动化 reviewed、孤儿 library）；悬空引用数、孤儿用例 ID 集合、
    需求缺口两份清单、`needs_recheck` 集合分别求差。规则、指标、排序只有
    `check`/`report` 一份实现，`diff` 不复制逻辑。
50. **退出码 2 只留给 git/基线输入。** 库内容错误（含 YAML/schema）算“新增 error”，
    即回归 1——`diff` 回答的是“这次改动是否让库变差”，不重新定义 `check` 的 2。
    git 不可用、不是 work tree、`--base` 未知、项目在该 commit 不存在、容差非法才
    是 2（`TRACE_DIFF_*`）。
51. **容差用百分点，CLI 覆盖项目配置。** 默认 `0`；`project.yaml` 的
    `thresholds.diff_coverage_tolerance` 提供默认值，`--coverage-tolerance` 覆盖它
    （文档 `tolerance.source` 记录 `cli|project|default`）。孤儿率方向相反（升高才算
    变差）；任一侧 `percent: null`（分母 0 或指标被抑制）记 `comparable: false`，
    不判回归。
52. **基线结构错误时只比诊断。** base 侧 `valid: false` 时 `build_report` 本就不输出
    覆盖率，`diff` 把 `base.metrics_available` 置 `false`、六个比率
    `comparable: false`，只用 new/resolved 诊断与悬空/孤儿计数判断；修好基线的 PR
    退出 0（resolved 不是回归）。
53. **CI 用同一套 CLI，优先 `qa` 再退回 `python -m qa_trace`。** GitHub Actions 里
    `pip install -e ".[dev]"`（editable 安装跳过 WebUI 构建，同时生成 `qa` 入口点），
    之后每条命令先探测 `command -v qa`，没有入口点就用 `python -m qa_trace`；PR 的
    `--base` 是 `origin/${{ github.base_ref }}`（`fetch-depth: 0`）。pre-commit 是本地
    hook，只跑 demo 项目的快检，不联网、不拉远端仓库。

### 2.7 P6（新增）

54. **YAML 是唯一的用例真源，SQLite 的 `cases` 表降级为派生索引。** 写路径先写 YAML，
    再重建该项目的派生行（`replace_derived_cases`），所以任何时刻「磁盘上的文件」都是
    权威答案；索引只是让列表/过滤/搜索仍走一条 SQL。旧行（`derived = 0`）不删除，是
    回滚副本；当某条 YAML 用例通过 `legacy_id`（迁移时记录）**或同一个 `code`**（把提交的
    库部署到另一台单独 seed 过的数据库时，行 id 是本地的、`code` 才是业务身份）认领它时，
    它才从列表里隐藏——这样「迁移过的库」不会双份计数，「还没迁移的库」也不会因为新建
    一条 YAML 用例而突然少掉原来的用例。
55. **文件位置就是复核状态。** `cases/<ID>.yaml` 是正式库，`draft/<batch>/cases/<ID>.yaml`
    是草稿，`tombstones/<ID>.yaml` 是墓碑。没有额外的状态列：迁移一条文件、看一眼目录
    就知道它在哪一步。`status` 字段仍然写在文档里（`draft|reviewed|deprecated`），但
    「正式库」与「草稿」由目录决定，因为加载器只读 `cases/`。
56. **无链路的用例不能进正式库，这不是 bug 而是规则 5。** `Case.from_dict` 要求
    `testpoints` 或直挂 `sources`（直挂还要 `direct_reason`），所以一个只有标题/步骤的
    用例无法被 `cases/` 接受，否则整个项目都 unloadable。因此：迁移出来的 SQLite 用例
    （天生没有链路）全部写进 `draft/`；更新接口允许把 `status` 记成 `reviewed`，但只要
    没有链路，文件仍留在 `draft/`，响应里带 `needs_links: true`，页面对此事明示。
    一旦补上测试点/来源再标记已评审，文件就移动到 `cases/` 并写入索引的 review 记录。
    晋级前还会加载一次项目、核对被引用的测试点/来源确实存在：写错 ID 直接 409，而不是
    把干净库变成一条悬空引用（`TRACE_REF_MISSING`）。
57. **删除是墓碑，不是 `rm`。** 删除把文档原地改成 `status: deprecated` 并加一个
    `tombstone: {at, from, reason, by}` 块，移动到 `tombstones/<ID>.yaml`；默认列表
    排除 `deprecated`，`?status=deprecated` 仍能查到，ID 分配器扫描墓碑因而**永不复用**
    已删除的编号（规则 5 的「ID 退休」在这里落地一半：没有 `ids/<id>.yaml` 台账，但
    墓碑足以阻止重用）。
58. **ID 用可读的计数器，不是 UUID4。** 迁移要求 `TC-<MODULE>-<seq>`，工作台里人也要读
    得懂，所以新增用例同样按「项目内该模块最大号 + 1」分配（补零到 3 位）。代价是并发
    写入可能撞号（见限制 41）；写文件本身是原子的，加载器也会对重名文件报
    `TRACE_ID_DUPLICATE`，不会静默覆盖。UUID4 仍然是 `draft new` / `qa trace` 内部
    新建实体的默认（P3 决定不变），两条路径互不影响。
59. **响应形状冻结成兼容层，新字段只增不改。** `qa_case` 工具与 `/api/qa/cases*` 继续
    返回 `id/code/title/kind/priority/status/preconditions/steps/api/expected/tags/source/
    author/created_at/updated_at/project_id`，`kind↔type`、`status` 的翻译只在
    `qa_trace/compat.py` 里做一次；新增字段（`type/trace_status/testpoints/sources/script/
    needs_recheck/draft/batch/yaml_path/legacy_id/legacy/needs_links`）是纯增量，旧客户端
    忽略即可。WebUI 的 `normalizeCase` 对每个新字段做防御式归一化。
60. **`api` 块是一等字段，不是 `data` 里的自由 JSON。** 工作台的「API 定义」直接映射到
    用例文档的 `api:`（`request/assertions/variables`），加载期就拒绝无法执行的结构
    （缺 `request.path`、`assertions` 不是列表等），执行器（`nanobot/qa/runner.py`）
    继续消费同一形状。用例的 `steps` 仍是必填：API 用例没有显式步骤时，从请求与断言
    派生一条（`GET /api/products` + `HTTP 200；$.code equals 0`），保证文档可加载。
61. **摘要把新字段算进去，但配方版本必须提升。** `code/expected/api/legacy_id` 都是业务
    字段（改了就应触发复核），因此 `FINGERPRINT_VERSION = 2`；旧索引在**读**路径被拒绝
    （`require_compatible`，提示 `stale --write`），在**写**路径按空索引重建
    （`load_index_for_write`）——派生数据不该让一次编辑失败。
62. **迁移只读数据库、只写 YAML，且可重复执行。** `qa trace migrate-sqlite` 用
    `mode=ro` 打开 SQLite（测试用字节对比证明库文件未变），逐项目导出：保留 `code`、
    写入 `legacy_id`、新 ID 从项目内最大号续；已经导出过的行按 `legacy_id` 跳过，所以
    重跑不会产生第二份用例。`deprecated` 行写成墓碑；其余一律草稿（理由见决定 56）。
63. **索引重建有两个入口，读路径还会自愈一次。** `nanobot qa reindex` 是显式命令；
    另外 `CaseFiles` 发现某项目「有 YAML 用例但一条派生行都没有」（新检出、刚迁移）时
    会就地重建一次，避免用户第一次打开页面看到空列表。已经有了派生行的项目不会被
    自动重建——否则每次读都等于一次全量扫描；手工改完 YAML 请跑 `reindex`。
64. **旧行是可读的只读视图。** 尚未迁移的 SQLite 行仍然出现在列表里（`legacy: true`），
    详情可看，但更新/删除会返回 409 并提示先跑 `qa trace migrate-sqlite`。这样「先 seed
    再迁移」的演示顺序不会在中间态看起来像坏页面。
65. **归档/评审都走既有 mutation，不新增动作。** 「标记为已评审」= `qa.case.update`
    带 `status=ready`；「归档」= `qa.case.delete`（带可选 `reason`）。`QA_MUTATION_PATHS`
    不扩张，WebUI 的 CSRF/写通道规则不变；审核身份仍是自填的 `reviewer`（与 P4 相同）。
66. **演示库随仓库提交。** `qa-workbench/projects/shop/` 是真实迁移产物（8 条用例），
    和 `login-lock` 一起作为演示数据；`.qa-trace/` 仍在 gitignore 里，SQLite 库不进仓库。

## 3. 规则码

### 3.1 P0（文档层，全部 error）

| code | 触发条件 |
|---|---|
| `TRACE_ID_INVALID` | ID 缺失、语法错误、`new_id` 参数非法 |
| `TRACE_ID_TYPE_MISMATCH` | ID 语法合法但前缀与实体/引用位置不符 |
| `TRACE_ID_DUPLICATE` | 同一项目内 ID 重复定义 |
| `TRACE_FILE_ID_MISMATCH` | 文件名与声明的 ID 不一致 |
| `TRACE_SCHEMA_VERSION` | `schema_version` 不是本版本认识的 1 |
| `TRACE_SCHEMA_INVALID` | 文件根不是 mapping |
| `TRACE_FIELD_MISSING` | 必填字段缺失或为空（含空的 `steps`/`sources`） |
| `TRACE_FIELD_INVALID` | 字段类型/取值形态错误（含 sha256、时间戳） |
| `TRACE_ENUM_INVALID` | 枚举取值越界（priority、method、automation.status…） |
| `TRACE_EVIDENCE_MISSING` | Source 没有 evidence（所有 type 都要求） |
| `TRACE_LINK_MISSING` | Case 既没有 testpoints 也没有 sources |
| `TRACE_DIRECT_REASON_MISSING` | Case 直接挂 sources 但没有 `direct_reason` |
| `TRACE_STEP_EXPECTED_MISSING` | 步骤没有 expected 或 expected 为空白 |
| `TRACE_SCRIPT_INVALID` | 脚本绑定不是 `<file>::<nodeid>` |
| `TRACE_YAML_INVALID` | YAML 无法读取或解析 |
| `TRACE_YAML_DUPLICATE_KEY` | YAML mapping 重复 key |
| `TRACE_PROJECT_INVALID` | 项目目录、`project.yaml` 或阈值配置不可用 |
| `TRACE_ERRORS` | 一次扫描发现多条错误时的聚合错误 |

### 3.2 P1（图层）

| code | 级别 | 规则 | 触发条件 |
|---|---|---|---|
| `TRACE_REF_MISSING` | error | 2 | `sources` / `testpoints` / `automation.script` 指向不存在的实体或文件 |
| `TRACE_REF_TYPE_MISMATCH` | error | 2 | 引用解析到错误的实体类型，或脚本目标不是 `.py` |
| `TRACE_REF_OUTSIDE_PROJECT` | error | 2 | 脚本目标越出项目根目录 |
| `TRACE_CASE_ORPHAN` | error | 3 | Case 无法 BFS 上溯到任何已存在的 Source |
| `TRACE_P0_RATIO_HIGH` | warn | 10 | reviewed Case 中 P0 占比 > `thresholds.p0_ratio_max` |
| `TRACE_SOURCE_NO_DOWNSTREAM` | info | 11 | active Source 没有任何下游 TP/Case（可能是漏测） |
| `TRACE_SOURCE_DRAFT_ONLY` | info | 11 | active Source 的下游全是 draft，没有任何 reviewed Case |
| `TRACE_NEEDS_RECHECK` | info | 12 | stale Source 的下游 Case（派生，不写回文件） |
| `TRACE_DIRECT_REASON_MISSING` | warn | 13 | 直挂 `sources` 但无 `direct_reason`（模型层是 error，见决定 14） |

规则 1/4/5/6/7 属于 P0 已完成的文档层规则；规则 8（预期结果是否含可观察对象）是
语义判断，P1/P2 都不做；规则 9（脚本 marker 双向一致）由 P2 的 marker lint 实现，
见 §3.3。

### 3.3 P2（marker 与运行记录）

| code | 级别 | 规则 | 触发条件 |
|---|---|---|---|
| `TRACE_MARKER_MISMATCH` | error | 9 | `automation.status=done` 的用例在绑定脚本里找不到自己的 marker；或 marker 在文件里但挂在别的 nodeid 上 |
| `TRACE_MARKER_ORPHAN` | error | 9 | 绑定文件里的 marker 指向一个没有绑定该文件的用例（manual、无 script、指向别处） |
| `TRACE_MARKER_UNKNOWN` | error | 9 | marker 里的 ID 语法非法，或不是本项目定义的 Case |
| `TRACE_MARKER_UNREADABLE` | error | 9 | 绑定脚本无法读取或 `ast` 解析失败，marker 无从校验 |

`qa trace check` 的退出码不变（这些 error → 1）；pytest 插件的 marker 校验失败是
pytest 的 usage error（退出码 4），与 `qa` CLI 的退出码是两套契约。

### 3.4 P3（复核、入库与查询）

P3 的错误码分两类：**输入/工具失败**（退出码 2）与**资产/流程拒绝**（退出码 1）。

| code | 退出码 | 触发条件 |
|---|---|---|
| `TRACE_INDEX_INVALID` | 2 | `.qa-trace/index.json` 不是合法 JSON、版本不认识、属于别的项目、`fingerprint_version` 不匹配 |
| `TRACE_DRAFT_INVALID` | 2 | `draft` 命令参数不可用（kind/module/batch 非法、`--file` 不存在、缺父依赖、`base_content_hash` 无对应正式实体） |
| `TRACE_RUN_NOT_FOUND` | 2 | `qa trace failure --run` 指向的 manifest 不存在或读不了 |
| `TRACE_RUN_INVALID` | 2 | manifest 不是 JSON、根不是 mapping、缺 `run_id`、`results` 不是列表 |
| `TRACE_ENTITY_NOT_FOUND` | 1 | `impact`/`review approve` 的 ID 不是该类型的实体 |
| `TRACE_DRAFT_NOT_FOUND` | 1 | 没有携带该 ID 的草稿（或跨批次重名，需要 `--batch`） |
| `TRACE_DRAFT_ID_CONFLICT` | 1 | 草稿要占用正式库已有 ID 却没有 `base_content_hash`；草稿 ID 重复 |
| `TRACE_DRAFT_BASE_MISMATCH` | 1 | `base_content_hash` 与正式实体当前内容摘要不一致（别人改过了） |
| `TRACE_REVIEW_BLOCKED` | 1 | 晋级/复核被业务规则拒绝：草稿结构无效、候选图有 error、依赖仍是草稿、上游 Source deprecated/observed/stale、上游 TP 未 reviewed、草稿已被驳回、对 Source 调用复核 |

`qa trace stale` 不产生新的错误码：变更与待复核是**报告内容**而不是诊断；只有索引
读不了才是 `TRACE_INDEX_INVALID`（退出码 2）。

### 3.5 P4（HTTP 层）

P4 不新增规则码：工作台接口把 P0–P3 的错误原样带出，只换一层 HTTP 语义。响应体
统一是 `{"ok": false, "error": "<CODE>: <path>: <message>"}`，`error` 里保留库的
`code`，所以页面显示的错误与命令行看到的是同一条诊断。

| HTTP | 触发条件 | 典型 code |
|---|---|---|
| 401 | token 校验失败（与其它 `/api/qa/*` 路由一致） | — |
| 404 | 未知项目、未知实体/草稿/运行、未知 trace 路由 | `TRACE_ENTITY_NOT_FOUND`、`TRACE_DRAFT_NOT_FOUND`、`TRACE_RUN_NOT_FOUND` |
| 405 | 未走 WebSocket mutation 通道的写请求 | — |
| 409 | 草稿冲突、基线不匹配、审核被业务规则拒绝 | `TRACE_DRAFT_ID_CONFLICT`、`TRACE_DRAFT_BASE_MISMATCH`、`TRACE_REVIEW_BLOCKED` |
| 400 | 参数缺失、项目/YAML/schema/索引/manifest 不可用、链无法加载 | `TRACE_PROJECT_INVALID`、`TRACE_SCHEMA_*`、`TRACE_YAML_*`、`TRACE_INDEX_INVALID`、`TRACE_RUN_INVALID` |
| 500 | 未预期异常（记日志，不把栈返回给浏览器） | — |

`GET /api/qa/trace/summary` 是例外：结构错误不产生 4xx，而是返回
`valid: false` + `metrics_suppressed` + `diagnostics`，让页面显示“先修断链”而不是
一个成功含义的覆盖率。

### 3.6 P5（diff 输入错误码）

P5 不新增校验规则（库内容仍由 P0–P3 的规则码判定），只新增 5 个“输入不可用”码，
全部进 `diagnostics.INPUT_ERROR_CODES`、映射退出码 2：

| code | 触发条件 |
|---|---|
| `TRACE_DIFF_NOT_GIT` | 项目目录不在 git work tree 里（`git rev-parse --show-toplevel` 失败） |
| `TRACE_DIFF_BASE_UNKNOWN` | `--base` 无法解析成 commit（拼错、浅克隆缺历史、不是本仓库的 ref） |
| `TRACE_DIFF_BASE_MISSING` | 该 commit 下没有 `<project-path>/project.yaml`（项目是本次改动新建的） |
| `TRACE_DIFF_GIT_FAILED` | 找不到 git 可执行文件，或 `git archive` 失败、归档流不可读、含越界路径 |
| `TRACE_DIFF_INVALID` | `--coverage-tolerance` 为负，或 `thresholds.diff_coverage_tolerance` 不是非负数 |

### 3.7 P6（迁移输入错误码）

P6 不新增校验规则（库内容仍由 P0–P3 的规则码判定），只新增一个「工具输入不可用」码：

| code | 退出码 | 触发条件 |
|---|---|---|
| `TRACE_MIGRATE_INVALID` | 2 | `migrate-sqlite` 的数据库不存在/打不开、库里有 `projects`/`cases` 之外的表结构（不是 QA 库）、`--project` 指向不存在的项目、既没给 `--db` 也没有 `NANOBOT_QA_DB` |

`qa trace reindex` 是产品命令（`nanobot qa reindex`），失败沿用 QA API 的错误类型：
未知项目 → `QaNotFoundError`（CLI 里是 `typer.BadParameter`）；磁盘/YAML 不可读 →
`QaValidationError` 或直接抛 `QaTraceError`（不被吞掉）。

## 4. 退出码

`qa trace check` 与 `qa trace report` 使用同一套退出码：

| code | 含义 | 触发条件 |
|---|---|---|
| 0 | 干净 | 没有 error；warn/info 不阻塞（除非 `strict: true`） |
| 1 | 规则失败 | 任一 error（ID、字段、枚举、证据、链接、步骤、悬空、孤儿…）；`strict` 下出现 warn |
| 2 | 输入/配置/工具失败 | 项目目录或 `project.yaml` 缺失、YAML 不可解析、文件根不是 mapping、`schema_version` 未知、阈值非法 |

映射为 2 的码固定为：`TRACE_PROJECT_INVALID`、`TRACE_SCHEMA_INVALID`、
`TRACE_SCHEMA_VERSION`、`TRACE_YAML_INVALID`、`TRACE_YAML_DUPLICATE_KEY`
（`diagnostics.INPUT_ERROR_CODES`）；其余 error 一律 1。

`trace report` 即使最终退出 1 也会先完整输出报告（JSON 或文本），这样同一个命令既能
“看”又能“卡”。P0 的 `qa trace check` 只区分 0/1，P1 按方案 §4 补齐 2，因此
`test_loader.py` 中“项目目录不存在”的断言从 1 改为 2（契约变更已在此登记）。

P2 的 pytest 插件使用 pytest 自己的退出码，不改动 `qa` CLI 的 0/1/2 契约：

| pytest 退出码 | 含义 | P2 行为 |
|---|---|---|
| 0 / 5 | 通过 / 没收集到测试 | 写 `status=complete` 的 manifest（5 时结果为空） |
| 1 | 有测试失败 | 照常写 `status=complete`，`exitstatus=1` |
| 2 / 3 | Ctrl-C 中断 / internal error | 写 `status=incomplete` 的 manifest，不伪造成成功 |
| 4 | marker 校验或项目库加载失败（`pytest.UsageError`） | 不写 manifest，错误进 stderr |

`--collect-only` 写 `status=collect_only`：`results` 为空，`summary.collected` 是真实
收集数。manifest 写盘失败只打印一行红字，不篡改测试退出码，也不会写出半个 JSON。

P3 各命令的 0/1/2 含义（全部实测，见 §8）：

| 命令 | 0 | 1 | 2 |
|---|---|---|---|
| `trace check [--include-draft]` | 无 error（warn/info 不阻塞，除非 `strict`） | 任一 error（含草稿批次） | 项目/YAML/schema/阈值不可用 |
| `trace report [--json]` | 同上 | 同上（仍先输出完整报告） | 同上 |
| `trace impact` | 目标存在，输出影响面 | 目标 ID 不存在或类型不符 | 项目/索引不可用 |
| `trace stale` | 没有变更、没有待复核 | 有变更或有待复核 | 索引不可用/版本不匹配 |
| `trace stale --write` | 记录 baseline 后无待复核 | 记录成功但仍有待复核（如 stale 来源） | 索引不可用 |
| `trace draft new/add` | 草稿已写入 | 草稿 ID 冲突/基线不匹配 | 参数或项目不可用 |
| `trace review list` | 输出草稿清单 | — | 项目/索引不可用 |
| `trace review approve` | 晋级成功或复核记录已更新 | 未知 ID、无效草稿、冲突、被规则拒绝 | 项目/索引不可用 |
| `trace review reject` | 驳回已记录 | 没有该草稿 | 项目/索引不可用 |
| `trace failure` | manifest 已读出（可以 0 条失败） | `--case` 指定的用例本次没跑 | manifest 缺失/不可读 |

P5 的 `qa trace diff` 单独一套（它不判“库是否合法”，只判“这次改动是否变差”）：

| code | 含义 | 触发条件 |
|---|---|---|
| 0 | 无回归 | 没有新增 error 诊断；六个比率没有比基线差超过容差；悬空引用数与孤儿用例没有增加 |
| 1 | 回归 | 新增任一 error 诊断（含 YAML/schema 等结构错误）、新增悬空引用、新增孤儿用例、任一指率变差超过 `--coverage-tolerance`（孤儿率是升高）；仍然先输出完整 JSON/文本 |
| 2 | 输入/工具失败 | 项目目录缺失、不在 git work tree、`--base` 未知、项目在该 commit 不存在、git 不可用、容差非法（`TRACE_DIFF_*`） |

`diff` 的 2 与 `check` 的 2 语义不同：`check` 把“库读不出来”当 2，`diff` 把它当
“新增 error”= 1，因为 diff 的结论必须是“变差/没变差”，而 CI 对 1 和 2 都是失败。

P6 的迁移只有两个退出码：`0`（已导出，可能跳过了一些已迁移的行）与 `2`
（`TRACE_MIGRATE_INVALID`：数据库/项目/参数不可用）。它不判断库是否合法（迁移出来的
草稿本来就没有链路，正式库仍然是空的且 `check` 退出 0），因此不存在 1 的含义。

## 5. 覆盖范围

### 5.1 P0

实体形状、必填字段、枚举、ID 语法与类型前缀、证据要求、步骤 expected、Case 关联
规则、脚本绑定形态、YAML 安全解析、文件名/重复 ID 结构规则。

### 5.2 P1

- 引用存在性与目标类型：`testpoints[].sources`、`cases[].testpoints`、
  `cases[].sources`、`automation.script` 目标文件。
- 正/反向邻接表与 `case → source` BFS 上溯，孤儿用例报 error。
- 规则 10（P0 占比 warn，阈值可配）、11（无下游 Source / 仅 draft 下游 info）、
  12（stale 传播，派生 `needs_recheck`，不落盘）、13（直挂无理由，warn）。
- 四个指标分开报：需求覆盖率、行为覆盖率、自动化率、孤儿率；另有需求缺口（两份
  清单）、悬空引用数、死资产、`needs_recheck`。
- `qa trace check`（error/warn/info + 0/1/2）、`qa trace report [--json]`。
- reviewed 与 current_valid 双口径；未确认来源单列。

### 5.3 P2

- 规则 9 双向 marker 对照（用例缺 marker / marker 无人认领 / ID 未知或非法 /
  脚本不可解析），诊断带 `code`、`path`、`field`，`qa trace check` 退出码沿用 0/1。
- `@pytest.mark.case("TC-...", ...)`：一个 node 可声明多个用例；未知/非法 ID 在
  collection 阶段中止（pytest 退出码 4）。
- run manifest：run_id、UTC 起止、状态（complete / incomplete / collect_only）、
  环境、工具版本、git commit（有则填）、库快照（内容摘要 + 关系）、脚本摘要、
  每个 nodeid 的 outcome / failure_stage / 截断错误摘要 / 耗时、按用例的实例聚合、
  未带 marker 的 nodeid 清单。
- 参数化结果聚合：一个参数实例失败，用例汇总就是 failed；xfail/xpass 单独记
  `xfailed` / `xpassed`，skip 记 `skipped`，fixture/setup 异常记 `error`。
- 原子写入：同目录临时文件 + `os.replace`，不留半截 JSON。
- 覆盖 `pytester` 真实嵌套会话：通过、失败、跳过、error、xfail、xpass、参数化、
  多 marker、未知 ID、非法 ID、非字符串参数、无法加载的项目库、`--collect-only`、
  无选项不写文件、只给 `--qa-run-dir`。

### 5.4 P3

- **内容摘要与依赖指纹**：每个 Source/TP/Case 一条内容摘要 + 一条传递依赖指纹；
  排除审核元数据、`stale`、派生字段与未知字段；排版/键序变化不触发复核。
- **派生索引** `<project>/.qa-trace/index.json`：baseline、reviews、草稿驳回记录；
  原子写入；版本/项目/指纹配方不匹配即拒绝；删除后可重建。
- **`qa trace stale`**：变更实体清单（content/dependency/新增/删除）、下游待复核
  Case 与四个理由（`content_changed`/`dependency_changed`/`source_stale`/
  `no_review_baseline`）；`--write` 记录新 baseline 并“采纳”尚无 review 记录的
  reviewed TP/Case，但绝不覆盖已有 review。
- **`qa trace impact`**：给定 Source/TP/Case，列出受影响 TP、Case（含 `via` 路径、
  `needs_recheck`、原因、变化 ID）与脚本（`binding`/`file`/`nodeid`/`resolves`）。
- **草稿批次**：`draft new`（UUID4 骨架）与 `draft add`（导入外部 YAML）；默认不参与
  `check`/覆盖率，`check --include-draft` 逐批用候选图校验。
- **`qa trace review`**：`list`（批次/状态/有效性/问题）、`approve`（晋级或复核，
  校验失败/冲突/业务阻塞一律拒绝且不改正式库）、`reject`（留在 `draft/`，按文件摘要
  失效）。
- **`qa trace failure`**：manifest 失败结果 → Case → TP → Source（优先用运行快照）、
  与当前资产的差异（`changed_since_run`）、当前 `needs_recheck`、最近一次运行。
- **`check --include-draft`** 与 P3 错误码/退出码矩阵（§3.4、§4）。

### 5.5 P4

- **工作台入口**：已有「QA 工作台」新增「追溯」标签（`QaWorkbench` + `QaTrace.tsx`），
  项目选择、四个指标卡、链树、影响面、变更/待复核、草稿审核、失败回溯都在同一页。
- **HTTP 接口**（全部 `GET`，除注明外只读）：

  | 路径 | 作用 |
  |---|---|
  | `GET /api/qa/trace/projects` | 列举根目录下的项目（含坏项目与其错误） |
  | `GET /api/qa/trace/summary?project=` | 报告指标 + counts + stale/drafts/runs 摘要 |
  | `GET /api/qa/trace/tree?project=` | Source → TestPoint → Case → Script 链（含孤儿） |
  | `GET /api/qa/trace/impact?project=&source=\|case=\|testpoint=` | 影响面 |
  | `GET /api/qa/trace/stale?project=` | 变更实体与待复核清单 |
  | `GET /api/qa/trace/drafts?project=&batch=` | 草稿批次 |
  | `GET /api/qa/trace/failure?project=&run=&case=` | 失败回溯 |
  | `GET /api/qa/trace/runs?project=` | 运行记录清单 |
  | mutation `qa.trace.stale_write` | `/api/qa/trace/stale/write`：记录基线 |
  | mutation `qa.trace.review_approve` | `/api/qa/trace/review/approve`：晋级/复核 |
  | mutation `qa.trace.review_reject` | `/api/qa/trace/review/reject`：退回草稿 |

- **演示项目**：`qa-workbench/projects/login-lock/`（REQ-LOGIN-01 + UI-LOGIN-02 →
  TP-LOGIN-005 → TC-LOGIN-003 → `scripts/test_login.py` → 一次真实失败运行）。
- **测试**：`tests/qa/test_trace_api.py`（适配器、HTTP 鉴权/405/错误映射、项目隔离）
  与 `webui/src/tests/qa-trace.test.tsx`（渲染、影响面请求、三个 mutation）。

### 5.6 P5

- **`qa trace diff --project <path> --base <git-ref> [--json]`**：
  - 基线侧：`git rev-parse` 解析 ref → `git cat-file -e <commit>:<project>/project.yaml`
    预检 → `git archive --format=tar <commit> -- <project>` → 安全解包到临时目录；
    工作区不动。
  - 两侧各跑一次 `run_check` + `build_report`（同一套规则/指标/排序），只比较两份
    report。
  - 比较内容：新增/已消除诊断、六个比率（需求/行为 × reviewed/current_valid、自动化、
    孤儿）、悬空引用数、孤儿用例 ID、需求缺口两份清单、`needs_recheck` 集合、
    counts（sources/testpoints/cases/reviewed_cases）。
  - 回归判定：新增 error、悬空数增加、孤儿 ID 增加、任一指率变差超过容差。
  - 容差：`--coverage-tolerance`（百分点）> `project.yaml`
    `thresholds.diff_coverage_tolerance` > `0`。
  - 退出码 0/1/2 见 §4；JSON 形状见 §7.8。
- **CI**：`.github/workflows/qa-trace.yml`（安装 → 测试 → demo 快检 → 报告 artifact →
  PR diff 门禁 → diff artifact）与 `.pre-commit-config.yaml`（本地快检 hook），
  见 §8.2。
- **测试**：`tests/qa_trace/test_diff.py`（12 条）。

### 5.7 P6

- **用例文档**：`code`（人读编号，`SHOP-API-001`）、`expected`（用例级预期）、`api`
  （结构化 `request/assertions/variables`）、`legacy_id`（迁移来源）；四个字段都参与
  内容摘要（`FINGERPRINT_VERSION=2`）。
- **用例文件布局**：`cases/`（正式）、`draft/<batch>/cases/`（草稿）、`tombstones/`
  （墓碑）；`TC-<MODULE>-<seq>` 分配扫描三个目录，墓碑占号因而 ID 不复用。
- **`qa_case` 工具**：list/get/create/bulk_create/update/delete 全部走 YAML；创建落在
  `draft/workbench/`（`status: draft`），删除写墓碑；响应形状与旧 SQLite 版本一致，
  另带链路徽标字段。
- **`/api/qa/cases*`**：列表/详情/导出/创建/批量创建/更新/删除/导入全部走 YAML；
  列表从派生索引读出（过滤/搜索/分页仍是 SQL），详情附带 YAML 链路徽标与
  `needs_recheck`。
- **派生索引**：`nanobot qa reindex [--project KEY] [--root DIR]` 从 YAML 重建
  `derived = 1` 的行；读路径在「有 YAML 无索引行」时就地重建一次；旧行被同 `legacy_id`
  或同 `code` 的派生行认领后隐藏，不删除。
- **迁移**：`qa trace migrate-sqlite [--project SHOP] [--db PATH] [--root DIR] [--batch ID]`
  只读导出 → `draft/sqlite-migration/cases/TC-<MODULE>-<seq>.yaml`，保留 `code`、
  写 `legacy_id`、`deprecated` 行进墓碑；重跑按 `legacy_id` 跳过。报告给出
  项目数/用例数/草稿/正式/墓碑/已迁移计数。
- **WebUI 「用例库」**：链路徽标列（来源/测试点/脚本/需复核/草稿区）、追溯链路编辑区
  （测试点/来源/直挂理由/风险）、显式「标记为已评审」、删除改为「归档」；草稿/已评审/
  已归档三种文案；未迁移的旧行显示「只读，请先迁移」。
- **测试**：`tests/qa_trace/`（compat、yamlfile、case 字段与摘要、caseyaml、migrate，
  共 65 条）与 `tests/qa/test_case_files.py`（19 条）、`webui/src/tests/
  qa-workbench.test.tsx` 新增 3 条链路/评审/归档用例。

## 6. P3 之后仍未覆盖（后续阶段）

| 阶段 | 未实现内容 |
|---|---|
| P2 剩余 | pytest collection 与真实 nodeid 对照（`--qa-project` 只校验用例 ID 存在性，不 collect 用户测试）、xdist 下的结果汇总 |
| P3 剩余 | 多实体晋级事务、项目写锁与中断恢复（方案 §7 的写锁/事务日志）、`ids/<id>.yaml` 分配与退休台账（`qa retire`）、`qa trace case` 单条追溯命令、基于基线的删除/重命名影响面、`qa source mark-stale --all --reason` |
| P4 剩余 | 工作台内的草稿**生成**（页面只审不生成，Agent 走 `qa trace draft new/add`）、后台任务与取消（追溯查询都是秒级同步读）、多项目对比视图、权限分级（能看追溯页的人就能审核） |
| P5 剩余 | 分支保护/必需检查的仓库设置（属仓库配置，不在代码里）、`qa trace diff` 之外的历史趋势（多基线、报告归档对比）、CI 上的完整 collection（`diff` 与 `check` 一样只做静态 marker lint）、`--strict` 下 warn 变化是否算回归的策略开关 |
| P6 剩余 | 多实体的 SQLite 迁移事务（逐文件写，无批次提交/回滚）、增量/差异迁移（每次都全表扫描）、把 SQLite 的 `scripts.case_ids` 映射到脚本绑定（`automation.script` 仍需人工补）、`migrate-sqlite` 之后自动 `reindex`（当前是两步）、并发写入下的 ID 分配台账 |

P1 曾经**不做**的 `trace case` / `impact` 查询，P3 已交付 `impact`；`trace case` 仍缺
（`impact --case` 覆盖了它的主要信息，但没有“单条用例全量视图”）。

P2 曾经**不做**的 `qa trace failure` 查询，P3 已交付。

P3 明确**不做**：把 pytest 结果回写用例 YAML、自动把用例标成 done、自动判定失败根因、
跨项目索引、向量检索、MeterSphere/Excel/Jira 适配器、CI 门禁脚本。

P4 明确**不做**：第二套工作台、外部平台同步、P5 的 Git/CI 门禁、在工作台里自动生成
用例或自动审核（页面只有人点的「通过 / 退回」）。

P5 明确**不做**：仓库侧的分支保护/必需检查配置、多基线与历史趋势、`git worktree`
或 checkout 基线（只用 `git archive` 读对象库）、完整 pytest collection、把 diff 结果
回写工作台（`diff` 只服务 CI，工作台仍看当前库）。

## 7. 报告 JSON 形状

`qa trace report --json` 输出（节选自 `fixtures/metrics_project`）：

```json
{
  "report_version": 1,
  "tool": {"name": "qa_trace", "version": "0.3.0"},
  "project": {"id": "metrics-demo", "name": "Metrics fixture - exact known numbers", "root": "tests/qa_trace/fixtures/metrics_project"},
  "valid": true,
  "counts": {"sources": 5, "active_sources": 5, "testpoints": 2, "cases": 4, "library_cases": 4, "reviewed_cases": 3, "dangling_references": 0},
  "coverage": {
    "requirement": {
      "label": "requirement", "types": ["req"],
      "reviewed": {"numerator": 1, "denominator": 2, "percent": 50.0},
      "current_valid": {"numerator": 1, "denominator": 2, "percent": 50.0},
      "uncovered": ["REQ-LOGIN-02"], "unconfirmed_sources": []
    },
    "behavior": {
      "label": "behavior", "types": ["ui", "api"],
      "reviewed": {"numerator": 1, "denominator": 2, "percent": 50.0},
      "current_valid": {"numerator": 1, "denominator": 2, "percent": 50.0},
      "uncovered": ["API-LOGIN-01"], "unconfirmed_sources": []
    },
    "automation": {
      "label": "automation",
      "reviewed": {"numerator": 1, "denominator": 3, "percent": 33.33},
      "provisional": true, "provisional_reason": "markers are linted statically (ast); pytest collection and execution are not part of qa trace check",
      "unresolved_scripts": []
    },
    "orphan": {
      "label": "orphan",
      "library": {"numerator": 0, "denominator": 4, "percent": 0.0},
      "case_ids": []
    }
  },
  "requirement_gaps": {
    "uncovered_requirements": ["REQ-LOGIN-02"],
    "cases_without_requirement_root": ["TC-LOGIN-004"],
    "count": 1, "uncovered_requirement_count": 1
  },
  "requirement_gap_count": 1,
  "dangling_count": 0,
  "dead_assets": {
    "sources_without_downstream": ["API-LOGIN-01"],
    "deprecated_cases": [],
    "manual_p0_cases": {"status": "unknown", "candidates": ["TC-LOGIN-002"], "note": "…"},
    "count": 1, "count_is_partial": true
  },
  "needs_recheck": [],
  "metrics_suppressed": null,
  "diagnostics": {
    "counts": {"error": 0, "warn": 1, "info": 1},
    "items": [
      {"severity": "warn", "code": "TRACE_P0_RATIO_HIGH", "entity_id": null, "path": "project.yaml", "field": "thresholds.p0_ratio_max", "message": "P0 cases are 1/3 (33.33%) of reviewed cases; threshold is 20.00%", "suggestion": "lower the priority of the extra P0 cases or raise thresholds.p0_ratio_max"},
      {"severity": "info", "code": "TRACE_SOURCE_NO_DOWNSTREAM", "entity_id": "API-LOGIN-01", "path": "sources/API-LOGIN-01.yaml", "field": "id", "message": "source API-LOGIN-01 has no downstream test point or case", "suggestion": "add a test point or a direct case, or deprecate the source"}
    ]
  }
}
```

约定：

- 顶层键集合固定（`test_report.py` 有断言），新增字段必须提升 `report_version`。
- 每个指标自带 `numerator` / `denominator` / `percent`；分母为 0 时 `percent` 为
  `null`，文本显示 `N/A`，绝不显示 100%。
- 四个指标是四个平级键，**没有**任何合并的“总覆盖率”。
- `percent` 四舍五入到两位小数，便于断言精确值。
- 指标被抑制时 `coverage`/`requirement_gaps`/`dead_assets` 为 `null`，
  `metrics_suppressed` 说明原因。

### 7.2 run manifest 形状（P2）

pytest 插件在会话结束后写 `runs/<run_id>/manifest.json`（或 `--qa-run-dir` 指定的
目录）。下面是一次真实运行（`fixtures/marker_ok` 作为库，两个测试一个通过一个失败）
的节选：

```json
{
  "manifest_version": 1,
  "run_id": "20261018T130041Z-91d06d69",
  "project_id": "marker-ok",
  "project_path": "F:\\xiangmu\\qa-agent\\tests\\qa_trace\\fixtures\\marker_ok",
  "status": "complete",
  "exitstatus": 1,
  "started_at": "2026-10-18T13:00:41.752979+00:00",
  "finished_at": "2026-10-18T13:00:42.890448+00:00",
  "tool": {"name": "qa_trace", "version": "0.3.0"},
  "tool_version": "0.3.0",
  "environment": "win32/python-3.12.7",
  "code_commit": "4d7e011e627de1d848c54ceb76738609cf677c3b",
  "script_digest": {
    "sha256": "c5abb3d8bd8263415764a7bbea077db1238336ca9db1b4913f600d3492100537",
    "files": {".qa-demo/demo_test.py": "3dc9dd0201a079d14bd4d1785f41db46e44470b6d11e4dea564d85932adad904"}
  },
  "asset_snapshot": {
    "project_id": "marker-ok",
    "root": "F:\\xiangmu\\qa-agent\\tests\\qa_trace\\fixtures\\marker_ok",
    "sources": {"UI-LOGIN-02": "5f8d5fa479aab65323e4874a7dba631d3d3d37715e67e12560caf27059353b81"},
    "testpoints": {"TP-LOGIN-005": "50b097bf73d078c932afcc678ffe6782956019b2818c7eef9e8d737123866484"},
    "cases": {"TC-LOGIN-003": "31142ee1c96ba4e89772e8939a0f05ae7ffc6aab2b53cbcbd681318a69a40b9d"},
    "relations": {"TC-LOGIN-003": {"testpoints": ["TP-LOGIN-005"], "sources": []}}
  },
  "summary": {
    "collected": 2, "results": 2, "cases": 1,
    "outcomes": {"cancelled": 0, "skipped": 0, "xfailed": 0, "passed": 1, "xpassed": 0, "failed": 1, "error": 0}
  },
  "results": [
    {
      "case_id": "TC-LOGIN-003",
      "nodeid": ".qa-demo/demo_test.py::test_lock_after_5_failures",
      "attempt": 1,
      "outcome": "passed",
      "started_at": "2026-10-18T13:00:41.846167+00:00",
      "finished_at": "2026-10-18T13:00:42.263063+00:00",
      "duration_ms": 416,
      "failure_stage": null,
      "error_summary": null
    },
    {
      "case_id": "TC-LOGIN-003",
      "nodeid": ".qa-demo/demo_test.py::test_remaining_attempts",
      "attempt": 2,
      "outcome": "failed",
      "started_at": "2026-10-18T13:00:42.263063+00:00",
      "finished_at": "2026-10-18T13:00:42.886939+00:00",
      "duration_ms": 4,
      "failure_stage": "call",
      "error_summary": "@pytest.mark.case(\"TC-LOGIN-003\")\n    def test_remaining_attempts():\n>       assert 1 == 2, \"remaining attempts should be 4\"\nE       AssertionError: remaining attempts should be 4\nE       assert 1 == 2\n\n.qa-demo\\demo_test.py:11: AssertionError"
    }
  ],
  "cases": [
    {
      "case_id": "TC-LOGIN-003",
      "outcome": "failed",
      "counts": {"cancelled": 0, "skipped": 0, "xfailed": 0, "passed": 1, "xpassed": 0, "failed": 1, "error": 0},
      "nodeids": [
        ".qa-demo/demo_test.py::test_lock_after_5_failures",
        ".qa-demo/demo_test.py::test_remaining_attempts"
      ],
      "attempts": 2,
      "duration_ms": 420,
      "error_summary": "…"
    }
  ],
  "unmapped_nodeids": [],
  "pytest": {
    "version": "9.1.1",
    "rootdir": "F:\\xiangmu\\qa-agent",
    "args": ["-p", "qa_trace.pytest_plugin", "--qa-project=tests/qa_trace/fixtures/marker_ok", "--qa-run-dir=.qa-demo/runs", ".qa-demo/demo_test.py", "-q"]
  }
}
```

约定：

- `manifest_version` 是 manifest 自己的版本；`Run.from_dict(manifest)` 必须能回读
  （P0 模型的 `run_id`/`project_id`/`started_at`/`finished_at`/`results`/`environment`/
  `tool_version`/`code_commit`/`asset_snapshot` 都在顶层，其余键进 `Run.extra`）。
- `status` 只有 `complete`、`incomplete`、`collect_only`；`exitstatus` 是 pytest 的
  退出码，不是 `qa` CLI 的。
- 每个 nodeid 一条 `results`（一个 node 声明多个用例时按用例展开），`attempt` 按用例
  从 1 递增；`cases[].outcome` 是最差实例结果，`counts` 保留每个实例的 outcome。
- `duration_ms` 是该 nodeid 的 setup+call+teardown 报告耗时之和；`error_summary`
  截断到 2000 字符并追加 `... (truncated)`。
- `asset_snapshot` 只存 SHA-256 与关系，不复制 YAML 正文；没有 Git 时
  `code_commit` 为 `null`，快照由内容摘要标识。
- `script_digest.files` 的键是相对 pytest rootdir 的 POSIX 路径（rootdir 之外用绝对
  路径），排序后参与合成摘要。
- `unmapped_nodeids` 是本次收集到但没有 `case` marker 的 nodeid。
- 写入是原子的：同目录隐藏临时文件 → `fsync` → `os.replace`；失败时删除临时文件，
  磁盘上不会出现半个 JSON。

### 7.3 派生索引形状（P3）

`<project>/.qa-trace/index.json`（派生、可删、不进 YAML）：

```json
{
  "index_version": 1,
  "fingerprint_version": 1,
  "project_id": "demo",
  "updated_at": "2026-10-18T13:21:08.135463+00:00",
  "baseline": {
    "TC-LOGIN-010": {
      "kind": "case",
      "content_hash": "95fa7ae4ba6535349853013f12a413ea474fa1474cb527818d369c171aa95188",
      "dependency_hash": "0f612c17859ad9b6a85b7449a2fd298a673488ca498b7a3077d62fd64ad1e96d",
      "upstream": {"TP-LOGIN-005": "022984d7660e31ec983e69abcad1c35f239bc14895dfb1da6b1a61781106cf2b"},
      "recorded_at": "2026-10-18T13:21:07.567924+00:00",
      "reviewed_by": null,
      "reviewed_at": null,
      "note": null,
      "adopted": false
    }
  },
  "reviews": {
    "TC-LOGIN-010": {
      "kind": "case",
      "content_hash": "95fa…5188",
      "dependency_hash": "0f61…e96d",
      "upstream": {"TP-LOGIN-005": "0229…cf2b"},
      "recorded_at": "2026-10-18T13:21:07.567924+00:00",
      "reviewed_by": "qa.li",
      "reviewed_at": "2026-10-18T13:21:07.567924+00:00",
      "note": "补充倒计时断言",
      "adopted": false
    }
  },
  "drafts": {
    "login-lock/TP-LOGIN-011": {
      "batch": "login-lock",
      "id": "TP-LOGIN-011",
      "kind": "testpoint",
      "file_hash": "315bebc6…e05395",
      "status": "rejected",
      "reviewed_by": "qa.zhang",
      "reviewed_at": "2026-10-18T13:21:08.135463+00:00",
      "note": "边界描述不清"
    }
  }
}
```

约定：

- `baseline` 的条目只有 kind/摘要/upstream/`recorded_at`，**没有** reviewer——
  它是“上次记录的状态”，不是审核。
- `reviews` 是审核（或 `--write` 采纳，`adopted: true` + `reviewed_by: null`）。
- `drafts` 只存驳回；文件摘要一变，草稿自动回到 pending。
- 删除整个文件即可重建；`stale` 会报告 `baseline: missing`。

### 7.4 `qa trace stale --json` 形状（P3）

```json
{
  "stale_version": 1,
  "project": {"id": "impact-demo", "root": "…/impact_project"},
  "baseline": "recorded",
  "fingerprint_version": 1,
  "written": false,
  "recorded": 0,
  "index": "…/impact_project/.qa-trace/index.json",
  "counts": {"changed": 4, "removed": 0, "needs_recheck": 1, "reviewed_cases": 3,
             "adopted_reviews": 4, "named_reviews": 1},
  "changed": [
    {"id": "REQ-LOGIN-01", "kind": "source", "content_changed": true,
     "dependency_changed": true, "in_baseline": true},
    {"id": "TC-LOGIN-002", "kind": "case", "content_changed": false,
     "dependency_changed": true, "in_baseline": true}
  ],
  "removed": [],
  "needs_recheck": [
    {"case_id": "TC-LOGIN-002", "reasons": ["dependency_changed"],
     "changed_ids": ["TP-LOGIN-002"], "reviewed_by": null}
  ]
}
```

### 7.5 `qa trace impact --json` 形状（P3）

```json
{
  "impact_version": 1,
  "project": {"id": "impact-demo", "root": "…/impact_project"},
  "target": {"id": "REQ-LOGIN-01", "kind": "source"},
  "counts": {"testpoints": 2, "cases": 2, "scripts": 1, "needs_recheck": 2},
  "testpoints": [
    {"id": "TP-LOGIN-001", "exists": true, "title": "连续失败计数与锁定阈值",
     "status": "reviewed", "method": "boundary", "risk": "high"}
  ],
  "cases": [
    {"id": "TC-LOGIN-001", "title": "密码连续错误 5 次锁定账号", "status": "reviewed",
     "priority": "P1", "automation": "done",
     "script": "scripts/test_login.py::test_lock_after_5_failures",
     "needs_recheck": true, "reasons": ["dependency_changed"],
     "changed_ids": ["TP-LOGIN-001"],
     "via": [{"source_id": "REQ-LOGIN-01", "testpoint_id": "TP-LOGIN-001"}]}
  ],
  "scripts": [
    {"case_id": "TC-LOGIN-001", "binding": "scripts/test_login.py::test_lock_after_5_failures",
     "file": "scripts/test_login.py", "nodeid": "test_lock_after_5_failures",
     "resolves": true, "problem": null}
  ],
  "sources": [
    {"id": "REQ-LOGIN-01", "exists": true, "type": "req", "title": "连续失败 5 次锁定账号",
     "status": "active", "confidence": "confirmed", "stale": false}
  ]
}
```

### 7.6 `qa trace review list|approve` 与 `failure` 形状（P3）

`review list --json`：`{review_version, project, counts{drafts,pending,rejected,invalid,
batches}, batches[], drafts[{batch,id,kind,path,status,valid,problems,content_hash,
base_content_hash,file_hash,rejected_by,rejected_at,note}]}`。

`review approve --json`：`{review_version, id, kind, mode(promoted|reviewed|rejected),
path, reviewed_by, reviewed_at, content_hash, dependency_hash, note, needs_recheck}`。

`failure --json`（节选）：

```json
{
  "failure_version": 1,
  "project": {"id": "impact-demo", "root": "…/proj"},
  "run": {"run_id": "20261018T131532Z-85270322", "status": "complete", "exitstatus": 1,
          "started_at": "…", "finished_at": "…", "environment": "win32/python-3.12.7",
          "code_commit": null, "tool_version": "0.4.0", "path": "…/manifest.json"},
  "requested_case": null,
  "case_missing": false,
  "counts": {"results": 2, "failed_results": 1, "failed_cases": 1, "reported_cases": 1},
  "failures": [
    {"case_id": "TC-LOGIN-001",
     "results": [{"nodeid": "demo_test.py::test_remaining_attempts", "attempt": 2,
                  "outcome": "failed", "failure_stage": "call",
                  "error_summary": "AssertionError: remaining attempts should be 4"}],
     "chain": {"origin": "snapshot",
               "testpoints": [{"id": "TP-LOGIN-001", "exists": true, "status": "reviewed"}],
               "sources": [{"id": "REQ-LOGIN-01", "exists": true, "type": "req",
                            "status": "active", "confidence": "confirmed", "stale": false}]},
     "current": {"exists": true, "status": "reviewed", "changed_since_run": false,
                 "needs_recheck": false, "reasons": [], "changed_ids": []},
     "last_run": {"run_id": "20261018T131532Z-85270322", "outcome": "failed",
                  "finished_at": "…"}}
  ]
}
```

### 7.7 工作台接口形状（P4）

所有 `/api/qa/trace/*` 读接口都返回 `{"ok": true, ...}`，字段名与库的 JSON 文档一致
（适配器只加 `trace_version`/`tool_version` 与 `project` 块，不改领域字段）。

`GET /api/qa/trace/summary?project=login-lock`（节选自演示项目，值取自真实运行）：

```json
{
  "ok": true,
  "trace_version": 1,
  "tool_version": "0.4.0",
  "project": {"id": "login-lock", "name": "登录锁定演示库（qa-trace P4）",
              "root": "…/qa-workbench/projects/login-lock", "modules": ["LOGIN"]},
  "valid": true,
  "counts": {"sources": 2, "active_sources": 2, "testpoints": 1, "cases": 1,
             "library_cases": 1, "reviewed_cases": 1, "dangling_references": 0},
  "coverage": {
    "requirement": {"label": "requirement", "types": ["req"],
                    "reviewed": {"numerator": 1, "denominator": 1, "percent": 100.0},
                    "current_valid": {"numerator": 1, "denominator": 1, "percent": 100.0},
                    "uncovered": [], "unconfirmed_sources": []},
    "behavior": {"label": "behavior", "types": ["ui", "api"],
                 "reviewed": {"numerator": 1, "denominator": 1, "percent": 100.0},
                 "current_valid": {"numerator": 1, "denominator": 1, "percent": 100.0},
                 "uncovered": [], "unconfirmed_sources": []},
    "automation": {"label": "automation",
                   "reviewed": {"numerator": 1, "denominator": 1, "percent": 100.0},
                   "provisional": true, "provisional_reason": "…", "unresolved_scripts": []},
    "orphan": {"label": "orphan",
               "library": {"numerator": 0, "denominator": 1, "percent": 0.0},
               "case_ids": []}
  },
  "requirement_gaps": {"uncovered_requirements": [], "cases_without_requirement_root": [],
                       "count": 0, "uncovered_requirement_count": 0},
  "requirement_gap_count": 0,
  "dangling_count": 0,
  "dead_assets": {"sources_without_downstream": [], "deprecated_cases": [],
                  "manual_p0_cases": {"status": "unknown", "candidates": []},
                  "count": 0, "count_is_partial": true},
  "needs_recheck": [],
  "metrics_suppressed": null,
  "diagnostics": {"counts": {"error": 0, "warn": 0, "info": 0}, "items": []},
  "stale": {"error": null, "baseline": "missing",
            "counts": {"changed": 4, "removed": 0, "needs_recheck": 0,
                       "reviewed_cases": 1, "adopted_reviews": 0, "named_reviews": 0},
            "needs_recheck": []},
  "drafts": {"error": null, "counts": {"drafts": 1, "pending": 1, "rejected": 0,
                                       "invalid": 0, "batches": 1}, "batches": ["login-lock"]},
  "runs": {"error": null, "counts": {"runs": 1, "failed_runs": 1, "failed_cases": 1,
                                     "unreadable": 0}}
}
```

`GET /api/qa/trace/tree`（节选）：`{trace_version, tool_version, project, counts{sources,
testpoints, cases, scripts, orphans}, sources[{…source 字段, testpoints[{…, cases[
{id, title, status, priority, type, automation, owner, tags, testpoints, sources,
script{binding, file, nodeid, resolves, problem}, needs_recheck, recheck_reasons,
changed_ids}]}], cases[…直挂来源的用例], case_count}], orphans[…], scripts[…去重后的
(case, binding)]}`。同一个 Case 挂在两个来源下时会在两处出现，但 `scripts` 与
`counts.scripts` 只算一次。

`GET /api/qa/trace/impact` = `qa trace impact --json`；`GET /api/qa/trace/stale` =
`qa trace stale --json`；`GET /api/qa/trace/drafts` = `review list --json`；
`GET /api/qa/trace/failure` = `failure --json`；`GET /api/qa/trace/runs` 是 manifest
清单（`items[]` 带 `run_id/status/exitstatus/started_at/finished_at/environment/
code_commit/tool_version/path/results/failed_cases/failed_case_ids`，按 `finished_at`
倒序）。

mutation 响应：`{"ok": true, "stale": <stale --json>}`、
`{"ok": true, "review": <review approve --json>}`。

### 7.8 `qa trace diff --json` 形状（P5）

真实输出（`metrics_project` 复制到临时 git 仓库，第二个 commit 加了一个没有下游的
`REQ-LOGIN-03`；`--base` 指向第一个 commit，退出码 1）。为便于阅读，`coverage` 的
六个比率只完整展开一个，其余同理；`…` 表示省略，字段集合是完整的：

```json
{
  "diff_version": 1,
  "tool": {"name": "qa_trace", "version": "0.5.0"},
  "project": {
    "id": "metrics-demo",
    "root": "…/qa-workbench/projects/demo",
    "repo_root": "…",
    "path_in_repo": "qa-workbench/projects/demo"
  },
  "base": {
    "ref": "8c9677dfcb79fdfaa24c873af5eb9c287ea036d3",
    "commit": "8c9677dfcb79fdfaa24c873af5eb9c287ea036d3",
    "valid": true,
    "metrics_available": true,
    "metrics_suppressed": null,
    "counts": {"sources": 5, "active_sources": 5, "testpoints": 2, "cases": 4,
               "library_cases": 4, "reviewed_cases": 3, "dangling_references": 0},
    "dangling_count": 0
  },
  "head": {
    "commit": "41f8a7af9087cc2948adcfbdac96c044ff18a0fb",
    "valid": true,
    "metrics_available": true,
    "metrics_suppressed": null,
    "counts": {"sources": 6, "active_sources": 6, "testpoints": 2, "cases": 4,
               "library_cases": 4, "reviewed_cases": 3, "dangling_references": 0},
    "dangling_count": 0
  },
  "tolerance": {"coverage_points": 0.0, "source": "default"},
  "regression": true,
  "exit_code": 1,
  "reasons": [
    {
      "code": "coverage_drop",
      "message": "2 coverage metric(s) dropped by more than 0 point(s)",
      "items": ["requirement reviewed: 50.00% -> 33.33%",
                "requirement current-valid: 50.00% -> 33.33%"]
    }
  ],
  "diagnostics": {
    "new": [
      {"severity": "info", "code": "TRACE_SOURCE_NO_DOWNSTREAM",
       "entity_id": "REQ-LOGIN-03", "path": "sources/REQ-LOGIN-03.yaml",
       "field": "id", "message": "source REQ-LOGIN-03 has no downstream test point or case"}
    ],
    "resolved": [],
    "unchanged_count": 2,
    "counts": {"base": 2, "head": 3}
  },
  "counts": {
    "base": {"sources": 5, "…": 0},
    "head": {"sources": 6, "…": 0},
    "delta": {"active_sources": 1, "cases": 0, "dangling_references": 0,
              "library_cases": 0, "reviewed_cases": 0, "sources": 1, "testpoints": 0}
  },
  "coverage": {
    "requirement": {
      "reviewed": {
        "base": {"numerator": 1, "denominator": 2, "percent": 50.0},
        "head": {"numerator": 1, "denominator": 3, "percent": 33.33},
        "comparable": true, "delta_percent": -16.67,
        "worsening_points": 16.67, "regression": true
      },
      "current_valid": {"base": {"…": "同上"}, "head": {"…": "同上"},
                        "comparable": true, "delta_percent": -16.67,
                        "worsening_points": 16.67, "regression": true}
    },
    "behavior": {"reviewed": {"…": "50.00% -> 50.00%, regression false"},
                 "current_valid": {"…": "同上"}},
    "automation": {"reviewed": {"…": "33.33% -> 33.33%, regression false"}},
    "orphan": {"library": {"…": "0.00% -> 0.00%, regression false"}}
  },
  "dangling": {"base": 0, "head": 0, "delta": 0, "new": false},
  "orphan": {"base": [], "head": [], "added": [], "removed": [],
             "counts": {"base": 0, "head": 0}},
  "requirement_gaps": {
    "base": {"count": 1, "uncovered_requirement_count": 1,
             "uncovered_requirements": ["REQ-LOGIN-02"],
             "cases_without_requirement_root": ["TC-LOGIN-004"]},
    "head": {"count": 1, "uncovered_requirement_count": 2,
             "uncovered_requirements": ["REQ-LOGIN-02", "REQ-LOGIN-03"],
             "cases_without_requirement_root": ["TC-LOGIN-004"]},
    "new_uncovered_requirements": ["REQ-LOGIN-03"],
    "resolved_uncovered_requirements": [],
    "new_cases_without_requirement_root": [],
    "resolved_cases_without_requirement_root": []
  },
  "needs_recheck": {"base": [], "head": [], "added": [], "removed": []}
}
```

约定：

- 顶层 16 个键恒在；`reasons` 只会是 `new_errors`、`new_dangling`、`new_orphan`、
  `coverage_drop`、`orphan_rate` 的组合，`exit_code` 是 `0` 或 `1`（`2` 是异常路径，
  不出 JSON）。
- 每个比率块恒有 `base`/`head`/`comparable`/`delta_percent`/`worsening_points`/
  `regression`；`base`/`head` 是 `{numerator, denominator, percent}` 或 `null`。
- 指标被抑制（结构错误）时 `metrics_available: false`，对应比率的 `base`/`head` 为
  `null`、`comparable: false`、`regression: false`。
- `diagnostics.new/resolved` 是完整诊断对象（与 `report` 的 `diagnostics.items` 同形）。
- 临时物化目录不会出现在任何字段里（`project.root`/`repo_root` 是调用者给的路径）。

### 7.9 `qa trace migrate-sqlite --json` 形状（P6）

真实输出（本机 SHOP 演示库，8 条用例；`--root qa-workbench/projects`）：

```json
{
  "migration_version": 1,
  "db": "C:/Users/jn/.nanobot/qa/qa.sqlite3",
  "root": "qa-workbench/projects",
  "batch": "sqlite-migration",
  "counts": {
    "projects": 1,
    "cases": 8,
    "drafts": 8,
    "formal": 0,
    "tombstones": 0,
    "skipped": 0,
    "errors": 0
  },
  "projects": [
    {
      "key": "SHOP",
      "project_id": "proj_8a86656ab0fa",
      "project_dir": "qa-workbench/projects/shop",
      "cases": 8,
      "drafts": 8,
      "formal": 0,
      "tombstones": 0,
      "skipped": 0
    }
  ],
  "skipped": [],
  "errors": []
}
```

约定：

- `counts.cases` = 本次写出的用例数；`drafts`/`formal`/`tombstones` 三者相加等于它；
  `skipped` 是「该项目里已经有 `legacy_id` 相同的 YAML」的行数（重跑时等于用例总数）。
- `errors[]` 是单条用例的文档构造失败（`{"case_id", "code", "message"}`），不影响其余
  用例；输入级失败（库/项目/参数）直接抛 `TRACE_MIGRATE_INVALID`，不出 JSON。
- 报告里的 `db`/`root` 是调用者给的路径，不展开成临时目录。
- `legacy_id` 只出现在 YAML 文档里（以及派生索引行的 `legacy_id` 列），不出现在报告里。

## 8. 验证方式

```powershell
# 自动化测试（P0/P1/P2/P3/P5 一起；P4 的接口/页面测试在 tests/qa 与 webui）
.\.venv\Scripts\python.exe -m pytest tests/qa_trace -q                       # 231 passed
.\.venv\Scripts\ruff.exe check qa_trace tests/qa_trace                       # All checks passed

# 校验（规则 9 已接入 run_check）
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/valid_project    # OK, 0
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/metrics_project  # warn+info, 0
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/marker_ok        # OK, 0
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/marker_missing   # TRACE_MARKER_MISMATCH, 1
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/marker_extra     # ORPHAN + 2×UNKNOWN, 1
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/invalid_dangling_source  # 2 errors, 1
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/invalid_dangling_script  # TRACE_REF_MISSING, 1
.\.venv\Scripts\python.exe -m qa_trace trace check  --project tests/qa_trace/fixtures/nope             # TRACE_PROJECT_INVALID, 2
.\.venv\Scripts\python.exe -m qa_trace trace report --project tests/qa_trace/fixtures/metrics_project   # 四数 + 缺口, 0
.\.venv\Scripts\python.exe -m qa_trace trace report --project tests/qa_trace/fixtures/metrics_project --json  # 稳定 JSON, 0

# P3：草稿批次默认不参与校验，加 --include-draft 才校验
.\.venv\Scripts\python.exe -m qa_trace trace check --project tests/qa_trace/fixtures/draft_review                     # OK, 0
.\.venv\Scripts\python.exe -m qa_trace trace check --project tests/qa_trace/fixtures/draft_review --include-draft     # OK, 0
.\.venv\Scripts\python.exe -m qa_trace trace check --project tests/qa_trace/fixtures/draft_invalid --include-draft    # TRACE_FIELD_MISSING (draft/…), 1
.\.venv\Scripts\python.exe -m qa_trace trace check --project tests/qa_trace/fixtures/draft_invalid                    # OK, 0

# P3：影响面查询
.\.venv\Scripts\python.exe -m qa_trace trace impact --project tests/qa_trace/fixtures/impact_project --source REQ-LOGIN-01      # 2 TP / 2 Case / 1 script, 0
.\.venv\Scripts\python.exe -m qa_trace trace impact --project tests/qa_trace/fixtures/impact_project --testpoint TP-LOGIN-001 --json  # 稳定 JSON, 0
.\.venv\Scripts\python.exe -m qa_trace trace impact --project tests/qa_trace/fixtures/impact_project --case TC-LOGIN-999        # TRACE_ENTITY_NOT_FOUND, 1
.\.venv\Scripts\python.exe -m qa_trace trace impact --project tests/qa_trace/fixtures/nope --source REQ-LOGIN-01               # TRACE_PROJECT_INVALID, 2

# P3：变更/摘要（改一个 Source 只影响真实下游；--write 记录新 baseline）
.\.venv\Scripts\python.exe -m qa_trace trace stale --project <copy>            # baseline missing, 7 changed, 0 recheck, 1
.\.venv\Scripts\python.exe -m qa_trace trace stale --project <copy> --write    # recorded 7, 5 adopted, 0
# 改 <copy>/sources/REQ-LOGIN-01.yaml 的标题后
.\.venv\Scripts\python.exe -m qa_trace trace stale --project <copy>            # 5 changed, 2 recheck (dependency_changed), 1
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project <copy> --id TC-LOGIN-001 --reviewer qa.zhang
#                                                                              # reviewed（不写文件），0；recheck 只剩 TC-LOGIN-002

# P3：草稿 → 审核 → 入库 / 驳回
.\.venv\Scripts\python.exe -m qa_trace trace review list   --project <copy>                        # 2 drafts / 2 batches, 0
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project <copy> --id TC-LOGIN-010 --reviewer qa.li
#                                                                              # promoted → cases/TC-LOGIN-010.yaml, 0
.\.venv\Scripts\python.exe -m qa_trace trace review reject  --project <copy> --id TP-LOGIN-011 --reviewer qa.zhang --note "边界描述不清"
#                                                                              # rejected（文件留在 draft/），0
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project <copy> --id TP-LOGIN-011     # TRACE_REVIEW_BLOCKED, 1
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project <copy> --id TC-LOGIN-999     # TRACE_ENTITY_NOT_FOUND, 1
.\.venv\Scripts\python.exe -m qa_trace trace review approve --project <copy> --id TC-LOGIN-011     # 无效草稿, TRACE_REVIEW_BLOCKED, 1
.\.venv\Scripts\python.exe -m qa_trace trace draft new --project <copy> --kind case --module LOGIN --testpoint TP-LOGIN-005   # draft written, 0
.\.venv\Scripts\python.exe -m qa_trace trace draft new --project <copy> --kind case --module LOGIN                            # TRACE_DRAFT_INVALID, 2
.\.venv\Scripts\python.exe -m qa_trace trace draft add --project <copy> --file <yaml>                                         # draft written, 0
.\.venv\Scripts\python.exe -m qa_trace trace draft add --project <copy> --file <same-id-as-formal>                            # TRACE_DRAFT_ID_CONFLICT, 1

# P3：失败回溯（先用 P2 插件跑一次真实会话）
.\.venv\Scripts\python.exe -m qa_trace trace failure --project <copy> --run <run_id>                 # case→TP→Source + last run, 0
.\.venv\Scripts\python.exe -m qa_trace trace failure --project <copy> --run <run_id> --case TC-LOGIN-003  # 本次没跑该用例, 1
.\.venv\Scripts\python.exe -m qa_trace trace failure --project <copy> --run nope                     # TRACE_RUN_NOT_FOUND, 2

# 真实插件运行：写 manifest（入口点未重装，显式 -p 加载；库路径用等号形式，见限制 11）
# 先把上面 §7.2 的两个测试写进 .qa-demo/demo_test.py
.\.venv\Scripts\python.exe -m pytest -p qa_trace.pytest_plugin `
  --qa-project=tests/qa_trace/fixtures/marker_ok `
  --qa-run-dir=.qa-demo/runs .qa-demo/demo_test.py -q
# 1 failed, 1 passed；退出码 1；manifest 写到 .qa-demo/runs/<run_id>/manifest.json
```

fixtures：

| fixture | 用途 |
|---|---|
| `valid_project` | P0 登录锁定样例，P1/P2/P3 下仍然干净（0 诊断） |
| `metrics_project` | 指标精确值：需求 1/2、行为 1/2、自动化 1/3、孤儿 0/4；含 P0 占比 warn 与无下游 Source info |
| `stale_propagation` | stale Source 传播出 `needs_recheck`（info，退出 0）；P3 下 `review approve` 该用例会被拒绝（来源仍 stale） |
| `impact_project` | P3 影响面样例：2 Source、2 TP（TP-001 挂两个来源）、3 Case（含直挂来源的 TC-003 与脚本绑定） |
| `draft_review` | P3 草稿样例：`default` 批次的合法新用例 + `login-lock` 批次的新 TP（`check --include-draft` 干净） |
| `draft_invalid` | P3 坏草稿样例：缺 `steps` 的 Case（正式库干净，`--include-draft` 退出 1） |
| `marker_ok` | 用例与脚本 marker 双向一致，0 诊断（退出 0） |
| `marker_missing` | 脚本重写丢了 marker：`TRACE_MARKER_MISMATCH`（退出 1） |
| `marker_extra` | 手工用例的 marker（ORPHAN）+ 未知用例 ID（UNKNOWN）+ 非法 ID（UNKNOWN），退出 1 |
| `invalid_dangling_source` | TP 引用不存在的 Source：`TRACE_REF_MISSING` + `TRACE_CASE_ORPHAN`，退出 1 |
| `invalid_orphan_case` | Case 引用不存在的 TP：`TRACE_REF_MISSING` + `TRACE_CASE_ORPHAN`，退出 1 |
| `invalid_dangling_script` | `automation.script` 指向不存在的文件，退出 1（marker lint 跳过，不重复报） |
| `invalid_bad_id` / `invalid_missing_evidence` / `invalid_case_no_testpoints` / `invalid_step_no_expected` / `invalid_enum` | P0 文档层无效样例，退出 1 |

`tests/qa_trace/test_pytest_plugin.py` 用 `pytester` 跑真实嵌套会话，覆盖
`passed/failed/skipped/error/xfailed/xpassed`、参数化聚合、一个 node 多个 marker、
未知/非法/非字符串 marker（pytest 退出码 4，且不写 manifest）、无法加载的项目库、
`--collect-only`、无选项不写文件、只给 `--qa-run-dir`。

P3 的测试文件：

| 文件 | 覆盖 |
|---|---|
| `test_hashing.py` | canonical JSON、内容摘要排除审核元数据/`stale`/未知字段、排版不变、业务字段变化、依赖指纹传递、悬空引用记 `null` |
| `test_stale.py` | 无 baseline / `--write` / 改 Source 只影响真实下游 / 改 Case 内容 / 只改排版 / 人工 stale / 新用例无 review 记录 / `review approve` 清除 recheck / `--write` 不清 review / 索引损坏与版本不匹配 / 项目不匹配 / CLI 退出码与 JSON |
| `test_impact.py` | Source/TP/Case 三种目标、`via` 路径、脚本 nodeid、`needs_recheck`、未知 ID、退出码 0/1/2、JSON 稳定 |
| `test_drafts.py` | 批次列举、晋级写正式文件+索引、驳回留在 `draft/`、编辑后回到 pending、无效草稿拒绝且不改正式库、`check --include-draft`、ID 冲突、`base_content_hash` 更新/过期、批次内依赖阻塞、`draft new/add`、Source 草稿只记 baseline、上游变更后的更新草稿清除 recheck、CLI 退出码 |
| `test_failure.py` | 快照回溯（含已删除用例）、无快照退回当前库、`changed_since_run`、当前 `needs_recheck`、`--case` 过滤、最近一次运行、缺失/损坏 manifest、文本与 JSON |

### 8.1 P4 验证与端到端演示

```powershell
# 0) 全部测试与构建
.\.venv\Scripts\python.exe -m pytest tests/qa_trace tests/qa -q      # 344 passed
.\.venv\Scripts\python.exe -m pytest tests/webui -q                  # 776 passed, 18 skipped
cd webui; npm test -- qa                                             # 16 passed (qa-workbench + qa-trace)
cd webui; npm run build                                              # tsc + vite, exit 0

# 1) 演示库自检：真实资产，0 诊断（草稿默认不参与）
.\.venv\Scripts\python.exe -m qa_trace trace check --project qa-workbench/projects/login-lock
# OK, 0

# 2) 用 P2 插件跑一次真实 pytest：断言故意失败，manifest 写进项目 runs/
.\.venv\Scripts\python.exe -m pytest -p qa_trace.pytest_plugin `
  --qa-project=qa-workbench/projects/login-lock `
  qa-workbench/projects/login-lock/scripts/test_login.py -q
# 1 failed（第 5 次仍返回 401，需求要求 423）；manifest 写到 runs/<run-id>/manifest.json

# 3) 失败回溯：run -> case -> testpoint -> source
.\.venv\Scripts\python.exe -m qa_trace trace failure `
  --project qa-workbench/projects/login-lock --run <run-id>
# case TC-LOGIN-003 / result failed (call) / TP-LOGIN-005 reviewed /
# REQ-LOGIN-01 active req / UI-LOGIN-02 active ui / changed since run=False, 0

# 4) 变更传播与复核（在临时副本上做，演示库本身保持不变）
Copy-Item -Recurse qa-workbench/projects/login-lock $env:TEMP/login-lock-demo
.\.venv\Scripts\python.exe -m qa_trace trace stale --project $env:TEMP/login-lock-demo --write
# baseline recorded, 4 entities
# 改 sources/UI-LOGIN-02.yaml 的 title 后：
.\.venv\Scripts\python.exe -m qa_trace trace stale --project $env:TEMP/login-lock-demo
# 3 changed (UI-LOGIN-02 / TP-LOGIN-005 / TC-LOGIN-003), 1 needs re-check, 1
.\.venv\Scripts\python.exe -m qa_trace trace impact --project $env:TEMP/login-lock-demo --source UI-LOGIN-02
# TP-LOGIN-005 + TC-LOGIN-003 (RECHECK, dependency_changed) + 1 script, 0
.\.venv\Scripts\python.exe -m qa_trace trace review approve `
  --project $env:TEMP/login-lock-demo --id TC-LOGIN-003 --reviewer qa.zhang
# reviewed（不写文件，只记索引）；再跑 stale 为 0 needs re-check, 0
```

工作台验证（真实页面）：启动网关后打开 WebUI → 左侧「QA 工作台」→「追溯」标签，
选 `login-lock` 项目，可见四个指标卡、链树（REQ-LOGIN-01 / UI-LOGIN-02 →
TP-LOGIN-005 → TC-LOGIN-003 → 脚本）、影响面查询、变更/待复核、草稿
`TC-LOGIN-004` 的「通过 / 退回」与失败回溯；点「记录基线」写的是
`.qa-trace/index.json`（派生、gitignored），不会改 YAML。

### 8.2 P5 验证与 CI

```powershell
# 0) 测试与静态检查
.\.venv\Scripts\python.exe -m pytest tests/qa_trace -q        # 231 passed（含 test_diff.py 12 条）
.\.venv\Scripts\ruff.exe check qa_trace tests/qa_trace         # All checks passed

# 1) 真实仓库历史：当前 HEAD 与自己比，无回归
.\.venv\Scripts\python.exe -m qa_trace trace diff `
  --project qa-workbench/projects/login-lock --base 00bd2b4f
# regression no, exit 0（两侧都是 2 source / 1 TP / 1 case，比率全部持平）

# 2) 项目在基线 commit 还不存在（login-lock 是 P4 才加的）：输入失败
.\.venv\Scripts\python.exe -m qa_trace trace diff `
  --project qa-workbench/projects/login-lock --base 0a3cf427
# TRACE_DIFF_BASE_MISSING qa-workbench/projects/login-lock/project.yaml, 2

# 3) 未知 ref
.\.venv\Scripts\python.exe -m qa_trace trace diff `
  --project qa-workbench/projects/login-lock --base no-such-ref
# TRACE_DIFF_BASE_UNKNOWN, 2

# 4) 回归与容差（临时 git 仓库、两个 commit，样例见 §7.8）
#    第二个 commit 加了一个没有下游的 REQ-LOGIN-03
.\.venv\Scripts\python.exe -m qa_trace trace diff `
  --project $env:TEMP/qa-diff-demo/qa-workbench/projects/demo --base <base-commit> --json
# regression YES (coverage_drop 50.00% -> 33.33%), exit 1
.\.venv\Scripts\python.exe -m qa_trace trace diff `
  --project $env:TEMP/qa-diff-demo/qa-workbench/projects/demo --base <base-commit> `
  --coverage-tolerance 20
# tolerance 20 point(s) (cli), regression no, exit 0

# 5) 非 git 目录
.\.venv\Scripts\python.exe -m qa_trace trace diff --project <copy-without-.git> --base HEAD
# TRACE_DIFF_NOT_GIT, 2

# 6) pre-commit hook 的 entry（.pre-commit-config.yaml）
.\.venv\Scripts\python.exe -m qa_trace trace check --project qa-workbench/projects/login-lock
# OK, 0
```

`tests/qa_trace/test_diff.py`（12 条）覆盖：无改动 0、新悬空引用 1（base 仍为 0，
证明基线来自 git 而不是工作区）、覆盖率下降 1、容差 20 放行 / 10 拦截、
`project.yaml` 的 `diff_coverage_tolerance`、已消除诊断（base 坏、head 修好）为 0 且
`metrics_available: false`、未知 ref 2、非 git 2、项目缺失 2、基线缺项目 2、
JSON 形状与“临时目录不泄漏”、diff 不改写工作区。

CI 文件（两份都自包含、不引用远端仓库）：

| 文件 | 内容 |
|---|---|
| `.github/workflows/qa-trace.yml` | `actions/checkout@v4`（`fetch-depth: 0`，PR 需要历史）→ `setup-python@v5` 3.12 → `pip install -e ".[dev]"`（editable 跳过 WebUI 构建）→ 探测 `qa`/退回 `python -m qa_trace` → `pytest tests/qa_trace` → `trace check` demo 项目 → `trace report --json` 上传 `qa-trace-report` → PR 上 `trace diff --base origin/<base_ref> --json`（非 0 即失败）并上传 `qa-trace-diff`。`NANOBOT_QA_TRACE_ROOT` 设为 `${{ github.workspace }}/qa-workbench/projects`（只影响工作台适配器，CLI 一律显式 `--project`） |
| `.pre-commit-config.yaml` | 本地 hook `qa-trace-check`（`language: system`）：`python -m qa_trace trace check --project qa-workbench/projects/login-lock`，只对 `qa_trace/`、`qa-workbench/projects/`、`tests/qa_trace/` 的改动触发；需要 venv 里能 import `qa_trace`（`pip install -e .`） |

GitHub Actions 只在真实仓库运行，本机没有执行（见限制 34）：本地验证到的是同一条
命令的退出码与 JSON，以及 YAML 可解析。分支保护（required checks）属于仓库设置，
不在代码里。

### 8.3 P6 验证与 SHOP 迁移结果

```powershell
# 0) 全量测试与静态检查（P6 收尾时的真实计数）
.\.venv\Scripts\python.exe -m pytest tests/qa_trace tests/qa -q      # 428 passed
.\.venv\Scripts\python.exe -m pytest tests/webui -q                  # 776 passed, 18 skipped
cd webui; npm test -- qa                                             # 19 passed
cd webui; npm run build                                              # tsc + vite, exit 0
.\.venv\Scripts\ruff.exe check qa_trace nanobot tests/qa tests/qa_trace   # All checks passed

# 1) 迁移只读 SQLite，把 8 条 SHOP 用例写成 YAML 草稿
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite `
  --project SHOP --db "$env:USERPROFILE\.nanobot\qa\qa.sqlite3" --root qa-workbench/projects
# 1 project(s), 8 case(s): 8 draft, 0 formal, 0 tombstone, 0 already migrated, 0

# 2) 迁移结果：项目元信息 + 8 个草稿文档（ID 连续、code 保留、legacy_id 回指）
Get-ChildItem qa-workbench/projects/shop/draft/sqlite-migration/cases
.\.venv\Scripts\python.exe -m qa_trace trace check --project qa-workbench/projects/shop   # OK（草稿不参与正式库）
.\.venv\Scripts\python.exe -m qa_trace trace review list --project qa-workbench/projects/shop
# 8 drafts / 1 batch；每条只差链路：TRACE_LINK_MISSING（附给人补测试点）

# 3) 重建 SQLite 派生索引：列表变成 TC-* 行，旧行留作回滚
.\.venv\Scripts\nanobot.exe qa reindex --project SHOP --root qa-workbench/projects
# {"cases": 8, "drafts": 8, "reviewed": 0, "archived": 0}
.\.venv\Scripts\nanobot.exe qa cases --project SHOP
# TC-SHOP-001..008（code 仍是 SHOP-API-001..006 / SHOP-UI-001..002）
.\.venv\Scripts\nanobot.exe qa status
# cases 8 / ready_cases 0 / scripts 1 / runs 1 / tasks 3（旧行没有被双份计数）

# 4) 幂等：再跑一次迁移不会产生新文件
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite `
  --project SHOP --db "$env:USERPROFILE\.nanobot\qa\qa.sqlite3" --root qa-workbench/projects
# 8 already migrated, 0

# 5) 错误路径：库不存在 / 项目不存在 / 没给库路径 都是 TRACE_MIGRATE_INVALID + 2
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite --db nope.sqlite3   # 2
.\.venv\Scripts\python.exe -m qa_trace trace migrate-sqlite --project NOPE --db <db>   # 2
```

用例库行为（`tests/qa/test_case_files.py` 覆盖）：创建写
`draft/workbench/cases/TC-<KEY>-001.yaml`（`status: draft`）；无链路时 `update status=ready`
仍然留在 `draft/`；补上 `TP-*`/来源后写进 `cases/` 并在 `.qa-trace/index.json` 记一条
review；删除写 `tombstones/<ID>.yaml` 且下一个编号跳过它。

## 9. 已知限制

1. **marker 对照是静态的**：`qa trace check` 只 `ast.parse` 被绑定的脚本，不 import、
   不 collect、不执行。`import pytest as pt` 之类的别名、模块级 `pytestmark`、运行期
   动态挂 marker 都识别不到，可能误报 `TRACE_MARKER_MISMATCH`；真正的 collection
   对照要等后续的 full check。插件运行时只校验 marker 的 ID（语法 + 存在性），也不
   做 collection 与 `automation.script` 的 nodeid 对照。
2. **nodeid 只在能静态确定时对照**：绑定 nodeid 在文件里找不到对应函数（动态生成、
   插件提供 item）时退回文件级判断；绑定函数存在而 marker 在别的函数上才报错。
3. **`qa trace failure` 依赖 manifest 快照的完整度**：P3 之前的 manifest 没有
   `asset_snapshot.testpoint_sources`，这时“TP → Source”这一跳退回**当前**库，报告
   在 `chain.origin` 里写明；用例/TP/Source 若在运行后被删改，只能保证 case → TP
   这一跳来自快照。另外 manifest 里没有记录的资产（运行后才新建的）不会被回溯。
4. **自动化率仍是 provisional**：规则 9 已静态校验 marker，但 `qa trace check` 不做
   collection/执行，`coverage.automation.provisional` 恒为 `true`。
5. **`report`/`check` 的 `needs_recheck` 仍是 P1 口径**：内容/依赖摘要与
   `review approve` 已经能派生完整待复核清单，但 `qa trace report` 的
   `needs_recheck`、`coverage.*.current_valid` 仍只按人工 `stale` 标记计算（P3 没有
   改指标口径）。要看摘要口径的待复核，用 `qa trace stale` / `qa trace impact`。
6. **规则 13 走不到 CLI**：P0 模型层已把它当 error，图规则的 warn 版本只能靠单测
   覆盖（决定 14）。
7. **manual P0 老化未知**：没有 automation 状态变更时间，`dead_assets.manual_p0_cases`
   只能给出 `status: unknown` 与当前候选清单，`dead_assets.count` 是部分计数
   （`count_is_partial: true`）。
8. **索引是本地派生状态**：`.qa-trace/index.json` 不在 YAML 真源里，删掉或换一台机器
   后 `stale` 会回到 `baseline: missing`（exit 1），需要重新 `--write`；CI 若要在
   干净检出上判断“审核是否仍有效”，必须把索引作为可重建产物先跑一次 `--write`，或
   接受“首次运行没有基线”。仓库 `.gitignore` 已忽略 `.qa-trace/`。
9. **`stale --write` 是“采纳当前状态”的运维动作**：它把 baseline 推到当前指纹，并给
   尚无 review 记录的 reviewed TP/Case 写 `adopted: true, reviewed_by: null` 的采纳
   记录（让 P3 之前的老库可用）。它**不会**覆盖已有 review 记录，所以不能清除
   `dependency_changed`；但“采纳”本身没有人工签名，审计要求高的场景应改用
   `review approve --reviewer`。
10. **没有多实体事务与写锁**：`review approve` 只晋级一个实体，流程是“先校验 → 单文件
   原子替换 → 记索引”。多个实体同时晋级、进程在写文件与写索引之间被强杀（会留下
   已晋级但未记 review 的实体，`stale` 会把它报成 `no_review_baseline`）、以及多人
   并发写同一项目，都没有锁或事务日志（方案 §7 的写锁/事务日志留到后续）。
11. **晋级会重写 YAML 排版**：草稿晋级用 `yaml.safe_dump` 落盘，会丢注释、改变缩进与
   引号风格（业务字段与值不变）。`review approve` 对**已存在**实体的“重新复核”不写
   文件，排版保持不变。
12. **审核记录在索引里，不在实体 YAML 里**：方案 §3.4 原本要求 `reviewed_by`/
    `reviewed_at`/`reviewed_content_hash` 写进实体；P3 按任务约定统一放索引。因此
    “谁在什么时候审核的”只存在于本工作副本的索引中，删索引即丢（实体内容与状态仍在）。
13. **草稿与 ID 分配记录**：草稿 ID 用 UUID4（方案 §3.1），但没有 `ids/<id>.yaml` 的
    分配/退休记录，也没有 `qa retire`；ID 复用/删除检测留给后续阶段。
14. **`impact` 只看当前图**：删除/改名后的影响面（方案 §6 要求用基线快照里的旧图继续
    查下游）没有实现；`impact` 只回答“现在的库”，悬空引用会显示 `exists: false` 但
    不会沿旧关系继续展开。`qa trace case` 单条追溯命令也没有（`impact --case` 覆盖了
    主要信息）。
15. **`stale` 每次全量计算**：一次扫描全库算摘要（方案 §6 允许先内存索引），没有
    SQLite/增量缓存；1k Source / 5k TP / 20k Case 的性能验收未做。
16. **只扫正式库**：`draft/` 默认不参与 `check`、覆盖率与报告（`--include-draft`
    才校验草稿批次）；`runs/` 不参与校验；一个项目一次校验，无跨项目规则。
17. **结构错误即中止图规则与 marker lint**：一旦有 loader 错误，图规则和规则 9 都不
    运行（半加载的库没有意义），需要先修文档层错误。
18. **pytest 首次解析会吞掉自定义选项的值**：pytest 在加载 `-p` 插件之前就确定了
    rootdir，`--qa-project <path>` 的空格形式可能让库路径被当成位置参数，从而改变
    rootdir 和 nodeid（库在测试树之外时尤其明显）。请用等号形式
    `--qa-project=<path>`（`--qa-run-dir` 同理）；库与测试在同一工作区内时通常无影响。
19. **入口点未安装**：`pyproject.toml` 已声明 `pytest11` 入口点，但需要
    `pip install -e .` 才会自动加载；P2/P3 没有重装（避免触发 WebUI 构建），验证统一
    显式 `-p qa_trace.pytest_plugin`。仓库根 `conftest.py` 只是为测试打开了
    `pytester` 插件，不会自动加载 qa-trace 插件。
20. **xdist 与硬中断**：`pytest -n` 下每个 worker 是一个独立会话，各自写自己的
    manifest（run_id 不同），P2 不做合并；Ctrl-C 会写 `status=incomplete` 的
    manifest，但进程被强杀时没有中间落盘（方案 §3.5 的“运行中写临时区域”留到后续）。
21. **未安装入口脚本**：`qa` 命令需要 `pip install -e .` 才生成，验证统一走
    `python -m qa_trace`；P1/P2/P3 没有重装，以免触发 WebUI 构建。
22. **仓库级 `pytest tests` 有既存的同名模块冲突**（`tests/cli/test_models.py` 与
    `tests/qa_trace/test_models.py`、`tests/pairing/test_store.py` 与
    `tests/qa/test_store.py`），与本阶段无关；`pytest tests/qa_trace` 正常。
23. **追溯页不轮询**：`summary` 会跑一次完整库校验（含 marker lint），按 3 秒轮询代价
    太高；页面只在挂载、切项目、点「刷新」或动作成功后重新拉取。别人在命令行改了库，
    需要手动刷新才看得到。
24. **工作台不生成草稿**：页面只做「查看 + 审核」，草稿仍由 Agent 通过
    `qa trace draft new/add` 写入。方案 §8 的“工作台支持草稿生成”只完成到“查看审核包 +
    人工确认”，没有把模型调用搬进这个标签页。
25. **审核权限没有分级**：能打开 QA 工作台的人就能点「通过」，`reviewer` 只是自填的
    声明身份（与 CLI 的 `--reviewer` 同等可信度）。要强人工保证仍需 P5 的分支保护或
    受控发布入口。
26. **索引是本机派生状态，演示库不自带 baseline**：`.qa-trace/` 被 gitignore，
    所以新检出打开追溯页时 `stale.baseline` 是 `missing`（“变了什么”未知），
    需要先点「记录基线」；审核记录也只在本机索引里（同限制 12）。
27. **演示项目的运行记录来自录制机器**：`runs/<run-id>/manifest.json` 里
    `project_path`/`asset_snapshot.root` 是录制时的绝对路径，`code_commit` 是录制时
    的 HEAD；换机器后仍可读（回溯用的是快照关系与内容摘要），但要生成新记录请重跑
    §8.1 第 2 步。
28. **一次 `tree` 请求整库返回**：链树不分页，也没有增量接口；1k Source / 20k Case
    的规模未做性能验收（同限制 15），工作台首屏只适合中小型库。
29. **「用例库」与「追溯」读的是同一个 YAML 库，但看到的范围不同**：用例库列出
    `cases/` + `draft/<batch>/cases/`（含未挂链路的草稿与未迁移的旧 SQLite 行），追溯页
    的链树只画正式库（草稿在 `draft/` 与 `review list` 里出现）。P6 之前这是两套数据，
    现在 SQLite 只是 YAML 的派生索引（同一条用例不会有两份内容）。
30. **安装成 wheel 后默认项目根不在检出目录**：`default_trace_root()` 用
    `nanobot/qa/trace_api.py` 的 `parents[2]` 推仓库根，`pip install` 之后那里是
    site-packages，默认根通常不存在（页面会显示“没有追溯项目”）。部署时请显式设置
    `NANOBOT_QA_TRACE_ROOT` 指向真实数据目录；开发检出下无需配置。
31. **追溯页的新文案只有中文兜底**：新增的 `qa.trace.*` 文案通过
    `tx(key, "中文")` 的 `defaultValue` 提供，没有写进 `webui/src/i18n/locales/*`；
    11 个 locale 的键一致性测试要求所有语言同时补齐，本阶段没有做翻译，所以英文等
    其它语言下这一页显示中文。
32. **`diff` 的基线是“项目目录在 git 里的样子”**：`--base` 解析的是**项目所在仓库**
    的 ref，项目目录必须在仓库内（`git rev-parse --show-prefix` 决定路径）。项目在
    另一个仓库、或数据目录被 `.gitignore` 排除时，`diff` 只能退出 2（`TRACE_DIFF_NOT_GIT`
    或 `TRACE_DIFF_BASE_MISSING`），不会退回“文件系统快照”基线。
33. **覆盖率容差的语义是“百分点”，不是“相对变化”**：分母变化（新增需求/来源）会
    直接压低比率并触发 `coverage_drop`，即使新增的需求本来就该没有用例。要允许这类
    改动，把 `thresholds.diff_coverage_tolerance` 调大，或用 `--coverage-tolerance`
    按次放宽；`diff` 不区分“新增未覆盖项”和“原有覆盖丢失”，只在 `requirement_gaps`
    里列出新增的缺口 ID 供人判断。
34. **GitHub Actions 没有在本机执行**：本阶段验证到的是 workflow YAML 可解析、
    `pip install -e ".[dev]"` 的 editable 路径（P1 起就一直用它）、以及每条命令的
    退出码；runner 上的行为（缓存、`fetch-depth`、`origin/<base_ref>` 是否存在、
    artifact 上传）需要在真实仓库跑一次才能确认。PR 的 `--base` 依赖
    `actions/checkout` 的 `fetch-depth: 0`；浅克隆下会退化成 `TRACE_DIFF_BASE_UNKNOWN`。
35. **`diff` 与 `check` 一样只做静态 marker lint**：不跑 pytest collection，所以
    “脚本里 marker 与 `automation.script` 双向一致”仍是静态判断（限制 1）；CI 上的
    diff 不会因为“marker 动态生成”而给出完整结论。
36. **回归判定只看 error 与指标**：`strict: true` 的 warn 变化、新增 info（如无下游
    来源）、`needs_recheck` 增加、需求缺口增加都只写进 JSON/文本，不算回归。这是
    刻意的：告警项在 CI 上应当先被看见，而不是先被当成失败。
37. **`diff` 不写任何状态**：不更新 `.qa-trace/index.json`、不写报告文件、不缓存
    基线；每次调用都重新解析 ref、重新物化、重新跑两侧校验。库大时是“两次全量
    check”的成本（同限制 15），没有增量 diff。
38. **迁移出来的用例全是草稿，而且暂时是「无效草稿」**：SQLite 用例没有任何链路，
    文档只差 `testpoints`/`sources`，所以 `review list` 会把 8 条 SHOP 草稿标成
    invalid 并给出 `TRACE_LINK_MISSING`。这是规则 5 的必然结果（正式库不能收无链路的
    用例），需要人先补测试点/来源再 `qa trace review approve`。迁移不会自动造需求或
    测试点，也不会因为「想让它看起来绿」而放宽模型。
39. **迁移只管用例，不管脚本/运行/任务**：`scripts.case_ids` 里存的是旧 `case_*` ID，
    没有映射到 `automation.script`（脚本绑定需要 `<file>::<nodeid>`，SQLite 里没有
    nodeid 信息）。执行侧仍读派生索引行，所以迁移后的用例可以被 `qa_run` 按 `TC-*`
    ID 执行；但「哪条用例由哪个 pytest 函数验证」要人工补绑定。
40. **索引是派生物，手工改 YAML 后要重建**：读路径只在「该项目有 YAML 但一条派生行
    都没有」时自愈一次；已经建过索引的项目，外部改文件（编辑器、`git pull`）不会自动
    反映，必须 `nanobot qa reindex`。这是索引的本分，不是 bug。
41. **ID 分配是「项目内最大号 + 1」，不是 UUID4**：为了可读的 `TC-SHOP-009`，并发写
    同一项目可能算出同一个号。文件写入是原子的、加载器会报重名（`TRACE_ID_DUPLICATE`），
    所以结果是「一条失败」而不是「静默覆盖」；真正的分配台账（`ids/<id>.yaml`）仍在
    P3 剩余的清单里。
42. **未迁移的旧行只读**：`legacy: true` 的行可以看、不能被用例库改（409 并提示
    `qa trace migrate-sqlite`）。这是刻意的过渡态：数据库不再接受新的写入者，旧行保留
    是为了回滚。
43. **每次写都全量重建该项目的派生行**：`reindex` 是「删掉 derived=1 的切片再插入」，
    一次写 = 一次全项目扫描 + 一次批量 INSERT。工作台规模（百级用例）没问题，万级
    用例需要增量方案（未做）。
44. **迁移没有批次事务与回滚**：逐文件写入，中途失败会留下已写的一部分用例；重跑会
    按 `legacy_id` 跳过已写行，所以可以「继续跑完」，但不能「撤销上一次迁移」。删除
    迁移批次目录即可回到迁移前（SQLite 一行都没被改）。
45. **归档用例不能再被执行**：`execute_cases --kind` 用 `exclude_deprecated=True`，
    显式传 `case_ids` 时遇到 `deprecated` 行直接报错；但 `runs/` 里的历史记录仍引用
    旧 ID（那是事实记录，不回改）。
