"""Tests for the QA agent tools (the model-facing contract)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import nanobot.qa as qa_package
from nanobot.agent.tools.qa import (
    QaCaseTool,
    QaOverviewTool,
    QaProjectTool,
    QaRunTool,
    QaScriptTool,
    QaTaskTool,
)


@pytest.fixture(autouse=True)
def qa_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "qa.sqlite3"
    monkeypatch.setenv("NANOBOT_QA_DB", str(path))
    qa_package._STORE_CACHE.clear()
    yield path
    qa_package._STORE_CACHE.clear()


def _json(result: Any) -> dict[str, Any]:
    return json.loads(str(result))


async def _create_project() -> str:
    payload = _json(await QaProjectTool().execute(
        "create", key="shop", name="Shop", base_url="http://127.0.0.1:8799",
    ))
    return payload["project"]["id"]


async def test_project_tool_round_trip() -> None:
    project_id = await _create_project()
    payload = _json(await QaProjectTool().execute("get", project_id=project_id))
    assert payload["project"]["key"] == "SHOP"
    payload = _json(await QaProjectTool().execute("list"))
    assert len(payload["projects"]) == 1
    payload = _json(await QaProjectTool().execute(
        "update", project_id=project_id, name="Shop 2",
    ))
    assert payload["project"]["name"] == "Shop 2"


async def test_project_tool_rejects_invalid_action() -> None:
    result = await QaProjectTool().execute("destroy")
    assert str(result).startswith("Error:")


async def test_case_tool_bulk_create_and_validation() -> None:
    project_id = await _create_project()
    tool = QaCaseTool()
    payload = _json(await tool.execute(
        "bulk_create",
        project_id=project_id,
        cases=[
            {
                "title": "create order",
                "kind": "api",
                "priority": "P0",
                "api": {
                    "request": {"method": "POST", "path": "/api/orders"},
                    "assertions": [{"type": "status", "expect": 201}],
                },
            },
            {"title": "cart flow", "kind": "ui",
             "steps": [{"action": "open cart", "expected": "visible"}]},
            {"title": "broken", "kind": "api",
             "api": {"request": {"method": "NOPE", "path": "/x"}}},
        ],
    ))
    assert payload["count"] == 2
    assert payload["errors"][0]["index"] == 2

    listing = _json(await tool.execute("list", project_id=project_id))
    assert listing["total"] == 2
    assert listing["cases"][0]["code"] == "SHOP-API-001"
    assert listing["cases"][1]["steps"] == 1

    case_id = listing["cases"][0]["id"]
    detail = _json(await tool.execute("get", case_id=case_id))
    assert detail["case"]["api"]["request"]["method"] == "POST"

    updated = _json(await tool.execute("update", case_id=case_id, status="ready"))
    assert updated["case"]["status"] == "ready"

    deleted = _json(await tool.execute("delete", case_id=case_id))
    assert deleted["deleted"] == case_id


async def test_script_tool_lifecycle() -> None:
    project_id = await _create_project()
    tool = QaScriptTool()
    payload = _json(await tool.execute(
        "create",
        project_id=project_id,
        name="smoke",
        framework="pytest",
        file_path="tests/test_smoke.py",
        content="def test_ok():\n    assert True\n",
    ))
    script_id = payload["script"]["id"]
    listing = _json(await tool.execute("list", project_id=project_id))
    assert listing["items"][0]["content_lines"] == 2
    detail = _json(await tool.execute("get", script_id=script_id))
    assert "assert True" in detail["script"]["content"]
    updated = _json(await tool.execute("update", script_id=script_id, status="ready"))
    assert updated["script"]["status"] == "ready"


async def test_task_tool_plan_without_dispatch() -> None:
    project_id = await _create_project()
    tool = QaTaskTool(None)
    payload = _json(await tool.execute(
        "plan",
        project_id=project_id,
        title="回归",
        tasks=[
            {"role": "api", "title": "接口", "prompt": "覆盖下单"},
            {"role": "ui", "title": "功能", "prompt": "覆盖购物车"},
        ],
        dispatch={"dispatch": False},
    ))
    assert payload["dispatched"] is False
    assert len(payload["tasks"]) == 2
    parent_id = payload["parent"]["id"]

    listing = _json(await tool.execute("list", project_id=project_id))
    assert listing["total"] == 3

    detail = _json(await tool.execute("get", task_id=parent_id))
    assert len(detail["task"]["children"]) == 2

    child_id = payload["tasks"][0]["id"]
    updated = _json(await tool.execute("update", task_id=child_id, status="done",
                                       result="2 条用例，全部通过"))
    assert updated["task"]["status"] == "done"
    assert updated["task"]["progress"] == 100

    overview = _json(await QaOverviewTool().execute())
    assert overview["counts"]["tasks"] == 3


async def test_dispatch_without_manager_reports_error() -> None:
    project_id = await _create_project()
    task = _json(await QaTaskTool(None).execute(
        "create", project_id=project_id, title="接口测试", role="api",
    ))
    result = await QaTaskTool(None).execute("dispatch", task_id=task["task"]["id"])
    assert str(result).startswith("Error:")
    assert "subagent manager" in str(result)


async def test_run_tool_executes_cases(demo_api: str) -> None:
    project_id = await _create_project()
    await QaProjectTool().execute("update", project_id=project_id, base_url=demo_api)
    await QaCaseTool().execute(
        "create",
        project_id=project_id,
        title="products",
        kind="api",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    tool = QaRunTool()
    payload = _json(await tool.execute("start", project_id=project_id, kind="api"))
    assert payload["run"]["status"] == "passed"
    run_id = payload["run"]["id"]
    detail = _json(await tool.execute("get", run_id=run_id))
    assert detail["run"]["report"]["tests"][0]["status"] == "passed"
    listing = _json(await tool.execute("list", project_id=project_id))
    assert listing["total"] == 1
