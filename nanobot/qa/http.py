"""HTTP routes for the QA platform (``/api/qa/*``).

Reads are ordinary authenticated GETs. Writes follow the WebUI CSRF design:
they are only accepted through the authenticated WebSocket mutation channel,
which marks the synthetic request and carries the JSON payload.

``/api/qa/trace/*`` is served by :mod:`nanobot.qa.trace_api`, which delegates to
the ``qa_trace`` domain library.  It lives under the same prefix on purpose: the
traceability chain is a tab of the existing workbench, not a second workbench,
and it reuses the same token check and the same mutation channel.

This module must not import ``nanobot.webui.ws_http`` (that module imports the
QA routes), so the mutation attribute names are repeated here exactly as the
WebUI transport defines them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, cast

from loguru import logger
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.qa import service
from nanobot.qa import testpoints as qa_testpoints
from nanobot.qa.case_files import CaseFiles, incremental_enabled
from nanobot.qa.store import QaStore
from nanobot.qa.testpoints import require_links_for_ready
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
    "qa.schedule.create": "/api/qa/schedules/create",
    "qa.schedule.update": "/api/qa/schedules/update",
    "qa.schedule.delete": "/api/qa/schedules/delete",
    "qa.schedule.run_now": "/api/qa/schedules/run-now",
    # P4: trace-chain review. ``stale_write`` only records a baseline; the two
    # review actions are the only way a draft enters the formal library.
    "qa.trace.stale_write": "/api/qa/trace/stale/write",
    "qa.trace.review_approve": "/api/qa/trace/review/approve",
    "qa.trace.review_reject": "/api/qa/trace/review/reject",
}

QA_WRITE_PATHS = frozenset(QA_MUTATION_PATHS.values())

#: Fields a case write may carry.  The first block is the legacy workbench
#: contract; the second is the trace link a case needs before it can leave
#: ``draft/`` for ``cases/``.
_CASE_WRITE_FIELDS = frozenset({
    "title",
    "kind",
    "code",
    "priority",
    "status",
    "preconditions",
    "steps",
    "api",
    "expected",
    "tags",
    "source",
    "author",
    "batch",
    "testpoints",
    "sources",
    "direct_reason",
    "risk",
    "postconditions",
    "owner",
    "note",
})



def _refresh_after_review(
    library: CaseFiles, root: Path, result: Mapping[str, Any]
) -> None:
    """Refresh only the reviewed entity after a trace review.

    Approving a draft moves its file from ``draft/`` to ``cases/``; the derived
    row and its trace summary must follow.  A failed incremental refresh falls
    back to the full project reindex, because the review itself already
    succeeded.
    """
    reviews = result.get("reviews")
    if not isinstance(reviews, list):
        review = result.get("review")
        reviews = [review] if isinstance(review, Mapping) else []
    if not reviews:
        return
    try:
        qa_project = next(
            (
                project
                for project in library.store.list_projects()
                if library.project_dir(project).resolve() == root.resolve()
            ),
            None,
        )
    except OSError:  # pragma: no cover - the directory vanished mid-request
        qa_project = None
    if qa_project is None:
        logger.warning(
            "qa cases: no QA project owns trace root {}", root.as_posix()
        )
        return
    if not incremental_enabled():
        library.reindex(project_id=qa_project["id"])
        return
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        entity_id = review.get("id")
        kind = review.get("kind")
        if not isinstance(entity_id, str) or kind not in {
            "source",
            "testpoint",
            "case",
        }:
            continue
        try:
            library.refresh_trace_entity(qa_project["id"], kind, entity_id)
        except Exception:  # pragma: no cover - the write already succeeded
            logger.warning(
                "qa cases: incremental refresh after review failed", exc_info=True
            )
            try:
                library.reindex(project_id=qa_project["id"])
            except Exception:
                logger.warning("qa cases: reindex after review failed", exc_info=True)
            return


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
        trace_root: str | Path | None = None,
    ) -> None:
        self.store = store
        self._check_api_token = check_api_token
        # None keeps the environment-driven default (NANOBOT_QA_TRACE_ROOT);
        # tests and demos point the adapter at a temporary project root.
        self.trace_root = trace_root
        self._trace_api: Any = None
        self._case_files: CaseFiles | None = None

    # -- YAML case library -------------------------------------------------

    def _cases(self) -> CaseFiles:
        """Return the YAML-backed case library (SQLite only indexes it)."""
        if self._case_files is None:
            self._case_files = CaseFiles(self.store, self.trace_root)
        return self._case_files

    # -- trace adapter -----------------------------------------------------

    def _trace(self) -> Any:
        """Return the lazily created trace adapter (imported on first use)."""
        if self._trace_api is None:
            from nanobot.qa.trace_api import TraceApi

            self._trace_api = TraceApi(self.trace_root)
        return self._trace_api

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
        if path == f"{QA_PREFIX}/trace" or path.startswith(f"{QA_PREFIX}/trace/"):
            return self._dispatch_trace_read(path, query)
        if path == f"{QA_PREFIX}/health":
            return _ok({"store": str(store.path)})
        if path == f"{QA_PREFIX}/overview":
            return _ok(store.overview())
        if path == f"{QA_PREFIX}/projects":
            return _ok({"projects": store.list_projects()})
        if path.startswith(f"{QA_PREFIX}/projects/"):
            return _ok({"project": store.get_project(path.rsplit("/", 1)[-1])})
        if path == f"{QA_PREFIX}/cases/export":
            payload = self._cases().export_cases(_query_first(query, "project_id") or None)
            return _ok(payload)
        if path == f"{QA_PREFIX}/cases/facets":
            return _ok(store.list_case_facets(
                _query_first(query, "project_id") or None
            ))
        if path == f"{QA_PREFIX}/cases":
            return _ok(self._cases().list_cases(
                project_id=_query_first(query, "project_id") or None,
                module_id=(
                    _query_first(query, "module_id")
                    or _query_first(query, "module")
                    or None
                ),
                operation_id=(
                    _query_first(query, "operation_id")
                    or _query_first(query, "operation")
                    or None
                ),
                kind=_query_first(query, "kind") or None,
                status=_query_first(query, "status") or None,
                query=(
                    _query_first(query, "q")
                    or _query_first(query, "query")
                    or None
                ),
                limit=_int_query(query, "limit", 50),
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
        if path == f"{QA_PREFIX}/testpoints":
            project_id = _query_first(query, "project_id")
            if not project_id:
                raise QaValidationError("project_id is required")
            return _ok(qa_testpoints.list_assets(store, project_id))
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
            return _ok({"case": self._cases().get_case(path.rsplit("/", 1)[-1])})
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
        if path == f"{QA_PREFIX}/schedules":
            return _ok({"items": store.list_schedules(
                project_id=_query_first(query, "project_id") or None,
            )})
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

    # -- trace reads -------------------------------------------------------

    def _dispatch_trace_read(
        self, path: str, query: dict[str, list[str]]
    ) -> Response:
        """Serve ``/api/qa/trace/*`` from the qa_trace domain library."""
        trace = self._trace()
        route = path[len(f"{QA_PREFIX}/trace"):].strip("/")
        project = _query_first(query, "project") or None
        if route == "projects":
            return _ok(trace.list_projects())
        if route == "summary":
            return _ok(trace.summary(project))
        if route == "tree":
            return _ok(trace.tree(project))
        if route == "impact":
            return _ok(trace.impact(
                project,
                source=_query_first(query, "source") or None,
                testpoint=_query_first(query, "testpoint") or None,
                case=_query_first(query, "case") or None,
            ))
        if route == "stale":
            return _ok(trace.stale(project))
        if route == "drafts":
            return _ok(trace.drafts(project, batch=_query_first(query, "batch") or None))
        if route == "failure":
            return _ok(trace.failure(
                project,
                run=_query_first(query, "run") or None,
                case=_query_first(query, "case") or None,
            ))
        if route == "runs":
            return _ok(trace.runs(project))
        raise QaNotFoundError(f"QA trace route not found: {path}")

    # -- writes ------------------------------------------------------------

    async def _dispatch_write(self, request: WsRequest, path: str) -> Response:
        if not getattr(request, _MUTATION_REQUEST_ATTR, False):
            return _error(405, "WebUI mutation requires an authenticated WebSocket")
        payload = _mutation_payload(request)
        if payload is None:
            return _error(400, "missing mutation payload")
        store = self.store
        if path.startswith(f"{QA_PREFIX}/trace/"):
            trace = self._trace()
            if path == "/api/qa/trace/stale/write":
                return _ok(await asyncio.to_thread(trace.stale_write, payload))
            if path == "/api/qa/trace/review/approve":
                root = trace.resolve_project(str(payload.get("project") or "") or None)
                result = await asyncio.to_thread(trace.review_approve, payload)
                _refresh_after_review(self._cases(), root, result)
                return _ok(result)
            if path == "/api/qa/trace/review/reject":
                root = trace.resolve_project(str(payload.get("project") or "") or None)
                result = await asyncio.to_thread(trace.review_reject, payload)
                _refresh_after_review(self._cases(), root, result)
                return _ok(result)
            return _error(404, "QA trace mutation route not found")
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
            require_links_for_ready(
                payload.get("status") or "draft",
                payload.get("testpoints"),
                payload.get("sources"),
                payload.get("direct_reason"),
            )
            case = self._cases().create_case(
                (_require_field(payload, "project_id")),
                **_fields(payload, _CASE_WRITE_FIELDS),
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
                    created.append(self._cases().create_case(
                        project_id,
                        **_fields(item, _CASE_WRITE_FIELDS),
                    ))
                except QaError as exc:
                    errors.append({"index": index, "error": str(exc)})
            return _ok({"cases": created, "errors": errors, "created": len(created)})
        if path == "/api/qa/cases/update":
            if payload.get("status") == "ready":
                current = self._cases().get_case(_require_id(payload))
                require_links_for_ready(
                    "ready",
                    payload.get("testpoints", current.get("testpoints")),
                    payload.get("sources", current.get("sources")),
                    payload.get("direct_reason", current.get("direct_reason")),
                )
            case = self._cases().update_case(
                _require_id(payload), **_fields(payload, _CASE_WRITE_FIELDS)
            )
            return _ok({"case": case})
        if path == "/api/qa/cases/delete":
            self._cases().delete_case(
                _require_id(payload),
                reason=str(payload.get("reason") or "") or None,
                reviewer=str(payload.get("reviewer") or "") or None,
            )
            return _ok({"deleted": True})
        if path == "/api/qa/cases/import":
            project_id = _require_field(payload, "project_id")
            result = self._cases().import_cases(
                project_id,
                payload.get("payload", payload.get("cases")),
                mode=str(payload.get("mode") or "compat"),
            )
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
        if path == "/api/qa/schedules/create":
            schedule = store.create_schedule(
                _require_field(payload, "project_id"),
                name=_require_field(payload, "name"),
                cron=_require_field(payload, "cron"),
                timezone=str(payload.get("timezone") or ""),
                enabled=payload.get("enabled", True),
                target=payload.get("target"),
            )
            return _ok({"schedule": schedule})
        if path == "/api/qa/schedules/update":
            schedule_id = _require_id(payload)
            updates = _fields(
                payload, {"name", "cron", "timezone", "enabled", "target"},
            )
            return _ok({"schedule": store.update_schedule(schedule_id, **updates)})
        if path == "/api/qa/schedules/delete":
            store.delete_schedule(_require_id(payload))
            return _ok({"deleted": True})
        if path == "/api/qa/schedules/run-now":
            from nanobot.qa.scheduler import run_schedule

            schedule = store.get_schedule(_require_id(payload))
            run = await asyncio.to_thread(run_schedule, store, schedule)
            store.record_schedule_run(
                schedule["id"], run_id=run["id"], status=run["status"],
            )
            return _ok({"run": run, "schedule": store.get_schedule(schedule["id"])})
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
