"""Tests for run metadata, CI ingest, and review decisions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nanobot.qa import service
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError

JUNIT_OK = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="shop" tests="3" failures="1" skipped="1">
    <testcase classname="tests.test_shop" name="test_list" time="0.10"/>
    <testcase classname="tests.test_shop" name="test_order" time="0.25">
      <failure message="expected 201 got 400">AssertionError: expected 201</failure>
    </testcase>
    <testcase classname="tests.test_shop" name="test_legacy" time="0">
      <skipped message="deprecated"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_run_metadata_round_trip(store: QaStore, project: dict) -> None:
    run = store.create_run(
        project["id"], name="nightly", environment="staging", trigger="ci",
    )
    assert run["name"] == "nightly"
    assert run["environment"] == "staging"
    assert run["trigger"] == "ci"
    finished = store.finish_run(run["id"], status="passed", passed=1)
    assert finished["status"] == "passed"

    listing = store.list_runs(project_id=project["id"])["items"]
    assert listing[0]["name"] == "nightly"
    assert listing[0]["environment"] == "staging"
    assert listing[0]["trigger"] == "ci"


def test_run_trigger_is_validated(store: QaStore, project: dict) -> None:
    with pytest.raises(QaValidationError):
        store.create_run(project["id"], trigger="cron")


def test_migration_adds_run_columns_to_a_v1_database(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', base_url TEXT NOT NULL DEFAULT '',
            repo_path TEXT NOT NULL DEFAULT '', default_env TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            script_id TEXT,
            case_ids TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'running',
            passed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            report TEXT NOT NULL DEFAULT '{}',
            log TEXT NOT NULL DEFAULT ''
        );
        PRAGMA user_version=1;
        """
    )
    connection.commit()
    connection.close()

    store = QaStore(path)
    try:
        project = store.create_project(key="old", name="Old")
        run = store.create_run(project["id"], name="legacy", trigger="ci")
        assert run["name"] == "legacy"
        assert run["trigger"] == "ci"
        assert run["environment"] == ""
    finally:
        store.close()


def test_ingest_junit_creates_a_ci_run(store: QaStore, project: dict) -> None:
    run = service.ingest_junit(
        store, project["id"], xml=JUNIT_OK, name="pipeline #42",
        environment="staging",
    )
    assert run["trigger"] == "ci"
    assert run["name"] == "pipeline #42"
    assert run["status"] == "failed"
    assert (run["passed"], run["failed"], run["skipped"]) == (1, 1, 1)
    report = run["report"]
    assert report["reportFormat"] == "junit"
    names = [test["name"] for test in report["tests"]]
    assert "tests.test_shop::test_order" in names
    failed = next(test for test in report["tests"] if test["status"] == "failed")
    assert "expected 201" in failed["message"]


def test_ingest_junit_all_passed(store: QaStore, project: dict) -> None:
    xml = (
        '<testsuite name="s"><testcase name="a" time="0.1"/>'
        '<testcase name="b" time="0.2"/></testsuite>'
    )
    run = service.ingest_junit(store, project["id"], xml=xml)
    assert run["status"] == "passed"
    assert run["passed"] == 2
    assert run["name"] == "CI import"


def test_ingest_junit_rejects_bad_input(store: QaStore, project: dict) -> None:
    with pytest.raises(QaValidationError):
        service.ingest_junit(store, project["id"], xml="")
    with pytest.raises(QaValidationError):
        service.ingest_junit(store, project["id"], xml="<not-xml")
    with pytest.raises(QaValidationError):
        service.ingest_junit(store, project["id"], xml="<testsuite/>")


def test_approve_closes_the_task_and_records_the_decision(
    store: QaStore, project: dict,
) -> None:
    task = store.create_task(
        title="接口用例", role="api", project_id=project["id"],
        status="needs_review", progress=90,
    )
    approved = store.decide_task(
        task["id"], approved=True, note="覆盖足够，通过", reviewer="alice",
    )
    assert approved["status"] == "done"
    assert approved["progress"] == 100
    assert "[approved] alice: 覆盖足够，通过" in approved["result"]
    events = store.list_events(task["id"])
    assert events[-1]["kind"] == "approved"
    assert events[-1]["data"]["reviewer"] == "alice"


def test_reject_closes_the_task_as_failed(store: QaStore, project: dict) -> None:
    task = store.create_task(
        title="功能用例", role="ui", project_id=project["id"], status="needs_review",
    )
    rejected = store.decide_task(
        task["id"], approved=False, note="缺少权限场景", reviewer="bob",
    )
    assert rejected["status"] == "failed"
    assert "[rejected] bob: 缺少权限场景" in rejected["result"]
    assert store.list_events(task["id"])[-1]["kind"] == "rejected"


def test_decisions_are_limited_to_reviewable_tasks(store: QaStore, project: dict) -> None:
    from nanobot.qa.validation import QaConflictError

    task = store.create_task(
        title="still running", role="api", project_id=project["id"], status="running",
    )
    with pytest.raises(QaConflictError):
        store.decide_task(task["id"], approved=True)
