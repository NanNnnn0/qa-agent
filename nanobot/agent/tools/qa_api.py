"""Agent-runtime adapters for the QA API asset tools.

The behaviour lives in :mod:`nanobot.qa.api_tools` so the stdio MCP server and the
agent runtime share one implementation. These adapters exist because
``ToolLoader`` only discovers :class:`~nanobot.agent.tools.base.Tool` subclasses
under ``nanobot/agent/tools``: without them the chat agent could read the
``qa-api-testing`` skill but had no ``qa_api_*`` tool to call.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.qa import api_tools
from nanobot.qa.chat_context import bound_project_id

_BOUND_PROJECT_HINT = (
    " project_id defaults to the QA project this chat is bound to when omitted."
)


class _QaApiTool(Tool):
    """Delegate one agent tool call to the shared API asset implementation."""

    # Main-agent only: the three schemas cost about 2.3k prompt tokens, which the
    # subagent prompt budget contract (tests/agent/test_subagent_consolidator_contract.py)
    # does not have room for. Subagents keep qa_case + qa_run for API work.
    _scopes = {"core"}
    impl: Any = None

    def __init__(self, store: Any = None) -> None:
        self._impl = self.impl() if store is None else self.impl(store)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return str(self._impl.name)

    @property
    def description(self) -> str:
        return f"{self._impl.description}{_BOUND_PROJECT_HINT}"

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(self._impl.parameters)

    def _project_id(self, explicit: str | None) -> str | None:
        """Default to the chat's bound QA project when the caller omitted it."""
        if explicit:
            return explicit
        ctx = current_request_context()
        if ctx is None:
            return None
        return bound_project_id(ctx.metadata)

    async def execute(self, **kwargs: Any) -> Any:
        if not kwargs.get("project_id"):
            bound = self._project_id(None)
            if bound:
                kwargs["project_id"] = bound
        return await self._impl.execute(**kwargs)


class QaApiCatalogTool(_QaApiTool):
    """Register and read the project's API reference catalog."""

    impl = api_tools.QaApiCatalogTool


class QaApiWorkflowTool(_QaApiTool):
    """Stage, validate and apply candidate API case batches."""

    impl = api_tools.QaApiWorkflowTool


class QaApiRunTool(_QaApiTool):
    """Preflight and run the pinned API execution plan."""

    impl = api_tools.QaApiRunTool
