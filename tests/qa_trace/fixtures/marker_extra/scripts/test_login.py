"""Sample script with one correct marker and three markers no case owns.

``TC-LOGIN-004`` is a manual case, so its marker is ``TRACE_MARKER_ORPHAN``;
``TC-LOGIN-999`` is not a case of this project and ``not-a-case-id`` is not a
valid ID, so both are ``TRACE_MARKER_UNKNOWN``.
"""

from __future__ import annotations

import pytest


@pytest.mark.case("TC-LOGIN-003")
def test_lock_after_5_failures() -> None:
    assert True


@pytest.mark.case("TC-LOGIN-004")
def test_manual_case_has_a_marker() -> None:
    assert True


@pytest.mark.case("TC-LOGIN-999")
def test_unknown_case_marker() -> None:
    assert True


@pytest.mark.case("not-a-case-id")
def test_invalid_case_marker() -> None:
    assert True
