"""Tests for the P3 content and dependency fingerprints (plan section 3.4)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from qa_trace.hashing import (
    canonical_json,
    changed_upstream,
    content_hash,
    dependency_hash,
    fingerprint_project,
    sha256_text,
)
from qa_trace.loader import load_project

REFORMATTED_CASE = """\
# A comment and a different key order must not change the content hash.
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
needs_recheck: false
"""


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [2, 3]}) == '{"a":[2,3],"b":1}'
    assert canonical_json({"a": "中文"}) == '{"a":"中文"}'
    assert sha256_text("x") == sha256_text("x")
    assert sha256_text("x") != sha256_text("y")


def test_content_hash_ignores_layout_review_metadata_and_derived_keys(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    before = content_hash(load_project(root).cases["TC-LOGIN-002"])
    (root / "cases" / "TC-LOGIN-002.yaml").write_text(
        REFORMATTED_CASE, encoding="utf-8"
    )
    after = content_hash(load_project(root).cases["TC-LOGIN-002"])
    assert before == after


def test_content_hash_tracks_a_business_field(copy_fixture: Callable[..., Path]) -> None:
    root = copy_fixture("impact_project")
    before = content_hash(load_project(root).cases["TC-LOGIN-002"])
    path = root / "cases" / "TC-LOGIN-002.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("剩余次数 = 4", "剩余次数 = 5"),
        encoding="utf-8",
    )
    after = content_hash(load_project(root).cases["TC-LOGIN-002"])
    assert before != after


def test_source_content_hash_ignores_the_manual_stale_flag(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    before = fingerprint_project(load_project(root))
    path = root / "sources" / "UI-LOGIN-01.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("stale: false", "stale: true"),
        encoding="utf-8",
    )
    after = fingerprint_project(load_project(root))
    assert before["UI-LOGIN-01"].content_hash == after["UI-LOGIN-01"].content_hash
    # The stale flag is a review-validity marker, not business content, so it does
    # not move the dependency fingerprint either; staleness reports it separately.
    assert (
        before["TC-LOGIN-001"].dependency_hash == after["TC-LOGIN-001"].dependency_hash
    )


def test_dependency_fingerprint_reaches_a_case_through_its_testpoint(
    copy_fixture: Callable[..., Path],
) -> None:
    root = copy_fixture("impact_project")
    before = fingerprint_project(load_project(root))
    path = root / "sources" / "REQ-LOGIN-01.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "连续失败 5 次锁定账号", "连续失败 6 次锁定账号"
        ),
        encoding="utf-8",
    )
    after = fingerprint_project(load_project(root))
    assert before["REQ-LOGIN-01"].content_hash != after["REQ-LOGIN-01"].content_hash
    assert (
        before["TP-LOGIN-001"].dependency_hash != after["TP-LOGIN-001"].dependency_hash
    )
    assert (
        before["TC-LOGIN-001"].dependency_hash != after["TC-LOGIN-001"].dependency_hash
    )
    # The case itself did not change, only what it depends on.
    assert before["TC-LOGIN-001"].content_hash == after["TC-LOGIN-001"].content_hash
    # A case on the other source is untouched.
    assert (
        before["TC-LOGIN-003"].dependency_hash == after["TC-LOGIN-003"].dependency_hash
    )


def test_dependency_hash_is_stable_and_sorted() -> None:
    first = dependency_hash("TC-X-001", "case", "abc", {"TP-B": "2", "TP-A": "1"})
    second = dependency_hash("TC-X-001", "case", "abc", {"TP-A": "1", "TP-B": "2"})
    assert first == second
    assert dependency_hash("TC-X-001", "case", "abc", {"TP-A": "1"}) != first


def test_changed_upstream_reports_added_removed_and_changed() -> None:
    assert changed_upstream({"A": "1", "B": "2"}, {"A": "1", "C": "3"}) == ("B", "C")
    assert changed_upstream({}, {"A": "1"}) == ("A",)
    assert changed_upstream({"A": None}, {"A": "1"}) == ("A",)
    assert changed_upstream({"A": "1"}, {"A": "1"}) == ()


def test_a_dangling_reference_contributes_none() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    fingerprints = fingerprint_project(load_project(fixtures / "invalid_dangling_source"))
    assert fingerprints["TP-LOGIN-005"].upstream == {"UI-LOGIN-404": None}
