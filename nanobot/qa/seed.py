"""Demo fixtures: a small shop project with realistic API/UI cases.

``python -m nanobot.cli qa seed`` (or the CLI alias) writes these into the QA
database so a fresh install has something to look at in the QA workbench.
"""

from __future__ import annotations

from typing import Any

from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaConflictError

DEMO_KEY = "SHOP"
DEMO_BASE_URL = "http://127.0.0.1:8799"


def _api_cases() -> list[dict[str, Any]]:
    return [
        {
            "title": "商品列表返回 200 且 items 为数组",
            "kind": "api",
            "priority": "P0",
            "status": "ready",
            "api": {
                "request": {"method": "GET", "path": "/api/products"},
                "assertions": [
                    {"type": "status", "expect": 200},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 0},
                    {"type": "json_path", "path": "$.items", "op": "exists"},
                ],
            },
            "expected": "返回 200，code=0，items 存在",
            "tags": ["smoke", "catalog"],
        },
        {
            "title": "正常下单返回 201 并生成订单号",
            "kind": "api",
            "priority": "P0",
            "status": "ready",
            "preconditions": "商品 A-1 库存充足",
            "api": {
                "request": {
                    "method": "POST",
                    "path": "/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"sku": "A-1", "qty": 2},
                },
                "assertions": [
                    {"type": "status", "expect": 201},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 0},
                    {"type": "json_path", "path": "$.data.orderId", "op": "exists"},
                ],
            },
            "expected": "下单成功，返回订单号",
            "tags": ["smoke", "order"],
        },
        {
            "title": "库存不足时下单被拒绝（code=1001）",
            "kind": "api",
            "priority": "P0",
            "status": "ready",
            "preconditions": "商品 A-1 库存为 5",
            "api": {
                "request": {
                    "method": "POST",
                    "path": "/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"sku": "A-1", "qty": 999},
                },
                "assertions": [
                    {"type": "status", "expect": 400},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 1001},
                ],
            },
            "expected": "返回 400 + 业务码 1001，不创建订单",
            "tags": ["order", "negative"],
        },
        {
            "title": "数量非法（qty=0）返回参数错误 1000",
            "kind": "api",
            "priority": "P1",
            "status": "ready",
            "api": {
                "request": {
                    "method": "POST",
                    "path": "/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"sku": "A-1", "qty": 0},
                },
                "assertions": [
                    {"type": "status", "expect": 400},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 1000},
                ],
            },
            "expected": "参数校验生效",
            "tags": ["order", "negative", "boundary"],
        },
        {
            "title": "未知 SKU 返回 404 + 1002",
            "kind": "api",
            "priority": "P1",
            "status": "ready",
            "api": {
                "request": {
                    "method": "POST",
                    "path": "/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"sku": "NOPE-999", "qty": 1},
                },
                "assertions": [
                    {"type": "status", "expect": 404},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 1002},
                ],
            },
            "expected": "返回 SKU 不存在",
            "tags": ["order", "negative"],
        },
        {
            "title": "缺少 qty 时返回参数错误",
            "kind": "api",
            "priority": "P1",
            "status": "ready",
            "api": {
                "request": {
                    "method": "POST",
                    "path": "/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"sku": "A-1"},
                },
                "assertions": [
                    {"type": "status", "expect": 400},
                    {"type": "json_path", "path": "$.code", "op": "equals", "expect": 1000},
                ],
            },
            "expected": "缺少必填参数被拒绝",
            "tags": ["order", "negative"],
        },
    ]


def _ui_cases() -> list[dict[str, Any]]:
    return [
        {
            "title": "购物车结算流程：库存充足时下单成功",
            "kind": "ui",
            "priority": "P1",
            "status": "ready",
            "preconditions": "已登录，购物车含 A-1 两件",
            "steps": [
                {"action": "打开购物车页面", "expected": "展示 A-1，数量 2，金额 398"},
                {"action": "点击【去结算】", "expected": "进入订单确认页"},
                {"action": "点击【提交订单】", "expected": "提示下单成功并跳转订单详情"},
            ],
            "expected": "订单创建成功，购物车清空",
            "tags": ["cart", "regression"],
        },
        {
            "title": "库存不足时前端拦截结算",
            "kind": "ui",
            "priority": "P1",
            "status": "ready",
            "preconditions": "购物车含库存为 0 的商品",
            "steps": [
                {"action": "点击【去结算】", "expected": "提示库存不足，停留在购物车"},
                {"action": "刷新页面", "expected": "商品仍在购物车，未生成订单"},
            ],
            "expected": "不创建订单，错误提示可理解",
            "tags": ["cart", "negative"],
        },
    ]


