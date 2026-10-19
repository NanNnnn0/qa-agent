"""Tests for the P2 static marker lint (spec section 3, rule 9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_trace.check import CheckResult, run_check
from qa_trace.cli import main
from qa_trace.markers import (
    MARKER_MISMATCH,
    MARKER_ORPHAN,
    MARKER_UNKNOWN,
    MARKER_UNREADABLE,
    scan_markers,
)

FIXTURES = Path(__file__).parent / "fixtures"

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
"""

TESTPOINT_TEMPLATE = """\
schema_version: 1
id: TP-LOGIN-005
title: 连续失败计数与锁定阈值
sources:
  - UI-LOGIN-02
method: boundary
risk: high
status: reviewed
"""

CASE_TEMPLATE = """\
schema_version: 1
id: TC-LOGIN-001
title: 手工构造的用例
testpoints:
  - TP-LOGIN-005
priority: P1
type: functional
status: reviewed
steps:
  - action: 连续输错密码 5 次
    expected: 提示“账号锁定 15 分钟”，HTTP 状态码 423
automation:
  status: done
  script: {script}
"""


def _write_project(root: Path, *, script: str, binding: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(
        "schema_version: 1\nproject_id: hand\n", encoding="utf-8"
    )
    (root / "sources").mkdir(exist_ok=True)
    (root / "testpoints").mkdir(exist_ok=True)
    (root / "cases").mkdir(exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "sources" / "UI-LOGIN-02.yaml").write_text(
        SOURCE_TEMPLATE, encoding="utf-8"
    )
    (root / "testpoints" / "TP-LOGIN-005.yaml").write_text(
        TESTPOINT_TEMPLATE, encoding="utf-8"
    )
    (root / "cases" / "TC-LOGIN-001.yaml").write_text(
        CASE_TEMPLATE.format(script=binding), encoding="utf-8"
    )
    (root / "scripts" / "test_login.py").write_text(script, encoding="utf-8")
    return root


def _codes(result: CheckResult) -> list[str]:
    return [item.code for item in result.diagnostics]


def test_scan_reads_classes_multiple_ids_and_plain_functions(tmp_path: Path) -> None:
    script = tmp_path / "test_login.py"
    script.write_text(
        """\
import pytest


class TestLogin:
    @pytest.mark.case("TC-LOGIN-001", "TC-LOGIN-002")
    def test_multi(self) -> None:
        pass

    def test_plain(self) -> None:
        pass


@pytest.mark.case("TC-LOGIN-003")
def test_single() -> None:
    pass
""",
        encoding="utf-8",
    )
    scan = scan_markers(script)
    assert scan.error is None
    assert scan.case_ids == ("TC-LOGIN-001", "TC-LOGIN-002", "TC-LOGIN-003")
    assert [marker.nodeid for marker in scan.markers] == [
        "TestLogin::test_multi",
        "test_single",
    ]
    assert scan.markers_for("TC-LOGIN-002")[0].nodeid == "TestLogin::test_multi"
    assert scan.nodeids_for("TC-LOGIN-003") == ("test_single",)
    assert set(scan.defined_nodeids) == {
        "TestLogin::test_multi",
        "TestLogin::test_plain",
        "test_single",
    }


def test_scan_flags_invalid_and_empty_marker_arguments(tmp_path: Path) -> None:
    script = tmp_path / "test_login.py"
    script.write_text(
        """\
import pytest


@pytest.mark.case("not-a-case")
def test_bad_id() -> None:
    pass


@pytest.mark.case(1)
def test_non_literal() -> None:
    pass


@pytest.mark.case
def test_bare() -> None:
    pass


@pytest.mark.case()
def test_empty() -> None:
    pass


@pytest.mark.case(id="TC-LOGIN-001")
def test_keyword() -> None:
    pass
""",
        encoding="utf-8",
    )
    scan = scan_markers(script)
    assert scan.error is None
    assert scan.case_ids == ()
    assert [marker.nodeid for marker in scan.markers] == [
        "test_bad_id",
        "test_non_literal",
        "test_bare",
        "test_empty",
        "test_keyword",
    ]
    assert all(marker.invalid for marker in scan.markers)
    assert "'not-a-case' is not a valid case ID" in scan.markers[0].invalid
    assert "keyword argument 'id' is not supported" in scan.markers[4].invalid


def test_scan_reports_an_unparseable_file(tmp_path: Path) -> None:
    script = tmp_path / "test_broken.py"
    script.write_text("def broken(:\n", encoding="utf-8")
    scan = scan_markers(script)
    assert scan.markers == ()
    assert scan.error is not None
    assert "cannot parse the file" in scan.error


def test_matching_marker_is_clean() -> None:
    result = run_check(FIXTURES / "marker_ok")
    assert result.diagnostics == ()
    assert result.exit_code == 0


def test_a_missing_marker_is_an_error() -> None:
    result = run_check(FIXTURES / "marker_missing")
    assert [item.code for item in result.diagnostics] == [MARKER_MISMATCH]
    diagnostic = result.diagnostics[0]
    assert diagnostic.path == "cases/TC-LOGIN-003.yaml"
    assert diagnostic.field == "automation.script"
    assert diagnostic.entity_id == "TC-LOGIN-003"
    assert "@pytest.mark.case('TC-LOGIN-003')" in diagnostic.message
    assert result.exit_code == 1


def test_extra_markers_are_orphan_and_unknown_errors() -> None:
    result = run_check(FIXTURES / "marker_extra")
    assert [item.code for item in result.diagnostics] == [
        MARKER_ORPHAN,
        MARKER_UNKNOWN,
        MARKER_UNKNOWN,
    ]
    orphan = result.diagnostics[0]
    assert orphan.path == "scripts/test_login.py"
    assert orphan.field == "test_manual_case_has_a_marker"
    assert orphan.entity_id == "TC-LOGIN-004"
    assert "not automated" in orphan.message
    unknown = {item.field: item for item in result.diagnostics[1:]}
    assert unknown["test_unknown_case_marker"].entity_id == "TC-LOGIN-999"
    assert "not a case of this project" in unknown["test_unknown_case_marker"].message
    assert "not a valid case ID" in unknown["test_invalid_case_marker"].message
    assert result.exit_code == 1


def test_a_marker_on_the_wrong_node_is_a_mismatch(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "proj",
        script="""\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_other() -> None:
    pass


def test_bound() -> None:
    pass
""",
        binding="scripts/test_login.py::test_bound",
    )
    result = run_check(project)
    assert [item.code for item in result.diagnostics] == [MARKER_MISMATCH]
    diagnostic = result.diagnostics[0]
    assert "test_other" in diagnostic.message
    assert "test_bound" in diagnostic.message


def test_an_unparseable_script_is_reported_once(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "proj",
        script="def broken(:\n",
        binding="scripts/test_login.py::test_bound",
    )
    result = run_check(project)
    assert [item.code for item in result.diagnostics] == [MARKER_UNREADABLE]
    diagnostic = result.diagnostics[0]
    assert diagnostic.path == "scripts/test_login.py"
    assert "cannot parse the file" in diagnostic.message


def test_a_dangling_script_is_not_double_reported() -> None:
    result = run_check(FIXTURES / "invalid_dangling_script")
    codes = _codes(result)
    assert "TRACE_REF_MISSING" in codes
    assert MARKER_MISMATCH not in codes
    assert MARKER_UNREADABLE not in codes


def test_cli_exits_one_on_a_marker_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["trace", "check", "--project", str(FIXTURES / "marker_missing")]
    )
    assert exit_code == 1
    output = capsys.readouterr().out
    assert MARKER_MISMATCH in output
    assert "automation.script" in output
