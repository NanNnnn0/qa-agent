"""Tests for the MCP-facing API asset tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.qa.api_tools import (
    QaApiCatalogTool,
    QaApiRunTool,
    QaApiWorkflowTool,
    api_tools,
)
from nanobot.qa.store import QaStore

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Shop", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders",
                "responses": {"200": {}},
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Create order",
                "responses": {"201": {}},
            },
        },
        "/orders/{orderId}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Get one order",
                "parameters": [],
            },
        },
    },
}


def candidate(scenario: str = "create-success", base: int | None = None) -> dict:
    return {
        "case": {
            "title": "create an order",
            "kind": "api",
            "status": "ready",
            "api": {
                "request": {"method": "POST", "path": "/orders", "body": {"qty": 1}},
                "assertions": [{"type": "status", "expect": 201}],
            },
        },
        "operation": {"method": "POST", "path": "/orders"},
        "scenario_key": scenario,
        "evidence": [{"kind": "openapi", "ref": "#/paths/~1orders/post"}],
        "base_revision": base,
    }


async def _call(tool, **kwargs) -> dict:
    return json.loads(await tool.execute(**kwargs))


async def test_catalog_ingest_list_and_get(store: QaStore, project: dict) -> None:
    tool = QaApiCatalogTool(store)
    ingested = await _call(
        tool,
        action="ingest",
        project_id=project["id"],
        document=json.dumps(SPEC),
        source_ref="specs/orders.json",
        source_version="v1",
    )
    assert ingested["action"] == "ingest"
    assert len(ingested["added"]) == 3
    assert ingested["source"]["ref"] == "specs/orders.json"

    listing = await _call(tool, action="list", project_id=project["id"])
    assert listing["total"] == 3
    assert listing["limit"] == 10

    first = listing["items"][0]
    detail = await _call(tool, action="get", operation_id=first["id"])
    assert detail["operation"]["method"] == first["method"]
    assert detail["operation"]["spec"]
    assert detail["operation"]["evidence"]


async def test_catalog_diff_reports_without_writing(store: QaStore, project: dict) -> None:
    tool = QaApiCatalogTool(store)
    await _call(tool, action="ingest", project_id=project["id"], document=json.dumps(SPEC))
    changed = json.loads(json.dumps(SPEC))
    changed["paths"]["/orders"]["get"]["summary"] = "List every order"
    diff = await _call(
        tool, action="diff", project_id=project["id"], document=json.dumps(changed)
    )
    assert diff["unchanged"] == 2
    assert diff["changed"][0]["fields"] == ["summary"]
    listing = await _call(tool, action="list", project_id=project["id"], query="List orders")
    assert listing["total"] == 1


async def test_catalog_rejects_bad_calls(store: QaStore, project: dict) -> None:
    tool = QaApiCatalogTool(store)
    missing = await _call(tool, action="ingest", project_id=project["id"])
    assert "document or source_path" in missing["error"]
    unknown = await _call(tool, action="get", operation_id="op_missing")
    assert "not found" in unknown["error"]
    invalid = await _call(tool, action="magic", project_id=project["id"])
    assert "action must be one of" in invalid["error"]


async def test_catalog_reads_only_configured_roots(
    store: QaStore, project: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    inside = specs / "orders.json"
    inside.write_text(json.dumps(SPEC), encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(SPEC), encoding="utf-8")
    tool = QaApiCatalogTool(store)

    blocked = await _call(tool, action="ingest", project_id=project["id"], source_path=str(inside))
    assert "no reference roots" in blocked["error"]

    monkeypatch.setenv("NANOBOT_QA_SPEC_ROOTS", str(specs))
    refused = await _call(tool, action="ingest", project_id=project["id"], source_path=str(outside))
    assert "outside the allowed roots" in refused["error"]
    accepted = await _call(tool, action="ingest", project_id=project["id"], source_path=str(inside))
    assert len(accepted["added"]) == 3


async def test_workflow_create_validate_apply_export(store: QaStore, project: dict) -> None:
    await _call(
        QaApiCatalogTool(store),
        action="ingest",
        project_id=project["id"],
        document=json.dumps(SPEC),
    )
    tool = QaApiWorkflowTool(store)
    created = await _call(
        tool, action="create", project_id=project["id"], candidates=[candidate()]
    )
    workflow_id = created["workflow"]["id"]
    assert created["workflow"]["status"] == "pending"

    validated = await _call(tool, action="validate", workflow_id=workflow_id)
    assert validated["ok"] is True
    assert validated["candidates"][0]["action"] == "create"

    applied = await _call(tool, action="apply", workflow_id=workflow_id)
    assert applied["workflow"]["status"] == "applied"
    assert applied["workflow"]["result"] == {"applied": 1, "updated": 0, "skipped": 0}

    again = await _call(tool, action="validate", workflow_id=workflow_id)
    assert again["candidates"][0]["action"] == "update"

    exported = await _call(tool, action="export", workflow_id=workflow_id)
    assert exported["format"] == "qa-agent.api-workflow.v1"
    assert exported["cases"][0]["snapshot"]["title"] == "create an order"
    assert exported["cases"][0]["revision"] == 1


async def test_workflow_idempotency_key(store: QaStore, project: dict) -> None:
    tool = QaApiWorkflowTool(store)
    first = await _call(
        tool, action="create", project_id=project["id"], candidates=[candidate()],
        idempotency_key="batch-1",
    )
    second = await _call(
        tool, action="create", project_id=project["id"], candidates=[candidate()],
        idempotency_key="batch-1",
    )
    assert first["workflow"]["id"] == second["workflow"]["id"]


async def test_workflow_failure_resume_and_submit(store: QaStore, project: dict) -> None:
    await _call(
        QaApiCatalogTool(store),
        action="ingest",
        project_id=project["id"],
        document=json.dumps(SPEC),
    )
    tool = QaApiWorkflowTool(store)
    broken = candidate()
    broken["operation"] = {"method": "GET", "path": "/nowhere"}
    broken["scenario_key"] = "get-nowhere"
    created = await _call(
        tool, action="create", project_id=project["id"], candidates=[broken]
    )
    workflow_id = created["workflow"]["id"]

    failed = await _call(tool, action="apply", workflow_id=workflow_id)
    assert "not in this project's catalog" in failed["error"]

    resumed = await _call(tool, action="resume", workflow_id=workflow_id)
    assert resumed["status"] == "failed"
    assert resumed["next_action"] == "submit"
    assert resumed["errors"]

    submitted = await _call(
        tool, action="submit", workflow_id=workflow_id, candidates=[candidate()]
    )
    assert submitted["workflow"]["status"] == "pending"
    applied = await _call(tool, action="apply", workflow_id=workflow_id)
    assert applied["workflow"]["status"] == "applied"


async def test_workflow_requires_ids(store: QaStore, project: dict) -> None:
    tool = QaApiWorkflowTool(store)
    no_project = await _call(tool, action="create", candidates=[candidate()])
    assert "project_id is required" in no_project["error"]
    no_workflow = await _call(tool, action="apply")
    assert "workflow_id is required" in no_workflow["error"]


async def test_run_tool_preflight_start_and_get(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    store.create_case(
        project["id"],
        title="product list",
        kind="api",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    tool = QaApiRunTool(store)
    checked = await _call(tool, action="preflight", project_id=project["id"])
    assert checked["ok"] is True
    assert checked["ready_count"] == 1
    assert checked["blockers"] == []

    started = await _call(
        tool, action="start", project_id=project["id"], name="smoke", wait=True,
    )
    assert started["run"]["status"] == "passed"
    assert started["run"]["template_version"] == "1"
    fetched = await _call(tool, action="get", run_id=started["run"]["id"])
    assert fetched["run"]["id"] == started["run"]["id"]
    assert fetched["run"]["failed_tests"] == []


async def test_run_tool_starts_in_background(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    store.create_case(
        project["id"],
        title="product list",
        kind="api",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    tool = QaApiRunTool(store)
    started = await _call(tool, action="start", project_id=project["id"])
    assert started["run"]["status"] == "running"
    settled = await _call(
        tool, action="get", run_id=started["run"]["id"], wait=True, timeout_s=60,
    )
    assert settled["run"]["status"] == "passed"


async def test_run_tool_reports_blockers(store: QaStore, project: dict) -> None:
    store.create_case(
        project["id"],
        title="draft case",
        kind="api",
        status="draft",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    tool = QaApiRunTool(store)
    checked = await _call(tool, action="preflight", project_id=project["id"])
    assert checked["ok"] is False
    assert checked["blocked_count"] == 1
    assert checked["blocked"][0]["reasons"] == [
        "status is 'draft', only ready cases execute",
    ]
    started = await _call(tool, action="start", project_id=project["id"])
    assert "cannot run" in started["error"]
    missing = await _call(tool, action="get")
    assert "run_id is required" in missing["error"]


def test_tool_schemas_are_provider_ready() -> None:
    tools = api_tools()
    assert [tool.name for tool in tools] == [
        "qa_api_catalog",
        "qa_api_workflow",
        "qa_api_run",
    ]
    for tool in tools:
        schema = tool.to_schema()
        function = schema["function"]
        assert function["name"] == tool.name
        assert function["parameters"]["additionalProperties"] is False
        assert function["parameters"]["required"] == ["action"]
        assert function["parameters"]["properties"]["action"]["enum"]
        json.dumps(schema)
