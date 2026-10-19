"""Tests for the project loader, its fixtures and its diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_trace.cli import main
from qa_trace.errors import QaTraceError, QaTraceGroupError
from qa_trace.loader import collect_errors, load_project
from qa_trace.models import AutomationStatus

FIXTURES = Path(__file__).parent / "fixtures"

CASE_TEMPLATE = """\
schema_version: 1
id: {case_id}
title: 测试用例
testpoints:
  - TP-LOGIN-005
priority: P1
type: functional
status: draft
steps:
  - action: 打开登录页
    expected: 登录页标题显示“登录”
automation:
  status: manual
"""

EVIDENCE_FREE_SOURCE = """\
schema_version: 1
id: UI-LOGIN-02
type: ui
title: 没有证据的 UI 来源
url: /login
app_version: 3.4.1
observed_at: 2026-10-18
"""


def _write_project(
    root: Path,
    *,
    project_yaml: str = "schema_version: 1\nproject_id: demo\n",
    cases: dict[str, str] | None = None,
    sources: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(project_yaml, encoding="utf-8")
    for directory, files in (("cases", cases), ("sources", sources)):
        if not files:
            continue
        target = root / directory
        target.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (target / name).write_text(text, encoding="utf-8")
    return root


def test_valid_project_loads() -> None:
    project = load_project(FIXTURES / "valid_project")
    assert project.config.project_id == "demo"
    assert project.config.modules == ("LOGIN", "CART")
    assert project.entity_count() == 3
    assert set(project.sources) == {"UI-LOGIN-02"}
    assert set(project.testpoints) == {"TP-LOGIN-005"}
    assert set(project.cases) == {"TC-LOGIN-003"}
    case = project.cases["TC-LOGIN-003"]
    assert case.automation.status is AutomationStatus.DONE
    assert case.automation.script is not None
    assert case.automation.script.file == "scripts/test_login.py"
    assert case.automation.script.nodeid == "test_lock_after_5_failures"
    assert project.testpoints["TP-LOGIN-005"].sources == ("UI-LOGIN-02",)


def test_valid_project_reports_no_errors() -> None:
    assert collect_errors(FIXTURES / "valid_project") == ()


def test_valid_project_script_carries_the_case_marker() -> None:
    script = FIXTURES / "valid_project" / "scripts" / "test_login.py"
    text = script.read_text(encoding="utf-8")
    assert '@pytest.mark.case("TC-LOGIN-003")' in text
    assert "def test_lock_after_5_failures" in text


@pytest.mark.parametrize(
    ("fixture", "code", "field"),
    [
        ("invalid_bad_id", "TRACE_ID_INVALID", "id"),
        ("invalid_missing_evidence", "TRACE_EVIDENCE_MISSING", "evidence"),
        ("invalid_case_no_testpoints", "TRACE_DIRECT_REASON_MISSING", "direct_reason"),
        ("invalid_step_no_expected", "TRACE_STEP_EXPECTED_MISSING", "steps[0].expected"),
        ("invalid_enum", "TRACE_ENUM_INVALID", "priority"),
    ],
)
def test_invalid_fixture_raises_the_expected_code(
    fixture: str, code: str, field: str
) -> None:
    with pytest.raises(QaTraceError) as info:
        load_project(FIXTURES / fixture)
    error = info.value
    assert not isinstance(error, QaTraceGroupError)
    assert error.code == code
    assert error.field == field
    assert error.path is not None
    assert error.path.endswith(".yaml")
    assert str(FIXTURES / fixture) in error.path


def test_missing_project_directory_is_reported(tmp_path: Path) -> None:
    errors = collect_errors(tmp_path / "missing")
    assert [error.code for error in errors] == ["TRACE_PROJECT_INVALID"]


def test_missing_project_file_is_reported(tmp_path: Path) -> None:
    errors = collect_errors(tmp_path)
    assert [error.code for error in errors] == ["TRACE_PROJECT_INVALID"]


def test_project_file_requires_a_project_id(tmp_path: Path) -> None:
    root = _write_project(tmp_path / "proj", project_yaml="schema_version: 1\n")
    errors = collect_errors(root)
    assert [error.code for error in errors] == ["TRACE_FIELD_MISSING"]
    assert errors[0].field == "project_id"


def test_file_name_must_match_the_declared_id(tmp_path: Path) -> None:
    text = CASE_TEMPLATE.format(case_id="TC-LOGIN-001")
    root = _write_project(tmp_path / "proj", cases={"TC-LOGIN-002.yaml": text})
    with pytest.raises(QaTraceError) as info:
        load_project(root)
    assert info.value.code == "TRACE_FILE_ID_MISMATCH"


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    text = CASE_TEMPLATE.format(case_id="TC-LOGIN-001")
    root = _write_project(
        tmp_path / "proj",
        cases={"TC-LOGIN-001.yaml": text, "TC-LOGIN-001.yml": text},
    )
    with pytest.raises(QaTraceError) as info:
        load_project(root)
    assert info.value.code == "TRACE_ID_DUPLICATE"
    assert info.value.field == "id"


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    text = CASE_TEMPLATE.format(case_id="TC-LOGIN-001").replace(
        "title: 测试用例", "title: 第一个标题\ntitle: 第二个标题"
    )
    root = _write_project(tmp_path / "proj", cases={"TC-LOGIN-001.yaml": text})
    with pytest.raises(QaTraceError) as info:
        load_project(root)
    assert info.value.code == "TRACE_YAML_DUPLICATE_KEY"
    assert info.value.field == "title"


def test_entity_schema_version_is_enforced(tmp_path: Path) -> None:
    text = CASE_TEMPLATE.format(case_id="TC-LOGIN-001").replace(
        "schema_version: 1", "schema_version: 9"
    )
    root = _write_project(tmp_path / "proj", cases={"TC-LOGIN-001.yaml": text})
    with pytest.raises(QaTraceError) as info:
        load_project(root)
    assert info.value.code == "TRACE_SCHEMA_VERSION"


def test_every_error_is_collected(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        cases={"TC-LOGIN-ABC.yaml": CASE_TEMPLATE.format(case_id="TC-LOGIN-ABC")},
        sources={"UI-LOGIN-02.yaml": EVIDENCE_FREE_SOURCE},
    )
    errors = collect_errors(root)
    assert [error.code for error in errors] == [
        "TRACE_EVIDENCE_MISSING",
        "TRACE_ID_INVALID",
    ]
    with pytest.raises(QaTraceGroupError) as info:
        load_project(root)
    assert info.value.codes == ("TRACE_EVIDENCE_MISSING", "TRACE_ID_INVALID")
    assert "TRACE_EVIDENCE_MISSING" in info.value.format()
    assert "TRACE_ID_INVALID" in info.value.format()


def test_cli_check_prints_ok_for_a_valid_project(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["trace", "check", "--project", str(FIXTURES / "valid_project")]) == 0
    assert capsys.readouterr().out.strip() == "OK"


def test_cli_check_prints_errors_for_an_invalid_project(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["trace", "check", "--project", str(FIXTURES / "invalid_enum")]) == 1
    output = capsys.readouterr().out
    assert "TRACE_ENUM_INVALID" in output
    assert "priority" in output


def test_cli_check_reports_a_missing_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"
    # P1 extends the exit-code contract with 2 for an unusable input (plan
    # section 4); a missing project directory is an input failure, not a rule
    # violation.
    assert main(["trace", "check", "--project", str(missing)]) == 2
    assert "TRACE_PROJECT_INVALID" in capsys.readouterr().out
