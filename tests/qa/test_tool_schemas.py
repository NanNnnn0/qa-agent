"""Every tool definition must be JSON-serializable for provider payloads."""

from __future__ import annotations

import json

import pytest


def _definitions(scope: str) -> list[dict]:
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.loader import ToolLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.schema import ToolsConfig

    registry = ToolRegistry()
    ToolLoader().load(
        ToolContext(config=ToolsConfig(), workspace="."), registry, scope=scope,
    )
    return registry.get_definitions()


@pytest.mark.parametrize("scope", ["core", "subagent"])
def test_tool_definitions_are_json_serializable(scope: str) -> None:
    definitions = _definitions(scope)
    assert definitions
    serialized = json.dumps(definitions)
    assert "qa_project" in serialized


@pytest.mark.parametrize("scope", ["core", "subagent"])
def test_qa_tools_expose_plain_string_descriptions(scope: str) -> None:
    for definition in _definitions(scope):
        function = definition["function"]
        if not function["name"].startswith("qa_"):
            continue
        parameters = function["parameters"]
        assert isinstance(parameters.get("description", ""), str), function["name"]
        for name, prop in parameters.get("properties", {}).items():
            assert isinstance(prop, dict), f"{function['name']}.{name}"
            assert isinstance(prop.get("description", ""), str), f"{function['name']}.{name}"
