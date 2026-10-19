"""Sample script whose marker was lost when the file was rewritten.

``cases/TC-LOGIN-003.yaml`` still declares this test as its automation, so the
P2 lint must report ``TRACE_MARKER_MISMATCH`` for the case.
"""

from __future__ import annotations


def test_lock_after_5_failures() -> None:
    assert True
