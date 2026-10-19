"""The derived per-project index: baselines, review records and draft rejections.

The index lives at ``<project>/.qa-trace/index.json`` and is *derived*: deleting
it loses no asset and no run history, only the ability to tell "changed since the
last look" from "never looked at".  It is never YAML, so a review never rewrites
the library files (plan section 3.4; the spec's "派生状态不写回文件").

Two maps answer two different questions:

``baseline``
    the last fingerprint recorded for an entity by ``qa trace stale --write``.
    Comparing against it answers *what changed since the operator last recorded
    the state*.
``reviews``
    the fingerprint a reviewer approved (``qa trace review approve``), or the
    fingerprint adopted without a named reviewer when ``--write`` first saw the
    entity.  Comparing against it answers *is the review still current*.

Keeping them apart is what stops ``stale --write`` from silently approving a
change: it moves the baseline, never an existing review record.

A third map, ``drafts``, only remembers rejections (batch/id → file digest), so a
rejected draft stays in ``draft/`` but is reported as rejected until its content
changes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import TraceIndexError
from .hashing import FINGERPRINT_VERSION, Fingerprint

#: Directory (inside a project) holding the derived index.
INDEX_DIRNAME = ".qa-trace"

#: File name of the index document.
INDEX_FILENAME = "index.json"

#: Version of the index document itself.
INDEX_VERSION = 1

DRAFT_STATUS_REJECTED = "rejected"


def index_path(project_root: str | Path) -> Path:
    """Return the index file path of a project directory."""
    return Path(project_root) / INDEX_DIRNAME / INDEX_FILENAME


def _optional_str(data: Mapping[str, Any], key: str, *, path: Path, entity: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TraceIndexError(
            f"{key} must be a string", path=path, field=f"{entity}.{key}"
        )
    return value


def _required_str(data: Mapping[str, Any], key: str, *, path: Path, entity: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TraceIndexError(
            f"{key} must be a non-empty string", path=path, field=f"{entity}.{key}"
        )
    return value


def _read_upstream(
    data: Mapping[str, Any], *, path: Path, entity: str
) -> dict[str, str | None]:
    raw = data.get("upstream", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TraceIndexError(
            "upstream must be a mapping", path=path, field=f"{entity}.upstream"
        )
    upstream: dict[str, str | None] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TraceIndexError(
                "upstream keys must be entity IDs", path=path, field=f"{entity}.upstream"
            )
        if value is not None and not isinstance(value, str):
            raise TraceIndexError(
                "upstream values must be strings or null",
                path=path,
                field=f"{entity}.upstream.{key}",
            )
        upstream[key] = value
    return upstream


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One recorded fingerprint, optionally with its review record."""

    kind: str
    content_hash: str
    dependency_hash: str
    upstream: Mapping[str, str | None] = field(default_factory=dict)
    recorded_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    note: str | None = None
    adopted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON form of this entry."""
        return {
            "kind": self.kind,
            "content_hash": self.content_hash,
            "dependency_hash": self.dependency_hash,
            "upstream": {key: self.upstream[key] for key in sorted(self.upstream)},
            "recorded_at": self.recorded_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "note": self.note,
            "adopted": self.adopted,
        }

    @classmethod
    def from_dict(
        cls, data: Any, *, path: Path, entity: str
    ) -> IndexEntry:
        """Parse one entry, raising :class:`TraceIndexError` when malformed."""
        if not isinstance(data, Mapping):
            raise TraceIndexError(
                "index entry must be a mapping", path=path, field=entity
            )
        adopted = data.get("adopted", False)
        if not isinstance(adopted, bool):
            raise TraceIndexError(
                "adopted must be true or false", path=path, field=f"{entity}.adopted"
            )
        return cls(
            kind=_required_str(data, "kind", path=path, entity=entity),
            content_hash=_required_str(data, "content_hash", path=path, entity=entity),
            dependency_hash=_required_str(
                data, "dependency_hash", path=path, entity=entity
            ),
            upstream=_read_upstream(data, path=path, entity=entity),
            recorded_at=_optional_str(data, "recorded_at", path=path, entity=entity),
            reviewed_by=_optional_str(data, "reviewed_by", path=path, entity=entity),
            reviewed_at=_optional_str(data, "reviewed_at", path=path, entity=entity),
            note=_optional_str(data, "note", path=path, entity=entity),
            adopted=adopted,
        )


@dataclass(frozen=True, slots=True)
class DraftRecord:
    """The rejection record of one draft entity (the only draft state we keep)."""

    batch: str
    entity_id: str
    kind: str
    file_hash: str
    status: str = DRAFT_STATUS_REJECTED
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    note: str | None = None

    @property
    def key(self) -> str:
        """Return the ``<batch>/<id>`` key of this record."""
        return f"{self.batch}/{self.entity_id}"

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON form of this record."""
        return {
            "batch": self.batch,
            "id": self.entity_id,
            "kind": self.kind,
            "file_hash": self.file_hash,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, key: str, data: Any, *, path: Path) -> DraftRecord:
        """Parse one draft record, raising :class:`TraceIndexError` when malformed."""
        if not isinstance(data, Mapping):
            raise TraceIndexError("draft record must be a mapping", path=path, field=key)
        return cls(
            batch=_required_str(data, "batch", path=path, entity=key),
            entity_id=_required_str(data, "id", path=path, entity=key),
            kind=_required_str(data, "kind", path=path, entity=key),
            file_hash=_required_str(data, "file_hash", path=path, entity=key),
            status=_required_str(data, "status", path=path, entity=key),
            reviewed_by=_optional_str(data, "reviewed_by", path=path, entity=key),
            reviewed_at=_optional_str(data, "reviewed_at", path=path, entity=key),
            note=_optional_str(data, "note", path=path, entity=key),
        )


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    """Everything the index remembers about one project."""

    root: Path
    project_id: str | None = None
    fingerprint_version: int = FINGERPRINT_VERSION
    baseline: Mapping[str, IndexEntry] = field(default_factory=dict)
    reviews: Mapping[str, IndexEntry] = field(default_factory=dict)
    drafts: Mapping[str, DraftRecord] = field(default_factory=dict)
    updated_at: str | None = None

    @property
    def path(self) -> Path:
        """Return the index file path."""
        return index_path(self.root)

    @property
    def exists(self) -> bool:
        """Whether an index file is on disk."""
        return self.path.is_file()

    @property
    def compatible(self) -> bool:
        """Whether the recorded fingerprint recipe matches this build."""
        return self.fingerprint_version == FINGERPRINT_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON document of this index."""
        return {
            "index_version": INDEX_VERSION,
            "fingerprint_version": self.fingerprint_version,
            "project_id": self.project_id,
            "updated_at": self.updated_at,
            "baseline": {key: self.baseline[key].to_dict() for key in sorted(self.baseline)},
            "reviews": {key: self.reviews[key].to_dict() for key in sorted(self.reviews)},
            "drafts": {key: self.drafts[key].to_dict() for key in sorted(self.drafts)},
        }


def _read_map(
    data: Mapping[str, Any], key: str, *, path: Path
) -> Mapping[str, Any]:
    raw = data.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TraceIndexError(f"{key} must be a mapping", path=path, field=key)
    return raw


def load_index(project_root: str | Path, *, project_id: str | None = None) -> ProjectIndex:
    """Read the index of a project; a missing file is an empty index."""
    root = Path(project_root)
    path = index_path(root)
    if not path.is_file():
        return ProjectIndex(root=root, project_id=project_id)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceIndexError(f"cannot read the index: {exc}", path=path) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TraceIndexError(f"index is not valid JSON: {exc}", path=path) from None
    if not isinstance(data, Mapping):
        raise TraceIndexError("index root must be a mapping", path=path)
    version = data.get("index_version")
    if version != INDEX_VERSION:
        raise TraceIndexError(
            f"unsupported index_version {version!r}; this build writes {INDEX_VERSION}",
            path=path,
            field="index_version",
        )
    fingerprint_version = data.get("fingerprint_version")
    if not isinstance(fingerprint_version, int) or isinstance(fingerprint_version, bool):
        raise TraceIndexError(
            "fingerprint_version must be an integer", path=path, field="fingerprint_version"
        )
    recorded_project = data.get("project_id")
    if recorded_project is not None and not isinstance(recorded_project, str):
        raise TraceIndexError(
            "project_id must be a string", path=path, field="project_id"
        )
    if project_id is not None and recorded_project not in (None, project_id):
        raise TraceIndexError(
            (
                f"the index belongs to project {recorded_project!r}, not {project_id!r}; "
                "remove it if the directory was reused"
            ),
            path=path,
            field="project_id",
        )
    baseline = {
        key: IndexEntry.from_dict(value, path=path, entity=f"baseline.{key}")
        for key, value in _read_map(data, "baseline", path=path).items()
    }
    reviews = {
        key: IndexEntry.from_dict(value, path=path, entity=f"reviews.{key}")
        for key, value in _read_map(data, "reviews", path=path).items()
    }
    drafts = {
        key: DraftRecord.from_dict(key, value, path=path)
        for key, value in _read_map(data, "drafts", path=path).items()
    }
    updated_at = data.get("updated_at")
    if updated_at is not None and not isinstance(updated_at, str):
        raise TraceIndexError("updated_at must be a string", path=path, field="updated_at")
    return ProjectIndex(
        root=root,
        project_id=recorded_project if recorded_project is not None else project_id,
        fingerprint_version=fingerprint_version,
        baseline=baseline,
        reviews=reviews,
        drafts=drafts,
        updated_at=updated_at,
    )


def require_compatible(index: ProjectIndex) -> ProjectIndex:
    """Refuse an index written by another fingerprint recipe."""
    if index.compatible:
        return index
    raise TraceIndexError(
        (
            f"the index was written with fingerprint_version {index.fingerprint_version}, "
            f"this build uses {FINGERPRINT_VERSION}; run 'qa trace stale --write' to rebuild it"
        ),
        path=index.path,
        field="fingerprint_version",
    )


def load_index_for_write(
    project_root: str | Path, *, project_id: str | None = None
) -> ProjectIndex:
    """Read the index for a mutation, treating an incompatible one as empty.

    The index is derived, so a write never has to fail because a previous build
    wrote it with another fingerprint recipe: the mutation records fresh hashes
    and the stale baseline is simply gone (which is exactly what
    ``qa trace stale --write`` would do).  Read-only callers keep using
    :func:`require_compatible` so an unreadable/obsolete index stays visible.
    """
    index = load_index(project_root, project_id=project_id)
    if index.compatible:
        return index
    return ProjectIndex(root=Path(project_root), project_id=index.project_id or project_id)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` atomically (temporary file, fsync, ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def write_index(index: ProjectIndex, *, now: str) -> Path:
    """Write the index atomically and return its path."""
    return _write_json(index.path, replace(index, updated_at=now).to_dict())


def upsert_baseline(
    index: ProjectIndex,
    fingerprints: Mapping[str, Fingerprint],
    *,
    now: str,
    adopt_ids: Iterable[str] = (),
) -> ProjectIndex:
    """Record current fingerprints as the baseline, adopting missing reviews.

    ``adopt_ids`` are the entities that already carry a review status in their
    own document (reviewed test points and cases).  They get a review record with
    ``reviewed_by=None`` and ``adopted=True`` when none exists yet, so a library
    that predates P3 is usable without pretending a person reviewed it.  An
    existing review record is never overwritten here.
    """
    adopt = set(adopt_ids)
    baseline = dict(index.baseline)
    reviews = dict(index.reviews)
    for entity_id, fingerprint in fingerprints.items():
        baseline[entity_id] = IndexEntry(
            kind=fingerprint.kind,
            content_hash=fingerprint.content_hash,
            dependency_hash=fingerprint.dependency_hash,
            upstream=fingerprint.upstream,
            recorded_at=now,
        )
        if entity_id in adopt and entity_id not in reviews:
            reviews[entity_id] = IndexEntry(
                kind=fingerprint.kind,
                content_hash=fingerprint.content_hash,
                dependency_hash=fingerprint.dependency_hash,
                upstream=fingerprint.upstream,
                reviewed_at=now,
                adopted=True,
            )
    return replace(index, baseline=baseline, reviews=reviews)


def upsert_review(
    index: ProjectIndex,
    fingerprint: Fingerprint,
    *,
    reviewer: str | None,
    note: str | None,
    now: str,
) -> ProjectIndex:
    """Record an approval: the review fingerprint and the baseline both move.

    The baseline moves for the approved entity only, because approving it means
    its current content is the accepted one.  Upstream entities keep their old
    baseline entry, so a source change stays visible until an operator records a
    new baseline with ``qa trace stale --write``.
    """
    entry = IndexEntry(
        kind=fingerprint.kind,
        content_hash=fingerprint.content_hash,
        dependency_hash=fingerprint.dependency_hash,
        upstream=fingerprint.upstream,
        recorded_at=now,
        reviewed_by=reviewer,
        reviewed_at=now,
        note=note,
        adopted=False,
    )
    reviews = dict(index.reviews)
    reviews[fingerprint.entity_id] = entry
    baseline = dict(index.baseline)
    # The baseline entry is not a review record: it only remembers the accepted
    # content, so it carries neither a reviewer nor a review time.
    baseline[fingerprint.entity_id] = IndexEntry(
        kind=fingerprint.kind,
        content_hash=fingerprint.content_hash,
        dependency_hash=fingerprint.dependency_hash,
        upstream=fingerprint.upstream,
        recorded_at=now,
    )
    return replace(index, baseline=baseline, reviews=reviews)


def record_draft_rejection(
    index: ProjectIndex, record: DraftRecord
) -> ProjectIndex:
    """Store (or replace) the rejection record of one draft entity."""
    drafts = dict(index.drafts)
    drafts[record.key] = record
    return replace(index, drafts=drafts)


def clear_draft_record(index: ProjectIndex, key: str) -> ProjectIndex:
    """Forget the rejection record of one draft (it was promoted)."""
    if key not in index.drafts:
        return index
    drafts = dict(index.drafts)
    del drafts[key]
    return replace(index, drafts=drafts)


__all__ = [
    "INDEX_DIRNAME",
    "INDEX_FILENAME",
    "INDEX_VERSION",
    "DRAFT_STATUS_REJECTED",
    "DraftRecord",
    "IndexEntry",
    "ProjectIndex",
    "clear_draft_record",
    "index_path",
    "load_index",
    "load_index_for_write",
    "record_draft_rejection",
    "require_compatible",
    "upsert_baseline",
    "upsert_review",
    "write_index",
]
