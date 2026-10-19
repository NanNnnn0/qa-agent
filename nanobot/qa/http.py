"""HTTP routes for the QA platform (``/api/qa/*``).

Reads are ordinary authenticated GETs. Writes follow the WebUI CSRF design:
they are only accepted through the authenticated WebSocket mutation channel,
which marks the synthetic request and carries the JSON payload.

This module must not import ``nanobot.webui.ws_http`` (that module imports the
QA routes), so the mutation attribute names are repeated here exactly as the
WebUI transport defines them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from loguru import logger
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.qa import service
from nanobot.qa.store import QaStore
from nanobot.qa.validation import (
    QaConflictError,
    QaError,
    QaNotFoundError,
    QaValidationError,
)
from nanobot.webui.http_utils import (
    http_json_response as _json,
)
from nanobot.webui.http_utils import (
    parse_query as _parse_query,
)
from nanobot.webui.http_utils import (
    query_first as _query_first,
)

_MUTATION_PAYLOAD_ATTR = "_nanobot_webui_mutation_payload"
_MUTATION_REQUEST_ATTR = "_nanobot_webui_mutation_request"

QA_PREFIX = "/api/qa"

#: WebSocket mutation action -> HTTP path. ``WebUIMutationPaths`` in ws_http
#: merges this mapping into its allowlist.
QA_MUTATION_PATHS: dict[str, str] = {
    "qa.project.create": "/api/qa/projects/create",
    "qa.project.update": "/api/qa/projects/update",
    "qa.project.delete": "/api/qa/projects/delete",
    "qa.case.create": "/api/qa/cases/create",
    "qa.case.bulk_create": "/api/qa/cases/bulk-create",
    "qa.case.update": "/api/qa/cases/update",
    "qa.case.delete": "/api/qa/cases/delete",
    "qa.case.import": "/api/qa/cases/import",
    "qa.script.create": "/api/qa/scripts/create",
    "qa.script.update": "/api/qa/scripts/update",
    "qa.script.delete": "/api/qa/scripts/delete",
    "qa.task.create": "/api/qa/tasks/create",
    "qa.task.update": "/api/qa/tasks/update",
    "qa.task.cancel": "/api/qa/tasks/cancel",
    "qa.task.approve": "/api/qa/tasks/approve",
    "qa.task.reject": "/api/qa/tasks/reject",
    "qa.run.start": "/api/qa/runs/start",
    "qa.run.import": "/api/qa/runs/import",
}

QA_WRITE_PATHS = frozenset(QA_MUTATION_PATHS.values())


def _error(status: int, message: str) -> Response:
    return _json({"ok": False, "error": message}, status=status)


def _ok(data: dict[str, Any]) -> Response:
    return _json({"ok": True, **data})


def _mutation_payload(request: WsRequest) -> dict[str, Any] | None:
    payload = getattr(request, _MUTATION_PAYLOAD_ATTR, None)
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else None


class QaApi:
    """Route QA reads and writes for one gateway process."""

    def __init__(
        self,
        store: QaStore,
        *,
        check_api_token: Callable[[WsRequest], bool] | None = None,
    ) -> None:
        self.store = store
        self._check_api_token = check_api_token

    # -- authorization -----------------------------------------------------

    def _authorized(self, request: WsRequest) -> bool:
        if self._check_api_token is None:
            return True
        try:
            return bool(self._check_api_token(request))
        except Exception:
            logger.exception("QA API token check failed")
            return False

    # -- dispatch ----------------------------------------------------------

    async def dispatch(self, connection: Any, request: WsRequest, path: str) -> Response | None:
        if path != QA_PREFIX and not path.startswith(QA_PREFIX + "/"):
            return None
        try:
            if not self._authorized(request):
                return _error(401, "unauthorized")
            if path in QA_WRITE_PATHS:
                return await self._dispatch_write(request, path)
            return await self._dispatch_read(request, path)
        except QaNotFoundError as exc:
            return _error(404, str(exc))
        except QaConflictError as exc:
            return _error(409, str(exc))
        except QaValidationError as exc:
            return _error(400, str(exc))
        except QaError as exc:
            return _error(400, str(exc))
        except Exception:
            logger.exception("QA API route failed: {}", path)
            return _error(500, "internal QA API error")

    # -- reads -------------------------------------------------------------

    async def _dispatch_read(self, request: WsRequest, path: str) -> Response | None:
        query = _parse_query(request.path)
        store = self.store
        if path == f"{QA_PREFIX}/health":
            return _ok({"store": str(store.path)})
        if path == f"{QA_PREFIX}/overview":
            return _ok(store.overview())
        if path == f"{QA_PREFIX}/projects":
            return _ok({"projects": store.list_projects()})
        if path.startswith(f"{QA_PREFIX}/projects/"):
            return _ok({"project": store.get_project(path.rsplit("/", 1)[-1])})
        if path == f"{QA_PREFIX}/cases/export":
            payload = store.export_cases(_query_first(query, "project_id") or None)
            return _ok(payload)
        if path == f"{QA_PREFIX}/cases":
            return _ok(store.list_cases(
                project_id=_query_first(query, "project_id") or None,
                kind=_query_first(query, "kind") or None,
                status=_query_first(query, "status") or None,
                query=_query_first(query, "q") or None,
                limit=_int_query(query, "limit", 100),
                offset=_int_query(query, "offset", 0),
            ))
        if path.startswith(f"{QA_PREFIX}/cases/") and "/revisions" in path:
            rest = path[len(QA_PREFIX) + len("/cases/"):]
            case_id, _, revision = rest.partition("/revisions")
            revision = revision.strip("/")
            if revision:
                try:
                    number = int(revision)
                except ValueError as exc:
                    raise QaValidationError("revision must be an integer") from exc
                return _ok({"revision": store.get_case_revision(case_id, number)})
            return _ok(store.list_case_revisions(
                case_id,
                limit=_int_query(query, "limit", 50),
                offset=_int_query(query, "offset", 0),
            ))
        if path == f"{QA_PREFIX}/api-operations":
            return _ok(store.list_api_operations(
                _query_first(query, "project_id") or None,
                query=_query_first(query, "q") or None,
                method=_query_first(query, "method") or None,
                status=_query_first(query, "status") or None,
                limit=_int_query(query, "limit", 10),
                offset=_int_query(query, "offset", 0),
            ))
        if path.startswith(f"{QA_PREFIX}/api-operations/"):
            return _ok({"operation": store.get_api_operation(path.rsplit("/", 1)[-1])})
        if path.startswith(f"{QA_PREFIX}/cases/"):
            return _ok({"case": store.get_case(path.rsplit("/", 1)[-1])})
        if path == f"{QA_PREFIX}/scripts":
            return _ok(store.list_scripts(
                project_id=_query_first(query, "project_id") or None,
                query=_query_first(query, "q") or None,
                limit=_int_query(query, "limit", 100),
                offset=_int_query(query, "offset", 0),
            ))
        if path.startswith(f"{QA_PREFIX}/scripts/"):
            return _ok({"script": store.get_script(path.rsplit("/", 1)[-1])})
        if path == f"{QA_PREFIX}/runs":
            return _ok(store.list_runs(
                project_id=_query_first(query, "project_id") or None,
                limit=_int_query(query, "limit", 50),
                offset=_int_query(query, "offset", 0),
            ))
        if path.startswith(f"{QA_PREFIX}/runs/"):
            return _ok({"run": store.get_run(path.rsplit("/", 1)[-1])})
        if path == f"{QA_PREFIX}/tasks":
            return _ok(store.list_tasks(
                project_id=_query_first(query, "project_id") or None,
                status=_query_first(query, "status") or None,
                role=_query_first(query, "role") or None,
                limit=_int_query(query, "limit", 100),
                offset=_int_query(query, "offset", 0),
            ))
        if path.startswith(f"{QA_PREFIX}/tasks/") and path.endswith("/events"):
            task_id = path[len(QA_PREFIX) + len("/tasks/"):-len("/events")]
            return _ok({"events": store.list_events(task_id)})
        if path.startswith(f"{QA_PREFIX}/tasks/"):
            return _ok({"task": store.get_task(path.rsplit("/", 1)[-1])})
        return None

    # -- writes ------------------------------------------------------------

    async def _dispatch_write(self, request: WsRequest, path: str) -> Response:
        if not getattr(request, _MUTATION_REQUEST_ATTR, False):
            return _error(405, "WebUI mutation requires an authenticated WebSocket")
        payload = _mutation_payload(request)
        if payload is None:
            return _error(400, "missing mutation payload")
        store = self.store
        if path == "/api/qa/projects/create":
            project = store.create_project(
                key=payload.get("key"),
                name=payload.get("name"),
                description=payload.get("description", ""),
                base_url=payload.get("base_url", ""),
                repo_path=payload.get("repo_path", ""),
                default_env=payload.get("default_env"),
            )
            return _ok({"project": project})
        if path == "/api/qa/projects/update":
            project_id = _require_id(payload)
            project = store.update_project(project_id, **_fields(payload, {
                "key", "name", "description", "base_url", "repo_path", "default_env",
            }))
            return _ok({"project": project})
        if path == "/api/qa/projects/delete":
            store.delete_project(_require_id(payload))
            return _ok({"deleted": True})
        if path == "/api/qa/cases/create":
            case = store.create_case(
                (_require_field(payload, "project_id")),
                **_fields(payload, {
                    "title", "kind", "code", "priority", "status", "preconditions",
                    "steps", "api", "expected", "tags", "source", "author",
                }),
            )
            return _ok({"case": case})
        if path == "/api/qa/cases/bulk-create":
            project_id = _require_field(payload, "project_id")
            raw_cases = payload.get("cases")
            if not isinstance(raw_cases, list):
                raise QaValidationError("cases must be an array")
            if len(raw_cases) > 50:
                raise QaValidationError("bulk-create accepts at most 50 cases per call")
            created: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for index, item in enumerate(raw_cases):
                if not isinstance(item, dict):
                    errors.append({"index": index, "error": "case must be an object"})
                    continue
                try:
                    created.append(store.create_case(
                        project_id,
                        **_fields(item, {
                            "title", "kind", "code", "priority", "status", "preconditions",
                            "steps", "api", "expected", "tags", "source", "author",
                        }),
                    ))
                except QaError as exc:
                    errors.append({"index": index, "error": str(exc)})
            return _ok({"cases": created, "errors": errors, "created": len(created)})
        if path == "/api/qa/cases/update":
            case = store.update_case(_require_id(payload), **_fields(payload, {
                "title", "kind", "code", "priority", "status", "preconditions", "steps",
                "api", "expected", "tags", "source", "author",
            }))
            return _ok({"case": case})
        if path == "/api/qa/cases/delete":
            store.delete_case(_require_id(payload))
            return _ok({"deleted": True})
        if path == "/api/qa/cases/import":
            project_id = _require_field(payload, "project_id")
            result = store.import_cases(project_id, payload.get("payload", payload.get("cases")))
            return _ok(result)
        if path == "/api/qa/scripts/create":
            script = store.create_script(
                _require_field(payload, "project_id"),
                **_fields(payload, {
                    "name", "content", "framework", "language", "file_path",
                    "case_ids", "tags", "status",
                }),
            )
            return _ok({"script": script})
        if path == "/api/qa/scripts/update":
            script = store.update_script(_require_id(payload), **_fields(payload, {
                "name", "content", "framework", "language", "file_path",
                "case_ids", "tags", "status",
            }))
            return _ok({"script": script})
        if path == "/api/qa/scripts/delete":
            store.delete_script(_require_id(payload))
            return _ok({"deleted": True})
        if path == "/api/qa/tasks/create":
            task = store.create_task(
                title=_require_field(payload, "title"),
                prompt=payload.get("prompt", ""),
                role=payload.get("role", "orchestrator"),
                project_id=payload.get("project_id") or None,
                parent_id=payload.get("parent_id") or None,
                status=payload.get("status", "queued"),
                progress=int(payload.get("progress") or 0),
            )
            return _ok({"task": task})
        if path == "/api/qa/tasks/update":
            task = store.update_task(_require_id(payload), **_fields(payload, {
                "title", "prompt", "status", "progress", "result", "session_key",
                "subagent_task_id", "role", "project_id", "parent_id",
            }))
            return _ok({"task": task})
        if path == "/api/qa/tasks/cancel":
            task = store.update_task(_require_id(payload), status="cancelled")
            return _ok({"task": task})
        if path in {"/api/qa/tasks/approve", "/api/qa/tasks/reject"}:
            task = store.decide_task(
                _require_id(payload),
                approved=path.endswith("/approve"),
                note=str(payload.get("note") or ""),
                reviewer=str(payload.get("reviewer") or ""),
            )
            return _ok({"task": task})
        if path == "/api/qa/runs/start":
            project_id = _require_field(payload, "project_id")
            run_name = str(payload.get("name") or "")
            environment = str(payload.get("environment") or "")
            trigger = str(payload.get("trigger") or "manual")
            script_id = payload.get("script_id")
            if isinstance(script_id, str) and script_id:
                run = await asyncio.to_thread(
                    service.execute_script, store, project_id, script_id,
                    name=run_name, environment=environment, trigger=trigger,
                )
            else:
                case_ids = payload.get("case_ids")
                if case_ids is not None and not (
                    isinstance(case_ids, list) and all(isinstance(x, str) for x in case_ids)
                ):
                    raise QaValidationError("case_ids must be an array of case ids")
                kind = payload.get("kind")
                run = await asyncio.to_thread(
                    service.execute_cases, store, project_id,
                    case_ids=case_ids, kind=kind if isinstance(kind, str) else None,
                    name=run_name, environment=environment, trigger=trigger,
                )
            return _ok({"run": run})
        if path == "/api/qa/runs/import":
            project_id = _require_field(payload, "project_id")
            xml = payload.get("xml")
            if not isinstance(xml, str):
                raise QaValidationError("xml is required")
            run = await asyncio.to_thread(
                service.ingest_junit, store, project_id,
                xml=xml,
                name=str(payload.get("name") or ""),
                environment=str(payload.get("environment") or ""),
                trigger=str(payload.get("trigger") or "ci"),
            )
            return _ok({"run": run})
        return _error(404, "QA mutation route not found")


def _int_query(query: dict[str, list[str]], key: str, default: int) -> int:
    raw = _query_first(query, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _require_id(payload: dict[str, Any]) -> str:
    return _require_field(payload, "id")


def _require_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise QaValidationError(f"{key} is required")
    return value.strip()


def _fields(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: payload[key] for key in allowed if key in payload}


def mutation_action_names() -> list[str]:
    """Expose registered actions for diagnostics and tests."""
    return sorted(QA_MUTATION_PATHS)


__all__ = [
    "QA_MUTATION_PATHS",
    "QA_WRITE_PATHS",
    "QaApi",
    "mutation_action_names",
]

# Keep the Awaitable import meaningful for typed callers adding handlers.
_Handler = Callable[[], Awaitable[None]]
