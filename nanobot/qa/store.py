"""SQLite persistence for the QA platform.

The store is the single source of truth for projects, test cases, automation
scripts, runs and dispatch tasks. Nothing in this module imports the agent
runtime, so it is shared by the gateway HTTP API, the built-in tools, the MCP
server and the test suite.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from nanobot.qa import catalog
from nanobot.qa.util import dumps, loads, new_id, sha256_json, utcnow_iso
from nanobot.qa.validation import (
    CASE_KINDS,
    CASE_PRIORITIES,
    CASE_REVISION_SOURCES,
    CASE_SOURCES,
    CASE_STATUSES,
    OPERATION_STATUSES,
    RUN_STATUSES,
    RUN_TRIGGERS,
    SCRIPT_FRAMEWORKS,
    TASK_ROLES,
    TASK_STATUSES,
    QaConflictError,
    QaNotFoundError,
    QaValidationError,
    normalize_api_operation,
    normalize_case_candidate,
    normalize_json_object,
    normalize_project_key,
    normalize_tags,
    optional_text,
    require_enum,
    require_method,
    require_text,
    validate_api_spec,
    validate_steps,
)

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    repo_path TEXT NOT NULL DEFAULT '',
    default_env TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'api',
    priority TEXT NOT NULL DEFAULT 'P1',
    status TEXT NOT NULL DEFAULT 'draft',
    preconditions TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',
    api TEXT NOT NULL DEFAULT '{}',
    expected TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual',
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, code)
);
CREATE INDEX IF NOT EXISTS idx_cases_project ON cases(project_id);
CREATE INDEX IF NOT EXISTS idx_cases_kind ON cases(project_id, kind);

CREATE TABLE IF NOT EXISTS scripts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    framework TEXT NOT NULL DEFAULT 'pytest',
    language TEXT NOT NULL DEFAULT 'python',
    file_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    case_ids TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scripts_project ON scripts(project_id);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    script_id TEXT REFERENCES scripts(id) ON DELETE SET NULL,
    case_ids TEXT NOT NULL DEFAULT '[]',
    name TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT '',
    trigger TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'running',
    passed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    report TEXT NOT NULL DEFAULT '{}',
    log TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, started_at);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    parent_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'orchestrator',
    title TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    session_key TEXT NOT NULL DEFAULT '',
    subagent_task_id TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'progress',
    message TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);

CREATE TABLE IF NOT EXISTS task_artifacts (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, kind, ref_id)
);

-- Version 3: API reference assets. The catalog records what the reference
-- material declares, revisions record every case body, and workflows keep the
-- batch that produced them.
CREATE TABLE IF NOT EXISTS api_operations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    path_template TEXT NOT NULL,
    operation_id TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    spec TEXT NOT NULL DEFAULT '{}',
    evidence TEXT NOT NULL DEFAULT '[]',
    source_kind TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    source_version TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, method, path)
);
CREATE INDEX IF NOT EXISTS idx_api_operations_project ON api_operations(project_id, status);

CREATE TABLE IF NOT EXISTS api_case_metadata (
    case_id TEXT PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
    operation_id TEXT REFERENCES api_operations(id) ON DELETE SET NULL,
    scenario_key TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE (operation_id, scenario_key)
);

CREATE TABLE IF NOT EXISTS api_case_revisions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    change_source TEXT NOT NULL DEFAULT 'edit',
    changed_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (case_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_api_case_revisions_hash ON api_case_revisions(content_hash);

CREATE TABLE IF NOT EXISTS api_workflows (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'api_cases',
    status TEXT NOT NULL DEFAULT 'pending',
    base TEXT NOT NULL DEFAULT '{}',
    candidates TEXT NOT NULL DEFAULT '[]',
    checkpoint TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_workflows_idempotency
    ON api_workflows(idempotency_key) WHERE idempotency_key != '';
"""

_JSON_CASE_FIELDS = ("steps", "api", "tags")
_JSON_PROJECT_FIELDS = ("default_env",)
_JSON_SCRIPT_FIELDS = ("case_ids", "tags")
_JSON_RUN_FIELDS = ("case_ids", "report")
_JSON_TASK_EVENT_FIELDS = ("data",)

_CASE_UPDATE_FIELDS = {
    "title", "kind", "priority", "status", "preconditions", "steps", "api",
    "expected", "tags", "source", "author", "code",
}
_SCRIPT_UPDATE_FIELDS = {
    "name", "framework", "language", "file_path", "content", "case_ids", "tags", "status",
}
_TASK_UPDATE_FIELDS = {
    "project_id", "parent_id", "role", "title", "prompt", "status", "progress",
    "session_key", "subagent_task_id", "result",
}
_JSON_OPERATION_FIELDS = ("spec", "evidence")
_JSON_METADATA_FIELDS = ("evidence",)
_CASE_COLUMNS = (
    "id", "project_id", "code", "title", "kind", "priority", "status",
    "preconditions", "steps", "api", "expected", "tags", "source", "author",
    "created_at", "updated_at",
)
_CASE_BODY_FIELDS = (
    "code", "title", "kind", "priority", "status", "preconditions", "steps",
    "api", "expected", "tags", "source", "author", "updated_at",
)
_INSERT_CASE_SQL = (
    "INSERT INTO cases (" + ", ".join(_CASE_COLUMNS) + ") VALUES ("
    + ", ".join("?" for _ in _CASE_COLUMNS) + ")"
)
_UPDATE_CASE_SQL = (
    "UPDATE cases SET " + ", ".join(f"{field} = ?" for field in _CASE_BODY_FIELDS)
    + " WHERE id = ?"
)


def _row_to_dict(row: sqlite3.Row, json_fields: Iterable[str] = ()) -> dict[str, Any]:
    data = {key: row[key] for key in row.keys()}
    for field in json_fields:
        if field in data:
            data[field] = loads(data[field], None if field in {"steps"} else {})
            if field == "steps" and data[field] is None:
                data[field] = []
            if field in {"tags", "case_ids"} and data[field] is None:
                data[field] = []
    return data


