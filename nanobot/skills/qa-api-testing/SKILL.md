---
name: qa-api-testing
description: 从接口资料生成可维护的结构化接口用例：登记接口目录、按场景矩阵设计、批次校验后落库、执行并给出结论。
metadata: {"nanobot":{"emoji":"🔌"}}
---

# 接口测试

## 固定顺序

登记资料 → 设计场景 → 提交批次 → 校验 → 应用 → 执行 → 结论。顺序不要跳步：没有登记过的接口，用例里不要引用。

## 第 1 步：登记接口资料

- **OpenAPI 3.0/3.1（JSON 或 YAML）**：`qa_api_catalog action=ingest project_id=... document="<文档全文>"`。
- **本地文件**：先在部署环境配置 `NANOBOT_QA_SPEC_ROOTS`（多个目录用 `:` 分隔），再传 `source_path=/srv/specs/orders.yaml`。路径不在允许目录内会直接报错，不会自动下载远程文档。
- **Markdown / 源码片段**：自己定位相关段落，用 `source_kind=markdown|source` + `source_ref`（文件路径或提交号）+ 摘录登记，不追求通用解析。
- 重复登记同一份资料不会新增接口；资料里删掉的接口会被标记为 `missing`，已有用例不会被删除。
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

## 第 4 步：执行

`qa_run action=start project_id=... case_ids=[...]`。结果：

- `passed`：全部断言通过。
- `failed`：断言失败 → 逐条看 `checks`，区分产品缺陷和断言写错。
- `blocked_by_env`：全部用例连不上 → 检查 base_url 和服务是否启动，报告阻塞而不是报缺陷。

需要登录的接口：把 token 放进项目 `default_env`（`{"token":"..."}`），用例里写 `{{token}}`。

## 第 5 步：结论

用 `qa_task action=update` 落结论，并 `qa_task action=artifact` 挂上 run。
缺陷摘要格式：`接口 + 场景 + 期望 vs 实际 + 复现请求(curl) + 初步判断`。

## 边界

- 只写结构化产物到 qa_* 工具，不要在对话里贴一堆 JSON 当交付。
- 不要断言时间戳、随机 id、自增主键的具体值；用 `exists` 或正则 `matches`。
- 不改别人的结论；评审角色只增补用例或给判定。
