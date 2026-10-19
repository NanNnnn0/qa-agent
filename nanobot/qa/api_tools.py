"""MCP-facing tools for the API asset workflow.

The stdio MCP server exposes these directly. They are plain classes rather than
agent-runtime tools so this module stays free of the runtime: business logic
lives in :mod:`nanobot.qa.store` and :mod:`nanobot.qa.catalog`, and the tests can
call ``execute`` without a model or a gateway.

Both tools answer with a JSON string and report validation problems as
``{"error": ...}`` so a model can correct its call instead of losing the turn.
"""

from __future__ import annotations

import json
from typing import Any

from nanobot.qa import catalog, execution
from nanobot.qa.store import QaStore
from nanobot.qa.util import utcnow_iso
from nanobot.qa.validation import (
    EVIDENCE_KINDS,
    QaError,
    QaValidationError,
    require_enum,
)

CATALOG_ACTIONS = ("ingest", "list", "get", "diff")
WORKFLOW_ACTIONS = ("create", "get", "validate", "submit", "apply", "resume", "export")
RUN_ACTIONS = ("preflight", "start", "get")
_LIST_DEFAULT = 10
_LIST_MAX = 50


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise QaValidationError(f"{field} must be a string")
    return value.strip()


def _count(value: Any, field: str, *, default: int) -> int:
    if value is None or value == "":
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QaValidationError(f"{field} must be a non-negative integer")
    return value


class _QaApiTool:
    """Shared plumbing: store resolution, schema shape and error reporting."""

    name = ""
    description = ""
    parameters: dict[str, Any] = {}

    def __init__(self, store: QaStore | None = None) -> None:
        self._injected_store = store

    def _store(self) -> QaStore:
        if self._injected_store is not None:
            return self._injected_store
        from nanobot.qa import shared_store

        return shared_store()

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        action = _text(kwargs.get("action"), "action")
        try:
            payload = self._run(action, kwargs)
        except QaError as exc:
            return _dumps({"action": action or None, "error": str(exc)})
        return _dumps(payload)

    def _run(self, action: str, kwargs: dict[str, Any]) -> Any:
        raise NotImplementedError


