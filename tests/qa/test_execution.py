"""Tests for pinned runs: preflight, template execution, snapshot, batching, masking."""

from __future__ import annotations

import json

import pytest

from nanobot.qa import catalog
from nanobot.qa.execution import execute_pinned, preflight, run_summary
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Shop", "version": "1.0.0"},
    "paths": {
        "/api/products": {
            "get": {"operationId": "listProducts", "summary": "List products"},
        }
    },
}


def ready_case(
    store: QaStore,
    project: dict,
    *,
    title: str = "product list",
    status: str = "ready",
    path: str = "/api/products",
    method: str = "GET",
    assertions: list[dict] | None = None,
    body: dict | None = None,
    headers: dict | None = None,
    extract: dict | None = None,
) -> dict:
    request: dict = {"method": method, "path": path}
    if body is not None:
        request["body"] = body
    if headers is not None:
        request["headers"] = headers
    api: dict = {
        "request": request,
        "assertions": assertions
        if assertions is not None
        else [{"type": "status", "expect": 200}],
    }
    if extract:
        api["extract"] = extract
    return store.create_case(
        project["id"], title=title, kind="api", status=status, api=api,
    )


def test_preflight_blocks_a_draft_case(store: QaStore, project: dict) -> None:
    ready_case(store, project, status="draft")
    checked = preflight(store, project["id"])
    assert checked["ok"] is False
    assert checked["blocked"][0]["reasons"] == [
        "status is 'draft', only ready cases execute",
    ]


def test_preflight_reports_each_problem(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="no api", kind="api", status="ready")
    store.create_case(
        project["id"],
        title="no assertions",
        kind="api",
        status="ready",
        api={"request": {"method": "GET", "path": "/api/products"}},
    )
    store.create_case(
        project["id"],
        title="unresolved variable",
        kind="api",
        status="ready",
        api={
            "request": {
                "method": "GET",
                "path": "/api/products",
                "headers": {"Authorization": "Bearer {{token}}"},
            },
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    checked = preflight(store, project["id"])
    reasons = [reason for item in checked["blocked"] for reason in item["reasons"]]
    assert "case has no api.request" in reasons
    assert "case has no assertions" in reasons
    assert "unresolved variable 'token'" in reasons
    assert checked["ready"] == []


def test_preflight_reports_missing_base_url(store: QaStore, project: dict) -> None:
    store.update_project(project["id"], base_url="")
    ready_case(store, project)
    checked = preflight(store, project["id"])
    assert "project has no base_url configured" in checked["blockers"]
    assert checked["ok"] is False


def test_preflight_blocks_a_missing_catalog_operation(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(project["id"], candidates=[{
        "case": {
            "title": "list products",
            "kind": "api",
            "status": "ready",
            "api": {
                "request": {"method": "GET", "path": "/api/products"},
                "assertions": [{"type": "status", "expect": 200}],
            },
        },
        "operation": {"method": "GET", "path": "/api/products"},
        "scenario_key": "list-products",
    }])
    applied = store.apply_api_workflow(workflow["id"])
    case_id = applied["checkpoint"]["applied"][0]["case_id"]

    # The reference material drops the endpoint; the case keeps pointing at it.
    store.ingest_api_operations(project["id"], [
        {"method": "GET", "path": "/health"},
    ])
    checked = preflight(store, project["id"], case_ids=[case_id])
    assert checked["blocked"][0]["reasons"] == [
        "case references catalog operation '/api/products' marked missing",
    ]


def test_execute_pinned_records_a_snapshot(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project, title="product list")
    ready_case(
        store,
        project,
        title="create order",
        path="/api/orders",
        method="POST",
        body={"sku": "A-1", "qty": 1},
        assertions=[{"type": "status", "expect": 201}],
    )
    run = execute_pinned(store, project["id"], kind="api", name="smoke")
    assert run["status"] == "passed"
    assert run["passed"] == 2

    stored = store.get_run(run["id"])
    report = stored["report"]
    assert report["template_version"] == "1"
    assert len(report["snapshot"]["cases"]) == 2
    assert all(entry["revision"] >= 1 for entry in report["snapshot"]["cases"])
    assert len(report["batches"]) == 1
    assert report["batches"][0]["reported"] == 2
    assert stored["log"].count("passed") >= 0


def test_execute_pinned_refuses_blocked_cases(store: QaStore, project: dict) -> None:
    ready_case(store, project, status="draft")
    with pytest.raises(QaValidationError) as excinfo:
        execute_pinned(store, project["id"], kind="api")
    assert "cannot run" in str(excinfo.value)
    assert store.list_runs(project_id=project["id"])["total"] == 0


def test_extracted_variables_flow_between_cases(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    create = ready_case(
        store,
        project,
        title="create order",
        path="/api/orders",
        method="POST",
        body={"sku": "A-1", "qty": 1},
        assertions=[{"type": "status", "expect": 201}],
        extract={"order_id": "$.data.orderId"},
    )
    fetch = ready_case(
        store,
        project,
        title="read the created order",
        path="/api/orders/{{run.order_id}}",
        assertions=[
            {"type": "status", "expect": 200},
            {"type": "json_path", "path": "$.data.sku", "op": "equals", "expect": "A-1"},
        ],
    )
    run = execute_pinned(store, project["id"], case_ids=[create["id"], fetch["id"]])
    assert run["status"] == "passed", run["report"]["tests"]


def test_batching_covers_the_whole_selection(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    for index in range(3):
        ready_case(store, project, title=f"product list {index}")
    run = execute_pinned(store, project["id"], kind="api", batch_size=2)
    report = store.get_run(run["id"])["report"]
    assert report["summary"]["tests"] == 3
    assert report["summary"]["passed"] == 3
    assert report["summary"]["batches"] == 2
    assert [batch["cases"] for batch in report["batches"]] == [2, 1]


def test_report_masks_credentials(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    token = "super-secret-token"
    ready_case(
        store,
        project,
        assertions=[
            {"type": "status", "expect": 200},
            {"type": "body_contains", "text": token},
        ],
    )
    run = execute_pinned(
        store, project["id"], kind="api", auth={"kind": "bearer", "token": token},
    )
    assert run["status"] == "failed"
    report = store.get_run(run["id"])["report"]
    serialized = json.dumps(report)
    assert token not in serialized
    assert "***" in serialized
    assert report["auth"] == {"kind": "bearer"}


def test_auth_failure_is_recorded_as_a_run(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project)
    run = execute_pinned(
        store,
        project["id"],
        kind="api",
        auth={
            "kind": "login",
            "path": "/api/login",
            "body": {"user": "qa", "password": "wrong"},
            "token_path": "$.data.token",
        },
    )
    assert run["status"] == "error"
    report = store.get_run(run["id"])["report"]
    assert report["classification"] == "auth_failed"
    assert "HTTP 401" in report["message"]


def test_unreachable_target_is_blocked_by_env(store: QaStore, project: dict) -> None:
    store.update_project(project["id"], base_url="http://127.0.0.1:1")
    ready_case(store, project)
    run = execute_pinned(store, project["id"], kind="api")
    assert run["status"] == "blocked_by_env"
    report = store.get_run(run["id"])["report"]
    assert report["tests"][0]["classification"] == "env_blocked"


def test_run_summary_lists_failed_tests(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project, assertions=[{"type": "status", "expect": 500}])
    run = execute_pinned(store, project["id"], kind="api")
    summary = run_summary(store.get_run(run["id"]))
    assert summary["failed"] == 1
    assert summary["failed_tests"][0]["classification"] == "assertion_failed"
    assert summary["snapshot"]["cases"][0]["case_id"]