PYTEST_TEMPLATE = '''"""Shop API smoke tests generated for the QA Agent demo.

Runs against $QA_BASE_URL (default http://127.0.0.1:8799).
"""

import os

import httpx

BASE_URL = os.environ.get("QA_BASE_URL", "http://127.0.0.1:8799")


def test_SHOP_API_001_product_list():
    resp = httpx.get(f"{BASE_URL}/api/products", timeout=10)
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0


def test_SHOP_API_003_insufficient_stock():
    resp = httpx.post(f"{BASE_URL}/api/orders", json={"sku": "A-1", "qty": 999}, timeout=10)
    body = resp.json()
    assert resp.status_code == 400, resp.text
    assert body["code"] == 1001, body
'''


def seed_demo(store: QaStore, *, base_url: str = DEMO_BASE_URL) -> dict[str, Any]:
    """Create the demo project and fixtures; safe to call repeatedly."""
    try:
        project = store.create_project(
            key=DEMO_KEY,
            name="Demo 商城",
            description="QA Agent 演示项目：商品目录 + 下单接口",
            base_url=base_url,
            default_env={},
        )
    except QaConflictError:
        project = store.get_project_by_key(DEMO_KEY)
        return {
            "created": 0,
            "project": project,
            "message": "demo project already exists",
        }

    cases = [
        store.create_case(project["id"], source="ai", author="qa-agent", **item)
        for item in (*_api_cases(), *_ui_cases())
    ]
    script = store.create_script(
        project["id"],
        name="shop_api_smoke",
        framework="pytest",
        language="python",
        file_path="tests/test_shop_api.py",
        content=PYTEST_TEMPLATE,
        case_ids=[case["id"] for case in cases if case["kind"] == "api"][:2],
        tags=["smoke"],
        status="ready",
    )

    parent = store.create_task(
        title="商城下单回归（演示）",
        prompt="演示派单：接口用例 + 购物车功能用例",
        role="orchestrator",
        project_id=project["id"],
        status="running",
        progress=60,
    )
    api_task = store.create_task(
        title="下单接口用例设计与执行",
        prompt="覆盖正常下单、库存不足、参数非法、未知 SKU",
        role="api",
        project_id=project["id"],
        parent_id=parent["id"],
        status="done",
        progress=100,
    )
    ui_task = store.create_task(
        title="购物车结算功能用例",
        prompt="覆盖结算成功与库存不足拦截",
        role="ui",
        project_id=project["id"],
        parent_id=parent["id"],
        status="needs_review",
        progress=80,
    )
    store.update_task(api_task["id"], result=(
        "已落库 6 条接口用例，覆盖正常/库存不足/参数非法/未知 SKU。"
        "等待 demo 服务启动后执行。"
    ))
    store.update_task(ui_task["id"], result=(
        "已产出 2 条功能用例，库存不足场景需产品确认提示文案。"
    ))
    for task in (parent, api_task, ui_task):
        store.add_event(task["id"], kind="progress", message="演示数据初始化")
    store.add_artifact(api_task["id"], kind="script", ref_id=script["id"],
                       title=script["name"])
    for case in cases[:3]:
        store.add_artifact(api_task["id"], kind="case", ref_id=case["id"],
                           title=case["title"])
    store.add_event(ui_task["id"], kind="status", message="status → needs_review")
    return {
        "created": len(cases),
        "project": project,
        "cases": [case["code"] for case in cases],
        "script": script["name"],
        "tasks": {"parent": parent["id"], "api": api_task["id"], "ui": ui_task["id"]},
    }
