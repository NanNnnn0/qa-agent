---
name: qa-automation
description: 把已落库用例写成 pytest/Playwright 自动化脚本，遵循命名与数据规范，执行并修复。
metadata: {"nanobot":{"emoji":"🤖"}}
---

# 自动化脚本编写

## 什么时候写什么

| 场景 | framework | 说明 |
|---|---|---|
| 接口/契约 | `pytest` | pytest + httpx，可直接被 `qa_run` 执行 |
| 页面流程 | `playwright` | `@playwright/test` 或 `pytest-playwright`，需要浏览器环境 |
| 已有 collection | `postman` | 只保存导出文件，执行走 Postman CLI（Newman 已停止维护） |

## 脚本规范（硬性）

- 文件路径：`tests/<domain>/test_<behavior>.py`，或 `e2e/<flow>.spec.ts`，写入 `file_path`。
- 每个测试函数必须以对应用例编号开头，例如 `def test_SHOP_API_001_inventory_conflict()`，
  并在 `qa_script.case_ids` 里登记 case id，保证 用例↔脚本 可追溯。
- base_url / 账号 / token 从环境变量读取（`QA_BASE_URL`、`QA_TOKEN`），禁止硬编码域名与凭证。
- 明确超时；禁止 `time.sleep()` 等固定等待，UI 用 Playwright 的自动等待或显式 `expect(...)`。
- 断言失败信息要能定位：断言里带上 response body 或 locator。
- 不写 `try/except: pass`；skip 必须写 reason。

## pytest 模板

```python
import os
import httpx

BASE_URL = os.environ["QA_BASE_URL"]

def test_SHOP_API_001_inventory_conflict():
    resp = httpx.post(f"{BASE_URL}/api/orders", json={"sku": "A-1", "qty": 999}, timeout=10)
    body = resp.json()
    assert resp.status_code == 400, resp.text
    assert body["code"] == 1001, body
```

## Playwright 模板（Node）

```ts
import { test, expect } from "@playwright/test";

test("SHOP_UI_003 库存不足时结算被拦截", async ({ page }) => {
  await page.goto(`${process.env.QA_BASE_URL}/cart`);
  await page.getByRole("button", { name: "去结算" }).click();
  await expect(page.getByText("库存不足")).toBeVisible();
  await expect(page.getByText("支付成功")).toHaveCount(0);
});
```

## 执行与修复

1. `qa_script action=create` 落库（content 必填，file_path 必填）。
2. 需要落盘时按项目 `repo_path` 写文件，再 `qa_run action=start script_id=...`。
3. 失败处理顺序：环境问题 → 用例本身写错 → 定位器失效 → 真实缺陷。
4. **只允许修改定位器与等待条件**来修脚本；每用例最多修 2 次，超限把任务标 `needs_review`。
5. 绝不允许通过删除断言、放宽断言"修绿"。发现这一点必须在结论里写明。
