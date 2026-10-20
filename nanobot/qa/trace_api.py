"""P4: the QA workbench adapter over the ``qa_trace`` domain library.

The workbench must not grow a second implementation of the trace rules: coverage,
``needs_recheck``, impact, drafts and failure tracing are all computed by
:mod:`qa_trace` and this module only *selects a project* and *shapes the answer*
for ``/api/qa/trace/*``.  Every function here is a thin call into the library:

==============================  ==============================================
route                           library call
==============================  ==============================================
``GET  summary``                ``run_check`` + ``build_report`` + derived blocks
``GET  tree``                   ``load_project`` + ``build_graph`` + ``recheck_map``
``GET  impact``                 ``compute_impact``
``GET  stale``                  ``compute_stale``
``GET  drafts``                 ``list_drafts``
``GET  failure``                ``compute_failure``
``GET  runs``                   ``load_manifest`` over ``runs/*/manifest.json``
``GET  projects``               directory scan + ``load_project``
``POST stale/write``            ``compute_stale(write=True)``
``POST review/approve``         ``approve``
``POST review/reject``          ``reject``
==============================  ==============================================

Projects live under :data:`TRACE_ROOT_ENV` (default ``<repo>/qa-workbench/projects``)
and one project is ``projects/<project-id>/``, exactly the layout the CLI uses.
Reads are pure: they never write YAML and never change a review record.  Only the
three mutations change state, and each of them goes through the library function
that owns that state (``stale --write`` moves the baseline only; a review is a
separate, explicit act).

Error mapping follows the existing QA API contract: the library raises typed
``QaTraceError`` instances, which are translated into ``QaNotFoundError`` (404),
``QaConflictError`` (409) or ``QaValidationError`` (400) here, so
``nanobot.qa.http.QaApi.dispatch`` reports them with the same shape as every other
QA route.
"""

from __future__ import annotations

import functools
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from loguru import logger

from nanobot.qa.validation import (
    QaConflictError,
    QaError,
    QaNotFoundError,
    QaValidationError,
)
from qa_trace import __version__ as qa_trace_version
from qa_trace import (
    approve,
    build_graph,
    build_report,
    compute_failure,
    compute_impact,
    compute_stale,
    list_drafts,
    load_manifest,
    load_project,
    recheck_map,
    reject,
    resolve_script_target,
    run_check,
)
from qa_trace.errors import (
    DraftBaseMismatchError,
    DraftIdConflictError,
    DraftNotFoundError,
    EntityNotFoundError,
    ProjectError,
    QaTraceError,
    ReviewBlockedError,
    RunInvalidError,
    RunNotFoundError,
    TraceIndexError,
)
from qa_trace.failure import MANIFEST_FILENAME, RUNS_DIRNAME
from qa_trace.models import Source

#: Environment variable pointing at the directory that holds trace projects.
TRACE_ROOT_ENV = "NANOBOT_QA_TRACE_ROOT"

#: URL prefix owned by this adapter (under the QA API prefix).
TRACE_PREFIX = "/api/qa/trace"

#: Version of the JSON documents produced here (bumped with a shape change).
TRACE_API_VERSION = 1

_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Project metadata file the loader requires.
_PROJECT_FILE = "project.yaml"

#: Errors that mean "the ID/run/project does not exist" -> HTTP 404.
_NOT_FOUND = (EntityNotFoundError, DraftNotFoundError, RunNotFoundError)

#: Errors that mean "the operation conflicts with current state" -> HTTP 409.
_CONFLICT = (DraftIdConflictError, DraftBaseMismatchError, ReviewBlockedError)


