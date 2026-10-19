"""A version-2 database keeps its data when version 3 adds the API asset tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nanobot.qa.store import SCHEMA_VERSION, QaStore


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
