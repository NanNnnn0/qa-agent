"""Tests for ordered run plans: setup, cases, cleanup, revisions and skip rules."""

from __future__ import annotations

import json

import pytest

from nanobot.qa.api_tools import QaApiRunTool
from nanobot.qa.execution import execute_pinned, normalize_plan, preflight
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError


def make_case(
    store: QaStore,
    project: dict,
    *,
    title: str,
    method: str = "GET",
    path: str = "/api/products",
    body: dict | None = None,
    assertions: list[dict] | None = None,
    extract: dict | None = None,
) -> dict:
    request: dict = {"method": method, "path": path}
    if body is not None:
        request["body"] = body
    api: dict = {
        "request": request,
        "assertions": assertions
        if assertions is not None
        else [{"type": "status", "expect": 200}],
    }
    if extract:
        api["extract"] = extract
    return store.create_case(
        project["id"], title=title, kind="api", status="ready", api=api,
    )


def plan(*, setup=(), cases=(), cleanup=()) -> dict:
    def steps(case_ids):
        return [{"case_id": case_id} for case_id in case_ids]

    return {
        "version": "1",
        "setup": steps(setup),
        "cases": steps(cases),
        "cleanup": steps(cleanup),
    }


def test_plan_runs_setup_cases_and_cleanup(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    setup = make_case(
        store,
        project,
        title="create an order",
        method="POST",
        path="/api/orders",
        body={"sku": "A-1", "qty": 1},
        assertions=[{"type": "status", "expect": 201}],
        extract={"order_id": "$.data.orderId"},
    )
    check = make_case(
        store,
        project,
        title="read the created order",
        path="/api/orders/{{run.order_id}}",
        assertions=[
            {"type": "status", "expect": 200},
            {"type": "json_path", "path": "$.data.status", "op": "equals", "expect": "CREATED"},
        ],
    )
    cleanup = make_case(
        store,
        project,
        title="cancel the created order",
        method="DELETE",
        path="/api/orders/{{run.order_id}}",
        assertions=[
            {"type": "status", "expect": 200},
            {"type": "json_path", "path": "$.data.status", "op": "equals", "expect": "CANCELLED"},
        ],
    )
    run = execute_pinned(
        store,
        project["id"],
        plan=plan(setup=[setup["id"]], cases=[check["id"]], cleanup=[cleanup["id"]]),
    )
    report = store.get_run(run["id"])["report"]
    assert run["status"] == "passed", report["tests"]
    assert report["summary"]["phases"] == {
        "setup": {"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "error": 0},
        "cases": {"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "error": 0},
        "cleanup": {"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "error": 0},
    }
    assert [test["phase"] for test in report["tests"]] == ["setup", "cases", "cleanup"]
    assert report["snapshot"]["plan"]["phases"]["cleanup"] == [
        {"case_id": cleanup["id"], "revision": 1},
    ]
    assert report["plan_version"] == "1"


def test_setup_failure_skips_cases_but_runs_cleanup(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    broken_setup = make_case(
        store,
        project,
        title="setup that fails",
        assertions=[{"type": "status", "expect": 500}],
    )
    check = make_case(store, project, title="case that would pass")
    cleanup = make_case(store, project, title="cleanup that still runs")
    run = execute_pinned(
        store,
        project["id"],
        plan=plan(setup=[broken_setup["id"]], cases=[check["id"]], cleanup=[cleanup["id"]]),
    )
    report = store.get_run(run["id"])["report"]
    assert run["status"] == "failed"
    phases = {test["phase"]: test for test in report["tests"]}
    assert phases["setup"]["status"] == "failed"
    assert phases["setup"]["classification"] == "assertion_failed"
    assert phases["cases"]["status"] == "skipped"
    assert phases["cases"]["classification"] == "dependency_blocked"
    assert phases["cleanup"]["status"] == "passed"


def test_cleanup_failure_is_classified(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    check = make_case(store, project, title="case that passes")
    cleanup = make_case(
        store,
        project,
        title="cleanup that fails",
        assertions=[{"type": "status", "expect": 500}],
    )
    run = execute_pinned(
        store, project["id"], plan=plan(cases=[check["id"]], cleanup=[cleanup["id"]]),
    )
    report = store.get_run(run["id"])["report"]
    assert run["status"] == "failed"
    cleanup_test = next(test for test in report["tests"] if test["phase"] == "cleanup")
    assert cleanup_test["classification"] == "cleanup_failed"


def test_pinned_revision_must_match_the_case(store: QaStore, project: dict) -> None:
    case = make_case(store, project, title="product list")
    store.update_case(case["id"], title="product list v2")
    pinned = {"version": "1", "setup": [], "cases": [
        {"case_id": case["id"], "revision": 1},
    ], "cleanup": []}
    checked = preflight(store, project["id"], plan=pinned)
    assert checked["blocked"][0]["reasons"] == [
        "plan pins revision 1 but the case is at revision 2; "
        "re-validate the plan against the current case",
    ]
    with pytest.raises(QaValidationError):
        execute_pinned(store, project["id"], plan=pinned)


def test_plan_structure_is_validated() -> None:
    with pytest.raises(QaValidationError):
        normalize_plan({"cases": []})
    with pytest.raises(QaValidationError):
        normalize_plan({"cases": [{"case_id": "case_1", "extra": 1}]})
    with pytest.raises(QaValidationError):
        normalize_plan({"cases": [{"case_id": "case_1"}, {"case_id": "case_1"}]})
    with pytest.raises(QaValidationError):
        normalize_plan({"cases": [{"case_id": "case_1"}], "unknown": []})
    with pytest.raises(QaValidationError):
        normalize_plan({"cases": [{"case_id": "case_1", "revision": 0}]})


def test_plan_and_case_ids_are_exclusive(store: QaStore, project: dict) -> None:
    case = make_case(store, project, title="product list")
    with pytest.raises(QaValidationError):
        preflight(
            store,
            project["id"],
            case_ids=[case["id"]],
            plan=plan(cases=[case["id"]]),
        )


def test_plan_rejects_a_case_from_another_project(
    store: QaStore, project: dict,
) -> None:
    other = store.create_project(key="crm", name="CRM")
    case = make_case(store, other, title="foreign case")
    with pytest.raises(QaValidationError):
        preflight(store, project["id"], plan=plan(cases=[case["id"]]))


async def test_run_tool_accepts_a_plan(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    setup = make_case(
        store,
        project,
        title="create an order",
        method="POST",
        path="/api/orders",
        body={"sku": "A-1", "qty": 1},
        assertions=[{"type": "status", "expect": 201}],
        extract={"order_id": "$.data.orderId"},
    )
    cleanup = make_case(
        store,
        project,
        title="cancel the created order",
        method="DELETE",
        path="/api/orders/{{run.order_id}}",
    )
    tool = QaApiRunTool(store)
    checked = json.loads(await tool.execute(
        action="preflight", project_id=project["id"],
        plan=plan(setup=[setup["id"]], cleanup=[cleanup["id"]]),
    ))
    assert checked["ok"] is True
    assert checked["phases"] == {"setup": 1, "cases": 0, "cleanup": 1}

    started = json.loads(await tool.execute(
        action="start", project_id=project["id"],
        plan=plan(setup=[setup["id"]], cleanup=[cleanup["id"]]),
    ))
    assert started["run"]["status"] == "passed"
    assert started["run"]["plan_version"] == "1"
    assert started["run"]["summary"]["phases"]["cleanup"]["passed"] == 1
