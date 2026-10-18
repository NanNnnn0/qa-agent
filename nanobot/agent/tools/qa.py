"""Agent tools for the QA platform.

These tools are the model-facing half of the product: the model never writes
free-form test files to disk through this path. It creates structured cases,
scripts, runs and dispatch tasks that the gateway, the WebUI and the MCP server
all see.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import (
    ToolContext,
    current_request_context,
)
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.qa import service, shared_store
from nanobot.qa.roles import ROLE_LABELS, compose_prompt
from nanobot.qa.store import QaStore
from nanobot.qa.validation import (
    CASE_KINDS,
    CASE_PRIORITIES,
    CASE_STATUSES,
    SCRIPT_FRAMEWORKS,
    TASK_ROLES,
    TASK_STATUSES,
    QaError,
    QaValidationError,
)

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

_PLAN_MAX_TASKS = 6
_CASE_LIST_LIMIT = 100


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "code": case["code"],
        "title": case["title"],
        "kind": case["kind"],
        "priority": case["priority"],
        "status": case["status"],
        "tags": case.get("tags", []),
        "has_api": bool(case.get("api")),
        "steps": len(case.get("steps") or []),
    }


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "project_id": task.get("project_id"),
        "role": task["role"],
        "role_label": ROLE_LABELS.get(task["role"], task["role"]),
        "title": task["title"],
        "status": task["status"],
        "progress": task["progress"],
        "subagent_task_id": task.get("subagent_task_id") or "",
        "updated_at": task.get("updated_at"),
        "result_preview": (task.get("result") or "")[:200],
    }


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run["id"],
        "project_id": run["project_id"],
        "name": run.get("name", ""),
        "environment": run.get("environment", ""),
        "trigger": run.get("trigger", "manual"),
        "status": run["status"],
        "passed": run["passed"],
        "failed": run["failed"],
        "errors": run["errors"],
        "skipped": run["skipped"],
        "duration_ms": run["duration_ms"],
        "started_at": run["started_at"],
        "case_ids": run.get("case_ids", []),
        "script_id": run.get("script_id"),
    }


class _QaTool(Tool):
    """Shared plumbing for QA tools."""

    _scopes = {"core", "subagent"}

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    def _store(self) -> QaStore:
        return shared_store()


# ---------------------------------------------------------------------------
# qa_project
# ---------------------------------------------------------------------------


@tool_parameters(ObjectSchema(
    {
        "action": StringSchema(
            "list returns all projects; get reads one; create registers a project; "
            "update changes fields.",
            enum=("list", "get", "create", "update"),
        ),
        "project_id": StringSchema("Project id (proj_...)."),
        "key": StringSchema("Short project key used as the case-code prefix, e.g. MALL."),
        "name": StringSchema("Project display name."),
        "description": StringSchema("What the project does."),
        "base_url": StringSchema("Base URL the API runner sends requests to."),
        "repo_path": StringSchema("Local repository path used to resolve automation scripts."),
    },
    required=["action"],
    additional_properties=False,
).to_json_schema())
class QaProjectTool(_QaTool):
    """Manage QA projects."""

    @property
    def name(self) -> str:
        return "qa_project"

    @property
    def description(self) -> str:
        return (
            "Manage QA projects. A project owns test cases, automation scripts and runs. "
            "Call action=get or list before creating cases so project_id is correct."
        )

    async def execute(
        self,
        action: str,
        project_id: str | None = None,
        key: str | None = None,
        name: str | None = None,
        description: str | None = None,
        base_url: str | None = None,
        repo_path: str | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        try:
            if action == "list":
                return _dumps({"projects": store.list_projects()})
            if action == "get":
                if project_id:
                    return _dumps({"project": store.get_project(project_id)})
                if key:
                    return _dumps({"project": store.get_project_by_key(key)})
                return ToolResult.error("Error: get requires project_id or key")
            if action == "create":
                if not name:
                    return ToolResult.error("Error: create requires name")
                if not key:
                    return ToolResult.error("Error: create requires key (case-code prefix)")
                project = store.create_project(
                    key=key,
                    name=name,
                    description=description or "",
                    base_url=base_url or "",
                    repo_path=repo_path or "",
                )
                return _dumps({"project": project})
            if action == "update":
                if not project_id:
                    return ToolResult.error("Error: update requires project_id")
                project = store.update_project(
                    project_id, key=key, name=name, description=description,
                    base_url=base_url, repo_path=repo_path,
                )
                return _dumps({"project": project})
            return ToolResult.error("Error: unknown qa_project action")
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# qa_case
# ---------------------------------------------------------------------------


@tool_parameters(tool_parameters_schema(
    action=StringSchema(
        "list searches cases; get reads one; create adds one; bulk_create adds many "
        "(max 50); update changes fields; delete removes a case.",
        enum=("list", "get", "create", "bulk_create", "update", "delete"),
    ),
    project_id=StringSchema("Project id that owns the case."),
    case_id=StringSchema("Case id (case_...)."),
    title=StringSchema("Case title: one behaviour, no steps."),
    kind=StringSchema("api = executable API case; ui = UI flow; manual = human run.",
                      enum=list(CASE_KINDS)),
    code=StringSchema("Optional explicit case code; generated as KEY-API-001 otherwise."),
    priority=StringSchema("Priority.", enum=list(CASE_PRIORITIES)),
    status=StringSchema("Lifecycle status.", enum=list(CASE_STATUSES)),
    preconditions=StringSchema("Setup required before the case runs."),
    steps=ArraySchema({"type": "object"}, description="[{action, expected}] for ui/manual cases."),
    api=ObjectSchema(
        description="Structured API contract: {request:{method,path,headers,query,body},"
                    " assertions:[...], variables:{}}. Required for kind=api.",
    ),
    expected=StringSchema("Expected overall result."),
    tags=ArraySchema(StringSchema(""), description="Free-form labels."),
    query=StringSchema("list: substring match on title/code/tags/expected."),
    limit=IntegerSchema(description="list: page size.", minimum=1, maximum=500),
    cases=ArraySchema({"type": "object"}, description="bulk_create: case objects."),
    required=["action"],
))
class QaCaseTool(_QaTool):
    """Manage test cases."""

    @property
    def name(self) -> str:
        return "qa_case"

    @property
    def description(self) -> str:
        return (
            "Manage test cases in the unified QA library. API cases must carry a structured "
            "api.request + api.assertions object so the built-in runner can execute them; "
            "functional cases use ordered steps with expected results. Create cases here "
            "instead of writing Markdown files."
        )

    async def execute(
        self,
        action: str,
        project_id: str | None = None,
        case_id: str | None = None,
        title: str | None = None,
        kind: str | None = None,
        code: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        preconditions: str | None = None,
        steps: list[Any] | None = None,
        api: dict[str, Any] | None = None,
        expected: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        limit: int | None = None,
        cases: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        try:
            if action == "list":
                result = store.list_cases(
                    project_id=project_id,
                    kind=kind,
                    query=query,
                    limit=limit or _CASE_LIST_LIMIT,
                )
                return _dumps({
                    "total": result["total"],
                    "cases": [_case_summary(item) for item in result["items"]],
                })
            if action == "get":
                if not case_id:
                    return ToolResult.error("Error: get requires case_id")
                return _dumps({"case": store.get_case(case_id)})
            if action == "create":
                if not project_id:
                    return ToolResult.error("Error: create requires project_id")
                case = store.create_case(
                    project_id,
                    title=title or "",
                    kind=kind or "api",
                    code=code,
                    priority=priority or "P1",
                    status=status or "draft",
                    preconditions=preconditions or "",
                    steps=steps,
                    api=api,
                    expected=expected or "",
                    tags=tags,
                    source="ai",
                )
                return _dumps({"case": case})
            if action == "bulk_create":
                if not cases:
                    return ToolResult.error("Error: bulk_create requires cases")
                if len(cases) > 50:
                    return ToolResult.error("Error: bulk_create accepts at most 50 cases per call")
                created: list[dict[str, Any]] = []
                errors: list[dict[str, Any]] = []
                for index, item in enumerate(cases):
                    if not isinstance(item, dict):
                        errors.append({"index": index, "error": "case must be an object"})
                        continue
                    target_project = item.get("project_id") or project_id
                    if not target_project:
                        errors.append({"index": index, "error": "project_id is required"})
                        continue
                    try:
                        created.append(store.create_case(
                            target_project,
                            title=item.get("title", ""),
                            kind=item.get("kind", "api"),
                            code=item.get("code"),
                            priority=item.get("priority", "P1"),
                            status=item.get("status", "draft"),
                            preconditions=item.get("preconditions", ""),
                            steps=item.get("steps"),
                            api=item.get("api"),
                            expected=item.get("expected", ""),
                            tags=item.get("tags"),
                            source="ai",
                        ))
                    except QaError as exc:
                        errors.append({"index": index, "error": str(exc)})
                return _dumps({
                    "created": [_case_summary(case) for case in created],
                    "count": len(created),
                    "errors": errors,
                })
            if action == "update":
                if not case_id:
                    return ToolResult.error("Error: update requires case_id")
                case = store.update_case(
                    case_id,
                    title=title,
                    kind=kind,
                    code=code,
                    priority=priority,
                    status=status,
                    preconditions=preconditions,
                    steps=steps,
                    api=api,
                    expected=expected,
                    tags=tags,
                )
                return _dumps({"case": case})
            if action == "delete":
                if not case_id:
                    return ToolResult.error("Error: delete requires case_id")
                store.delete_case(case_id)
                return _dumps({"deleted": case_id})
            return ToolResult.error("Error: unknown qa_case action")
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# qa_script
# ---------------------------------------------------------------------------


@tool_parameters(tool_parameters_schema(
    action=StringSchema("list searches scripts; get reads one with content; "
                        "create adds a script; update rewrites it.",
                        enum=("list", "get", "create", "update")),
    project_id=StringSchema("Project id that owns the script."),
    script_id=StringSchema("Script id (scr_...)."),
    name=StringSchema("Short script name."),
    framework=StringSchema("Runner framework.", enum=list(SCRIPT_FRAMEWORKS)),
    language=StringSchema("Language: python, typescript, yaml."),
    file_path=StringSchema("Path relative to the project repo where the script should live."),
    content=StringSchema("Full script source."),
    case_ids=ArraySchema(StringSchema(""), description="Cases this script automates."),
    tags=ArraySchema(StringSchema(""), description="Free-form labels."),
    status=StringSchema("Lifecycle status.", enum=list(CASE_STATUSES)),
    query=StringSchema("list: substring match on name/tags/file_path."),
    limit=IntegerSchema(description="list: page size.", minimum=1, maximum=500),
    required=["action"],
))
class QaScriptTool(_QaTool):
    """Manage automation scripts."""

    @property
    def name(self) -> str:
        return "qa_script"

    @property
    def description(self) -> str:
        return (
            "Manage automation scripts stored in the unified library. Scripts are code; "
            "link them to case_ids so coverage stays traceable. framework=pytest scripts "
            "can be executed by qa_run."
        )

    async def execute(
        self,
        action: str,
        project_id: str | None = None,
        script_id: str | None = None,
        name: str | None = None,
        framework: str | None = None,
        language: str | None = None,
        file_path: str | None = None,
        content: str | None = None,
        case_ids: list[str] | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        try:
            if action == "list":
                return _dumps(store.list_scripts(
                    project_id=project_id, query=query, limit=limit or _CASE_LIST_LIMIT,
                ))
            if action == "get":
                if not script_id:
                    return ToolResult.error("Error: get requires script_id")
                return _dumps({"script": store.get_script(script_id)})
            if action == "create":
                if not project_id:
                    return ToolResult.error("Error: create requires project_id")
                if not name:
                    return ToolResult.error("Error: create requires name")
                script = store.create_script(
                    project_id,
                    name=name,
                    content=content or "",
                    framework=framework or "pytest",
                    language=language or "python",
                    file_path=file_path or "",
                    case_ids=case_ids,
                    tags=tags,
                    status=status or "draft",
                )
                return _dumps({"script": script})
            if action == "update":
                if not script_id:
                    return ToolResult.error("Error: update requires script_id")
                script = store.update_script(
                    script_id,
                    name=name,
                    content=content,
                    framework=framework,
                    language=language,
                    file_path=file_path,
                    case_ids=case_ids,
                    tags=tags,
                    status=status,
                )
                return _dumps({"script": script})
            return ToolResult.error("Error: unknown qa_script action")
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# qa_run
# ---------------------------------------------------------------------------


@tool_parameters(tool_parameters_schema(
    action=StringSchema(
        "start executes cases or a pytest script; import ingests a CI JUnit XML "
        "report as a run; list returns recent runs; get reads one run.",
        enum=("start", "import", "list", "get"),
    ),
    project_id=StringSchema("Project id."),
    run_id=StringSchema("Run id (run_...)."),
    case_ids=ArraySchema(StringSchema(""), description="start: explicit case ids."),
    kind=StringSchema("start: run every case of this kind when case_ids is omitted.",
                      enum=list(CASE_KINDS)),
    script_id=StringSchema("start: run this pytest script instead of API cases."),
    name=StringSchema("Run name shown in the workbench, e.g. 'nightly regression'."),
    environment=StringSchema("Environment label, e.g. staging / prod."),
    trigger=StringSchema("Who started the run.", enum=["manual", "ci", "agent", "schedule"]),
    xml=StringSchema("import: the JUnit XML document produced by CI."),
    limit=IntegerSchema(description="list: page size.", minimum=1, maximum=200),
    required=["action"],
))
class QaRunTool(_QaTool):
    """Execute cases and scripts."""

    @property
    def name(self) -> str:
        return "qa_run"

    @property
    def description(self) -> str:
        return (
            "Execute API cases (structured assertions, httpx) or pytest scripts in a "
            "subprocess, then persist the run. Read the report before writing a defect "
            "summary. Use list/get to inspect previous failures."
        )

    async def execute(
        self,
        action: str,
        project_id: str | None = None,
        run_id: str | None = None,
        case_ids: list[str] | None = None,
        kind: str | None = None,
        script_id: str | None = None,
        name: str | None = None,
        environment: str | None = None,
        trigger: str | None = None,
        xml: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        try:
            if action == "list":
                return _dumps(store.list_runs(project_id=project_id, limit=limit or 50))
            if action == "get":
                if not run_id:
                    return ToolResult.error("Error: get requires run_id")
                run = store.get_run(run_id)
                report = run.get("report") or {}
                tests = report.get("tests") or []
                if len(tests) > 30:
                    report = {**report, "tests": tests[:30],
                              "testsTruncated": len(tests) - 30}
                    run = {**run, "report": report}
                return _dumps({"run": run})
            if action == "start":
                if not project_id:
                    return ToolResult.error("Error: start requires project_id")
                if script_id:
                    run = service.execute_script(
                        store, project_id, script_id,
                        name=name or "", environment=environment or "",
                        trigger=trigger or "manual",
                    )
                else:
                    run = service.execute_cases(
                        store, project_id, case_ids=case_ids, kind=kind,
                        name=name or "", environment=environment or "",
                        trigger=trigger or "manual",
                    )
                return _dumps({"run": run})
            if action == "import":
                if not project_id:
                    return ToolResult.error("Error: import requires project_id")
                if not xml:
                    return ToolResult.error("Error: import requires xml (JUnit report)")
                run = service.ingest_junit(
                    store, project_id, xml=xml,
                    name=name or "", environment=environment or "",
                    trigger=trigger or "ci",
                )
                return _dumps({"run": run})
            return ToolResult.error("Error: unknown qa_run action")
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# qa_task
# ---------------------------------------------------------------------------


@tool_parameters(tool_parameters_schema(
    action=StringSchema(
        "list/get read dispatch state; create adds one task; update reports progress/result; "
        "plan creates a parent task plus specialist child tasks and dispatches them; "
        "dispatch sends one task to its specialist; cancel stops it; event appends progress; "
        "artifact links a case/script/run to the task; approve/reject close a "
        "needs_review task with a reviewer note.",
        enum=("list", "get", "create", "update", "plan", "dispatch", "cancel", "event",
              "artifact", "approve", "reject"),
    ),
    project_id=StringSchema("Project id the work belongs to."),
    task_id=StringSchema("Task id (task_...)."),
    title=StringSchema("Task title."),
    prompt=StringSchema("Detailed instructions for the specialist."),
    role=StringSchema("Specialist role.",
                      enum=list(TASK_ROLES)),
    status=StringSchema("New status.", enum=list(TASK_STATUSES)),
    progress=IntegerSchema(description="0-100 progress.", minimum=0, maximum=100),
    result=StringSchema("Conclusion written by the specialist."),
    tasks=ArraySchema({"type": "object"},
                      description="plan: [{role, title, prompt}] child tasks."),
    dispatch=ObjectSchema(
        description="plan: {dispatch: true} also starts subagents (default true).",
    ),
    artifacts=ArraySchema({"type": "object"},
                          description="artifact: [{kind, ref_id, title}]."),
    event_message=StringSchema("event: progress message."),
    note=StringSchema("approve/reject: reviewer note recorded in the task result."),
    reviewer=StringSchema("approve/reject: who made the decision."),
    limit=IntegerSchema(description="list: page size.", minimum=1, maximum=200),
    required=["action"],
))
class QaTaskTool(_QaTool):
    """Dispatch and track QA work."""

    @property
    def name(self) -> str:
        return "qa_task"

    @property
    def description(self) -> str:
        return (
            "Dispatch QA work to specialist subagents and track progress. "
            "Typical flow: qa_task action=plan project_id=... tasks=[{role:'api',...}, ...] "
            "to create and start tasks; specialists call qa_task action=update when done; "
            "the user watches the same tasks in the QA workbench. "
            "Roles: api (interfaces), ui (functional), automation (scripts), review."
        )

    def __init__(self, manager: SubagentManager | None = None) -> None:
        self._manager = manager

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx.subagent_manager)

    # -- helpers -------------------------------------------------------

    async def _reconcile(self, store: QaStore, tasks: list[dict[str, Any]]) -> None:
        """Pull terminal states from the subagent manager so the board is truthful."""
        manager = self._manager
        if manager is None:
            return
        by_session: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            if (
                task.get("subagent_task_id")
                and task.get("session_key")
                and task.get("status") in {"queued", "running"}
            ):
                by_session.setdefault(task["session_key"], []).append(task)
        for session_key, owned in by_session.items():
            try:
                statuses = await manager.read_statuses_for_session(session_key)
            except Exception:
                continue
            for task in owned:
                status = statuses.get(task["subagent_task_id"])
                if status is None:
                    continue
                mapped: str | None = None
                if status.state == "done":
                    mapped = "done"
                elif status.state in {"error", "interrupted"}:
                    mapped = "failed"
                elif status.state == "cancelled":
                    mapped = "cancelled"
                elif status.state == "incomplete":
                    mapped = "needs_review"
                if mapped is None:
                    continue
                try:
                    store.update_task(
                        task["id"], status=mapped,
                        result=(status.result or task.get("result") or "")[:20_000],
                    )
                except QaError:
                    logger.debug("QA task reconcile failed for {}", task["id"])

    async def _spawn(self, store: QaStore, task: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            raise QaValidationError("subagent manager is unavailable in this runtime")
        request_ctx = current_request_context()
        if request_ctx is None or request_ctx.runtime is None:
            raise QaValidationError("dispatch requires an active model runtime")
        project = None
        if task.get("project_id"):
            project = store.get_project(task["project_id"])
        prompt = compose_prompt(
            role=task["role"],
            task_id=task["id"],
            title=task["title"],
            prompt=task.get("prompt") or "",
            project=project,
        )
        from nanobot.security.workspace_access import current_workspace_scope
        from nanobot.session.manager import SessionPolicy

        ctx = request_ctx
        status = await manager.spawn_task(
            task=prompt,
            label=f"QA/{task['role']}: {task['title']}"[:60],
            origin_channel=ctx.channel,
            origin_chat_id=ctx.chat_id,
            session_key=ctx.session_key,
            origin_message_id=ctx.message_id,
            origin_turn_id=ctx.turn_id,
            workspace_scope=current_workspace_scope(),
            runtime=ctx.runtime,
            session_policy=SessionPolicy(
                persist=ctx.persist_session, log_content=ctx.log_content,
            ),
        )
        store.update_task(
            task["id"],
            status="running",
            progress=max(5, int(task.get("progress") or 0)),
            session_key=ctx.session_key or "",
            subagent_task_id=status.task_id,
        )
        store.add_event(
            task["id"], kind="dispatched",
            message=f"dispatched to {ROLE_LABELS.get(task['role'], task['role'])}",
            data={"subagent_task_id": status.task_id},
        )
        return status.task_id

    # -- execute ------------------------------------------------------

    async def execute(
        self,
        action: str,
        project_id: str | None = None,
        task_id: str | None = None,
        title: str | None = None,
        prompt: str | None = None,
        role: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        result: str | None = None,
        tasks: list[dict[str, Any]] | None = None,
        dispatch: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        event_message: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        store = self._store()
        try:
            if action == "list":
                payload = store.list_tasks(
                    project_id=project_id, status=status, limit=limit or 100,
                )
                await self._reconcile(store, payload["items"])
                payload["items"] = [_task_summary(task) for task in store.list_tasks(
                    project_id=project_id, status=status, limit=limit or 100,
                )["items"]]
                return _dumps(payload)
            if action == "get":
                if not task_id:
                    return ToolResult.error("Error: get requires task_id")
                task = store.get_task(task_id)
                await self._reconcile(store, [task])
                task = store.get_task(task_id)
                task["events"] = store.list_events(task_id)
                return _dumps({"task": task})
            if action == "create":
                if not title:
                    return ToolResult.error("Error: create requires title")
                task = store.create_task(
                    title=title, prompt=prompt or "", role=role or "api",
                    project_id=project_id,
                )
                return _dumps({"task": _task_summary(task)})
            if action == "update":
                if not task_id:
                    return ToolResult.error("Error: update requires task_id")
                task = store.update_task(
                    task_id, status=status, progress=progress, result=result,
                )
                return _dumps({"task": _task_summary(task)})
            if action == "cancel":
                if not task_id:
                    return ToolResult.error("Error: cancel requires task_id")
                task = store.update_task(task_id, status="cancelled")
                return _dumps({"task": _task_summary(task)})
            if action in {"approve", "reject"}:
                if not task_id:
                    return ToolResult.error(f"Error: {action} requires task_id")
                task = store.decide_task(
                    task_id,
                    approved=action == "approve",
                    note=note or "",
                    reviewer=reviewer or "",
                )
                return _dumps({"task": _task_summary(task)})
            if action == "event":
                if not task_id:
                    return ToolResult.error("Error: event requires task_id")
                event = store.add_event(
                    task_id, kind="progress", message=event_message or "",
                    data={"progress": progress} if progress is not None else None,
                )
                if progress is not None:
                    store.update_task(task_id, progress=progress)
                return _dumps({"event": event})
            if action == "artifact":
                if not task_id or not artifacts:
                    return ToolResult.error("Error: artifact requires task_id and artifacts")
                for item in artifacts:
                    if not isinstance(item, dict):
                        continue
                    store.add_artifact(
                        task_id,
                        kind=str(item.get("kind") or "note"),
                        ref_id=str(item.get("ref_id") or ""),
                        title=str(item.get("title") or ""),
                    )
                return _dumps({"task": _task_summary(store.get_task(task_id))})
            if action == "plan":
                if not tasks:
                    return ToolResult.error("Error: plan requires tasks")
                if len(tasks) > _PLAN_MAX_TASKS:
                    return ToolResult.error(
                        f"Error: plan accepts at most {_PLAN_MAX_TASKS} tasks per call"
                    )
                parent = store.create_task(
                    title=title or "测试任务派单",
                    prompt=prompt or "",
                    role="orchestrator",
                    project_id=project_id,
                    status="running",
                    progress=10,
                )
                store.add_event(
                    parent["id"], kind="plan",
                    message=f"planned {len(tasks)} specialist tasks",
                )
                should_dispatch = True
                if isinstance(dispatch, dict) and dispatch.get("dispatch") is False:
                    should_dispatch = False
                created: list[dict[str, Any]] = []
                errors: list[dict[str, Any]] = []
                for index, item in enumerate(tasks):
                    if not isinstance(item, dict):
                        errors.append({"index": index, "error": "task must be an object"})
                        continue
                    try:
                        child = store.create_task(
                            title=str(item.get("title") or f"任务 {index + 1}"),
                            prompt=str(item.get("prompt") or ""),
                            role=str(item.get("role") or "api"),
                            project_id=project_id,
                            parent_id=parent["id"],
                            status="queued",
                        )
                    except QaError as exc:
                        errors.append({"index": index, "error": str(exc)})
                        continue
                    store.add_event(parent["id"], kind="child",
                                    message=f"created {child['id']} ({child['role']})")
                    if should_dispatch:
                        try:
                            await self._spawn(store, child)
                        except (QaError, Exception) as exc:  # noqa: BLE001
                            store.update_task(child["id"], status="failed", result=str(exc))
                            errors.append({"index": index, "error": str(exc)})
                    created.append(_task_summary(store.get_task(child["id"])))
                if not errors:
                    store.update_task(parent["id"], status="running", progress=20)
                return _dumps({
                    "parent": _task_summary(store.get_task(parent["id"])),
                    "tasks": created,
                    "dispatched": should_dispatch,
                    "errors": errors,
                })
            if action == "dispatch":
                if not task_id:
                    return ToolResult.error("Error: dispatch requires task_id")
                task = store.get_task(task_id)
                subagent_id = await self._spawn(store, task)
                return _dumps({
                    "task": _task_summary(store.get_task(task_id)),
                    "subagent_task_id": subagent_id,
                })
            return ToolResult.error("Error: unknown qa_task action")
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# qa_overview
# ---------------------------------------------------------------------------


@tool_parameters(tool_parameters_schema())
class QaOverviewTool(_QaTool):
    """One-call snapshot of the QA platform."""

    @property
    def name(self) -> str:
        return "qa_overview"

    @property
    def description(self) -> str:
        return (
            "Read QA platform counts, projects with health stats, and recent tasks/runs. "
            "Start here when the user says 'run the tests' without naming a project."
        )

    async def execute(self, **kwargs: Any) -> Any:
        try:
            return _dumps(self._store().overview())
        except QaError as exc:
            return ToolResult.error(f"Error: {exc}")
