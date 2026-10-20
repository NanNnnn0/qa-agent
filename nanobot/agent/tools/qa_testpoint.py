"""Agent tool for the trace chain: sources and test points (ADR 0012).

A case links a **test point**; the test point links the **sources** that justify
it. The tool writes drafts (review promotes them), so an agent cannot fabricate a
"reviewed" chain on its own.
"""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    ArraySchema,
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.qa import shared_store, testpoints
from nanobot.qa.chat_context import bound_project_id
from nanobot.qa.validation import QaError


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "create writes a draft; list reads sources, test points or pending drafts; "
            "get reads one asset; attach links existing cases to a test point.",
            enum=("create", "list", "get", "attach"),
        ),
        entity=StringSchema(
            "source = the root of the chain (requirement, API spec, bug, standard, "
            "exploration); testpoint = a test idea under one or more sources; "
            "draft = pending drafts.",
            enum=("source", "testpoint", "draft"),
        ),
        project_id=StringSchema("Project id (proj_...); defaults to the chat's bound project."),
        title=StringSchema("Title of the source or test point."),
        source_type=StringSchema(
            "entity=source: which kind of root this is.", enum=list(testpoints.SOURCE_TYPES)
        ),
        evidence=ArraySchema(
            {"type": "object"},
            description=(
                "entity=source: at least one pointer, "
                '[{"type": "openapi", "locator": "#/paths/~1api~1orders/post"}]. '
                "type is document|openapi|ui_capture|issue|standard|exploration."
            ),
        ),
        sources=ArraySchema(
            StringSchema(""),
            description=(
                "entity=testpoint: ids of existing sources, e.g. [\"API-SHOP-01\"]. "
                "List them first with action=list entity=source."
            ),
        ),
        method=StringSchema("entity=testpoint: test design method.", enum=list(testpoints.TESTPOINT_METHODS)),
        risk=StringSchema("entity=testpoint: risk.", enum=list(testpoints.TESTPOINT_RISKS)),
        confidence=StringSchema(
            "entity=source: observed (an inference) or confirmed (an authoritative document "
            "the user supplied). Review refuses a test point whose source is only observed.",
            enum=("observed", "confirmed"),
        ),
        module=StringSchema("Module segment of the generated id (default: the project key)."),
        group=StringSchema(
            "entity=testpoint: where it sits in the product, as a 模块/页面 breadcrumb, "
            "e.g. \"登录模块/注册界面\". Groups the workbench list; ids stay global."
        ),
        owner=StringSchema("Owner recorded on the entity."),
        note=StringSchema("Free-form note."),
        tags=ArraySchema(StringSchema(""), description="entity=testpoint: tags."),
        asset_id=StringSchema("get: the source or test point id."),
        testpoint_id=StringSchema("attach: the formal test point id."),
        case_ids=ArraySchema(StringSchema(""), description="attach: case ids to link."),
        replace=BooleanSchema(description="attach: replace the case's test points instead of adding."),
        batch=StringSchema("Draft batch name (default agent)."),
        limit=IntegerSchema(description="list: page size.", minimum=1, maximum=200),
        required=["action"],
    )
)
class QaTestpointTool(Tool):
    """Write and read the chain above cases: sources and test points."""

    _scopes = {"core"}

    @property
    def name(self) -> str:
        return "qa_testpoint"

    @property
    def description(self) -> str:
        return (
            "Trace assets for the QA chain. A case links a test point; the test point links "
            "the sources that justify it (requirement, API spec, bug, standard, exploration). "
            "create writes a draft that review promotes; attach links existing cases to a test "
            "point. Link a source directly on a case only when no test point fits, and then set "
            "direct_reason on the case."
        )

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    def _store(self) -> Any:
        return shared_store()

    def _project_id(self, explicit: str | None) -> str | None:
        if explicit:
            return explicit
        ctx = current_request_context()
        if ctx is None:
            return None
        return bound_project_id(ctx.metadata)

    async def execute(
        self,
        action: str,
        entity: str | None = None,
        project_id: str | None = None,
        title: str | None = None,
        source_type: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        sources: list[str] | None = None,
        method: str | None = None,
        risk: str | None = None,
        confidence: str | None = None,
        module: str | None = None,
        group: str | None = None,
        owner: str | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
        asset_id: str | None = None,
        testpoint_id: str | None = None,
        case_ids: list[str] | None = None,
        replace: bool = False,
        batch: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        project = self._project_id(project_id)
        try:
            if action == "create":
                if not project:
                    return ToolResult.error(
                        "Error: create requires project_id (or a chat bound to a QA project)"
                    )
                if entity == "source":
                    if not source_type:
                        return ToolResult.error(
                            "Error: create entity=source requires source_type "
                            "(req|api|ui|bug|std|ex)"
                        )
                    created = testpoints.create_source(
                        store,
                        project,
                        source_type=source_type,
                        title=title or "",
                        evidence=evidence,
                        module=module,
                        owner=owner or "agent",
                        note=note,
                        confidence=confidence or "observed",
                        batch=batch or testpoints.AGENT_BATCH,
                    )
                    return _dumps(created)
                if entity == "testpoint":
                    created = testpoints.create_testpoint(
                        store,
                        project,
                        title=title or "",
                        sources=sources,
                        method=method or "equivalence",
                        risk=risk or "medium",
                        module=module,
                        group=group,
                        owner=owner or "agent",
                        tags=tags,
                        note=note,
                        batch=batch or testpoints.AGENT_BATCH,
                    )
                    return _dumps(created)
                return ToolResult.error(
                    "Error: create requires entity=source or entity=testpoint"
                )
            if action == "list":
                if not project:
                    return ToolResult.error("Error: list requires project_id")
                assets = testpoints.list_assets(store, project)
                if entity == "source":
                    return _dumps(
                        {
                            "project_id": project,
                            "count": len(assets["sources"]),
                            "sources": assets["sources"][: limit or 50],
                        }
                    )
                if entity == "testpoint":
                    return _dumps(
                        {
                            "project_id": project,
                            "count": len(assets["testpoints"]),
                            "testpoints": assets["testpoints"][: limit or 50],
                        }
                    )
                if entity == "draft":
                    return _dumps(
                        {
                            "project_id": project,
                            "count": len(assets["drafts"]),
                            "drafts": assets["drafts"][: limit or 50],
                        }
                    )
                return _dumps(assets)
            if action == "get":
                if not project or not asset_id:
                    return ToolResult.error("Error: get requires project_id and asset_id")
                return _dumps(testpoints.get_asset(store, project, asset_id))
            if action == "attach":
                if not testpoint_id or not case_ids:
                    return ToolResult.error("Error: attach requires testpoint_id and case_ids")
                return _dumps(
                    testpoints.attach_cases(
                        store, testpoint_id, case_ids, replace=bool(replace)
                    )
                )
            return ToolResult.error(
                "Error: unknown qa_testpoint action (create|list|get|attach)"
            )
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")
