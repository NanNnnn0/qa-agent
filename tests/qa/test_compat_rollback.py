"""Feature-flag fallback and index-recovery behavior."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.qa.case_files import CaseFiles
from nanobot.qa.store import QaStore
from nanobot.qa.trace_api import default_trace_root

API_SPEC: dict[str, Any] = {
    "request": {"method": "GET", "path": "/api/products"},
    "assertions": [{"type": "status", "expect": 200}],
}

FLAG = "QA_CASE_TRACE_INCREMENTAL"


@pytest.fixture
def library(store: QaStore) -> CaseFiles:
    return CaseFiles(store, default_trace_root())


def test_flag_off_restores_the_full_list_payload(
    library: CaseFiles,
    store: QaStore,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library.create_case(project["id"], title="one", kind="api", api=API_SPEC)
    monkeypatch.setenv(FLAG, "0")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("flag-off list must not query summaries")

    monkeypatch.setattr(store, "list_case_summaries", fail)
    listing = library.list_cases(project_id=project["id"])
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["api"]["request"]["path"] == "/api/products"
    assert "trace_testpoints" in item


def test_flag_off_create_uses_the_full_reindex_path(
    library: CaseFiles,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FLAG, "0")
    calls: list[str | None] = []
    original = library.reindex

    def spy(
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        trace: bool = True,
    ) -> dict[str, Any]:
        calls.append(project_id)
        return original(project_id=project_id, project_key=project_key, trace=trace)

    monkeypatch.setattr(library, "reindex", spy)
    case = library.create_case(
        project["id"], title="created", kind="api", api=API_SPEC
    )
    assert calls == [project["id"]]
    assert case["api"]["request"]["path"] == "/api/products"


def test_flag_off_refresh_falls_back_to_full_reindex(
    library: CaseFiles,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = library.create_case(
        project["id"], title="one", kind="api", api=API_SPEC
    )
    monkeypatch.setenv(FLAG, "0")
    result = library.refresh_trace_for_cases(project["id"], [case["id"]])
    assert result["fallback"] == "full_reindex"
    assert result["refreshed"] == [case["id"]]


def test_flag_off_update_uses_the_full_reindex_path(
    library: CaseFiles,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = library.create_case(
        project["id"], title="before", kind="api", api=API_SPEC
    )
    monkeypatch.setenv(FLAG, "0")
    calls: list[tuple[str | None, bool]] = []
    original = library.reindex

    def spy(
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        trace: bool = True,
    ) -> dict[str, Any]:
        calls.append((project_id, trace))
        return original(project_id=project_id, project_key=project_key, trace=trace)

    monkeypatch.setattr(library, "reindex", spy)
    updated = library.update_case(case["id"], title="after")
    assert updated["title"] == "after"
    assert calls
    assert calls[0][0] == project["id"]


def test_flag_off_import_uses_the_legacy_per_item_path(
    library: CaseFiles,
    store: QaStore,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FLAG, "0")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("legacy import must not use the batch transaction")

    monkeypatch.setattr(store, "apply_case_batch", fail)
    result = library.import_cases(
        project["id"],
        {
            "cases": [
                {"title": "one", "kind": "api", "code": "SHOP-API-001"},
                {"title": "two", "kind": "api", "code": "SHOP-API-002"},
            ]
        },
    )
    assert len(result["created"]) == 2
    assert store.list_cases(project_id=project["id"])["total"] == 2


def test_missing_summary_falls_back_then_reindex_repairs_it(
    library: CaseFiles,
    store: QaStore,
    project: dict[str, Any],
) -> None:
    case = library.create_case(
        project["id"], title="one", kind="api", api=API_SPEC
    )
    store._conn.execute(
        "DELETE FROM case_trace_summary WHERE case_id = ?", (case["id"],)
    )
    store._conn.commit()

    fallback = library.list_cases(project_id=project["id"])
    assert fallback["total"] == 1
    assert "api" in fallback["items"][0]

    library.reindex(project_id=project["id"])
    assert store.get_case_trace_summary(case["id"]) is not None
    summary_listing = library.list_cases(project_id=project["id"])
    assert "api" not in summary_listing["items"][0]


def test_a_dropped_summary_table_falls_back_and_reindex_recreates_it(
    library: CaseFiles,
    store: QaStore,
    project: dict[str, Any],
) -> None:
    case = library.create_case(
        project["id"], title="one", kind="api", api=API_SPEC
    )
    store._conn.execute("DROP TABLE case_trace_summary")
    store._conn.commit()

    fallback = library.list_cases(project_id=project["id"])
    assert fallback["total"] == 1
    assert "api" in fallback["items"][0]

    library.reindex(project_id=project["id"])
    assert store.get_case_trace_summary(case["id"]) is not None


def test_reindex_never_rewrites_the_yaml_source(
    library: CaseFiles,
    project: dict[str, Any],
) -> None:
    case = library.create_case(
        project["id"], title="one", kind="api", api=API_SPEC
    )
    path = default_trace_root() / "shop" / case["yaml_path"]
    before = path.read_bytes()
    library.reindex(project_id=project["id"])
    assert path.read_bytes() == before
