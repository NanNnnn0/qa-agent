"""Tests for the legacy SQLite <-> trace vocabulary mapping (``qa_trace.compat``).

The mapping is the only place that translates the old field names, so these
tests pin both directions: the lossless kinds, the intentionally widened ones
(``manual`` absorbs four trace types), the status rename and the defaults used by
callers that pass nothing.
"""

from __future__ import annotations

import pytest

from qa_trace.compat import (
    KIND_BY_TYPE,
    LEGACY_BY_STATUS,
    LEGACY_KINDS,
    LEGACY_STATUSES,
    STATUS_BY_LEGACY,
    TYPE_BY_KIND,
    automation_for_kind,
    kind_for_type,
    legacy_for_status,
    status_for_legacy,
    type_for_kind,
)


def test_every_legacy_kind_round_trips_through_the_trace_type() -> None:
    for kind in LEGACY_KINDS:
        trace_type = type_for_kind(kind)
        assert kind_for_type(trace_type) == kind


def test_api_and_ui_are_lossless_and_manual_absorbs_the_rest() -> None:
    assert TYPE_BY_KIND == {"api": "api", "ui": "ui", "manual": "functional"}
    # The legacy enum has no slot for the trace-only categories.
    assert {
        kind_for_type("functional"),
        kind_for_type("security"),
        kind_for_type("compat"),
        kind_for_type("perf"),
    } == {"manual"}
    assert set(KIND_BY_TYPE) >= set(TYPE_BY_KIND.values())


def test_unknown_and_missing_kinds_fall_back_to_the_default() -> None:
    assert type_for_kind(None) == "api"
    assert type_for_kind(None, default="ui") == "ui"
    assert type_for_kind("smoke") == "api"
    assert kind_for_type(None) == "manual"
    assert kind_for_type("does-not-exist") == "manual"


def test_kind_and_type_lookup_ignore_case_and_surrounding_space() -> None:
    assert type_for_kind(" API ") == "api"
    assert kind_for_type(" UI ") == "ui"
    assert status_for_legacy(" Ready ") == "reviewed"


def test_status_is_a_rename_between_ready_and_reviewed() -> None:
    assert STATUS_BY_LEGACY == {
        "draft": "draft",
        "ready": "reviewed",
        "deprecated": "deprecated",
    }
    assert LEGACY_BY_STATUS == {
        "draft": "draft",
        "reviewed": "ready",
        "deprecated": "deprecated",
    }
    for status in LEGACY_STATUSES:
        assert legacy_for_status(status_for_legacy(status)) == status


def test_unknown_and_missing_statuses_fall_back_to_the_default() -> None:
    assert status_for_legacy(None) == "draft"
    assert status_for_legacy(None, default="reviewed") == "reviewed"
    assert status_for_legacy("readyish") == "draft"
    assert legacy_for_status(None) == "draft"
    assert legacy_for_status("reviewed", default="draft") == "ready"
    assert legacy_for_status("nope") == "draft"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("api", {"status": "todo"}), ("ui", {"status": "manual"}), ("manual", {"status": "manual"})],
)
def test_automation_is_derived_from_the_kind(kind: str, expected: dict[str, str]) -> None:
    assert automation_for_kind(kind) == expected


def test_an_explicit_automation_block_wins_over_the_derived_one() -> None:
    explicit = {"status": "done", "script": "scripts/test_login.py::test_lock"}
    assert automation_for_kind("api", explicit=explicit) == explicit
    # The returned block is a copy: mutating it must not touch the caller's mapping.
    resolved = automation_for_kind("api", explicit=explicit)
    resolved["status"] = "doing"
    assert explicit["status"] == "done"


def test_an_empty_explicit_automation_block_is_ignored() -> None:
    assert automation_for_kind("api", explicit={}) == {"status": "todo"}
    assert automation_for_kind(None, explicit={}) == {"status": "todo"}
