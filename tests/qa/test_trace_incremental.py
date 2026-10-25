"""Incremental trace refresh: only the cases behind a changed entity move."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.qa.case_files import CaseFiles
from nanobot.qa.store import QaStore
from nanobot.qa.trace_api import default_trace_root
from qa_trace.caseyaml import read_case_document, write_case_document

API_SPEC: dict[str, Any] = {
    "request": {"method": "GET", "path": "/api/products"},
    "assertions": [{"type": "status", "expect": 200}],
}


def _write_source(directory: Path, source_id: str, title: str) -> None:
    write_case_document(
        directory / "sources" / f"{source_id}.yaml",
        {
            "schema_version": 1,
            "id": source_id,
            "type": "req",
            "module": "SHOP",
            "title": title,
            "evidence": [{"type": "document", "locator": "docs/requirement.md"}],
            "status": "active",
            "confidence": "confirmed",
        },
    )


def _write_testpoint(
    directory: Path,
    testpoint_id: str,
    title: str,
    sources: list[str],
    *,
    group: str,
) -> None:
    write_case_document(
        directory / "testpoints" / f"{testpoint_id}.yaml",
        {
            "schema_version": 1,
            "id": testpoint_id,
            "title": title,
            "sources": sources,
            "group": group,
            "method": "boundary",
            "risk": "high",
            "status": "reviewed",
        },
    )


def _edit_document(path: Path, **fields: Any) -> None:
    document = read_case_document(path)
    document.update(fields)
    write_case_document(path, document)


@pytest.fixture
def chain(store: QaStore, project: dict[str, Any]) -> dict[str, Any]:
    """Two linked reviewed cases and one unlinked draft."""
    library = CaseFiles(store, default_trace_root())
    directory = library.ensure_project(project)
    _write_source(directory, "REQ-SHOP-01", "requirement one")
    _write_source(directory, "REQ-SHOP-02", "requirement two")
    _write_testpoint(
        directory,
        "TP-SHOP-001",
        "login boundary",
        ["REQ-SHOP-01"],
        group="登录模块/注册界面",
    )
    _write_testpoint(
        directory,
        "TP-SHOP-002",
        "order boundary",
        ["REQ-SHOP-02"],
        group="订单模块/下单",
    )
    first = library.create_case(
        project["id"],
        title="login case",
        kind="api",
        status="ready",
        api=API_SPEC,
        testpoints=["TP-SHOP-001"],
    )
    second = library.create_case(
        project["id"],
        title="order case",
        kind="api",
        status="ready",
        api=API_SPEC,
        testpoints=["TP-SHOP-002"],
    )
    unlinked = library.create_case(
        project["id"], title="unlinked draft", kind="api", api=API_SPEC
    )
    library.reindex(project_id=project["id"])
    return {
        "library": library,
        "directory": directory,
        "first": first,
        "second": second,
        "unlinked": unlinked,
    }


def _summary(store: QaStore, case_id: str) -> dict[str, Any]:
    summary = store.get_case_trace_summary(case_id)
    assert summary is not None
    return summary


def _without_checked_at(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "checked_at"}


def _assert_matches_full(
    store: QaStore,
    library: CaseFiles,
    project_id: str,
    case_id: str,
    incremental: dict[str, Any],
) -> None:
    edges = store.list_trace_edges(project_id)
    files = store.list_trace_file_states(project_id)
    library.reindex(project_id=project_id)
    full = _summary(store, case_id)
    assert _without_checked_at(incremental) == _without_checked_at(full)
    assert store.list_trace_edges(project_id) == edges
    assert store.list_trace_file_states(project_id) == files


def test_a_testpoint_change_refreshes_only_its_cases(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    unlinked = chain["unlinked"]["id"]
    before_first = _summary(store, first)
    before_second = _summary(store, second)
    before_unlinked = _summary(store, unlinked)

    _edit_document(
        chain["directory"] / "testpoints" / "TP-SHOP-001.yaml",
        title="login boundary v2",
        group="登录模块/登录页",
    )
    affected = library.affected_cases_for_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert affected == {first}

    report = library.refresh_trace_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert report["affected"] == [first]
    assert report["refreshed"] == [first]
    assert report["missing"] is False

    after_first = _summary(store, first)
    after_second = _summary(store, second)
    after_unlinked = _summary(store, unlinked)
    assert after_first["input_hash"] != before_first["input_hash"]
    assert after_first["group_name"] == "登录模块/登录页"
    assert after_first["module_id"] == "登录模块"
    assert after_first["trace_status"] == "reviewed"
    assert after_first["state"] == "fresh"
    assert after_first["needs_links"] is False
    assert after_first["testpoint_count"] == 1
    assert after_first["source_count"] == 1
    assert after_first["needs_recheck"] is True
    assert "dependency_changed" in after_first["recheck_reasons"]
    # The unrelated case keeps both its hash and its exact checked_at.
    assert after_second == before_second
    assert after_unlinked == before_unlinked

    _assert_matches_full(
        store, library, project["id"], first, after_first
    )


def test_a_requirement_change_refreshes_cases_below_its_testpoints(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    unlinked = chain["unlinked"]["id"]
    before_first = _summary(store, first)
    before_second = _summary(store, second)
    before_unlinked = _summary(store, unlinked)

    _edit_document(
        chain["directory"] / "sources" / "REQ-SHOP-01.yaml",
        title="requirement one v2",
    )
    affected = library.affected_cases_for_entity(
        project["id"], "requirement", "REQ-SHOP-01"
    )
    assert affected == {first}

    report = library.refresh_trace_entity(
        project["id"], "requirement", "REQ-SHOP-01"
    )
    assert report["affected"] == [first]
    assert report["refreshed"] == [first]

    after_first = _summary(store, first)
    assert after_first["input_hash"] != before_first["input_hash"]
    assert after_first["needs_recheck"] is True
    assert "dependency_changed" in after_first["recheck_reasons"]
    assert _summary(store, second) == before_second
    assert _summary(store, unlinked) == before_unlinked

    _assert_matches_full(
        store, library, project["id"], first, after_first
    )


def test_a_testpoint_source_change_updates_the_reverse_edges(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    before_first = _summary(store, first)
    before_second = _summary(store, second)

    _edit_document(
        chain["directory"] / "testpoints" / "TP-SHOP-001.yaml",
        sources=["REQ-SHOP-02"],
    )
    report = library.refresh_trace_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert report["affected"] == [first]

    old_source = store.get_dependents(project["id"], "source", "REQ-SHOP-01")
    new_source = store.get_dependents(project["id"], "source", "REQ-SHOP-02")
    assert {"from_type": "testpoint", "from_id": "TP-SHOP-001"} not in old_source
    assert {"from_type": "testpoint", "from_id": "TP-SHOP-001"} in new_source

    after_first = _summary(store, first)
    assert after_first["input_hash"] != before_first["input_hash"]
    assert after_first["source_count"] == 1
    assert _summary(store, second) == before_second
    _assert_matches_full(
        store, library, project["id"], first, after_first
    )


def test_deleting_a_testpoint_marks_its_cases_stale(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    before_second = _summary(store, second)

    (chain["directory"] / "testpoints" / "TP-SHOP-001.yaml").unlink()
    affected = library.affected_cases_for_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert affected == {first}
    report = library.refresh_trace_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert report["missing"] is True

    after_first = _summary(store, first)
    assert after_first["state"] == "stale"
    assert after_first["testpoint_count"] == 0
    assert after_first["source_count"] == 0
    assert after_first["needs_links"] is False
    assert _summary(store, second) == before_second
    _assert_matches_full(
        store, library, project["id"], first, after_first
    )


def test_batch_refresh_does_not_load_the_project(
    store: QaStore,
    project: dict[str, Any],
    chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    before_first = _summary(store, first)
    before_second = _summary(store, second)

    case_path = chain["directory"] / "cases" / f"{first}.yaml"
    _edit_document(case_path, expected="201")

    def fail_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("incremental refresh must not load the project")

    monkeypatch.setattr("nanobot.qa.case_files.load_project", fail_load)
    result = library.refresh_trace_for_cases(project["id"], [first])
    assert result["refreshed"] == [first]
    assert _summary(store, first)["input_hash"] != before_first["input_hash"]
    assert _summary(store, second) == before_second


def test_a_requirement_change_also_refreshes_direct_cases(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    direct = library.create_case(
        project["id"],
        title="direct requirement case",
        kind="api",
        api=API_SPEC,
        sources=["REQ-SHOP-01"],
        direct_reason="the source has no test point for this case",
    )
    library.reindex(project_id=project["id"])
    before_first = _summary(store, first)
    before_direct = _summary(store, direct["id"])
    before_second = _summary(store, second)

    _edit_document(
        chain["directory"] / "sources" / "REQ-SHOP-01.yaml",
        title="requirement one v3",
    )
    affected = library.affected_cases_for_entity(
        project["id"], "requirement", "REQ-SHOP-01"
    )
    assert affected == {first, direct["id"]}

    report = library.refresh_trace_entity(
        project["id"], "requirement", "REQ-SHOP-01"
    )
    assert set(report["affected"]) == {first, direct["id"]}
    after_first = _summary(store, first)
    after_direct = _summary(store, direct["id"])
    assert after_first["input_hash"] != before_first["input_hash"]
    assert after_direct["input_hash"] != before_direct["input_hash"]
    assert _summary(store, second) == before_second

    _assert_matches_full(
        store, library, project["id"], direct["id"], after_direct
    )


def test_one_testpoint_change_refreshes_a_batch_of_cases(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    extra = library.create_case(
        project["id"],
        title="second login case",
        kind="api",
        status="ready",
        api=API_SPEC,
        testpoints=["TP-SHOP-001"],
    )
    library.reindex(project_id=project["id"])
    before_first = _summary(store, first)
    before_extra = _summary(store, extra["id"])
    before_second = _summary(store, second)

    _edit_document(
        chain["directory"] / "testpoints" / "TP-SHOP-001.yaml",
        title="login boundary v3",
    )
    affected = library.affected_cases_for_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert affected == {first, extra["id"]}

    report = library.refresh_trace_entity(
        project["id"], "testpoint", "TP-SHOP-001"
    )
    assert set(report["affected"]) == {first, extra["id"]}
    assert set(report["refreshed"]) == {first, extra["id"]}
    assert _summary(store, first)["input_hash"] != before_first["input_hash"]
    assert _summary(store, extra["id"])["input_hash"] != before_extra["input_hash"]
    assert _summary(store, second) == before_second

    _assert_matches_full(
        store, library, project["id"], extra["id"], _summary(store, extra["id"])
    )


def test_a_case_change_refreshes_only_that_case(
    store: QaStore, project: dict[str, Any], chain: dict[str, Any]
) -> None:
    library: CaseFiles = chain["library"]
    first = chain["first"]["id"]
    second = chain["second"]["id"]
    unlinked = chain["unlinked"]["id"]
    before_first = _summary(store, first)
    before_second = _summary(store, second)
    before_unlinked = _summary(store, unlinked)

    _edit_document(
        chain["directory"] / "cases" / f"{first}.yaml",
        expected="200",
    )
    affected = library.affected_cases_for_entity(
        project["id"], "case", first
    )
    assert affected == {first}
    report = library.refresh_trace_entity(project["id"], "case", first)
    assert report["affected"] == [first]
    assert report["refreshed"] == [first]
    after_first = _summary(store, first)
    assert after_first["input_hash"] != before_first["input_hash"]
    assert _summary(store, second) == before_second
    assert _summary(store, unlinked) == before_unlinked

    _assert_matches_full(
        store, library, project["id"], first, after_first
    )
