"""Tests for the P1 metrics and the ``qa trace report`` payload."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from qa_trace.check import run_check
from qa_trace.cli import main
from qa_trace.report import REPORT_VERSION, build_report, render_report

FIXTURES = Path(__file__).parent / "fixtures"

METRICS = FIXTURES / "metrics_project"
STALE = FIXTURES / "stale_propagation"

CASE_TEMPLATE = """\
schema_version: 1
id: {case_id}
title: 手工构造的用例
testpoints:
  - TP-LOGIN-005
priority: P1
type: functional
status: {status}
steps:
  - action: 连续输错密码 5 次
    expected: 提示“账号锁定 15 分钟”，HTTP 状态码 423
automation:
  status: {automation}
"""

SOURCE_TEMPLATE = """\
schema_version: 1
id: {source_id}
type: ui
title: 登录失败 5 次触发账号锁定
evidence:
  - type: ui_capture
    locator: artifacts/ui/login-lock-5x.png
url: /login
app_version: 3.4.1
observed_at: 2026-10-18
confidence: confirmed
status: {status}
"""

TESTPOINT_TEMPLATE = """\
schema_version: 1
id: {testpoint_id}
title: 连续失败计数与锁定阈值
sources:
  - {source_id}
method: boundary
risk: high
status: reviewed
"""


def _write_project(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text("schema_version: 1\nproject_id: hand\n", encoding="utf-8")
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _tree_digest(root: Path) -> dict[str, str]:
    digest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digest


def _ratio(report: dict[str, Any], block: str, key: str) -> dict[str, Any]:
    return report["coverage"][block][key]


def test_metrics_are_the_exact_known_numbers() -> None:
    report = build_report(run_check(METRICS))
    assert report["valid"] is True
    # 1 of 2 active requirements is covered by a reviewed case through a reviewed TP.
    assert _ratio(report, "requirement", "reviewed") == {
        "numerator": 1,
        "denominator": 2,
        "percent": 50.0,
    }
    # 1 of 2 active UI/API sources is covered; the API source has no downstream.
    assert _ratio(report, "behavior", "reviewed") == {
        "numerator": 1,
        "denominator": 2,
        "percent": 50.0,
    }
    # 1 of 3 reviewed cases is automated with a resolvable script.
    assert _ratio(report, "automation", "reviewed") == {
        "numerator": 1,
        "denominator": 3,
        "percent": 33.33,
    }
    # No case in the library is orphaned.
    assert _ratio(report, "orphan", "library") == {
        "numerator": 0,
        "denominator": 4,
        "percent": 0.0,
    }
    assert report["requirement_gap_count"] == 1
    assert report["requirement_gaps"]["cases_without_requirement_root"] == ["TC-LOGIN-004"]
    assert report["requirement_gaps"]["uncovered_requirements"] == ["REQ-LOGIN-02"]
    assert report["dangling_count"] == 0
    assert report["counts"]["dangling_references"] == 0


def test_dead_assets_are_reported_per_bucket() -> None:
    report = build_report(run_check(METRICS))
    dead = report["dead_assets"]
    assert dead["sources_without_downstream"] == ["API-LOGIN-01"]
    assert dead["deprecated_cases"] == []
    assert dead["count"] == 1
    assert dead["count_is_partial"] is True
    # Manual P0 aging needs a status-change timestamp that P1 does not record.
    assert dead["manual_p0_cases"]["status"] == "unknown"
    assert dead["manual_p0_cases"]["candidates"] == ["TC-LOGIN-002"]


def test_the_four_numbers_are_never_merged() -> None:
    report = build_report(run_check(METRICS))
    assert set(report["coverage"]) == {"requirement", "behavior", "automation", "orphan"}
    for block in report["coverage"].values():
        assert isinstance(block, dict)
        assert block["label"] in {"requirement", "behavior", "automation", "orphan"}
    assert "overall" not in report
    assert "coverage_percent" not in report
    assert "total_coverage" not in report


def test_only_reviewed_cases_count_for_coverage() -> None:
    report = build_report(run_check(METRICS))
    # TC-LOGIN-003 is a reviewed-path candidate on paper but is still draft.
    assert "REQ-LOGIN-02" in report["coverage"]["requirement"]["uncovered"]
    assert report["counts"]["reviewed_cases"] == 3
    assert report["counts"]["cases"] == 4


def test_reviewed_coverage_requires_a_reviewed_testpoint(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        {
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(
                source_id="UI-LOGIN-02", status="active"
            ),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(
                testpoint_id="TP-LOGIN-005", source_id="UI-LOGIN-02"
            ).replace("status: reviewed", "status: draft"),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", status="reviewed", automation="manual"
            ),
        },
    )
    report = build_report(run_check(root))
    assert _ratio(report, "behavior", "reviewed") == {
        "numerator": 0,
        "denominator": 1,
        "percent": 0.0,
    }


def test_unconfirmed_sources_stay_in_the_denominator(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        {
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(
                source_id="UI-LOGIN-02", status="active"
            ).replace("confidence: confirmed", "confidence: observed"),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(
                testpoint_id="TP-LOGIN-005", source_id="UI-LOGIN-02"
            ),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", status="reviewed", automation="manual"
            ),
        },
    )
    report = build_report(run_check(root))
    block = report["coverage"]["behavior"]
    assert block["reviewed"] == {"numerator": 0, "denominator": 1, "percent": 0.0}
    assert block["unconfirmed_sources"] == ["UI-LOGIN-02"]


def test_deprecated_assets_are_excluded_from_metrics(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        {
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(
                source_id="UI-LOGIN-02", status="active"
            ),
            "sources/UI-LOGIN-03.yaml": SOURCE_TEMPLATE.format(
                source_id="UI-LOGIN-03", status="deprecated"
            ),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(
                testpoint_id="TP-LOGIN-005", source_id="UI-LOGIN-02"
            ),
            "testpoints/TP-LOGIN-006.yaml": TESTPOINT_TEMPLATE.format(
                testpoint_id="TP-LOGIN-006", source_id="UI-LOGIN-03"
            ),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", status="reviewed", automation="manual"
            ),
            "cases/TC-LOGIN-002.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-002", status="reviewed", automation="manual"
            ).replace("TP-LOGIN-005", "TP-LOGIN-006"),
            "cases/TC-LOGIN-003.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-003", status="deprecated", automation="manual"
            ),
        },
    )
    report = build_report(run_check(root))
    # The deprecated source leaves the behavior denominator, so it is 1, not 2.
    assert _ratio(report, "behavior", "reviewed") == {
        "numerator": 1,
        "denominator": 1,
        "percent": 100.0,
    }
    # The deprecated case leaves the orphan denominator, so it is 2, not 3.
    assert _ratio(report, "orphan", "library") == {
        "numerator": 0,
        "denominator": 2,
        "percent": 0.0,
    }
    assert report["dead_assets"]["deprecated_cases"] == ["TC-LOGIN-003"]
    assert report["dead_assets"]["sources_without_downstream"] == []


def test_stale_source_separates_reviewed_from_current_valid() -> None:
    report = build_report(run_check(STALE))
    behavior = report["coverage"]["behavior"]
    assert behavior["reviewed"] == {"numerator": 1, "denominator": 1, "percent": 100.0}
    assert behavior["current_valid"] == {"numerator": 0, "denominator": 1, "percent": 0.0}
    assert report["needs_recheck"] == [
        {"case_id": "TC-LOGIN-003", "reasons": [{"source_id": "UI-LOGIN-02", "reason": "stale"}]}
    ]


def test_zero_denominator_is_null_and_renders_as_na() -> None:
    report = build_report(run_check(STALE))
    requirement = report["coverage"]["requirement"]
    assert requirement["reviewed"] == {"numerator": 0, "denominator": 0, "percent": None}
    text = render_report(report)
    assert "0/0 = N/A" in text
    assert "100.00%" in text


def test_automation_rate_counts_only_resolvable_scripts(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path / "proj",
        {
            "sources/UI-LOGIN-02.yaml": SOURCE_TEMPLATE.format(
                source_id="UI-LOGIN-02", status="active"
            ),
            "testpoints/TP-LOGIN-005.yaml": TESTPOINT_TEMPLATE.format(
                testpoint_id="TP-LOGIN-005", source_id="UI-LOGIN-02"
            ),
            "cases/TC-LOGIN-001.yaml": CASE_TEMPLATE.format(
                case_id="TC-LOGIN-001", status="reviewed", automation="done"
            ).replace("status: done", "status: done\n  script: scripts/test_login.py::test_x"),
            # P2 rule 9: the automated case must be declared back by the script.
            "scripts/test_login.py": (
                'import pytest\n\n\n@pytest.mark.case("TC-LOGIN-001")\n'
                "def test_x():\n    assert True\n"
            ),
        },
    )
    report = build_report(run_check(root))
    automation = report["coverage"]["automation"]
    assert automation["reviewed"] == {"numerator": 1, "denominator": 1, "percent": 100.0}
    assert automation["provisional"] is True
    assert automation["unresolved_scripts"] == []


def test_report_shape_is_stable_across_runs() -> None:
    first = build_report(run_check(METRICS))
    second = build_report(run_check(METRICS))
    assert first == second
    assert first["report_version"] == REPORT_VERSION
    assert set(first) == {
        "report_version",
        "tool",
        "project",
        "valid",
        "counts",
        "coverage",
        "requirement_gaps",
        "requirement_gap_count",
        "dangling_count",
        "dead_assets",
        "needs_recheck",
        "metrics_suppressed",
        "diagnostics",
    }
    assert json.loads(json.dumps(first, ensure_ascii=False)) == first


def test_metrics_are_suppressed_for_an_invalid_library() -> None:
    report = build_report(run_check(FIXTURES / "invalid_dangling_source"))
    assert report["valid"] is False
    assert report["coverage"] is None
    assert report["requirement_gaps"] is None
    assert report["dead_assets"] is None
    assert report["dangling_count"] == 1
    assert "structural error" in report["metrics_suppressed"]
    assert report["diagnostics"]["counts"]["error"] == 2


def test_reporting_never_writes_back_to_the_library() -> None:
    before = _tree_digest(METRICS)
    result = run_check(METRICS)
    build_report(result)
    render_report(build_report(result))
    assert _tree_digest(METRICS) == before


def test_cli_report_prints_the_four_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["trace", "report", "--project", str(METRICS)]) == 0
    output = capsys.readouterr().out
    assert "qa-trace report: metrics-demo (valid)" in output
    assert "requirement cover.  reviewed 1/2 = 50.00%" in output
    assert "behavior cover.     reviewed 1/2 = 50.00%" in output
    assert "automation rate     reviewed 1/3 = 33.33%" in output
    assert "orphan rate         0/4 = 0.00%" in output


def test_cli_report_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["trace", "report", "--project", str(METRICS), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["coverage"]["requirement"]["reviewed"]["percent"] == 50.0
    assert payload["project"]["id"] == "metrics-demo"
    assert payload["tool"]["version"].startswith("0.")


def test_cli_report_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["trace", "report", "--project", str(FIXTURES / "valid_project")]) == 0
    capsys.readouterr()

    assert main(["trace", "report", "--project", str(FIXTURES / "invalid_orphan_case")]) == 1
    invalid = capsys.readouterr().out
    assert "(INVALID)" in invalid
    assert "suppressed" in invalid

    assert main(["trace", "report", "--project", str(tmp_path / "missing")]) == 2
    assert "TRACE_PROJECT_INVALID" in capsys.readouterr().out


def test_cli_report_json_is_valid_even_when_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(
        ["trace", "report", "--project", str(FIXTURES / "invalid_dangling_source"), "--json"]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["dangling_count"] == 1
