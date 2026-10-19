---
name: qa-api-testing
description: 从接口资料生成可维护的结构化接口用例：登记接口目录、按场景矩阵设计、批次校验后落库、预检执行并给出结论。
metadata: {"nanobot":{"emoji":"🔌"}}
---

# 接口测试

## 固定顺序

登记资料 → 设计场景 → 提交批次 → 校验 → 应用 → 预检 → 执行 → 结论。顺序不要跳步：没有登记过的接口，用例里不要引用。

## 第 1 步：登记接口资料

- **OpenAPI 3.0/3.1（JSON 或 YAML）**：`qa_api_catalog action=ingest project_id=... document="<文档全文>"`。
- **本地文件**：先在部署环境配置 `NANOBOT_QA_SPEC_ROOTS`（多个目录用 `:` 分隔），再传 `source_path=/srv/specs/orders.yaml`。路径不在允许目录内会直接报错，不会自动下载远程文档。
- **Markdown / 源码片段**：自己定位相关段落，用 `source_kind=markdown|source` + `source_ref`（文件路径或提交号）+ 摘录登记，不追求通用解析。
- 重复登记同一份资料不会新增接口；资料里删掉的接口会被标记为 `missing`，已有用例不会被删除，但引用它的用例会在预检时被拦下。
- 先用 `action=diff` 看会新增、变更、消失哪些接口，再决定是否 `action=ingest`；`action=list` 默认每页 10 条，`action=get` 取单个接口的 spec 与证据。

## 第 2 步：场景矩阵

对每个接口按需覆盖（不是每个接口都要全填）：

| 维度 | 例子 |
|---|---|
| 正常 | 合法参数 → 2xx 且业务 code=0 |
| 必填缺失 | 少一个必填参数 → 400 + 业务错误码 |
| 类型/格式非法 | qty="abc"、email 非法 |
| 边界 | qty=0、1、库存上限、超长字符串 |
| 业务异常 | 库存不足、重复下单、余额不足 |
| 权限 | 未登录 401、无权限 403、越权访问他人资源 404 |
| 幂等/并发（重要接口） | 重复提交同一幂等键只成功一次 |

- 状态码和业务码必须有依据：需求文档、已确认的契约，或已观测的接口行为。没有依据的预期写进 `preconditions` 或在结论里标为待确认，不要猜。
- 源码只用来理解实现，不作为预期来源。

## 第 3 步：提交候选批次

```json
{"project_id":"proj_xxx",
 "idempotency_key":"orders-2026-10-19",
 "candidates":[{
   "case":{"title":"库存不足时下单返回 1001","kind":"api","priority":"P0","status":"ready",
     "preconditions":"商品 A-1 库存为 0",
     "api":{"request":{"method":"POST","path":"/api/orders",
             "headers":{"Content-Type":"application/json"},
             "body":{"sku":"A-1","qty":999}},
            "assertions":[{"type":"status","expect":400},
                          {"type":"json_path","path":"$.code","op":"equals","expect":1001}]},
     "expected":"提示库存不足，不扣减库存"},
   "operation":{"method":"POST","path":"/api/orders"},
   "scenario_key":"order-out-of-stock",
   "evidence":[{"kind":"openapi","ref":"#/paths/~1api~1orders/post"}]}]}
```

- `scenario_key` 要稳定（小写字母 + 连字符），同一个接口的同一个场景重复提交会**更新原用例**，不会新建。
- 单批候选 ≤50 条，超出就分批提交；每批用不同的 `idempotency_key`。
- 要覆盖别人可能改过的用例时带 `base_revision`；基线过期会报冲突，先 `qa_api_workflow action=get` 看当前修订。
- 流程：`action=create` 拿到 workflow_id → `action=validate` 看每条是 create 还是 update、有没有错误 → `action=apply` 才真正落库。
- 批次失败：`action=resume` 看检查点和错误，修好候选后 `action=submit` 替换，再 `action=apply`。已 applied 的批次重复 apply 不会产生副作用。
- 需要留档：`action=export` 返回批次和用例修订快照，适合提交进 Git。

## 第 4 步：预检与执行

先预检，再执行，不要跳过预检：

- `qa_api_run action=preflight project_id=...`：返回阻塞项。常见阻塞是未 ready、缺 `api.request`、缺断言、变量缺失、引用的接口资料已 `missing`、项目没有 base_url、鉴权配置错误。有阻塞就修用例或资料。
- `qa_api_run action=start project_id=... case_ids=[...] auth={...}`：走固定 pytest 模板执行。运行记录会固定每条用例的修订号和模板版本，之后改用例不会改变这次运行依据；超过 200 条自动分批，汇总覆盖全部选中范围。默认异步：返回 `status=running` 的 run，随后用 `qa_api_run action=get run_id=...` 轮询（或传 `wait=true` 直接等）；同一项目的运行会排队串行执行。
- 有序计划：传 `plan` 对象，`{"version":"1","setup":[{"case_id":"...","revision":3}],"cases":[...],"cleanup":[...]}`。setup 先跑，setup 失败会跳过 cases（标记 dependency_blocked），cleanup 仍会执行；cleanup 失败单独记为 cleanup_failed。步骤里的 revision 必须等于用例当前修订，否则预检直接拦下。`plan` 与 `case_ids` 二选一。
- `qa_api_run action=get run_id=...`：看结论和失败用例的分类。
- 鉴权：`auth` 支持 `{"kind":"bearer","token":"env:QA_TOKEN"}` 和 `{"kind":"login","path":"/api/login","body":{"user":"env:QA_USER","password":"env:QA_PASS"},"token_path":"$.data.token"}`。凭证只存在于运行上下文，报告和日志已脱敏。
- 需要串场数据：在创建用例里写 `api.extract`（名字到 JSONPath 的映射），后续用例用 `run.` 前缀的占位符引用；提取值只在本次运行内有效。

失败分类：`assertion_failed`（断言失败，先判断是产品缺陷还是断言写错）、`config_error`（用例或配置问题）、`env_blocked`（连不上，报阻塞而不是缺陷）、`auth_failed`（登录或凭证问题）。

临时手工验证仍可用 `qa_run action=start`，但它不做预检、不固定快照、不分批，也不脱敏，不要用它出正式结论。

## 第 5 步：结论

用 `qa_task action=update` 落结论，并 `qa_task action=artifact` 挂上 run。
缺陷摘要格式：`接口 + 场景 + 期望 vs 实际 + 复现请求(curl) + 初步判断`。

## 边界

- 只写结构化产物到 qa_* 工具，不要在对话里贴一堆 JSON 当交付。
- 不要断言时间戳、随机 id、自增主键的具体值；用 `exists` 或正则 `matches`。
- 不改别人的结论；评审角色只增补用例或给判定。
