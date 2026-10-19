"""Tests for staged API asset batches: linking, transactions, conflicts, resume."""

from __future__ import annotations

import json

import pytest

from nanobot.qa import catalog
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaConflictError, QaNotFoundError, QaValidationError

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


def test_apply_creates_a_linked_case(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(project["id"], candidates=[candidate()])
    assert workflow["status"] == "pending"
    assert workflow["candidate_count"] == 1

    applied = store.apply_api_workflow(workflow["id"])
    assert applied["status"] == "applied"
    assert applied["result"] == {"applied": 1, "updated": 0, "skipped": 0}

    case_id = applied["checkpoint"]["applied"][0]["case_id"]
    case = store.get_case(case_id)
    assert case["title"] == "create an order"
    assert case["code"] == "SHOP-API-001"
    metadata = store.get_case_metadata(case_id)
    assert metadata["scenario_key"] == "create-success"
    operation = store.list_api_operations(project["id"])["items"][0]
    assert metadata["operation_id"] == operation["id"]
    revisions = store.list_case_revisions(case_id)
    assert revisions["total"] == 1
    assert revisions["items"][0]["change_source"] == "workflow"


def test_generated_codes_are_unique_within_a_batch(
    store: QaStore, project: dict,
) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    candidates = []
    for scenario in ("create-success", "create-duplicate", "create-invalid"):
        item = candidate(scenario=scenario)
        item["case"]["title"] = f"create an order ({scenario})"
        candidates.append(item)
    workflow = store.create_api_workflow(project["id"], candidates=candidates)
    applied = store.apply_api_workflow(workflow["id"])
    codes = [entry["code"] for entry in applied["checkpoint"]["applied"]]
    assert codes == ["SHOP-API-001", "SHOP-API-002", "SHOP-API-003"]
    assert store.list_cases(project_id=project["id"])["total"] == 3


def test_reapplying_an_applied_batch_is_a_noop(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(project["id"], candidates=[candidate()])
    first = store.apply_api_workflow(workflow["id"])
    again = store.apply_api_workflow(workflow["id"])
    assert again["result"] == first["result"]
    assert store.list_cases(project_id=project["id"])["total"] == 1


def test_idempotency_key_returns_the_same_workflow(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    first = store.create_api_workflow(
        project["id"], candidates=[candidate()], idempotency_key="batch-1"
    )
    second = store.create_api_workflow(
        project["id"], candidates=[candidate()], idempotency_key="batch-1"
    )
    assert first["id"] == second["id"]
    assert store.get_api_workflow(first["id"])["candidate_count"] == 1


def test_second_batch_updates_the_same_case(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    first = store.apply_api_workflow(
        store.create_api_workflow(project["id"], candidates=[candidate()])["id"]
    )
    case_id = first["checkpoint"]["applied"][0]["case_id"]

    refined = candidate(base=1)
    refined["case"]["title"] = "create an order returns 201"
    second = store.apply_api_workflow(
        store.create_api_workflow(project["id"], candidates=[refined])["id"]
    )
    assert second["result"] == {"applied": 0, "updated": 1, "skipped": 0}
    assert store.get_case(case_id)["title"] == "create an order returns 201"
    assert store.list_case_revisions(case_id)["total"] == 2
    assert store.list_cases(project_id=project["id"])["total"] == 1


def test_stale_base_revision_fails_the_batch(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    first = store.apply_api_workflow(
        store.create_api_workflow(project["id"], candidates=[candidate()])["id"]
    )
    case_id = first["checkpoint"]["applied"][0]["case_id"]
    store.update_case(case_id, title="edited by hand")

    workflow = store.create_api_workflow(
        project["id"], candidates=[candidate(base=1)]
    )
    with pytest.raises(QaConflictError):
        store.apply_api_workflow(workflow["id"])
    failed = store.get_api_workflow(workflow["id"])
    assert failed["status"] == "failed"
    assert "revision" in failed["result"]["errors"][0]
    assert store.get_case(case_id)["title"] == "edited by hand"


def test_invalid_candidate_leaves_no_partial_batch(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    broken = candidate(scenario="create-invalid")
    broken["case"]["api"] = {"request": {"method": "FLY", "path": "/orders"}}
    workflow = store.create_api_workflow(
        project["id"], candidates=[candidate(), broken]
    )
    with pytest.raises(QaValidationError):
        store.apply_api_workflow(workflow["id"])
    assert store.list_cases(project_id=project["id"])["total"] == 0
    assert store.get_api_workflow(workflow["id"])["status"] == "failed"


def test_transaction_rolls_back_earlier_candidates(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    first = store.apply_api_workflow(
        store.create_api_workflow(project["id"], candidates=[candidate()])["id"]
    )
    case_id = first["checkpoint"]["applied"][0]["case_id"]
    store.update_case(case_id, title="edited by hand")

    new_scenario = candidate(scenario="create-secondary")
    new_scenario["case"]["title"] = "create an order twice"
    stale = candidate(base=1)
    workflow = store.create_api_workflow(
        project["id"], candidates=[new_scenario, stale]
    )
    with pytest.raises(QaConflictError):
        store.apply_api_workflow(workflow["id"])
    titles = [case["title"] for case in store.list_cases(project_id=project["id"])["items"]]
    assert titles == ["edited by hand"]


def test_unknown_operation_fails_the_batch(store: QaStore, project: dict) -> None:
    workflow = store.create_api_workflow(
        project["id"],
        candidates=[{
            "case": {"title": "call nowhere", "kind": "api"},
            "operation": {"method": "GET", "path": "/nowhere"},
            "scenario_key": "get-nowhere",
        }],
    )
    with pytest.raises(QaValidationError):
        store.apply_api_workflow(workflow["id"])
    assert store.get_api_workflow(workflow["id"])["status"] == "failed"


def test_failed_batch_can_resume_with_new_candidates(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(
        project["id"],
        candidates=[{
            "case": {"title": "call nowhere", "kind": "api"},
            "operation": {"method": "GET", "path": "/nowhere"},
            "scenario_key": "get-nowhere",
        }],
    )
    with pytest.raises(QaValidationError):
        store.apply_api_workflow(workflow["id"])

    resumed = store.replace_api_workflow_candidates(workflow["id"], [candidate()])
    assert resumed["status"] == "pending"
    applied = store.apply_api_workflow(workflow["id"])
    assert applied["status"] == "applied"
    assert store.list_cases(project_id=project["id"])["total"] == 1


def test_candidate_without_a_catalog_link_is_allowed(store: QaStore, project: dict) -> None:
    workflow = store.create_api_workflow(
        project["id"], candidates=[{"case": {"title": "manual check", "kind": "manual"}}]
    )
    applied = store.apply_api_workflow(workflow["id"])
    assert applied["result"]["applied"] == 1
    case_id = applied["checkpoint"]["applied"][0]["case_id"]
    with pytest.raises(QaNotFoundError):
        store.get_case_metadata(case_id)


def test_duplicate_candidates_are_refused(store: QaStore, project: dict) -> None:
    duplicate = json.loads(json.dumps(candidate()))
    with pytest.raises(QaValidationError):
        store.create_api_workflow(
            project["id"], candidates=[candidate(), duplicate]
        )


def test_applied_workflow_cannot_be_rewritten(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    workflow = store.create_api_workflow(project["id"], candidates=[candidate()])
    store.apply_api_workflow(workflow["id"])
    with pytest.raises(QaConflictError):
        store.replace_api_workflow_candidates(workflow["id"], [candidate()])
