"""Tests for the P2 pytest plugin: marker validation and run manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from qa_trace.models import Outcome, Run

PLUGIN = "qa_trace.pytest_plugin"

SOURCE = """\
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

TESTPOINT = """\
schema_version: 1
id: TP-LOGIN-005
title: 连续失败计数与锁定阈值
sources:
  - UI-LOGIN-02
method: boundary
risk: high
status: reviewed
"""

CASE = """\
schema_version: 1
id: {case_id}
title: 插件测试用例 {case_id}
testpoints:
  - TP-LOGIN-005
priority: P1
type: functional
status: reviewed
steps:
  - action: 连续输错密码 5 次
    expected: 提示“账号锁定 15 分钟”，HTTP 状态码 423
automation:
  status: manual
"""

CASE_IDS: tuple[str, ...] = tuple(f"TC-LOGIN-{index:03d}" for index in range(1, 8))

SAMPLE = """\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_pass() -> None:
    assert True


@pytest.mark.case("TC-LOGIN-002")
def test_fail() -> None:
    assert 1 == 2, "boom failure"


@pytest.mark.case("TC-LOGIN-003")
@pytest.mark.skip(reason="not ready")
def test_skip() -> None:
    pass


@pytest.fixture
def broken_fixture():
    raise RuntimeError("fixture boom")


@pytest.mark.case("TC-LOGIN-004")
def test_error(broken_fixture) -> None:
    pass


@pytest.mark.case("TC-LOGIN-005")
@pytest.mark.parametrize("value", [1, 2])
def test_param(value: int) -> None:
    assert value == 1


@pytest.mark.case("TC-LOGIN-006")
@pytest.mark.xfail(reason="known bug")
def test_xfail() -> None:
    assert False


@pytest.mark.case("TC-LOGIN-007")
@pytest.mark.xfail(reason="unexpectedly fixed")
def test_xpass() -> None:
    assert True
"""


