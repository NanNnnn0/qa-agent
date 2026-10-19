"""Tests for the API reference catalog: parsing, identity, diffs and storage."""

from __future__ import annotations

import json

import pytest

from nanobot.qa import catalog
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError

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


def test_parse_openapi_normalizes_identity() -> None:
    operations = catalog.parse_openapi(
        SPEC, source={"kind": "spec", "ref": "specs/orders.json", "version": "v1"}
    )
    assert [(item["method"], item["path"]) for item in operations] == [
        ("GET", "/orders"),
        ("POST", "/orders"),
        ("GET", "/orders/{}"),
    ]
    pointer = operations[2]["evidence"][-1]
    assert pointer["ref"] == "#/paths/~1orders~1{orderId}/get"
    assert pointer["kind"] == "openapi"


def test_path_parameter_names_share_one_identity() -> None:
    first = catalog.parse_openapi({"openapi": "3.1.0", "paths": {"/orders/{id}": {"get": {}}}})
    second = catalog.parse_openapi(
        {"openapi": "3.1.0", "paths": {"/orders/{orderId}/": {"get": {}}}}
    )
    assert first[0]["path"] == second[0]["path"] == "/orders/{}"


def test_json_and_yaml_documents_hash_the_same() -> None:
    as_json = json.dumps(
        {"openapi": "3.0.3", "paths": {"/ping": {"get": {"operationId": "ping"}}}}
    )
    as_yaml = "openapi: 3.0.3\npaths:\n  /ping:\n    get:\n      operationId: ping\n"
    from_json = catalog.parse_openapi(as_json)
    from_yaml = catalog.parse_openapi(as_yaml)
    assert catalog.operation_hash(from_json[0]) == catalog.operation_hash(from_yaml[0])


def test_invalid_documents_are_rejected() -> None:
    with pytest.raises(QaValidationError):
        catalog.parse_openapi({"swagger": "2.0", "paths": {}})
    with pytest.raises(QaValidationError):
        catalog.parse_openapi({"openapi": "3.0.3", "paths": {}})
    with pytest.raises(QaValidationError):
        catalog.parse_openapi({"openapi": "3.0.3"})


def test_local_reference_must_stay_inside_the_roots(tmp_path) -> None:
    root = tmp_path / "specs"
    root.mkdir()
    inside = root / "orders.json"
    inside.write_text(json.dumps(SPEC), encoding="utf-8")
    text, source = catalog.read_local_source(str(inside), allowed_roots=[str(root)])
    assert source["kind"] == "spec"
    assert json.loads(text)["openapi"] == "3.0.3"

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(QaValidationError):
        catalog.read_local_source(str(outside), allowed_roots=[str(root)])


def test_ingest_is_idempotent(store: QaStore, project: dict) -> None:
    operations = catalog.parse_openapi(SPEC)
    first = store.ingest_api_operations(
        project["id"], operations, source_kind="spec", source_ref="specs/orders.json"
    )
    assert len(first["added"]) == 3
    assert first["unchanged"] == 0

    again = store.ingest_api_operations(
        project["id"], operations, source_kind="spec", source_ref="specs/orders.json"
    )
    assert again["added"] == []
    assert again["updated"] == []
    assert again["unchanged"] == 3
    assert store.list_api_operations(project["id"])["total"] == 3


def test_changed_operation_reports_the_changed_fields(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    changed = json.loads(json.dumps(SPEC))
    changed["paths"]["/orders"]["get"]["summary"] = "List every order"

    diff = store.diff_api_operations(project["id"], catalog.parse_openapi(changed))
    assert diff["added"] == []
    assert diff["unchanged"] == 2
    assert diff["changed"][0]["fields"] == ["summary"]

    result = store.ingest_api_operations(project["id"], catalog.parse_openapi(changed))
    assert len(result["updated"]) == 1
    assert result["updated"][0]["fields"] == ["summary"]


def test_dropped_operation_is_marked_missing_not_deleted(store: QaStore, project: dict) -> None:
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    smaller = catalog.parse_openapi({
        "openapi": "3.0.3",
        "paths": {
            "/orders": {
                "get": {
                    "operationId": "listOrders",
                    "summary": "List orders",
                    "responses": {"200": {}},
                }
            }
        },
    })
    result = store.ingest_api_operations(project["id"], smaller)
    assert result["unchanged"] == 1
    assert len(result["missing"]) == 2
    missing = store.list_api_operations(project["id"], status="missing")
    assert missing["total"] == 2
    assert store.list_api_operations(project["id"])["total"] == 3


def test_catalog_listing_paginates(store: QaStore, project: dict) -> None:
    operations = [{"method": "GET", "path": f"/items/{index}"} for index in range(12)]
    store.ingest_api_operations(project["id"], operations)
    page = store.list_api_operations(project["id"])
    assert page["total"] == 12
    assert len(page["items"]) == 10
    assert len(store.list_api_operations(project["id"], offset=10)["items"]) == 2
    assert store.list_api_operations(project["id"], method="get", query="/items/1")["total"] == 3
