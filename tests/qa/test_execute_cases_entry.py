"""The qa_run entry point now runs through the pinned pipeline."""

from __future__ import annotations

import pytest

from nanobot.qa import service
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError


def ready_case(
    store: QaStore, project: dict, *, title: str = "product list", status: str = "ready",
) -> dict:
    return store.create_case(
        project["id"],
        title=title,
        kind="api",
        status=status,
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )


def test_execute_cases_refuses_unready_cases(store: QaStore, project: dict) -> None:
    case = ready_case(store, project, status="draft")
    with pytest.raises(QaValidationError) as excinfo:
        service.execute_cases(store, project["id"], kind="api")
    message = str(excinfo.value)
    assert case["code"] in message
    assert "status is 'draft'" in message
    assert store.list_runs(project_id=project["id"])["total"] == 0


def test_execute_cases_records_a_snapshot(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    case = ready_case(store, project)
    run = service.execute_cases(store, project["id"], kind="api")
    assert run["status"] == "passed"
    report = store.get_run(run["id"])["report"]
    assert report["template_version"] == "1"
    snapshot = report["snapshot"]["cases"][0]
    assert snapshot["case_id"] == case["id"]
    assert snapshot["revision"] == 1


def test_execute_cases_attaches_the_task_artifact(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project)
    task = store.create_task(title="run api", role="api", project_id=project["id"])
    run = service.execute_cases(store, project["id"], kind="api", task_id=task["id"])
    artifacts = store.get_task(task["id"])["artifacts"]
    assert [item["ref_id"] for item in artifacts] == [run["id"]]


def test_execute_cases_keeps_the_trigger(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project)
    run = service.execute_cases(store, project["id"], kind="api", trigger="schedule")
    assert run["trigger"] == "schedule"
    assert run["status"] == "passed"
