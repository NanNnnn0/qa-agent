"""Tests for the YAML case document helpers (``qa_trace.caseyaml``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_trace.caseyaml import (
    CaseDocumentError,
    automation_block,
    case_document,
    case_files,
    case_module,
    case_path_for,
    case_relative_path,
    draft_batches,
    iter_case_documents,
    next_case_id,
    read_case_document,
    write_case_document,
)


def _document(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "case_id": "TC-LOGIN-001",
        "code": "LOGIN-API-001",
        "title": "连续失败 5 次锁定账号",
        "priority": "P0",
        "case_type": "api",
        "status": "draft",
        "steps": [{"action": "POST /login", "expected": "HTTP 423"}],
        "automation": {"status": "todo"},
        "testpoints": ["TP-LOGIN-001"],
    }
    values.update(overrides)
    return case_document(**values)  # type: ignore[arg-type]


def test_case_module_makes_a_project_key_usable_as_an_id_module() -> None:
    assert case_module("SHOP") == "SHOP"
    assert case_module("my-shop") == "MY_SHOP"
    assert case_module("login.lock") == "LOGIN_LOCK"
    with pytest.raises(CaseDocumentError):
        case_module("")


def test_the_document_keeps_the_reading_order_and_omits_empty_fields() -> None:
    document = _document()
    assert list(document)[:6] == [
        "schema_version",
        "id",
        "code",
        "title",
        "testpoints",
        "priority",
    ]
    assert document["schema_version"] == 1
    assert document["steps"] == [{"action": "POST /login", "expected": "HTTP 423"}]
    # Optional fields that were not supplied are absent, not null.
    assert "preconditions" not in document
    assert "api" not in document
    assert "risk" not in document


def test_sources_require_a_direct_reason_to_be_written() -> None:
    with_reason = _document(
        testpoints=[],
        sources=["REQ-LOGIN-01"],
        direct_reason="the requirement itself is testable",
        risk="high",
    )
    assert with_reason["sources"] == ["REQ-LOGIN-01"]
    assert with_reason["direct_reason"] == "the requirement itself is testable"
    without_reason = _document(
        testpoints=[], sources=["REQ-LOGIN-01"], risk="high"
    )
    assert "direct_reason" not in without_reason


def test_extra_keys_are_appended_without_overriding_known_fields() -> None:
    document = _document(extra={"source": "ai", "jira": "QA-1", "title": "nope"})
    assert document["source"] == "ai"
    assert document["jira"] == "QA-1"
    assert document["title"] != "nope"


@pytest.mark.parametrize(
    "override",
    [
        {"case_id": "TP-LOGIN-001"},
        {"title": "  "},
        {"priority": "P9"},
        {"case_type": "smoke"},
        {"status": "ready"},
        {"steps": []},
        {"risk": "huge"},
    ],
)
def test_an_unusable_document_is_refused(override: dict[str, object]) -> None:
    with pytest.raises(CaseDocumentError):
        _document(**override)


def test_automation_block_rejects_an_unknown_status() -> None:
    assert automation_block("todo") == {"status": "todo"}
    assert automation_block("done", "scripts/test_login.py::test_lock") == {
        "status": "done",
        "script": "scripts/test_login.py::test_lock",
    }
    with pytest.raises(CaseDocumentError):
        automation_block("finished")


def test_case_ids_are_allocated_from_disk_and_never_reused(tmp_path: Path) -> None:
    root = tmp_path / "login"
    assert next_case_id(root, project_key="LOGIN") == "TC-LOGIN-001"
    (root / "cases").mkdir(parents=True)
    (root / "cases" / "TC-LOGIN-001.yaml").write_text("id: TC-LOGIN-001\n", encoding="utf-8")
    (root / "draft" / "b1" / "cases").mkdir(parents=True)
    (root / "draft" / "b1" / "cases" / "TC-LOGIN-003.yaml").write_text(
        "id: TC-LOGIN-003\n", encoding="utf-8"
    )
    (root / "tombstones").mkdir()
    (root / "tombstones" / "TC-LOGIN-004.yaml").write_text(
        "id: TC-LOGIN-004\n", encoding="utf-8"
    )
    # The tombstone keeps 004 retired, so the next ID is 005.
    assert next_case_id(root, project_key="LOGIN") == "TC-LOGIN-005"
    # Another module has its own counter.
    assert next_case_id(root, project_key="SHOP") == "TC-SHOP-001"
    # Explicitly taken IDs (the derived index) count too.
    assert next_case_id(root, project_key="LOGIN", taken=["TC-LOGIN-007"]) == "TC-LOGIN-008"


def test_case_path_for_follows_the_review_state(tmp_path: Path) -> None:
    root = tmp_path / "login"
    assert case_path_for(root, "TC-LOGIN-001", status="reviewed").as_posix().endswith(
        "login/cases/TC-LOGIN-001.yaml"
    )
    assert case_path_for(root, "TC-LOGIN-001", status="draft", batch="b1").as_posix().endswith(
        "login/draft/b1/cases/TC-LOGIN-001.yaml"
    )
    assert case_path_for(root, "TC-LOGIN-001", status="draft").as_posix().endswith(
        "login/draft/workbench/cases/TC-LOGIN-001.yaml"
    )
    assert case_path_for(root, "TC-LOGIN-001", status="deprecated").as_posix().endswith(
        "login/tombstones/TC-LOGIN-001.yaml"
    )


def test_documents_are_listed_with_their_batch_and_tombstones_only_on_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "login"
    (root / "cases").mkdir(parents=True)
    (root / "cases" / "TC-LOGIN-001.yaml").write_text("id: TC-LOGIN-001\n", encoding="utf-8")
    (root / "draft" / "b1" / "cases").mkdir(parents=True)
    (root / "draft" / "b1" / "cases" / "TC-LOGIN-002.yaml").write_text(
        "id: TC-LOGIN-002\n", encoding="utf-8"
    )
    (root / "draft" / "b2" / "cases").mkdir(parents=True)
    (root / "draft" / "b2" / "cases" / "TC-LOGIN-003.yaml").write_text(
        "id: TC-LOGIN-003\n", encoding="utf-8"
    )
    (root / "tombstones").mkdir()
    (root / "tombstones" / "TC-LOGIN-004.yaml").write_text(
        "id: TC-LOGIN-004\n", encoding="utf-8"
    )

    assert draft_batches(root) == ("b1", "b2")
    found = case_files(root)
    assert len(found) == 3
    assert any(batch == "b1" for _, batch in found)
    assert len(case_files(root, include_drafts=False)) == 1
    assert len(case_files(root, include_tombstones=True)) == 4
    documents = {document["id"]: batch for _, batch, document in iter_case_documents(root)}
    assert documents == {
        "TC-LOGIN-001": None,
        "TC-LOGIN-002": "b1",
        "TC-LOGIN-003": "b2",
    }


def test_a_document_round_trips_with_utf8_content(tmp_path: Path) -> None:
    document = _document()
    path = write_case_document(tmp_path / "cases" / "TC-LOGIN-001.yaml", document)
    assert read_case_document(path) == document
    assert "连续失败 5 次锁定账号" in path.read_text(encoding="utf-8")
    assert case_relative_path(path, tmp_path) == "cases/TC-LOGIN-001.yaml"
