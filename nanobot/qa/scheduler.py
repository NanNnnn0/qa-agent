"""Background runner for QA schedules.

The gateway starts one scheduler per process. Due schedules are claimed with a
conditional update in the store, so two gateway processes sharing the QA
database cannot both run the same occurrence. Runs execute in a worker thread
because the runner blocks on HTTP and on the pytest subprocess.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from loguru import logger

from nanobot.qa import service
from nanobot.qa.store import QaStore

DEFAULT_TICK_SECONDS = 30.0


def run_schedule(store: QaStore, schedule: dict[str, Any]) -> dict[str, Any]:
    """Execute one claimed schedule and return the persisted run."""
    name = str(schedule.get("name") or "")
    target = schedule.get("target")
    if not isinstance(target, dict):
        raise ValueError("schedule target is missing")
    if target.get("kind") == "script":
        return service.execute_script(
            store,
            str(schedule["project_id"]),
            str(target["script_id"]),
            name=name,
            trigger="schedule",
        )
    case_ids = target.get("case_ids")
    run_kind = target.get("run_kind")
    return service.execute_cases(
        store,
        str(schedule["project_id"]),
        case_ids=[str(item) for item in case_ids] if isinstance(case_ids, list) else None,
        kind=str(run_kind) if isinstance(run_kind, str) and run_kind else None,
        name=name,
        trigger="schedule",
    )


class QaScheduler:
    """Tick-based scheduler bound to the gateway event loop."""

    def __init__(
        self,
        store: QaStore,
        *,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
    ) -> None:
        self._store = store
        self._tick_seconds = tick_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run_forever(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                await self.tick()
            except Exception:
                # One broken schedule must not stop the loop for the others.
                logger.exception("QA schedule tick failed")

    async def tick(self, *, now_iso: str | None = None) -> list[str]:
        """Claim and start every due schedule; returns the claimed ids."""
        claimed = await asyncio.to_thread(self._store.claim_due_schedules, now_iso)
        for schedule in claimed:
            asyncio.create_task(self._execute(schedule))
        return [schedule["id"] for schedule in claimed]

    async def _execute(self, schedule: dict[str, Any]) -> None:
        try:
            run = await asyncio.to_thread(run_schedule, self._store, schedule)
        except Exception as exc:
            logger.exception("QA schedule {} failed", schedule.get("id"))
            await asyncio.to_thread(
                self._store.record_schedule_run,
                schedule["id"],
                status="error",
                error=str(exc),
            )
            return
        await asyncio.to_thread(
            self._store.record_schedule_run,
            schedule["id"],
            run_id=run["id"],
            status=run["status"],
        )
