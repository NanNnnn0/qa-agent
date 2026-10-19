"""Export the legacy SQLite case table into the YAML case library.

Before YAML became the source of truth, cases lived in ``cases`` rows of the QA
SQLite database.  This module performs the one-way move: it reads those rows and
writes YAML documents under ``<root>/<project-key-lower>/`` with readable
``TC-<MODULE>-<seq>`` IDs and a ``legacy_id`` that points back at the row it came
from.

Two rules make the export safe to run against a live installation:

*it never writes the database*.  The connection is opened read-only
(``mode=ro``), so a migration cannot damage the rollback copy.
*it never invents traceability*.  A SQLite case has no test points and no
sources, and the trace model refuses a formal case without a link, so every
migrated case is written as a draft and reported as one.  A human then attaches
the case to a test point (or a source) and promotes it.

Re-running is idempotent: a row whose ``legacy_id`` already has a YAML document
in the project is skipped instead of duplicated.  The YAML side owns the next
``TC-*`` number (tombstones included), so a re-run never re-uses a retired ID.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .caseyaml import (
    TOMBSTONES_DIRNAME,
    CaseDocumentError,
    automation_block,
    case_document,
    case_files,
    case_module,
    case_path_for,
    next_case_id,
    read_case_document,
    write_case_document,
)
from .compat import type_for_kind
from .errors import MigrateError
from .loader import PROJECT_FILE
from .models import AutomationStatus, CaseType, Priority, ReviewStatus
from .yamlfile import write_yaml

#: Batch that receives migrated cases (they are drafts: unlinked by definition).
MIGRATION_BATCH = "sqlite-migration"

#: Columns the export reads from the legacy ``cases`` table.
CASE_COLUMNS: tuple[str, ...] = (
    "id",
    "project_id",
    "code",
    "title",
    "kind",
    "priority",
    "status",
    "preconditions",
    "steps",
    "api",
    "expected",
    "tags",
    "source",
    "author",
)

#: Columns of the ``projects`` table the export needs.
PROJECT_COLUMNS: tuple[str, ...] = ("id", "key", "name")


@dataclass(frozen=True, slots=True)
class MigratedProject:
    """What one SQLite project contributed to the YAML library."""

    key: str
    project_id: str
    project_dir: str
    cases: int = 0
    drafts: int = 0
    formal: int = 0
    tombstones: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "project_id": self.project_id,
            "project_dir": self.project_dir,
            "cases": self.cases,
            "drafts": self.drafts,
            "formal": self.formal,
            "tombstones": self.tombstones,
            "skipped": self.skipped,
        }


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """The result of one ``qa trace migrate-sqlite`` run."""

    db: str
    root: str
    batch: str
    projects: tuple[MigratedProject, ...] = ()
    skipped: tuple[dict[str, str], ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    migration_version: int = 1

    @property
    def cases(self) -> int:
        return sum(item.cases for item in self.projects)

    @property
    def drafts(self) -> int:
        return sum(item.drafts for item in self.projects)

    @property
    def formal(self) -> int:
        return sum(item.formal for item in self.projects)

    @property
    def tombstones(self) -> int:
        return sum(item.tombstones for item in self.projects)

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_version": self.migration_version,
            "db": self.db,
            "root": self.root,
            "batch": self.batch,
            "counts": {
                "projects": len(self.projects),
                "cases": self.cases,
                "drafts": self.drafts,
                "formal": self.formal,
                "tombstones": self.tombstones,
                "skipped": sum(item.skipped for item in self.projects),
                "errors": len(self.errors),
            },
            "projects": [item.to_dict() for item in self.projects],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


def render_migration(report: MigrationReport) -> str:
    """Return the human-readable summary printed by the CLI."""
    lines = [
        f"SQLite -> YAML case migration: {report.db}",
        f"root: {report.root}  batch: {report.batch}",
        (
            f"{len(report.projects)} project(s), {report.cases} case(s): "
            f"{report.drafts} draft, {report.formal} formal, "
            f"{report.tombstones} tombstone, "
            f"{sum(item.skipped for item in report.projects)} already migrated"
        ),
    ]
    for item in report.projects:
        lines.append(
            f"  {item.key}: {item.cases} case(s) -> {item.project_dir}"
            f" (drafts {item.drafts}, formal {item.formal}, tombstones {item.tombstones},"
            f" skipped {item.skipped})"
        )
    for error in report.errors:
        lines.append(
            f"  ERROR {error.get('case_id') or '-'}: {error.get('code')}: {error.get('message')}"
        )
    if report.drafts:
        lines.append(
            "every migrated case is a draft: attach a test point or source and promote it "
            "with 'qa trace review approve'"
        )
    return "\n".join(lines)


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise MigrateError(f"cannot open the SQLite database: {exc}", path=db_path) from exc
    connection.row_factory = sqlite3.Row
    return connection


def _json_value(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return fallback
    try:
        return json.loads(raw)
    except ValueError:
        return fallback


def _steps_of(row: Mapping[str, Any], api: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return the case steps, deriving one from the API request when empty."""
    raw = _json_value(row.get("steps"), [])
    steps: list[dict[str, str]] = []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
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
    if steps:
        return steps
    expected = str(row.get("expected") or "").strip()
    request = api.get("request") if isinstance(api, Mapping) else None
    if isinstance(request, Mapping):
        action = f"{str(request.get('method') or 'GET').upper()} {request.get('path') or ''}"
        return [{"action": action.strip(), "expected": expected or "request succeeds"}]
    title = str(row.get("title") or "").strip() or "run the case"
    return [{"action": title, "expected": expected or title}]


