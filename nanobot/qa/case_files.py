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

import os
import re
import shutil
import sqlite3
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from stat import S_ISREG
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

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
    draft_batches,
    iter_case_documents,
    legacy_kind,
    read_case_document,
    write_case_document,
)
from qa_trace.caseyaml import case_files as case_file_paths
from qa_trace.compat import kind_for_type, legacy_for_status, status_for_legacy, type_for_kind
from qa_trace.errors import IdError, QaTraceError
from qa_trace.hashing import (
    canonical_json,
    fingerprint_project,
    sha256_bytes,
    sha256_text,
)
from qa_trace.ids import SOURCE_KINDS, IdKind, parse_id
from qa_trace.index import load_index_for_write, upsert_review, write_index
from qa_trace.labels import testpoint_codes
from qa_trace.loader import (
    YAML_SUFFIXES,
    Project,
    ProjectConfig,
    load_project,
    load_project_from_documents,
    load_yaml_document,
)
from qa_trace.models import Case, Source, TestPoint
from qa_trace.staleness import recheck_map
from qa_trace.yamlfile import write_yaml

#: Project metadata file the loader requires (one per trace project).
PROJECT_FILE = "project.yaml"

#: Feature switch for the incremental/summary read and write paths.  ``0``
#: restores the pre-step-2 full-list/full-reindex behavior without touching YAML.
INCREMENTAL_ENV = "QA_CASE_TRACE_INCREMENTAL"


def incremental_enabled() -> bool:
    """Return whether the incremental trace/list/write paths are enabled."""
    value = os.environ.get(INCREMENTAL_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}

#: Default file name of the SQLite database the migration reads.
SQLITE_FILENAME = "qa.sqlite3"

_PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")


def _stat_stamp(path: Path) -> str:
    """Return the file modification time as a UTC ISO timestamp."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:  # pragma: no cover - the file disappeared mid-scan
        return utcnow_iso()


#: Collection directory -> trace entity type used by the derived index.
_COLLECTION_ENTITY_TYPES: dict[str, str] = {
    "sources": "source",
    "testpoints": "testpoint",
    "cases": "case",
}

#: Reverse mapping used by the incremental path to locate one entity file.
_ENTITY_COLLECTIONS: dict[str, str] = {
    "source": "sources",
    "testpoint": "testpoints",
    "case": "cases",
}

#: Names a caller may use for a source/requirement or test point entity.
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    "requirement": "source",
    "req": "source",
    "source": "source",
    "testpoint": "testpoint",
    "test_point": "testpoint",
    "case": "case",
}

#: Review statuses a case document may declare (the YAML vocabulary).
_REVIEW_STATUSES = frozenset({"draft", "reviewed", "deprecated"})


def _yaml_files(directory: Path) -> list[Path]:
    """Return the YAML files directly inside ``directory``, sorted by name."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in YAML_SUFFIXES
    )


def _document_review_status(document: Mapping[str, Any]) -> str:
    """Return the review status a case document declares (``draft`` fallback)."""
    raw = document.get("status")
    if isinstance(raw, str) and raw.strip().lower() in _REVIEW_STATUSES:
        return raw.strip().lower()
    return "draft"


def _case_module_id(case_id: str) -> str:
    """Return the module segment of a case ID (``SHOP`` for ``TC-SHOP-001``)."""
    try:
        return parse_id(case_id, field="id").module or ""
    except IdError:
        return ""


def _declared_ids(value: Any) -> list[str]:
    """Return the non-empty string references of a YAML list field.

    The trace index is derived data, so a malformed draft reference must not
    abort the whole rebuild; it is recorded as declared but does not resolve.
    """
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = [str(item) for item in value]
    else:
        return []
    return [item.strip() for item in items if item.strip()]


def _normalize_entity_type(entity_type: str) -> str:
    """Map ``requirement``/``source`` aliases to the stored entity type."""
    if not isinstance(entity_type, str):
        raise QaValidationError("entity_type must be a string")
    normalized = entity_type.strip().lower().replace("-", "_")
    resolved = _ENTITY_TYPE_ALIASES.get(normalized)
    if resolved is None:
        raise QaValidationError(
            "entity_type must be one of case, testpoint, source, requirement"
        )
    return resolved


def _declared_edges(
    document: Mapping[str, Any], entity_type: str
) -> list[tuple[str, str]]:
    """Return the declared ``(to_type, to_id)`` parent references of an entity."""
    edges: list[tuple[str, str]] = []
    if entity_type == "case":
        edges.extend(
            ("testpoint", item) for item in _declared_ids(document.get("testpoints"))
        )
        edges.extend(
            ("source", item) for item in _declared_ids(document.get("sources"))
        )
    elif entity_type == "testpoint":
        edges.extend(
            ("source", item) for item in _declared_ids(document.get("sources"))
        )
    return edges


def _file_state_record(
    path: Path,
    directory: Path,
    entity_type: str,
    entity_id: str,
    document: Mapping[str, Any],
    *,
    batch: str | None = None,
) -> dict[str, Any]:
    """Return one YAML file record (parsed document, identity, hash and mtime)."""
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    try:
        content_hash = sha256_text(canonical_json(document))
    except (TypeError, ValueError):
        try:
            content_hash = sha256_bytes(path.read_bytes())
        except OSError:
            content_hash = ""
    return {
        "path": path,
        "relative": case_relative_path(path, directory),
        "batch": batch,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "content_hash": content_hash,
        "mtime_ns": mtime_ns,
        "document": dict(document),
    }


def _load_document_record(
    path: Path,
    directory: Path,
    entity_type: str,
    *,
    batch: str | None = None,
) -> dict[str, Any] | None:
    """Read one YAML file into a record, skipping a broken document."""
    try:
        document = load_yaml_document(path)
    except (OSError, QaTraceError, ValueError) as exc:
        logger.warning("qa cases: cannot read {}: {}", path, exc)
        return None
    if not isinstance(document, Mapping):
        logger.warning("qa cases: {} is not a YAML mapping", path)
        return None
    raw_id = document.get("id")
    if entity_type == "project":
        entity_id = str(document.get("project_id") or directory.name)
    else:
        entity_id = (
            raw_id.strip()
            if isinstance(raw_id, str) and raw_id.strip()
            else path.stem
        )
    return _file_state_record(
        path, directory, entity_type, entity_id, document, batch=batch
    )


def _entity_candidates(
    directory: Path, entity_type: str, entity_id: str
) -> list[dict[str, Any]]:
    """Return every YAML file that declares one entity, formal first.

    Only the expected file names are probed, so an incremental refresh does not
    list or parse the whole collection.  The last record wins for hashing, which
    mirrors the full scan's formal -> draft -> tombstone order.
    """
    if (
        not entity_id
        or "/" in entity_id
        or "\\" in entity_id
        or entity_type not in _ENTITY_COLLECTIONS
    ):
        return []
    collection = _ENTITY_COLLECTIONS[entity_type]
    records: list[dict[str, Any]] = []

    def add(path: Path, batch: str | None) -> None:
        if not path.is_file():
            return
        record = _load_document_record(path, directory, entity_type, batch=batch)
        if record is None or record["entity_id"] != entity_id:
            return
        records.append(record)

    for suffix in YAML_SUFFIXES:
        add(directory / collection / f"{entity_id}{suffix}", None)
    for batch in draft_batches(directory):
        for suffix in YAML_SUFFIXES:
            add(
                directory / "draft" / batch / collection / f"{entity_id}{suffix}",
                batch,
            )
    if entity_type == "case":
        for suffix in YAML_SUFFIXES:
            add(directory / TOMBSTONES_DIRNAME / f"{entity_id}{suffix}", None)
    return records


def _project_config(directory: Path) -> ProjectConfig:
    """Build the config half of a minimal ``Project`` for one-case rechecks."""
    raw = load_yaml_document(directory / PROJECT_FILE)
    if not isinstance(raw, Mapping):
        raise ValueError("project.yaml must be a mapping")
    schema_version = raw.get("schema_version")
    project_id = raw.get("project_id")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or not isinstance(project_id, str)
        or not project_id.strip()
    ):
        raise ValueError("project.yaml needs schema_version and project_id")
    modules = raw.get("modules") or ()
    if not isinstance(modules, (list, tuple)):
        raise ValueError("project.yaml modules must be a list")
    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, Mapping):
        raise ValueError("project.yaml thresholds must be a mapping")
    name = raw.get("name")
    return ProjectConfig(
        schema_version=schema_version,
        project_id=project_id.strip(),
        name=name.strip() if isinstance(name, str) and name.strip() else None,
        modules=tuple(str(item) for item in modules),
        thresholds=dict(thresholds),
        strict=bool(raw.get("strict", False)),
        extra={
            key: value
            for key, value in raw.items()
            if key
            not in {
                "schema_version",
                "project_id",
                "name",
                "modules",
                "thresholds",
                "strict",
            }
        },
    )


