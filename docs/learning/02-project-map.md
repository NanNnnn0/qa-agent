# 测试范围与实现依据

本文件供设计或归因时查阅，不要求先通读源码。依据来自部署目录 `/opt/qa-agent` 的代码基线 `e43ba24d279589d53f487462cf667c9f59c8a515`，不代表该版本全部能力已验证。文档 worktree 的代码基线较旧，后续实际测试要单独记录目标服务版本。

## 范围

首轮测试主 Agent 接收车易查任务后对项目、用例和预检工具的使用。车易查资料路径是部署目录中的现有数据，本分支不复制它们，也不把追溯文件的 project_id 当作运行时数据库 ID。

| 测试依据 | 代码或文件位置 | 可以设计的检查 |
|---|---|---|
| 模型调用工具并接收结果 | [agent/runner.py](/opt/qa-agent/nanobot/agent/runner.py:472) | 选择的工具、传入参数、结果回传后的下一步 |
| 项目查询与绑定 | [qa.py](/opt/qa-agent/nanobot/agent/tools/qa.py:175) | 项目 ID 是否真实、是否误用其他项目 |
| 用例列表和详情 | [qa.py](/opt/qa-agent/nanobot/agent/tools/qa.py:306) | 是否读取真实用例，是否仅凭标题编造请求或断言 |
| 预检入口 | [api_tools.py](/opt/qa-agent/nanobot/qa/api_tools.py:464) | action、project_id、case_ids 是否符合范围 |
| 预检规则 | [execution.py](/opt/qa-agent/nanobot/qa/execution.py:187) | ready、请求、断言、变量等阻塞是否被如实解释 |
| 异步运行 | [api_tools.py](/opt/qa-agent/nanobot/qa/api_tools.py:479) | running 是否被错误当成最终成功，是否查询终态 |
| 固定断言 | [runner.py](/opt/qa-agent/nanobot/qa/runner.py:145) | 报告成功实际证明了哪些条件 |
| 响应预览限制 | [runner.py](/opt/qa-agent/nanobot/qa/runner.py:315) | 是否把截断的预览说成完整业务证据 |

## 业务场景的事实与未知

[车易查来源登记](/opt/qa-agent/qa-workbench/projects/cheyicha-api/sources/API-CHEYICHA_API-0788b556-8e56-4f21-8040-5e17b2594e8a.yaml:5) 指向注册接口说明，但仍需核对原始契约内容；迁移用例标题里的历史“实测”不自动成为本次实测证据。

[注册成功用例](/opt/qa-agent/qa-workbench/projects/cheyicha-api/cases/TC-CHEYICHA_API-001.yaml:1) 的编号是 CHEYICHA-API-API-001，文件状态为 reviewed，预期含业务码 200 和 token 检查。执行器只接受 ready；这是测试线索，工作台运行时状态仍需你核实。

## 能力边界

预检是配置和用例的静态检查，不发被测接口请求；预检 ok 不能证明服务可达或业务通过。主 Agent 可用的 qa_api_* 工具范围见 [qa_api.py](/opt/qa-agent/nanobot/agent/tools/qa_api.py:28)，子 Agent 提示词与工具权限存在静态不匹配，首轮不派单。

报告的 method、url 和正文预览不能替代完整请求响应。任务状态更新、产物登记仅在确实创建 QA 任务时检查，不要求每次普通聊天都创建任务或写产物。

尚未验证：当前模型凭证可用性、前端能否取得完整工具输入输出、车易查业务可达性、主 Agent 端到端行为。若工具轨迹缺失，对相应内部行为记证据不足，不凭最终回复推断。
