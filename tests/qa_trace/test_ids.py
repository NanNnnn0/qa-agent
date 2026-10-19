"""Unit tests for the qa-trace ID grammar, mapping and generator."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from qa_trace.errors import IdError, IdTypeMismatchError
from qa_trace.ids import (
    KIND_BY_PREFIX,
    PREFIX_BY_KIND,
    IdKind,
    ensure_kind,
    is_valid_id,
    kind_for_prefix,
    new_id,
    normalize_id,
    parse_id,
    prefix_for_kind,
)


@pytest.mark.parametrize(
    ("raw", "prefix", "kind", "module", "seq"),
    [
        ("REQ-12", "REQ", IdKind.REQ, None, "12"),
        ("API-PAY-100", "API", IdKind.API, "PAY", "100"),
        ("UI-LOGIN-02", "UI", IdKind.UI, "LOGIN", "02"),
        ("BUG-CART-7", "BUG", IdKind.BUG, "CART", "7"),
        ("STD-A11Y-01", "STD", IdKind.STD, "A11Y", "01"),
        ("EX-CHECKOUT-1", "EX", IdKind.EX, "CHECKOUT", "1"),
        ("TP-LOGIN-005", "TP", IdKind.TESTPOINT, "LOGIN", "005"),
        ("TC-LOGIN-003", "TC", IdKind.CASE, "LOGIN", "003"),
    ],
)
def test_parse_id_accepts_every_entity_prefix(
    raw: str, prefix: str, kind: IdKind, module: str | None, seq: str
) -> None:
    parsed = parse_id(raw)
    assert parsed.prefix == prefix
    assert parsed.kind is kind
    assert parsed.module == module
    assert parsed.seq == seq
    assert parsed.value == raw
    assert parsed.is_uuid is False


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "TC-",
        "TC-LOGIN",
        "TC-LOGIN-",
        "LOGIN-003",
        "TC-login-003",
        "TC-LOGIN-ABC",
        "TC-LOGIN-1234567",
        "XX-LOGIN-003",
        "TC-1LOGIN-003",
        " TC-LOGIN-003",
        None,
        12,
    ],
)
def test_parse_id_rejects_malformed_ids(raw: object) -> None:
    with pytest.raises(IdError) as info:
        parse_id(raw)
    assert info.value.code == "TRACE_ID_INVALID"
    assert info.value.field == "id"


def test_uuid4_sequence_is_accepted() -> None:
    raw = f"TC-LOGIN-{uuid.uuid4()}"
    parsed = parse_id(raw)
    assert parsed.is_uuid is True
    assert parsed.value == raw


def test_non_v4_uuid_sequence_is_rejected() -> None:
    with pytest.raises(IdError):
        parse_id(f"TC-LOGIN-{uuid.uuid1()}")


def test_normalize_id_canonicalizes_case_and_whitespace() -> None:
    assert normalize_id("  tc-login-003  ") == "TC-LOGIN-003"
    assert normalize_id("ui-login-02") == "UI-LOGIN-02"
    generated = str(uuid.uuid4())
    assert normalize_id(f"tc-login-{generated.upper()}") == f"TC-LOGIN-{generated}"


def test_normalize_id_rejects_garbage() -> None:
    with pytest.raises(IdError):
        normalize_id("not-an-id")


def test_prefix_and_kind_mapping_round_trips() -> None:
    assert len(PREFIX_BY_KIND) == len(KIND_BY_PREFIX) == len(IdKind)
    for kind, prefix in PREFIX_BY_KIND.items():
        assert prefix_for_kind(kind) == prefix
        assert prefix_for_kind(prefix) == prefix
        assert kind_for_prefix(prefix) is kind
        assert KIND_BY_PREFIX[prefix] is kind


def test_unknown_prefix_is_an_id_error() -> None:
    with pytest.raises(IdError):
        kind_for_prefix("ZZ")


def test_new_id_zero_pads_counters() -> None:
    assert new_id(IdKind.CASE, "LOGIN", 3) == "TC-LOGIN-003"
    assert new_id("testpoint", "login", 12) == "TP-LOGIN-012"
    assert new_id("ui", "LOGIN", 2) == "UI-LOGIN-002"


def test_new_id_uses_uuid4_sequence_for_parallel_branches() -> None:
    generated = uuid.uuid4()
    value = new_id(IdKind.CASE, "LOGIN", generated)
    assert value == f"TC-LOGIN-{generated}"
    assert parse_id(value).is_uuid


@pytest.mark.parametrize(
    ("kind", "module", "seq"),
    [
        ("nope", "LOGIN", 1),
        ("case", "", 1),
        ("case", None, 1),
        ("case", "1LOGIN", 1),
        ("case", "LOGIN", 0),
        ("case", "LOGIN", "ABC"),
        ("case", "LOGIN", uuid.uuid1()),
    ],
)
def test_new_id_rejects_invalid_input(
    kind: str, module: str | None, seq: int | str | uuid.UUID
) -> None:
    with pytest.raises(IdError):
        new_id(kind, module, seq)


def test_is_valid_id() -> None:
    assert is_valid_id("TC-LOGIN-003")
    assert not is_valid_id("TC-LOGIN-ABC")
    assert not is_valid_id(None)


def test_ensure_kind_accepts_a_matching_prefix() -> None:
    assert ensure_kind("TP-LOGIN-005", IdKind.TESTPOINT).value == "TP-LOGIN-005"


def test_ensure_kind_rejects_a_wrong_prefix() -> None:
    with pytest.raises(IdTypeMismatchError) as info:
        ensure_kind("TP-LOGIN-005", IdKind.CASE)
    assert info.value.code == "TRACE_ID_TYPE_MISMATCH"
    assert info.value.field == "id"


def test_errors_carry_file_and_field_context(tmp_path: Path) -> None:
    path = tmp_path / "TC-LOGIN-ABC.yaml"
    with pytest.raises(IdError) as info:
        parse_id("TC-LOGIN-ABC", path=path, field="id")
    assert info.value.path == str(path)
    assert info.value.field == "id"
    assert "TC-LOGIN-ABC" in info.value.message
    assert "TRACE_ID_INVALID" in info.value.format()
