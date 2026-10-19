"""Tests for ``qa trace failure``: mapping a run's failures back to the chain."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from qa_trace.cli import main
from qa_trace.errors import RunInvalidError, RunNotFoundError
from qa_trace.failure import compute_failure, latest_runs, load_manifest
from qa_trace.loader import load_project
from qa_trace.runs import write_manifest
from qa_trace.staleness import compute_stale

NOW = "2026-10-18T00:00:00+00:00"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failed_result(case_id: str, nodeid: str, *, attempt: int = 1) -> dict[str, object]:
    return {
        "case_id": case_id,
        "nodeid": nodeid,
        "attempt": attempt,
        "outcome": "failed",
        "started_at": "2026-10-18T12:00:01+00:00",
        "finished_at": "2026-10-18T12:00:02+00:00",
        "duration_ms": 3,
        "failure_stage": "call",
        "error_summary": "AssertionError: remaining attempts should be 4",
    }


def _passed_result(case_id: str, nodeid: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "nodeid": nodeid,
        "attempt": 1,
        "outcome": "passed",
        "failure_stage": None,
        "error_summary": None,
    }


def _write_manifest(
    root: Path,
    *,
    run_id: str,
    results: list[dict[str, object]],
    snapshot: dict[str, object] | None = None,
    finished_at: str = "2026-10-18T12:00:05+00:00",
) -> Path:
    payload: dict[str, object] = {
        "manifest_version": 1,
        "run_id": run_id,
        "project_id": "impact-demo",
        "status": "complete",
        "exitstatus": 1,
        "started_at": "2026-10-18T12:00:00+00:00",
        "finished_at": finished_at,
        "tool_version": "0.4.0",
        "environment": "test/python-3.12",
        "code_commit": None,
        "results": results,
    }
    if snapshot is not None:
        payload["asset_snapshot"] = snapshot
    return write_manifest(root / "runs" / run_id / "manifest.json", payload)


def _snapshot(root: Path, case_id: str = "TC-LOGIN-001") -> dict[str, object]:
    return {
        "cases": {case_id: _digest(root / "cases" / f"{case_id}.yaml")},
        "relations": {case_id: {"testpoints": ["TP-LOGIN-001"], "sources": []}},
        "testpoint_sources": {"TP-LOGIN-001": ["REQ-LOGIN-01", "UI-LOGIN-01"]},
    }


def test_failure_maps_a_failed_result_to_its_chain(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[
            _passed_result("TC-LOGIN-001", "demo_test.py::test_lock"),
            _failed_result("TC-LOGIN-001", "demo_test.py::test_remaining", attempt=2),
        ],
        snapshot=_snapshot(root),
    )
    report = compute_failure(load_project(root), "run-1")
    assert report.exit_code == 0
    assert report.run["run_id"] == "run-1"
    assert report.run["status"] == "complete"
    assert report.counts == {
        "results": 2,
        "failed_results": 1,
        "failed_cases": 1,
        "reported_cases": 1,
    }
    failure = report.failures[0]
    assert failure["case_id"] == "TC-LOGIN-001"
    assert failure["results"][0]["attempt"] == 2
    assert failure["results"][0]["failure_stage"] == "call"
    assert failure["chain"]["origin"] == "snapshot"
    assert [item["id"] for item in failure["chain"]["testpoints"]] == ["TP-LOGIN-001"]
    assert [item["id"] for item in failure["chain"]["sources"]] == [
        "REQ-LOGIN-01",
        "UI-LOGIN-01",
    ]
    assert failure["current"]["changed_since_run"] is False
    assert failure["last_run"]["run_id"] == "run-1"


def test_failure_uses_the_run_snapshot_when_the_case_is_gone(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-009", "demo_test.py::test_old")],
        snapshot={
            "cases": {"TC-LOGIN-009": "0" * 64},
            "relations": {
                "TC-LOGIN-009": {"testpoints": ["TP-LOGIN-001"], "sources": []}
            },
            "testpoint_sources": {"TP-LOGIN-001": ["REQ-LOGIN-01"]},
        },
    )
    report = compute_failure(load_project(root), "run-1")
    failure = report.failures[0]
    assert failure["chain"]["origin"] == "snapshot"
    assert [item["id"] for item in failure["chain"]["sources"]] == ["REQ-LOGIN-01"]
    assert failure["current"]["exists"] is False
    assert failure["current"]["changed_since_run"] is None


def test_failure_falls_back_to_the_current_library_without_a_snapshot(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
    )
    report = compute_failure(load_project(root), "run-1")
    failure = report.failures[0]
    assert failure["chain"]["origin"] == "current"
    assert [item["id"] for item in failure["chain"]["sources"]] == [
        "REQ-LOGIN-01",
        "UI-LOGIN-01",
    ]
    assert failure["current"]["changed_since_run"] is None


def test_failure_detects_a_case_that_changed_since_the_run(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
        snapshot={
            "cases": {"TC-LOGIN-001": "f" * 64},
            "relations": {"TC-LOGIN-001": {"testpoints": ["TP-LOGIN-001"], "sources": []}},
        },
    )
    report = compute_failure(load_project(root), "run-1")
    assert report.failures[0]["current"]["changed_since_run"] is True


def test_failure_reports_the_current_recheck_state(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    compute_stale(load_project(root), write=True, now=NOW)
    source = root / "sources" / "REQ-LOGIN-01.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "连续失败 5 次锁定账号", "连续失败 6 次锁定账号"
        ),
        encoding="utf-8",
    )
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
    )
    report = compute_failure(load_project(root), "run-1")
    current = report.failures[0]["current"]
    assert current["needs_recheck"] is True
    assert current["reasons"] == ["dependency_changed"]
    assert current["changed_ids"] == ["TP-LOGIN-001"]


def test_failure_case_filter(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[
            _failed_result("TC-LOGIN-001", "demo_test.py::test_remaining"),
            _passed_result("TC-LOGIN-002", "demo_test.py::test_copy"),
        ],
    )
    project = load_project(root)
    only_passing = compute_failure(project, "run-1", case_id="TC-LOGIN-002")
    assert only_passing.failures == ()
    assert only_passing.case_missing is False
    assert only_passing.exit_code == 0

    missing = compute_failure(project, "run-1", case_id="TC-LOGIN-003")
    assert missing.case_missing is True
    assert missing.failures == ()
    assert missing.exit_code == 1


def test_failure_shows_the_latest_run(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
        finished_at="2026-10-18T12:00:05+00:00",
    )
    _write_manifest(
        root,
        run_id="run-2",
        results=[_passed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
        finished_at="2026-10-18T13:00:05+00:00",
    )
    project = load_project(root)
    latest = latest_runs(project)
    assert latest["TC-LOGIN-001"]["run_id"] == "run-2"
    report = compute_failure(project, "run-1")
    assert report.failures[0]["last_run"]["run_id"] == "run-2"
    assert report.failures[0]["last_run"]["outcome"] == "passed"


def test_failure_missing_and_malformed_runs_are_input_failures(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("impact_project")
    with pytest.raises(RunNotFoundError):
        compute_failure(load_project(root), "nope")
    assert main(["trace", "failure", "--project", str(root), "--run", "nope"]) == 2
    assert "TRACE_RUN_NOT_FOUND" in capsys.readouterr().out

    broken = root / "runs" / "broken" / "manifest.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(RunInvalidError):
        load_manifest(broken)
    assert main(["trace", "failure", "--project", str(root), "--run", "broken"]) == 2
    assert "TRACE_RUN_INVALID" in capsys.readouterr().out

    (root / "runs" / "empty" / "manifest.json").parent.mkdir(parents=True)
    (root / "runs" / "empty" / "manifest.json").write_text("[]", encoding="utf-8")
    assert main(["trace", "failure", "--project", str(root), "--run", "empty"]) == 2
    assert "TRACE_RUN_INVALID" in capsys.readouterr().out


def test_failure_cli_text_and_json(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("impact_project")
    _write_manifest(
        root,
        run_id="run-1",
        results=[_failed_result("TC-LOGIN-001", "demo_test.py::test_remaining")],
        snapshot=_snapshot(root),
    )
    assert main(["trace", "failure", "--project", str(root), "--run", "run-1"]) == 0
    text = capsys.readouterr().out
    assert "case TC-LOGIN-001" in text
    assert "source            REQ-LOGIN-01" in text
    assert "last run" in text

    assert (
        main(["trace", "failure", "--project", str(root), "--run", "run-1", "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["failure_version"] == 1
    assert payload["run"]["run_id"] == "run-1"
    assert payload["failures"][0]["case_id"] == "TC-LOGIN-001"
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
