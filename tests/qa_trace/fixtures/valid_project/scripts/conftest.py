"""Keep the sample script out of the repository's own pytest run.

The file is named ``test_login.py`` because that is what a real project looks
like, but it belongs to a fixture, not to this test suite.
"""

from __future__ import annotations

collect_ignore_glob = ["*.py"]
