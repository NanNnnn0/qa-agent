"""Tests for the QA SQLite store."""

from __future__ import annotations

import pytest

from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaConflictError, QaNotFoundError, QaValidationError


def test_project_lifecycle_and_duplicate_key(store: QaStore) -> None:
    project = store.create_project(key="mall", name="Mall")
    assert project["key"] == "MALL"
    with pytest.raises(QaConflictError):
        store.create_project(key="MALL", name="Other")

    updated = store.update_project(project["id"], name="Mall 2", base_url="http://x")
    assert updated["name"] == "Mall 2"
    assert updated["base_url"] == "http://x"
    assert store.get_project_by_key("mall")["id"] == project["id"]

    store.delete_project(project["id"])
    with pytest.raises(QaNotFoundError):
        store.get_project(project["id"])


def test_case_codes_are_generated_and_unique(store: QaStore, project: dict) -> None:
    first = store.create_case(project["id"], title="list products", kind="api")
    second = store.create_case(project["id"], title="create order", kind="api")
    ui = store.create_case(project["id"], title="cart flow", kind="ui")
    assert first["code"] == "SHOP-API-001"
    assert second["code"] == "SHOP-API-002"
    assert ui["code"] == "SHOP-UI-001"

    with pytest.raises(QaConflictError):
        store.create_case(project["id"], title="dup", kind="api", code="SHOP-API-001")


def test_case_validation_rejects_bad_shapes(store: QaStore, project: dict) -> None:
    with pytest.raises(QaValidationError):
        store.create_case(project["id"], title="bad kind", kind="smoke")
    with pytest.raises(QaValidationError):
        store.create_case(
            project["id"],
            title="bad api",
            api={"request": {"method": "FLY", "path": "/x"}},
        )
    with pytest.raises(QaValidationError):
        store.create_case(
            project["id"],
            title="bad assertion",
            api={
                "request": {"method": "GET", "path": "/x"},
                "assertions": [{"type": "magic"}],
            },
        )


def test_case_api_spec_is_normalized(store: QaStore, project: dict) -> None:
    case = store.create_case(
        project["id"],
        title="order",
        api={
            "request": {"method": "post", "path": "/api/orders", "body": {"qty": 1}},
            "assertions": [
                {"type": "status", "expect": 201},
                {"type": "json_path", "path": "$.data.id", "op": "exists"},
            ],
        },
    )
    assert case["api"]["request"]["method"] == "POST"
    assert case["api"]["assertions"][0]["expect"] == 201
    assert case["api"]["request"]["headers"] == {}


def test_list_cases_filters_and_pagination(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="api one", kind="api", priority="P0")
    store.create_case(project["id"], title="api two", kind="api", status="ready")
    store.create_case(project["id"], title="ui one", kind="ui")
    assert store.list_cases(project_id=project["id"])["total"] == 3
    assert store.list_cases(project_id=project["id"], kind="api")["total"] == 2
    assert store.list_cases(project_id=project["id"], status="ready")["total"] == 1
    assert store.list_cases(query="ui one")["total"] == 1
    page = store.list_cases(project_id=project["id"], limit=2, offset=2)
    assert len(page["items"]) == 1


def test_import_export_round_trip(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="api one", kind="api")
    exported = store.export_cases(project["id"])
    assert exported["format"] == "qa-agent.cases.v1"
    assert exported["project"]["key"] == "SHOP"

    other = store.create_project(key="crm", name="CRM")
    result = store.import_cases(other["id"], {"cases": exported["cases"]})
    assert len(result["created"]) == 1
    assert result["created"][0]["code"] == "SHOP-API-001"
    # Importing the same payload again is skipped, not duplicated.
    again = store.import_cases(other["id"], {"cases": exported["cases"]})
    assert again["created"] == []
    assert again["skipped"]


def test_export_is_complete_beyond_the_page_cap(store: QaStore, project: dict) -> None:
    for index in range(510):
        store.create_case(project["id"], title=f"case {index:03d}", kind="api")
    exported = store.export_cases(project["id"])
    assert exported["total"] == 510
    assert len(exported["cases"]) == 510
    # The paged listing keeps its own cap; only the export is complete.
    assert len(store.list_cases(project_id=project["id"], limit=500)["items"]) == 500
    assert store.list_cases(project_id=project["id"], limit=500)["total"] == 510


def test_scripts_crud(store: QaStore, project: dict) -> None:
    script = store.create_script(
        project["id"], name="smoke", content="print('x')", file_path="tests/test_x.py",
        case_ids=["case_a", "case_a"],
    )
    assert script["case_ids"] == ["case_a"]
    listing = store.list_scripts(project_id=project["id"])["items"]
    assert "content" not in listing[0]
    assert listing[0]["content_lines"] == 1
    detail = store.get_script(script["id"])
    assert detail["content"] == "print('x')"

    store.update_script(script["id"], status="ready")
    assert store.get_script(script["id"])["status"] == "ready"
    store.delete_script(script["id"])
    with pytest.raises(QaNotFoundError):
        store.get_script(script["id"])


