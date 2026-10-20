"""Human-facing labels for trace IDs (display only).

A trace ID carries the project module and a uuid so two projects, or two test
points written in the same second, never collide.  That is the right key and a
terrible thing to read in a list, so every surface that shows a list also shows
a short ordinal derived from it.  The ordinal is **never stored**: it is
computed from the current library, so it can shift when a test point is deleted.
Callers therefore show the full id next to it (hover, or the detail drawer).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def testpoint_codes(testpoints: Iterable[Any]) -> dict[str, str]:
    """Return ``{test point id: "TP-01"}`` in id order."""
    ids = sorted(
        str(item if isinstance(item, str) else getattr(item, "id", item))
        for item in testpoints
    )
    return {item: f"TP-{index:02d}" for index, item in enumerate(ids, start=1)}
