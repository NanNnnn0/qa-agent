"""Tests for the case fields the workbench compatibility layer added.

Stage 1 of the YAML case-source migration taught ``Case`` four optional fields
(``code``/``expected``/``api``/``legacy_id``) and taught the content fingerprint
to hash them, so the derived index notices an edit to any of them.  These tests
pin the document rules (what is accepted, what is refused and with which code),
the fingerprint recipe version, and the tolerant index read used by mutations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from qa_trace.errors import FieldInvalidError, TraceIndexError
from qa_trace.hashing import FINGERPRINT_VERSION, case_payload, content_hash
from qa_trace.index import (
    IndexEntry,
    ProjectIndex,
    index_path,
    load_index,
    load_index_for_write,
    require_compatible,
    write_index,
)
from qa_trace.models import Case

API_SPEC: dict[str, Any] = {
    "request": {
        "method": "POST",
        "path": "/api/orders",
        "headers": {"Content-Type": "application/json"},
        "body": {"sku": "A-1", "qty": 2},
    },
    "assertions": [
        {"type": "status", "expect": 201},
        {"type": "json_path", "path": "$.data.orderId", "op": "exists"},
    ],
}


def case_document(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid case document, with overrides applied."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "TC-SHOP-001",
        "title": "正常下单返回 201 并生成订单号",
        "testpoints": ["TP-SHOP-001"],
        "priority": "P0",
        "type": "api",
        "status": "draft",
        "steps": [{"action": "POST /api/orders", "expected": "返回 201 和订单号"}],
        "automation": {"status": "todo"},
    }
    data.update(overrides)
    return data


def parse(**overrides: Any) -> Case:
    return Case.from_dict(case_document(**overrides))


# -- document rules --------------------------------------------------------


def test_the_new_case_fields_are_optional_and_default_to_none() -> None:
    case = parse()
    assert case.code is None
    assert case.expected is None
    assert case.api is None
    assert case.legacy_id is None
    assert dict(case.extra) == {}


def test_code_expected_api_and_legacy_id_are_read() -> None:
    case = parse(
        code="SHOP-API-002",
        expected="下单成功，返回订单号",
        api=API_SPEC,
        legacy_id="case_9f2c",
    )
    assert case.code == "SHOP-API-002"
    assert case.expected == "下单成功，返回订单号"
    assert case.legacy_id == "case_9f2c"
    assert isinstance(case.api, Mapping)
    assert case.api["request"]["method"] == "POST"
    assert case.api["request"]["body"] == {"sku": "A-1", "qty": 2}
    # They are first-class fields now, not preserved "unknown" keys.
    assert dict(case.extra) == {}


def test_an_empty_api_block_reads_as_none() -> None:
    assert parse(api={}).api is None


def test_an_api_request_without_a_path_is_refused() -> None:
    with pytest.raises(FieldInvalidError) as caught:
        parse(api={"request": {"method": "GET"}})
    assert caught.value.field == "api.request.path"


def test_an_api_request_must_be_a_mapping() -> None:
    with pytest.raises(FieldInvalidError) as caught:
        parse(api={"request": ["GET", "/x"]})
    assert caught.value.field == "api.request"


def test_api_assertions_must_be_a_list() -> None:
    with pytest.raises(FieldInvalidError) as caught:
        parse(api={"assertions": {"type": "status", "expect": 200}})
    assert caught.value.field == "api.assertions"


def test_api_variables_must_be_a_mapping() -> None:
    with pytest.raises(FieldInvalidError) as caught:
        parse(api={"variables": ["a", "b"]})
    assert caught.value.field == "api.variables"


def test_unknown_keys_still_land_in_extra() -> None:
    case = parse(api=API_SPEC, jira="QA-12", code="SHOP-API-001")
    assert dict(case.extra) == {"jira": "QA-12"}


# -- content fingerprint ---------------------------------------------------


def test_the_fingerprint_recipe_version_covers_the_new_fields() -> None:
    assert FINGERPRINT_VERSION == 2


@pytest.mark.parametrize(
    "change",
    [
        {"code": "SHOP-API-777"},
        {"expected": "another observable result"},
        {"legacy_id": "case_other"},
        {"api": {**API_SPEC, "variables": {"sku": "A-1"}}},
    ],
)
def test_editing_a_new_field_changes_the_content_hash(change: dict[str, Any]) -> None:
    baseline = parse(api=API_SPEC)
    edited = parse(**change)
    assert content_hash(baseline) != content_hash(edited)


def test_reordering_the_api_block_does_not_change_the_content_hash() -> None:
    reordered = {
        "assertions": API_SPEC["assertions"],
        "request": API_SPEC["request"],
    }
    assert content_hash(parse(api=API_SPEC)) == content_hash(parse(api=reordered))


def test_the_hashed_payload_carries_the_new_fields() -> None:
    payload = case_payload(parse())
    assert payload["code"] is None
    assert payload["api"] is None
    assert payload["legacy_id"] is None
    assert payload["expected"] is None


# -- derived index ---------------------------------------------------------


def _entry(**overrides: Any) -> IndexEntry:
    data: dict[str, Any] = {
        "kind": "case",
        "content_hash": "a" * 64,
        "dependency_hash": "b" * 64,
    }
    data.update(overrides)
    return IndexEntry(**data)


def _write_index_with_version(root: Path, version: int) -> ProjectIndex:
    index = ProjectIndex(
        root=root,
        project_id="shop",
        fingerprint_version=version,
        baseline={"TC-SHOP-001": _entry()},
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    write_index(index, now=datetime.now(timezone.utc).isoformat())
    return index


def test_an_index_with_the_old_recipe_is_refused_for_reads(tmp_path: Path) -> None:
    _write_index_with_version(tmp_path, FINGERPRINT_VERSION - 1)
    loaded = load_index(tmp_path, project_id="shop")
    assert loaded.compatible is False
    assert loaded.baseline["TC-SHOP-001"].content_hash == "a" * 64

    with pytest.raises(TraceIndexError) as caught:
        require_compatible(loaded)
    assert caught.value.field == "fingerprint_version"


def test_load_index_for_write_treats_an_old_recipe_as_an_empty_index(
    tmp_path: Path,
) -> None:
    _write_index_with_version(tmp_path, 1)
    index = load_index_for_write(tmp_path, project_id="shop")
    assert index.compatible is True
    assert index.project_id == "shop"
    assert dict(index.baseline) == {}
    assert dict(index.reviews) == {}
    # The caller can now record fresh fingerprints; nothing is deleted on disk.
    assert index_path(tmp_path).is_file()


def test_load_index_for_write_keeps_a_compatible_index(tmp_path: Path) -> None:
    _write_index_with_version(tmp_path, FINGERPRINT_VERSION)
    index = load_index_for_write(tmp_path, project_id="shop")
    assert index.compatible is True
    assert index.baseline["TC-SHOP-001"].content_hash == "a" * 64
