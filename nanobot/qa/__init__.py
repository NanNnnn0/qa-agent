"""QA platform: projects, test cases, automation scripts, runs and dispatch tasks.

Public entry points:

- :class:`nanobot.qa.store.QaStore` — SQLite persistence used by the gateway,
  the agent tools, the MCP server and the tests.
- :class:`nanobot.qa.http.QaApi` — WebUI HTTP routes (``/api/qa/*``).
- :class:`nanobot.qa.runner.CaseRunner` — executes structured API cases.
- :mod:`nanobot.qa.roles` — specialist role prompts used by dispatch.
"""

from __future__ import annotations

import os
from pathlib import Path

from nanobot.qa.store import QaStore

__all__ = ["default_store_path", "open_store", "shared_store"]

_STORE_CACHE: dict[str, QaStore] = {}


def default_store_path() -> Path:
    """Return the configured QA database path.

    ``NANOBOT_QA_DB`` wins so development, tests and demos can point at an
    isolated database without touching the instance data directory.
    """
    override = os.environ.get("NANOBOT_QA_DB", "").strip()
    if override:
        return Path(override).expanduser()
    from nanobot.config.paths import get_config_path

    return get_config_path().parent / "qa" / "qa.sqlite3"


def open_store(path: str | Path | None = None) -> QaStore:
    """Open (and migrate) a fresh QA store, defaulting to the instance data dir."""
    target = Path(path) if path is not None else default_store_path()
    return QaStore(target)


def shared_store(path: str | Path | None = None) -> QaStore:
    """Return a process-wide store for the default (or given) database path."""
    target = Path(path) if path is not None else default_store_path()
    key = str(target.expanduser().resolve())
    store = _STORE_CACHE.get(key)
    if store is None:
        store = QaStore(target)
        _STORE_CACHE[key] = store
    return store
