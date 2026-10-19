"""Unit tests for the entity models and their required-field rules."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from qa_trace.errors import (
    DirectReasonMissingError,
    EnumValueError,
    EvidenceMissingError,
    FieldInvalidError,
    FieldMissingError,
    IdTypeMismatchError,
    LinkMissingError,
    SchemaVersionError,
    ScriptBindingError,
    StepExpectedMissingError,
)
from qa_trace.models import (
    AutomationStatus,
    Case,
    CaseResult,
    Confidence,
    EntityStatus,
    EvidenceType,
    Method,
    Outcome,
    Priority,
    ReviewStatus,
    Risk,
    Run,
    ScriptBinding,
    Source,
    SourceType,
    validate_schema_version,
)

# Aliased so pytest does not mistake the model for a test class.
from qa_trace.models import TestPoint as PointModel


def without(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return ``data`` with ``keys`` removed, for missing-field tests."""
    for key in keys:
        data.pop(key, None)
    return data


def source_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "UI-LOGIN-02",
        "type": "ui",
        "title": "登录失败 5 次触发账号锁定",
        "url": "/login",
        "app_version": "3.4.1",
        "observed_at": "2026-10-18",
        "evidence": [{"type": "ui_capture", "locator": "artifacts/ui/login-lock.png"}],
    }
    data.update(overrides)
    return data


def point_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "TP-LOGIN-005",
        "title": "连续失败计数与锁定阈值",
        "sources": ["UI-LOGIN-02"],
        "method": "boundary",
        "risk": "high",
        "status": "reviewed",
    }
    data.update(overrides)
    return data


def case_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "TC-LOGIN-003",
        "title": "密码连续错误 5 次锁定账号",
        "testpoints": ["TP-LOGIN-005"],
        "priority": "P1",
        "type": "functional",
        "status": "reviewed",
        "steps": [
            {"action": "输入 qa01 与错误密码后提交", "expected": "剩余尝试次数显示 4"},
            {"action": "重复提交至第 5 次", "expected": "HTTP 状态码 423"},
        ],
        "automation": {"status": "done", "script": "tests/test_login.py::test_lock"},
    }
    data.update(overrides)
    return data


def result_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "case_id": "TC-LOGIN-003",
        "nodeid": "tests/test_login.py::test_lock",
        "outcome": "passed",
    }
    data.update(overrides)
    return data


def test_source_from_dict_reads_ui_observation() -> None:
    source = Source.from_dict(source_data())
    assert source.id == "UI-LOGIN-02"
    assert source.type is SourceType.UI
    assert source.status is EntityStatus.ACTIVE
    assert source.confidence is Confidence.OBSERVED
    assert source.observed_at == date(2026, 10, 18)
    assert source.stale is False
    assert source.evidence[0].type is EvidenceType.UI_CAPTURE


def test_source_requires_evidence() -> None:
    with pytest.raises(EvidenceMissingError) as info:
        Source.from_dict(without(source_data(), "evidence"))
    assert info.value.code == "TRACE_EVIDENCE_MISSING"
    assert info.value.field == "evidence"


def test_source_rejects_an_empty_evidence_list() -> None:
    with pytest.raises(EvidenceMissingError):
        Source.from_dict(source_data(evidence=[]))


def test_ui_source_requires_url_version_and_date() -> None:
    for key in ("url", "app_version", "observed_at"):
        with pytest.raises(FieldMissingError) as info:
            Source.from_dict(without(source_data(), key))
        assert info.value.field == key


def test_source_type_must_match_the_id_prefix() -> None:
    with pytest.raises(IdTypeMismatchError):
        Source.from_dict(source_data(id="API-LOGIN-01"))


def test_source_rejects_an_unknown_type() -> None:
    with pytest.raises(EnumValueError) as info:
        Source.from_dict(source_data(type="screen"))
    assert info.value.code == "TRACE_ENUM_INVALID"
    assert info.value.field == "type"


def test_evidence_entry_requires_a_locator() -> None:
    with pytest.raises(FieldMissingError) as info:
        Source.from_dict(source_data(evidence=[{"type": "issue"}]))
    assert info.value.field == "evidence[0].locator"


