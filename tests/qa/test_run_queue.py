"""Tests for background runs: per-project serialization and async start."""

from __future__ import annotations

import threading
import time

import pytest

from nanobot.qa.execution import execute_pinned_async, wait_for_run
from nanobot.qa.run_queue import RunScheduler
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError


def ready_case(store: QaStore, project: dict, *, title: str = "product list") -> dict:
    return store.create_case(
        project["id"],
        title=title,
        kind="api",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )


def test_scheduler_serializes_one_project() -> None:
    order: list[str] = []
    scheduler = RunScheduler(max_workers=2)

    def task(name: str):
        def run() -> None:
            order.append(f"enter-{name}")
            time.sleep(0.05)
            order.append(f"exit-{name}")

        return run

    try:
        scheduler.submit("p1", task("a"))
        scheduler.submit("p1", task("b"))
    finally:
        scheduler.shutdown(wait=True)
    assert order == ["enter-a", "exit-a", "enter-b", "exit-b"]


def test_scheduler_runs_different_projects_together() -> None:
    barrier = threading.Barrier(2, timeout=5)
    results: list[str] = []
    scheduler = RunScheduler(max_workers=2)

    def task(name: str):
        def run() -> None:
            try:
                barrier.wait()
                results.append(name)
            except threading.BrokenBarrierError:
                results.append(f"blocked-{name}")

        return run

    try:
        scheduler.submit("p1", task("one"))
        scheduler.submit("p2", task("two"))
    finally:
        scheduler.shutdown(wait=True)
    assert sorted(results) == ["one", "two"]


def test_async_start_returns_running_then_finishes(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project)
    scheduler = RunScheduler(max_workers=1)
    try:
        run = execute_pinned_async(store, project["id"], kind="api", scheduler=scheduler)
        assert run["status"] == "running"
        finished = wait_for_run(store, run["id"], timeout_s=60)
    finally:
        scheduler.shutdown(wait=True)
    assert finished["status"] == "passed"
    assert finished["passed"] == 1
    assert finished["finished_at"]


def test_async_start_refuses_blocked_cases(store: QaStore, project: dict) -> None:
    store.create_case(project["id"], title="draft case", kind="api", status="draft")
    scheduler = RunScheduler(max_workers=1)
    try:
        with pytest.raises(QaValidationError):
            execute_pinned_async(store, project["id"], kind="api", scheduler=scheduler)
    finally:
        scheduler.shutdown(wait=True)
    assert store.list_runs(project_id=project["id"])["total"] == 0


def test_two_runs_of_one_project_both_finish(
    store: QaStore, project: dict, demo_api: str,
) -> None:
    store.update_project(project["id"], base_url=demo_api)
    ready_case(store, project)
    scheduler = RunScheduler(max_workers=2)
    try:
        first = execute_pinned_async(store, project["id"], kind="api", scheduler=scheduler)
        second = execute_pinned_async(store, project["id"], kind="api", scheduler=scheduler)
        one = wait_for_run(store, first["id"], timeout_s=60)
        two = wait_for_run(store, second["id"], timeout_s=60)
    finally:
        scheduler.shutdown(wait=True)
    assert one["status"] == "passed"
    assert two["status"] == "passed"
    assert one["id"] != two["id"]
