"""Tests for ``qa trace impact``: affected test points, cases and scripts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from qa_trace.cli import main
from qa_trace.impact import compute_impact, render_impact
from qa_trace.loader import load_project
from qa_trace.staleness import compute_stale

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-10-18T00:00:00+00:00"


def _change_source(root: Path) -> None:
    path = root / "sources" / "REQ-LOGIN-01.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "连续失败 5 次锁定账号", "连续失败 6 次锁定账号"
        ),
        encoding="utf-8",
    )


def test_impact_of_a_source_lists_testpoints_cases_and_scripts() -> None:
    project = load_project(FIXTURES / "impact_project")
    result = compute_impact(project, source="REQ-LOGIN-01")
    assert result is not None
    assert [item["id"] for item in result.testpoints] == ["TP-LOGIN-001", "TP-LOGIN-002"]
    assert [item["id"] for item in result.cases] == ["TC-LOGIN-001", "TC-LOGIN-002"]
    assert result.scripts == (
        {
            "case_id": "TC-LOGIN-001",
            "binding": "scripts/test_login.py::test_lock_after_5_failures",
            "file": "scripts/test_login.py",
            "nodeid": "test_lock_after_5_failures",
            "resolves": True,
            "problem": None,
        },
    )
    # A case hanging directly off another source is not dragged in.
    assert "TC-LOGIN-003" not in {item["id"] for item in result.cases}
    # The affected path is the one through the queried source.
    assert result.cases[0]["via"] == [
        {"source_id": "REQ-LOGIN-01", "testpoint_id": "TP-LOGIN-001"},
    ]
    payload = result.to_dict()
    assert payload["impact_version"] == 1
    assert payload["target"] == {"id": "REQ-LOGIN-01", "kind": "source"}
    assert payload["counts"] == {
        "testpoints": 2,
        "cases": 2,
        "scripts": 1,
        "needs_recheck": 0,
    }
    assert "TP-LOGIN-001" in render_impact(result)


def test_impact_of_a_testpoint_lists_its_sources_and_cases() -> None:
    project = load_project(FIXTURES / "impact_project")
    result = compute_impact(project, testpoint="TP-LOGIN-001")
    assert result is not None
    assert [item["id"] for item in result.sources] == ["REQ-LOGIN-01", "UI-LOGIN-01"]
    assert [item["id"] for item in result.cases] == ["TC-LOGIN-001"]
    assert [item["id"] for item in result.testpoints] == ["TP-LOGIN-001"]
    assert result.cases[0]["via"] == [
        {"source_id": "REQ-LOGIN-01", "testpoint_id": "TP-LOGIN-001"},
        {"source_id": "UI-LOGIN-01", "testpoint_id": "TP-LOGIN-001"},
    ]


def test_impact_of_a_case_lists_its_own_chain() -> None:
    project = load_project(FIXTURES / "impact_project")
    result = compute_impact(project, case="TC-LOGIN-003")
    assert result is not None
    assert [item["id"] for item in result.sources] == ["UI-LOGIN-01"]
    assert result.testpoints == ()
    assert [item["id"] for item in result.cases] == ["TC-LOGIN-003"]
    assert result.scripts == ()


def test_impact_marks_the_cases_that_need_a_recheck(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    compute_stale(load_project(root), write=True, now=NOW)
    _change_source(root)
    result = compute_impact(load_project(root), source="REQ-LOGIN-01")
    assert result is not None
    assert [item["id"] for item in result.cases] == ["TC-LOGIN-001", "TC-LOGIN-002"]
    assert all(item["needs_recheck"] for item in result.cases)
    assert result.cases[0]["reasons"] == ["dependency_changed"]
    assert result.cases[0]["changed_ids"] == ["TP-LOGIN-001"]
    # A case on an untouched source stays current.
    other = compute_impact(load_project(root), case="TC-LOGIN-003")
    assert other is not None
    assert other.cases[0]["needs_recheck"] is False


def test_impact_unknown_id_returns_none() -> None:
    project = load_project(FIXTURES / "impact_project")
    assert compute_impact(project, case="TC-LOGIN-999") is None
    # A valid ID of the wrong kind is just as unknown for that selector.
    assert compute_impact(project, source="TP-LOGIN-001") is None


def test_impact_cli_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    project = str(FIXTURES / "impact_project")
    assert main(["trace", "impact", "--project", project, "--source", "REQ-LOGIN-01"]) == 0
    assert "TC-LOGIN-001" in capsys.readouterr().out

    assert main(["trace", "impact", "--project", project, "--case", "TC-LOGIN-999"]) == 1
    assert "TRACE_ENTITY_NOT_FOUND" in capsys.readouterr().out

    assert main(["trace", "impact", "--project", project, "--json", "--testpoint", "TP-LOGIN-002"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == {"id": "TP-LOGIN-002", "kind": "testpoint"}

    missing = str(FIXTURES / "no-such-project")
    assert main(["trace", "impact", "--project", missing, "--source", "REQ-LOGIN-01"]) == 2
    assert "TRACE_PROJECT_INVALID" in capsys.readouterr().out


def test_impact_json_is_stable_across_runs() -> None:
    project = load_project(FIXTURES / "impact_project")
    first = compute_impact(project, source="REQ-LOGIN-01")
    second = compute_impact(load_project(FIXTURES / "impact_project"), source="REQ-LOGIN-01")
    assert first is not None and second is not None
    assert first.to_dict() == second.to_dict()
    assert json.loads(json.dumps(first.to_dict(), ensure_ascii=False)) == first.to_dict()
