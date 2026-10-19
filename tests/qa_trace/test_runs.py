"""Tests for the P2 run-manifest helpers (plan section 3.5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from qa_trace.models import FailureStage, Outcome, Run
from qa_trace.runs import (
    MANIFEST_VERSION,
    MAX_ERROR_SUMMARY,
    STATUS_COLLECT_ONLY,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    NodeResult,
    aggregate_cases,
    build_manifest,
    run_status,
    truncate_error,
    write_manifest,
)

STARTED = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
FINISHED = datetime(2026, 10, 18, 12, 0, 5, tzinfo=UTC)


def _node(
    nodeid: str,
    outcome: Outcome,
    *,
    case_ids: tuple[str, ...] = ("TC-LOGIN-001",),
    started_at: datetime | None = None,
    failure_stage: FailureStage | None = None,
    error_summary: str | None = None,
) -> NodeResult:
    return NodeResult(
        nodeid=nodeid,
        case_ids=case_ids,
        outcome=outcome,
        started_at=started_at or STARTED,
        finished_at=FINISHED,
        duration_ms=12,
        failure_stage=failure_stage,
        error_summary=error_summary,
    )


def test_truncate_error_keeps_the_head_and_marks_the_loss() -> None:
    message = "x" * (MAX_ERROR_SUMMARY + 500)
    truncated = truncate_error(message)
    assert truncated is not None
    assert len(truncated) == MAX_ERROR_SUMMARY
    assert truncated.endswith("(truncated)")
    assert truncated.startswith("x" * 100)


def test_truncate_error_keeps_short_and_empty_messages() -> None:
    assert truncate_error("boom") == "boom"
    assert truncate_error("  \n ") is None
    assert truncate_error(None) is None


def test_a_failing_parameter_never_aggregates_to_a_pass() -> None:
    results = [
        _node("tests/test_x.py::test_param[1]", Outcome.PASSED),
        _node("tests/test_x.py::test_param[2]", Outcome.FAILED),
    ]
    cases = aggregate_cases(results)
    assert len(cases) == 1
    case = cases[0]
    assert case["case_id"] == "TC-LOGIN-001"
    assert case["outcome"] == "failed"
    assert case["counts"]["passed"] == 1
    assert case["counts"]["failed"] == 1
    assert case["attempts"] == 2
    assert case["nodeids"] == [
        "tests/test_x.py::test_param[1]",
        "tests/test_x.py::test_param[2]",
    ]


def test_an_error_outranks_a_failure() -> None:
    cases = aggregate_cases(
        [
            _node("tests/test_x.py::test_a", Outcome.FAILED),
            _node("tests/test_x.py::test_b", Outcome.ERROR),
        ]
    )
    assert cases[0]["outcome"] == "error"


def test_run_status_marks_interrupted_sessions_incomplete() -> None:
    assert run_status(0) == STATUS_COMPLETE
    assert run_status(1) == STATUS_COMPLETE
    assert run_status(2) == STATUS_INCOMPLETE
    assert run_status(3) == STATUS_INCOMPLETE
    assert run_status(1, collect_only=True) == STATUS_COLLECT_ONLY


def test_manifest_parses_as_the_p0_run_model() -> None:
    manifest = build_manifest(
        run_id="20261018T120000Z-abcdef12",
        project_id="demo",
        project_path="projects/demo",
        status=STATUS_COMPLETE,
        exitstatus=1,
        started_at=STARTED,
        finished_at=FINISHED,
        environment="win32/python-3.12.7",
        tool_version="0.3.0",
        code_commit=None,
        asset_snapshot={"cases": {"TC-LOGIN-001": "deadbeef"}},
        script_digest={"sha256": "00", "files": {}},
        results=[
            _node(
                "tests/test_x.py::test_fail",
                Outcome.FAILED,
                failure_stage=FailureStage.CALL,
                error_summary="boom",
            )
        ],
        unmapped_nodeids=["tests/test_x.py::test_plain"],
        pytest_version="9.1.1",
        rootdir=".",
        args=["-q"],
    )
    assert manifest["manifest_version"] == MANIFEST_VERSION
    run = Run.from_dict(manifest)
    assert run.run_id == "20261018T120000Z-abcdef12"
    assert run.project_id == "demo"
    assert len(run.results) == 1
    assert run.results[0].outcome is Outcome.FAILED
    assert run.results[0].failure_stage is FailureStage.CALL


def test_results_are_numbered_per_case_in_run_order() -> None:
    manifest = build_manifest(
        run_id="run-1",
        project_id="demo",
        project_path=None,
        status=STATUS_COMPLETE,
        exitstatus=0,
        started_at=STARTED,
        finished_at=FINISHED,
        environment=None,
        tool_version="0.3.0",
        code_commit=None,
        asset_snapshot=None,
        script_digest=None,
        results=[
            _node(
                "tests/test_x.py::test_param[1]",
                Outcome.PASSED,
                started_at=datetime(2026, 10, 18, 12, 0, 1, tzinfo=UTC),
            ),
            _node(
                "tests/test_x.py::test_param[2]",
                Outcome.PASSED,
                started_at=datetime(2026, 10, 18, 12, 0, 2, tzinfo=UTC),
            ),
        ],
    )
    assert [(row["nodeid"], row["attempt"]) for row in manifest["results"]] == [
        ("tests/test_x.py::test_param[1]", 1),
        ("tests/test_x.py::test_param[2]", 2),
    ]
    assert manifest["summary"]["results"] == 2
    assert manifest["summary"]["collected"] == 2


def test_write_manifest_replaces_the_file_atomically(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "run-1" / "manifest.json"
    first = write_manifest(target, {"run_id": "run-1", "value": 1})
    second = write_manifest(target, {"run_id": "run-1", "value": 2})
    assert first == target
    assert second == target
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "run_id": "run-1",
        "value": 2,
    }
    # No temporary file survives, and the parent directory holds one file.
    assert [path.name for path in target.parent.iterdir()] == ["manifest.json"]
