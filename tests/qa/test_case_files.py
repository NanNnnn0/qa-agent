"""Tests for the YAML case library (``nanobot.qa.case_files``).

YAML is the source of truth for cases and SQLite only indexes it.  These tests
pin the contract the WebUI and the agent tool rely on (the legacy JSON shape stays
the same), the file layout a human reviews, the tombstone rules, the promotion
gate (a formal case must be linked) and the transitional read of hand-written
SQLite rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from qa_helpers import make_request

from nanobot.qa.case_files import CaseFiles
from nanobot.qa.http import QaApi
from nanobot.qa.store import QaStore
from nanobot.qa.trace_api import default_trace_root
from nanobot.qa.validation import (
    CASE_KINDS,
    CASE_PRIORITIES,
    CASE_STATUSES,
    QaConflictError,
    QaNotFoundError,
    QaValidationError,
)
from qa_trace import run_check
from qa_trace.caseyaml import write_case_document

API_SPEC: dict[str, Any] = {
    "request": {"method": "GET", "path": "/api/products"},
    "assertions": [{"type": "status", "expect": 200}],
}


@pytest.fixture
def library(store: QaStore) -> CaseFiles:
    return CaseFiles(store, default_trace_root())


@pytest.fixture
def shop(store: QaStore) -> dict[str, Any]:
    return store.create_project(key="shop", name="Demo Shop")


def _write_trace_link(project_dir: Path) -> None:
    """Add one source and one test point so a case can be linked."""
    write_case_source = {
        "schema_version": 1,
        "id": "REQ-SHOP-01",
        "type": "req",
        "module": "SHOP",
        "title": "订单必须可追溯",
        "evidence": [{"type": "document", "locator": "docs/order.md#1"}],
        "status": "active",
        "confidence": "confirmed",
    }
    write_case_document(project_dir / "sources" / "REQ-SHOP-01.yaml", write_case_source)
    write_case_document(
        project_dir / "testpoints" / "TP-SHOP-001.yaml",
        {
            "schema_version": 1,
            "id": "TP-SHOP-001",
            "title": "下单返回订单号",
            "sources": ["REQ-SHOP-01"],
            "method": "boundary",
            "risk": "high",
            "status": "reviewed",
        },
    )


# -- creating --------------------------------------------------------------


def test_create_writes_a_draft_file_and_indexes_it(
    library: CaseFiles, shop: dict[str, Any], tmp_path: Path
) -> None:
    case = library.create_case(
        shop["id"],
        title="商品列表返回 200",
        kind="api",
        priority="P0",
        expected="返回 200",
        api=API_SPEC,
        tags=["smoke", "order"],
        source="ai",
        author="qa-agent",
    )

    assert case["id"] == "TC-SHOP-001"
    assert case["code"] == "SHOP-API-001"
    assert case["kind"] == "api"
    assert case["priority"] == "P0"
    assert case["status"] == "draft"
    assert case["project_id"] == shop["id"]
    assert case["api"]["request"]["path"] == "/api/products"
    assert case["tags"] == ["smoke", "order"]
    assert case["draft"] is True
    assert case["needs_links"] is True
    assert case["batch"] == "workbench"
    assert case["yaml_path"] == "draft/workbench/cases/TC-SHOP-001.yaml"

    path = default_trace_root() / "shop" / case["yaml_path"]
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "status: draft" in text
    assert "type: api" in text

    # The store is a derived index, so the row exists after the write.
    assert library.store.get_case("TC-SHOP-001")["derived"] == 1


def test_an_api_case_without_steps_gets_one_from_its_request(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    case = library.create_case(
        shop["id"], title="商品列表", kind="api", expected="返回 200", api=API_SPEC
    )
    assert case["steps"] == [{"action": "GET /api/products", "expected": "返回 200"}]


def test_codes_are_generated_per_kind_and_ids_per_project(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    first = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    second = library.create_case(shop["id"], title="two", kind="api", api=API_SPEC)
    ui = library.create_case(
        shop["id"],
        title="cart",
        kind="ui",
        steps=[{"action": "open cart", "expected": "visible"}],
    )
    assert (first["code"], second["code"], ui["code"]) == (
        "SHOP-API-001",
        "SHOP-API-002",
        "SHOP-UI-001",
    )
    assert [first["id"], second["id"], ui["id"]] == [
        "TC-SHOP-001",
        "TC-SHOP-002",
        "TC-SHOP-003",
    ]


def test_an_explicit_code_must_be_unique_and_well_formed(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    library.create_case(shop["id"], title="one", code="SHOP-API-007", api=API_SPEC)
    with pytest.raises(QaConflictError):
        library.create_case(shop["id"], title="two", code="SHOP-API-007", api=API_SPEC)
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="bad", code="lowercase code", api=API_SPEC)


def test_validation_reuses_the_sqlite_contract(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="bad kind", kind="smoke")
    with pytest.raises(QaValidationError):
        library.create_case(
            shop["id"], title="bad api", api={"request": {"method": "FLY", "path": "/x"}}
        )
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="")
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="archived", status="deprecated")


def test_links_are_validated(library: CaseFiles, shop: dict[str, Any]) -> None:
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="x", testpoints=["REQ-SHOP-01"])
    with pytest.raises(QaValidationError):
        library.create_case(shop["id"], title="x", sources=["TP-SHOP-001"])


# -- reading ---------------------------------------------------------------


def test_list_filters_and_orders_like_the_sqlite_listing(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    library.create_case(shop["id"], title="api one", kind="api", api=API_SPEC)
    library.create_case(shop["id"], title="cart flow", kind="ui",
                        steps=[{"action": "open", "expected": "visible"}])
    library.create_case(shop["id"], title="api two", kind="api", api=API_SPEC, status="ready")

    assert library.list_cases(project_id=shop["id"])["total"] == 3
    assert library.list_cases(project_id=shop["id"], kind="api")["total"] == 2
    assert library.list_cases(project_id=shop["id"], status="ready")["total"] == 1
    assert library.list_cases(project_id=shop["id"], query="cart")["total"] == 1
    page = library.list_cases(project_id=shop["id"], limit=1, offset=1)
    assert len(page["items"]) == 1
    assert page["total"] == 3


def test_get_carries_the_legacy_shape_and_the_trace_badges(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    created = library.create_case(
        shop["id"], title="one", kind="api", api=API_SPEC, expected="200"
    )
    case = library.get_case(created["id"])
    for key in (
        "id",
        "code",
        "title",
        "kind",
        "priority",
        "status",
        "steps",
        "api",
        "tags",
        "project_id",
    ):
        assert key in case
    assert case["trace_status"] == "draft"
    assert case["type"] == "api"
    assert case["automation"] == "todo"
    assert case["testpoints"] == []
    assert case["sources"] == []
    assert case["script"] is None
    assert case["needs_recheck"] is False
    with pytest.raises(QaNotFoundError):
        library.get_case("TC-SHOP-999")


# -- updating --------------------------------------------------------------


def test_a_linkless_case_keeps_the_review_status_but_stays_a_draft(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    created = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    updated = library.update_case(created["id"], status="ready")
    assert updated["status"] == "ready"
    assert updated["draft"] is True
    assert updated["needs_links"] is True
    assert updated["yaml_path"].startswith("draft/")
    # The formal library stays loadable: nothing was written into cases/.
    assert run_check(default_trace_root() / "shop").exit_code == 0


def test_a_linked_case_is_promoted_to_the_formal_library(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    directory = library.ensure_project(shop)
    _write_trace_link(directory)
    created = library.create_case(
        shop["id"],
        title="下单返回订单号",
        kind="api",
        api=API_SPEC,
        expected="返回 200",
    )
    assert created["draft"] is True

    promoted = library.update_case(
        created["id"], status="ready", testpoints=["TP-SHOP-001"], reviewer="qa.li"
    )
    assert promoted["draft"] is False
    assert promoted["yaml_path"] == "cases/TC-SHOP-001.yaml"
    assert promoted["testpoints"] == ["TP-SHOP-001"]
    assert promoted["needs_links"] is False
    assert (directory / "cases" / "TC-SHOP-001.yaml").is_file()
    assert not (directory / created["yaml_path"]).is_file()

    # The formal library loads and the review is recorded in the derived index.
    assert run_check(directory).exit_code == 0
    index = json.loads((directory / ".qa-trace" / "index.json").read_text(encoding="utf-8"))
    assert index["reviews"]["TC-SHOP-001"]["reviewed_by"] == "qa.li"

    # Demoting it moves the file back to draft/.
    demoted = library.update_case(created["id"], status="draft")
    assert demoted["draft"] is True
    assert demoted["status"] == "draft"
    assert not (directory / "cases" / "TC-SHOP-001.yaml").exists()


def test_a_case_whose_link_does_not_exist_cannot_be_promoted(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    directory = library.ensure_project(shop)
    _write_trace_link(directory)
    created = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    with pytest.raises(QaConflictError):
        library.update_case(created["id"], status="ready", testpoints=["TP-SHOP-999"])
    # Nothing moved into the formal library, so the project still checks clean.
    assert not (directory / "cases" / f"{created['id']}.yaml").exists()
    assert run_check(directory).exit_code == 0

    with pytest.raises(QaConflictError):
        library.create_case(
            shop["id"],
            title="dangling",
            kind="api",
            api=API_SPEC,
            status="ready",
            testpoints=["TP-SHOP-999"],
        )


def test_update_edits_the_document_and_keeps_unknown_keys(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    created = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    path = default_trace_root() / "shop" / created["yaml_path"]
    document = path.read_text(encoding="utf-8")
    path.write_text(document + "jira: QA-77\n", encoding="utf-8")
    library.reindex(project_id=shop["id"])

    updated = library.update_case(
        created["id"],
        title="renamed",
        priority="P2",
        expected="201",
        tags=["regression"],
        steps=[{"action": "GET /api/products", "expected": "201"}],
    )
    assert updated["title"] == "renamed"
    assert updated["priority"] == "P2"
    assert updated["tags"] == ["regression"]
    assert "jira: QA-77" in path.read_text(encoding="utf-8")


# -- deleting --------------------------------------------------------------


def test_delete_writes_a_tombstone_and_retires_the_id(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    created = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    outcome = library.delete_case(created["id"], reason="duplicate")
    assert outcome["deleted"] is True
    assert outcome["tombstone"] == "tombstones/TC-SHOP-001.yaml"

    directory = default_trace_root() / "shop"
    tombstone = directory / "tombstones" / "TC-SHOP-001.yaml"
    assert tombstone.is_file()
    assert "status: deprecated" in tombstone.read_text(encoding="utf-8")
    assert "reason: duplicate" in tombstone.read_text(encoding="utf-8")

    with pytest.raises(QaNotFoundError):
        library.get_case(created["id"])
    assert library.list_cases(project_id=shop["id"])["total"] == 0
    # An explicit filter for archived cases still finds it.
    archived = library.list_cases(project_id=shop["id"], status="deprecated")
    assert archived["total"] == 1

    # The ID is retired: the next case gets 002.
    again = library.create_case(shop["id"], title="two", kind="api", api=API_SPEC)
    assert again["id"] == "TC-SHOP-002"


# -- index maintenance -----------------------------------------------------


def test_reindex_picks_up_a_hand_edit(
    library: CaseFiles, shop: dict[str, Any]
) -> None:
    created = library.create_case(shop["id"], title="one", kind="api", api=API_SPEC)
    path = default_trace_root() / "shop" / created["yaml_path"]
    path.write_text(
        path.read_text(encoding="utf-8").replace("title: one", "title: renamed on disk"),
        encoding="utf-8",
    )
    # The index (not the file) answers reads, so the listing is still stale…
    assert library.list_cases(project_id=shop["id"])["items"][0]["title"] == "one"
    report = library.reindex(project_id=shop["id"])
    assert report["cases"] == 1
    # …until the index is rebuilt from YAML.
    assert (
        library.list_cases(project_id=shop["id"])["items"][0]["title"] == "renamed on disk"
    )


def test_export_and_import_round_trip(
    library: CaseFiles, shop: dict[str, Any], store: QaStore
) -> None:
    library.create_case(shop["id"], title="api one", kind="api", api=API_SPEC)
    exported = library.export_cases(shop["id"])
    assert exported["format"] == "qa-agent.cases.v1"
    assert exported["project"]["key"] == "SHOP"
    assert len(exported["cases"]) == 1

    other = store.create_project(key="crm", name="CRM")
    result = library.import_cases(other["id"], {"cases": exported["cases"]})
    assert len(result["created"]) == 1
    assert result["created"][0]["code"] == "SHOP-API-001"
    again = library.import_cases(other["id"], {"cases": exported["cases"]})
    assert again["created"] == []
    assert again["skipped"]


# -- the transitional legacy rows -----------------------------------------


def test_a_hand_written_sqlite_row_is_readable_but_not_editable(
    library: CaseFiles, store: QaStore, shop: dict[str, Any]
) -> None:
    legacy = store.create_case(shop["id"], title="seeded row", kind="api", api=API_SPEC)
    listed = library.list_cases(project_id=shop["id"])
    assert listed["total"] == 1
    assert listed["items"][0]["legacy"] is True
    assert listed["items"][0]["id"] == legacy["id"]

    detail = library.get_case(legacy["id"])
    assert detail["title"] == "seeded row"
    assert detail["needs_links"] is True

    with pytest.raises(QaConflictError):
        library.update_case(legacy["id"], title="nope")
    with pytest.raises(QaConflictError):
        library.delete_case(legacy["id"])


def test_a_migrated_legacy_row_is_replaced_by_the_yaml_case(
    library: CaseFiles, store: QaStore, shop: dict[str, Any]
) -> None:
    legacy = store.create_case(shop["id"], title="seeded row", kind="api", code="SHOP-API-001")
    directory = library.ensure_project(shop)
    write_case_document(
        directory / "draft" / "sqlite-migration" / "cases" / "TC-SHOP-001.yaml",
        {
            "schema_version": 1,
            "id": "TC-SHOP-001",
            "code": "SHOP-API-001",
            "legacy_id": legacy["id"],
            "title": "seeded row",
            "priority": "P1",
            "type": "api",
            "status": "draft",
            "steps": [{"action": "GET /api/products", "expected": "200"}],
            "automation": {"status": "todo"},
        },
    )
    library.reindex(project_id=shop["id"])
    listed = library.list_cases(project_id=shop["id"])
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == "TC-SHOP-001"
    assert listed["items"][0]["legacy_id"] == legacy["id"]
    assert listed["items"][0]["legacy"] is False


def test_a_legacy_row_with_the_same_code_is_hidden_by_the_yaml_case(
    library: CaseFiles, store: QaStore, shop: dict[str, Any]
) -> None:
    """A seeded database keeps its own row ids, so the code has to claim it too.

    The committed library records the ``legacy_id`` of the machine it was migrated
    on; deploying it onto a separately seeded database used to show both rows.
    """
    legacy = store.create_case(shop["id"], title="seeded row", kind="api", code="SHOP-API-001")
    directory = library.ensure_project(shop)
    write_case_document(
        directory / "cases" / "TC-SHOP-001.yaml",
        {
            "schema_version": 1,
            "id": "TC-SHOP-001",
            "code": "SHOP-API-001",
            "legacy_id": "case_from_another_machine",
            "title": "migrated row",
            "priority": "P1",
            "type": "api",
            "status": "reviewed",
            "testpoints": ["TP-SHOP-001"],
            "steps": [{"action": "GET /api/products", "expected": "200"}],
            "automation": {"status": "todo"},
        },
    )
    library.reindex(project_id=shop["id"])
    listed = library.list_cases(project_id=shop["id"])
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == "TC-SHOP-001"
    assert store.project_stats(shop["id"])["cases"] == 1
    assert store.get_case(legacy["id"])["code"] == "SHOP-API-001"  # the row is kept


# -- HTTP ------------------------------------------------------------------


async def _dispatch(api: QaApi, request: Any) -> Any:
    from nanobot.webui.http_utils import parse_request_path

    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got)


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


async def test_http_cases_are_backed_by_yaml(store: QaStore, shop: dict[str, Any]) -> None:
    from nanobot.qa.http import QaApi

    api = QaApi(store, trace_root=default_trace_root())
    response = await _dispatch(
        api,
        make_request(
            "/api/qa/cases/create",
            {
                "project_id": shop["id"],
                "title": "通过 HTTP 新建",
                "kind": "api",
                "api": API_SPEC,
            },
        ),
    )
    payload = _body(response)
    assert payload["ok"] is True
    case_id = payload["case"]["id"]
    assert case_id == "TC-SHOP-001"

    yaml_path = default_trace_root() / "shop" / payload["case"]["yaml_path"]
    assert yaml_path.is_file()

    response = await _dispatch(api, make_request(f"/api/qa/cases?project_id={shop['id']}"))
    listing = _body(response)
    assert listing["total"] == 1
    assert listing["items"][0]["code"] == "SHOP-API-001"

    response = await _dispatch(
        api, make_request(f"/api/qa/cases/{case_id}")
    )
    assert _body(response)["case"]["title"] == "通过 HTTP 新建"

    # Delete archives the case (tombstone), so the default listing is empty.
    response = await _dispatch(
        api, make_request("/api/qa/cases/delete", {"id": case_id})
    )
    assert _body(response)["deleted"] is True
    assert (default_trace_root() / "shop" / "tombstones" / f"{case_id}.yaml").is_file()
    response = await _dispatch(api, make_request(f"/api/qa/cases?project_id={shop['id']}"))
    assert _body(response)["total"] == 0


# -- vocabulary drift ------------------------------------------------------


def test_the_legacy_vocabulary_matches_the_sqlite_contract() -> None:
    from qa_trace.compat import LEGACY_BY_STATUS, LEGACY_KINDS, LEGACY_STATUSES

    assert set(LEGACY_KINDS) == set(CASE_KINDS)
    assert set(LEGACY_STATUSES) == set(CASE_STATUSES)
    assert set(LEGACY_BY_STATUS.values()) == set(CASE_STATUSES)
    assert set(CASE_PRIORITIES) == {"P0", "P1", "P2", "P3"}
