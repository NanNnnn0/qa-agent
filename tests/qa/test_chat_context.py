"""Tests for the chat -> QA project binding context."""

from __future__ import annotations

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.qa import QaCaseTool, QaRunTool, QaScriptTool
from nanobot.qa.chat_context import (
    QA_PROJECT_METADATA_KEY,
    binding_payload,
    bound_project_id,
    normalize_binding,
    qa_project_context,
)

BINDING = {"id": "proj_1", "key": "WEB", "name": "Web 商城"}


def test_normalize_binding_requires_an_id() -> None:
    assert normalize_binding(None) is None
    assert normalize_binding({}) is None
    assert normalize_binding({"id": " "}) is None
    assert normalize_binding({"id": "proj_1"}) == {"id": "proj_1", "key": "", "name": ""}
    assert normalize_binding(BINDING) == BINDING


def test_binding_payload_snapshots_the_project() -> None:
    project = {
        "id": "proj_1",
        "key": "WEB",
        "name": "Web 商城",
        "base_url": "x",
        "repo_path": "/srv/shop",
    }
    assert binding_payload(project) == {**BINDING, "repo_path": "/srv/shop"}


def test_bound_project_id_reads_turn_metadata() -> None:
    assert bound_project_id(None) is None
    assert bound_project_id({}) is None
    assert bound_project_id({QA_PROJECT_METADATA_KEY: BINDING}) == "proj_1"


async def test_context_block_is_only_injected_when_bound() -> None:
    unbound = RequestContext(channel="websocket", chat_id="chat-1")
    assert await qa_project_context(unbound) is None

    bound = RequestContext(
        channel="websocket",
        chat_id="chat-1",
        metadata={QA_PROJECT_METADATA_KEY: BINDING},
    )
    block = await qa_project_context(bound)
    assert block is not None
    assert block.source == "qa_project"
    assert "WEB (proj_1)" in block.content
    assert "qa_case" in block.content
    assert "qa_script" in block.content


def test_qa_tools_default_to_the_bound_project() -> None:
    bound = RequestContext(
        channel="websocket",
        chat_id="chat-1",
        metadata={QA_PROJECT_METADATA_KEY: BINDING},
    )
    with request_context(bound):
        for tool in (QaCaseTool(), QaScriptTool(), QaRunTool()):
            assert tool._project_id(None) == "proj_1"
            assert tool._project_id("proj_2") == "proj_2"

    unbound = RequestContext(channel="websocket", chat_id="chat-1")
    with request_context(unbound):
        assert QaCaseTool()._project_id(None) is None
