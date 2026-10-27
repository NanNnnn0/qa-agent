# 2026-10-27 docs-readme

- Goal: 根 README 从「上游 nanobot 原文」换成本分支自己的说明，并补一份中文版；别人打开仓库能直接看懂这是什么、怎么跑。
- Changed: `README.md`（重写，英文，429 行，替换 913 行的上游原文）；`README.CN.md`（新增，简体中文，428 行）；`docs/images/qa-workbench-{overview,cases,trace,tasks}.jpg`（新增截图，共 288 KB）。
- Behavior: 顶部语言切换 English / 简体中文，两份文档内容等价；截图来自隔离的演示实例（`qa seed` 的 SHOP 项目 + `login-lock` 追溯演示），不含线上项目数据。
- Verified: 脚本校验 20 个相对链接全部存在；Markdown 渲染后逐屏检查（表格、代码块、图片宽度、锚点）；`git diff --stat` 为 README.md 426 插入 / 913 删除；文档类改动不触发 `fork-gate.yml` 与 `scripts/hooks/pre-push`。
- Not done: 没有 `docs/qa-agent.md` 的英文版；截图是简体中文界面（界面本身只有中文）。
- Affects other sessions: 根 README 归本分支维护，上游能力说明改由 `docs/README.md` 承担；`README.md` 行尾统一为 LF（其余 fork 自有文档同样如此），上游 README 原本是 CRLF，整文件 diff 属预期；`README.CN.md` 是新增文件，改 README 的会话要同时改两份。
