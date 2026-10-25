"""A version-2 database keeps its data when version 3 adds the API asset tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nanobot.qa.case_files import CaseFiles
from nanobot.qa.store import SCHEMA_VERSION, QaStore
from qa_trace.caseyaml import write_case_document


def _strip_version_three_tables(path: Path) -> None:
    """Turn a current database back into the version-2 shape this upgrade must accept."""
    with sqlite3.connect(path) as conn:
        for table in (
            "api_case_revisions",
            "api_case_metadata",
            "api_workflows",
            "api_operations",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version=2")
        conn.commit()


def _strip_version_five_tables(path: Path) -> None:
    """Turn a current database back into the version-4 shape this upgrade must accept."""
    with sqlite3.connect(path) as conn:
        for table in ("case_trace_summary", "trace_edges", "trace_file_state"):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version=4")
        conn.commit()


def test_version_2_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "qa.sqlite3"
    original = QaStore(path)
    project = original.create_project(key="legacy", name="Legacy", base_url="http://old")
    case = original.create_case(
        project["id"],
        title="existing case",
        kind="api",
        api={"request": {"method": "GET", "path": "/ping"}},
    )
    original.close()
    _strip_version_three_tables(path)

    upgraded = QaStore(path)
    try:
        assert upgraded.get_project(project["id"])["key"] == "LEGACY"
        assert upgraded.get_case(case["id"])["title"] == "existing case"
        assert upgraded.list_cases(project_id=project["id"])["total"] == 1
        assert upgraded.list_api_operations(project["id"])["total"] == 0
        upgraded.create_case(project["id"], title="after upgrade", kind="api")
        assert upgraded.list_cases(project_id=project["id"])["total"] == 2
    finally:
        upgraded.close()

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "api_operations",
        "api_case_metadata",
        "api_case_revisions",
        "api_workflows",
    } <= tables


def test_version_4_database_gains_the_trace_index_and_keeps_its_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qa.sqlite3"
    original = QaStore(path)
    project = original.create_project(key="legacy", name="Legacy")
    case = original.create_case(project["id"], title="existing case", kind="api")
    original.close()
    _strip_version_five_tables(path)

    # Opening twice must neither duplicate the new tables nor lose a row.
    for _ in range(2):
        upgraded = QaStore(path)
        try:
            assert upgraded.get_case(case["id"])["title"] == "existing case"
            assert upgraded.get_case(case["id"])["derived"] == 0
            assert upgraded.list_cases(project_id=project["id"])["total"] == 1
            assert upgraded.trace_index_stats(project["id"]) == {
                "edges": 0,
                "summaries": 0,
                "files": 0,
                "stale": 0,
                "needs_recheck": 0,
            }
        finally:
            upgraded.close()

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
    assert {"trace_edges", "case_trace_summary", "trace_file_state"} <= tables
    assert {
        "idx_trace_edges_target",
        "idx_case_trace_summary_project",
        "idx_case_trace_summary_recheck",
        "idx_trace_file_state_entity",
        "idx_cases_project_status_code",
        "idx_cases_project_kind_status_code",
        "idx_cases_project_code",
        "idx_cases_project_kind_code",
        "idx_api_case_metadata_operation",
        "idx_case_trace_summary_project_module",
    } <= indexes


def _seed_trace_project(store: QaStore) -> tuple[dict, dict, dict[str, int]]:
    """Create one linked YAML case and return its project, case and trace stats."""
    project = store.create_project(key="shop", name="Shop")
    library = CaseFiles(store)
    directory = library.ensure_project(project)
    write_case_document(
        directory / "sources" / "REQ-SHOP-01.yaml",
        {
            "schema_version": 1,
            "id": "REQ-SHOP-01",
            "type": "req",
            "title": "requirement",
            "evidence": [{"type": "document", "locator": "docs/requirement.md"}],
            "status": "active",
            "confidence": "confirmed",
        },
    )
    write_case_document(
        directory / "testpoints" / "TP-SHOP-001.yaml",
        {
            "schema_version": 1,
            "id": "TP-SHOP-001",
            "title": "behaviour",
            "sources": ["REQ-SHOP-01"],
            "method": "boundary",
            "risk": "high",
            "status": "reviewed",
        },
    )
    case = library.create_case(
        project["id"],
        title="linked",
        kind="api",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
        testpoints=["TP-SHOP-001"],
    )
    return project, case, store.trace_index_stats(project["id"])


def test_reopening_a_populated_database_keeps_the_trace_index_stable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qa.sqlite3"
    store = QaStore(path)
    project, case, stats = _seed_trace_project(store)
    summary = store.get_case_trace_summary(case["id"])
    assert summary is not None
    assert stats == {
        "edges": 2,
        "summaries": 1,
        "files": 4,
        "stale": 0,
        "needs_recheck": 0,
    }
    store.close()

    for _ in range(2):
        reopened = QaStore(path)
        try:
            assert reopened.trace_index_stats(project["id"]) == stats
            again = reopened.get_case_trace_summary(case["id"])
            assert again is not None
            assert again["input_hash"] == summary["input_hash"]
            assert reopened.list_cases(project_id=project["id"])["total"] == 1
        finally:
            reopened.close()


def test_version_4_database_rebuilds_the_trace_index_from_yaml(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qa.sqlite3"
    store = QaStore(path)
    project, case, stats = _seed_trace_project(store)
    summary = store.get_case_trace_summary(case["id"])
    assert summary is not None
    store.close()

    # Simulate the version-4 shape: the derived trace tables are gone but the
    # YAML library and the case index rows are exactly what they were.
    _strip_version_five_tables(path)
    upgraded = QaStore(path)
    try:
        assert upgraded.list_cases(project_id=project["id"])["total"] == 1
        assert upgraded.trace_index_stats(project["id"]) == {
            "edges": 0,
            "summaries": 0,
            "files": 0,
            "stale": 0,
            "needs_recheck": 0,
        }
        report = CaseFiles(upgraded).reindex(project_id=project["id"])
        assert report["trace_edges"] == stats["edges"]
        assert report["trace_summaries"] == stats["summaries"]
        assert report["trace_files"] == stats["files"]
        assert upgraded.trace_index_stats(project["id"]) == stats
        again = upgraded.get_case_trace_summary(case["id"])
        assert again is not None
        assert again["input_hash"] == summary["input_hash"]
    finally:
        upgraded.close()


def test_version_5_summary_gains_the_list_columns(tmp_path: Path) -> None:
    path = tmp_path / "qa.sqlite3"
    store = QaStore(path)
    project = store.create_project(key="shop", name="Shop")
    case = store.create_case(project["id"], title="one", kind="api")
    store.close()

    # Recreate the first v5 summary shape: it has no module/group/interface
    # columns, and a row that must survive the additive repair.
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE case_trace_summary")
        conn.execute(
            "CREATE TABLE case_trace_summary ("
            " case_id TEXT PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,"
            " project_id TEXT NOT NULL,"
            " needs_links INTEGER NOT NULL DEFAULT 1,"
            " needs_recheck INTEGER NOT NULL DEFAULT 0,"
            " trace_status TEXT NOT NULL DEFAULT 'draft',"
            " recheck_reasons TEXT NOT NULL DEFAULT '[]',"
            " testpoint_count INTEGER NOT NULL DEFAULT 0,"
            " source_count INTEGER NOT NULL DEFAULT 0,"
            " input_hash TEXT NOT NULL DEFAULT '',"
            " checked_at TEXT NOT NULL DEFAULT '',"
            " state TEXT NOT NULL DEFAULT 'unknown'"
            ")"
        )
        conn.execute(
            "INSERT INTO case_trace_summary (case_id, project_id, needs_links, state)"
            " VALUES (?, ?, 0, 'fresh')",
            (case["id"], project["id"]),
        )
        conn.execute("PRAGMA user_version=5")
        conn.commit()

    reopened = QaStore(path)
    try:
        columns = {
            row[1]
            for row in reopened._conn.execute(
                "PRAGMA table_info(case_trace_summary)"
            ).fetchall()
        }
        assert {"module_id", "group_name", "api_method", "api_path"} <= columns
        summary = reopened.get_case_trace_summary(case["id"])
        assert summary is not None
        assert summary["state"] == "fresh"
        assert summary["module_id"] == ""
        assert summary["api_method"] == ""
    finally:
        reopened.close()