class QaStore:
    """Thread-safe SQLite store for the QA platform."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Apply additive migrations to databases created by older versions."""
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= SCHEMA_VERSION:
            return
        if version < 2:
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()
            }
            for name, ddl in (
                ("name", "TEXT NOT NULL DEFAULT ''"),
                ("environment", "TEXT NOT NULL DEFAULT ''"),
                ("trigger", "TEXT NOT NULL DEFAULT 'manual'"),
            ):
                if name not in columns:
                    self._conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")
        # Version 3 only adds tables, which executescript already created above,
        # so upgrading a version-2 database needs no data rewrite.
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- low level ---------------------------------------------------------

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _write(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock, self._conn:
            self._conn.execute(sql, params)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Run several statements atomically while holding the store lock.

        Statement helpers that commit on their own must not be used inside the
        block; call ``self._conn.execute`` directly so a failure rolls back the
        whole batch.
        """
        with self._lock:
            if self._conn.in_transaction:
                self._conn.commit()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            self._conn.commit()

    # -- projects ----------------------------------------------------------

    def create_project(
        self,
        *,
        key: str,
        name: str,
        description: str = "",
        base_url: str = "",
        repo_path: str = "",
        default_env: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project_key = normalize_project_key(key)
        title = require_text(name, "name", max_length=120)
        existing = self._fetchone("SELECT id FROM projects WHERE key = ?", (project_key,))
        if existing is not None:
            raise QaConflictError(f"project key '{project_key}' already exists")
        now = utcnow_iso()
        project_id = new_id("proj")
        self._write(
            "INSERT INTO projects (id, key, name, description, base_url, repo_path,"
            " default_env, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                project_key,
                title,
                optional_text(description, "description"),
                optional_text(base_url, "base_url", max_length=2000),
                optional_text(repo_path, "repo_path", max_length=2000),
                dumps(normalize_json_object(default_env, "default_env")),
                now,
                now,
            ),
        )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None:
            raise QaNotFoundError(f"project '{project_id}' not found")
        project = _row_to_dict(row, _JSON_PROJECT_FIELDS)
        project["stats"] = self.project_stats(project_id)
        return project

    def get_project_by_key(self, key: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM projects WHERE key = ?", (key.upper(),))
        if row is None:
            raise QaNotFoundError(f"project '{key}' not found")
        project = _row_to_dict(row, _JSON_PROJECT_FIELDS)
        project["stats"] = self.project_stats(project["id"])
        return project

    def update_project(self, project_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"key", "name", "description", "base_url", "repo_path", "default_env"}
        updates: dict[str, Any] = {}
        for field, value in fields.items():
            if field not in allowed or value is None:
                continue
            if field == "key":
                value = normalize_project_key(value)
            elif field == "name":
                value = require_text(value, "name", max_length=120)
            elif field == "description":
                value = optional_text(value, "description")
            elif field in {"base_url", "repo_path"}:
                value = optional_text(value, field, max_length=2000)
            elif field == "default_env":
                value = dumps(normalize_json_object(value, "default_env"))
            updates[field] = value
        if not updates:
            return self.get_project(project_id)
        self._require_project(project_id)
        if "key" in updates:
            clash = self._fetchone(
                "SELECT id FROM projects WHERE key = ? AND id != ?", (updates["key"], project_id)
            )
            if clash is not None:
                raise QaConflictError(f"project key '{updates['key']}' already exists")
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        self._write(
            f"UPDATE projects SET {assignments} WHERE id = ?",
            (*updates.values(), project_id),
        )
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> None:
        self._require_project(project_id)
        self._write("DELETE FROM projects WHERE id = ?", (project_id,))

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT p.*,"
            " (SELECT COUNT(*) FROM cases c WHERE c.project_id = p.id) AS case_count,"
            " (SELECT COUNT(*) FROM cases c WHERE c.project_id = p.id AND c.status = 'ready')"
            "   AS ready_case_count,"
            " (SELECT COUNT(*) FROM scripts s WHERE s.project_id = p.id) AS script_count,"
            " (SELECT COUNT(*) FROM runs r WHERE r.project_id = p.id) AS run_count,"
            " (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id"
            "   AND t.status IN ('queued', 'running')) AS active_task_count"
            " FROM projects p ORDER BY p.created_at, p.key"
        )
        projects: list[dict[str, Any]] = []
        for row in rows:
            item = _row_to_dict(row, _JSON_PROJECT_FIELDS)
            item["stats"] = {
                "cases": row["case_count"],
                "ready_cases": row["ready_case_count"],
                "scripts": row["script_count"],
                "runs": row["run_count"],
                "active_tasks": row["active_task_count"],
            }
            for key in ("case_count", "ready_case_count", "script_count", "run_count",
                        "active_task_count"):
                item.pop(key, None)
            projects.append(item)
        return projects

    def project_stats(self, project_id: str) -> dict[str, int]:
        row = self._fetchone(
            "SELECT"
            " (SELECT COUNT(*) FROM cases WHERE project_id = ?) AS cases,"
            " (SELECT COUNT(*) FROM cases WHERE project_id = ? AND status = 'ready')"
            "   AS ready_cases,"
            " (SELECT COUNT(*) FROM scripts WHERE project_id = ?) AS scripts,"
            " (SELECT COUNT(*) FROM runs WHERE project_id = ?) AS runs,"
            " (SELECT COUNT(*) FROM tasks WHERE project_id = ?"
            "   AND status IN ('queued','running')) AS active_tasks",
            (project_id, project_id, project_id, project_id, project_id),
        )
        if row is None:
            return {"cases": 0, "ready_cases": 0, "scripts": 0, "runs": 0, "active_tasks": 0}
        return {
            "cases": row["cases"],
            "ready_cases": row["ready_cases"],
            "scripts": row["scripts"],
            "runs": row["runs"],
            "active_tasks": row["active_tasks"],
        }

    def _require_project(self, project_id: str) -> sqlite3.Row:
        row = self._fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None:
            raise QaNotFoundError(f"project '{project_id}' not found")
        return row

    # -- cases -------------------------------------------------------------

    def _next_case_code(self, project_key: str, kind: str) -> str:
        prefix = f"{project_key.upper()}-{kind.upper()}-"
        rows = self._fetchall(
            "SELECT code FROM cases WHERE code LIKE ? ORDER BY code", (f"{prefix}%",)
        )
        highest = 0
        for row in rows:
            suffix = row["code"][len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"{prefix}{highest + 1:03d}"

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
        change_source: str = "create",
        changed_by: str = "",
    ) -> dict[str, Any]:
        return self._create_case(
            project_id,
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
            source=source,
            author=author,
            change_source=change_source,
            changed_by=changed_by,
        )

    def _prepare_case(
        self,
        project: dict[str, Any],
        *,
        case_id: str,
        title: str,
        kind: str,
        code: Any,
        priority: str,
        status: str,
        preconditions: str,
        steps: Any,
        api: Any,
        expected: str,
        tags: Any,
        source: str,
        author: str,
        exclude_case_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and normalize one case row without touching the database."""
        case_kind = require_enum(kind, "kind", CASE_KINDS, default="api")
        now = utcnow_iso()
        return {
            "id": case_id,
            "project_id": project["id"],
            "code": self._resolve_case_code(
                project["key"], project["id"], case_kind, code,
                exclude_case_id=exclude_case_id,
            ),
            "title": require_text(title, "title", max_length=300),
            "kind": case_kind,
            "priority": require_enum(priority, "priority", CASE_PRIORITIES, default="P1"),
            "status": require_enum(status, "status", CASE_STATUSES, default="draft"),
            "preconditions": optional_text(preconditions, "preconditions", max_length=5000),
            "steps": dumps(validate_steps(steps)),
            "api": dumps(validate_api_spec(api)),
            "expected": optional_text(expected, "expected", max_length=5000),
            "tags": dumps(normalize_tags(tags)),
            "source": require_enum(source, "source", CASE_SOURCES, default="manual"),
            "author": optional_text(author, "author", max_length=120),
            "created_at": now,
            "updated_at": now,
        }

    def _create_case(
        self,
        project_id: str,
        *,
        title: str,
        kind: str = "api",
        code: Any = None,
        priority: str = "P1",
        status: str = "draft",
        preconditions: str = "",
        steps: Any = None,
        api: Any = None,
        expected: str = "",
        tags: Any = None,
        source: str = "manual",
        author: str = "",
        change_source: str = "create",
        changed_by: str = "",
    ) -> dict[str, Any]:
        project = self._require_project(project_id)
        row = self._prepare_case(
            project,
            case_id=new_id("case"),
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
            source=source,
            author=author,
        )
        with self._transaction():
            self._conn.execute(_INSERT_CASE_SQL, tuple(row[column] for column in _CASE_COLUMNS))
            self._insert_case_revision(
                row["id"],
                revision=1,
                change_source=require_enum(
                    change_source, "change_source", CASE_REVISION_SOURCES, default="create",
                ),
                changed_by=changed_by or row["author"],
            )
        return self.get_case(row["id"])

    def _resolve_case_code(
        self, project_key: str, project_id: str, kind: str, code: Any,
        *, exclude_case_id: str | None = None,
    ) -> str:
        if code is None or code == "":
            return self._next_case_code(project_key, kind)
        if not isinstance(code, str):
            raise QaValidationError("code must be a string")
        normalized = code.strip().upper()
        if not normalized:
            return self._next_case_code(project_key, kind)
        clash = self._fetchone(
            "SELECT id FROM cases WHERE project_id = ? AND code = ? AND id != ?",
            (project_id, normalized, exclude_case_id or ""),
        )
        if clash is not None:
            raise QaConflictError(f"case code '{normalized}' already exists in this project")
        return normalized

    def get_case(self, case_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM cases WHERE id = ?", (case_id,))
        if row is None:
            raise QaNotFoundError(f"case '{case_id}' not found")
        return _row_to_dict(row, _JSON_CASE_FIELDS)

    def update_case(
        self,
        case_id: str,
        *,
        base_revision: int | None = None,
        change_source: str = "edit",
        changed_by: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        current = self.get_case(case_id)
        updates: dict[str, Any] = {}
        for field, value in fields.items():
            if field not in _CASE_UPDATE_FIELDS or value is None:
                continue
            if field == "title":
                value = require_text(value, "title", max_length=300)
            elif field == "kind":
                value = require_enum(value, "kind", CASE_KINDS)
            elif field == "priority":
                value = require_enum(value, "priority", CASE_PRIORITIES)
            elif field == "status":
                value = require_enum(value, "status", CASE_STATUSES)
            elif field == "source":
                value = require_enum(value, "source", CASE_SOURCES)
            elif field == "steps":
                value = dumps(validate_steps(value))
            elif field == "api":
                value = dumps(validate_api_spec(value))
            elif field == "tags":
                value = dumps(normalize_tags(value))
            elif field == "code":
                project = self.get_project(current["project_id"])
                value = self._resolve_case_code(
                    project["key"], current["project_id"], current["kind"], value,
                )
            else:
                value = optional_text(value, field, max_length=5000)
            updates[field] = value
        if not updates:
            return current
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        source = require_enum(
            change_source, "change_source", CASE_REVISION_SOURCES, default="edit",
        )
        with self._transaction():
            latest = self._latest_case_revision_row(case_id)
            latest_revision = int(latest["revision"]) if latest is not None else 0
            if base_revision is not None and base_revision != latest_revision:
                raise QaConflictError(
                    f"case '{case_id}' is at revision {latest_revision}, not {base_revision}"
                )
            self._conn.execute(
                f"UPDATE cases SET {assignments} WHERE id = ?",
                (*updates.values(), case_id),
            )
            snapshot = self._case_snapshot(self.get_case(case_id))
            if latest is None or latest["content_hash"] != sha256_json(snapshot):
                self._insert_case_revision(
                    case_id,
                    revision=latest_revision + 1,
                    change_source=source,
                    changed_by=changed_by,
                )
        return self.get_case(case_id)

    def delete_case(self, case_id: str) -> None:
        self.get_case(case_id)
        self._write("DELETE FROM cases WHERE id = ?", (case_id,))

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
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if kind:
            clauses.append("kind = ?")
            params.append(require_enum(kind, "kind", CASE_KINDS))
        if status:
            clauses.append("status = ?")
            params.append(require_enum(status, "status", CASE_STATUSES))
        if query:
            clauses.append("(title LIKE ? OR code LIKE ? OR tags LIKE ? OR expected LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = self._fetchone(f"SELECT COUNT(*) AS total FROM cases{where}", tuple(params))
        rows = self._fetchall(
            f"SELECT * FROM cases{where} ORDER BY code LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 500)), max(0, offset)),
        )
        return {
            "items": [_row_to_dict(row, _JSON_CASE_FIELDS) for row in rows],
            "total": int(total_row["total"]) if total_row is not None else 0,
            "limit": limit,
            "offset": offset,
        }

    def export_cases(self, project_id: str | None = None) -> dict[str, Any]:
        """Export every case in scope; the response is never truncated."""
        project = self.get_project(project_id) if project_id else None
        where = " WHERE project_id = ?" if project_id else ""
        params: tuple[Any, ...] = (project_id,) if project_id else ()
        rows = self._fetchall(f"SELECT * FROM cases{where} ORDER BY code", params)
        cases = [_row_to_dict(row, _JSON_CASE_FIELDS) for row in rows]
        return {
            "format": "qa-agent.cases.v1",
            "project": {"key": project["key"], "name": project["name"]}
            if project else None,
            "exported_at": utcnow_iso(),
            "total": len(cases),
            "cases": cases,
        }

    def import_cases(self, project_id: str, payload: Any) -> dict[str, Any]:
        raw_cases: Any = payload
        if isinstance(payload, dict):
            raw_cases = payload.get("cases", [])
        if not isinstance(raw_cases, list):
            raise QaValidationError("import payload must be an array or {'cases': [...]}")
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        project = self.get_project(project_id)
        existing_codes = {
            row["code"]
            for row in self._fetchall("SELECT code FROM cases WHERE project_id = ?", (project_id,))
        }
        for index, item in enumerate(raw_cases):
            if not isinstance(item, dict):
                errors.append({"index": index, "error": "case must be an object"})
                continue
            code = item.get("code")
            if isinstance(code, str) and code.strip().upper() in existing_codes:
                skipped.append({"index": index, "code": code.strip().upper(),
                                "reason": "code already exists"})
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
                    change_source="import",
                    changed_by=item.get("author", ""),
                )
            except QaConflictError as exc:
                skipped.append({"index": index, "code": code, "reason": str(exc)})
                continue
            except QaValidationError as exc:
                errors.append({"index": index, "error": str(exc)})
                continue
            existing_codes.add(case["code"])
            created.append(case)
        return {
            "project": {"id": project_id, "key": project["key"]},
            "created": created,
            "skipped": skipped,
            "errors": errors,
        }

    # -- scripts -----------------------------------------------------------

    def create_script(
        self,
        project_id: str,
        *,
        name: str,
        content: str = "",
        framework: str = "pytest",
        language: str = "python",
        file_path: str = "",
        case_ids: Any = None,
        tags: Any = None,
        status: str = "draft",
    ) -> dict[str, Any]:
        self._require_project(project_id)
        now = utcnow_iso()
        script_id = new_id("scr")
        self._write(
            "INSERT INTO scripts (id, project_id, name, framework, language, file_path,"
            " content, case_ids, tags, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                script_id,
                project_id,
                require_text(name, "name", max_length=200),
                require_enum(framework, "framework", SCRIPT_FRAMEWORKS, default="pytest"),
                optional_text(language, "language", max_length=40) or "python",
                optional_text(file_path, "file_path", max_length=1000),
                optional_text(content, "content", max_length=400_000),
                dumps(self._normalize_id_list(case_ids)),
                dumps(normalize_tags(tags)),
                require_enum(status, "status", CASE_STATUSES, default="draft"),
                now,
                now,
            ),
        )
        return self.get_script(script_id)

    @staticmethod
    def _normalize_id_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise QaValidationError("expected an array of ids")
        return [item for item in dict.fromkeys(value) if item]

    def get_script(self, script_id: str, *, include_content: bool = True) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM scripts WHERE id = ?", (script_id,))
        if row is None:
            raise QaNotFoundError(f"script '{script_id}' not found")
        script = _row_to_dict(row, _JSON_SCRIPT_FIELDS)
        if not include_content:
            script.pop("content", None)
        return script

    def update_script(self, script_id: str, **fields: Any) -> dict[str, Any]:
        self.get_script(script_id)
        updates: dict[str, Any] = {}
        for field, value in fields.items():
            if field not in _SCRIPT_UPDATE_FIELDS or value is None:
                continue
            if field == "name":
                value = require_text(value, "name", max_length=200)
            elif field == "framework":
                value = require_enum(value, "framework", SCRIPT_FRAMEWORKS)
            elif field == "status":
                value = require_enum(value, "status", CASE_STATUSES)
            elif field == "case_ids":
                value = dumps(self._normalize_id_list(value))
            elif field == "tags":
                value = dumps(normalize_tags(value))
            elif field == "content":
                value = optional_text(value, "content", max_length=400_000)
            else:
                value = optional_text(value, field, max_length=1000)
            updates[field] = value
        if not updates:
            return self.get_script(script_id)
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        self._write(
            f"UPDATE scripts SET {assignments} WHERE id = ?",
            (*updates.values(), script_id),
        )
        return self.get_script(script_id)

    def delete_script(self, script_id: str) -> None:
        self.get_script(script_id)
        self._write("DELETE FROM scripts WHERE id = ?", (script_id,))

    def list_scripts(
        self,
        *,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if query:
            clauses.append("(name LIKE ? OR tags LIKE ? OR file_path LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = self._fetchone(f"SELECT COUNT(*) AS total FROM scripts{where}", tuple(params))
        rows = self._fetchall(
            f"SELECT * FROM scripts{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 500)), max(0, offset)),
        )
        items = []
        for row in rows:
            item = _row_to_dict(row, _JSON_SCRIPT_FIELDS)
            content = item.pop("content", "")
            item["content_bytes"] = len(content.encode("utf-8"))
            item["content_lines"] = len(content.splitlines()) if content else 0
            items.append(item)
        return {
            "items": items,
            "total": int(total_row["total"]) if total_row is not None else 0,
            "limit": limit,
            "offset": offset,
        }

    # -- runs --------------------------------------------------------------

    def create_run(
        self,
        project_id: str,
        *,
        case_ids: list[str] | None = None,
        script_id: str | None = None,
        status: str = "running",
        name: str = "",
        environment: str = "",
        trigger: str = "manual",
    ) -> dict[str, Any]:
        self._require_project(project_id)
        run_id = new_id("run")
        self._write(
            "INSERT INTO runs (id, project_id, script_id, case_ids, name, environment,"
            " trigger, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                project_id,
                script_id,
                dumps(self._normalize_id_list(case_ids)),
                optional_text(name, "name", max_length=200),
                optional_text(environment, "environment", max_length=120),
                require_enum(trigger, "trigger", RUN_TRIGGERS, default="manual"),
                require_enum(status, "status", RUN_STATUSES, default="running"),
                utcnow_iso(),
            ),
        )
        return self.get_run(run_id)

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        passed: int = 0,
        failed: int = 0,
        errors: int = 0,
        skipped: int = 0,
        duration_ms: int = 0,
        report: dict[str, Any] | None = None,
        log: str = "",
    ) -> dict[str, Any]:
        self.get_run(run_id)
        self._write(
            "UPDATE runs SET status = ?, passed = ?, failed = ?, errors = ?, skipped = ?,"
            " duration_ms = ?, finished_at = ?, report = ?, log = ? WHERE id = ?",
            (
                require_enum(status, "status", RUN_STATUSES),
                max(0, int(passed)),
                max(0, int(failed)),
                max(0, int(errors)),
                max(0, int(skipped)),
                max(0, int(duration_ms)),
                utcnow_iso(),
                dumps(report or {}),
                optional_text(log, "log", max_length=200_000),
                run_id,
            ),
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise QaNotFoundError(f"run '{run_id}' not found")
        return _row_to_dict(row, _JSON_RUN_FIELDS)

    def list_runs(
        self, *, project_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        params: list[Any] = []
        where = ""
        if project_id:
            where = " WHERE project_id = ?"
            params.append(project_id)
        total_row = self._fetchone(f"SELECT COUNT(*) AS total FROM runs{where}", tuple(params))
        rows = self._fetchall(
            f"SELECT id, project_id, script_id, case_ids, name, environment, trigger,"
            f" status, passed, failed, errors,"
            f" skipped, duration_ms, started_at, finished_at FROM runs{where}"
            f" ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 200)), max(0, offset)),
        )
        items = []
        for row in rows:
            item = _row_to_dict(row, ("case_ids",))
            items.append(item)
        return {
            "items": items,
            "total": int(total_row["total"]) if total_row is not None else 0,
        }

    # -- tasks -------------------------------------------------------------

    def create_task(
        self,
        *,
        title: str,
        prompt: str = "",
        role: str = "orchestrator",
        project_id: str | None = None,
        parent_id: str | None = None,
        status: str = "queued",
        progress: int = 0,
        session_key: str = "",
        subagent_task_id: str = "",
    ) -> dict[str, Any]:
        role_value = require_enum(role, "role", TASK_ROLES, default="orchestrator")
        status_value = require_enum(status, "status", TASK_STATUSES, default="queued")
        if project_id:
            self._require_project(project_id)
        if parent_id:
            parent = self._fetchone("SELECT * FROM tasks WHERE id = ?", (parent_id,))
            if parent is None:
                raise QaNotFoundError(f"parent task '{parent_id}' not found")
            if not project_id:
                project_id = parent["project_id"]
        now = utcnow_iso()
        task_id = new_id("task")
        self._write(
            "INSERT INTO tasks (id, project_id, parent_id, role, title, prompt, status,"
            " progress, session_key, subagent_task_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                project_id,
                parent_id,
                role_value,
                require_text(title, "title", max_length=300),
                optional_text(prompt, "prompt", max_length=20_000),
                status_value,
                max(0, min(int(progress), 100)),
                optional_text(session_key, "session_key", max_length=300),
                optional_text(subagent_task_id, "subagent_task_id", max_length=200),
                now,
                now,
            ),
        )
        self.add_event(
            task_id,
            kind="created",
            message=f"{role_value} task created",
            data={"status": status_value, "role": role_value},
        )
        return self.get_task(task_id)

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        self.get_task(task_id)
        updates: dict[str, Any] = {}
        event_note: str | None = None
        for field, value in fields.items():
            if field not in _TASK_UPDATE_FIELDS or value is None:
                continue
            if field in {"role"}:
                value = require_enum(value, "role", TASK_ROLES)
            elif field == "status":
                value = require_enum(value, "status", TASK_STATUSES)
                event_note = f"status → {value}"
                if value == "done":
                    updates["progress"] = 100
            elif field == "progress":
                value = max(0, min(int(value), 100))
            elif field == "title":
                value = require_text(value, "title", max_length=300)
            elif field in {"prompt", "result"}:
                value = optional_text(value, field, max_length=20_000)
            else:
                value = optional_text(value, field, max_length=300)
            updates[field] = value
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        self._write(
            f"UPDATE tasks SET {assignments} WHERE id = ?",
            (*updates.values(), task_id),
        )
        if event_note:
            self.add_event(task_id, kind="status", message=event_note,
                           data={"status": updates.get("status")})
        return self.get_task(task_id)

    def decide_task(
        self, task_id: str, *, approved: bool, note: str = "", reviewer: str = "",
    ) -> dict[str, Any]:
        """Approve or reject a task that is waiting for review.

        Approval closes the task as done; rejection closes it as failed so the
        orchestrator can create a rework task. Both record an event with the
        reviewer and note, which is the audit trail the workbench shows.
        """
        task = self.get_task(task_id)
        if task["status"] == "cancelled":
            raise QaConflictError("cancelled tasks cannot be reviewed")
        if task["status"] not in {"needs_review", "blocked"}:
            raise QaConflictError(
                "only tasks waiting for review (needs_review/blocked) can be approved or rejected"
            )
        note_text = optional_text(note, "note", max_length=4000)
        reviewer_text = optional_text(reviewer, "reviewer", max_length=120)
        decision = "approved" if approved else "rejected"
        existing = (task.get("result") or "").strip()
        suffix = f"[{decision}]"
        if reviewer_text:
            suffix += f" {reviewer_text}:"
        if note_text:
            suffix += f" {note_text}"
        result = f"{existing}\n{suffix}".strip() if existing else suffix
        self.update_task(
            task_id,
            status="done" if approved else "failed",
            result=result,
        )
        self.add_event(
            task_id,
            kind=decision,
            message=note_text or decision,
            data={"reviewer": reviewer_text, "from_status": task["status"]},
        )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise QaNotFoundError(f"task '{task_id}' not found")
        task = _row_to_dict(row)
        task["artifacts"] = [
            dict(item)
            for item in self._fetchall(
                "SELECT kind, ref_id, title FROM task_artifacts WHERE task_id = ?"
                " ORDER BY kind, ref_id",
                (task_id,),
            )
        ]
        task["children"] = [
            _row_to_dict(child)
            for child in self._fetchall(
                "SELECT * FROM tasks WHERE parent_id = ? ORDER BY created_at, id", (task_id,)
            )
        ]
        return task

    def list_tasks(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        role: str | None = None,
        parent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("t.project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("t.status = ?")
            params.append(require_enum(status, "status", TASK_STATUSES))
        if role:
            clauses.append("t.role = ?")
            params.append(require_enum(role, "role", TASK_ROLES))
        if parent_id:
            clauses.append("t.parent_id = ?")
            params.append(parent_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = self._fetchone(
            f"SELECT COUNT(*) AS total FROM tasks t{where}", tuple(params)
        )
        rows = self._fetchall(
            f"SELECT t.*, p.key AS project_key FROM tasks t"
            f" LEFT JOIN projects p ON p.id = t.project_id{where}"
            f" ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 200)), max(0, offset)),
        )
        return {
            "items": [_row_to_dict(row) for row in rows],
            "total": int(total_row["total"]) if total_row is not None else 0,
        }

    def add_event(
        self, task_id: str, *, kind: str = "progress", message: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_task_row(task_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO task_events (task_id, at, kind, message, data)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    task_id,
                    utcnow_iso(),
                    optional_text(kind, "kind", max_length=40) or "progress",
                    optional_text(message, "message", max_length=4000),
                    dumps(data or {}),
                ),
            )
            event_id = cursor.lastrowid
        row = self._fetchone("SELECT * FROM task_events WHERE id = ?", (event_id,))
        assert row is not None
        return _row_to_dict(row, _JSON_TASK_EVENT_FIELDS)

    def list_events(self, task_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        self._require_task_row(task_id)
        rows = self._fetchall(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC LIMIT ?",
            (task_id, max(1, min(limit, 1000))),
        )
        return [_row_to_dict(row, _JSON_TASK_EVENT_FIELDS) for row in rows]

    def add_artifact(
        self, task_id: str, *, kind: str, ref_id: str, title: str = "",
    ) -> None:
        self._require_task_row(task_id)
        if kind not in {"case", "script", "run", "report", "note"}:
            raise QaValidationError("artifact kind must be case, script, run, report or note")
        ref = require_text(ref_id, "ref_id", max_length=200)
        self._write(
            "INSERT OR REPLACE INTO task_artifacts (task_id, kind, ref_id, title)"
            " VALUES (?, ?, ?, ?)",
            (task_id, kind, ref, optional_text(title, "title", max_length=300)),
        )

    def _require_task_row(self, task_id: str) -> sqlite3.Row:
        row = self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise QaNotFoundError(f"task '{task_id}' not found")
        return row

    # -- case revisions ----------------------------------------------------

    def _latest_case_revision_row(self, case_id: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT revision, content_hash FROM api_case_revisions"
            " WHERE case_id = ? ORDER BY revision DESC LIMIT 1",
            (case_id,),
        )

    def _case_snapshot(self, case: dict[str, Any]) -> dict[str, Any]:
        return {field: case[field] for field in sorted(_CASE_UPDATE_FIELDS) if field in case}

    def _prepared_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        """Snapshot of a prepared row, shaped exactly like ``_case_snapshot``."""
        snapshot = {field: row.get(field, "") for field in sorted(_CASE_UPDATE_FIELDS)}
        snapshot["steps"] = loads(row.get("steps"), [])
        snapshot["api"] = loads(row.get("api"), {})
        snapshot["tags"] = loads(row.get("tags"), [])
        return snapshot

    def _insert_case_revision(
        self, case_id: str, *, revision: int, change_source: str, changed_by: str,
    ) -> None:
        """Append a revision row; the caller must already hold a transaction."""
        snapshot = self._case_snapshot(self.get_case(case_id))
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO api_case_revisions (id, case_id, revision, snapshot, content_hash,"
            " change_source, changed_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("rev"), case_id, revision, dumps(snapshot), sha256_json(snapshot),
                change_source, changed_by, now,
            ),
        )
        self._conn.execute(
            "UPDATE api_case_metadata SET revision = ?, updated_at = ? WHERE case_id = ?",
            (revision, now, case_id),
        )

    def list_case_revisions(
        self, case_id: str, *, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        self.get_case(case_id)
        total_row = self._fetchone(
            "SELECT COUNT(*) AS total FROM api_case_revisions WHERE case_id = ?", (case_id,)
        )
        rows = self._fetchall(
            "SELECT id, case_id, revision, content_hash, change_source, changed_by, created_at"
            " FROM api_case_revisions WHERE case_id = ? ORDER BY revision DESC LIMIT ? OFFSET ?",
            (case_id, max(1, min(limit, 200)), max(0, offset)),
        )
        return {
            "items": [_row_to_dict(row) for row in rows],
            "total": int(total_row["total"]) if total_row is not None else 0,
            "limit": limit,
            "offset": offset,
        }

    def get_case_revision(self, case_id: str, revision: int) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM api_case_revisions WHERE case_id = ? AND revision = ?",
            (case_id, int(revision)),
        )
        if row is None:
            raise QaNotFoundError(f"revision {revision} of case '{case_id}' not found")
        data = _row_to_dict(row)
        data["snapshot"] = loads(data.get("snapshot"), {})
        return data

    def get_case_metadata(self, case_id: str) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM api_case_metadata WHERE case_id = ?", (case_id,)
        )
        if row is None:
            raise QaNotFoundError(f"case '{case_id}' is not linked to the API catalog")
        return _row_to_dict(row, _JSON_METADATA_FIELDS)

    # -- api catalog -------------------------------------------------------

    def ingest_api_operations(
        self,
        project_id: str,
        operations: Any,
        *,
        source_kind: str = "",
        source_ref: str = "",
        source_version: str = "",
    ) -> dict[str, Any]:
        """Upsert a parsed reference batch and report what moved.

        The batch is compared before writing, so re-ingesting identical material
        writes nothing. Operations that disappeared from the material are marked
        ``missing`` instead of deleted: existing cases may still point at them.
        """
        self._require_project(project_id)
        normalized = self._normalize_operations(operations)
        existing = [
            _row_to_dict(row, _JSON_OPERATION_FIELDS)
            for row in self._fetchall(
                "SELECT * FROM api_operations WHERE project_id = ?", (project_id,)
            )
        ]
        diff = catalog.diff_operations(existing, normalized)
        now = utcnow_iso()
        added: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        with self._transaction():
            for operation in diff["added"]:
                operation_id = new_id("op")
                self._conn.execute(
                    "INSERT INTO api_operations (id, project_id, method, path, path_template,"
                    " operation_id, summary, spec, evidence, source_kind, source_ref,"
                    " source_version, content_hash, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                    (
                        operation_id,
                        project_id,
                        operation["method"],
                        operation["path"],
                        operation["path_template"],
                        operation["operation_id"],
                        operation["summary"],
                        dumps(operation["spec"]),
                        dumps(operation["evidence"]),
                        optional_text(source_kind, "source_kind", max_length=40),
                        optional_text(source_ref, "source_ref", max_length=2000),
                        optional_text(source_version, "source_version", max_length=200),
                        catalog.operation_hash(operation),
                        now,
                        now,
                    ),
                )
                added.append({
                    "id": operation_id,
                    "method": operation["method"],
                    "path": operation["path"],
                    "operation_id": operation["operation_id"],
                })
            for change in diff["changed"]:
                operation = change["operation"]
                self._conn.execute(
                    "UPDATE api_operations SET path_template = ?, operation_id = ?,"
                    " summary = ?, spec = ?, evidence = ?, source_kind = ?, source_ref = ?,"
                    " source_version = ?, content_hash = ?, status = 'active', updated_at = ?"
                    " WHERE id = ?",
                    (
                        operation["path_template"],
                        operation["operation_id"],
                        operation["summary"],
                        dumps(operation["spec"]),
                        dumps(operation["evidence"]),
                        optional_text(source_kind, "source_kind", max_length=40),
                        optional_text(source_ref, "source_ref", max_length=2000),
                        optional_text(source_version, "source_version", max_length=200),
                        catalog.operation_hash(operation),
                        now,
                        change["id"],
                    ),
                )
                updated.append({
                    "id": change["id"],
                    "method": operation["method"],
                    "path": operation["path"],
                    "fields": change["fields"],
                })
            for stale in diff["missing"]:
                self._conn.execute(
                    "UPDATE api_operations SET status = 'missing', updated_at = ? WHERE id = ?",
                    (now, stale["id"]),
                )
        return {
            "added": added,
            "updated": updated,
            "missing": diff["missing"],
            "unchanged": diff["unchanged"],
        }

    def diff_api_operations(self, project_id: str, operations: Any) -> dict[str, Any]:
        """Report what ingesting the batch would change without writing anything."""
        self._require_project(project_id)
        normalized = self._normalize_operations(operations)
        existing = [
            _row_to_dict(row, _JSON_OPERATION_FIELDS)
            for row in self._fetchall(
                "SELECT * FROM api_operations WHERE project_id = ?", (project_id,)
            )
        ]
        diff = catalog.diff_operations(existing, normalized)
        return {
            "added": [self._operation_summary(item) for item in diff["added"]],
            "changed": [
                {**self._operation_summary(change["operation"]), "id": change["id"],
                 "fields": change["fields"]}
                for change in diff["changed"]
            ],
            "missing": diff["missing"],
            "unchanged": diff["unchanged"],
        }

    def list_api_operations(
        self,
        project_id: str | None = None,
        *,
        query: str | None = None,
        method: str | None = None,
        status: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if method:
            clauses.append("method = ?")
            params.append(require_method(method))
        if status:
            clauses.append("status = ?")
            params.append(require_enum(status, "status", OPERATION_STATUSES))
        if query:
            clauses.append("(summary LIKE ? OR path LIKE ? OR operation_id LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = self._fetchone(
            f"SELECT COUNT(*) AS total FROM api_operations{where}", tuple(params)
        )
        rows = self._fetchall(
            "SELECT id, project_id, method, path, path_template, operation_id, summary,"
            " source_kind, source_ref, source_version, status, created_at, updated_at"
            f" FROM api_operations{where} ORDER BY path, method LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 200)), max(0, offset)),
        )
        return {
            "items": [_row_to_dict(row) for row in rows],
            "total": int(total_row["total"]) if total_row is not None else 0,
            "limit": limit,
            "offset": offset,
        }

    def get_api_operation(self, operation_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM api_operations WHERE id = ?", (operation_id,))
        if row is None:
            raise QaNotFoundError(f"operation '{operation_id}' not found")
        return _row_to_dict(row, _JSON_OPERATION_FIELDS)

    def _normalize_operations(self, operations: Any) -> list[dict[str, Any]]:
        if not isinstance(operations, list) or not operations:
            raise QaValidationError("operations must be a non-empty array")
        normalized = [normalize_api_operation(item) for item in operations]
        keys = [(item["method"], item["path"]) for item in normalized]
        if len(set(keys)) != len(keys):
            raise QaValidationError("operations contain duplicate method + path entries")
        return normalized

    def _operation_summary(self, operation: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": operation["method"],
            "path": operation["path"],
            "operation_id": operation.get("operation_id", ""),
            "summary": operation.get("summary", ""),
        }

    def _find_api_operation(
        self, project_id: str, operation: dict[str, str] | None,
    ) -> dict[str, Any] | None:
        if not operation:
            return None
        if "operation_id" in operation:
            row = self._fetchone(
                "SELECT * FROM api_operations WHERE id = ? AND project_id = ?",
                (operation["operation_id"], project_id),
            )
            target = operation["operation_id"]
        else:
            row = self._fetchone(
                "SELECT * FROM api_operations WHERE project_id = ? AND method = ? AND path = ?",
                (project_id, operation["method"], operation["path"]),
            )
            target = f"{operation['method']} {operation['path']}"
        if row is None:
            raise QaValidationError(f"operation '{target}' is not in this project's catalog")
        return _row_to_dict(row, _JSON_OPERATION_FIELDS)
    # -- api asset workflows -----------------------------------------------

    def create_api_workflow(
        self,
        project_id: str,
        *,
        candidates: Any,
        idempotency_key: str = "",
        kind: str = "api_cases",
        base: Any = None,
    ) -> dict[str, Any]:
        """Stage a candidate batch; the same idempotency key returns the same workflow."""
        self._require_project(project_id)
        key = optional_text(idempotency_key, "idempotency_key", max_length=200)
        if key:
            existing = self._fetchone(
                "SELECT * FROM api_workflows WHERE idempotency_key = ?", (key,)
            )
            if existing is not None:
                return self._row_to_workflow(existing)
        normalized = self._normalize_candidates(candidates)
        workflow_id = new_id("wf")
        now = utcnow_iso()
        self._write(
            "INSERT INTO api_workflows (id, project_id, kind, status, base, candidates,"
            " checkpoint, result, idempotency_key, created_at, updated_at)"
            " VALUES (?, ?, ?, 'pending', ?, ?, '{}', '{}', ?, ?, ?)",
            (
                workflow_id,
                project_id,
                require_text(kind, "kind", max_length=40),
                dumps(normalize_json_object(base, "base")),
                dumps(normalized),
                key,
                now,
                now,
            ),
        )
        return self.get_api_workflow(workflow_id)

    def get_api_workflow(self, workflow_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM api_workflows WHERE id = ?", (workflow_id,))
        if row is None:
            raise QaNotFoundError(f"workflow '{workflow_id}' not found")
        workflow = self._row_to_workflow(row)
        workflow["candidate_count"] = len(workflow["candidates"])
        return workflow

    def replace_api_workflow_candidates(
        self, workflow_id: str, candidates: Any,
    ) -> dict[str, Any]:
        """Replace the staged batch and reset the checkpoint, so a failed batch can resume."""
        workflow = self.get_api_workflow(workflow_id)
        if workflow["status"] == "applied":
            raise QaConflictError(f"workflow '{workflow_id}' is already applied")
        normalized = self._normalize_candidates(candidates)
        self._write(
            "UPDATE api_workflows SET candidates = ?, status = 'pending', checkpoint = '{}',"
            " result = '{}', updated_at = ? WHERE id = ?",
            (dumps(normalized), utcnow_iso(), workflow_id),
        )
        return self.get_api_workflow(workflow_id)

    def apply_api_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Apply a staged batch in one transaction; repeating it changes nothing."""
        workflow = self.get_api_workflow(workflow_id)
        if workflow["status"] == "applied":
            return workflow
        project = self._require_project(workflow["project_id"])
        try:
            prepared = [
                self._prepare_candidate(project, candidate)
                for candidate in workflow["candidates"]
            ]
        except Exception as exc:
            self._fail_workflow(workflow_id, {"errors": [str(exc)]})
            raise
        applied: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        try:
            with self._transaction():
                for item in prepared:
                    row = item["row"]
                    existing_case_id = item["existing_case_id"]
                    if existing_case_id:
                        latest = self._latest_case_revision_row(existing_case_id)
                        latest_revision = int(latest["revision"]) if latest is not None else 0
                        if (
                            item["base_revision"] is not None
                            and item["base_revision"] != latest_revision
                        ):
                            raise QaConflictError(
                                f"case '{row['code']}' is at revision {latest_revision},"
                                f" not {item['base_revision']}"
                            )
                        self._conn.execute(
                            _UPDATE_CASE_SQL,
                            (*[row[field] for field in _CASE_BODY_FIELDS], existing_case_id),
                        )
                        self._insert_case_revision(
                            existing_case_id,
                            revision=latest_revision + 1,
                            change_source="workflow",
                            changed_by="",
                        )
                        case_id = existing_case_id
                        revision = latest_revision + 1
                        updated.append({
                            "case_id": case_id, "code": row["code"], "revision": revision,
                        })
                    else:
                        duplicate = self._find_identical_case(
                            project["id"], self._prepared_snapshot(row)
                        )
                        if duplicate is not None:
                            skipped.append({
                                "code": row["code"],
                                "reason": "identical content",
                                "case_id": duplicate,
                            })
                            continue
                        self._conn.execute(
                            _INSERT_CASE_SQL, tuple(row[column] for column in _CASE_COLUMNS)
                        )
                        self._insert_case_revision(
                            row["id"], revision=1, change_source="workflow", changed_by="",
                        )
                        case_id = row["id"]
                        revision = 1
                        applied.append({
                            "case_id": case_id, "code": row["code"], "revision": revision,
                        })
                    if item["operation"] is not None or item["scenario_key"]:
                        self._upsert_case_metadata(
                            case_id,
                            operation_id=item["operation"]["id"] if item["operation"] else None,
                            scenario_key=item["scenario_key"],
                            evidence=item["evidence"],
                            revision=revision,
                        )
                checkpoint = {"applied": applied, "updated": updated, "skipped": skipped}
                result = {
                    "applied": len(applied),
                    "updated": len(updated),
                    "skipped": len(skipped),
                }
                self._conn.execute(
                    "UPDATE api_workflows SET status = 'applied', checkpoint = ?, result = ?,"
                    " updated_at = ? WHERE id = ?",
                    (dumps(checkpoint), dumps(result), utcnow_iso(), workflow_id),
                )
        except Exception as exc:
            self._fail_workflow(workflow_id, {"errors": [str(exc)]})
            raise
        return self.get_api_workflow(workflow_id)

    def _prepare_candidate(
        self, project: dict[str, Any], candidate: dict[str, Any],
    ) -> dict[str, Any]:
        operation = self._find_api_operation(project["id"], candidate["operation"])
        payload = candidate["case"]
        existing_case_id: str | None = None
        if operation is not None and candidate["scenario_key"]:
            row = self._fetchone(
                "SELECT case_id FROM api_case_metadata"
                " WHERE operation_id = ? AND scenario_key = ?",
                (operation["id"], candidate["scenario_key"]),
            )
            existing_case_id = row["case_id"] if row is not None else None
        code = payload.get("code")
        if existing_case_id is not None and not code:
            code = self.get_case(existing_case_id)["code"]
        row = self._prepare_case(
            project,
            case_id=existing_case_id or new_id("case"),
            title=payload.get("title", ""),
            kind=payload.get("kind", "api"),
            code=code,
            priority=payload.get("priority", "P1"),
            status=payload.get("status", "draft"),
            preconditions=payload.get("preconditions", ""),
            steps=payload.get("steps"),
            api=payload.get("api"),
            expected=payload.get("expected", ""),
            tags=payload.get("tags"),
            source=payload.get("source", "ai"),
            author=payload.get("author", ""),
            exclude_case_id=existing_case_id,
        )
        return {
            "row": row,
            "operation": operation,
            "scenario_key": candidate["scenario_key"],
            "evidence": candidate["evidence"],
            "base_revision": candidate["base_revision"],
            "existing_case_id": existing_case_id,
        }

    def _find_identical_case(
        self, project_id: str, snapshot: dict[str, Any],
    ) -> str | None:
        row = self._fetchone(
            "SELECT r.case_id AS case_id FROM api_case_revisions r"
            " JOIN cases c ON c.id = r.case_id"
            " WHERE c.project_id = ? AND r.content_hash = ? LIMIT 1",
            (project_id, sha256_json(snapshot)),
        )
        return row["case_id"] if row is not None else None

    def _upsert_case_metadata(
        self,
        case_id: str,
        *,
        operation_id: str | None,
        scenario_key: str,
        evidence: list[dict[str, str]],
        revision: int,
    ) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO api_case_metadata (case_id, operation_id, scenario_key, evidence,"
            " revision, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET operation_id = excluded.operation_id,"
            " scenario_key = excluded.scenario_key, evidence = excluded.evidence,"
            " revision = excluded.revision, updated_at = excluded.updated_at",
            (case_id, operation_id, scenario_key, dumps(evidence), revision, now),
        )

    def _normalize_candidates(self, candidates: Any) -> list[dict[str, Any]]:
        if not isinstance(candidates, list) or not candidates:
            raise QaValidationError("candidates must be a non-empty array")
        normalized = [
            normalize_case_candidate(item, index) for index, item in enumerate(candidates)
        ]
        seen: set[tuple[str, str]] = set()
        for item in normalized:
            operation = item["operation"]
            if operation is None:
                continue
            target = operation.get("operation_id") or (
                f"{operation.get('method')} {operation.get('path')}"
            )
            key = (target, item["scenario_key"])
            if key in seen:
                raise QaValidationError(
                    f"candidates contain a duplicate {target} + '{item['scenario_key']}' pair"
                )
            seen.add(key)
        return normalized

    def _row_to_workflow(self, row: sqlite3.Row) -> dict[str, Any]:
        data = _row_to_dict(row)
        for field in ("base", "candidates", "checkpoint", "result"):
            data[field] = loads(data.get(field), {})
        if not isinstance(data.get("candidates"), list):
            data["candidates"] = []
        for field in ("base", "checkpoint", "result"):
            if not isinstance(data.get(field), dict):
                data[field] = {}
        return data

    def _fail_workflow(self, workflow_id: str, result: dict[str, Any]) -> None:
        """Record why a batch did not apply; the workflow stays resumable."""
        self._write(
            "UPDATE api_workflows SET status = 'failed', result = ?, updated_at = ?"
            " WHERE id = ?",
            (dumps(result), utcnow_iso(), workflow_id),
        )

    # -- overview ----------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        counts_row = self._fetchone(
            "SELECT"
            " (SELECT COUNT(*) FROM projects) AS projects,"
            " (SELECT COUNT(*) FROM cases) AS cases,"
            " (SELECT COUNT(*) FROM cases WHERE status = 'ready') AS ready_cases,"
            " (SELECT COUNT(*) FROM scripts) AS scripts,"
            " (SELECT COUNT(*) FROM runs) AS runs,"
            " (SELECT COUNT(*) FROM tasks) AS tasks,"
            " (SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')) AS active_tasks"
        )
        counts = {
            key: int(counts_row[key])
            for key in (
                "projects", "cases", "ready_cases", "scripts", "runs", "tasks", "active_tasks",
            )
        } if counts_row is not None else {}
        recent_tasks = self.list_tasks(limit=8)["items"]
        recent_runs = self.list_runs(limit=8)["items"]
        return {
            "counts": counts,
            "projects": self.list_projects(),
            "recent_tasks": recent_tasks,
            "recent_runs": recent_runs,
        }
