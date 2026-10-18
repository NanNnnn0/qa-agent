"""Dispatch tests: the plan tool must start real subagents with role prompts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import nanobot.qa as qa_package
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.qa import QaCaseTool, QaProjectTool, QaTaskTool


class FakeSubagentManager:
    """Records spawn calls and returns a stable task id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def spawn_task(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(task_id=f"sub-{len(self.calls)}", label=kwargs.get("label", ""))

    async def read_statuses_for_session(self, session_key: str) -> dict[str, Any]:
        return {}


@pytest.fixture(autouse=True)
def qa_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "qa.sqlite3"
    monkeypatch.setenv("NANOBOT_QA_DB", str(path))
    qa_package._STORE_CACHE.clear()
    yield path
    qa_package._STORE_CACHE.clear()


def _request_context() -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        message_id="msg-1",
        turn_id="turn-1",
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )


async def _project_id() -> str:
    payload = json.loads(str(await QaProjectTool().execute(
        "create", key="shop", name="Shop",
    )))
    return payload["project"]["id"]


async def test_dispatch_starts_a_subagent_with_the_role_prompt() -> None:
    manager = FakeSubagentManager()
    tool = QaTaskTool(manager)  # type: ignore[arg-type]
    project_id = await _project_id()
    task = json.loads(str(await tool.execute(
        "create", project_id=project_id, title="下单接口测试", role="api",
        prompt="覆盖库存不足",
    )))["task"]

    with request_context(_request_context()):
        result = json.loads(str(await tool.execute("dispatch", task_id=task["id"])))

    assert result["subagent_task_id"] == "sub-1"
    assert len(manager.calls) == 1
    spawn = manager.calls[0]
    assert spawn["label"].startswith("QA/api")
    prompt = spawn["task"]
    assert "接口测试助手" in prompt
    assert task["id"] in prompt
    assert "覆盖库存不足" in prompt
    assert "qa_task action=update" in prompt
    assert spawn["session_policy"].persist is True

    stored = json.loads(str(await tool.execute("get", task_id=task["id"])))["task"]
    assert stored["status"] == "running"
    assert stored["subagent_task_id"] == "sub-1"
    assert any(event["kind"] == "dispatched" for event in stored["events"])


async def test_plan_dispatches_each_child() -> None:
    manager = FakeSubagentManager()
    tool = QaTaskTool(manager)  # type: ignore[arg-type]
    project_id = await _project_id()

    with request_context(_request_context()):
        result = json.loads(str(await tool.execute(
            "plan",
            project_id=project_id,
            title="回归",
            tasks=[
                {"role": "api", "title": "接口", "prompt": "a"},
                {"role": "ui", "title": "功能", "prompt": "b"},
            ],
        )))

    assert result["dispatched"] is True
    assert len(manager.calls) == 2
    assert {call["label"].split(":")[0] for call in manager.calls} == {"QA/api", "QA/ui"}
    for item in result["tasks"]:
        assert item["status"] == "running"
        assert item["subagent_task_id"]


async def test_plan_without_dispatch_leaves_tasks_queued() -> None:
    manager = FakeSubagentManager()
    tool = QaTaskTool(manager)  # type: ignore[arg-type]
    project_id = await _project_id()
    result = json.loads(str(await tool.execute(
        "plan",
        project_id=project_id,
        tasks=[{"role": "api", "title": "接口"}],
        dispatch={"dispatch": False},
    )))
    assert result["dispatched"] is False
    assert manager.calls == []
    assert result["tasks"][0]["status"] == "queued"


async def test_dispatch_requires_a_runtime() -> None:
    manager = FakeSubagentManager()
    tool = QaTaskTool(manager)  # type: ignore[arg-type]
    project_id = await _project_id()
    task = json.loads(str(await tool.execute(
        "create", project_id=project_id, title="接口", role="api",
    )))["task"]
    result = await tool.execute("dispatch", task_id=task["id"])
    assert str(result).startswith("Error:")
    assert manager.calls == []


async def test_case_tool_bulk_creates_for_dispatch_consumers() -> None:
    """The specialist flow uses bulk_create then the task records artifacts."""
    project_id = await _project_id()
    tool = QaCaseTool()
    result = json.loads(str(await tool.execute(
        "bulk_create",
        project_id=project_id,
        cases=[{"title": "one", "kind": "api",
                "api": {"request": {"method": "GET", "path": "/x"},
                        "assertions": [{"type": "status", "expect": 200}]}}],
    )))
    assert result["count"] == 1
