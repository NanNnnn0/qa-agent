"""Sample script for the P2 marker lint: case and script declare each other.

``cases/TC-LOGIN-003.yaml`` binds this file, and the marker below is the
script-side half of that binding (spec section 1.4).  ``qa trace check`` must
report nothing for this fixture.
"""

from __future__ import annotations

import pytest


@pytest.mark.case("TC-LOGIN-003")
def test_lock_after_5_failures() -> None:
    assert True