def test_evidence_sha256_must_be_a_digest() -> None:
    evidence = [{"type": "ui_capture", "locator": "x.png", "sha256": "abc"}]
    with pytest.raises(FieldInvalidError) as info:
        Source.from_dict(source_data(evidence=evidence))
    assert info.value.field == "evidence[0].sha256"


def test_unknown_keys_are_preserved_in_extra() -> None:
    source = Source.from_dict(source_data(future_field=1))
    assert source.extra == {"future_field": 1}


def test_schema_version_is_enforced() -> None:
    with pytest.raises(SchemaVersionError) as info:
        Source.from_dict(source_data(schema_version=2))
    assert info.value.code == "TRACE_SCHEMA_VERSION"
    assert info.value.field == "schema_version"
    with pytest.raises(FieldMissingError):
        Source.from_dict(without(source_data(), "schema_version"))
    with pytest.raises(FieldInvalidError):
        validate_schema_version("1")


def test_testpoint_from_dict() -> None:
    testpoint = PointModel.from_dict(point_data())
    assert testpoint.id == "TP-LOGIN-005"
    assert testpoint.method is Method.BOUNDARY
    assert testpoint.risk is Risk.HIGH
    assert testpoint.status is ReviewStatus.REVIEWED
    assert testpoint.sources == ("UI-LOGIN-02",)


def test_testpoint_requires_at_least_one_source() -> None:
    with pytest.raises(FieldMissingError) as info:
        PointModel.from_dict(point_data(sources=[]))
    assert info.value.field == "sources"


def test_testpoint_rejects_an_unknown_method() -> None:
    with pytest.raises(EnumValueError) as info:
        PointModel.from_dict(point_data(method="guess"))
    assert info.value.field == "method"


def test_testpoint_sources_must_be_source_ids() -> None:
    with pytest.raises(IdTypeMismatchError) as info:
        PointModel.from_dict(point_data(sources=["TC-LOGIN-003"]))
    assert info.value.field == "sources[0]"


def test_case_from_dict() -> None:
    case = Case.from_dict(case_data())
    assert case.id == "TC-LOGIN-003"
    assert case.priority is Priority.P1
    assert case.status is ReviewStatus.REVIEWED
    assert [step.expected for step in case.steps] == [
        "剩余尝试次数显示 4",
        "HTTP 状态码 423",
    ]
    assert case.automation.status is AutomationStatus.DONE
    assert case.automation.script is not None
    assert case.automation.script.file == "tests/test_login.py"
    assert case.automation.script.script == "tests/test_login.py::test_lock"


def test_case_requires_steps() -> None:
    with pytest.raises(FieldMissingError) as info:
        Case.from_dict(without(case_data(), "steps"))
    assert info.value.field == "steps"
    with pytest.raises(FieldMissingError):
        Case.from_dict(case_data(steps=[]))


def test_case_step_requires_expected() -> None:
    data = case_data()
    del data["steps"][1]["expected"]
    with pytest.raises(StepExpectedMissingError) as info:
        Case.from_dict(data)
    assert info.value.code == "TRACE_STEP_EXPECTED_MISSING"
    assert info.value.field == "steps[1].expected"


def test_case_step_expected_must_not_be_blank() -> None:
    data = case_data()
    data["steps"][0]["expected"] = "   "
    with pytest.raises(StepExpectedMissingError) as info:
        Case.from_dict(data)
    assert info.value.field == "steps[0].expected"


def test_case_requires_testpoints_or_sources() -> None:
    with pytest.raises(LinkMissingError) as info:
        Case.from_dict(case_data(testpoints=[]))
    assert info.value.code == "TRACE_LINK_MISSING"


def test_direct_source_requires_direct_reason() -> None:
    with pytest.raises(DirectReasonMissingError) as info:
        Case.from_dict(case_data(testpoints=[], sources=["UI-LOGIN-02"], risk="high"))
    assert info.value.code == "TRACE_DIRECT_REASON_MISSING"
    assert info.value.field == "direct_reason"


