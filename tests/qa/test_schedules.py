"""Tests for QA schedules: storage, actions and the background tick."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from qa_helpers import make_request
from websockets.http11 import Request as WsRequest

from nanobot.qa.http import QaApi
from nanobot.qa.scheduler import QaScheduler
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaNotFoundError, QaValidationError


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


async def _dispatch(api: QaApi, request: WsRequest, path: str | None = None) -> Any:
    from nanobot.webui.http_utils import parse_request_path

    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got if path is None else path)


def _script_schedule(store: QaStore, project: dict[str, Any]) -> dict[str, Any]:
    script = store.create_script(
        project["id"], name="nightly", file_path="tests/test_nightly.py",
    )
    return store.create_schedule(
        project["id"],
        name="Nightly",
        cron="0 3 * * *",
        timezone="UTC",
        target={"kind": "script", "script_id": script["id"]},
    )


def test_schedule_crud_and_next_run(store: QaStore, project: dict[str, Any]) -> None:
    schedule = _script_schedule(store, project)
    assert schedule["id"].startswith("sch_")
    assert schedule["enabled"] == 1
    assert schedule["target"]["kind"] == "script"
    assert schedule["next_run_at"].endswith("Z")
    assert schedule["last_run_id"] == ""

    listed = store.list_schedules(project_id=project["id"])
    assert [item["id"] for item in listed] == [schedule["id"]]

    paused = store.update_schedule(schedule["id"], enabled=False)
    assert paused["enabled"] == 0
    assert paused["next_run_at"] is None

    resumed = store.update_schedule(schedule["id"], enabled=True, name="Nightly v2")
    assert resumed["enabled"] == 1
    assert resumed["name"] == "Nightly v2"
    assert resumed["next_run_at"].endswith("Z")

    store.delete_schedule(schedule["id"])
    with pytest.raises(QaNotFoundError):
        store.get_schedule(schedule["id"])


def test_schedule_validation_rejects_bad_input(
    store: QaStore, project: dict[str, Any],
) -> None:
    other = store.create_project(key="other", name="Other")
    script = store.create_script(project["id"], name="s", file_path="a.py")
    other_script = store.create_script(other["id"], name="s", file_path="a.py")
    case = store.create_case(project["id"], title="manual case", kind="manual")
    other_case = store.create_case(other["id"], title="other case", kind="manual")

    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="not a cron",
            target={"kind": "script", "script_id": script["id"]},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *", timezone="Mars/Base",
            target={"kind": "script", "script_id": script["id"]},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *",
            target={"kind": "script", "script_id": other_script["id"]},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *",
            target={"kind": "cases", "case_ids": []},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *",
            target={"kind": "cases", "case_ids": [other_case["id"]]},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *", enabled="yes",
            target={"kind": "cases", "case_ids": [case["id"]]},
        )
    with pytest.raises(QaValidationError):
        store.create_schedule(
            project["id"], name="x", cron="0 3 * * *", target={"kind": "nope"},
        )


def test_deleting_a_project_removes_its_schedules(
    store: QaStore, project: dict[str, Any],
) -> None:
    case = store.create_case(project["id"], title="t", kind="manual")
    schedule = store.create_schedule(
        project["id"], name="n", cron="0 3 * * *",
        target={"kind": "cases", "case_ids": [case["id"]]},
    )
    store.delete_project(project["id"])
    with pytest.raises(QaNotFoundError):
        store.get_schedule(schedule["id"])


def test_due_schedules_are_claimed_once(
    store: QaStore, project: dict[str, Any],
) -> None:
    case = store.create_case(project["id"], title="t", kind="manual")
    schedule = store.create_schedule(
        project["id"], name="n", cron="* * * * *",
        target={"kind": "cases", "case_ids": [case["id"]]},
    )
    future = "2099-01-01T00:00:00Z"

    first = store.claim_due_schedules(future)
    assert [item["id"] for item in first] == [schedule["id"]]
    assert first[0]["next_run_at"] > future
    # The next occurrence is scheduled; the same instant cannot claim it again.
    assert store.claim_due_schedules(future) == []
    assert [item["id"] for item in store.claim_due_schedules("2099-01-02T00:00:00Z")] == [
        schedule["id"]
    ]


async def test_schedule_actions_over_http(store: QaStore, project: dict[str, Any]) -> None:
    script = store.create_script(project["id"], name="s", file_path="a.py")
    api = QaApi(store)

    response = await _dispatch(
        api,
        make_request(
            "/api/qa/schedules/create",
            {
                "project_id": project["id"],
                "name": "Nightly",
                "cron": "0 3 * * *",
                "timezone": "UTC",
                "target": {"kind": "script", "script_id": script["id"]},
            },
        ),
        "/api/qa/schedules/create",
    )
    payload = _body(response)
    assert payload["ok"] is True
    schedule = payload["schedule"]
    assert schedule["name"] == "Nightly"
    assert schedule["target"] == {"kind": "script", "script_id": script["id"]}

    response = await _dispatch(api, make_request("/api/qa/schedules"))
    assert [item["id"] for item in _body(response)["items"]] == [schedule["id"]]

    response = await _dispatch(
        api,
        make_request("/api/qa/schedules/update", {"id": schedule["id"], "enabled": False}),
        "/api/qa/schedules/update",
    )
    assert _body(response)["schedule"]["next_run_at"] is None

    response = await _dispatch(
        api,
        make_request("/api/qa/schedules/delete", {"id": schedule["id"]}),
        "/api/qa/schedules/delete",
    )
    assert _body(response)["deleted"] is True
    response = await _dispatch(api, make_request("/api/qa/schedules"))
    assert _body(response)["items"] == []


async def test_run_now_records_the_executed_run(
    store: QaStore, project: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule = _script_schedule(store, project)
    calls: list[str] = []

    def fake_run(store_arg: QaStore, schedule_arg: dict[str, Any]) -> dict[str, Any]:
        calls.append(schedule_arg["id"])
        return {"id": "run_fake", "status": "passed"}

    monkeypatch.setattr("nanobot.qa.scheduler.run_schedule", fake_run)
    api = QaApi(store)
    response = await _dispatch(
        api,
        make_request("/api/qa/schedules/run-now", {"id": schedule["id"]}),
        "/api/qa/schedules/run-now",
    )
    payload = _body(response)
    assert payload["run"]["id"] == "run_fake"
    assert payload["schedule"]["last_run_id"] == "run_fake"
    assert payload["schedule"]["last_status"] == "passed"
    assert calls == [schedule["id"]]


async def test_scheduler_tick_claims_and_records(
    store: QaStore, project: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = store.create_case(project["id"], title="t", kind="manual")
    schedule = store.create_schedule(
        project["id"], name="n", cron="* * * * *",
        target={"kind": "cases", "case_ids": [case["id"]]},
    )
    monkeypatch.setattr(
        "nanobot.qa.scheduler.run_schedule",
        lambda store_arg, schedule_arg: {"id": "run_tick", "status": "passed"},
    )
    scheduler = QaScheduler(store, tick_seconds=0.01)

    claimed = await scheduler.tick(now_iso="2099-01-01T00:00:00Z")
    assert claimed == [schedule["id"]]
    for _ in range(100):
        if store.get_schedule(schedule["id"])["last_run_id"] == "run_tick":
            break
        await asyncio.sleep(0.01)
    recorded = store.get_schedule(schedule["id"])
    assert recorded["last_run_id"] == "run_tick"
    assert recorded["last_status"] == "passed"
    assert await scheduler.tick(now_iso="2099-01-01T00:00:00Z") == []
