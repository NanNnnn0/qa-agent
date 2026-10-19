"""Tests for the P1 graph rules: references, orphans and checklist rules 10-13."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_trace.check import run_check
from qa_trace.cli import main
from qa_trace.diagnostics import Diagnostic
from qa_trace.graph import TraceGraph, TracePath
from qa_trace.loader import Project, ProjectConfig, load_project
from qa_trace.models import (
    Automation,
    AutomationStatus,
    Case,
    CaseType,
    Evidence,
    EvidenceType,
    Method,
    Priority,
    ReviewStatus,
    Risk,
    Source,
    SourceType,
    Step,
    TestPoint,
)
from qa_trace.rules import (
    NEEDS_RECHECK,
    P0_RATIO_HIGH,
    SOURCE_DRAFT_ONLY,
    SOURCE_NO_DOWNSTREAM,
    check_graph,
)

FIXTURES = Path(__file__).parent / "fixtures"

#: The model class is not a test class, but pytest collects anything named Test*.
TestPoint.__test__ = False

CASE_TEMPLATE = """\
schema_version: 1
id: {case_id}
title: 手工构造的用例
testpoints:
  - TP-LOGIN-005
priority: {priority}
type: functional
status: {status}
steps:
  - action: 连续输错密码 5 次
    expected: 提示“账号锁定 15 分钟”，HTTP 状态码 423
automation:
  status: manual
"""

SOURCE_TEMPLATE = """\
schema_version: 1
id: UI-LOGIN-02
type: ui
title: 登录失败 5 次触发账号锁定
evidence:
  - type: ui_capture
    locator: artifacts/ui/login-lock-5x.png
url: /login
app_version: 3.4.1
observed_at: 2026-10-18
confidence: confirmed
status: active
stale: {stale}
"""

TESTPOINT_TEMPLATE = """\
schema_version: 1
id: TP-LOGIN-005
title: 连续失败计数与锁定阈值
sources:
  - UI-LOGIN-02
