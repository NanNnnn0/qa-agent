"""Tests for role prompts and demo seeding."""

from __future__ import annotations

from nanobot.qa.roles import ROLE_LABELS, compose_prompt, role_snapshot
from nanobot.qa.seed import seed_demo
from nanobot.qa.store import QaStore


def test_every_role_has_a_label_and_guide() -> None:
    snapshot = role_snapshot()
    assert {item["role"] for item in snapshot} == set(ROLE_LABELS)
    for item in snapshot:
        assert item["label"]
        assert item["guide"]


def test_compose_prompt_embeds_task_contract() -> None:
    prompt = compose_prompt(
        role="api",
        task_id="task_123",
        title="下单接口测试",
        prompt="覆盖库存不足",
        project={"id": "proj_1", "key": "SHOP", "base_url": "http://x"},
    )
    assert "task_id: task_123" in prompt
    assert "SHOP" in prompt
    assert "http://x" in prompt
    assert "qa_task action=update" in prompt
    assert "json_path" in prompt
    assert "blocked_by_env" in prompt


def test_compose_prompt_handles_missing_project() -> None:
    prompt = compose_prompt(
        role="ui", task_id="task_9", title="t", prompt="", project=None,
    )
    assert "task_9" in prompt
    assert "base_url: " in prompt


def test_seed_demo_is_idempotent(store: QaStore) -> None:
    first = seed_demo(store)
    assert first["created"] == 8
    project = first["project"]
    assert project["key"] == "SHOP"
    cases = store.list_cases(project_id=project["id"])
    assert cases["total"] == 8
    assert {case["kind"] for case in cases["items"]} == {"api", "ui"}
    scripts = store.list_scripts(project_id=project["id"])
    assert scripts["total"] == 1
    tasks = store.list_tasks(project_id=project["id"])
    assert tasks["total"] == 3

    second = seed_demo(store)
    assert second["created"] == 0
    assert store.list_cases(project_id=project["id"])["total"] == 8


def test_seeded_api_cases_are_executable(store: QaStore, demo_api: str) -> None:
    from nanobot.qa import service

    seeded = seed_demo(store, base_url=demo_api)
    run = service.execute_cases(store, seeded["project"]["id"], kind="api")
    assert run["status"] == "passed"
    assert run["passed"] == 6
