"""Tests for hash-based staleness: what changed and which cases need a re-check."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from qa_trace.cli import main
from qa_trace.errors import TraceIndexError
from qa_trace.index import (
    INDEX_DIRNAME,
    INDEX_FILENAME,
    index_path,
    load_index,
)
from qa_trace.loader import load_project
from qa_trace.staleness import (
    BASELINE_MISSING,
    BASELINE_RECORDED,
    REASON_CONTENT_CHANGED,
    REASON_DEPENDENCY_CHANGED,
    REASON_NO_REVIEW,
    REASON_SOURCE_STALE,
    compute_stale,
)

NOW = "2026-10-18T00:00:00+00:00"

NEW_CASE = """\
schema_version: 1
id: TC-LOGIN-004
module: LOGIN
title: 新增的回归用例
testpoints:
  - TP-LOGIN-002
priority: P2
type: functional
status: reviewed
steps:
  - action: 输入错误密码一次
    expected: 提示文案 = “用户名或密码错误”
automation:
  status: manual
"""


REFORMATTED_CASE = """\
# Same business content, different key order and layout.
schema_version: 1
status: reviewed
owner: qa.zhang
type: functional
priority: P2
title: 错误提示文案可判定
testpoints:
  - TP-LOGIN-002
module: LOGIN
id: TC-LOGIN-002
automation:
  status: manual
steps:
  - expected: 提示文案 = “用户名或密码错误”，剩余次数 = 4
    action: 输入错误密码一次