def _scan_project_documents(directory: Path) -> list[dict[str, Any]]:
    """Read every YAML source file of one trace project.

    Returns one record per file with its parsed document, entity identity and the
    content hash/mtime the incremental path uses.  Unreadable files are skipped
    with a warning: one broken draft must not hide the whole library.
    """
    if not directory.is_dir():
        return []
    candidates: list[tuple[Path, str | None, str]] = []
    for collection, entity_type in _COLLECTION_ENTITY_TYPES.items():
        candidates.extend(
            (path, None, entity_type) for path in _yaml_files(directory / collection)
        )
    for batch in draft_batches(directory):
        for collection, entity_type in _COLLECTION_ENTITY_TYPES.items():
            candidates.extend(
                (path, batch, entity_type)
                for path in _yaml_files(directory / "draft" / batch / collection)
            )
    candidates.extend(
        (path, None, "case") for path in _yaml_files(directory / TOMBSTONES_DIRNAME)
    )
    project_file = directory / PROJECT_FILE
    if project_file.is_file():
        candidates.append((project_file, None, "project"))

    scanned: list[dict[str, Any]] = []
    for path, batch, entity_type in candidates:
        try:
            document = load_yaml_document(path)
        except (OSError, QaTraceError, ValueError) as exc:
            logger.warning("qa cases: cannot read {}: {}", path, exc)
            continue
        if not isinstance(document, Mapping):
            logger.warning("qa cases: {} is not a YAML mapping", path)
            continue
        raw_id = document.get("id")
        if entity_type == "project":
            entity_id = str(document.get("project_id") or directory.name)
        elif isinstance(raw_id, str) and raw_id.strip():
            entity_id = raw_id.strip()
        else:
            entity_id = path.stem
        scanned.append(
            _file_state_record(
                path,
                directory,
                entity_type,
                entity_id,
                document,
                batch=batch,
            )
        )
    return scanned


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
        self._claim_sync_signature: dict[str, tuple[Any, ...]] = {}
        self._claim_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._claim_sync_report: dict[str, dict[str, Any]] = {}
        self._claim_conflicts_cache: dict[str, tuple[Any, ...]] = {}
        self._recovered_projects: set[str] = set()

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
        reads as expensive as writes.  The list path passes ``trace=False``, so
        even this one-time build never loads the whole trace project.
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
            # Listing paths is enough to decide whether there is anything to
            # index; do not parse the library on a normal list request.
            if not case_file_paths(
                directory, include_drafts=True, include_tombstones=True
            ):
                continue
            # With the incremental path enabled the list never loads the trace
            # project; disabling it restores the old full first-time index.
            self.reindex(project_id=project_id, trace=not incremental_enabled())
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

    def _case_record(
        self,
        row: Mapping[str, Any],
        document: Mapping[str, Any],
        directory: Path,
    ) -> dict[str, Any] | None:
        """Return the file-state record of the target case, without rescanning."""
        path = self._document_path(row, directory)
        if path is None or not path.is_file():
            return None
        relative = case_relative_path(path, directory)
        batch = relative.split("/")[1] if relative.startswith("draft/") else None
        record = _file_state_record(
            path,
            directory,
            "case",
            str(row["id"]),
            document,
            batch=batch,
        )
        record["entity_id"] = str(row["id"])
        return record

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
        self._ensure_recovered(row["project_id"])
        document = self._document(row, directory)
        context = (
            self._case_reference_context(directory, document)
            if document is not None
            else {
                "testpoint_records": {},
                "source_records": {},
                "entities": {},
                "formal_entities": {},
            }
        )
        record = (
            self._case_record(row, document, directory)
            if document is not None
            else None
        )
        testpoint_records = [
            formal
            for records in context["testpoint_records"].values()
            if (
                formal := next(
                    (
                        candidate
                        for candidate in records
                        if candidate["batch"] is None
                    ),
                    None,
                )
            )
            is not None
        ]
        source_records = [
            formal
            for records in context["source_records"].values()
            if (
                formal := next(
                    (
                        candidate
                        for candidate in records
                        if candidate["batch"] is None
                    ),
                    None,
                )
            )
            is not None
        ]
        if document is not None:
            recheck, _library_ok = self._target_recheck(
                directory, document, testpoint_records, source_records
            )
        else:
            recheck = None
        current_reasons = list(recheck.reasons) if recheck is not None else []
        summary = self.store.get_case_trace_summary(case_id)
        needs_refresh = summary is None or str(summary.get("state") or "") != "fresh"
        if record is not None:
            entities = dict(context["entities"])
            entities[("case", case_id)] = record
            expected_hash = self._summary_input_hash(
                record, entities, context["formal_entities"]
            )
            needs_refresh = needs_refresh or (
                expected_hash != str(summary.get("input_hash") or "")
            )
        if summary is not None:
            needs_refresh = needs_refresh or (
                bool(summary.get("needs_recheck")) != (recheck is not None)
            ) or (
                list(summary.get("recheck_reasons") or []) != current_reasons
            )
        if needs_refresh and record is not None:
            self.refresh_trace_for_cases(
                row["project_id"],
                [case_id],
                records={case_id: record},
            )
            summary = self.store.get_case_trace_summary(case_id)
        effective_summary = dict(summary or {})
        # The detail must show the current review baseline even when the cached
        # summary row predates it; the refresh above repairs the row.
        effective_summary["needs_recheck"] = recheck is not None
        effective_summary["recheck_reasons"] = current_reasons
        return self._case_payload_for_target(
            project,
            directory,
            row,
            document or {},
            effective_summary,
            context=context,
        )

    def list_cases(
        self,
        *,
        project_id: str | None = None,
        module_id: str | None = None,
        operation_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List lightweight summaries from SQLite.

        The query itself reads no YAML: the row comes from ``cases`` plus the
        cached ``case_trace_summary``.  A project that has never been indexed is
        built once by :meth:`_ensure_indexed` (case rows only, trace stays
        unknown); it never loads the trace project.  The detail path
        (:meth:`get_case`) keeps the full legacy JSON contract.
        """
        if not incremental_enabled():
            return self._list_cases_full(
                project_id=project_id,
                module_id=module_id,
                operation_id=operation_id,
                kind=kind,
                status=status,
                query=query,
                limit=limit,
                offset=offset,
            )
        self._ensure_indexed([project_id] if project_id else self._all_project_ids())
        for target_project_id in (
            [project_id] if project_id else self._all_project_ids()
        ):
            self._ensure_recovered(target_project_id)
        try:
            result = self.store.list_case_summaries(
                project_id=project_id,
                module_id=module_id,
                operation_id=operation_id,
                kind=kind,
                status=status,
                query=query,
                exclude_deprecated=True,
                limit=limit,
                offset=offset,
            )
        except sqlite3.DatabaseError as exc:
            logger.warning(
                "qa cases: summary index unavailable, falling back to full list: {}",
                exc,
            )
            return self._list_cases_full(
                project_id=project_id,
                module_id=module_id,
                operation_id=operation_id,
                kind=kind,
                status=status,
                query=query,
                limit=limit,
                offset=offset,
            )
        missing_summary = any(
            not row.get("legacy") and row.get("state") == "unknown"
            for row in result["items"]
        )
        if missing_summary:
            logger.warning(
                "qa cases: summary rows missing, falling back to full list"
            )
            return self._list_cases_full(
                project_id=project_id,
                module_id=module_id,
                operation_id=operation_id,
                kind=kind,
                status=status,
                query=query,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [self._summary_payload(row) for row in result["items"]],
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
        }

    @staticmethod
    def _summary_payload(row: Mapping[str, Any]) -> dict[str, Any]:
        """Shape one SQLite summary row for the list endpoint.

        The list deliberately omits ``api``, ``steps``, ``expected``, the
        declared test point/source IDs and the resolved chain; those belong to
        the detail payload.  Counts and freshness flags are enough for the table
        badges, and the group/interface scalars keep the list navigable.
        """
        yaml_path = str(row.get("yaml_path") or "")
        draft = yaml_path.startswith("draft/")
        batch = yaml_path.split("/")[1] if draft and yaml_path.count("/") >= 2 else None
        legacy = bool(row.get("legacy"))
        module_id = str(row.get("module_id") or "") or _case_module_id(
            str(row.get("id") or "")
        )
        has_api = row.get("has_api")
        has_api = (
            bool(has_api)
            if has_api is not None
            else bool(row.get("api_method") or row.get("api_path"))
        )
        return {
            "id": row.get("id") or "",
            "project_id": row.get("project_id") or "",
            "code": row.get("code") or row.get("id") or "",
            "title": row.get("title") or "",
            "kind": row.get("kind") or "manual",
            "priority": row.get("priority") or "P1",
            "status": row.get("status") or "draft",
            "tags": list(row.get("tags") or []),
            "source": row.get("source") or ("sqlite" if legacy else "yaml"),
            "author": row.get("author") or "",
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
            "step_count": int(row.get("step_count") or 0),
            "has_api": has_api,
            "module_id": module_id,
            "group": str(row.get("group_name") or "") or None,
            "operation_id": row.get("operation_id") or "",
            "api_method": row.get("api_method") or "",
            "api_path": row.get("api_path") or "",
            "trace_status": row.get("trace_status") or "draft",
            "trace_state": row.get("state") or "unknown",
            "needs_links": bool(row.get("needs_links")),
            "needs_recheck": bool(row.get("needs_recheck")),
            "recheck_reasons": list(row.get("recheck_reasons") or []),
            "testpoint_count": int(row.get("testpoint_count") or 0),
            "source_count": int(row.get("source_count") or 0),
            "input_hash": row.get("input_hash") or "",
            "checked_at": row.get("checked_at") or "",
            "yaml_path": yaml_path,
            "draft": draft,
            "batch": batch,
            "legacy": legacy,
            "legacy_id": row.get("legacy_id") or None,
        }

    def _list_cases_full(
        self,
        *,
        project_id: str | None = None,
        module_id: str | None = None,
        operation_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return full case payloads (export and legacy callers only)."""
        self._ensure_indexed([project_id] if project_id else self._all_project_ids())
        result = self.store.list_cases(
            project_id=project_id,
            module_id=module_id,
            operation_id=operation_id,
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
        result = self._list_cases_full(project_id=project_id, limit=500)
        return {
            "format": "qa-agent.cases.v1",
            "project": {"key": project["key"], "name": project["name"]}
            if project
            else None,
            "exported_at": utcnow_iso(),
            "cases": result["items"],
        }

    # -- code and ID allocation -------------------------------------------

    @staticmethod
    def _claim_number(
        code: str, project_key: str, kind: str
    ) -> int | None:
        prefix = f"{project_key.upper()}-{kind.upper()}-"
        if not code.startswith(prefix):
            return None
        suffix = code[len(prefix):]
        return int(suffix) if suffix.isdigit() else None

    @staticmethod
    def _claim_id_parts(case_id: str) -> tuple[str, int | None]:
        try:
            parsed = parse_id(case_id)
        except IdError:
            return "", None
        if (
            parsed.kind is not IdKind.CASE
            or parsed.is_uuid
            or not parsed.seq.isdigit()
        ):
            return "", None
        return parsed.module or "", int(parsed.seq)

    def _claim_from_row(
        self,
        project: Mapping[str, Any],
        row: Mapping[str, Any],
        *,
        id_parts: tuple[str, int | None] | None = None,
    ) -> dict[str, Any]:
        case_id = str(row["id"])
        code = str(row.get("code") or case_id).strip().upper()
        kind = str(row.get("kind") or "api")
        status = str(row.get("status") or "draft")
        state = (
            "reviewed"
            if status == "ready"
            else "deprecated"
            if status == "deprecated"
            else "draft"
        )
        module, seq = (
            id_parts if id_parts is not None else self._claim_id_parts(case_id)
        )
        return {
            "case_id": case_id,
            "code": code,
            "kind": kind,
            "state": state,
            "source": "yaml",
            "number": self._claim_number(code, str(project["key"]), kind),
            "module": module,
            "seq": seq,
            "conflict": 0,
        }

    def _claim_from_record(
        self, project: Mapping[str, Any], record: Mapping[str, Any]
    ) -> dict[str, Any]:
        document = record["document"]
        case_id = str(record["entity_id"])
        raw_code = document.get("code")
        code = (
            raw_code.strip().upper()
            if isinstance(raw_code, str) and raw_code.strip()
            else case_id
        )
        kind = kind_for_type(
            document.get("type")
            if isinstance(document.get("type"), str)
            else None
        )
        module, seq = self._claim_id_parts(case_id)
        return {
            "case_id": case_id,
            "code": code,
            "kind": kind,
            "state": _document_review_status(document),
            "source": "yaml",
            "number": self._claim_number(code, str(project["key"]), kind),
            "module": module,
            "seq": seq,
            "conflict": 0,
        }

    @staticmethod
    def _relative_path_fast(path: Path, directory: Path) -> str:
        """Return a project-relative path without resolving every file."""
        try:
            return path.relative_to(directory).as_posix()
        except ValueError:
            return case_relative_path(path, directory)

    def _case_dirs_signature(self, directory: Path) -> tuple[Any, ...]:
        """Return a cheap fingerprint of the directories that can add cases."""
        parts: list[tuple[str, int]] = []
        for name in ("cases", TOMBSTONES_DIRNAME, "draft"):
            path = directory / name
            try:
                parts.append((name, path.stat().st_mtime_ns))
            except OSError:
                parts.append((name, 0))
        for batch in draft_batches(directory):
            path = directory / "draft" / batch
            try:
                parts.append((f"draft/{batch}", path.stat().st_mtime_ns))
            except OSError:
                continue
        return tuple(sorted(parts))

    def sync_case_claims(self, project_id: str) -> dict[str, Any]:
        """Synchronise the allocation ledger with the case files on disk.

        Unchanged files are read from the derived rows; only new or modified
        files are parsed.  The directory signature avoids re-listing 10,000
        files on every write, while the per-file mtime still catches a hand
        edit inside an existing batch.
        """
        project = self.store.get_project(project_id)
        directory = self.project_dir(project)
        empty = {
            "project_id": project_id,
            "scanned": 0,
            "parsed": 0,
            "codes": 0,
            "conflicts": 0,
        }
        if not directory.is_dir():
            return empty
        states = {
            str(state["path"]): state
            for state in self.store.list_trace_file_states(project_id)
            if state.get("entity_type") == "case"
        }
        signature = self._case_dirs_signature(directory)
        list_paths = self._claim_sync_signature.get(project_id) != signature
        cached = self._claim_cache.get(project_id)
        previous = cached
        if previous is None:
            previous = {
                str(claim["case_id"]): claim
                for claim in self.store.list_case_claims(project_id)
                if claim.get("source") == "yaml"
            }
            for claim in self.store.list_case_id_claims(project_id):
                case_id = str(claim["case_id"])
                if case_id in previous and claim.get("source") == "yaml":
                    previous[case_id]["module"] = claim.get("module")
                    previous[case_id]["seq"] = claim.get("seq")
        if cached is not None and not list_paths:
            unchanged_all = True
            for relative, state in states.items():
                try:
                    st = os.stat(directory / relative)
                except OSError:
                    unchanged_all = False
                    break
                if (
                    not S_ISREG(st.st_mode)
                    or st.st_mtime_ns != int(state.get("mtime_ns") or 0)
                ):
                    unchanged_all = False
                    break
            if unchanged_all:
                report = self._claim_sync_report.get(project_id)
                if report is not None:
                    return report
        rows_by_id = {
            str(row["id"]): row
            for row in self.store.case_claim_rows(project_id)
        }
        claims: dict[str, dict[str, Any]] = {}
        parsed: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        conflicts: list[dict[str, Any]] = []

        def add(record: Mapping[str, Any]) -> None:
            claim = self._claim_from_record(project, record)
            case_id = claim["case_id"]
            relative = str(record["relative"])
            existing = claims.get(case_id)
            if existing is not None and existing.get("path") != relative:
                conflicts.append(
                    {
                        "entity": "id",
                        "value": case_id,
                        "case_ids": [case_id],
                        "reason": (
                            f"id declared by both {existing.get('path')}"
                            f" and {relative}"
                        ),
                    }
                )
                return
            claim["path"] = relative
            claims[case_id] = claim
            seen.add(case_id)
            parsed[relative] = dict(record)

        for relative, state in states.items():
            path = directory / relative
            try:
                st = os.stat(path)
            except OSError:
                continue
            if not S_ISREG(st.st_mode):
                continue
            case_id = str(state["entity_id"])
            seen.add(case_id)
            unchanged = st.st_mtime_ns == int(state.get("mtime_ns") or 0)
            if unchanged:
                row = rows_by_id.get(case_id)
                if row is not None:
                    prior = previous.get(case_id)
                    claims[case_id] = self._claim_from_row(
                        project,
                        row,
                        id_parts=(
                            (
                                str(prior.get("module") or ""),
                                prior.get("seq"),
                            )
                            if prior is not None
                            else None
                        ),
                    )
                    claims[case_id]["path"] = relative
                    continue
            record = _load_document_record(path, directory, "case")
            if record is not None:
                add(record)

        if list_paths:
            for path, _batch in case_file_paths(
                directory, include_drafts=True, include_tombstones=True
            ):
                relative = self._relative_path_fast(path, directory)
                if relative in parsed:
                    continue
                state = states.get(relative)
                if state is not None:
                    try:
                        unchanged = path.stat().st_mtime_ns == int(
                            state.get("mtime_ns") or 0
                        )
                    except OSError:
                        continue
                    if unchanged and str(state["entity_id"]) in claims:
                        continue
                record = _load_document_record(path, directory, "case")
                if record is not None:
                    add(record)
                else:
                    seen.add(path.stem)

        by_code: dict[str, list[dict[str, Any]]] = {}
        for claim in claims.values():
            by_code.setdefault(str(claim["code"]), []).append(claim)
        for code, group in by_code.items():
            if len(group) < 2:
                continue
            ids = sorted(str(item["case_id"]) for item in group)
            for item in group:
                item["conflict"] = 1 if str(item["case_id"]) != ids[0] else 0
            conflicts.append(
                {
                    "entity": "code",
                    "value": code,
                    "case_ids": ids,
                    "reason": "duplicate yaml case code",
                }
            )

        for record in parsed.values():
            if record["path"].stem != record["entity_id"]:
                conflicts.append(
                    {
                        "entity": "path",
                        "value": str(record["relative"]),
                        "case_ids": [str(record["entity_id"])],
                        "reason": "file name does not match declared id",
                    }
                )

        def key(claim: Mapping[str, Any]) -> tuple[Any, ...]:
            return (
                str(claim.get("code") or "").upper(),
                str(claim.get("kind") or ""),
                str(claim.get("state") or ""),
                claim.get("number"),
                int(claim.get("conflict") or 0),
                str(claim.get("module") or ""),
                claim.get("seq"),
            )

        upserts = [
            claim
            for case_id, claim in claims.items()
            if key(claim) != key(previous.get(case_id, {}))
        ]
        deletes = [
            case_id
            for case_id, claim in previous.items()
            if case_id not in claims
            and str(claim.get("state") or "") != "reserved"
        ]
        conflict_signature = tuple(
            sorted(
                (
                    str(item["entity"]),
                    str(item["value"]),
                    tuple(str(case_id) for case_id in item["case_ids"]),
                    str(item["reason"]),
                )
                for item in conflicts
            )
        )
        changed = bool(upserts or deletes) or (
            self._claim_conflicts_cache.get(project_id) != conflict_signature
        )
        if changed:
            result = self.store.apply_case_claim_changes(
                project_id,
                upserts,
                delete_case_ids=deletes,
                conflicts=conflicts,
            )
        else:
            result = {
                "codes": 0,
                "deleted": 0,
                "conflicts": len(conflicts),
            }
        for record in parsed.values():
            self._upsert_file_state(project_id, record)
        self._claim_sync_signature[project_id] = signature
        self._claim_cache[project_id] = {
            str(claim["case_id"]): claim for claim in claims.values()
        }
        self._claim_conflicts_cache[project_id] = conflict_signature
        report = {
            "project_id": project_id,
            "scanned": len(seen),
            "parsed": len(parsed),
            "codes": len(claims),
            "conflicts": len(conflicts),
            "changed": result["codes"] + result["deleted"],
        }
        self._claim_sync_report[project_id] = report
        return report

    def _remember_case_claim(
        self,
        project_id: str,
        project: Mapping[str, Any],
        directory: Path,
        row: Mapping[str, Any],
    ) -> None:
        """Keep the in-process claim cache warm after one confirmed write."""
        cache = self._claim_cache.get(project_id)
        if cache is None:
            return
        claim = self._claim_from_row(project, row)
        cache[str(row["id"])] = claim
        self._claim_sync_signature[project_id] = self._case_dirs_signature(
            directory
        )
        report = self._claim_sync_report.get(project_id)
        if report is not None:
            report["codes"] = len(cache)

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
        self._ensure_recovered(project_id)
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
        self.sync_case_claims(project_id)
        requested_code: str | None = None
        if code is not None and not (isinstance(code, str) and not code.strip()):
            if not isinstance(code, str):
                raise QaValidationError("code must be a string")
            requested_code = code.strip().upper()
            if not CASE_CODE_RE.match(requested_code):
                raise QaValidationError(
                    "code must start with a letter and use uppercase letters, "
                    "digits, '_' or '-'"
                )
        allocation = self.store.allocate_case_identity(
            project_id,
            kind=case_kind,
            module=case_module(str(project["key"])),
            code=requested_code,
        )[0]
        case_id = str(allocation["case_id"])
        case_code = str(allocation["code"])
        try:
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
        except BaseException:
            self.store.release_case_claims(project_id, [case_id])
            raise
        self.store.confirm_case_claims(
            project_id, [case_id], state=trace_status
        )
        if not incremental_enabled():
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
        record = _file_state_record(target, directory, "case", case_id, document)
        derived_row = self._derived_row(project, record)
        stored_row = self.store.upsert_derived_case(derived_row)
        self._remember_case_claim(project_id, project, directory, stored_row)
        if trace_status == "reviewed" and (testpoint_values or source_values):
            self._record_review(
                project,
                directory,
                case_id,
                reviewer=None,
                note=note if isinstance(note, str) else None,
            )
        self.refresh_trace_for_cases(project_id, [case_id])
        summary = self.store.get_case_trace_summary(case_id) or {}
        payload = self._case_payload_for_target(
            project, directory, stored_row, document, summary
        )
        payload["path"] = case_relative_path(target, directory)
        return payload

    def update_case(self, case_id: str, **fields: Any) -> dict[str, Any]:
        """Update one case file (and move it when its review status changes)."""
        row = self._row(case_id)
        project = self.store.get_project(row["project_id"])
        directory = self.ensure_project(project)
        self._ensure_recovered(row["project_id"])
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
        self.sync_case_claims(row["project_id"])
        current_code = str(row.get("code") or "").strip().upper()
        raw_code = fields.get("code", document.get("code"))
        if raw_code is None or (isinstance(raw_code, str) and not raw_code.strip()):
            code = current_code
        else:
            if not isinstance(raw_code, str):
                raise QaValidationError("code must be a string")
            code = raw_code.strip().upper()
            if not CASE_CODE_RE.match(code):
                raise QaValidationError(
                    "code must start with a letter and use uppercase letters, "
                    "digits, '_' or '-'"
                )
        if not code:
            allocation = self.store.allocate_case_identity(
                row["project_id"],
                kind=kind,
                module=case_module(str(project["key"])),
            )[0]
            code = str(allocation["code"])
        claim_changed = code != current_code
        if claim_changed:
            self.store.replace_case_code_claim(
                row["project_id"], case_id, code, kind
            )
        extra = {
            key: value
            for key, value in document.items()
            if key not in KNOWN_CASE_KEYS and key != "tombstone"
        }
        try:
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
            self._check_promotable(
                directory, updated, trace_status, testpoints, sources
            )
            placement = trace_status
            if trace_status == "reviewed" and not has_links:
                placement = "draft"
            target = case_path_for(
                directory, case_id, status=placement, batch=batch
            )
            if target != path and target.exists():
                raise QaConflictError(
                    "case file already exists:"
                    f" {case_relative_path(target, directory)}"
                )
            target = self._write_document(
                directory, updated, batch=batch, overwrite=True
            )
        except BaseException:
            if claim_changed and current_code:
                try:
                    self.store.replace_case_code_claim(
                        row["project_id"], case_id, current_code, kind
                    )
                except QaError:  # pragma: no cover - best-effort compensation
                    logger.warning(
                        "qa cases: could not restore code {} for {}",
                        current_code,
                        case_id,
                    )
            raise
        self.store.confirm_case_claims(
            row["project_id"], [case_id], state=trace_status
        )
        if target != path:
            path.unlink(missing_ok=True)
        if not incremental_enabled():
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
        record = _file_state_record(target, directory, "case", case_id, updated)
        derived_row = self._derived_row(project, record)
        stored_row = self.store.upsert_derived_case(derived_row)
        self._remember_case_claim(
            row["project_id"], project, directory, stored_row
        )
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
        self.refresh_trace_for_cases(row["project_id"], [case_id])
        summary = self.store.get_case_trace_summary(case_id) or {}
        payload = self._case_payload_for_target(
            project, directory, stored_row, updated, summary
        )
        payload["path"] = case_relative_path(target, directory)
        return payload

    def delete_case(
        self, case_id: str, *, reason: str | None = None, reviewer: str | None = None
    ) -> dict[str, Any]:
        """Archive one case: write a tombstone, drop the case file, reindex."""
        row = self._row(case_id)
        project = self.store.get_project(row["project_id"])
        directory = self.ensure_project(project)
        self._ensure_recovered(row["project_id"])
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
        self.store.confirm_case_claims(
            row["project_id"], [case_id], state="deprecated"
        )
        cache = self._claim_cache.get(row["project_id"])
        if cache is not None:
            claim = dict(
                cache.get(case_id) or self._claim_from_row(project, row)
            )
            claim["state"] = "deprecated"
            cache[case_id] = claim
            self._claim_sync_signature[row["project_id"]] = (
                self._case_dirs_signature(directory)
            )
        if not incremental_enabled():
            self.reindex(project_id=row["project_id"])
            return {
                "deleted": True,
                "id": case_id,
                "tombstone": case_relative_path(tombstone, directory),
            }
        record = _file_state_record(tombstone, directory, "case", case_id, document)
        self.store.upsert_derived_case(self._derived_row(project, record))
        self.refresh_trace_for_cases(row["project_id"], [case_id])
        return {
            "deleted": True,
            "id": case_id,
            "tombstone": case_relative_path(tombstone, directory),
        }

    def _ensure_recovered(self, project_id: str) -> None:
        """Reconcile import journals left by a previous process."""
        if project_id in self._recovered_projects:
            return
        self._recovered_projects.add(project_id)
        try:
            batches = self.store.list_import_batches(
                project_id,
                statuses=(
                    "preparing",
                    "files_committed",
                    "aborting",
                    "index_committed",
                ),
            )
        except QaError:
            return
        for batch in batches:
            try:
                self._recover_import_batch(batch)
            except Exception:  # pragma: no cover - recovery must not break reads
                logger.exception(
                    "qa cases: could not recover import batch {}", batch["batch_id"]
                )

    def _manifest_matches(
        self, path: Path, directory: Path, expected_hash: str
    ) -> bool:
        if not path.is_file():
            return False
        record = _load_document_record(path, directory, "case")
        return (
            record is not None
            and str(record["content_hash"]) == str(expected_hash)
        )

    def _recover_import_batch(self, batch: Mapping[str, Any]) -> None:
        """Drive one journal row to ``complete`` or ``aborted``."""
        batch_id = str(batch["batch_id"])
        project = self.store.get_project(str(batch["project_id"]))
        directory = self.project_dir(project)
        status = str(batch.get("status") or "")
        files = list((batch.get("manifest") or {}).get("files") or [])
        if status == "index_committed":
            self.store.update_import_batch(batch_id, "complete")
            return
        if status in {"preparing", "aborting"}:
            for entry in files:
                target = directory / str(entry.get("target") or "")
                temp = directory / str(entry.get("temp") or "")
                if str(entry.get("target")):
                    if self._manifest_matches(
                        target, directory, str(entry.get("content_hash") or "")
                    ):
                        target.unlink(missing_ok=True)
                if str(entry.get("temp")):
                    temp.unlink(missing_ok=True)
            self.store.release_case_claims(
                str(batch["project_id"]),
                [str(entry.get("case_id") or "") for entry in files],
            )
            self.store.update_import_batch(batch_id, "aborted")
            return
        if status != "files_committed":
            return
        if not all(
            self._manifest_matches(
                directory / str(entry.get("target") or ""),
                directory,
                str(entry.get("content_hash") or ""),
            )
            for entry in files
        ):
            # A missing or user-edited target means we cannot safely roll
            # forward or delete the batch; leave the files and record failure.
            self.store.update_import_batch(
                batch_id,
                "failed",
                error="batch files no longer match the manifest",
            )
            return
        entries: list[dict[str, Any]] = []
        for entry in files:
            target = directory / str(entry["target"])
            record = _load_document_record(target, directory, "case")
            if record is None:
                self.store.update_import_batch(
                    batch_id, "failed", error="batch file cannot be read"
                )
                return
            entries.append(
                {
                    "case_id": str(entry["case_id"]),
                    "code": str(entry.get("code") or ""),
                    "document": record["document"],
                    "target": target,
                    "relative": str(entry["target"]),
                }
            )
        rows, summaries, state_files, edges, claims = self._prepare_case_batch(
            project, directory, entries
        )
        self.store.apply_case_claim_changes(str(batch["project_id"]), claims)
        if rows:
            self.store.apply_case_batch(
                str(batch["project_id"]),
                rows,
                summaries=summaries,
                files=state_files,
                edges=edges,
            )
        self.store.update_import_batch(batch_id, "index_committed")
        self.store.update_import_batch(batch_id, "complete")
        self._claim_cache.pop(str(batch["project_id"]), None)
        self._claim_sync_signature.pop(str(batch["project_id"]), None)

    def _prepare_case_batch(
        self,
        project: Mapping[str, Any],
        directory: Path,
        entries: Sequence[Mapping[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[tuple[str, str, str, str]],
        list[dict[str, Any]],
    ]:
        """Build the derived rows, summaries, edges and claims of a batch."""
        project_record = _load_document_record(
            directory / PROJECT_FILE, directory, "project"
        )
        rows: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        edges: list[tuple[str, str, str, str]] = []
        claims: list[dict[str, Any]] = []
        if project_record is not None:
            files.append(self._file_state_payload(project_record))
        for entry in entries:
            record = _file_state_record(
                entry["target"],
                directory,
                "case",
                entry["case_id"],
                entry["document"],
            )
            row = self._derived_row(project, record)
            context = self._case_reference_context(
                directory, entry["document"]
            )
            testpoint_records = [
                formal
                for records in context["testpoint_records"].values()
                if (
                    formal := next(
                        (
                            candidate
                            for candidate in records
                            if candidate["batch"] is None
                        ),
                        None,
                    )
                )
                is not None
            ]
            source_records = [
                formal
                for records in context["source_records"].values()
                if (
                    formal := next(
                        (
                            candidate
                            for candidate in records
                            if candidate["batch"] is None
                        ),
                        None,
                    )
                )
                is not None
            ]
            recheck, library_ok = self._target_recheck(
                directory,
                entry["document"],
                testpoint_records,
                source_records,
            )
            entities = {("case", entry["case_id"]): record}
            entities.update(context["entities"])
            summary = self._case_summary_row(
                project,
                record,
                entities=entities,
                formal_entities=context["formal_entities"],
                recheck=recheck,
                library_ok=library_ok,
            )
            entry["row"] = row
            entry["summary"] = summary
            rows.append(row)
            summaries.append(summary)
            files.append(self._file_state_payload(record))
            claim = self._claim_from_record(project, record)
            claim["state"] = _document_review_status(entry["document"])
            claims.append(claim)
            for records in (
                *context["testpoint_records"].values(),
                *context["source_records"].values(),
            ):
                for candidate in records:
                    files.append(self._file_state_payload(candidate))
            for to_type, to_id in _declared_edges(
                entry["document"], "case"
            ):
                edges.append(("case", entry["case_id"], to_type, to_id))
            for testpoint_id, records in context[
                "testpoint_records"
            ].items():
                if not records:
                    continue
                for to_type, to_id in _declared_edges(
                    records[-1]["document"], "testpoint"
                ):
                    edges.append(
                        ("testpoint", testpoint_id, to_type, to_id)
                    )
        files = list({item["path"]: item for item in files}.values())
        return rows, summaries, files, edges, claims

    def import_cases(
        self,
        project_id: str,
        payload: Any,
        *,
        mode: str = "compat",
    ) -> dict[str, Any]:
        """Import cases in ``compat`` (partial) or ``strict`` (all-or-none) mode.

        Both modes validate before writing.  Strict mode returns ``committed:
        False`` and leaves the project untouched when any item fails validation.
        Files are staged under ``.qa-import/<batch>/`` and committed with
        ``os.replace``; a journal row lets the next request reconcile a crash
        between the file commit and the index transaction.
        """
        mode_value = require_enum(mode, "mode", ("compat", "strict"))
        raw_cases: Any = payload
        if isinstance(payload, Mapping):
            raw_cases = payload.get("cases", [])
        if not isinstance(raw_cases, list):
            raise QaValidationError("import payload must be an array or {'cases': [...]}")
        if not incremental_enabled():
            return self._import_cases_legacy(project_id, raw_cases)
        project = self.store.get_project(project_id)
        directory = self.ensure_project(project)
        module = case_module(str(project["key"]))
        self._ensure_recovered(project_id)
        self._ensure_indexed([project_id])
        self.sync_case_claims(project_id)
        existing_codes = {
            str(claim["code"]).upper()
            for claim in self.store.list_case_claims(project_id)
        }
        prepared: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, item in enumerate(raw_cases):
            if not isinstance(item, Mapping):
                errors.append({"index": index, "error": "case must be an object"})
                continue
            allocation: dict[str, Any] | None = None
            try:
                title = require_text(
                    item.get("title", ""), "title", max_length=300
                )
                kind = require_enum(
                    item.get("kind", "api"), "kind", CASE_KINDS, default="api"
                )
                priority = require_enum(
                    item.get("priority", "P1"),
                    "priority",
                    CASE_PRIORITIES,
                    default="P1",
                )
                legacy_status = require_enum(
                    item.get("status", "draft"),
                    "status",
                    CASE_STATUSES,
                    default="draft",
                )
                if legacy_status == "deprecated":
                    raise QaValidationError(
                        "a new case cannot start as deprecated; use the delete action to archive one"
                    )
                trace_status = status_for_legacy(legacy_status)
                raw_code = item.get("code")
                if raw_code is not None and not isinstance(raw_code, str):
                    raise QaValidationError("code must be a string")
                requested_code: str | None = None
                if isinstance(raw_code, str) and raw_code.strip():
                    requested_code = raw_code.strip().upper()
                    if not CASE_CODE_RE.match(requested_code):
                        raise QaValidationError(
                            "code must start with a letter and use uppercase letters, "
                            "digits, '_' or '-'"
                        )
                    if requested_code in existing_codes:
                        raise QaConflictError(
                            f"case code '{requested_code}' already exists in this project"
                        )
                steps = validate_steps(item.get("steps"))
                api_spec = validate_api_spec(item.get("api"))
                expected = optional_text(
                    item.get("expected", ""), "expected", max_length=5000
                )
                preconditions = optional_text(
                    item.get("preconditions", ""),
                    "preconditions",
                    max_length=5000,
                )
                tags = normalize_tags(item.get("tags"))
                author = item.get("author", "")
                if not isinstance(author, str):
                    raise QaValidationError("author must be a string")
                testpoints = _as_id_list(
                    item.get("testpoints"), field="testpoints"
                )
                sources = _as_id_list(item.get("sources"), field="sources")
                direct_reason = item.get("direct_reason")
                risk = item.get("risk")
                allocation = self.store.allocate_case_identity(
                    project_id,
                    kind=kind,
                    module=module,
                    code=requested_code,
                )[0]
                case_id = str(allocation["case_id"])
                code = str(allocation["code"])
                document = self._build_document(
                    case_id=case_id,
                    code=code,
                    title=title,
                    priority=priority,
                    case_type=derive_case_type(kind),
                    status=trace_status,
                    steps=steps
                    or self._derived_steps(kind, api_spec, expected, title),
                    automation=automation_block(
                        self._automation_status(kind, api_spec)
                    ),
                    preconditions=preconditions,
                    expected=expected,
                    api=api_spec or None,
                    owner=author or None,
                    tags=tags,
                    testpoints=testpoints,
                    sources=sources,
                    direct_reason=(
                        direct_reason if isinstance(direct_reason, str) else None
                    ),
                    risk=risk if isinstance(risk, str) else None,
                    extra={"source": "import"},
                )
                self._check_promotable(
                    directory, document, trace_status, testpoints, sources
                )
                placement = trace_status
                if trace_status == "reviewed" and not (testpoints or sources):
                    placement = "draft"
                target = case_path_for(
                    directory, case_id, status=placement, batch=None
                )
                relative = case_relative_path(target, directory)
                prepared.append(
                    {
                        "index": index,
                        "case_id": case_id,
                        "code": code,
                        "kind": kind,
                        "document": document,
                        "target": target,
                        "relative": relative,
                    }
                )
                existing_codes.add(code)
            except QaConflictError as exc:
                if allocation is not None:
                    self.store.release_case_claims(
                        project_id, [str(allocation["case_id"])]
                    )
                if mode_value == "strict":
                    errors.append({"index": index, "error": str(exc)})
                else:
                    skipped.append(
                        {
                            "index": index,
                            "code": item.get("code"),
                            "reason": str(exc),
                        }
                    )
            except QaError as exc:
                if allocation is not None:
                    self.store.release_case_claims(
                        project_id, [str(allocation["case_id"])]
                    )
                errors.append({"index": index, "error": str(exc)})

        if mode_value == "strict" and (errors or skipped):
            self.store.release_case_claims(
                project_id, [entry["case_id"] for entry in prepared]
            )
            return {
                "project": {"id": project_id, "key": project["key"]},
                "mode": mode_value,
                "committed": False,
                "created": [],
                "skipped": skipped,
                "errors": errors,
            }
        if not prepared:
            return {
                "project": {"id": project_id, "key": project["key"]},
                "mode": mode_value,
                "committed": True,
                "created": [],
                "skipped": skipped,
                "errors": errors,
            }

        batch_id = uuid4().hex
        staging = directory / ".qa-import" / batch_id
        manifest_files: list[dict[str, Any]] = []
        for entry in prepared:
            temp = staging / f"{entry['case_id']}.yaml"
            manifest_files.append(
                {
                    "case_id": entry["case_id"],
                    "code": entry["code"],
                    "target": entry["relative"],
                    "temp": self._relative_path_fast(temp, directory),
                    "content_hash": sha256_text(
                        canonical_json(entry["document"])
                    ),
                }
            )
        self.store.create_import_batch(
            batch_id,
            project_id,
            mode=mode_value,
            manifest={"files": manifest_files},
        )
        written: list[Path] = []
        try:
            staging.mkdir(parents=True, exist_ok=True)
            for entry in prepared:
                temp = staging / f"{entry['case_id']}.yaml"
                write_case_document(temp, entry["document"])
                entry["temp"] = temp
            for entry in prepared:
                target = entry["target"]
                if target.exists():
                    raise QaConflictError(
                        f"case file already exists: {entry['relative']}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(entry["temp"], target)
                written.append(target)
                entry["written"] = True
            self.store.update_import_batch(batch_id, "files_committed")
            rows, summaries, files, edges, batch_claims = (
                self._prepare_case_batch(project, directory, prepared)
            )
            self.store.apply_case_claim_changes(project_id, batch_claims)
            if rows:
                self.store.apply_case_batch(
                    project_id,
                    rows,
                    summaries=summaries,
                    files=files,
                    edges=edges,
                )
            self.store.update_import_batch(batch_id, "index_committed")
            self.store.update_import_batch(batch_id, "complete")
        except BaseException as exc:
            try:
                self.store.update_import_batch(
                    batch_id, "aborting", error=str(exc)
                )
            except QaError:  # pragma: no cover - journal best effort
                pass
            for entry in prepared:
                temp = entry.get("temp")
                if isinstance(temp, Path):
                    temp.unlink(missing_ok=True)
                if entry.get("written"):
                    entry["target"].unlink(missing_ok=True)
            self.store.apply_case_claim_changes(
                project_id,
                [],
                delete_case_ids=[entry["case_id"] for entry in prepared],
            )
            try:
                self.store.update_import_batch(
                    batch_id, "aborted", error=str(exc)
                )
            except QaError:  # pragma: no cover - journal best effort
                pass
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

        created: list[dict[str, Any]] = []
        for entry in prepared:
            entry["row"] = self.store.get_case(entry["case_id"])
            document = entry["document"]
            if document.get("testpoints") or document.get("sources"):
                payload = self._case_payload_for_target(
                    project,
                    directory,
                    entry["row"],
                    document,
                    entry["summary"],
                )
            else:
                payload = self._case_payload(
                    entry["row"],
                    document=document,
                    needs_recheck=bool(entry["summary"].get("needs_recheck")),
                    recheck_reasons=list(
                        entry["summary"].get("recheck_reasons") or []
                    ),
                    trace=None,
                )
            payload["path"] = entry["relative"]
            created.append(payload)
        return {
            "project": {"id": project_id, "key": project["key"]},
            "mode": mode_value,
            "committed": True,
            "batch_id": batch_id,
            "created": created,
            "skipped": skipped,
            "errors": errors,
        }

    def _import_cases_legacy(
        self, project_id: str, raw_cases: list[Any]
    ) -> dict[str, Any]:
        """Pre-step-4 import: one create_case/reindex per item."""
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

    def _claims_for_scanned(
        self,
        project: Mapping[str, Any],
        scanned: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build the v6 allocation claims from one project scan."""
        claims: dict[str, dict[str, Any]] = {}
        conflicts: list[dict[str, Any]] = []
        for item in scanned:
            if item["entity_type"] != "case":
                continue
            claim = self._claim_from_record(project, item)
            claim["path"] = str(item["relative"])
            existing = claims.get(str(claim["case_id"]))
            if existing is not None and existing.get("path") != claim["path"]:
                conflicts.append(
                    {
                        "entity": "id",
                        "value": str(claim["case_id"]),
                        "case_ids": [str(claim["case_id"])],
                        "reason": (
                            f"id declared by both {existing.get('path')}"
                            f" and {claim['path']}"
                        ),
                    }
                )
                continue
            claims[str(claim["case_id"])] = claim
        by_code: dict[str, list[dict[str, Any]]] = {}
        for claim in claims.values():
            by_code.setdefault(str(claim["code"]), []).append(claim)
        for code, group in by_code.items():
            if len(group) < 2:
                continue
            ids = sorted(str(item["case_id"]) for item in group)
            for item in group:
                item["conflict"] = 1 if str(item["case_id"]) != ids[0] else 0
            conflicts.append(
                {
                    "entity": "code",
                    "value": code,
                    "case_ids": ids,
                    "reason": "duplicate yaml case code",
                }
            )
        return list(claims.values()), conflicts

    def reindex(
        self,
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        trace: bool = True,
    ) -> dict[str, Any]:
        """Rebuild the derived case and trace index from the YAML files.

        This is the only writer of ``derived = 1`` rows, so a YAML edit done by
        hand (or pulled from git) becomes visible after one call.  The v5 trace
        tables are rebuilt in the same pass: they are derived data, and dropping
        them must lose nothing that is not in YAML.

        ``trace=False`` builds only the case rows.  The list path uses it for a
        first-time index so a list request never loads the whole trace project;
        the trace summaries then stay ``unknown`` until a full reindex.
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
            "trace_edges": 0,
            "trace_summaries": 0,
            "trace_files": 0,
            "trace_rebuilt": trace,
        }
        for project in projects:
            directory = self.project_dir(project)
            self._ensure_recovered(str(project["id"]))
            parse_started = time.perf_counter()
            scanned = _scan_project_documents(directory)
            parse_seconds = time.perf_counter() - parse_started
            rows = self._derived_rows(project, directory, scanned)
            claims, conflicts = self._claims_for_scanned(project, scanned)
            if trace:
                edges, summaries, files = self._trace_index_rows(
                    project, directory, scanned
                )
                index_stats = self.store.replace_project_index(
                    project["id"],
                    rows,
                    edges=edges,
                    summaries=summaries,
                    files=files,
                )
                written = index_stats["cases"]
                trace_stats = {
                    "edges": index_stats["edges"],
                    "summaries": index_stats["summaries"],
                    "files": index_stats["files"],
                }
            else:
                written = self.store.replace_derived_cases(project["id"], rows)
                trace_stats = {"edges": 0, "summaries": 0, "files": 0}
            self.store.sync_case_claims(
                project["id"],
                claims,
                seen_case_ids=[str(claim["case_id"]) for claim in claims],
                conflicts=conflicts,
            )
            self._claim_cache.pop(project["id"], None)
            self._claim_sync_signature.pop(project["id"], None)
            self._claim_conflicts_cache.pop(project["id"], None)
            self._claim_sync_report.pop(project["id"], None)
            report["projects"].append({
                "id": project["id"],
                "key": project["key"],
                "root": directory.as_posix(),
                "cases": written,
                "parse_seconds": round(parse_seconds, 4),
                "trace": trace_stats,
                "trace_rebuilt": trace,
            })
            report["cases"] += written
            report["trace_edges"] += trace_stats["edges"]
            report["trace_summaries"] += trace_stats["summaries"]
            report["trace_files"] += trace_stats["files"]
            for row in rows:
                if row["status"] == "deprecated":
                    report["archived"] += 1
                elif row["status"] == "ready":
                    report["reviewed"] += 1
                else:
                    report["drafts"] += 1
        return report

    def _derived_row(
        self,
        project: Mapping[str, Any],
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build one derived ``cases`` row from a scanned case document."""
        document = item["document"]
        case_id = item["entity_id"]
        trace_status = _document_review_status(document)
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
        return {
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
            "yaml_path": item["relative"],
            "stamp": _stat_stamp(item["path"]),
        }

    def _derived_rows(
        self,
        project: Mapping[str, Any],
        directory: Path,
        scanned: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        documents = scanned if scanned is not None else _scan_project_documents(directory)
        return [
            self._derived_row(project, item)
            for item in documents
            if item["entity_type"] == "case"
        ]

    def _case_reference_context(
        self, directory: Path, document: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Load the formal/draft files one case references, without the project."""
        testpoint_records: dict[str, list[dict[str, Any]]] = {}
        for testpoint_id in _declared_ids(document.get("testpoints")):
            testpoint_records[testpoint_id] = _entity_candidates(
                directory, "testpoint", testpoint_id
            )
        source_ids = list(_declared_ids(document.get("sources")))
        for records in testpoint_records.values():
            formal = next(
                (record for record in records if record["batch"] is None),
                None,
            )
            if formal is None:
                continue
            for source_id in _declared_ids(formal["document"].get("sources")):
                if source_id not in source_ids:
                    source_ids.append(source_id)
        source_records = {
            source_id: _entity_candidates(directory, "source", source_id)
            for source_id in source_ids
        }

        entities: dict[tuple[str, str], Mapping[str, Any]] = {}
        formal_entities: dict[tuple[str, str], Mapping[str, Any]] = {}
        for testpoint_id, records in testpoint_records.items():
            if not records:
                continue
            entities[("testpoint", testpoint_id)] = records[-1]
            formal = next(
                (record for record in records if record["batch"] is None),
                None,
            )
            if formal is not None:
                formal_entities[("testpoint", testpoint_id)] = formal
        for source_id, records in source_records.items():
            if not records:
                continue
            entities[("source", source_id)] = records[-1]
            formal = next(
                (record for record in records if record["batch"] is None),
                None,
            )
            if formal is not None:
                formal_entities[("source", source_id)] = formal
        return {
            "testpoint_records": testpoint_records,
            "source_records": source_records,
            "entities": entities,
            "formal_entities": formal_entities,
        }

    def _minimal_project(
        self,
        directory: Path,
        case_document: Mapping[str, Any],
        testpoint_records: Sequence[Mapping[str, Any]],
        source_records: Sequence[Mapping[str, Any]],
        *,
        config: ProjectConfig | None = None,
    ) -> Project:
        """Build a one-case project for fingerprints and review checks."""
        resolved = config if config is not None else _project_config(directory)
        case = Case.from_dict(case_document)
        testpoints = {
            record["entity_id"]: TestPoint.from_dict(record["document"])
            for record in testpoint_records
        }
        sources = {
            record["entity_id"]: Source.from_dict(record["document"])
            for record in source_records
        }
        return Project(
            root=directory,
            config=resolved,
            sources=sources,
            testpoints=testpoints,
            cases={case.id: case},
            files={},
        )

    def _case_payload_for_target(
        self,
        project: Mapping[str, Any],
        directory: Path,
        row: Mapping[str, Any],
        document: Mapping[str, Any],
        summary: Mapping[str, Any],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the full payload from the target case and its direct upstream."""
        context = (
            context
            if context is not None
            else self._case_reference_context(directory, document)
        )
        testpoints: dict[str, Any] = {}
        for testpoint_id, records in context["testpoint_records"].items():
            formal = next(
                (record for record in records if record["batch"] is None),
                None,
            )
            if formal is None:
                continue
            try:
                testpoints[testpoint_id] = TestPoint.from_dict(formal["document"])
            except QaTraceError:
                continue
        sources: dict[str, Any] = {}
        for source_id, records in context["source_records"].items():
            formal = next(
                (record for record in records if record["batch"] is None),
                None,
            )
            if formal is None:
                continue
            try:
                sources[source_id] = Source.from_dict(formal["document"])
            except QaTraceError:
                continue
        # Test point codes are ordinals over the whole formal library; the
        # trace file state gives those IDs without parsing the YAML files.
        # A hand-added file that has not been indexed yet is only listed by
        # name, so parse just that file when its stem disagrees with the
        # recorded id (the loader would reject such a file anyway).
        indexed_ids = set(
            self.store.list_trace_entity_ids(str(project["id"]), "testpoint")
        )
        all_ids = set(indexed_ids)
        for path in _yaml_files(directory / "testpoints"):
            if path.stem in indexed_ids:
                continue
            record = _load_document_record(path, directory, "testpoint")
            all_ids.add(record["entity_id"] if record is not None else path.stem)
        for testpoint_id in all_ids:
            testpoints.setdefault(
                testpoint_id, SimpleNamespace(id=testpoint_id)
            )
        trace = SimpleNamespace(testpoints=testpoints, sources=sources)
        return self._case_payload(
            row,
            document=document,
            needs_recheck=bool(summary.get("needs_recheck")),
            recheck_reasons=list(summary.get("recheck_reasons") or []),
            trace=trace,
        )

    @staticmethod
    def _summary_input_hash(
        item: Mapping[str, Any],
        entities: Mapping[tuple[str, str], Mapping[str, Any]],
        formal_entities: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> str:
        """Return the content/dependency fingerprint of one case summary."""
        document = item["document"]
        declared_testpoints = _declared_ids(document.get("testpoints"))
        declared_sources = _declared_ids(document.get("sources"))
        resolved_testpoints = [
            testpoint_id
            for testpoint_id in declared_testpoints
            if ("testpoint", testpoint_id) in formal_entities
        ]
        input_payload: dict[str, Any] = {
            "version": 1,
            "case": item["content_hash"],
            "testpoints": {
                testpoint_id: entities.get(
                    ("testpoint", testpoint_id), {}
                ).get("content_hash")
                for testpoint_id in declared_testpoints
            },
            "sources": {
                source_id: entities.get(("source", source_id), {}).get(
                    "content_hash"
                )
                for source_id in declared_sources
            },
        }
        for testpoint_id in resolved_testpoints:
            testpoint = entities[("testpoint", testpoint_id)]
            for source_id in _declared_ids(testpoint["document"].get("sources")):
                input_payload["sources"].setdefault(
                    source_id,
                    entities.get(("source", source_id), {}).get("content_hash"),
                )
        return sha256_text(canonical_json(input_payload))

    def _case_summary_row(
        self,
        project: Mapping[str, Any],
        item: Mapping[str, Any],
        *,
        entities: Mapping[tuple[str, str], Mapping[str, Any]],
        formal_entities: Mapping[tuple[str, str], Mapping[str, Any]],
        recheck: Any,
        library_ok: bool,
    ) -> dict[str, Any]:
        """Build one case summary; shared by full reindex and incremental refresh."""
        document = item["document"]
        declared_testpoints = _declared_ids(document.get("testpoints"))
        declared_sources = _declared_ids(document.get("sources"))
        resolved_testpoints = [
            testpoint_id
            for testpoint_id in declared_testpoints
            if ("testpoint", testpoint_id) in formal_entities
        ]
        reachable_sources = {
            source_id
            for source_id in declared_sources
            if ("source", source_id) in formal_entities
        }
        broken_chain = False
        for testpoint_id in resolved_testpoints:
            testpoint = formal_entities[("testpoint", testpoint_id)]
            for source_id in _declared_ids(testpoint["document"].get("sources")):
                if ("source", source_id) in formal_entities:
                    reachable_sources.add(source_id)
                else:
                    broken_chain = True
        missing = broken_chain or any(
            ("testpoint", testpoint_id) not in formal_entities
            for testpoint_id in declared_testpoints
        ) or any(
            ("source", source_id) not in formal_entities
            for source_id in declared_sources
        )

        input_hash = self._summary_input_hash(
            item, entities, formal_entities
        )

        # The list groups by the test point's 模块/页面 breadcrumb; the first
        # segment is the stable module, the full breadcrumb stays in
        # ``group_name`` for the UI.  A case without a group falls back to its
        # ID module so the field is still useful.
        group_name = ""
        raw_group = document.get("group")
        if isinstance(raw_group, str) and raw_group.strip():
            group_name = raw_group.strip()
        for testpoint_id in resolved_testpoints:
            testpoint = formal_entities[("testpoint", testpoint_id)]
            testpoint_group = testpoint["document"].get("group")
            if (
                not group_name
                and isinstance(testpoint_group, str)
                and testpoint_group.strip()
            ):
                group_name = testpoint_group.strip()
        module_id = (
            group_name.split("/", 1)[0].strip()
            if group_name
            else _case_module_id(str(item["entity_id"]))
        )

        # The list may show which interface a case belongs to, but never the
        # full ``api`` object: only the two scalars the summary needs.
        api_spec = document.get("api")
        request = (
            api_spec.get("request")
            if isinstance(api_spec, Mapping)
            and isinstance(api_spec.get("request"), Mapping)
            else {}
        )
        api_method = str(request.get("method") or "").strip().upper()
        api_path = str(request.get("path") or "").strip()

        return {
            "case_id": item["entity_id"],
            "project_id": project["id"],
            "needs_links": not declared_testpoints and not declared_sources,
            "needs_recheck": recheck is not None,
            "trace_status": _document_review_status(document),
            "recheck_reasons": list(recheck.reasons) if recheck is not None else [],
            "testpoint_count": len(resolved_testpoints),
            "source_count": len(reachable_sources),
            "module_id": module_id,
            "group_name": group_name,
            "api_method": api_method,
            "api_path": api_path,
            "input_hash": input_hash,
            "checked_at": utcnow_iso(),
            "state": "stale" if missing or not library_ok else "fresh",
        }

    def _target_recheck(
        self,
        directory: Path,
        case_document: Mapping[str, Any],
        testpoint_records: Sequence[Mapping[str, Any]],
        source_records: Sequence[Mapping[str, Any]],
    ) -> tuple[Any | None, bool]:
        """Return ``(recheck, project_ok)`` for one case without a full load.

        The minimal ``Project`` contains only the target case and its formal
        upstream entities.  ``recheck_map`` then computes the same content and
        dependency fingerprints as the full library for that case.
        """
        try:
            config = _project_config(directory)
        except (OSError, QaTraceError, ValueError) as exc:
            logger.debug("qa cases: target project config unavailable: {}", exc)
            return None, False
        if _document_review_status(case_document) != "reviewed":
            return None, True
        if not _declared_ids(case_document.get("testpoints")) and not _declared_ids(
            case_document.get("sources")
        ):
            # A reviewed-but-unlinked case stays in draft/ and is not part of
            # the formal project; the full library therefore loads cleanly.
            return None, True
        try:
            project = self._minimal_project(
                directory,
                case_document,
                testpoint_records,
                source_records,
                config=config,
            )
            rechecks = recheck_map(project, build_graph(project))
            case_id = next(iter(project.cases))
            return rechecks.get(case_id), True
        except (QaTraceError, ValueError) as exc:
            logger.debug("qa cases: target recheck unavailable: {}", exc)
            return None, False

    def _trace_index_rows(
        self,
        project: Mapping[str, Any],
        directory: Path,
        scanned: Sequence[Mapping[str, Any]],
    ) -> tuple[list[tuple[str, str, str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Build the v5 trace rows from one project scan.

        Edges are the *declared* parent references (case -> testpoint/source,
        testpoint -> source); a dangling reference still creates an edge so a
        later create/rename can invalidate the right summaries.  Counts and
        freshness only use references that resolve, and a missing reference marks
        the summary ``stale`` instead of pretending the case is unlinked.
        """
        entities: dict[tuple[str, str], Mapping[str, Any]] = {}
        for item in scanned:
            if item["entity_type"] in {"source", "testpoint", "case"}:
                entities[(item["entity_type"], item["entity_id"])] = item
        # Draft sources/test points are not part of the formal trace library, so
        # they must not inflate the counts the detail payload reports.  They are
        # still scanned above: their file changes invalidate summaries.
        formal_entities = {
            key: item
            for key, item in entities.items()
            if item["entity_type"] in {"source", "testpoint"} and item["batch"] is None
        }

        edges: set[tuple[str, str, str, str]] = set()
        for item in scanned:
            for to_type, to_id in _declared_edges(
                item["document"], item["entity_type"]
            ):
                edges.add(
                    (item["entity_type"], item["entity_id"], to_type, to_id)
                )

        formal_documents: list[
            tuple[str, Path, Mapping[str, Any]]
        ] = []
        for item in scanned:
            if item["entity_type"] == "project":
                formal_documents.append(
                    ("project", item["path"], item["document"])
                )
            elif (
                item["entity_type"] in {"source", "testpoint", "case"}
                and item["batch"] is None
                and not str(item["relative"]).startswith("tombstones/")
            ):
                formal_documents.append(
                    (item["entity_type"], item["path"], item["document"])
                )
        outcome = load_project_from_documents(directory, formal_documents)
        library = outcome.project if outcome.ok else None
        if library is None and outcome.errors:
            logger.debug(
                "qa cases: trace index rebuild without a valid library: {}",
                outcome.errors[0].format(),
            )
        rechecks: Mapping[str, Any] = {}
        if library is not None:
            try:
                rechecks = recheck_map(library, build_graph(library))
            except QaTraceError as exc:
                logger.debug(
                    "qa cases: recheck map unavailable during trace rebuild: {}",
                    exc.format(),
                )
                library = None

        summaries = [
            self._case_summary_row(
                project,
                item,
                entities=entities,
                formal_entities=formal_entities,
                recheck=rechecks.get(item["entity_id"]),
                library_ok=library is not None,
            )
            for item in scanned
            if item["entity_type"] == "case"
        ]

        files = [
            {
                "path": item["relative"],
                "entity_type": item["entity_type"],
                "entity_id": item["entity_id"],
                "content_hash": item["content_hash"],
                "mtime_ns": item["mtime_ns"],
            }
            for item in scanned
        ]
        return sorted(edges), summaries, files

    # -- incremental trace refresh -----------------------------------------

    @staticmethod
    def _file_state_payload(record: Mapping[str, Any]) -> dict[str, Any]:
        """Return one file record in the store's path-relative shape."""
        return {
            "path": record["relative"],
            "entity_type": record["entity_type"],
            "entity_id": record["entity_id"],
            "content_hash": record["content_hash"],
            "mtime_ns": record["mtime_ns"],
        }

    def _upsert_file_state(
        self, project_id: str, record: Mapping[str, Any]
    ) -> None:
        """Record one parsed YAML file using its project-relative path."""
        self.store.upsert_trace_file_state(
            project_id, self._file_state_payload(record)
        )

    def _delete_entity_file_states(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> None:
        """Drop the recorded file states of a deleted entity."""
        for state in self.store.list_trace_file_states(project_id):
            if (
                state.get("entity_type") == entity_type
                and state.get("entity_id") == entity_id
            ):
                self.store.delete_trace_file_state(project_id, str(state["path"]))

    def affected_cases_for_entity(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> set[str]:
        """Return the cases a change to one trace entity can affect.

        A case change affects that case.  A test point change affects the cases
        that reference it.  A source/requirement change affects the cases that
        reference it directly and the cases of every test point that references
        it (the reverse ``testpoint -> case`` lookup).
        """
        resolved = _normalize_entity_type(entity_type)
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise QaValidationError("entity_id must be a non-empty string")
        entity_id = entity_id.strip()
        if resolved == "case":
            return {entity_id}
        dependents = self.store.get_dependents(project_id, resolved, entity_id)
        if resolved == "testpoint":
            return {
                dependent["from_id"]
                for dependent in dependents
                if dependent["from_type"] == "case"
            }
        cases = {
            dependent["from_id"]
            for dependent in dependents
            if dependent["from_type"] == "case"
        }
        testpoint_ids = {
            dependent["from_id"]
            for dependent in dependents
            if dependent["from_type"] == "testpoint"
        }
        for testpoint_id in testpoint_ids:
            cases.update(
                dependent["from_id"]
                for dependent in self.store.get_dependents(
                    project_id, "testpoint", testpoint_id
                )
                if dependent["from_type"] == "case"
            )
        return cases

    def refresh_trace_for_cases(
        self,
        project_id: str,
        case_ids: Iterable[str],
        *,
        records: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Recompute the trace summary and edges of a batch of cases.

        The function reads only the target case and the formal entities it
        references (plus their sources); it never calls ``load_project()``.  A
        missing case file marks the summary ``stale`` instead of deleting the
        row, which is the honest state a list can show.
        """
        project = self.store.get_project(project_id)
        directory = self.project_dir(project)
        project_record = _load_document_record(
            directory / PROJECT_FILE, directory, "project"
        )
        if project_record is not None:
            self._upsert_file_state(project_id, project_record)
        if isinstance(case_ids, str):
            case_ids = [case_ids]
        requested = list(
            dict.fromkeys(
                case_id.strip()
                for case_id in case_ids
                if isinstance(case_id, str) and case_id.strip()
            )
        )
        if not incremental_enabled():
            self.reindex(project_id=project_id)
            return {
                "project_id": project_id,
                "requested": requested,
                "refreshed": requested,
                "missing": [],
                "skipped": [],
                "fallback": "full_reindex",
            }
        refreshed: list[str] = []
        missing: list[str] = []
        skipped: list[str] = []
        for case_id in requested:
            try:
                row = self.store.get_case(case_id)
            except QaNotFoundError:
                missing.append(case_id)
                continue
            if row.get("derived") != 1:
                skipped.append(case_id)
                continue

            provided = records.get(case_id) if records is not None else None
            case_records = (
                [dict(provided)]
                if provided is not None
                else _entity_candidates(directory, "case", case_id)
            )
            if not case_records:
                relative = str(row.get("yaml_path") or "")
                path = directory / relative if relative else None
                record = (
                    _load_document_record(path, directory, "case")
                    if path is not None and path.is_file()
                    else None
                )
                if record is not None:
                    case_records = [record]
            if not case_records:
                self.store.replace_trace_edges(project_id, "case", case_id, [])
                self._delete_entity_file_states(project_id, "case", case_id)
                self.store.mark_case_trace_stale([case_id])
                missing.append(case_id)
                continue

            record = dict(case_records[-1])
            record["entity_id"] = case_id
            for candidate in case_records:
                self._upsert_file_state(project_id, candidate)
            document = record["document"]
            self.store.replace_trace_edges(
                project_id, "case", case_id, _declared_edges(document, "case")
            )

            entities: dict[tuple[str, str], Mapping[str, Any]] = {
                ("case", case_id): record
            }
            formal_entities: dict[tuple[str, str], Mapping[str, Any]] = {}
            testpoint_records: list[Mapping[str, Any]] = []
            source_records: list[Mapping[str, Any]] = []

            for testpoint_id in _declared_ids(document.get("testpoints")):
                candidates = _entity_candidates(
                    directory, "testpoint", testpoint_id
                )
                for candidate in candidates:
                    self._upsert_file_state(project_id, candidate)
                if candidates:
                    entities[("testpoint", testpoint_id)] = candidates[-1]
                    self.store.replace_trace_edges(
                        project_id,
                        "testpoint",
                        testpoint_id,
                        _declared_edges(candidates[-1]["document"], "testpoint"),
                    )
                    formal = next(
                        (
                            candidate
                            for candidate in candidates
                            if candidate["batch"] is None
                        ),
                        None,
                    )
                    if formal is not None:
                        formal_entities[("testpoint", testpoint_id)] = formal
                        testpoint_records.append(formal)
                else:
                    self.store.replace_trace_edges(
                        project_id, "testpoint", testpoint_id, []
                    )
                    self._delete_entity_file_states(
                        project_id, "testpoint", testpoint_id
                    )

            source_ids = list(_declared_ids(document.get("sources")))
            for testpoint_id in _declared_ids(document.get("testpoints")):
                formal = formal_entities.get(("testpoint", testpoint_id))
                if formal is None:
                    continue
                for source_id in _declared_ids(
                    formal["document"].get("sources")
                ):
                    if source_id not in source_ids:
                        source_ids.append(source_id)
            for source_id in source_ids:
                candidates = _entity_candidates(directory, "source", source_id)
                for candidate in candidates:
                    self._upsert_file_state(project_id, candidate)
                if candidates:
                    entities[("source", source_id)] = candidates[-1]
                    formal = next(
                        (
                            candidate
                            for candidate in candidates
                            if candidate["batch"] is None
                        ),
                        None,
                    )
                    if formal is not None:
                        formal_entities[("source", source_id)] = formal
                        source_records.append(formal)
                else:
                    self._delete_entity_file_states(
                        project_id, "source", source_id
                    )

            recheck, library_ok = self._target_recheck(
                directory, document, testpoint_records, source_records
            )
            summary = self._case_summary_row(
                project,
                record,
                entities=entities,
                formal_entities=formal_entities,
                recheck=recheck,
                library_ok=library_ok,
            )
            self.store.upsert_case_trace_summary(summary)
            refreshed.append(case_id)

        return {
            "project_id": project_id,
            "requested": requested,
            "refreshed": refreshed,
            "missing": missing,
            "skipped": skipped,
        }

    def refresh_trace_entity(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        """Refresh one changed entity and exactly the cases it affects."""
        resolved = _normalize_entity_type(entity_type)
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise QaValidationError("entity_id must be a non-empty string")
        entity_id = entity_id.strip()
        project = self.store.get_project(project_id)
        directory = self.project_dir(project)
        affected = self.affected_cases_for_entity(
            project_id, resolved, entity_id
        )
        if not incremental_enabled():
            self.reindex(project_id=project_id)
            return {
                "project_id": project_id,
                "entity_type": resolved,
                "entity_id": entity_id,
                "affected": sorted(affected),
                "refreshed": sorted(affected),
                "missing": False,
                "fallback": "full_reindex",
            }
        missing = False
        if resolved == "case":
            candidates = _entity_candidates(directory, "case", entity_id)
            if candidates:
                self.store.upsert_derived_case(
                    self._derived_row(project, candidates[-1])
                )
            result = self.refresh_trace_for_cases(project_id, [entity_id])
            missing = entity_id in result["missing"]
        else:
            candidates = _entity_candidates(directory, resolved, entity_id)
            if candidates:
                if resolved == "testpoint":
                    self.store.replace_trace_edges(
                        project_id,
                        "testpoint",
                        entity_id,
                        _declared_edges(candidates[-1]["document"], "testpoint"),
                    )
                for candidate in candidates:
                    self._upsert_file_state(project_id, candidate)
            else:
                if resolved == "testpoint":
                    self.store.replace_trace_edges(
                        project_id, "testpoint", entity_id, []
                    )
                self._delete_entity_file_states(project_id, resolved, entity_id)
                missing = True
            result = self.refresh_trace_for_cases(project_id, affected)
        return {
            "project_id": project_id,
            "entity_type": resolved,
            "entity_id": entity_id,
            "affected": sorted(affected),
            "refreshed": result["refreshed"],
            "missing": missing,
        }

    def refresh_trace_for_entity(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        """Alias for :meth:`refresh_trace_entity` (the design's wording)."""
        return self.refresh_trace_entity(project_id, entity_type, entity_id)

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
        overwrite: bool = False,
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
        if target.exists() and not overwrite:
            raise QaConflictError(
                f"case file already exists: {case_relative_path(target, directory)}"
            )
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
        missing: list[str] = []
        for testpoint_id in testpoints:
            records = _entity_candidates(directory, "testpoint", testpoint_id)
            if not any(record["batch"] is None for record in records):
                missing.append(testpoint_id)
        for source_id in sources:
            records = _entity_candidates(directory, "source", source_id)
            if not any(record["batch"] is None for record in records):
                missing.append(source_id)
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
        """Record the review fingerprint after a promotion (best effort).

        Only the target case and its formal upstream entities are loaded; a
        ready-case update must not pay for a full project parse.
        """
        try:
            row = self.store.get_case(case_id)
            path = self._document_path(row, directory)
            if path is None or not path.is_file():
                return
            document = self._read_document(case_id, path)
            context = self._case_reference_context(directory, document)
            testpoint_records = [
                formal
                for records in context["testpoint_records"].values()
                if (
                    formal := next(
                        (record for record in records if record["batch"] is None),
                        None,
                    )
                )
                is not None
            ]
            source_records = [
                formal
                for records in context["source_records"].values()
                if (
                    formal := next(
                        (record for record in records if record["batch"] is None),
                        None,
                    )
                )
                is not None
            ]
            config = _project_config(directory)
            minimal = self._minimal_project(
                directory,
                document,
                testpoint_records,
                source_records,
                config=config,
            )
            fingerprint = fingerprint_project(minimal).get(case_id)
            if fingerprint is None:
                return
            now = utcnow_iso()
            index = load_index_for_write(
                directory, project_id=config.project_id
            )
            index = upsert_review(
                index, fingerprint, reviewer=reviewer, note=note, now=now
            )
            write_index(index, now=now)
        except (OSError, QaTraceError, ValueError) as exc:
            message = exc.format() if isinstance(exc, QaTraceError) else str(exc)
            logger.warning(
                "qa cases: review record not written for {}: {}", case_id, message
            )


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
    "INCREMENTAL_ENV",
    "PROJECT_FILE",
    "SQLITE_FILENAME",
    "case_library",
    "incremental_enabled",
    "reindex_cases",
]
