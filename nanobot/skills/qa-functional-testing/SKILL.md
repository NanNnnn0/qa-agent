---
name: qa-functional-testing
description: 把需求拆成测试点，产出带前置/步骤/预期的功能用例，并标注自动化候选。
metadata: {"nanobot":{"emoji":"🧪"}}
---

# 功能测试用例设计

## 第 1 步：从需求提取测试点

逐条读需求，对每个"用户可观察的行为"写一个测试点。使用以下清单自查：
- **正常流**：主路径 + 最常见的两个变体。
- **边界**：空、最小、最大、刚好越界。
- **异常**：网络失败、服务报错、重复提交、超时。
- **状态流转**：待支付→已支付→已发货→已完成，以及非法跳转。
- **权限/角色**：游客/普通用户/管理员分别能看到什么。
- **数据一致性**：页面显示与接口/数据库一致（金额、库存、订单状态）。

## 第 2 步：写成步骤化用例

```json
{"project_id":"proj_xxx",
 "cases":[{
   "title":"购物车库存不足时结算被拦截",
   "kind":"ui","priority":"P1",
   "preconditions":"购物车有商品 A-1，库存为 0",
   "steps":[
     {"action":"打开购物车页面","expected":"展示 A-1，数量 1"},
     {"action":"点击【去结算】","expected":"提示库存不足，停留在购物车页"},
     {"action":"刷新页面","expected":"商品仍在购物车，未生成订单"}
   ],
   "expected":"不创建订单，给出明确错误提示",
   "tags":["cart","regression"]
 }]}
```

用 `qa_case action=bulk_create` 落库（kind=ui 或 manual）。
- 每条用例只验证一个行为；步骤里不要出现"验证一切正常"这种不可判定的预期。
- 前置条件必须可复现（数据、账号、开关状态）。
- 需要自动化的用例加 `tags:["automate"]`，并把 case_id 交给 automation 角色。

## 第 3 步：覆盖度自检

回答三件事，写进 `qa_task action=update` 的结论：
1. 需求里每条验收标准对应哪个用例编号？
2. 哪些风险最高（金额、权限、并发）？有没有对应用例？
3. 哪些点没有测/测不了，原因是什么？

## 不要做

- 不要把接口用例粘进功能用例（重复库会分裂，后续维护必然漏改）。
- 不要用"页面正常显示"作为唯一断言；要写可观察的具体文案/数值。
- 不要跳过前置条件直接写步骤。

## 链路：用例挂测试点，测试点挂来源

用例进正式库的前提是"有链路"：`testpoints` 或（少数情况）`sources` 至少一个。

1. 先查已有的：`qa_testpoint action=list entity=testpoint`；没有合适的再 `action=list entity=source`。
2. 没有来源就先建：`qa_testpoint action=create entity=source source_type=api|req|ui|bug|std|ex title=... evidence=[{"type":"openapi","locator":"#/paths/~1api~1x/post"}]`。来源必须带证据；`confidence=confirmed` 只用于用户提供的权威文档（评审会拒绝 observed 来源下的测试点）。
3. 建测试点：`qa_testpoint action=create entity=testpoint title=... sources=["API-..."] method=boundary risk=low`。
4. 写用例时挂上：`qa_case action=create ... testpoints=["TP-..."]`。`status=ready` 必须挂测试点，否则工具直接报错；`draft` 允许先不挂、后补。
5. 草稿要在「测试点」页签（或 `qa trace review approve`）通过评审，用例才进正式库、覆盖率才算数。

硬性规则：
- 一条用例挂 1 个测试点（最多 3 个）；一个测试点可以被多条用例覆盖。
- 直接挂来源（`sources`）是例外：确实没有合适测试点时才用，并且必须写 `direct_reason`。
- 不要编造 id：`sources`/`testpoints` 只能填工具列出来的、已存在的 id。
- 存量用例没挂链路：`qa_testpoint action=attach testpoint_id=... case_ids=[...]` 批量补。