def _write_library(root: Path, case_ids: Sequence[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(
        "schema_version: 1\nproject_id: plugin-demo\n", encoding="utf-8"
    )
    for name, text in (
        ("sources/UI-LOGIN-02.yaml", SOURCE),
        ("testpoints/TP-LOGIN-005.yaml", TESTPOINT),
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / "cases").mkdir(exist_ok=True)
    for case_id in case_ids:
        (root / "cases" / f"{case_id}.yaml").write_text(
            CASE.format(case_id=case_id), encoding="utf-8"
        )
    return root


def _manifest(run_dir: Path) -> dict[str, Any]:
    manifests = sorted(run_dir.glob("*/manifest.json"))
    assert len(manifests) == 1, manifests
    return json.loads(manifests[0].read_text(encoding="utf-8"))


def _by_leaf(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["nodeid"].split("::")[-1]: row for row in rows}


def test_plugin_records_a_manifest_with_every_outcome(
    pytester: pytest.Pytester,
) -> None:
    library = _write_library(pytester.path / "library", CASE_IDS)
    run_dir = pytester.path / "runs"
    pytester.makepyfile(test_sample=SAMPLE)

    result = pytester.runpytest(
        "-p",
        PLUGIN,
        "--qa-project",
        str(library),
        "--qa-run-dir",
        str(run_dir),
        "test_sample.py",
    )
    result.assert_outcomes(
        passed=2, failed=2, skipped=1, errors=1, xfailed=1, xpassed=1
    )
    assert "qa-trace run manifest:" in result.stdout.str()

    manifest = _manifest(run_dir)
    assert manifest["manifest_version"] == 1
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", manifest["run_id"])
    assert manifest["status"] == "complete"
    assert manifest["exitstatus"] == 1
    assert manifest["project_id"] == "plugin-demo"
    assert manifest["project_path"] == str(library)
    datetime.fromisoformat(manifest["started_at"])
    datetime.fromisoformat(manifest["finished_at"])
    assert manifest["tool"]["name"] == "qa_trace"
    commit = manifest["code_commit"]
    assert commit is None or re.fullmatch(r"[0-9a-f]{40}", commit)

    snapshot = manifest["asset_snapshot"]
    assert set(snapshot["cases"]) == set(CASE_IDS)
    assert snapshot["relations"]["TC-LOGIN-001"] == {
        "testpoints": ["TP-LOGIN-005"],
        "sources": [],
    }
    # P3 adds the testpoint -> source hop so a failure can be traced to a source
    # from the run-time snapshot instead of today's library.
    assert snapshot["testpoint_sources"] == {"TP-LOGIN-005": ["UI-LOGIN-02"]}
    script_files = manifest["script_digest"]["files"]
    assert len(script_files) == 1
    assert next(iter(script_files)).endswith("test_sample.py")
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["script_digest"]["sha256"])

    results = _by_leaf(manifest["results"])
    assert len(manifest["results"]) == 8
    assert results["test_pass"]["case_id"] == "TC-LOGIN-001"
    assert results["test_pass"]["outcome"] == "passed"
    assert results["test_pass"]["failure_stage"] is None
    assert results["test_pass"]["error_summary"] is None
    assert results["test_fail"]["outcome"] == "failed"
    assert results["test_fail"]["failure_stage"] == "call"
    assert "boom failure" in results["test_fail"]["error_summary"]
    assert results["test_skip"]["outcome"] == "skipped"
    assert results["test_skip"]["failure_stage"] is None
    assert results["test_error"]["outcome"] == "error"
    assert results["test_error"]["failure_stage"] == "setup"
    assert "fixture boom" in results["test_error"]["error_summary"]
    assert results["test_param[1]"]["outcome"] == "passed"
    assert results["test_param[2]"]["outcome"] == "failed"
    assert results["test_xfail"]["outcome"] == "xfailed"
    assert results["test_xpass"]["outcome"] == "xpassed"

    cases = {row["case_id"]: row for row in manifest["cases"]}
    assert len(cases) == 7
    assert cases["TC-LOGIN-001"]["outcome"] == "passed"
    assert cases["TC-LOGIN-005"]["outcome"] == "failed"
    assert cases["TC-LOGIN-005"]["counts"]["passed"] == 1
    assert cases["TC-LOGIN-005"]["counts"]["failed"] == 1
    assert cases["TC-LOGIN-005"]["attempts"] == 2
    assert cases["TC-LOGIN-006"]["outcome"] == "xfailed"
    assert cases["TC-LOGIN-007"]["outcome"] == "xpassed"

    assert manifest["summary"]["collected"] == 8
    assert manifest["summary"]["results"] == 8
    assert manifest["summary"]["cases"] == 7
    assert manifest["summary"]["outcomes"] == {
        "cancelled": 0,
        "skipped": 1,
        "xfailed": 1,
        "passed": 2,
        "xpassed": 1,
        "failed": 2,
        "error": 1,
    }
    assert manifest["unmapped_nodeids"] == []

    # The P0 Run model must be able to read the manifest back.
    run = Run.from_dict(manifest)
    assert len(run.results) == 8
    assert {result.outcome for result in run.results} == {
        Outcome.PASSED,
        Outcome.FAILED,
        Outcome.SKIPPED,
        Outcome.ERROR,
        Outcome.XFAILED,
        Outcome.XPASSED,
    }

    # Exactly one run directory, one manifest, and no temporary leftovers.
    assert [path.name for path in run_dir.iterdir()] == [manifest["run_id"]]
    assert [path for path in run_dir.rglob("*") if path.name.endswith(".tmp")] == []


def test_unknown_marker_id_aborts_collection(pytester: pytest.Pytester) -> None:
    library = _write_library(pytester.path / "library", ["TC-LOGIN-001"])
    run_dir = pytester.path / "runs"
    pytester.makepyfile(
        test_bad="""\
import pytest


@pytest.mark.case("TC-LOGIN-999")
def test_unknown() -> None:
    assert True
"""
    )
    result = pytester.runpytest(
        "-p",
        PLUGIN,
        "--qa-project",
        str(library),
        "--qa-run-dir",
        str(run_dir),
        "test_bad.py",
    )
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*qa_trace marker errors:*", "*unknown case id*"])
    assert not run_dir.exists()


def test_a_malformed_marker_id_aborts_collection(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_bad="""\
import pytest


@pytest.mark.case("not-a-case-id")
def test_bad() -> None:
    assert True
"""
    )
    result = pytester.runpytest("-p", PLUGIN, "test_bad.py")
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*not a valid qa-trace ID*"])


def test_a_non_string_marker_argument_aborts_collection(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_bad="""\
import pytest


@pytest.mark.case(1)
def test_bad() -> None:
    assert True
"""
    )
    result = pytester.runpytest("-p", PLUGIN, "test_bad.py")
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*must be non-empty strings*"])


def test_an_unloadable_library_aborts_the_run(pytester: pytest.Pytester) -> None:
    empty = pytester.path / "library"
    empty.mkdir()
    pytester.makepyfile(test_one="def test_one() -> None:\n    assert True\n")
    result = pytester.runpytest("-p", PLUGIN, "--qa-project", str(empty), "test_one.py")
    assert result.ret == 4
    result.stderr.fnmatch_lines(
        ["*cannot load the project library*", "*TRACE_PROJECT_INVALID*"]
    )


def test_without_options_nothing_is_recorded(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_sample="""\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_one() -> None:
    assert True
"""
    )
    result = pytester.runpytest("-p", PLUGIN, "test_sample.py")
    assert result.ret == 0
    assert not (pytester.path / "runs").exists()


def test_run_dir_only_records_without_a_library(pytester: pytest.Pytester) -> None:
    run_dir = pytester.path / "runs"
    pytester.makepyfile(
        test_sample="""\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_one() -> None:
    assert True
"""
    )
    result = pytester.runpytest(
        "-p", PLUGIN, "--qa-run-dir", str(run_dir), "test_sample.py"
    )
    assert result.ret == 0
    manifest = _manifest(run_dir)
    assert manifest["project_id"] == "unknown"
    assert manifest["project_path"] is None
    assert manifest["asset_snapshot"] == {}
    assert manifest["status"] == "complete"
    assert [row["case_id"] for row in manifest["results"]] == ["TC-LOGIN-001"]


def test_collect_only_records_a_collection_only_run(
    pytester: pytest.Pytester,
) -> None:
    run_dir = pytester.path / "runs"
    pytester.makepyfile(
        test_sample="""\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_one() -> None:
    assert True


@pytest.mark.case("TC-LOGIN-002")
def test_two() -> None:
    assert True
"""
    )
    result = pytester.runpytest(
        "-p",
        PLUGIN,
        "--qa-run-dir",
        str(run_dir),
        "--collect-only",
        "test_sample.py",
    )
    assert result.ret == 0
    manifest = _manifest(run_dir)
    assert manifest["status"] == "collect_only"
    assert manifest["results"] == []
    assert manifest["cases"] == []
    assert manifest["summary"]["collected"] == 2


def test_unmarked_tests_are_listed_as_unmapped(pytester: pytest.Pytester) -> None:
    run_dir = pytester.path / "runs"
    pytester.makepyfile(
        test_sample="""\
import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_marked() -> None:
    assert True


def test_plain() -> None:
    assert True
"""
    )
    result = pytester.runpytest(
        "-p", PLUGIN, "--qa-run-dir", str(run_dir), "test_sample.py"
    )
    assert result.ret == 0
    manifest = _manifest(run_dir)
    assert len(manifest["results"]) == 1
    assert len(manifest["unmapped_nodeids"]) == 1
    assert manifest["unmapped_nodeids"][0].endswith("::test_plain")


def test_one_node_may_declare_several_cases(pytester: pytest.Pytester) -> None:
    run_dir = pytester.path / "runs"
    pytester.makepyfile(
        test_sample="""\
import pytest


@pytest.mark.case("TC-LOGIN-001", "TC-LOGIN-002")
def test_shared() -> None:
    assert True
"""
    )
    result = pytester.runpytest(
        "-p", PLUGIN, "--qa-run-dir", str(run_dir), "test_sample.py"
    )
    assert result.ret == 0
    manifest = _manifest(run_dir)
    assert [row["case_id"] for row in manifest["results"]] == [
        "TC-LOGIN-001",
        "TC-LOGIN-002",
    ]
    assert [row["case_id"] for row in manifest["cases"]] == [
        "TC-LOGIN-001",
        "TC-LOGIN-002",
    ]
    assert all(row["outcome"] == "passed" for row in manifest["cases"])