def test_direct_source_without_testpoint_requires_risk() -> None:
    with pytest.raises(FieldMissingError) as info:
        Case.from_dict(
            case_data(testpoints=[], sources=["UI-LOGIN-02"], direct_reason="回归补充")
        )
    assert info.value.field == "risk"


def test_direct_source_case_is_accepted() -> None:
    case = Case.from_dict(
        case_data(
            testpoints=[],
            sources=["UI-LOGIN-02"],
            direct_reason="回归补充用例，无独立测试点",
            risk="medium",
        )
    )
    assert case.testpoints == ()
    assert case.sources == ("UI-LOGIN-02",)
    assert case.risk is Risk.MEDIUM


def test_case_automation_done_requires_a_script() -> None:
    with pytest.raises(FieldMissingError) as info:
        Case.from_dict(case_data(automation={"status": "done"}))
    assert info.value.field == "automation.script"


def test_case_rejects_a_bad_priority() -> None:
    with pytest.raises(EnumValueError) as info:
        Case.from_dict(case_data(priority="P9"))
    assert info.value.field == "priority"


def test_case_rejects_a_bad_automation_status() -> None:
    with pytest.raises(EnumValueError) as info:
        Case.from_dict(case_data(automation={"status": "finished"}))
    assert info.value.field == "automation.status"


def test_case_testpoints_must_be_testpoint_ids() -> None:
    with pytest.raises(IdTypeMismatchError) as info:
        Case.from_dict(case_data(testpoints=["TC-LOGIN-003"]))
    assert info.value.field == "testpoints[0]"


def test_script_binding_requires_a_nodeid() -> None:
    with pytest.raises(ScriptBindingError) as info:
        ScriptBinding.parse("tests/test_login.py")
    assert info.value.code == "TRACE_SCRIPT_INVALID"
    with pytest.raises(ScriptBindingError):
        ScriptBinding.parse("tests/test_login.py::")
    with pytest.raises(ScriptBindingError):
        ScriptBinding.parse("::test_lock")


def test_script_binding_round_trips_class_and_parametrised_nodeids() -> None:
    binding = ScriptBinding.parse("tests/test_login.py::TestLogin::test_lock[1]")
    assert binding.file == "tests/test_login.py"
    assert binding.nodeid == "TestLogin::test_lock[1]"
    assert binding.script == "tests/test_login.py::TestLogin::test_lock[1]"


def test_case_result_defaults() -> None:
    result = CaseResult.from_dict(result_data())
    assert result.case_id == "TC-LOGIN-003"
    assert result.outcome is Outcome.PASSED
    assert result.attempt == 1


def test_case_result_requires_failure_stage_for_failures() -> None:
    with pytest.raises(FieldMissingError) as info:
        CaseResult.from_dict(result_data(outcome="failed"))
    assert info.value.field == "failure_stage"


def test_case_result_rejects_a_bad_outcome() -> None:
    with pytest.raises(EnumValueError) as info:
        CaseResult.from_dict(result_data(outcome="broken"))
    assert info.value.field == "outcome"


def test_case_result_rejects_a_zero_attempt() -> None:
    with pytest.raises(FieldInvalidError) as info:
        CaseResult.from_dict(result_data(attempt=0))
    assert info.value.field == "attempt"


def test_run_from_dict() -> None:
    run = Run.from_dict(
        {
            "run_id": "2026-10-18T10-00-00Z",
            "project_id": "demo",
            "started_at": "2026-10-18T10:00:00Z",
            "finished_at": "2026-10-18T10:05:00Z",
            "environment": "local",
            "results": [result_data()],
        }
    )
    assert run.started_at == datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
    assert len(run.results) == 1


def test_run_rejects_finished_before_started() -> None:
    with pytest.raises(FieldInvalidError) as info:
        Run.from_dict(
            {
                "run_id": "r1",
                "project_id": "demo",
                "started_at": "2026-10-18T10:05:00Z",
                "finished_at": "2026-10-18T10:00:00Z",
            }
        )
    assert info.value.field == "finished_at"
