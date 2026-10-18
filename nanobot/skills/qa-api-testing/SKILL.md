---
name: qa-api-testing
description: 从接口文档设计接口用例（等价类/边界/异常/权限），用结构化 api 字段落库并执行。
metadata: {"nanobot":{"emoji":"🔌"}}
---

# 接口测试

## 输入

接口文档（OpenAPI / Markdown / 口头描述）、项目 `base_url`、鉴权方式、测试账号。

## 第 1 步：用例矩阵

对每个接口至少覆盖：

| 维度 | 例子 |
|---|---|
| 正常 | 合法参数 → 2xx 且业务 code=0 |
| 必填缺失 | 少一个必填参数 → 400 + 业务错误码 |
| 类型/格式非法 | qty="abc"、email 非法 |
| 边界 | qty=0、1、库存上限、超长字符串 |
| 业务异常 | 库存不足、重复下单、余额不足 |
| 权限 | 未登录 401、无权限 403、越权访问他人资源 404 |
| 幂等/并发（重要接口） | 重复提交同一幂等键只成功一次 |

## 第 2 步：落库为结构化用例

```json
{"project_id":"proj_xxx",
 "cases":[{
   "title":"库存不足时下单返回 1001",
   "kind":"api","priority":"P0",
   "preconditions":"商品 A-1 库存为 0",
   "api":{
     "request":{"method":"POST","path":"/api/orders",
       "headers":{"Content-Type":"application/json"},
       "body":{"sku":"A-1","qty":999}},
     "assertions":[
       {"type":"status","expect":400},
       {"type":"json_path","path":"$.code","op":"equals","expect":1001}
     ]},
   "expected":"提示库存不足，不扣减库存"
 }]}
```

调用 `qa_case action=bulk_create`（单次 ≤50）。要求：
- `title` 一句话说清"场景 + 预期"；步骤细节进 `steps`，接口细节进 `api`。
- 每个用例至少一条**失败路径**断言。
- 需要登录的接口，把 token 放进项目 `default_env`（`{"token":"..."}`），用例里写 `{{token}}`。
- 不要断言时间戳、随机 id、自增主键的具体值；用 `exists` 或正则 `matches`。

## 第 3 步：执行

`qa_run action=start project_id=... case_ids=[...]`。结果：
- `passed`：全部断言通过。
- `failed`：断言失败 → 逐条看 `checks`，区分产品缺陷 vs 断言写错。
- `blocked_by_env`：全部用例连不上 → 检查 base_url / 服务是否启动，报告阻塞而不是报缺陷。

## 第 4 步：结论

用 `qa_task action=update` 落结论，并 `qa_task action=artifact` 挂上 run。
缺陷摘要格式：`接口 + 场景 + 期望 vs 实际 + 复现请求(curl) + 初步判断`。
