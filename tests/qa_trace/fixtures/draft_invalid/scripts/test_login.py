"""Sample pytest script for the login-lock case.

The marker below is the script-side half of the binding declared in
``cases/TC-LOGIN-003.yaml`` (``automation.script``).  P0 only stores the
reference; marker lint and collection cross-checks arrive in P1/P2.
"""

from __future__ import annotations

import pytest


@pytest.mark.case("TC-LOGIN-003")
def test_lock_after_5_failures() -> None:
    assert True