def test_task_progress_result_and_events(store: QaStore, project: dict) -> None:
    task = store.create_task(title="run api", role="api", project_id=project["id"])
    assert task["status"] == "queued"
    assert task["children"] == []
    events = store.list_events(task["id"])
    assert events[0]["kind"] == "created"

    store.update_task(task["id"], status="running", progress=40)
    done = store.update_task(task["id"], status="done", result="ok")
    assert done["progress"] == 100
    assert done["result"] == "ok"
    assert [event["kind"] for event in store.list_events(task["id"])] == [
        "created", "status", "status",
    ]

    store.add_artifact(task["id"], kind="case", ref_id="case_1", title="one")
    fetched = store.get_task(task["id"])
    assert fetched["artifacts"] == [
        {"kind": "case", "ref_id": "case_1", "title": "one"},
    ]


def test_plan_children_inherit_project(store: QaStore, project: dict) -> None:
    parent = store.create_task(title="regression", project_id=project["id"], role="orchestrator")
    child = store.create_task(title="api part", parent_id=parent["id"], role="api")
    assert child["project_id"] == project["id"]
    assert store.get_task(parent["id"])["children"][0]["id"] == child["id"]


def test_overview_counts(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="one", kind="api", status="ready")
    store.create_script(project["id"], name="s", content="")
    store.create_task(title="t", project_id=project["id"], role="api")
    counts = store.overview()["counts"]
    assert counts["projects"] == 1
    assert counts["cases"] == 1
    assert counts["ready_cases"] == 1
    assert counts["scripts"] == 1
    assert counts["active_tasks"] == 1


def test_trace_edges_replace_and_reverse_lookup(store: QaStore, project: dict) -> None:
    store.replace_trace_edges(
        project["id"],
        "case",
        "TC-SHOP-001",
        [("testpoint", "TP-SHOP-001"), ("source", "REQ-SHOP-01")],
    )
    # Replacing the same source node removes the edge that is no longer declared.
    assert store.replace_trace_edges(
        project["id"], "case", "TC-SHOP-001", [("testpoint", "TP-SHOP-001")]
    ) == 1
    assert store.list_trace_edges(project["id"]) == [
        {
            "from_type": "case",
            "from_id": "TC-SHOP-001",
            "to_type": "testpoint",
            "to_id": "TP-SHOP-001",
        }
    ]
    assert store.get_dependents(project["id"], "testpoint", "TP-SHOP-001") == [
        {"from_type": "case", "from_id": "TC-SHOP-001"}
    ]
    assert store.get_dependents(project["id"], "source", "REQ-SHOP-01") == []


def test_case_trace_summary_upsert_and_stale(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="one", kind="api")
    summary = store.upsert_case_trace_summary({
        "case_id": case["id"],
        "needs_links": False,
        "needs_recheck": True,
        "trace_status": "reviewed",
        "recheck_reasons": ["content_changed"],
        "testpoint_count": 2,
        "source_count": 3,
        "input_hash": "abc",
        "state": "fresh",
    })
    assert summary["needs_links"] is False
    assert summary["needs_recheck"] is True
    assert summary["recheck_reasons"] == ["content_changed"]
    assert summary["testpoint_count"] == 2
    assert summary["source_count"] == 3

    updated = store.upsert_case_trace_summary({
        "case_id": case["id"],
        "needs_links": True,
        "state": "stale",
    })
    assert updated["needs_links"] is True
    assert updated["needs_recheck"] is False
    assert updated["state"] == "stale"

    assert store.mark_case_trace_stale([case["id"]]) == 0  # already stale
    store.upsert_case_trace_summary({"case_id": case["id"], "state": "fresh"})
    assert store.mark_case_trace_stale([case["id"]]) == 1
    assert store.get_case_trace_summary(case["id"])["state"] == "stale"


def test_replace_trace_index_is_idempotent(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="one", kind="api")
    payload = {
        "edges": [("case", case["id"], "testpoint", "TP-SHOP-001")],
        "summaries": [{
            "case_id": case["id"],
            "needs_links": False,
            "testpoint_count": 1,
            "source_count": 1,
            "input_hash": "hash",
            "state": "fresh",
        }],
        "files": [{
            "path": "cases/TC-SHOP-001.yaml",
            "entity_type": "case",
            "entity_id": case["id"],
            "content_hash": "filehash",
            "mtime_ns": 1,
        }],
    }
    first = store.replace_trace_index(project["id"], **payload)
    second = store.replace_trace_index(project["id"], **payload)
    assert first == second == {"edges": 1, "summaries": 1, "files": 1}
    assert store.trace_index_stats(project["id"]) == {
        "edges": 1,
        "summaries": 1,
        "files": 1,
        "stale": 0,
        "needs_recheck": 0,
    }
    assert store.get_trace_file_state(project["id"], "cases/TC-SHOP-001.yaml")[
        "content_hash"
    ] == "filehash"
