"""Tests for the P3 draft batches and the review/promote workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from qa_trace.check import run_check
from qa_trace.cli import main
from qa_trace.drafts import (
    DEFAULT_BATCH,
    MODE_PROMOTED,
    add_draft,
    approve,
    find_draft,
    list_batches,
    list_drafts,
    new_draft,
    reject,
)
from qa_trace.errors import (
    DraftBaseMismatchError,
    DraftError,
    DraftIdConflictError,
    DraftNotFoundError,
    EntityNotFoundError,
    ReviewBlockedError,
)
from qa_trace.hashing import content_hash
from qa_trace.index import load_index
from qa_trace.loader import load_project
from qa_trace.models import ReviewStatus

NOW = "2026-10-18T00:00:00+00:00"

DRAFT_TESTPOINT = """\
schema_version: 1
id: TP-LOGIN-020
module: LOGIN
title: 批次内测试点
sources:
  - UI-LOGIN-01
method: boundary
risk: high
status: draft
"""

DRAFT_CASE = """\
schema_version: 1
id: TC-LOGIN-020
module: LOGIN
title: 批次内用例
testpoints:
  - TP-LOGIN-020
priority: P2
type: functional
status: draft
steps:
  - action: 连续输错密码 4 次
    expected: 提示文案不包含“账号锁定”，剩余次数 = 1
automation:
  status: manual
"""


DRAFT_SOURCE = """\
schema_version: 1
id: BUG-LOGIN-01
type: bug
module: LOGIN
title: 锁定提示文案与文档不一致
evidence:
  - type: issue
    locator: BUG-1234
    description: 缺陷单
confidence: observed
status: active
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _update_case(
    identifier: str,
    base_hash: str,
    *,
    title: str = "修订后的用例",
    testpoint: str = "TP-LOGIN-005",
) -> str:
    return f"""\
schema_version: 1
id: {identifier}
module: LOGIN
title: {title}
testpoints:
  - {testpoint}
priority: P1
type: functional
status: draft
steps:
  - action: 连续输错密码 5 次
    expected: 提示“账号锁定 15 分钟”，HTTP 状态码 423
automation:
  status: manual
base_content_hash: "{base_hash}"
"""


