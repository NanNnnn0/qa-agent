"""Tests for the QA HTTP routes (reads + WebSocket mutations)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from qa_helpers import make_request
from websockets.http11 import Request as WsRequest

from nanobot.qa.http import QA_MUTATION_PATHS, QA_WRITE_PATHS, QaApi
from nanobot.qa.store import QaStore


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


async def _dispatch(api: QaApi, request: WsRequest, path: str | None = None) -> Any:
    from nanobot.webui.http_utils import parse_request_path

    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got if path is None else path)


async def test_read_routes_require_token(store: QaStore) -> None:
    api = QaApi(store, check_api_token=lambda request: False)
    response = await _dispatch(api, make_request("/api/qa/overview"))
    assert response.status_code == 401
    assert _body(response)["ok"] is False


async def test_overview_and_projects(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    response = await _dispatch(api, make_request("/api/qa/overview"))
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["counts"]["projects"] == 1

    response = await _dispatch(api, make_request("/api/qa/projects"))
    assert _body(response)["projects"][0]["key"] == "SHOP"


async def test_write_routes_require_websocket(store: QaStore) -> None:
    api = QaApi(store)
    response = await _dispatch(
        api, make_request("/api/qa/projects/create"), "/api/qa/projects/create",
    )
    assert response.status_code == 405


async def test_create_project_and_case_through_mutations(store: QaStore) -> None:
    api = QaApi(store)
    request = make_request(
        "/api/qa/projects/create",
        {"key": "crm", "name": "CRM", "base_url": "http://localhost:1"},
    )
    response = await _dispatch(api, request, "/api/qa/projects/create")
    payload = _body(response)
    assert payload["ok"] is True
    project_id = payload["project"]["id"]

    request = make_request(
        "/api/qa/cases/create",
        {
            "project_id": project_id,
            "title": "create customer",
            "kind": "api",
            "api": {
                "request": {"method": "POST", "path": "/api/customers"},
                "assertions": [{"type": "status", "expect": 201}],
            },
        },
    )
    response = await _dispatch(api, request, "/api/qa/cases/create")
    payload = _body(response)
    assert payload["case"]["code"] == "CRM-API-001"

    response = await _dispatch(
        api, make_request(f"/api/qa/cases?project_id={project_id}"),
    )
    listing = _body(response)
    assert listing["total"] == 1
    case_id = listing["items"][0]["id"]

    request = make_request("/api/qa/cases/update", {"id": case_id, "status": "ready"})
    response = await _dispatch(api, request, "/api/qa/cases/update")
    assert _body(response)["case"]["status"] == "ready"

    request = make_request("/api/qa/cases/delete", {"id": case_id})
    response = await _dispatch(api, request, "/api/qa/cases/delete")
    assert _body(response)["deleted"] is True
    response = await _dispatch(api, make_request(f"/api/qa/cases/{case_id}"))
    assert response.status_code == 404


async def test_validation_errors_are_json(store: QaStore) -> None:
    api = QaApi(store)
    request = make_request("/api/qa/projects/create", {"key": "1bad", "name": "x"})
    response = await _dispatch(api, request, "/api/qa/projects/create")
    assert response.status_code == 400
    assert _body(response)["ok"] is False


async def test_task_routes_and_run_start(store: QaStore, project: dict, demo_api: str) -> None:
    api = QaApi(store)
    store.update_project(project["id"], base_url=demo_api)
    case = store.create_case(
        project["id"],
        title="health",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    request = make_request(
        "/api/qa/runs/start", {"project_id": project["id"], "case_ids": [case["id"]]},
    )
    response = await _dispatch(api, request, "/api/qa/runs/start")
    payload = _body(response)
    assert payload["run"]["status"] == "passed"

    request = make_request(
        "/api/qa/tasks/create", {"title": "api work", "project_id": project["id"], "role": "api"},
    )
    response = await _dispatch(api, request, "/api/qa/tasks/create")
    task_id = _body(response)["task"]["id"]

    request = make_request("/api/qa/tasks/update", {"id": task_id, "status": "running",
                                                    "progress": 50})
    response = await _dispatch(api, request, "/api/qa/tasks/update")
    assert _body(response)["task"]["progress"] == 50

    response = await _dispatch(api, make_request(f"/api/qa/tasks/{task_id}/events"))
    events = _body(response)["events"]
    assert events[0]["kind"] == "created"
    assert any(event["kind"] == "status" for event in events)


async def test_unknown_route_falls_through(store: QaStore) -> None:
    api = QaApi(store)
    response = await _dispatch(api, make_request("/api/qa/nope"))
    assert response is None


async def test_mutation_mapping_covers_every_write_route() -> None:
    assert set(QA_MUTATION_PATHS.values()) == set(QA_WRITE_PATHS)
    assert all(path.startswith("/api/qa/") for path in QA_WRITE_PATHS)


def test_gateway_blocks_plain_http_writes() -> None:
    from nanobot.webui import ws_http

    handler = object.__new__(ws_http.GatewayHTTPHandler)
    assert handler._is_webui_mutation_path("/api/qa/cases/create") is True
    assert handler._is_webui_mutation_path("/api/qa/runs/start") is True


def test_ws_http_registers_qa_mutations() -> None:
    from nanobot.webui import ws_http

    for action, path in QA_MUTATION_PATHS.items():
        assert ws_http._WEBUI_MUTATION_PATHS[action] == path


@pytest.mark.parametrize("action", sorted(QA_MUTATION_PATHS))
def test_mutation_action_names_are_websocket_safe(action: str) -> None:
    import re

    assert re.fullmatch(r"[a-z][a-z0-9_.]{0,127}", action)