class QaApiCatalogTool(_QaApiTool):
    """Register and read the project's API reference catalog."""

    name = "qa_api_catalog"
    description = (
        "API reference catalog: ingest or diff an OpenAPI 3.0/3.1 document (JSON or YAML) "
        "and report added, changed and missing operations; list or get one operation with "
        "its normalized spec and evidence pointers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(CATALOG_ACTIONS),
                "description": "ingest | list | get | diff",
            },
            "project_id": {
                "type": "string",
                "description": "proj_... (ingest, diff)",
            },
            "operation_id": {
                "type": "string",
                "description": "op_... (get)",
            },
            "document": {
                "type": "string",
                "description": "OpenAPI JSON or YAML text.",
            },
            "source_path": {
                "type": "string",
                "description": (
                    "OpenAPI file under NANOBOT_QA_SPEC_ROOTS."
                ),
            },
            "source_kind": {
                "type": "string",
                "enum": list(EVIDENCE_KINDS),
                "description": "Evidence kind (default spec).",
            },
            "source_ref": {
                "type": "string",
                "description": "Evidence ref (commit, URL).",
            },
            "source_version": {
                "type": "string",
                "description": "Material version.",
            },
            "query": {
                "type": "string",
                "description": "Match path, summary or operationId.",
            },
            "method": {
                "type": "string",
                "description": "HTTP method filter.",
            },
            "status": {
                "type": "string",
                "enum": ["active", "missing"],
                "description": "active | missing",
            },
            "limit": {
                "type": "integer",
                "description": f"Page size (default {_LIST_DEFAULT}, max {_LIST_MAX}).",
            },
            "offset": {
                "type": "integer",
                "description": "Page offset.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def _run(self, action: str, kwargs: dict[str, Any]) -> Any:
        if action in ("ingest", "diff"):
            return self._ingest_or_diff(action, kwargs)
        if action == "list":
            return self._list(kwargs)
        if action == "get":
            return self._get(kwargs)
        raise QaValidationError(f"action must be one of {', '.join(CATALOG_ACTIONS)}")

    def _ingest_or_diff(self, action: str, kwargs: dict[str, Any]) -> Any:
        store = self._store()
        project_id = _text(kwargs.get("project_id"), "project_id")
        if not project_id:
            raise QaValidationError("project_id is required")
        operations, source = self._material(kwargs)
        if action == "diff":
            result = store.diff_api_operations(project_id, operations)
            return {"action": "diff", "source": source, **result}
        result = store.ingest_api_operations(
            project_id,
            operations,
            source_kind=source.get("kind", ""),
            source_ref=source.get("ref", ""),
            source_version=source.get("version", ""),
        )
        return {"action": "ingest", "source": source, **result}

    def _material(self, kwargs: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        source_path = _text(kwargs.get("source_path"), "source_path")
        if source_path:
            text, source = catalog.read_local_source(
                source_path, allowed_roots=catalog.configured_roots()
            )
            return catalog.parse_openapi(text, source=source), source
        document = kwargs.get("document")
        if document is None or document == "":
            raise QaValidationError(
                "document or source_path is required; set NANOBOT_QA_SPEC_ROOTS to read files"
            )
        source: dict[str, str] = {
            "kind": require_enum(
                kwargs.get("source_kind"), "source_kind", EVIDENCE_KINDS, default="spec",
            ),
            "ref": _text(kwargs.get("source_ref"), "source_ref") or "inline",
        }
        version = _text(kwargs.get("source_version"), "source_version")
        if version:
            source["version"] = version
        return catalog.parse_openapi(document, source=source), source

    def _list(self, kwargs: dict[str, Any]) -> Any:
        store = self._store()
        limit = _count(kwargs.get("limit"), "limit", default=_LIST_DEFAULT)
        page = store.list_api_operations(
            _text(kwargs.get("project_id"), "project_id") or None,
            query=_text(kwargs.get("query"), "query") or None,
            method=_text(kwargs.get("method"), "method") or None,
            status=_text(kwargs.get("status"), "status") or None,
            limit=max(1, min(limit, _LIST_MAX)),
            offset=_count(kwargs.get("offset"), "offset", default=0),
        )
        return {"action": "list", **page}

    def _get(self, kwargs: dict[str, Any]) -> Any:
        operation_id = _text(kwargs.get("operation_id"), "operation_id")
        if not operation_id:
            raise QaValidationError("operation_id is required")
        return {"action": "get", "operation": self._store().get_api_operation(operation_id)}


class QaApiWorkflowTool(_QaApiTool):
    """Stage, check and apply a batch of API cases."""

    name = "qa_api_workflow"
    description = (
        "Staged API case batch: create, validate, submit, apply, resume or export. apply "
        "writes cases, catalog links and revisions in one transaction; export returns the "
        "batch plus its case revisions as a snapshot for Git."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(WORKFLOW_ACTIONS),
                "description": "create | get | validate | submit | apply | resume | export",
            },
            "workflow_id": {
                "type": "string",
                "description": "wf_... (all but create)",
            },
            "project_id": {
                "type": "string",
                "description": "proj_... (create)",
            },
            "candidates": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "Items {case, operation?, scenario_key?, evidence?, base_revision?}; "
                    "case is the structured case body."
                ),
            },
            "idempotency_key": {
                "type": "string",
                "description": "Same key returns the same workflow.",
            },
            "kind": {
                "type": "string",
                "description": "Batch kind, default api_cases.",
            },
            "base": {
                "type": "object",
                "description": "Base marker, e.g. catalog source version.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def _run(self, action: str, kwargs: dict[str, Any]) -> Any:
        store = self._store()
        if action == "create":
            return self._create(store, kwargs)
        workflow_id = _text(kwargs.get("workflow_id"), "workflow_id")
        if not workflow_id:
            raise QaValidationError("workflow_id is required")
        if action == "get":
            return {"action": "get", "workflow": self._summary(store.get_api_workflow(workflow_id))}
        if action == "validate":
            return {"action": "validate", **store.validate_api_workflow(workflow_id)}
        if action == "submit":
            workflow = store.replace_api_workflow_candidates(
                workflow_id, kwargs.get("candidates")
            )
            return {"action": "submit", "workflow": self._summary(workflow)}
        if action == "apply":
            workflow = store.apply_api_workflow(workflow_id)
            return {"action": "apply", "workflow": self._summary(workflow)}
        if action == "resume":
            return self._resume(store, workflow_id)
        if action == "export":
            return self._export(store, workflow_id)
        raise QaValidationError(f"action must be one of {', '.join(WORKFLOW_ACTIONS)}")

    def _create(self, store: QaStore, kwargs: dict[str, Any]) -> Any:
        project_id = _text(kwargs.get("project_id"), "project_id")
        if not project_id:
            raise QaValidationError("project_id is required")
        workflow = store.create_api_workflow(
            project_id,
            candidates=kwargs.get("candidates"),
            idempotency_key=_text(kwargs.get("idempotency_key"), "idempotency_key"),
            kind=_text(kwargs.get("kind"), "kind") or "api_cases",
            base=kwargs.get("base"),
        )
        return {"action": "create", "workflow": self._summary(workflow)}

    def _resume(self, store: QaStore, workflow_id: str) -> Any:
        workflow = store.get_api_workflow(workflow_id)
        result = workflow.get("result") or {}
        errors = result.get("errors") or []
        next_action = {
            "pending": "apply",
            "failed": "submit" if errors else "apply",
            "applied": "none",
        }.get(workflow["status"], "apply")
        return {
            "action": "resume",
            "workflow_id": workflow_id,
            "status": workflow["status"],
            "errors": errors,
            "checkpoint": workflow.get("checkpoint") or {},
            "result": result,
            "next_action": next_action,
        }

    def _export(self, store: QaStore, workflow_id: str) -> Any:
        workflow = store.get_api_workflow(workflow_id)
        checkpoint = workflow.get("checkpoint") or {}
        entries = list(checkpoint.get("applied") or []) + list(checkpoint.get("updated") or [])
        cases: list[dict[str, Any]] = []
        for entry in entries:
            case_id = entry.get("case_id")
            revision = entry.get("revision")
            if not case_id or not revision:
                continue
            stored = store.get_case_revision(case_id, int(revision))
            cases.append({
                "case_id": case_id,
                "revision": revision,
                "content_hash": stored["content_hash"],
                "snapshot": stored["snapshot"],
            })
        return {
            "action": "export",
            "format": "qa-agent.api-workflow.v1",
            "exported_at": utcnow_iso(),
            "workflow_id": workflow["id"],
            "project_id": workflow["project_id"],
            "kind": workflow["kind"],
            "status": workflow["status"],
            "base": workflow.get("base") or {},
            "candidates": workflow.get("candidates") or [],
            "checkpoint": checkpoint,
            "result": workflow.get("result") or {},
            "cases": cases,
        }

    def _summary(self, workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": workflow["id"],
            "project_id": workflow["project_id"],
            "kind": workflow["kind"],
            "status": workflow["status"],
            "candidate_count": len(workflow.get("candidates") or []),
            "checkpoint": workflow.get("checkpoint") or {},
            "result": workflow.get("result") or {},
        }


class QaApiRunTool(_QaApiTool):
    """Preflight and run API cases with a pinned snapshot."""

    name = "qa_api_run"
    description = (
        "Pinned API runs. preflight reports every blocker (case not ready, no request, no "
        "assertions, unresolved variable, stale catalog reference, auth config) without sending "
        "a request; start runs the selected ready cases through the fixed pytest template, pins "
        "their revisions, batches more than 200 cases and masks credentials, and returns a "
        "running run unless wait is true; get returns one run summary with its failed tests."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(RUN_ACTIONS),
                "description": "preflight | start | get",
            },
            "project_id": {
                "type": "string",
                "description": "proj_... (preflight, start)",
            },
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Explicit case ids in run order; omit to select by kind. Not with plan."
                ),
            },
            "plan": {
                "type": "object",
                "description": (
                    "Ordered {version, setup, cases, cleanup}; steps are {case_id, revision?}. "
                    "A pinned revision must match the current revision."
                ),
            },
            "kind": {
                "type": "string",
                "enum": ["api", "ui", "manual"],
                "description": "Restrict the implicit selection.",
            },
            "auth": {
                "type": "object",
                "description": (
                    "{kind: none|bearer|login, token, path, body, token_path, header, prefix}; "
                    "env:NAME allowed, credentials are never persisted."
                ),
            },
            "name": {
                "type": "string",
                "description": "Run name.",
            },
            "environment": {
                "type": "string",
                "description": "Environment label.",
            },
            "run_id": {
                "type": "string",
                "description": "run_... (get)",
            },
            "wait": {
                "type": "boolean",
                "description": (
                    "Block until the run settles (default false)."
                ),
            },
            "timeout_s": {
                "type": "number",
                "description": "Seconds to wait with wait (default 300).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def _run(self, action: str, kwargs: dict[str, Any]) -> Any:
        store = self._store()
        if action == "preflight":
            project_id = _text(kwargs.get("project_id"), "project_id")
            if not project_id:
                raise QaValidationError("project_id is required")
            checked = execution.preflight(
                store,
                project_id,
                case_ids=self._case_ids(kwargs),
                kind=_text(kwargs.get("kind"), "kind") or None,
                auth=self._auth(kwargs),
                plan=self._plan(kwargs),
            )
            return {"action": "preflight", **self._compact(checked)}
        if action == "start":
            project_id = _text(kwargs.get("project_id"), "project_id")
            if not project_id:
                raise QaValidationError("project_id is required")
            starter = (
                execution.execute_pinned
                if bool(kwargs.get("wait"))
                else execution.execute_pinned_async
            )
            run = starter(
                store,
                project_id,
                case_ids=self._case_ids(kwargs),
                kind=_text(kwargs.get("kind"), "kind") or None,
                auth=self._auth(kwargs),
                plan=self._plan(kwargs),
                name=_text(kwargs.get("name"), "name"),
                environment=_text(kwargs.get("environment"), "environment"),
                trigger="agent",
            )
            return {"action": "start", "run": execution.run_summary(run)}
        if action == "get":
            run_id = _text(kwargs.get("run_id"), "run_id")
            if not run_id:
                raise QaValidationError("run_id is required")
            if bool(kwargs.get("wait")):
                run = execution.wait_for_run(
                    store,
                    run_id,
                    timeout_s=float(kwargs.get("timeout_s") or 300),
                )
            else:
                run = store.get_run(run_id)
            return {"action": "get", "run": execution.run_summary(run)}
        raise QaValidationError(f"action must be one of {', '.join(RUN_ACTIONS)}")

    def _case_ids(self, kwargs: dict[str, Any]) -> list[str] | None:
        value = kwargs.get("case_ids")
        if value is None:
            return None
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise QaValidationError("case_ids must be an array of case ids")
        return [item.strip() for item in value]

    def _auth(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        value = kwargs.get("auth")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise QaValidationError("auth must be a JSON object")
        return value

    def _plan(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        value = kwargs.get("plan")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise QaValidationError("plan must be a JSON object")
        return value

    def _compact(self, checked: dict[str, Any]) -> dict[str, Any]:
        ready = checked.get("ready") or []
        blocked = checked.get("blocked") or []
        return {
            "project_id": checked["project_id"],
            "base_url": checked["base_url"],
            "plan_version": checked["plan_version"],
            "phases": checked["phases"],
            "ok": checked["ok"],
            "case_count": checked["case_count"],
            "ready_count": len(ready),
            "ready": ready[:20],
            "blocked_count": len(blocked),
            "blocked": blocked[:20],
            "blockers": checked["blockers"],
            "template_version": checked["template_version"],
        }


def api_tools() -> list[_QaApiTool]:
    """Return the API asset tools in a stable order."""
    return [QaApiCatalogTool(), QaApiWorkflowTool(), QaApiRunTool()]