def test_review_list_shows_every_batch(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("draft_review")
    assert list_batches(root) == ("default", "login-lock")
    listing = list_drafts(root)
    assert [item.entity_id for item in listing.drafts] == [
        "TC-LOGIN-010",
        "TP-LOGIN-011",
    ]
    assert listing.counts == {
        "drafts": 2,
        "pending": 2,
        "rejected": 0,
        "invalid": 0,
        "batches": 2,
    }
    payload = listing.to_dict()
    assert payload["drafts"][0]["path"] == "draft/default/cases/TC-LOGIN-010.yaml"
    assert payload["drafts"][0]["status"] == "pending"
    assert payload["drafts"][0]["valid"] is True

    assert main(["trace", "review", "list", "--project", str(root)]) == 0
    assert "TC-LOGIN-010" in capsys.readouterr().out


def test_approve_promotes_a_draft_and_records_the_review(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("draft_review")
    before = run_check(root).diagnostics
    outcome = approve(root, "TC-LOGIN-010", reviewer="qa.li", note="补充倒计时", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    assert outcome.path == "cases/TC-LOGIN-010.yaml"
    assert outcome.reviewer == "qa.li"
    assert outcome.content_hash is not None
    assert outcome.needs_recheck is False

    promoted = root / "cases" / "TC-LOGIN-010.yaml"
    assert promoted.is_file()
    assert not (root / "draft" / "default" / "cases" / "TC-LOGIN-010.yaml").exists()
    project = load_project(root)
    assert project.cases["TC-LOGIN-010"].status is ReviewStatus.REVIEWED
    # The promotion is the only change: the formal library stays valid.
    assert run_check(root).diagnostics == before
    # The review record carries the reviewer, the time and both digests.
    index = load_index(root)
    entry = index.reviews["TC-LOGIN-010"]
    assert entry.reviewed_by == "qa.li"
    assert entry.reviewed_at == NOW
    assert entry.note == "补充倒计时"
    assert entry.content_hash == content_hash(project.cases["TC-LOGIN-010"])
    assert entry.dependency_hash is not None
    # The draft is gone from the listing and the empty batch directory is pruned.
    assert [item.entity_id for item in list_drafts(root).drafts] == ["TP-LOGIN-011"]
    assert not (root / "draft" / "default").exists()


def test_a_rejected_draft_stays_in_draft_and_cannot_be_approved(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("draft_review")
    draft_path = root / "draft" / "login-lock" / "testpoints" / "TP-LOGIN-011.yaml"
    outcome = reject(
        root, "TP-LOGIN-011", reviewer="qa.zhang", note="边界描述不清", now=NOW
    )
    assert outcome.mode == "rejected"
    assert draft_path.is_file()
    assert find_draft(root, "TP-LOGIN-011").rejected is True
    with pytest.raises(ReviewBlockedError, match="was rejected"):
        approve(root, "TP-LOGIN-011", now=NOW)
    assert "TP-LOGIN-011" not in load_project(root).testpoints

    # Editing the draft makes it pending again.
    draft_path.write_text(
        draft_path.read_text(encoding="utf-8").replace(
            "边界（4 次不锁定）", "边界（第 4 次不锁定）"
        ),
        encoding="utf-8",
    )
    assert find_draft(root, "TP-LOGIN-011").rejected is False
    promoted = approve(root, "TP-LOGIN-011", reviewer="qa.zhang", now=NOW)
    assert promoted.mode == MODE_PROMOTED
    assert load_project(root).testpoints["TP-LOGIN-011"].status is ReviewStatus.REVIEWED


def test_an_invalid_draft_is_refused_and_the_library_is_untouched(
    copy_fixture: Callable[..., Path], digest_tree: Callable[..., dict[str, str]]
) -> None:
    root = copy_fixture("draft_invalid")
    formal_before = digest_tree(root / "cases")
    with pytest.raises(ReviewBlockedError, match="steps"):
        approve(root, "TC-LOGIN-011", now=NOW)
    assert digest_tree(root / "cases") == formal_before
    assert not (root / "cases" / "TC-LOGIN-011.yaml").exists()
    # The draft is listed as invalid instead of disappearing.
    listing = list_drafts(root)
    assert listing.counts["invalid"] == 1
    assert listing.drafts[0].errors[0].code == "TRACE_FIELD_MISSING"


def test_check_excludes_drafts_by_default_and_validates_them_with_the_flag(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("draft_invalid")
    formal = run_check(root)
    assert formal.diagnostics == ()
    assert formal.exit_code == 0
    with_drafts = run_check(root, include_drafts=True)
    assert [item.code for item in with_drafts.diagnostics] == ["TRACE_FIELD_MISSING"]
    assert with_drafts.diagnostics[0].path == "draft/default/cases/TC-LOGIN-011.yaml"
    assert with_drafts.exit_code == 1

    clean = copy_fixture("draft_review", as_name="clean")
    assert run_check(clean, include_drafts=True).diagnostics == ()


def test_a_new_draft_cannot_take_an_existing_formal_id(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    root = copy_fixture("impact_project")
    external = _write(
        tmp_path / "dup.yaml",
        (root / "cases" / "TC-LOGIN-003.yaml").read_text(encoding="utf-8"),
    )
    with pytest.raises(DraftIdConflictError, match="base_content_hash"):
        add_draft(root, external, batch="dup")
    assert not (root / "draft").exists() or not list(
        (root / "draft").rglob("*.yaml")
    )


def test_an_update_draft_replaces_the_formal_entity(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    root = copy_fixture("draft_review")
    base = content_hash(load_project(root).cases["TC-LOGIN-003"])
    external = _write(tmp_path / "update.yaml", _update_case("TC-LOGIN-003", base))
    target = add_draft(root, external, batch="update")
    assert target.parent.name == "cases"
    outcome = approve(root, "TC-LOGIN-003", batch="update", reviewer="qa.zhang", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    project = load_project(root)
    assert project.cases["TC-LOGIN-003"].title == "修订后的用例"
    assert project.cases["TC-LOGIN-003"].status is ReviewStatus.REVIEWED
    assert not target.exists()


def test_an_update_draft_with_a_stale_base_is_refused(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    root = copy_fixture("draft_review")
    external = _write(
        tmp_path / "update.yaml",
        _update_case("TC-LOGIN-003", "a" * 64),
    )
    with pytest.raises(DraftBaseMismatchError, match="base_content_hash"):
        add_draft(root, external, batch="update")


def test_a_draft_that_depends_on_another_draft_is_refused(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    _write(root / "draft" / "together" / "testpoints" / "TP-LOGIN-020.yaml", DRAFT_TESTPOINT)
    _write(root / "draft" / "together" / "cases" / "TC-LOGIN-020.yaml", DRAFT_CASE)
    with pytest.raises(ReviewBlockedError, match="approve it first"):
        approve(root, "TC-LOGIN-020", now=NOW)
    approve(root, "TP-LOGIN-020", reviewer="qa.zhang", now=NOW)
    assert "TP-LOGIN-020" in load_project(root).testpoints
    outcome = approve(root, "TC-LOGIN-020", reviewer="qa.zhang", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    assert load_project(root).cases["TC-LOGIN-020"].status is ReviewStatus.REVIEWED


def test_draft_new_writes_a_valid_skeleton_and_approve_promotes_it(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    path = new_draft(
        root, kind="case", module="LOGIN", testpoint="TP-LOGIN-001", title="新草稿"
    )
    assert path.parent == root / "draft" / DEFAULT_BATCH / "cases"
    draft = find_draft(root, path.stem)
    assert draft.valid is True
    assert draft.entity_id.startswith("TC-LOGIN-")
    assert len(draft.entity_id.removeprefix("TC-LOGIN-")) == 36  # a UUID4, not a counter
    outcome = approve(root, draft.entity_id, reviewer="qa.li", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    assert run_check(root).exit_code == 0


def test_draft_new_requires_a_parent(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    with pytest.raises(DraftError, match="--testpoint or --source"):
        new_draft(root, kind="case", module="LOGIN")
    with pytest.raises(DraftError, match="--source"):
        new_draft(root, kind="testpoint", module="LOGIN")
    with pytest.raises(DraftError, match="module"):
        new_draft(root, kind="case", module="bad module", testpoint="TP-LOGIN-001")


def test_draft_add_refuses_a_duplicate_draft(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    root = copy_fixture("draft_review")
    external = _write(
        tmp_path / "new.yaml",
        (root / "draft" / "default" / "cases" / "TC-LOGIN-010.yaml").read_text(
            encoding="utf-8"
        ),
    )
    with pytest.raises(DraftIdConflictError, match="already exists as a draft"):
        add_draft(root, external, batch="other")


def test_approve_refuses_a_case_behind_a_stale_source(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("stale_propagation")
    with pytest.raises(ReviewBlockedError, match="is stale"):
        approve(root, "TC-LOGIN-003", now=NOW)


def test_approve_refuses_a_source(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    with pytest.raises(ReviewBlockedError, match="no review status"):
        approve(root, "REQ-LOGIN-01", now=NOW)


def test_review_cli_exit_codes(
    copy_fixture: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_fixture("draft_review")
    assert main(["trace", "review", "approve", "--project", str(root), "--id", "TC-LOGIN-010"]) == 0
    assert "promoted" in capsys.readouterr().out

    assert main(["trace", "review", "approve", "--project", str(root), "--id", "TC-LOGIN-999"]) == 1
    assert "TRACE_ENTITY_NOT_FOUND" in capsys.readouterr().out

    assert main(["trace", "review", "reject", "--project", str(root), "--id", "TC-LOGIN-999"]) == 1
    assert "TRACE_DRAFT_NOT_FOUND" in capsys.readouterr().out

    invalid = copy_fixture("draft_invalid", as_name="invalid")
    assert main(["trace", "review", "approve", "--project", str(invalid), "--id", "TC-LOGIN-011"]) == 1
    assert "TRACE_REVIEW_BLOCKED" in capsys.readouterr().out

    assert main(["trace", "check", "--project", str(invalid), "--include-draft"]) == 1
    assert "draft/default/cases/TC-LOGIN-011.yaml" in capsys.readouterr().out


def test_an_update_draft_clears_the_recheck_of_an_upstream_change(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    from qa_trace.staleness import compute_stale

    root = copy_fixture("impact_project")
    compute_stale(load_project(root), write=True, now=NOW)
    source = root / "sources" / "REQ-LOGIN-01.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "连续失败 5 次锁定账号", "连续失败 6 次锁定账号"
        ),
        encoding="utf-8",
    )
    assert {item.case_id for item in compute_stale(load_project(root)).needs_recheck} == {
        "TC-LOGIN-001",
        "TC-LOGIN-002",
    }
    base = content_hash(load_project(root).cases["TC-LOGIN-001"])
    external = _write(
        tmp_path / "update.yaml",
        _update_case(
            "TC-LOGIN-001", base, title="6 次锁定后的用例", testpoint="TP-LOGIN-001"
        ),
    )
    add_draft(root, external, batch="update")
    outcome = approve(root, "TC-LOGIN-001", batch="update", reviewer="qa.zhang", now=NOW)
    assert outcome.needs_recheck is False
    assert {item.case_id for item in compute_stale(load_project(root)).needs_recheck} == {
        "TC-LOGIN-002"
    }


def test_a_source_draft_is_promoted_and_records_only_the_baseline(
    copy_fixture: Callable[..., Path], tmp_path: Path
) -> None:
    root = copy_fixture("impact_project")
    external = _write(tmp_path / "source.yaml", DRAFT_SOURCE)
    add_draft(root, external, batch="sources")
    outcome = approve(root, "BUG-LOGIN-01", reviewer="qa.zhang", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    assert outcome.needs_recheck is False
    project = load_project(root)
    assert "BUG-LOGIN-01" in project.sources
    index = load_index(root)
    # A source has no review status: it gets a baseline, not a review record.
    assert "BUG-LOGIN-01" in index.baseline
    assert "BUG-LOGIN-01" not in index.reviews
    assert run_check(root).exit_code == 0


def test_draft_new_source_uses_the_source_prefix_and_promotes(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    path = new_draft(
        root, kind="source", module="LOGIN", source_type="api", title="登录接口契约"
    )
    assert path.name.startswith("API-LOGIN-")
    assert find_draft(root, path.stem).valid is True
    outcome = approve(root, path.stem, reviewer="qa.zhang", now=NOW)
    assert outcome.mode == MODE_PROMOTED
    assert path.stem in load_project(root).sources


def test_a_draft_testpoint_behind_an_observed_source_is_refused(
    copy_fixture: Callable[..., Path]
) -> None:
    root = copy_fixture("impact_project")
    source = root / "sources" / "UI-LOGIN-01.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "confidence: confirmed", "confidence: observed"
        ),
        encoding="utf-8",
    )
    _write(root / "draft" / "obs" / "testpoints" / "TP-LOGIN-020.yaml", DRAFT_TESTPOINT)
    with pytest.raises(ReviewBlockedError, match="observed"):
        approve(root, "TP-LOGIN-020", now=NOW)
    assert "TP-LOGIN-020" not in load_project(root).testpoints


def test_an_unknown_draft_id_is_reported(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("draft_review")
    with pytest.raises(DraftNotFoundError, match="no draft carries"):
        find_draft(root, "TC-LOGIN-999")
    with pytest.raises(EntityNotFoundError):
        approve(root, "TC-LOGIN-999", now=NOW)
