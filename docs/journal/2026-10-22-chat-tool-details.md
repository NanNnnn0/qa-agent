# 2026-10-22 chat-tool-details

- Goal: 对话里「已处理 30s」折叠区中的工具调用行可以点开，看到实际的调用参数与返回结果，而不只是一句摘要。
- Changed: `webui/src/components/thread/activity/tool-detail-model.ts`（新增：把 trace 行/工具事件整理成详情条目，脱敏、长文本截断）；`.../ToolCallDetail.tsx`（新增：参数/命令/结果/错误分区，复制与「显示全部」）；`.../ActivityStep.tsx`（有详情时整行变成可展开按钮，右侧 chevron，带 `aria-expanded`）；`AgentActivityCluster.tsx`（通用工具行、trace 行、CLI 行、MCP 行接入详情，事件里的 `result` 保留到行模型）；`GenericToolRun.tsx`（分组行逐条列出每次调用）；`lib/tool-traces.ts`（新增 `parseToolTraceCall`）；`generic-tool-model.ts`（行模型带 `arguments`/`result`）；10 个 locale 增加 `message.toolDetail.*`；新增 `webui/src/tests/activity-tool-detail.test.tsx`。
- Behavior: 行折叠时不渲染详情，点行展开；同一工具连续多次合并成一行时，展开后按顺序列出每一次的入参与结果；结果超过 4000 字符先截断，可「显示全部」；命令/参数/结果沿用既有脱敏规则；没有记录到入参或结果的行保持不可点。
- Verified: `npx tsc -p tsconfig.build.json --noEmit` 通过；本地 eslint 通过；相关 7 个测试文件 144 passed、新增 5 passed；全量 `npm test` 2848 passed / 2 failed（`app-layout` 的 context-menu 项目与 `temporary-chat-navigation`，均为既有失败）。
- Not done: 网页搜索行继续用自己的结果展示；历史会话的 trace 详情是懒加载的，先展开外层活动区加载完成后行才可点开。
- Affects other sessions: `ActivityStep` 在有 `details` 时整行渲染为 `<button>`（可点），按行 DOM 写的测试要用 `activity-line` / `aria-expanded` 查询；`CliRunSummary`、`McpRunSummary` 新增 `result` 字段。
