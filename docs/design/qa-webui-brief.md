# QA 工作台 WebUI 实现说明（给前端实现者）

后端已完成，本文件是前端对接契约与接入点清单。**不要改后端**；发现契约不一致请反馈。

## 1. 数据接口

读接口：普通 GET，`Authorization: Bearer <token>`，响应 `{"ok":true, ...}`。
写接口：只能走已认证 WebSocket 的 mutation（`transport.requestMutation(action, payload, timeoutMs)`），
action 与 payload 见下表。payload 中 id 字段名固定为 `id` / `project_id` / `case_id` / `script_id` / `task_id`。

| 读 | 返回 |
|---|---|
| `GET /api/qa/overview` | `{counts, projects[], recent_tasks[], recent_runs[]}` |
| `GET /api/qa/projects` | `{projects:[{id,key,name,description,base_url,repo_path,default_env,stats:{cases,ready_cases,scripts,runs,active_tasks}}]}` |
| `GET /api/qa/cases?project_id=&kind=&status=&q=&limit=&offset=` | `{items:[case], total, limit, offset}` |
| `GET /api/qa/cases/{id}` | `{case}` |
| `GET /api/qa/cases/export?project_id=` | `{format, project, exported_at, cases:[...]}` |
| `GET /api/qa/scripts?project_id=&q=` | `{items:[script(不含 content，含 content_bytes/content_lines)], total}` |
| `GET /api/qa/scripts/{id}` | `{script(含 content)}` |
| `GET /api/qa/runs?project_id=&limit=` | `{items:[run], total}` |
| `GET /api/qa/runs/{id}` | `{run(含 report)}` |
| `GET /api/qa/tasks?project_id=&status=&role=&limit=` | `{items:[task+project_key], total}` |
| `GET /api/qa/tasks/{id}` | `{task(含 artifacts[], children[])}` |
| `GET /api/qa/tasks/{id}/events` | `{events:[{id,task_id,at,kind,message,data}]}` |
| `GET /api/qa/health` | `{store}` |

写（WebSocket mutation action → payload）：

| action | payload |
|---|---|
| `qa.project.create` | `{key,name,description?,base_url?,repo_path?}` |
| `qa.project.update` | `{id,...fields}` |
| `qa.project.delete` | `{id}` |
| `qa.case.create` | `{project_id,title,kind,priority,status,preconditions?,steps?,api?,expected?,tags?}` |
| `qa.case.bulk_create` | `{project_id,cases:[...]}` |
| `qa.case.update` | `{id,...fields}` |
| `qa.case.delete` | `{id}` |
| `qa.case.import` | `{project_id,payload:{cases:[...]}}` |
| `qa.script.create` | `{project_id,name,framework,language,file_path,content,case_ids?,tags?}` |
| `qa.script.update` | `{id,...fields}` |
| `qa.script.delete` | `{id}` |
| `qa.task.create` | `{title,project_id?,role?,prompt?}` |
| `qa.task.update` | `{id,status?,progress?,result?}` |
| `qa.task.cancel` | `{id}` |
| `qa.run.start` | `{project_id, case_ids?[] , kind?, script_id?}`（同步执行，可能较慢；mutation timeout 用 180000） |

实体形状：

```ts
type QaCase = { id; project_id; code; title; kind: "api"|"ui"|"manual"; priority: "P0"|"P1"|"P2"|"P3";
  status: "draft"|"ready"|"deprecated"; preconditions; steps: {action,expected}[]; expected; tags: string[];
  api: { request?: {method,path,headers,query,body}; assertions?: any[]; variables?: Record<string,string> };
  source; author; created_at; updated_at }
type QaScript = { id; project_id; name; framework; language; file_path; content?; case_ids: string[]; tags; status;
  content_bytes?; content_lines?; created_at; updated_at }
type QaRun = { id; project_id; script_id|null; case_ids: string[]; status: "running"|"passed"|"failed"|"error"|"blocked_by_env"|"cancelled";
  passed; failed; errors; skipped; duration_ms; started_at; finished_at; report?: {summary?, tests?: {name?,code?,status,message?,duration?,checks?}[]}; log? }
type QaTask = { id; project_id|null; parent_id|null; role: "orchestrator"|"api"|"ui"|"automation"|"review";
  title; prompt; status: "queued"|"running"|"needs_review"|"blocked"|"done"|"failed"|"cancelled"; progress: 0..100;
  subagent_task_id; result; created_at; updated_at; artifacts?: {kind,ref_id,title}[]; children?: QaTask[] }
```

运行状态语义：`blocked_by_env` = 环境不可用（不是产品缺陷），UI 用黄色/灰色区分，不要显示为红色失败。

## 2. 页面

新增顶级视图 `qa`（hash `#/qa`），侧栏一个入口（图标用 `FlaskConical` from lucide-react）。
页面内五个 tab：

1. **概览**：计数卡片（项目/用例/脚本/运行/进行中任务）+ 项目表格（key、名称、base_url、用例数、活跃任务）。
2. **任务板**：任务列表（角色、标题、状态徽标、进度条、更新时间），点开右侧抽屉显示 prompt、result、children、artifacts 与事件时间线。
   进行中/排队任务每 3 秒轮询刷新（页面可见时）；提供"取消"操作（needs_review 时不显示取消，显示"标记完成"）。
