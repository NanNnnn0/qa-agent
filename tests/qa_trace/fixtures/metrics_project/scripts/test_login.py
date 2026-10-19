"""Sample pytest script for the metrics fixture.

Only ``TC-LOGIN-001`` is automated here; the marker is what the P2 plugin will
cross-check against ``automation.script``.
"""

from __future__ import annotations

import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_lock_after_5_failures() -> None:
    assert True
