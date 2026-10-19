"""Tests for the one-way SQLite -> YAML case migration (``qa_trace.migrate``).

The export must be safe on a live installation (the database is opened read-only),
readable on disk (``TC-<MODULE>-<seq>`` IDs, ``legacy_id`` back to the row) and
honest (a legacy case has no trace link, so it is a draft).  Re-running must not
duplicate anything.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from qa_trace.caseyaml import iter_case_documents, read_case_document
from qa_trace.cli import main
from qa_trace.errors import MigrateError
from qa_trace.migrate import MIGRATION_BATCH, migrate_sqlite_cases

SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE cases (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'api',
    priority TEXT NOT NULL DEFAULT 'P1',
    status TEXT NOT NULL DEFAULT 'draft',
    preconditions TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',
    api TEXT NOT NULL DEFAULT '{}',
    expected TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual',
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "case_api_1",
        "code": "SHOP-API-001",
        "title": "商品列表返回 200",
        "kind": "api",
        "priority": "P0",
        "status": "ready",
        "steps": json.dumps([{"action": "GET /api/products", "expected": "200"}]),
        "api": json.dumps({
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        }),
        "expected": "返回 200",
        "tags": json.dumps(["smoke"]),
        "author": "qa-agent",
        "source": "ai",
    },
    {
        "id": "case_api_2",
        "code": "SHOP-UI-001",
        "title": "购物车结算",
        "kind": "ui",
        "priority": "P1",
        "status": "draft",
        "steps": json.dumps([{"action": "打开购物车", "expected": "展示商品"}]),
        "api": "{}",
    },
    {
        "id": "case_api_3",
        "code": "SHOP-API-002",
        "title": "已删除的旧用例",
        "kind": "api",
        "priority": "P2",
        "status": "deprecated",
        "steps": "[]",
        "api": json.dumps({"request": {"method": "GET", "path": "/old"}}),
    },
)


def _build_database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO projects (id, key, name) VALUES (?, ?, ?)",
            ("proj_1", "SHOP", "Demo 商城"),
        )
        for item in CASES:
            connection.execute(
                "INSERT INTO cases (id, project_id, code, title, kind, priority, status,"
                " preconditions, steps, api, expected, tags, source, author, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, '', '')",
                (
                    item["id"],
                    "proj_1",
                    item["code"],
                    item["title"],
                    item["kind"],
                    item["priority"],
                    item["status"],
                    item.get("steps", "[]"),
                    item.get("api", "{}"),
                    item.get("expected", ""),
                    item.get("tags", "[]"),
                    item.get("source", "manual"),
                    item.get("author", ""),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return _build_database(tmp_path / "qa.sqlite3")


def test_the_export_writes_drafts_with_readable_ids_and_a_legacy_mapping(
    database: Path, tmp_path: Path
) -> None:
    root = tmp_path / "projects"
    report = migrate_sqlite_cases(database, root, project="SHOP")

    assert report.db == database.as_posix()
    assert len(report.projects) == 1
    project = report.projects[0]
    assert project.key == "SHOP"
    assert (project.cases, project.drafts, project.formal, project.tombstones) == (3, 2, 0, 1)
    assert report.drafts == 2 and report.formal == 0 and report.tombstones == 1

    directory = root / "shop"
    project_yaml = (directory / "project.yaml").read_text(encoding="utf-8")
    assert "project_id: shop" in project_yaml
    assert "modules:" in project_yaml

    documents = {
        document["id"]: (path, document)
        for path, _batch, document in iter_case_documents(
            directory, include_drafts=True, include_tombstones=True
        )
    }
    assert sorted(documents) == ["TC-SHOP-001", "TC-SHOP-002", "TC-SHOP-003"]

    path, api_case = documents["TC-SHOP-001"]
    assert path.as_posix().endswith(
        f"draft/{MIGRATION_BATCH}/cases/TC-SHOP-001.yaml"
    )
    assert api_case["legacy_id"] == "case_api_1"
    assert api_case["code"] == "SHOP-API-001"
    assert api_case["status"] == "draft"
    assert api_case["type"] == "api"
    assert api_case["steps"] == [{"action": "GET /api/products", "expected": "200"}]
    assert api_case["api"]["request"]["path"] == "/api/products"
    assert api_case["automation"] == {"status": "todo"}
    assert api_case["source"] == "ai"
    assert api_case["owner"] == "qa-agent"

    _, ui_case = documents["TC-SHOP-003"]
    assert ui_case["type"] == "ui"
    assert ui_case["status"] == "draft"
    assert ui_case["automation"] == {"status": "manual"}

    # A deprecated row becomes a tombstone, not a live case.
    deprecated_path, deprecated = documents["TC-SHOP-002"]
    assert deprecated_path.as_posix().endswith("tombstones/TC-SHOP-002.yaml")
    assert deprecated["status"] == "deprecated"


def test_an_api_case_without_steps_gets_one_from_its_request(
    database: Path, tmp_path: Path
) -> None:
    root = tmp_path / "projects"
    migrate_sqlite_cases(database, root)
    _, _, document = next(
        item
        for item in iter_case_documents(root / "shop", include_tombstones=True)
        if item[2]["id"] == "TC-SHOP-002"
    )
    # The deprecated row had empty steps: the request is the step.
    assert document["steps"] == [{"action": "GET /old", "expected": "request succeeds"}]


def test_the_export_never_writes_the_database(database: Path, tmp_path: Path) -> None:
    before = database.read_bytes()
    migrate_sqlite_cases(database, tmp_path / "projects")
    assert database.read_bytes() == before


def test_re_running_skips_rows_that_already_have_a_yaml_case(
    database: Path, tmp_path: Path
) -> None:
    root = tmp_path / "projects"
    first = migrate_sqlite_cases(database, root)
    files_before = sorted(
        path.as_posix()
        for path in (root / "shop").rglob("*.yaml")
    )
    second = migrate_sqlite_cases(database, root)
    assert second.cases == 0
    assert second.projects[0].skipped == len(CASES)
    assert sorted(path.as_posix() for path in (root / "shop").rglob("*.yaml")) == files_before
    assert first.cases == 3


def test_an_unknown_project_is_an_input_error(database: Path, tmp_path: Path) -> None:
    with pytest.raises(MigrateError) as caught:
        migrate_sqlite_cases(database, tmp_path / "projects", project="NOPE")
    assert "NOPE" in caught.value.message
    assert caught.value.code == "TRACE_MIGRATE_INVALID"


def test_a_missing_database_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(MigrateError):
        migrate_sqlite_cases(tmp_path / "missing.sqlite3", tmp_path / "projects")


def test_a_database_without_the_qa_tables_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE notes (id TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(MigrateError):
        migrate_sqlite_cases(path, tmp_path / "projects")


def test_the_cli_reports_counts_and_exits_zero(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "projects"
    assert main([
        "trace", "migrate-sqlite",
        "--db", str(database),
        "--root", str(root),
        "--project", "SHOP",
    ]) == 0
    out = capsys.readouterr().out
    assert "3 case(s)" in out
    assert "drafts 2" in out
    assert "tombstones 1" in out


def test_the_cli_emits_json_and_json_reports_the_counts(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "projects"
    assert main([
        "trace", "migrate-sqlite",
        "--db", str(database),
        "--root", str(root),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["migration_version"] == 1
    assert payload["counts"]["cases"] == 3
    assert payload["counts"]["drafts"] == 2
    assert payload["counts"]["projects"] == 1
    assert payload["projects"][0]["key"] == "SHOP"


def test_the_cli_maps_input_errors_to_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([
        "trace", "migrate-sqlite",
        "--db", str(tmp_path / "missing.sqlite3"),
        "--root", str(tmp_path / "projects"),
    ]) == 2
    assert "TRACE_MIGRATE_INVALID" in capsys.readouterr().out


def test_the_cli_requires_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NANOBOT_QA_DB", raising=False)
    assert main([
        "trace", "migrate-sqlite",
        "--root", str(tmp_path / "projects"),
    ]) == 2
    assert "NANOBOT_QA_DB" in capsys.readouterr().out


def test_the_cli_reads_the_database_path_from_the_environment(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NANOBOT_QA_DB", str(database))
    assert main([
        "trace", "migrate-sqlite",
        "--root", str(tmp_path / "projects"),
    ]) == 0
    assert "3 case(s)" in capsys.readouterr().out


def test_the_migrated_project_is_clean_for_check(database: Path, tmp_path: Path) -> None:
    from qa_trace import run_check

    root = tmp_path / "projects"
    migrate_sqlite_cases(database, root)
    # Drafts are not part of the formal library, so the empty formal library is valid.
    result = run_check(root / "shop")
    assert result.exit_code == 0
    assert result.diagnostics == ()


def test_the_documents_are_readable_by_the_case_store(database: Path, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    migrate_sqlite_cases(database, root)
    path = root / "shop" / "draft" / MIGRATION_BATCH / "cases" / "TC-SHOP-001.yaml"
    document = read_case_document(path)
    # The case is structurally complete; only the trace link is missing.
    assert document["title"]
    assert document["status"] == "draft"
    assert document["steps"]