method: boundary
risk: high
status: {status}
"""


def _write_project(
    root: Path,
    *,
    project_yaml: str = "schema_version: 1\nproject_id: hand\n",
    files: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(project_yaml, encoding="utf-8")
    for name, text in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _source(identifier: str, kind: SourceType = SourceType.BUG) -> Source:
    return Source(
        id=identifier,
        type=kind,
        title="hand built",
        evidence=(Evidence(type=EvidenceType.DOCUMENT, locator="docs/x.md"),),
    )


def _testpoint(identifier: str, sources: tuple[str, ...]) -> TestPoint:
    return TestPoint(
        id=identifier,
        title="hand built",
        sources=sources,
        method=Method.BOUNDARY,
        risk=Risk.HIGH,
        status=ReviewStatus.REVIEWED,
    )


def _case(
    identifier: str,
    *,
    testpoints: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    direct_reason: str | None = None,
) -> Case:
    return Case(
        id=identifier,
        title="hand built",
        priority=Priority.P1,
        type=CaseType.FUNCTIONAL,
        steps=(Step(action="a", expected="b"),),
        status=ReviewStatus.REVIEWED,
        automation=Automation(status=AutomationStatus.MANUAL),
        testpoints=testpoints,
        sources=sources,
        direct_reason=direct_reason,
    )


def _hand_built_project(
    *,
    sources: dict[str, Source],
    testpoints: dict[str, TestPoint] | None = None,
    cases: dict[str, Case] | None = None,
) -> Project:
    return Project(
        root=Path("."),
        config=ProjectConfig(schema_version=1, project_id="hand"),
        sources=sources,
        testpoints=testpoints or {},
        cases=cases or {},
    )


def _codes(diagnostics: tuple[Diagnostic, ...]) -> list[str]:
    return [item.code for item in diagnostics]


def test_graph_indexes_testpoints_and_cases() -> None:
    graph = TraceGraph(load_project(FIXTURES / "valid_project"))
    assert graph.downstream_testpoints("UI-LOGIN-02") == ("TP-LOGIN-005",)
    assert graph.downstream_cases("UI-LOGIN-02") == ("TC-LOGIN-003",)
    assert graph.case_paths("TC-LOGIN-003") == (
        TracePath(source_id="UI-LOGIN-02", testpoint_id="TP-LOGIN-005"),
    )
    assert graph.case_sources("TC-LOGIN-003") == ("UI-LOGIN-02",)
    assert not graph.is_orphan("TC-LOGIN-003")


def test_case_paths_include_every_testpoint_source() -> None:
    graph = TraceGraph(load_project(FIXTURES / "metrics_project"))
    paths = graph.case_paths("TC-LOGIN-001")
    assert paths == (
        TracePath(source_id="REQ-LOGIN-01", testpoint_id="TP-LOGIN-001"),
        TracePath(source_id="UI-LOGIN-01", testpoint_id="TP-LOGIN-001"),
    )


def test_case_paths_follow_direct_sources() -> None:
    graph = TraceGraph(load_project(FIXTURES / "metrics_project"))
    assert graph.case_paths("TC-LOGIN-004") == (TracePath(source_id="BUG-LOGIN-01"),)


def test_valid_project_has_no_graph_diagnostics() -> None:
    result = run_check(FIXTURES / "valid_project")
    assert result.diagnostics == ()
    assert result.exit_code == 0


def test_dangling_source_is_an_error() -> None:
    result = run_check(FIXTURES / "invalid_dangling_source")
    missing = [item for item in result.diagnostics if item.code == "TRACE_REF_MISSING"]
    assert len(missing) == 1
    assert missing[0].path == "testpoints/TP-LOGIN-005.yaml"
    assert missing[0].field == "sources[0]"
    assert missing[0].entity_id == "TP-LOGIN-005"
    assert "UI-LOGIN-404" in missing[0].message
    assert result.exit_code == 1


def test_orphan_case_is_an_error() -> None:
    result = run_check(FIXTURES / "invalid_orphan_case")
    orphans = [item for item in result.diagnostics if item.code == "TRACE_CASE_ORPHAN"]
    assert len(orphans) == 1
    assert orphans[0].path == "cases/TC-LOGIN-003.yaml"
    assert orphans[0].entity_id == "TC-LOGIN-003"
    assert "TRACE_REF_MISSING" in _codes(result.diagnostics)
    assert result.exit_code == 1


def test_dangling_script_target_is_an_error() -> None:
    result = run_check(FIXTURES / "invalid_dangling_script")
    missing = [item for item in result.diagnostics if item.code == "TRACE_REF_MISSING"]
    assert len(missing) == 1
    assert missing[0].path == "cases/TC-LOGIN-003.yaml"
    assert missing[0].field == "automation.script"
    assert "test_missing.py" in missing[0].message
    assert result.exit_code == 1


def test_stale_source_marks_downstream_cases_for_recheck() -> None:
    fixture = FIXTURES / "stale_propagation"
    case_file = fixture / "cases" / "TC-LOGIN-003.yaml"
    before = case_file.read_text(encoding="utf-8")
    result = run_check(fixture)
    rechecks = [item for item in result.diagnostics if item.code == NEEDS_RECHECK]
    assert len(rechecks) == 1
    assert rechecks[0].entity_id == "TC-LOGIN-003"
    assert rechecks[0].path == "cases/TC-LOGIN-003.yaml"
    assert "UI-LOGIN-02" in rechecks[0].message
    # Derived only: the run must not touch the case file or its status.
    assert case_file.read_text(encoding="utf-8") == before
    assert "needs_recheck" not in before
    project = load_project(fixture)
    assert project.cases["TC-LOGIN-003"].status is ReviewStatus.REVIEWED
    assert result.exit_code == 0


def test_stale_source_alone_does_not_fail_the_run() -> None:
    result = run_check(FIXTURES / "stale_propagation")
    assert [item.severity.value for item in result.diagnostics] == ["info"]
    assert result.valid


def test_deprecated_cases_are_not_put_up_for_recheck(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="true"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P1", status="reviewed"
            ),
            "cases/TC-LOGIN-002.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-002", priority="P1", status="deprecated"
            ),
        },
    )
    rechecks = [
        item.entity_id for item in run_check(root).diagnostics if item.code == NEEDS_RECHECK
    ]
    assert rechecks == ["TC-LOGIN-001"]


def test_p0_ratio_warns_above_the_threshold() -> None:
    result = run_check(FIXTURES / "metrics_project")
    warnings = [item for item in result.diagnostics if item.code == P0_RATIO_HIGH]
    assert len(warnings) == 1
    assert warnings[0].path == "project.yaml"
    assert warnings[0].field == "thresholds.p0_ratio_max"
    assert "1/3" in warnings[0].message
    assert "33.33%" in warnings[0].message
    # A draft P0 case must not raise the ratio: 3 reviewed cases, 1 of them P0.
    assert result.exit_code == 0


def test_p0_ratio_uses_the_configured_threshold(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        project_yaml="schema_version: 1\nproject_id: hand\nthresholds:\n  p0_ratio_max: 0.5\n",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="false"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P0", status="reviewed"
            ),
            "cases/TC-LOGIN-002.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-002", priority="P1", status="reviewed"
            ),
        },
    )
    result = run_check(root)
    assert P0_RATIO_HIGH not in _codes(result.diagnostics)
    assert result.exit_code == 0


def test_p0_ratio_above_a_strict_threshold_still_only_warns(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        project_yaml="schema_version: 1\nproject_id: hand\nthresholds:\n  p0_ratio_max: 0.1\n",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="false"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P0", status="reviewed"
            ),
        },
    )
    result = run_check(root)
    assert P0_RATIO_HIGH in _codes(result.diagnostics)
    assert result.exit_code == 0


def test_strict_project_fails_on_warnings(tmp_path: Path) -> None:
    fixture = FIXTURES / "metrics_project"
    root = tmp_path / "proj"
    for path in fixture.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            target = root / path.relative_to(fixture)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    project_yaml = root / "project.yaml"
    project_yaml.write_text(
        project_yaml.read_text(encoding="utf-8") + "strict: true\n", encoding="utf-8"
    )
    result = run_check(root)
    assert result.strict
    assert result.valid
    assert result.exit_code == 1


def test_source_without_downstream_is_info() -> None:
    result = run_check(FIXTURES / "metrics_project")
    infos = [item for item in result.diagnostics if item.code == SOURCE_NO_DOWNSTREAM]
    assert len(infos) == 1
    assert infos[0].entity_id == "API-LOGIN-01"
    assert infos[0].path == "sources/API-LOGIN-01.yaml"


def test_source_with_draft_only_downstream_is_info(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="false"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P1", status="draft"
            ),
        },
    )
    result = run_check(root)
    assert SOURCE_DRAFT_ONLY in _codes(result.diagnostics)
    assert SOURCE_NO_DOWNSTREAM not in _codes(result.diagnostics)
    assert result.exit_code == 0


def test_source_reference_to_the_wrong_kind_is_a_type_mismatch() -> None:
    project = _hand_built_project(
        sources={"BUG-LOGIN-01": _source("BUG-LOGIN-01")},
        testpoints={"TP-LOGIN-005": _testpoint("TP-LOGIN-005", ("BUG-LOGIN-01",))},
        cases={
            "TC-LOGIN-009": _case(
                "TC-LOGIN-009", sources=("TP-LOGIN-005",), direct_reason="regression"
            )
        },
    )
    diagnostics = check_graph(project)
    codes = _codes(diagnostics)
    assert "TRACE_REF_TYPE_MISMATCH" in codes
    assert "TRACE_REF_MISSING" not in codes
    mismatch = [item for item in diagnostics if item.code == "TRACE_REF_TYPE_MISMATCH"][0]
    assert mismatch.field == "sources[0]"
    assert mismatch.entity_id == "TC-LOGIN-009"


def test_case_with_direct_source_and_no_reason_warns() -> None:
    project = _hand_built_project(
        sources={"BUG-LOGIN-01": _source("BUG-LOGIN-01")},
        cases={"TC-LOGIN-009": _case("TC-LOGIN-009", sources=("BUG-LOGIN-01",))},
    )
    diagnostics = check_graph(project)
    assert _codes(diagnostics) == ["TRACE_DIRECT_REASON_MISSING"]
    assert diagnostics[0].severity.value == "warn"
    assert diagnostics[0].field == "direct_reason"


def test_script_target_outside_the_project_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    root = _write_project(
        tmp_path / "proj",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="false"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P1", status="reviewed"
            ).replace("status: manual", "status: done\n  script: ../outside.py::test_x"),
        },
    )
    result = run_check(root)
    assert _codes(result.diagnostics) == ["TRACE_REF_OUTSIDE_PROJECT"]
    assert result.exit_code == 1


def test_script_target_must_be_a_python_file(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        files={
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(stale="false"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(status="reviewed"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", priority="P1", status="reviewed"
            ).replace("status: manual", "status: done\n  script: scripts/data.txt::test_x"),
            "scripts/data.txt": "not a python file\n",
        },
    )
    result = run_check(root)
    assert _codes(result.diagnostics) == ["TRACE_REF_TYPE_MISMATCH"]
    assert result.diagnostics[0].field == "automation.script"


def test_diagnostics_are_sorted_and_stable() -> None:
    first = run_check(FIXTURES / "invalid_dangling_source").diagnostics
    second = run_check(FIXTURES / "invalid_dangling_source").diagnostics
    assert first == second
    keys = [(item.severity.value, item.path or "", item.code) for item in first]
    assert keys == sorted(keys, key=lambda key: ({"error": 0, "warn": 1, "info": 2}[key[0]], key[1], key[2]))


def test_cli_check_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["trace", "check", "--project", str(FIXTURES / "valid_project")]) == 0
    assert capsys.readouterr().out.strip() == "OK"

    assert main(["trace", "check", "--project", str(FIXTURES / "metrics_project")]) == 0
    warned = capsys.readouterr().out
    assert "WARN  TRACE_P0_RATIO_HIGH" in warned
    assert "INFO  TRACE_SOURCE_NO_DOWNSTREAM" in warned

    assert main(["trace", "check", "--project", str(FIXTURES / "invalid_orphan_case")]) == 1
    assert "TRACE_CASE_ORPHAN" in capsys.readouterr().out

    missing = tmp_path / "missing"
    assert main(["trace", "check", "--project", str(missing)]) == 2
    assert "TRACE_PROJECT_INVALID" in capsys.readouterr().out


def test_cli_check_exit_code_two_for_unreadable_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_project(
        tmp_path / "proj", files={"sources/UI-LOGIN-02.yaml": "id: [unclosed\n"}
    )
    assert main(["trace", "check", "--project", str(root)]) == 2
    assert "TRACE_YAML_INVALID" in capsys.readouterr().out


def test_invalid_threshold_is_an_input_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_project(
        tmp_path / "proj",
        project_yaml="schema_version: 1\nproject_id: hand\nthresholds:\n  p0_ratio_max: 3\n",
    )
    assert main(["trace", "check", "--project", str(root)]) == 2
    assert "thresholds.p0_ratio_max" in capsys.readouterr().out