reviewed_by: qa.zhang
"""


def _write_baseline(root: Path) -> None:
    compute_stale(load_project(root), write=True, now=NOW)


def _change_source(root: Path) -> None:
    path = root / "sources" / "REQ-LOGIN-01.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "连续失败 5 次锁定账号", "连续失败 6 次锁定账号"
        ),
        encoding="utf-8",
    )


def _recheck_ids(report: object) -> set[str]:
    return {item.case_id for item in report.needs_recheck}  # type: ignore[attr-defined]


def test_stale_without_a_baseline_reports_every_entity_as_untracked(
    copy_fixture: Callable[..., Path], digest_tree: Callable[..., dict[str, str]]
) -> None:
    root = copy_fixture("impact_project")
    before = digest_tree(root)
    report = compute_stale(load_project(root), now=NOW)
    assert report.baseline == BASELINE_MISSING
    assert report.written is False
    assert {item.entity_id for item in report.changed} == {
        "REQ-LOGIN-01",
        "UI-LOGIN-01",
        "TP-LOGIN-001",
        "TP-LOGIN-002",
        "TC-LOGIN-001",
        "TC-LOGIN-002",
        "TC-LOGIN-003",
    }
    assert all(not item.in_baseline for item in report.changed)
    # Before the first baseline the library predates P3: a missing review record
    # is not reported as a re-check, only the manual stale flag is.
    assert report.needs_recheck == ()
    assert report.exit_code == 1
    assert not index_path(root).exists()
    assert digest_tree(root) == before


def test_write_records_a_baseline_without_touching_yaml(
    copy_fixture: Callable[..., Path], digest_tree: Callable[..., dict[str, str]]
) -> None:
    root = copy_fixture("impact_project")
    before = digest_tree(root)
    report = compute_stale(load_project(root), write=True, now=NOW)
    assert report.written is True
    assert report.recorded == 7
    assert report.baseline == BASELINE_RECORDED
    assert report.changed == ()
    assert report.needs_recheck == ()
    assert report.exit_code == 0
    # Only the derived index appeared; every YAML file is byte-identical.
    assert digest_tree(root, skip=(INDEX_DIRNAME,)) == before
    assert index_path(root).is_file()
    assert index_path(root).parent.name == INDEX_DIRNAME
    assert index_path(root).name == INDEX_FILENAME
    index = load_index(root)
    assert index.project_id == "impact-demo"
    assert set(index.baseline) == set(index.reviews) | {"REQ-LOGIN-01", "UI-LOGIN-01"}
    # A reviewed case is adopted, not silently marked as reviewed by a person.
    assert index.reviews["TC-LOGIN-001"].reviewed_by is None
    assert index.reviews["TC-LOGIN-001"].adopted is True
    # The second run is clean.
    assert compute_stale(load_project(root), now=NOW).exit_code == 0


def test_a_source_change_only_marks_the_real_downstream(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    _change_source(root)
    report = compute_stale(load_project(root), now=NOW)
    assert {item.entity_id for item in report.changed} == {
        "REQ-LOGIN-01",
        "TP-LOGIN-001",
        "TP-LOGIN-002",
        "TC-LOGIN-001",
        "TC-LOGIN-002",
    }
    # TC-LOGIN-003 hangs off UI-LOGIN-01 and must not be dragged in.
    assert "TC-LOGIN-003" not in {item.entity_id for item in report.changed}
    rechecks = {item.case_id: item for item in report.needs_recheck}
    assert set(rechecks) == {"TC-LOGIN-001", "TC-LOGIN-002"}
    assert rechecks["TC-LOGIN-001"].reasons == (REASON_DEPENDENCY_CHANGED,)
    assert rechecks["TC-LOGIN-001"].changed_ids == ("TP-LOGIN-001",)
    assert report.exit_code == 1


def test_approving_the_affected_case_clears_its_recheck(
    copy_fixture: Callable[..., Path]
) -> None:
    from qa_trace.drafts import MODE_REVIEWED, approve

    root = copy_fixture("impact_project")
    _write_baseline(root)
    _change_source(root)
    outcome = approve(root, "TC-LOGIN-001", reviewer="qa.zhang", note="复核新阈值", now=NOW)
    assert outcome.mode == MODE_REVIEWED
    assert outcome.needs_recheck is False
    assert outcome.reviewer == "qa.zhang"
    index = load_index(root)
    assert index.reviews["TC-LOGIN-001"].reviewed_by == "qa.zhang"
    assert index.reviews["TC-LOGIN-001"].note == "复核新阈值"
    report = compute_stale(load_project(root), now=NOW)
    assert _recheck_ids(report) == {"TC-LOGIN-002"}
    # Approving the case did not accept the upstream source change.
    assert "REQ-LOGIN-01" in {item.entity_id for item in report.changed}


def test_write_does_not_clear_an_existing_review(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    _change_source(root)
    report = compute_stale(load_project(root), write=True, now=NOW)
    assert report.written is True
    assert report.changed == ()
    # ``--write`` moves the baseline only; the review record still points at the
    # old upstream fingerprint, so the re-check survives.
    assert _recheck_ids(report) == {"TC-LOGIN-001", "TC-LOGIN-002"}


def test_a_case_content_change_is_a_recheck(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    path = root / "cases" / "TC-LOGIN-002.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("剩余次数 = 4", "剩余次数 = 3"),
        encoding="utf-8",
    )
    report = compute_stale(load_project(root), now=NOW)
    rechecks = {item.case_id: item for item in report.needs_recheck}
    assert set(rechecks) == {"TC-LOGIN-002"}
    assert REASON_CONTENT_CHANGED in rechecks["TC-LOGIN-002"].reasons
    assert rechecks["TC-LOGIN-002"].changed_ids == ("TC-LOGIN-002",)
    changed = {item.entity_id: item for item in report.changed}
    assert changed["TC-LOGIN-002"].content_changed is True


def test_reformatting_a_file_does_not_trigger_a_recheck(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    (root / "cases" / "TC-LOGIN-002.yaml").write_text(
        REFORMATTED_CASE, encoding="utf-8"
    )
    report = compute_stale(load_project(root), now=NOW)
    assert report.changed == ()
    assert report.exit_code == 0


def test_a_manual_stale_flag_puts_downstream_cases_up_for_recheck(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("stale_propagation")
    _write_baseline(root)
    report = compute_stale(load_project(root), now=NOW)
    rechecks = {item.case_id: item for item in report.needs_recheck}
    assert set(rechecks) == {"TC-LOGIN-003"}
    assert rechecks["TC-LOGIN-003"].reasons == (REASON_SOURCE_STALE,)
    assert rechecks["TC-LOGIN-003"].changed_ids == ("UI-LOGIN-02",)
    assert report.changed == ()
    assert report.exit_code == 1


def test_a_reviewed_case_added_after_the_baseline_has_no_review_record(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    (root / "cases" / "TC-LOGIN-004.yaml").write_text(NEW_CASE, encoding="utf-8")
    report = compute_stale(load_project(root), now=NOW)
    rechecks = {item.case_id: item for item in report.needs_recheck}
    assert set(rechecks) == {"TC-LOGIN-004"}
    assert rechecks["TC-LOGIN-004"].reasons == (REASON_NO_REVIEW,)
    assert "TC-LOGIN-004" in {item.entity_id for item in report.changed}


def test_stale_cli_exit_codes_and_json(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("impact_project")
    assert main(["trace", "stale", "--project", str(root)]) == 1
    text = capsys.readouterr().out
    assert "baseline            missing" in text

    assert main(["trace", "stale", "--project", str(root), "--write"]) == 0
    assert "baseline            recorded" in capsys.readouterr().out

    _change_source(root)
    assert main(["trace", "stale", "--project", str(root), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_version"] == 1
    assert payload["baseline"] == BASELINE_RECORDED
    assert payload["counts"]["changed"] == 5
    assert payload["counts"]["needs_recheck"] == 2
    assert payload["needs_recheck"][0]["case_id"] == "TC-LOGIN-001"
    assert payload["changed"][0]["id"] == "REQ-LOGIN-01"

    assert main(["trace", "stale", "--project", str(root), "--write"]) == 1  # reviews still old
    assert main(["trace", "stale", "--project", str(root)]) == 1
    capsys.readouterr()


def test_an_unreadable_index_is_an_input_failure(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("impact_project")
    path = index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TraceIndexError):
        compute_stale(load_project(root))
    assert main(["trace", "stale", "--project", str(root)]) == 2
    assert "TRACE_INDEX_INVALID" in capsys.readouterr().out


def test_an_index_from_another_fingerprint_recipe_is_refused(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    payload = json.loads(index_path(root).read_text(encoding="utf-8"))
    payload["fingerprint_version"] = 99
    index_path(root).write_text(json.dumps(payload), encoding="utf-8")
    assert main(["trace", "stale", "--project", str(root)]) == 2
    out = capsys.readouterr().out
    assert "fingerprint_version" in out
    assert "stale --write" in out


def test_an_index_of_another_project_is_refused(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    _write_baseline(root)
    payload = json.loads(index_path(root).read_text(encoding="utf-8"))
    payload["project_id"] = "someone-else"
    index_path(root).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TraceIndexError):
        compute_stale(load_project(root))
