# 项目地图

## 研究对象

业务案例是车易查接口，当前资料目录为 `qa-workbench/projects/cheyicha-api/`。QA-Agent 是 nanobot fork 上的 QA 测试平台，提供项目、接口资料、测试点、用例、运行记录、任务和 Agent 工具。

车易查目录中的项目文件是 [project.yaml](../../qa-workbench/projects/cheyicha-api/project.yaml)，接口来源登记在 [注册接口资料](../../qa-workbench/projects/cheyicha-api/sources/API-CHEYICHA_API-0788b556-8e56-4f21-8040-5e17b2594e8a.yaml)，入门用例可从 [TC-CHEYICHA_API-001](../../qa-workbench/projects/cheyicha-api/cases/TC-CHEYICHA_API-001.yaml) 开始。该用例的当前文件状态是 `reviewed`，而执行器只接受 `ready` 用例；这是需要实际核对和处理的前置条件。

## 一条主流程

```text
学习者提出“验证车易查注册接口”
  -> 主 Agent 读取项目和工具说明
  -> 模型选择 qa_project / qa_case / qa_api_run 等工具并填写参数
  -> 平台读取结构化用例和项目 base_url
  -> 固定代码预检：状态、请求、断言、变量、目录和鉴权配置
  -> 固定执行器用 pytest 模板和 httpx 发请求
  -> 固定断言检查状态码、JSONPath、响应头、耗时或正文
  -> SQLite 保存运行、逐例结果、日志和分类
  -> 工具结果回传模型
  -> 模型组织结论和遗留风险
```

## 固定代码和模型判断的边界

| 环节 | 主要责任 | 当前依据 | 学习时要验证什么 |
|---|---|---|---|
| 任务理解 | 模型把自然语言转成目标和操作 | Agent runner 的模型调用循环 | 是否抓住接口、环境、范围和成功条件 |
| 项目/用例选择 | 模型选择工具和标识，代码校验参数 | `nanobot/agent/tools/qa.py`、`qa_api.py` | 是否选对项目、用例和动作 |
| 用例数据 | 结构化 request/assertions | `nanobot/qa/case_files.py`、`store.py` | 输入是否完整、断言是否足够强 |
| 预检 | 固定代码拒绝明显阻塞 | `nanobot/qa/execution.py` | 阻塞是否被正确报告，是否避免误发请求 |
| HTTP 执行 | 固定模板、pytest、httpx | `nanobot/qa/execution.py`、`runner.py` | 请求是否真正到达目标，响应是否被完整记录 |
| 结果判断 | 断言和分类由代码完成，最终解释由模型完成 | `runner.py`、`service.py`、Agent runner | 模型有没有把环境失败说成产品缺陷 |
| 任务完成 | 工具返回和模型收尾共同决定 | `qa_task`、角色契约 | 是否登记产物、更新状态并覆盖遗留风险 |

## 接口案例的学习顺序

先从注册成功用例开始，再选择一个不产生新用户或可安全隔离数据的异常用例，最后再做重复注册、边界长度和非 JSON body。注册接口会改变服务端数据，不能在没有测试账号、清理策略或明确隔离环境时反复执行。

## 当前已知限制

- 车易查项目的 base_url 和运行环境尚未在本轮确认，不能从 YAML 文件推断接口当前可达。
- 已有用例多为迁移产物，来源文件说明其部分依据来自历史 SQLite；历史记录可作为线索，不能替代当前需求或接口契约。
- `qa_api_*` 工具目前只加载到主 Agent，角色提示词与子 Agent 工具权限存在不匹配，因此首轮不把派单链路作为主学习入口。
- 报告中的响应正文是预览，不是无限长度的完整原文；原始请求和响应需要学习者在实验时另行保留。
- 运行服务处于监听状态不等于车易查业务接口、模型凭证或完整 Agent 链路已经验证。