def _automation_of(row: Mapping[str, Any], api: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(row.get("kind") or "manual")
    if kind == "api" and isinstance(api, Mapping) and api.get("request"):
        return automation_block(AutomationStatus.TODO.value)
    return automation_block(AutomationStatus.MANUAL.value)


def _project_document(project: Mapping[str, Any]) -> dict[str, Any]:
    key = str(project.get("key") or "").upper() or "PROJECT"
    name = str(project.get("name") or key)
    return {
        "schema_version": 1,
        "project_id": key.lower(),
        "name": name,
        "modules": [case_module(key)],
    }


def _ensure_project(project: Mapping[str, Any], root: Path) -> Path:
    key = str(project.get("key") or "").upper() or "PROJECT"
    directory = root / key.lower()
    path = directory / PROJECT_FILE
    if path.is_file():
        return directory
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml(path, _project_document(project))
    return directory


def _existing_legacy_ids(directory: Path) -> set[str]:
    """Return the ``legacy_id`` values already present in a project."""
    found: set[str] = set()
    for path, _ in case_files(directory, include_drafts=True, include_tombstones=True):
        try:
            document = read_case_document(path)
        except (OSError, ValueError):
            continue
        value = document.get("legacy_id")
        if isinstance(value, str) and value.strip():
            found.add(value.strip())
    return found


def _read_projects(
    connection: sqlite3.Connection, selector: str | None
) -> list[dict[str, Any]]:
    columns = ", ".join(PROJECT_COLUMNS)
    rows = [dict(row) for row in connection.execute(f"SELECT {columns} FROM projects ORDER BY key")]
    if selector is None:
        return rows
    wanted = selector.strip()
    if not wanted:
        return rows
    matches = [
        row
        for row in rows
        if str(row["id"]) == wanted or str(row["key"]).upper() == wanted.upper()
    ]
    if not matches:
        raise MigrateError(
            f"SQLite project {selector!r} was not found; known keys: "
            + ", ".join(sorted(str(row["key"]) for row in rows))
        )
    return matches


def _read_cases(connection: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    columns = ", ".join(CASE_COLUMNS)
    return [
        dict(row)
        for row in connection.execute(
            f"SELECT {columns} FROM cases WHERE project_id = ? ORDER BY code, id",
            (project_id,),
        )
    ]


def _document_for(
    row: Mapping[str, Any],
    case_id: str,
    *,
    status: str,
    steps: Sequence[Mapping[str, Any]],
    api: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the YAML document of one migrated case."""
    priority = str(row.get("priority") or "P1").upper()
    if priority not in {item.value for item in Priority}:
        priority = Priority.P1.value
    case_type = type_for_kind(str(row.get("kind") or "manual"))
    if case_type not in {item.value for item in CaseType}:
        case_type = CaseType.FUNCTIONAL.value
    tags = _json_value(row.get("tags"), [])
    tag_values = [str(item) for item in tags] if isinstance(tags, list) else []
    extra: dict[str, Any] = {}
    source = row.get("source")
    if isinstance(source, str) and source:
        extra["source"] = source
    return case_document(
        case_id=case_id,
        code=str(row.get("code") or case_id),
        legacy_id=str(row.get("id") or ""),
        title=str(row.get("title") or case_id),
        priority=priority,
        case_type=case_type,
        status=status,
        steps=steps,
        automation=_automation_of(row, api),
        preconditions=str(row.get("preconditions") or "") or None,
        expected=str(row.get("expected") or "") or None,
        api=api or None,
        owner=str(row.get("author") or "") or None,
        tags=tag_values,
        note=f"migrated from the legacy SQLite case {row.get('id')}",
        extra=extra,
    )


def _migrate_project(
    connection: sqlite3.Connection,
    project: Mapping[str, Any],
    *,
    root: Path,
    batch: str,
) -> tuple[MigratedProject, list[dict[str, str]], list[dict[str, str]]]:
    key = str(project["key"]).upper()
    directory = _ensure_project(project, root)
    seen = _existing_legacy_ids(directory)
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    cases = drafts = formal = tombstones = 0
    for row in _read_cases(connection, str(project["id"])):
        legacy_id = str(row["id"])
        if legacy_id in seen:
            skipped.append({
                "case_id": legacy_id,
                "code": str(row.get("code") or ""),
                "reason": "already migrated",
            })
            continue
        raw_status = str(row.get("status") or "draft")
        status = "reviewed" if raw_status == "ready" else raw_status
        if status not in {item.value for item in ReviewStatus}:
            status = ReviewStatus.DRAFT.value
        api_raw = _json_value(row.get("api"), {})
        api = dict(api_raw) if isinstance(api_raw, Mapping) else {}
        case_id = next_case_id(directory, project_key=key)
        try:
            document = _document_for(
                row,
                case_id,
                status=status,
                steps=_steps_of(row, api),
                api=api,
            )
        except CaseDocumentError as exc:
            errors.append({"case_id": legacy_id, "code": "TRACE_MIGRATE_INVALID",
                           "message": str(exc)})
            continue
        if status == ReviewStatus.DEPRECATED.value:
            target = directory / TOMBSTONES_DIRNAME / f"{case_id}.yaml"
            tombstones += 1
        else:
            # A SQLite case has no test point and no source, so it cannot enter
            # the formal library: it is written as a draft, never as "reviewed".
            document["status"] = ReviewStatus.DRAFT.value
            target = case_path_for(directory, case_id, status="draft", batch=batch)
            drafts += 1
        write_case_document(target, document)
        seen.add(legacy_id)
        cases += 1
    return (
        MigratedProject(
            key=key,
            project_id=str(project["id"]),
            project_dir=directory.as_posix(),
            cases=cases,
            drafts=drafts,
            formal=formal,
            tombstones=tombstones,
            skipped=len(skipped),
        ),
        skipped,
        errors,
    )


def migrate_sqlite_cases(
    db_path: str | Path,
    root: str | Path,
    *,
    project: str | None = None,
    batch: str = MIGRATION_BATCH,
) -> MigrationReport:
    """Export the SQLite cases of one (or every) project into the YAML library."""
    database = Path(db_path)
    if not database.is_file():
        raise MigrateError(f"SQLite database not found: {database.as_posix()}", path=database)
    target_root = Path(root)
    connection = _open_readonly(database)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "projects" not in tables or "cases" not in tables:
            raise MigrateError(
                "the database has no projects/cases tables (is this the QA database?)",
                path=database,
            )
        projects = _read_projects(connection, project)
        migrated: list[MigratedProject] = []
        skipped: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        for entry in projects:
            outcome, project_skipped, project_errors = _migrate_project(
                connection, entry, root=target_root, batch=batch
            )
            migrated.append(outcome)
            skipped.extend(project_skipped)
            errors.extend(project_errors)
    except sqlite3.Error as exc:
        raise MigrateError(f"cannot read the SQLite database: {exc}", path=database) from exc
    finally:
        connection.close()
    return MigrationReport(
        db=database.as_posix(),
        root=target_root.as_posix(),
        batch=batch,
        projects=tuple(migrated),
        skipped=tuple(skipped),
        errors=tuple(errors),
    )


__all__ = [
    "CASE_COLUMNS",
    "MIGRATION_BATCH",
    "MigratedProject",
    "MigrationReport",
    "migrate_sqlite_cases",
    "render_migration",
]