def default_trace_root() -> Path:
    """Return the configured trace project root.

    ``NANOBOT_QA_TRACE_ROOT`` wins so tests, demos and another data directory can
    be used without touching the checkout.  The default is
    ``<repo>/qa-workbench/projects``, next to the committed ``login-lock`` demo.
    """
    override = os.environ.get(TRACE_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / "qa-workbench" / "projects"


def _translate(error: QaTraceError) -> QaError:
    """Map one library error onto the QA API's HTTP error classes."""
    message = error.format()
    if isinstance(error, _NOT_FOUND):
        return QaNotFoundError(message)
    if isinstance(error, _CONFLICT):
        return QaConflictError(message)
    if isinstance(error, (ProjectError, TraceIndexError, RunInvalidError)):
        return QaValidationError(message)
    return QaValidationError(message)


_Method = TypeVar("_Method", bound=Callable[..., Any])


def _api_errors(method: _Method) -> _Method:
    """Translate every library error raised by one adapter call."""

    @functools.wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except QaError:
            raise
        except QaTraceError as exc:
            raise _translate(exc) from None
        except OSError as exc:  # pragma: no cover - an unreadable directory
            raise QaValidationError(f"trace project I/O failed: {exc}") from None

    return wrapper  # type: ignore[return-value]


def _require_id(payload: Mapping[str, Any], key: str = "id") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise QaValidationError(f"{key} is required")
    return value.strip()


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise QaValidationError(f"{key} must be a string")
    text = value.strip()
    return text or None


def _project_block(root: Path, project: Any | None = None) -> dict[str, Any]:
    """Return the ``project`` object shared by every trace payload."""
    config = getattr(project, "config", None)
    return {
        "id": config.project_id if config is not None else root.name,
        "name": config.name if config is not None else None,
        "root": root.as_posix(),
        "modules": list(config.modules) if config is not None else [],
    }


def _ratio_percent(ratio: Mapping[str, Any] | None) -> float | None:
    return ratio.get("percent") if isinstance(ratio, Mapping) else None


def _source_entry(project: Any, source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "type": source.type.value,
        "title": source.title,
        "status": source.status.value,
        "confidence": source.confidence.value,
        "module": source.module,
        "owner": source.owner,
        "url": source.url,
        "app_version": source.app_version,
        "observed_at": source.observed_at.isoformat() if source.observed_at else None,
        "stale": source.stale,
        "evidence": [
            {
                "type": item.type.value,
                "locator": item.locator,
                "description": item.description,
                "verified": item.verified.value if item.verified is not None else None,
            }
            for item in source.evidence
        ],
    }


def _script_entry(project: Any, case: Any) -> dict[str, Any] | None:
    binding = case.automation.script
    if binding is None:
        return None
    target = resolve_script_target(project.root, binding)
    return {
        "case_id": case.id,
        "binding": binding.script,
        "file": binding.file,
        "nodeid": binding.nodeid,
        "resolves": target.ok,
        "problem": None if target.ok else target.message,
    }


def _case_entry(
    project: Any, case: Any, *, rechecks: Mapping[str, Any]
) -> dict[str, Any]:
    recheck = rechecks.get(case.id)
    script = _script_entry(project, case)
    return {
        "id": case.id,
        "title": case.title,
        "status": case.status.value,
        "priority": case.priority.value,
        "type": case.type.value,
        "automation": case.automation.status.value,
        "owner": case.owner,
        "tags": list(case.tags),
        "testpoints": list(case.testpoints),
        "sources": list(case.sources),
        "script": script,
        "needs_recheck": recheck is not None,
        "recheck_reasons": list(recheck.reasons) if recheck is not None else [],
        "changed_ids": list(recheck.changed_ids) if recheck is not None else [],
    }


def _testpoint_entry(project: Any, testpoint: Any, cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": testpoint.id,
        "title": testpoint.title,
        "status": testpoint.status.value,
        "method": testpoint.method.value,
        "risk": testpoint.risk.value,
        "module": testpoint.module,
        "owner": testpoint.owner,
        "sources": list(testpoint.sources),
        "cases": cases,
    }


def _run_summary(manifest: Mapping[str, Any], path: Path, root: Path) -> dict[str, Any]:
    results = [row for row in manifest.get("results", []) if isinstance(row, Mapping)]
    failed = {
        row.get("case_id")
        for row in results
        if isinstance(row.get("case_id"), str)
        and row.get("outcome") in {"failed", "error"}
    }
    try:
        shown = path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - manifests always live under the project
        shown = path.as_posix()
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "exitstatus": manifest.get("exitstatus"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "environment": manifest.get("environment"),
        "app_version": manifest.get("app_version"),
        "code_commit": manifest.get("code_commit"),
        "tool_version": manifest.get("tool_version"),
        "path": shown,
        "results": len(results),
        "failed_cases": len(failed),
        "failed_case_ids": sorted(failed),
    }


class TraceApi:
    """Read the trace chain and apply the three review mutations.

    ``root`` is only passed by tests and the demo; production uses
    :func:`default_trace_root` (evaluated per call, so changing the environment
    variable is enough to point the workbench somewhere else).
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None

    # -- project resolution ------------------------------------------------

    @property
    def root(self) -> Path:
        """Return the directory that holds ``<project-id>/`` directories."""
        return self._root if self._root is not None else default_trace_root()

    def _candidate_dirs(self) -> list[Path]:
        root = self.root
        if not root.is_dir():
            return []
        return sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and (path / _PROJECT_FILE).is_file()
        )

    def resolve_project(self, project_id: str | None = None) -> Path:
        """Return ``<root>/<project-id>``, raising 404 when it is not a project."""
        root = self.root
        if not root.is_dir():
            raise QaNotFoundError(f"trace project root not found: {root.as_posix()}")
        candidate = (project_id or "").strip()
        if not candidate:
            dirs = self._candidate_dirs()
            if not dirs:
                raise QaNotFoundError(
                    f"no trace project under {root.as_posix()}; set {TRACE_ROOT_ENV}"
                )
            return dirs[0]
        if not _PROJECT_ID_PATTERN.match(candidate):
            raise QaValidationError(
                "project may only use letters, digits, dot, dash and underscore"
            )
        path = root / candidate
        if not (path / _PROJECT_FILE).is_file():
            raise QaNotFoundError(f"unknown trace project {candidate!r} under {root.as_posix()}")
        return path

    # -- shared blocks -----------------------------------------------------

    def _rechecks(self, project: Any, graph: Any) -> dict[str, Any]:
        """Return the hash-based re-check map, or an empty map on a broken index."""
        try:
            return recheck_map(project, graph)
        except QaTraceError as exc:
            logger.warning("qa trace: recheck map unavailable: {}", exc.format())
            return {}

    def _stale_block(self, project: Any) -> dict[str, Any]:
        """Return the derived stale state used by the summary cards."""
        try:
            report = compute_stale(project)
        except QaTraceError as exc:
            return {"error": exc.format(), "baseline": None, "counts": {}, "needs_recheck": []}
        return {
            "error": None,
            "baseline": report.baseline,
            "counts": report.to_dict()["counts"],
            "needs_recheck": [item.to_dict() for item in report.needs_recheck],
        }

    def _drafts_block(self, project: Any) -> dict[str, Any]:
        """Return draft counts for the summary cards."""
        try:
            listing = list_drafts(project.root)
        except QaTraceError as exc:
            return {"error": exc.format(), "counts": {}, "batches": []}
        return {"error": None, "counts": listing.counts, "batches": sorted(
            {item.batch for item in listing.drafts}
        )}

    def _run_items(self, root: Path) -> tuple[list[dict[str, Any]], int]:
        """Return every readable run summary (newest first) and an error count."""
        runs_dir = root / RUNS_DIRNAME
        if not runs_dir.is_dir():
            return [], 0
        items: list[dict[str, Any]] = []
        unreadable = 0
        for manifest_path in sorted(runs_dir.glob(f"*/{MANIFEST_FILENAME}")):
            try:
                manifest = load_manifest(manifest_path)
            except QaTraceError as exc:
                logger.warning("qa trace: skipping run manifest: {}", exc.format())
                unreadable += 1
                continue
            items.append(_run_summary(manifest, manifest_path, root))
        items.sort(
            key=lambda item: (
                str(item.get("finished_at") or item.get("started_at") or ""),
                str(item.get("run_id") or ""),
            ),
            reverse=True,
        )
        return items, unreadable

    def _runs_block(self, root: Path) -> dict[str, Any]:
        items, unreadable = self._run_items(root)
        return {
            "error": None,
            "counts": {
                "runs": len(items),
                "failed_runs": sum(1 for item in items if item["failed_cases"]),
                "failed_cases": sum(item["failed_cases"] for item in items),
                "unreadable": unreadable,
            },
        }

    # -- reads -------------------------------------------------------------

    @_api_errors
    def list_projects(self) -> dict[str, Any]:
        """List the trace projects under the root (broken ones included, with error)."""
        root = self.root
        projects: list[dict[str, Any]] = []
        for path in self._candidate_dirs():
            entry: dict[str, Any] = {
                "id": path.name,
                "name": None,
                "root": path.as_posix(),
                "valid": None,
                "error": None,
            }
            try:
                project = load_project(path)
            except QaTraceError as exc:
                entry["valid"] = False
                entry["error"] = exc.format()
            else:
                entry["name"] = project.config.name
                entry["valid"] = True
                entry["modules"] = list(project.config.modules)
                entry["counts"] = {
                    "sources": len(project.sources),
                    "testpoints": len(project.testpoints),
                    "cases": len(project.cases),
                }
            projects.append(entry)
        return {
            "trace_version": TRACE_API_VERSION,
            "tool_version": qa_trace_version,
            "root": root.as_posix(),
            "projects": projects,
        }

    @_api_errors
    def summary(self, project_id: str | None = None) -> dict[str, Any]:
        """Return the report metrics plus the derived stale/draft/run counts."""
        root = self.resolve_project(project_id)
        result = run_check(root)
        report = build_report(result)
        payload: dict[str, Any] = {
            "trace_version": TRACE_API_VERSION,
            "tool_version": qa_trace_version,
            "project": _project_block(root, result.project),
            "valid": report["valid"],
            "counts": report["counts"],
            "coverage": report["coverage"],
            "requirement_gaps": report["requirement_gaps"],
            "requirement_gap_count": report["requirement_gap_count"],
            "dangling_count": report["dangling_count"],
            "dead_assets": report["dead_assets"],
            "needs_recheck": report["needs_recheck"],
            "metrics_suppressed": report["metrics_suppressed"],
            "diagnostics": report["diagnostics"],
            "stale": None,
            "drafts": None,
            "runs": None,
        }
        project = result.project
        if project is not None:
            payload["stale"] = self._stale_block(project)
            payload["drafts"] = self._drafts_block(project)
            payload["runs"] = self._runs_block(root)
        return payload

    @_api_errors
    def tree(self, project_id: str | None = None) -> dict[str, Any]:
        """Return the ``source -> testpoint -> case -> script`` chain."""
        root = self.resolve_project(project_id)
        project = load_project(root)
        graph = build_graph(project)
        rechecks = self._rechecks(project, graph)

        sources: list[dict[str, Any]] = []
        # One entry per (case, binding): a case reachable from two sources is
        # still one script, and the count must not depend on the number of paths.
        scripts: dict[tuple[str, str], dict[str, Any]] = {}
        for source_id in sorted(project.sources):
            source = project.sources[source_id]
            testpoints = []
            for testpoint_id in graph.downstream_testpoints(source_id):
                testpoint = project.testpoints[testpoint_id]
                cases = [
                    _case_entry(project, project.cases[case_id], rechecks=rechecks)
                    for case_id in graph.cases_of_testpoint(testpoint_id)
                ]
                testpoints.append(_testpoint_entry(project, testpoint, cases))
                for item in cases:
                    if item["script"] is not None:
                        script = item["script"]
                        scripts[(script["case_id"], script["binding"])] = script
            direct_cases = [
                _case_entry(project, project.cases[case_id], rechecks=rechecks)
                for case_id in graph.cases_of_source(source_id)
            ]
            for item in direct_cases:
                if item["script"] is not None:
                    script = item["script"]
                    scripts[(script["case_id"], script["binding"])] = script
            entry = _source_entry(project, source)
            entry["testpoints"] = testpoints
            entry["cases"] = direct_cases
            entry["case_count"] = len(direct_cases) + sum(
                len(item["cases"]) for item in testpoints
            )
            sources.append(entry)

        orphans = [
            _case_entry(project, project.cases[case_id], rechecks=rechecks)
            for case_id in sorted(project.cases)
            if graph.is_orphan(case_id)
        ]
        return {
            "trace_version": TRACE_API_VERSION,
            "tool_version": qa_trace_version,
            "project": _project_block(root, project),
            "counts": {
                "sources": len(project.sources),
                "testpoints": len(project.testpoints),
                "cases": len(project.cases),
                "scripts": len(scripts),
                "orphans": len(orphans),
            },
            "sources": sources,
            "orphans": orphans,
            "scripts": [scripts[key] for key in sorted(scripts)],
        }

    @_api_errors
    def impact(
        self,
        project_id: str | None = None,
        *,
        source: str | None = None,
        testpoint: str | None = None,
        case: str | None = None,
    ) -> dict[str, Any]:
        """Return the impact of one source, test point or case."""
        root = self.resolve_project(project_id)
        project = load_project(root)
        result = compute_impact(
            project, source=source, testpoint=testpoint, case=case
        )
        if result is None:
            selector = source or testpoint or case or ""
            kind = "source" if source else "test point" if testpoint else "case"
            raise EntityNotFoundError(
                f"{selector} is not a {kind} of this project", field="id"
            )
        return result.to_dict()

    @_api_errors
    def stale(self, project_id: str | None = None) -> dict[str, Any]:
        """Return what changed and which cases need a re-check."""
        root = self.resolve_project(project_id)
        project = load_project(root)
        return compute_stale(project).to_dict()

    @_api_errors
    def drafts(self, project_id: str | None = None, *, batch: str | None = None) -> dict[str, Any]:
        """Return the draft batches waiting for a human decision."""
        root = self.resolve_project(project_id)
        return list_drafts(root, batch=batch).to_dict()

    @_api_errors
    def failure(
        self, project_id: str | None = None, *, run: str | None, case: str | None = None
    ) -> dict[str, Any]:
        """Map one run's failed results back to the trace chain."""
        if not run or not run.strip():
            raise QaValidationError("run is required")
        root = self.resolve_project(project_id)
        project = load_project(root)
        return compute_failure(project, run.strip(), case_id=case).to_dict()

    @_api_errors
    def runs(self, project_id: str | None = None) -> dict[str, Any]:
        """List the recorded run manifests of a project, newest first."""
        root = self.resolve_project(project_id)
        project = load_project(root)
        items, unreadable = self._run_items(root)
        return {
            "trace_version": TRACE_API_VERSION,
            "tool_version": qa_trace_version,
            "project": _project_block(root, project),
            "counts": {
                "runs": len(items),
                "failed_runs": sum(1 for item in items if item["failed_cases"]),
                "failed_cases": sum(item["failed_cases"] for item in items),
                "unreadable": unreadable,
            },
            "items": items,
        }

    # -- mutations ---------------------------------------------------------

    @_api_errors
    def stale_write(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Record the current fingerprints as the new baseline (never approves)."""
        root = self.resolve_project(_optional_str(payload, "project"))
        project = load_project(root)
        report = compute_stale(project, write=True)
        return {"stale": report.to_dict()}

    @_api_errors
    def review_approve(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Promote one draft, or re-review one formal test point/case.

        ``ids`` promotes a whole batch in one call: every failure is reported per
        entity so one blocked draft (for example a test point whose source is
        still a draft) does not hide the ones that went through.
        """
        reviewer = _optional_str(payload, "reviewer")
        note = _optional_str(payload, "note")
        raw_ids = payload.get("ids")
        if raw_ids is None:
            entity_id = _require_id(payload)
            root = self.resolve_project(_optional_str(payload, "project"))
            outcome = approve(
                root,
                entity_id,
                batch=_optional_str(payload, "batch"),
                reviewer=reviewer,
                note=note,
            )
            return {"review": outcome.to_dict()}
        if not isinstance(raw_ids, list) or not raw_ids:
            raise QaValidationError("ids must be a non-empty array")
        root = self.resolve_project(_optional_str(payload, "project"))
        reviews: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for item in raw_ids:
            entity_id = str(item).strip()
            if not entity_id:
                continue
            try:
                outcome = approve(root, entity_id, reviewer=reviewer, note=note)
            except QaTraceError as exc:
                failed.append({"id": entity_id, "error": exc.format()})
                continue
            reviews.append(outcome.to_dict())
        return {"reviews": reviews, "approved": len(reviews), "failed": failed}

    @_api_errors
    def review_reject(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Record the rejection of one draft (the file stays in ``draft/``)."""
        entity_id = _require_id(payload)
        root = self.resolve_project(_optional_str(payload, "project"))
        outcome = reject(
            root,
            entity_id,
            batch=_optional_str(payload, "batch"),
            reviewer=_optional_str(payload, "reviewer"),
            note=_optional_str(payload, "note"),
        )
        return {"review": outcome.to_dict()}


__all__ = [
    "TRACE_API_VERSION",
    "TRACE_PREFIX",
    "TRACE_ROOT_ENV",
    "TraceApi",
    "default_trace_root",
]
