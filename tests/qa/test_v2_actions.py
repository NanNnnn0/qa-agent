"""HTTP and tool coverage for the v1.1 actions (approve/reject, CI import)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from qa_helpers import make_request

import nanobot.qa as qa_package
from nanobot.agent.tools.qa import QaProjectTool, QaRunTool, QaTaskTool
from nanobot.qa.http import QaApi
from nanobot.qa.store import QaStore
from nanobot.webui.http_utils import parse_request_path

JUNIT = (
    '<testsuite name="ci"><testcase name="ok" time="0.1"/>'
    '<testcase name="bad" time="0.2"><failure message="boom">trace</failure></testcase>'
    "</testsuite>"
)


async def _dispatch(api: QaApi, request: Any) -> Any:
    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got)


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


async def test_http_approve_and_reject(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    task = store.create_task(
        title="review me", role="api", project_id=project["id"], status="needs_review",
    )
    request = make_request(
        "/api/qa/tasks/approve",
        {"id": task["id"], "note": "looks good", "reviewer": "alice"},
    )
    response = await _dispatch(api, request)
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["task"]["status"] == "done"
    assert "looks good" in payload["task"]["result"]

    other = store.create_task(
        title="reject me", role="ui", project_id=project["id"], status="needs_review",
    )
    request = make_request(
        "/api/qa/tasks/reject", {"id": other["id"], "note": "missing permission case"},
    )
    response = await _dispatch(api, request)
    assert _body(response)["task"]["status"] == "failed"


async def test_http_run_import(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    request = make_request(
        "/api/qa/runs/import",
        {
            "project_id": project["id"],
            "xml": JUNIT,
            "name": "pipeline 7",
            "environment": "staging",
        },
    )
    response = await _dispatch(api, request)
    payload = _body(response)
    assert payload["ok"] is True
    run = payload["run"]
    assert run["trigger"] == "ci"
    assert run["name"] == "pipeline 7"
    assert run["environment"] == "staging"
    assert run["status"] == "failed"
    assert (run["passed"], run["failed"]) == (1, 1)


async def test_http_run_start_records_metadata(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    api = QaApi(store)
    store.update_project(project["id"], base_url=demo_api)
    case = store.create_case(
        project["id"],
        title="products",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    request = make_request(
        "/api/qa/runs/start",
        {
            "project_id": project["id"],
            "case_ids": [case["id"]],
            "name": "smoke",
            "environment": "local",
            "trigger": "agent",
        },
    )
    run = _body(await _dispatch(api, request))["run"]
    assert (run["name"], run["environment"], run["trigger"]) == ("smoke", "local", "agent")


async def test_http_import_rejects_invalid_xml(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    request = make_request(
        "/api/qa/runs/import", {"project_id": project["id"], "xml": "<broken"},
    )
    response = await _dispatch(api, request)
    assert response.status_code == 400
    assert _body(response)["ok"] is False


@pytest.fixture(autouse=True)
def qa_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "qa.sqlite3"
    monkeypatch.setenv("NANOBOT_QA_DB", str(path))
    qa_package._STORE_CACHE.clear()
    yield path
    qa_package._STORE_CACHE.clear()


async def _tool_project() -> str:
    payload = json.loads(str(await QaProjectTool().execute(
        "create", key="shop", name="Shop", base_url="http://127.0.0.1:1",
    )))
    return payload["project"]["id"]


async def test_tool_run_import() -> None:
    project_id = await _tool_project()
    tool = QaRunTool()
    result = await tool.execute(
        "import", project_id=project_id, xml=JUNIT, name="nightly", environment="ci",
    )
    payload = json.loads(str(result))
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["name"] == "nightly"
    assert payload["run"]["trigger"] == "ci"


async def test_tool_task_approve_and_reject() -> None:
    project_id = await _tool_project()
    tool = QaTaskTool(None)
    task = json.loads(str(await tool.execute(
        "create", project_id=project_id, title="接口", role="api",
    )))["task"]
    # The specialist marks it for review, then a human approves it.
    await tool.execute("update", task_id=task["id"], status="needs_review", progress=90)
    approved = json.loads(str(await tool.execute(
        "approve", task_id=task["id"], note="通过", reviewer="alice",
    )))
    assert approved["task"]["status"] == "done"

    rejected_task = json.loads(str(await tool.execute(
        "create", project_id=project_id, title="功能", role="ui",
    )))["task"]
    await tool.execute("update", task_id=rejected_task["id"], status="needs_review")
    rejected = json.loads(str(await tool.execute(
        "reject", task_id=rejected_task["id"], note="缺少权限用例",
    )))
    assert rejected["task"]["status"] == "failed"
