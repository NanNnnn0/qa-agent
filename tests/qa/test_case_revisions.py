"""Tests for case revisions: every body change is recorded and conflicts are refused."""

from __future__ import annotations

import pytest

from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaConflictError, QaNotFoundError, QaValidationError


def test_create_and_edit_record_revisions(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="list orders", kind="api")
    revisions = store.list_case_revisions(case["id"])
    assert revisions["total"] == 1
    created = store.get_case_revision(case["id"], 1)
    assert created["snapshot"]["title"] == "list orders"
    assert created["change_source"] == "create"

    store.update_case(case["id"], base_revision=1, title="list every order")
    revisions = store.list_case_revisions(case["id"])
    assert revisions["total"] == 2
    edited = store.get_case_revision(case["id"], 2)
    assert edited["snapshot"]["title"] == "list every order"
    assert edited["change_source"] == "edit"


def test_noop_update_does_not_add_a_revision(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="same body", kind="api")
    store.update_case(case["id"], title="same body")
    assert store.list_case_revisions(case["id"])["total"] == 1


def test_stale_base_revision_is_rejected(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="v1", kind="api")
    store.update_case(case["id"], title="v2")
    with pytest.raises(QaConflictError):
        store.update_case(case["id"], base_revision=1, title="lost update")
    assert store.get_case(case["id"])["title"] == "v2"


def test_revision_rejects_unknown_change_source(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="body", kind="api")
    with pytest.raises(QaValidationError):
        store.update_case(case["id"], change_source="magic", title="changed")


def test_unknown_revision_is_not_found(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="body", kind="api")
    with pytest.raises(QaNotFoundError):
        store.get_case_revision(case["id"], 9)


def test_delete_case_removes_its_revisions(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="body", kind="api")
    store.delete_case(case["id"])
    with pytest.raises(QaNotFoundError):
        store.list_case_revisions(case["id"])


def test_import_records_import_provenance(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="api one", kind="api")
    exported = store.export_cases(project["id"])
    other = store.create_project(key="crm", name="CRM")
    store.import_cases(other["id"], {"cases": exported["cases"]})
    imported = store.list_cases(project_id=other["id"])["items"][0]
    revisions = store.list_case_revisions(imported["id"])
    assert revisions["items"][0]["change_source"] == "import"


def test_revision_listing_paginates(store: QaStore, project: dict) -> None:
    case = store.create_case(project["id"], title="body", kind="api")
    for index in range(3):
        store.update_case(case["id"], title=f"body {index}")
    page = store.list_case_revisions(case["id"], limit=2)
    assert page["total"] == 4
    assert [item["revision"] for item in page["items"]] == [4, 3]
    assert len(store.list_case_revisions(case["id"], limit=2, offset=2)["items"]) == 2
