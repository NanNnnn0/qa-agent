"""The YAML case library: YAML is the source of truth, SQLite is the index.

The QA platform shipped its cases in SQLite.  That is no longer true: a case is a
YAML document under the trace project root, and the ``cases`` table is a derived
index rebuilt from those files.  This module is the one place that knows how the
old API shape (``kind``/``status``/``code`` …) maps onto a case file, so the
agent tool, ``/api/qa/cases*`` and the WebUI all keep the same JSON contract while
the bytes live in YAML.

Layout (inside ``<root>/<project-key-lower>/``, the same directory ``qa_trace``
reads):

``draft/<batch>/cases/<ID>.yaml``
    where every write starts: an agent-created or UI-created case is a draft.
``cases/<ID>.yaml``
    a reviewed case, part of the formal trace library.  A case only moves here
    when it has a test point or a source to hang off, because the trace model
    refuses an unlinked formal case.
``tombstones/<ID>.yaml``
    a deleted case: ``status: deprecated`` plus a ``tombstone`` block.  The ID is
    retired (the allocator scans this directory) and the case disappears from
    default listings, but the file stays so the deletion is auditable.

Every mutation writes YAML first and then rebuilds the derived rows of the
project (:meth:`CaseFiles.reindex`), so a reader that asks SQLite gets exactly
what the files say.  The old hand-written rows are never deleted: a YAML case
claims its ancestor through ``legacy_id``, and unclaimed rows stay readable (via
:class:`CaseFiles` fallbacks) until ``qa trace migrate-sqlite`` moves them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.qa.store import QaStore
from nanobot.qa.trace_api import default_trace_root
from nanobot.qa.util import utcnow_iso
from nanobot.qa.validation import (
    CASE_CODE_RE,
    CASE_KINDS,
    CASE_PRIORITIES,
    CASE_STATUSES,
    QaConflictError,
    QaError,
    QaNotFoundError,
    QaValidationError,
    normalize_tags,
    optional_text,
    require_enum,
    require_text,
    validate_api_spec,
    validate_steps,
)
from qa_trace import build_graph
from qa_trace.caseyaml import (
    KNOWN_CASE_KEYS,
    TOMBSTONES_DIRNAME,
    CaseDocumentError,
    automation_block,
    case_document,
    case_module,
    case_path_for,
    case_relative_path,
    derive_case_type,
    iter_case_documents,
    legacy_kind,
    next_case_id,
    read_case_document,
    write_case_document,
)
from qa_trace.compat import kind_for_type, legacy_for_status, status_for_legacy, type_for_kind
from qa_trace.errors import IdError, QaTraceError
from qa_trace.hashing import fingerprint_project
from qa_trace.ids import SOURCE_KINDS, IdKind, parse_id
from qa_trace.index import load_index_for_write, upsert_review, write_index
from qa_trace.labels import testpoint_codes
from qa_trace.loader import load_project
from qa_trace.models import Case
from qa_trace.staleness import recheck_map
from qa_trace.yamlfile import write_yaml

#: Project metadata file the loader requires (one per trace project).
PROJECT_FILE = "project.yaml"

#: Default file name of the SQLite database the migration reads.
SQLITE_FILENAME = "qa.sqlite3"

_PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")


def _stat_stamp(path: Path) -> str:
    """Return the file modification time as a UTC ISO timestamp."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:  # pragma: no cover - the file disappeared mid-scan
        return utcnow_iso()


def _as_id_list(value: Any, *, field: str) -> list[str]:
    """Validate one reference list (``testpoints`` / ``sources``)."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw = [str(item).strip() for item in value]
    else:
        raise QaValidationError(f"{field} must be an array of IDs")
    items = [item for item in raw if item]
    expected_kind = IdKind.TESTPOINT if field == "testpoints" else None
    for item in items:
        try:
            parsed = parse_id(item, field=field)
        except IdError:
            raise QaValidationError(f"{field} entry {item!r} is not a valid ID") from None
        if expected_kind is not None and parsed.kind is not expected_kind:
            raise QaValidationError(f"{field} entry {item!r} is not a test point ID")
        if expected_kind is None and parsed.kind not in SOURCE_KINDS:
            raise QaValidationError(f"{field} entry {item!r} is not a source ID")
    return list(dict.fromkeys(items))


def _steps_from_document(document: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return the case steps of a document as plain ``{action, expected}`` rows."""
    steps: list[dict[str, str]] = []
    raw = document.get("steps")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return steps
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        action = item.get("action")
        expected = item.get("expected")
        if isinstance(action, str) and action.strip():
            steps.append({
                "action": action.strip(),
                "expected": expected.strip() if isinstance(expected, str) else "",
            })
    return steps


