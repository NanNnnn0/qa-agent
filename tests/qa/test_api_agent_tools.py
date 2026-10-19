"""The API asset workflow must be callable from the agent runtime.

The skill teaches ``qa_api_catalog`` -> ``qa_api_workflow`` -> ``qa_api_run``.
These tests pin the other half of that contract: the tools are discovered by
``ToolLoader``, so the chat agent and dispatched subagents actually have them.
"""

from __future__ import annotations

import json

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.qa_api import (
    QaApiCatalogTool,
    QaApiRunTool,
    QaApiWorkflowTool,
)
from nanobot.qa import catalog
from nanobot.qa.chat_context import (
    QA_PROJECT_METADATA_KEY,
    qa_project_context,
)
from nanobot.qa.store import QaStore

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Shop", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "summary": "Create order",
                "responses": {"201": {}},
            }
        }
    },
}


def candidate() -> dict:
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
        "scenario_key": "create-success",
        "evidence": [{"kind": "openapi", "ref": "#/paths/~1orders/post"}],
    }


def bound_context(project: dict) -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="chat-1",
        metadata={
            QA_PROJECT_METADATA_KEY: {
                "id": project["id"],
                "key": project["key"],
                "name": project["name"],
            }
        },
    )


def test_tool_loader_discovers_the_api_asset_tools() -> None:
    names = {cls.__name__ for cls in ToolLoader().discover()}
    assert {"QaApiCatalogTool", "QaApiWorkflowTool", "QaApiRunTool"} <= names


def test_api_asset_tools_stay_out_of_the_subagent_scope() -> None:
    """The subagent prompt budget leaves no room for these three schemas."""
    for tool_cls in (QaApiCatalogTool, QaApiWorkflowTool, QaApiRunTool):
        assert tool_cls._scopes == {"core"}


def test_api_asset_tools_expose_agent_schemas() -> None:
    expected = {"qa_api_catalog", "qa_api_workflow", "qa_api_run"}
    tools = (QaApiCatalogTool(), QaApiWorkflowTool(), QaApiRunTool())
    assert {tool.name for tool in tools} == expected
    for tool in tools:
        schema = tool.to_schema()["function"]
        assert schema["name"] == tool.name
        assert schema["parameters"]["type"] == "object"
        assert "action" in schema["parameters"]["properties"]
        assert "bound" in schema["description"]


async def test_catalog_list_uses_the_bound_project(
    store: QaStore, project: dict,
) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    other = store.create_project(key="other", name="Other")
    store.ingest_api_operations(other["id"], catalog.parse_openapi(SPEC))

    with request_context(bound_context(project)):
        payload = json.loads(await QaApiCatalogTool(store).execute(action="list"))

    assert payload["total"] == 1
    assert payload["items"][0]["project_id"] == project["id"]


async def test_unbound_catalog_call_reports_the_missing_project(store: QaStore) -> None:
    unbound = RequestContext(channel="websocket", chat_id="chat-1")
    with request_context(unbound):
        payload = json.loads(
            await QaApiCatalogTool(store).execute(action="diff", document=json.dumps(SPEC))
        )
    assert "project_id" in payload["error"]


async def test_agent_can_stage_validate_and_apply_a_case_batch(
    store: QaStore, project: dict,
) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    tool = QaApiWorkflowTool(store)

    with request_context(bound_context(project)):
        created = json.loads(
            await tool.execute(
                action="create",
                candidates=[candidate()],
                idempotency_key="agent-batch-1",
            )
        )
        workflow_id = created["workflow"]["id"]
        checked = json.loads(await tool.execute(action="validate", workflow_id=workflow_id))
        applied = json.loads(await tool.execute(action="apply", workflow_id=workflow_id))

    assert checked["action"] == "validate"
    assert applied["workflow"]["status"] == "applied"
    assert applied["workflow"]["result"]["applied"] == 1
    cases = store.list_cases(project_id=project["id"])["items"]
    assert [case["code"] for case in cases] == ["SHOP-API-001"]
    assert store.get_case_metadata(cases[0]["id"])["scenario_key"] == "create-success"
    assert store.list_case_revisions(cases[0]["id"])["total"] == 1


async def test_agent_can_preflight_a_bound_project(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(project["id"], candidates=[candidate()])
    store.apply_api_workflow(workflow["id"])

    with request_context(bound_context(project)):
        payload = json.loads(await QaApiRunTool(store).execute(action="preflight"))

    assert payload["ok"] is True
    assert payload["ready_count"] == 1
    assert payload["blocked_count"] == 0


async def test_bound_context_names_the_api_workflow(project: dict) -> None:
    block = await qa_project_context(bound_context(project))
    assert block is not None
    assert "qa_api_workflow" in block.content
    assert "qa_case" in block.content
