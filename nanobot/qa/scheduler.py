"""Background execution for pinned runs, serialized per project.

A run holds a project lock while it executes, so two runs of the same project
never interleave their writes or their extracted values. Runs of different
projects may proceed in parallel.

The scheduler is in-process. A gateway restart abandons runs that were still
``running``; the row keeps that status as evidence rather than being rewritten,
and the operator starts a new run.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class RunScheduler:
    """Run submitted tasks on a small pool, one at a time per project."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)), thread_name_prefix="qa-run",
        )
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def submit(self, project_id: str, task: Callable[[], Any]) -> None:
        lock = self._lock_for(project_id)

        def guarded() -> None:
            with lock:
                task()

        self._executor.submit(guarded)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _lock_for(self, project_id: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[project_id] = lock
            return lock


_SCHEDULER: RunScheduler | None = None
_SCHEDULER_GUARD = threading.Lock()


def shared_scheduler() -> RunScheduler:
    """Return the process-wide scheduler used by the MCP tool and the gateway."""
    global _SCHEDULER
    with _SCHEDULER_GUARD:
        if _SCHEDULER is None:
            _SCHEDULER = RunScheduler()
        return _SCHEDULER