def _assertion_summary(assertions: Sequence[Mapping[str, Any]]) -> str:
    """Return one line describing the assertions (used as a derived step)."""
    parts: list[str] = []
    for item in assertions[:4]:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "status":
            parts.append(f"HTTP {item.get('expect')}")
        elif kind == "json_path":
            parts.append(f"{item.get('path')} {item.get('op')} {item.get('expect')}".strip())
        elif kind == "header":
            parts.append(f"header {item.get('name')}")
        elif kind == "response_time_ms":
            parts.append(f"response <= {item.get('max')} ms")
        elif kind == "body_contains":
            parts.append(f"body contains {item.get('text')}")
    return "；".join(parts)


class CaseFiles:
    """Read and write the YAML case library of one QA platform store.

    ``root`` is only passed by tests and the CLI; production uses
    :func:`nanobot.qa.trace_api.default_trace_root` (``NANOBOT_QA_TRACE_ROOT``,
    else ``<repo>/qa-workbench/projects``).
    """

    def __init__(self, store: QaStore, root: str | Path | None = None) -> None:
        self.store = store
        self._root = Path(root) if root is not None else None
        self._indexed: set[str] = set()

    # -- project layout ----------------------------------------------------

    @property
    def root(self) -> Path:
        """Return the directory holding ``<project-key>/`` directories."""
        return self._root if self._root is not None else default_trace_root()

    def project_dir(self, project: Mapping[str, Any]) -> Path:
        """Return the trace project directory of a QA project row."""
        return self.root / str(project["key"]).lower()

    def ensure_project(self, project: Mapping[str, Any]) -> Path:
        """Return the trace project directory, writing ``project.yaml`` if absent."""
        directory = self.project_dir(project)
        path = directory / PROJECT_FILE
        if path.is_file():
            return directory
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml(
            path,
            {
                "schema_version": 1,
                "project_id": directory.name,
                "name": project.get("name") or directory.name,
                "modules": [case_module(str(project["key"]))],
            },
        )
        return directory

    @staticmethod
    def _read_document(case_id: str, path: Path) -> dict[str, Any]:
        """Read one case document, translating a broken file to a 400."""
        try:
            return read_case_document(path)
        except (OSError, QaTraceError, CaseDocumentError) as exc:
            raise QaValidationError(
                f"case {case_id} document is unreadable: {exc}"
            ) from None

    def _document_path(self, row: Mapping[str, Any], directory: Path) -> Path | None:
        relative = row.get("yaml_path")
        if isinstance(relative, str) and relative:
            return directory / relative
        return None

    def _document(self, row: Mapping[str, Any], directory: Path) -> dict[str, Any] | None:
        path = self._document_path(row, directory)
        if path is None or not path.is_file():
            return None
        try:
            return read_case_document(path)
        except (OSError, QaTraceError, CaseDocumentError, ValueError) as exc:
            logger.warning("qa cases: cannot read {}: {}", path, exc)
            return None

    # -- response shaping --------------------------------------------------

    def _case_payload(
        self,
        row: Mapping[str, Any],
        *,
        document: Mapping[str, Any] | None = None,
        needs_recheck: bool = False,
        recheck_reasons: Sequence[str] = (),
        legacy: bool = False,
        trace: Any = None,
    ) -> dict[str, Any]:
        """Return the legacy-shaped case object plus the trace badges."""
        document = document or {}
        testpoints = [
            str(item) for item in document.get("testpoints") or [] if str(item).strip()
        ]
        sources = [str(item) for item in document.get("sources") or [] if str(item).strip()]
        automation = document.get("automation")
        automation_status = (
            automation.get("status") if isinstance(automation, Mapping) else None
        )
        automation_status = automation_status or (
            "manual" if legacy_kind(str(row.get("kind") or "manual")) == "manual" else "todo"
        )
        binding = automation.get("script") if isinstance(automation, Mapping) else None
        yaml_path = str(row.get("yaml_path") or "")
        # The chain, resolved: a case hangs off test points, and a test point
        # hangs off sources.  The badge has to show the transitive roots or a
        # perfectly linked case still reads "missing source" (ADR 0012).
        trace_testpoints: list[dict[str, Any]] = []
        trace_sources: list[dict[str, Any]] = []
        group = document.get("group") if isinstance(document.get("group"), str) else None
        if trace is not None:
            codes = testpoint_codes(trace.testpoints.values())
            reachable = list(sources)
            for testpoint_id in testpoints:
                testpoint = trace.testpoints.get(testpoint_id)
                if testpoint is None:
                    continue
                trace_testpoints.append(
                    {
                        "id": testpoint.id,
                        "code": codes.get(testpoint.id, ""),
                        "title": testpoint.title,
                        "group": testpoint.group,
                        "risk": testpoint.risk.value,
                    }
                )
                group = group or testpoint.group
                for source_id in testpoint.sources:
                    if source_id not in reachable:
                        reachable.append(source_id)
            for source_id in reachable:
                source = trace.sources.get(source_id)
                trace_sources.append(
                    {
                        "id": source_id,
                        "title": source.title if source is not None else "",
                        "type": source.type.value if source is not None else "",
                        "direct": source_id in sources,
                    }
                )
        else:
            trace_sources = [
                {"id": item, "title": "", "type": "", "direct": True} for item in sources
            ]
        draft = yaml_path.startswith("draft/")
        batch = yaml_path.split("/")[1] if draft and yaml_path.count("/") >= 2 else None
        payload: dict[str, Any] = {
            "id": row["id"],
            "project_id": row["project_id"],
            "code": row.get("code") or row["id"],
            "title": row.get("title") or "",
            "kind": row.get("kind") or "manual",
            "priority": row.get("priority") or "P1",
            "status": row.get("status") or "draft",
            "preconditions": row.get("preconditions") or "",
            "steps": list(row.get("steps") or []),
            "api": dict(row.get("api") or {}),
            "expected": row.get("expected") or "",
            "tags": list(row.get("tags") or []),
            "source": row.get("source") or ("sqlite" if legacy else "yaml"),
            "author": row.get("author") or "",
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
            # Additive trace fields: the WebUI renders the chain from these.
            "type": str(document.get("type") or type_for_kind(row.get("kind"))),
            "automation": automation_status,
            "script": (
                {"binding": binding, "resolves": None}
                if isinstance(binding, str) and binding
                else None
            ),
            "testpoints": testpoints,
            "sources": sources,
            "group": group or None,
            "trace_testpoints": trace_testpoints,
            "trace_sources": trace_sources,
            "direct_reason": document.get("direct_reason"),
            "risk": document.get("risk"),
            "owner": document.get("owner"),
            "note": document.get("note"),
            "trace_status": status_for_legacy(row.get("status")),
            "draft": draft,
            "batch": batch,
            "yaml_path": yaml_path,
            "legacy_id": row.get("legacy_id") or document.get("legacy_id"),
            "legacy": legacy,
            "needs_links": not testpoints and not sources,
            "needs_recheck": needs_recheck,
            "recheck_reasons": list(recheck_reasons),
        }
        return payload

    def _trace_for(self, project: Mapping[str, Any]) -> Any:
        """Return the project's loaded trace library, or ``None`` when unreadable."""
        directory = self.project_dir(project)
        try:
            return load_project(directory)
        except QaTraceError as exc:
            logger.debug(
                "qa cases: trace library unavailable for {}: {}", directory, exc.format()
            )
            return None

    def _rechecks_for(self, library: Any) -> dict[str, Any]:
        """Return the hash-based re-check map of one loaded library."""
        if library is None:
            return {}
        try:
            return recheck_map(library, build_graph(library))
        except QaTraceError as exc:
            logger.debug("qa cases: recheck map unavailable: {}", exc.format())
            return {}

    def _recheck_map_for(self, project: Mapping[str, Any]) -> dict[str, Any]:
        """Return the hash-based re-check map of a project (empty when unreadable)."""
        return self._rechecks_for(self._trace_for(project))

    def _legacy_payload(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Return a hand-written SQLite row (read-only until it is migrated)."""
        return self._case_payload(row, legacy=True)

    # -- lookups -----------------------------------------------------------

    def _ensure_indexed(self, project_ids: Iterable[str]) -> int:
        """Build the derived index of projects that have YAML but no index rows.

        A library can arrive from disk (a git pull, ``qa trace migrate-sqlite``)
        without anyone running the reindex command; a project with YAML case files
        and zero derived rows is unambiguously "never indexed", so the read path
        builds it once instead of showing an empty list.  A project that already
        has rows is left alone: rebuilding after every external edit would make
        reads as expensive as writes.
        """
        rebuilt = 0
        for project_id in project_ids:
            if project_id in self._indexed:
                continue
            self._indexed.add(project_id)
            try:
                project = self.store.get_project(project_id)
            except QaError:  # pragma: no cover - deleted while listing
                continue
            directory = self.project_dir(project)
            if self.store.derived_case_count(project_id) > 0:
                continue
            if not any(
                True
                for _ in iter_case_documents(
                    directory, include_drafts=True, include_tombstones=True
                )
            ):
                continue
            self.reindex(project_id=project_id)
            rebuilt += 1
        return rebuilt

    def _all_project_ids(self) -> list[str]:
        return [str(project["id"]) for project in self.store.list_projects()]

    def _row(self, case_id: str) -> dict[str, Any]:
        row = self.store.get_case(case_id)
        if row.get("derived") != 1:
            raise QaConflictError(
                f"case {case_id} is a legacy SQLite row; run "
                "'qa trace migrate-sqlite' to move the library to YAML before editing"
            )
        if row.get("status") == "deprecated":
            raise QaNotFoundError(f"case '{case_id}' is archived")
        return row

    def get_case(self, case_id: str) -> dict[str, Any]:
        """Return one case, in the legacy shape, with its chain badges."""
        try:
            raw = self.store.get_case(case_id)
        except QaNotFoundError:
            # The YAML file may exist without an index row yet (a fresh checkout).
            self._ensure_indexed(self._all_project_ids())
            raw = self.store.get_case(case_id)
        if raw.get("derived") != 1:
            return self._legacy_payload(raw)
        row = self._row(case_id)
        project = self.store.get_project(row["project_id"])
        directory = self.project_dir(project)
        document = self._document(row, directory)
        trace = self._trace_for(project)
        recheck = self._rechecks_for(trace).get(case_id)
        return self._case_payload(
            row,
            document=document,
            needs_recheck=recheck is not None,
            recheck_reasons=list(recheck.reasons) if recheck is not None else (),
            trace=trace,
        )

    def list_cases(
        self,
        *,
        project_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List the case index (derived from YAML, archived cases excluded)."""
        self._ensure_indexed([project_id] if project_id else self._all_project_ids())
        result = self.store.list_cases(
            project_id=project_id,
            kind=kind,
            status=status,
            query=query,
            exclude_deprecated=True,
            limit=limit,
            offset=offset,
        )
        projects: dict[str, dict[str, Any]] = {}
        rows = result["items"]
        for row in rows:
            project_id_value = row["project_id"]
            if project_id_value not in projects:
                try:
                    projects[project_id_value] = self.store.get_project(project_id_value)
                except QaError:  # pragma: no cover - project deleted while listing
                    projects[project_id_value] = {}
        traces = {
            key: self._trace_for(project)
            for key, project in projects.items()
            if project
        }
        rechecks = {key: self._rechecks_for(library) for key, library in traces.items()}
        items: list[dict[str, Any]] = []
        for row in rows:
            project = projects.get(row["project_id"]) or {}
            if row.get("derived") != 1:
                items.append(self._legacy_payload(row))
                continue
            directory = self.project_dir(project) if project else self.root
            document = self._document(row, directory)
            recheck = rechecks.get(row["project_id"], {}).get(row["id"])
            items.append(
                self._case_payload(
                    row,
                    document=document,
                    needs_recheck=recheck is not None,
                    recheck_reasons=list(recheck.reasons) if recheck is not None else (),
                    trace=traces.get(row["project_id"]),
                )
            )
        return {
            "items": items,
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
        }

    def export_cases(self, project_id: str | None = None) -> dict[str, Any]:
        """Return the JSON export the import dialog and backup scripts use."""
        project = self.store.get_project(project_id) if project_id else None
        result = self.list_cases(project_id=project_id, limit=500)
        return {
            "format": "qa-agent.cases.v1",
            "project": {"key": project["key"], "name": project["name"]}
            if project
            else None,
            "exported_at": utcnow_iso(),
            "cases": result["items"],
        }

    # -- code and ID allocation -------------------------------------------

    def _known_codes(self, project: Mapping[str, Any], directory: Path) -> set[str]:
        codes = self.store.case_codes(project["id"])
        for _, _, document in iter_case_documents(
            directory, include_drafts=True, include_tombstones=True
        ):
            code = document.get("code")
            if isinstance(code, str) and code.strip():
                codes.add(code.strip().upper())
        return codes

    def _resolve_code(
        self,
        project: Mapping[str, Any],
        directory: Path,
        kind: str,
        code: Any,
        *,
        current: str | None = None,
    ) -> str:
        project_key = str(project["key"]).upper()
        if code is None or (isinstance(code, str) and not code.strip()):
            if current:
                return current.upper()
            return self._next_code(project_key, self._known_codes(project, directory), kind)
        if not isinstance(code, str):
            raise QaValidationError("code must be a string")
        normalized = code.strip().upper()
        if not normalized:
            if current:
                return current.upper()
            return self._next_code(project_key, self._known_codes(project, directory), kind)
        if not CASE_CODE_RE.match(normalized):
            raise QaValidationError(
                "code must start with a letter and use uppercase letters, digits, '_' or '-'"
            )
        if current is not None and normalized == current.upper():
            return normalized
        if normalized in self._known_codes(project, directory):
            raise QaConflictError(f"case code '{normalized}' already exists in this project")
        return normalized

    @staticmethod
    def _next_code(project_key: str, known: Iterable[str], kind: str) -> str:
        prefix = f"{project_key.upper()}-{kind.upper()}-"
        highest = 0
        for code in known:
            if not code.startswith(prefix):
                continue
            suffix = code[len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"{prefix}{highest + 1:03d}"

    def _taken_case_ids(self) -> list[str]:
        return self.store.derived_case_ids()

    # -- writes ------------------------------------------------------------

    def create_case(
        self,
        project_id: str,
        *,
        title: str,
        kind: str = "api",
        code: str | None = None,
        priority: str = "P1",
        status: str = "draft",
        preconditions: str = "",
        steps: Any = None,
        api: Any = None,
        expected: str = "",
        tags: Any = None,
        source: str = "manual",
        author: str = "",
        batch: str | None = None,
        testpoints: Any = None,
        sources: Any = None,
        direct_reason: str | None = None,
        risk: str | None = None,
        postconditions: str | None = None,
        owner: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a case as a draft file, then refresh the derived index."""
        project = self.store.get_project(project_id)
        directory = self.ensure_project(project)
        case_kind = require_enum(kind, "kind", CASE_KINDS, default="api")
        case_title = require_text(title, "title", max_length=300)
        legacy_status = require_enum(status, "status", CASE_STATUSES, default="draft")
        if legacy_status == "deprecated":
            raise QaValidationError(
                "a new case cannot start as deprecated; use the delete action to archive one"
            )
        trace_status = status_for_legacy(legacy_status)
        priority_value = require_enum(priority, "priority", CASE_PRIORITIES, default="P1")
        normalized_steps = validate_steps(steps)
        api_spec = validate_api_spec(api)
        expected_text = optional_text(expected, "expected", max_length=5000)
        tag_values = normalize_tags(tags)
        testpoint_values = _as_id_list(testpoints, field="testpoints")
        source_values = _as_id_list(sources, field="sources")
        case_code = self._resolve_code(project, directory, case_kind, code)
        case_id = next_case_id(
            directory, project_key=str(project["key"]), taken=self._taken_case_ids()
        )
        document = self._build_document(
            case_id=case_id,
            code=case_code,
            title=case_title,
            priority=priority_value,
            case_type=derive_case_type(case_kind),
            status=trace_status,
            steps=normalized_steps
            or self._derived_steps(case_kind, api_spec, expected_text, case_title),
            automation=automation_block(self._automation_status(case_kind, api_spec)),
            testpoints=testpoint_values,
            sources=source_values,
            direct_reason=direct_reason,
            risk=risk,
            preconditions=optional_text(preconditions, "preconditions", max_length=5000),
            postconditions=postconditions,
            expected=expected_text,
            api=api_spec or None,
            owner=owner or author or None,
            tags=tag_values,
            note=note,
            extra={"source": source} if source else None,
        )
        self._check_promotable(
            directory, document, trace_status, testpoint_values, source_values
        )
        target = self._write_document(directory, document, batch=batch)
        self.reindex(project_id=project_id)
        if trace_status == "reviewed" and (testpoint_values or source_values):
            self._record_review(
                project,
                directory,
                case_id,
                reviewer=None,
                note=note if isinstance(note, str) else None,
            )
        payload = self.get_case(case_id)
        payload["path"] = case_relative_path(target, directory)
        return payload

    def update_case(self, case_id: str, **fields: Any) -> dict[str, Any]:
        """Update one case file (and move it when its review status changes)."""
        row = self._row(case_id)
        project = self.store.get_project(row["project_id"])
        directory = self.ensure_project(project)
        path = self._document_path(row, directory)
        if path is None or not path.is_file():
            raise QaNotFoundError(f"case '{case_id}' has no YAML document")
        document = self._read_document(case_id, path)

        title = document.get("title")
        if fields.get("title") is not None:
            title = require_text(fields["title"], "title", max_length=300)
        kind = str(row.get("kind") or "manual")
        if fields.get("kind") is not None:
            kind = require_enum(fields["kind"], "kind", CASE_KINDS)
        priority = str(document.get("priority") or row.get("priority") or "P1")
        if fields.get("priority") is not None:
            priority = require_enum(fields["priority"], "priority", CASE_PRIORITIES)
        legacy_status = str(row.get("status") or "draft")
        if fields.get("status") is not None:
            legacy_status = require_enum(fields["status"], "status", CASE_STATUSES)
        trace_status = status_for_legacy(legacy_status)
        if fields.get("steps") is not None:
            steps = validate_steps(fields["steps"])
        else:
            steps = _steps_from_document(document)
        if fields.get("api") is not None:
            api_spec = validate_api_spec(fields["api"])
        else:
            raw_api = document.get("api")
            api_spec = dict(raw_api) if isinstance(raw_api, Mapping) else {}
        expected = document.get("expected")
        if fields.get("expected") is not None:
            expected = optional_text(fields["expected"], "expected", max_length=5000)
        preconditions = document.get("preconditions")
        if fields.get("preconditions") is not None:
            preconditions = optional_text(
                fields["preconditions"], "preconditions", max_length=5000
            )
        postconditions = document.get("postconditions")
        if fields.get("postconditions") is not None:
            postconditions = optional_text(
                fields["postconditions"], "postconditions", max_length=5000
            )
        if fields.get("tags") is not None:
            tags = normalize_tags(fields["tags"])
        else:
            tags = [str(item) for item in document.get("tags") or []]
        testpoints = _as_id_list(
            fields.get("testpoints", document.get("testpoints")), field="testpoints"
        )
        sources = _as_id_list(
            fields.get("sources", document.get("sources")), field="sources"
        )
        direct_reason = fields.get("direct_reason", document.get("direct_reason"))
        risk = fields.get("risk", document.get("risk"))
        note = fields.get("note", document.get("note"))
        owner = fields.get("owner", document.get("owner"))
        code = self._resolve_code(
            project,
            directory,
            kind,
            fields.get("code", document.get("code")),
            current=str(row.get("code") or "") or None,
        )
        extra = {
            key: value
            for key, value in document.items()
            if key not in KNOWN_CASE_KEYS and key != "tombstone"
        }
        updated = self._build_document(
            case_id=case_id,
            code=code,
            title=title if isinstance(title, str) else "",
            priority=priority,
            case_type=derive_case_type(kind),
            status=trace_status,
            steps=steps
            or self._derived_steps(
                kind, api_spec, str(expected or ""), str(title or "")
            ),
            automation=self._merge_automation(document, kind, api_spec),
            testpoints=testpoints,
            sources=sources,
            direct_reason=direct_reason if isinstance(direct_reason, str) else None,
            risk=risk if isinstance(risk, str) else None,
            preconditions=preconditions if isinstance(preconditions, str) else None,
            postconditions=postconditions if isinstance(postconditions, str) else None,
            expected=expected if isinstance(expected, str) else None,
            api=api_spec or None,
            data=document.get("data") if isinstance(document.get("data"), Mapping) else None,
            owner=owner if isinstance(owner, str) else None,
            tags=tags,
            note=note if isinstance(note, str) else None,
            legacy_id=(
                document.get("legacy_id")
                if isinstance(document.get("legacy_id"), str)
                else None
            ),
            extra=extra,
        )
        relative = case_relative_path(path, directory)
        batch = relative.split("/")[1] if relative.startswith("draft/") else None
        has_links = bool(testpoints or sources)
        self._check_promotable(directory, updated, trace_status, testpoints, sources)
        target = self._write_document(directory, updated, batch=batch)
        if target != path:
            path.unlink(missing_ok=True)
        self.reindex(project_id=row["project_id"])
        if trace_status == "reviewed" and has_links:
            reviewer = fields.get("reviewer")
            note_value = fields.get("note")
            self._record_review(
                project,
                directory,
                case_id,
                reviewer=reviewer if isinstance(reviewer, str) else None,
                note=note_value if isinstance(note_value, str) else None,
            )
        payload = self.get_case(case_id)
        payload["path"] = case_relative_path(target, directory)
        return payload

    def delete_case(
        self, case_id: str, *, reason: str | None = None, reviewer: str | None = None
    ) -> dict[str, Any]:
        """Archive one case: write a tombstone, drop the case file, reindex."""
        row = self._row(case_id)
        project = self.store.get_project(row["project_id"])
        directory = self.ensure_project(project)
        path = self._document_path(row, directory)
        if path is None or not path.is_file():
            raise QaNotFoundError(f"case '{case_id}' has no YAML document")
        document = self._read_document(case_id, path)
        document["status"] = "deprecated"
        document["tombstone"] = {
            "at": utcnow_iso(),
            "from": case_relative_path(path, directory),
            "reason": reason or "",
            "by": reviewer or "",
        }
        tombstone = directory / TOMBSTONES_DIRNAME / f"{case_id}.yaml"
        write_case_document(tombstone, document)
        path.unlink(missing_ok=True)
        self.reindex(project_id=row["project_id"])
        return {
            "deleted": True,
            "id": case_id,
            "tombstone": case_relative_path(tombstone, directory),
        }

    def import_cases(self, project_id: str, payload: Any) -> dict[str, Any]:
        """Import an exported JSON array as draft cases (duplicate codes skip)."""
        raw_cases: Any = payload
        if isinstance(payload, Mapping):
            raw_cases = payload.get("cases", [])
        if not isinstance(raw_cases, list):
            raise QaValidationError("import payload must be an array or {'cases': [...]}")
        project = self.store.get_project(project_id)
        directory = self.ensure_project(project)
        existing_codes = self._known_codes(project, directory)
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, item in enumerate(raw_cases):
            if not isinstance(item, Mapping):
                errors.append({"index": index, "error": "case must be an object"})
                continue
            code = item.get("code")
            if isinstance(code, str) and code.strip().upper() in existing_codes:
                skipped.append({
                    "index": index,
                    "code": code.strip().upper(),
                    "reason": "code already exists",
                })
                continue
            try:
                case = self.create_case(
                    project_id,
                    title=item.get("title", ""),
                    kind=item.get("kind", "api"),
                    code=code,
                    priority=item.get("priority", "P1"),
                    status=item.get("status", "draft"),
                    preconditions=item.get("preconditions", ""),
                    steps=item.get("steps"),
                    api=item.get("api"),
                    expected=item.get("expected", ""),
                    tags=item.get("tags"),
                    source="import",
                    author=item.get("author", ""),
                )
            except QaConflictError as exc:
                skipped.append({"index": index, "code": code, "reason": str(exc)})
                continue
            except QaError as exc:
                errors.append({"index": index, "error": str(exc)})
                continue
            existing_codes.add(str(case["code"]))
            created.append(case)
        return {
            "project": {"id": project_id, "key": project["key"]},
            "created": created,
            "skipped": skipped,
            "errors": errors,
        }

    # -- index maintenance -------------------------------------------------

    def reindex(
        self, *, project_id: str | None = None, project_key: str | None = None
    ) -> dict[str, Any]:
        """Rebuild the derived case rows from the YAML files.

        This is the only writer of ``derived = 1`` rows, so a YAML edit done by
        hand (or pulled from git) becomes visible after one call.
        """
        projects = self.store.list_projects()
        if project_id is not None:
            projects = [self.store.get_project(project_id)]
        if project_key is not None:
            wanted = project_key.strip().upper()
            projects = [item for item in projects if item["key"] == wanted]
            if not projects:
                raise QaNotFoundError(f"project '{project_key}' not found")
        report: dict[str, Any] = {
            "root": self.root.as_posix(),
            "projects": [],
            "cases": 0,
            "drafts": 0,
            "reviewed": 0,
            "archived": 0,
        }
        for project in projects:
            directory = self.project_dir(project)
            rows = self._derived_rows(project, directory)
            written = self.store.replace_derived_cases(project["id"], rows)
            report["projects"].append({
                "id": project["id"],
                "key": project["key"],
                "root": directory.as_posix(),
                "cases": written,
            })
            report["cases"] += written
            for row in rows:
                if row["status"] == "deprecated":
                    report["archived"] += 1
                elif row["status"] == "ready":
                    report["reviewed"] += 1
                else:
                    report["drafts"] += 1
        return report

    def _derived_rows(
        self, project: Mapping[str, Any], directory: Path
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path, _batch, document in iter_case_documents(
            directory, include_drafts=True, include_tombstones=True
        ):
            case_id = document.get("id")
            if not isinstance(case_id, str) or not case_id.strip():
                case_id = path.stem
            raw_status = document.get("status")
            trace_status = (
                raw_status.strip().lower()
                if isinstance(raw_status, str)
                and raw_status.strip().lower() in {"draft", "reviewed", "deprecated"}
                else "draft"
            )
            kind = kind_for_type(
                document.get("type") if isinstance(document.get("type"), str) else None
            )
            priority = document.get("priority")
            priority_value = (
                priority.strip().upper()
                if isinstance(priority, str) and priority.strip().upper() in set(CASE_PRIORITIES)
                else "P1"
            )
            api = document.get("api")
            code = document.get("code")
            steps = _steps_from_document(document)
            tags = document.get("tags")
            rows.append({
                "id": case_id.strip(),
                "project_id": project["id"],
                "code": (
                    code.strip().upper()
                    if isinstance(code, str) and code.strip()
                    else case_id.strip()
                ),
                "title": str(document.get("title") or case_id),
                "kind": kind,
                "priority": priority_value,
                "status": legacy_for_status(trace_status),
                "preconditions": document.get("preconditions") or "",
                "steps": steps,
                "api": dict(api) if isinstance(api, Mapping) else {},
                "expected": document.get("expected") or "",
                "tags": [str(item) for item in tags] if isinstance(tags, list) else [],
                "source": document.get("source") or "yaml",
                "author": document.get("author") or document.get("owner") or "",
                "legacy_id": document.get("legacy_id") or "",
                "yaml_path": case_relative_path(path, directory),
                "stamp": _stat_stamp(path),
            })
        return rows

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _automation_status(kind: str, api_spec: Mapping[str, Any]) -> str:
        if kind == "api" and api_spec.get("request"):
            return "todo"
        return "manual"

    @staticmethod
    def _merge_automation(
        document: Mapping[str, Any], kind: str, api_spec: Mapping[str, Any]
    ) -> dict[str, Any]:
        raw = document.get("automation")
        if isinstance(raw, Mapping):
            block = dict(raw)
            block.setdefault("status", "todo" if kind == "api" else "manual")
            return block
        return automation_block(CaseFiles._automation_status(kind, api_spec))

    @staticmethod
    def _derived_steps(
        kind: str, api_spec: Mapping[str, Any], expected: str, title: str
    ) -> list[dict[str, str]]:
        """Return the one step a case needs when the caller supplied none.

        ``qa_trace`` requires every case to have at least one step (its rules
        cannot tell "no steps" from "forgot the steps").  An API case derives its
        step from the request and the assertions; anything else uses the title and
        the expected result, which is exactly what the workbench captured.
        """
        request = api_spec.get("request") if isinstance(api_spec, Mapping) else None
        if kind == "api" and isinstance(request, Mapping):
            method = str(request.get("method") or "GET").upper()
            path = str(request.get("path") or "")
            summary = _assertion_summary(api_spec.get("assertions") or [])
            return [{
                "action": f"{method} {path}".strip(),
                "expected": expected or summary or "请求成功",
            }]
        action = title.strip() or "执行用例"
        return [{"action": action, "expected": expected or title.strip() or action}]

    def _write_document(
        self,
        directory: Path,
        document: Mapping[str, Any],
        *,
        batch: str | None,
        formal: bool | None = None,
    ) -> Path:
        """Write a case document where its review state belongs.

        ``cases/`` is reserved for a *reviewed and linked* case: an unlinked case
        can keep ``status: reviewed`` in its document (the legacy API allows
        recording the review) but stays in ``draft/`` until a test point or source
        is attached, because the trace loader refuses an unlinked formal case.
        """
        status = str(document.get("status") or "draft")
        if formal is None:
            formal = bool(document.get("testpoints") or document.get("sources"))
        placement = status
        if status == "reviewed" and not formal:
            placement = "draft"
        case_id = str(document.get("id"))
        target = case_path_for(directory, case_id, status=placement, batch=batch)
        write_case_document(target, document)
        return target

    @staticmethod
    def _build_document(**fields: Any) -> dict[str, Any]:
        """Build one case document, translating shape errors to 400s."""
        try:
            return case_document(**fields)
        except CaseDocumentError as exc:
            raise QaValidationError(str(exc)) from None

    def _check_promotable(
        self,
        directory: Path,
        document: Mapping[str, Any],
        trace_status: str,
        testpoints: Sequence[str],
        sources: Sequence[str],
    ) -> None:
        """Refuse to write a formal case the trace loader would reject.

        A case only reaches ``cases/`` when it is reviewed *and* linked; the rest
        stay drafts (with whatever status their document declares), so no write
        can make a project unloadable for ``qa trace check``.  The links must also
        exist: promoting a case to a misspelled test point would turn a clean
        library into a dangling reference.
        """
        if trace_status != "reviewed" or not (testpoints or sources):
            return
        try:
            Case.from_dict(document)
        except QaTraceError as exc:
            raise QaConflictError(
                "the case cannot enter the formal library yet: " + exc.format()
            ) from None
        try:
            library = load_project(directory)
        except QaTraceError as exc:
            raise QaConflictError(
                "the project library must load before a case can be promoted: "
                + exc.format()
            ) from None
        missing = [
            *(item for item in testpoints if item not in library.testpoints),
            *(item for item in sources if item not in library.sources),
        ]
        if missing:
            raise QaConflictError(
                "the case references trace assets that do not exist: "
                + ", ".join(missing)
            )

    def _record_review(
        self,
        project: Mapping[str, Any],
        directory: Path,
        case_id: str,
        *,
        reviewer: str | None,
        note: str | None,
    ) -> None:
        """Record the review fingerprint after a promotion (best effort)."""
        try:
            library = load_project(directory)
            fingerprint = fingerprint_project(library).get(case_id)
            if fingerprint is None:
                return
            index = load_index_for_write(
                directory, project_id=library.config.project_id
            )
            index = upsert_review(
                index, fingerprint, reviewer=reviewer, note=note, now=utcnow_iso()
            )
            write_index(index, now=utcnow_iso())
        except QaTraceError as exc:
            logger.warning("qa cases: review record not written for {}: {}", case_id, exc.format())


def case_library(store: QaStore, root: str | Path | None = None) -> CaseFiles:
    """Return the YAML case library for one store (``root`` for tests/CLI)."""
    return CaseFiles(store, root)


def reindex_cases(
    store: QaStore,
    *,
    root: str | Path | None = None,
    project_key: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Rebuild the derived case index from the YAML library."""
    return CaseFiles(store, root).reindex(project_id=project_id, project_key=project_key)


__all__ = [
    "CaseFiles",
    "PROJECT_FILE",
    "SQLITE_FILENAME",
    "case_library",
    "reindex_cases",
]
