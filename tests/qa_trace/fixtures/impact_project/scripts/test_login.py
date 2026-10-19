"""Sample pytest script for the impact fixture.

The marker is the script-side half of ``cases/TC-LOGIN-001.yaml``.
"""

from __future__ import annotations

import pytest


@pytest.mark.case("TC-LOGIN-001")
def test_lock_after_5_failures() -> None:
    assert True