3. **用例库**：项目下拉 + kind/status 过滤 + 搜索；表格（code、title、kind、priority、status、tags）；
   抽屉里展示 steps 与 api JSON（代码块），可编辑（标题、kind、priority、status、steps 文本、api JSON 文本）；
   新建用例（选项目）；导入（粘贴 JSON）/导出（下载 JSON）。
4. **自动化**：脚本表格（名称、框架、文件路径、关联用例数、更新时间）；抽屉展示 content 编辑器（textarea，等宽字体），保存；
   新建脚本；"运行"按钮（framework=pytest 时可用，调用 qa.run.start 并展示结果；playwright/postman 提示暂不支持）。
5. **运行记录**：运行列表（状态、通过/失败/错误、耗时、开始时间）；点开显示 summary 与每条 test 的 name/status/message/checks。

## 3. 接入点（当前代码位置）

- `App.tsx:145` `type ShellView` → 增加 `"qa"`。
- `App.tsx:256` `readShellRoute()` → 增加 `if (path === "/qa") return { view: "qa", ... }`。
- `App.tsx` `shellRouteHash()`（约 331 行）→ 增加 qa 分支（看函数现有写法）。
- `App.tsx:3131` 附近 `{view !== "chat" && (...)}` → 在 `view === "remote"` 旁增加 `view === "qa"` 分支渲染新页面。
- `App.tsx` document.title effect（约 2729 行）→ 增加 qa 标题。
- `Sidebar.tsx:71-78` props 与 220-270 行 nav 项 → 增加 `onOpenQa` 与 `activeUtility: "qa"`。
- `App.tsx` 中调用 `<Sidebar ... />` 处传 `onOpenQa={() => navigate({view:"qa",...})}`，并让 `activeUtility` 支持 "qa"（约 2821 行）。
- token/transport：App 里已有 `client`（NanobotClient，带 `requestMutation`）与 token 状态；沿用现有页面获取方式（参考 `RemoteConnectionsPage` 与 `SettingsView` 的 props）。页面 props 建议 `{token, client, onBackToChat}`。
- 样式：`@/components/ui/*`（button/input/textarea/select/dialog/sheet/dropdown-menu）与 Tailwind；参考 `components/settings/*` 的排版。
- i18n：`webui/src/i18n/locales/{zh-CN,en}/common.json` 增加 `qa.*` key；组件里用 `t("qa.xxx", { defaultValue: "中文" })` 兜底。

## 4. 验收

- `cd webui && npm test -- qa`：新增测试通过（mock fetch + 假 transport）。
- `npm test`：全部通过（如遇与本功能无关的既有失败，记录并说明）。
- `npm run build` 通过（tsc + vite）。
- 页面在无数据时不报错（空状态文案），有数据时展示正常；错误时给出错误条而不是白屏。

## 5. 禁止

- 不改后端 Python 与 `/api/qa` 契约。
- 不新增第三方依赖。
- 不把 mutation 写成 fetch POST（会 405）。
- 不删改既有测试来"通过"。

## 6. v1.1 增补（审批 + CI 导入 + 运行元数据）

新增写 action：

| action | payload | 说明 |
|---|---|---|
| `qa.task.approve` | `{id, note?, reviewer?}` | 通过 needs_review 任务：status→done，result 追加 `[approved]`，写 approved 事件 |
| `qa.task.reject` | `{id, note?, reviewer?}` | 退回：status→failed，result 追加 `[rejected]`，写 rejected 事件 |
| `qa.run.import` | `{project_id, xml, name?, environment?, trigger?}` | 把 CI 的 JUnit XML 导入为一次运行（trigger 默认 ci），同步返回 run |

运行对象新增字段：`name: string`、`environment: string`、`trigger: "manual"|"ci"|"agent"|"schedule"`。
`qa.run.start` 也接受 `name` / `environment` / `trigger`。

UI 要求：

- **任务板**：`needs_review` 任务显示「通过」「退回」两个按钮，点击弹对话框填写备注（可选）+ 评审人（可选），成功后刷新列表与抽屉。
  抽屉里显示已记录的 `approved` / `rejected` 事件（含 reviewer 与备注）。
- **运行记录**：列表与抽屉显示 `name`（空则显示 `run.id` 前 8 位）、`environment`、`trigger` 徽标（manual/ci/agent/schedule 颜色区分）；
  顶部增加「导入 JUnit」按钮，弹窗包含：项目选择、运行名称、环境、XML 文本域（等宽），提交调用 `qa.run.import`，成功后在列表顶部插入并打开抽屉。
- **自动化**：运行脚本时也传 `name`（默认 `脚本名 + 时间`）与 `environment`（可留空）。

测试要求：为 approve/reject 与 import 各加一条组件测试（断言调用 `requestMutation` 的 action 与 payload），运行 `npm test -- qa` 与 `npm run build`。
