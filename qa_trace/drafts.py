"""Draft batches, review approval and rejection (plan sections 3.3, 3.4, 9).

The agent only ever writes drafts.  A draft lives at
``draft/<batch-id>/<collection>/<ID>.yaml`` and is invisible to the formal
library, to coverage and to ``qa trace check`` unless ``--include-draft`` is
passed.  ``qa trace review approve`` is the only path from ``draft/`` into
``sources|testpoints|cases``:

1. the draft is parsed and validated as an entity (a structurally broken draft is
   refused with the model's diagnostics),
2. the *candidate* library — the formal library plus exactly this draft — is
   checked with the same graph and marker rules as the real library, so a draft
   cannot be promoted into a broken chain,
3. the review requirements are enforced (upstream sources active/confirmed/not
   stale, upstream test points reviewed),
4. the file is written into the formal collection atomically, the project is
   reloaded, and the approved fingerprint is recorded in the derived index.

An existing formal entity is never overwritten by a *new* draft: an update draft
must declare ``base_content_hash`` equal to the current content hash, which is
how two people editing the same entity are kept from silently clobbering each
other (plan section 3.1).

``qa trace review approve`` also accepts an already-formal test point or case.
That is a **re-review**: no file is written, but the current fingerprint is
recorded as the approved one, which is what clears ``needs_recheck`` after an
upstream source changed.  A *source* has no review status: promoting a source
draft accepts it into the library and records its baseline only.  ``qa trace
review reject`` only applies to drafts; it records the rejection in the index and
leaves the file in ``draft/``.

Exit codes: ``0`` success, ``1`` the draft/entity is unknown, invalid, blocked or
conflicting, ``2`` input/tool failure (bad arguments, unreadable YAML/project,
unreadable index).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .diagnostics import Diagnostic, Severity, from_error, relative_path, sort_diagnostics
from .errors import (
    DraftBaseMismatchError,
    DraftError,
    DraftIdConflictError,
    DraftNotFoundError,
    EntityNotFoundError,
    QaTraceError,
    ReferenceMissingError,
    ReviewBlockedError,
    SchemaError,
)
from .graph import TraceGraph
from .hashing import content_hash, fingerprint_project, sha256_bytes
from .ids import MODULE_PATTERN, IdKind, ensure_kind, new_id, parse_id
from .index import (
    DRAFT_STATUS_REJECTED,
    DraftRecord,
    ProjectIndex,
    clear_draft_record,
    load_index,
    record_draft_rejection,
    require_compatible,
    upsert_baseline,
    upsert_review,
    write_index,
)
from .loader import (
    COLLECTIONS,
    DRAFT_DIRNAME,
    PROJECT_FILE,
    YAML_SUFFIXES,
    Project,
    load_project,
    load_yaml_document,
)
from .markers import check_markers
from .models import (
    Case,
    Confidence,
    EntityStatus,
    ReviewStatus,
    Source,
    TestPoint,
    validate_schema_version,
)
from .rules import check_graph
from .staleness import recheck_map, utc_now

#: Version of the ``review list`` JSON document.
REVIEW_VERSION = 1

#: The batch a draft command uses when ``--batch`` is not given.
DEFAULT_BATCH = "default"

#: Draft kinds and the collection directory each one is written to.
COLLECTION_BY_KIND: dict[str, str] = {
    "source": "sources",
    "testpoint": "testpoints",
    "case": "cases",
}

KIND_BY_COLLECTION: dict[str, str] = {
    collection: kind for kind, collection in COLLECTION_BY_KIND.items()
}

MODEL_BY_KIND: dict[str, type[Source] | type[TestPoint] | type[Case]] = {
    "source": Source,
    "testpoint": TestPoint,
    "case": Case,
}

_BATCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

MODE_PROMOTED = "promoted"
MODE_REVIEWED = "reviewed"


def _kind_for_id_kind(kind: IdKind) -> str:
    if kind is IdKind.CASE:
        return "case"
    if kind is IdKind.TESTPOINT:
        return "testpoint"
    return "source"


def _check_batch(batch: str) -> str:
    text = batch.strip()
    if not _BATCH_PATTERN.match(text):
        raise DraftError(
            "batch must be 1-64 characters of letters, digits, dot, dash or underscore",
            field="batch",
        )
    return text


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` to ``path`` atomically and return the final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


@dataclass(frozen=True, slots=True)
class DraftEntity:
    """One draft file, parsed as far as its content allows."""

    batch: str
    path: Path
    kind: str
    entity_id: str
    raw: Mapping[str, Any] = field(default_factory=dict)
    entity: Source | TestPoint | Case | None = None
    errors: tuple[QaTraceError, ...] = ()
    content_hash: str | None = None
    base_content_hash: str | None = None
    file_hash: str | None = None
    status: str = "pending"
    rejected_by: str | None = None
    rejected_at: str | None = None
    note: str | None = None

    @property
    def key(self) -> str:
        """Return the ``<batch>/<id>`` key of this draft."""
        return f"{self.batch}/{self.entity_id}"

    @property
    def valid(self) -> bool:
        """Whether the draft parses as a complete entity."""
        return self.entity is not None and not self.errors

    @property
    def rejected(self) -> bool:
        """Whether this exact draft content was rejected."""
        return self.status == DRAFT_STATUS_REJECTED

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        """Return the stable machine-readable form of this draft."""
        return {
            "batch": self.batch,
            "id": self.entity_id,
            "kind": self.kind,
            "path": relative_path(self.path, root) if root is not None else self.path.as_posix(),
            "status": self.status,
            "valid": self.valid,
            "problems": [error.format() for error in self.errors],
            "content_hash": self.content_hash,
            "base_content_hash": self.base_content_hash,
            "file_hash": self.file_hash,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at,
            "note": self.note,
        }


def list_batches(root: str | Path) -> tuple[str, ...]:
    """Return the draft batch names of a project, sorted."""
    directory = Path(root) / DRAFT_DIRNAME
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            path.name
            for path in directory.iterdir()
            if path.is_dir() and _BATCH_PATTERN.match(path.name)
        )
    )


def _read_draft(
    path: Path, *, batch: str, kind: str, index: ProjectIndex
) -> DraftEntity:
    errors: list[QaTraceError] = []
    raw: Mapping[str, Any] = {}
    entity: Source | TestPoint | Case | None = None
    try:
        document = load_yaml_document(path)
    except QaTraceError as exc:
        errors.append(exc)
        document = None
    if document is not None and not isinstance(document, Mapping):
        errors.append(SchemaError("the file root must be a mapping", path=path))
        document = None
    if isinstance(document, Mapping):
        raw = document
        declared = document.get("id")
        if declared is None:
            errors.append(
                ReferenceMissingError("a draft needs an id", path=path, field="id")
            )
        elif not isinstance(declared, str):
            errors.append(
                ReferenceMissingError("id must be a string", path=path, field="id")
            )
    entity_id = path.stem
    if isinstance(raw.get("id"), str):
        try:
            entity_id = parse_id(raw["id"], path=path, field="id").value
        except QaTraceError as exc:
            errors.append(exc)
    if entity_id != path.stem:
        errors.append(
            ReferenceMissingError(
                f"file {path.name} declares id {entity_id}; expected {entity_id}.yaml",
                path=path,
                field="id",
            )
        )
    if _is_known_id(entity_id) and _kind_for_id_kind(parse_id(entity_id).kind) != kind:
        errors.append(
            ReferenceMissingError(
                f"{entity_id} is not a {kind} ID but sits in {COLLECTION_BY_KIND[kind]}/",
                path=path,
                field="id",
            )
        )
    if raw:
        try:
            validate_schema_version(raw.get("schema_version"), path=path)
        except QaTraceError as exc:
            errors.append(exc)
    if not errors and raw:
        model = MODEL_BY_KIND[kind]
        try:
            entity = model.from_dict(raw, path=path)  # type: ignore[union-attr]
        except QaTraceError as exc:
            errors.append(exc)
    base = raw.get("base_content_hash")
    base_content_hash = base if isinstance(base, str) and base.strip() else None
    try:
        file_hash: str | None = sha256_bytes(path.read_bytes())
    except OSError:  # pragma: no cover - the file was just listed
        file_hash = None
    record = index.drafts.get(f"{batch}/{entity_id}")
    rejected = record is not None and record.file_hash == file_hash
    return DraftEntity(
        batch=batch,
        path=path,
        kind=kind,
        entity_id=entity_id,
        raw=raw,
        entity=entity,
        errors=tuple(errors),
        content_hash=content_hash(entity) if entity is not None else None,
        base_content_hash=base_content_hash,
        file_hash=file_hash,
        status=DRAFT_STATUS_REJECTED if rejected else "pending",
        rejected_by=record.reviewed_by if rejected and record is not None else None,
        rejected_at=record.reviewed_at if rejected and record is not None else None,
        note=record.note if rejected and record is not None else None,
    )


def _is_known_id(value: str) -> bool:
    try:
        parse_id(value)
    except QaTraceError:
        return False
    return True


def load_batch(
    root: str | Path, batch: str, *, index: ProjectIndex | None = None
) -> tuple[DraftEntity, ...]:
    """Load one draft batch, in collection and file order."""
    root_path = Path(root)
    active_index = index if index is not None else load_index(root_path)
    base = root_path / DRAFT_DIRNAME / batch
    if not base.is_dir():
        return ()
    drafts: list[DraftEntity] = []
    for collection in COLLECTIONS:
        directory = base / collection
        if not directory.is_dir():
            continue
        kind = KIND_BY_COLLECTION[collection]
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in YAML_SUFFIXES:
                continue
            drafts.append(_read_draft(path, batch=batch, kind=kind, index=active_index))
    return tuple(drafts)


def load_all_drafts(
    root: str | Path, *, index: ProjectIndex | None = None
) -> tuple[DraftEntity, ...]:
    """Load every draft of a project, batch by batch."""
    root_path = Path(root)
    active_index = index if index is not None else load_index(root_path)
    drafts: list[DraftEntity] = []
    for batch in list_batches(root_path):
        drafts.extend(load_batch(root_path, batch, index=active_index))
    return tuple(drafts)


def _select_drafts(
    root: str | Path,
    entity_id: str,
    *,
    batch: str | None,
    index: ProjectIndex,
) -> list[DraftEntity]:
    """Return every draft carrying ``entity_id`` (optionally within one batch)."""
    root_path = Path(root)
    if batch is not None:
        return [
            item
            for item in load_batch(root_path, _check_batch(batch), index=index)
            if item.entity_id == entity_id
        ]
    return [
        item for item in load_all_drafts(root_path, index=index)
        if item.entity_id == entity_id
    ]


def _one_draft(
    matches: Sequence[DraftEntity], entity_id: str, batch: str | None
) -> DraftEntity:
    """Return the single match, raising when there is none or the choice is ambiguous."""
    if not matches:
        raise DraftNotFoundError(
            f"no draft carries {entity_id}" + (f" in batch {batch!r}" if batch else ""),
            field="id",
        )
    if len(matches) > 1:
        batches = ", ".join(sorted(item.batch for item in matches))
        raise DraftNotFoundError(
            f"draft {entity_id} exists in several batches ({batches}); pass --batch",
            field="id",
        )
    return matches[0]


def find_draft(
    root: str | Path,
    entity_id: str,
    *,
    batch: str | None = None,
    index: ProjectIndex | None = None,
) -> DraftEntity:
    """Return the one draft carrying ``entity_id``, raising when absent/ambiguous."""
    active_index = index if index is not None else load_index(root)
    matches = _select_drafts(root, entity_id, batch=batch, index=active_index)
    return _one_draft(matches, entity_id, batch)


def promoted_entity(entity: Source | TestPoint | Case) -> Source | TestPoint | Case:
    """Return the entity as it will look in the formal library.

    A draft test point or case is stored with ``status: draft`` (honest about
    where it lives) and becomes ``reviewed`` on promotion; everything else is
    promoted unchanged.
    """
    if isinstance(entity, (TestPoint, Case)) and entity.status is ReviewStatus.DRAFT:
        return replace(entity, status=ReviewStatus.REVIEWED)
    return entity


def candidate_project(project: Project, drafts: Sequence[DraftEntity]) -> Project:
    """Return the formal library with ``drafts`` promoted into it."""
    sources = dict(project.sources)
    testpoints = dict(project.testpoints)
    cases = dict(project.cases)
    files = dict(project.files)
    for draft in drafts:
        if draft.entity is None:
            continue
        entity = promoted_entity(draft.entity)
        if isinstance(entity, Source):
            sources[entity.id] = entity
        elif isinstance(entity, TestPoint):
            testpoints[entity.id] = entity
        else:
            cases[entity.id] = entity
        files[entity.id] = draft.path
    return Project(
        root=project.root,
        config=project.config,
        sources=sources,
        testpoints=testpoints,
        cases=cases,
        files=files,
    )


def _batch_diagnostics(project: Project, drafts: Sequence[DraftEntity]) -> tuple[Diagnostic, ...]:
    """Check the candidate library and keep the findings about the batch."""
    candidate = candidate_project(project, drafts)
    identifiers = {draft.entity_id for draft in drafts}
    prefix = f"{DRAFT_DIRNAME}/"
    found: list[Diagnostic] = []
    for diagnostic in (*check_graph(candidate), *check_markers(candidate)):
        if diagnostic.entity_id in identifiers:
            found.append(diagnostic)
        elif diagnostic.path is not None and diagnostic.path.startswith(prefix):
            found.append(diagnostic)
    return sort_diagnostics(found)


def check_draft_batches(project: Project) -> tuple[Diagnostic, ...]:
    """Validate every non-rejected draft batch of a project.

    Each batch is checked on its own candidate graph (formal library + that
    batch), so a draft that depends on another, unpromoted batch is reported as
    dangling instead of silently passing.  An unreadable index only costs the
    rejection state: the drafts are still validated.
    """
    try:
        index = require_compatible(
            load_index(project.root, project_id=project.config.project_id)
        )
    except QaTraceError:
        index = ProjectIndex(root=project.root, project_id=project.config.project_id)
    diagnostics: list[Diagnostic] = []
    for batch in list_batches(project.root):
        drafts = [
            item
            for item in load_batch(project.root, batch, index=index)
            if not item.rejected
        ]
        for draft in drafts:
            for error in draft.errors:
                diagnostics.append(
                    from_error(error, root=project.root, entity_id=draft.entity_id)
                )
        diagnostics.extend(_batch_diagnostics(project, drafts))
    return sort_diagnostics(diagnostics)


def _draft_path(root: Path, batch: str, kind: str, entity_id: str) -> Path:
    return root / DRAFT_DIRNAME / batch / COLLECTION_BY_KIND[kind] / f"{entity_id}.yaml"


def _skeleton(
    kind: str,
    identifier: str,
    *,
    module: str,
    title: str | None,
    testpoint: str | None,
    source: str | None,
    source_type: str,
    today: date,
) -> dict[str, Any]:
    """Return the starter document of a new draft."""
    if kind == "case":
        payload: dict[str, Any] = {
            "schema_version": 1,
            "id": identifier,
            "module": module,
            "title": title or "TODO: 用例标题",
            "priority": "P1",
            "type": "functional",
            "status": "draft",
            "steps": [
                {
                    "action": "TODO: 操作步骤",
                    "expected": "TODO: 可判定的预期结果（文案 / 状态码 / 数据变化）",
                }
            ],
            "automation": {"status": "manual"},
            "note": "qa trace draft new 生成的草稿；补充内容后执行 qa trace review approve",
        }
        if testpoint is not None:
            payload["testpoints"] = [testpoint]
        if source is not None:
            payload["sources"] = [source]
            payload["direct_reason"] = "TODO: 说明为什么不经过测试点"
            payload["risk"] = "high"
        return payload
    if kind == "testpoint":
        return {
            "schema_version": 1,
            "id": identifier,
            "module": module,
            "title": title or "TODO: 测试点标题",
            "sources": [source] if source is not None else [],
            "method": "boundary",
            "risk": "high",
            "status": "draft",
            "note": "qa trace draft new 生成的草稿；补充内容后执行 qa trace review approve",
        }
    payload = {
        "schema_version": 1,
        "id": identifier,
        "type": source_type,
        "module": module,
        "title": title or "TODO: 来源标题",
        "evidence": [
            {
                "type": _evidence_type(source_type),
                "locator": "TODO: 证据位置",
                "description": "TODO: 这条证据说明了什么",
            }
        ],
        "confidence": "observed",
        "status": "active",
        "note": "qa trace draft new 生成的草稿；补齐证据后执行 qa trace review approve",
    }
    if source_type == "ui":
        payload["url"] = "/TODO"
        payload["app_version"] = "TODO"
        payload["observed_at"] = today.isoformat()
    return payload


def _evidence_type(source_type: str) -> str:
    return {
        "req": "document",
        "api": "openapi",
        "ui": "ui_capture",
        "bug": "issue",
        "std": "standard",
        "ex": "exploration",
    }.get(source_type, "document")


def _validate_module(module: str) -> str:
    text = module.strip().upper()
    if not MODULE_PATTERN.match(text):
        raise DraftError(
            f"{module!r} is not a valid module (uppercase letters, digits and "
            "underscores, starting with a letter)",
            field="module",
        )
    return text


def new_draft(
    root: str | Path,
    *,
    kind: str,
    module: str,
    batch: str = DEFAULT_BATCH,
    title: str | None = None,
    testpoint: str | None = None,
    source: str | None = None,
    source_type: str = "ui",
    today: date | None = None,
) -> Path:
    """Write a starter draft and return its path."""
    root_path = Path(root)
    if not (root_path / PROJECT_FILE).is_file():
        raise DraftError(f"no {PROJECT_FILE} in {root_path}", path=root_path)
    load_project(root_path)  # a draft is only written into a loadable project
    if kind not in MODEL_BY_KIND:
        raise DraftError(
            f"unknown draft kind {kind!r}; expected one of "
            f"{', '.join(sorted(MODEL_BY_KIND))}",
            field="kind",
        )
    batch_name = _check_batch(batch)
    module_name = _validate_module(module)
    if kind == "testpoint" and source is None:
        raise DraftError("a test point draft needs --source", field="source")
    if kind == "case" and testpoint is None and source is None:
        raise DraftError(
            "a case draft needs --testpoint or --source", field="testpoint"
        )
    if testpoint is not None:
        try:
            testpoint = ensure_kind(testpoint, IdKind.TESTPOINT, field="testpoint").value
        except QaTraceError as exc:
            raise DraftError(exc.message, field="testpoint") from None
    if source is not None:
        try:
            source = ensure_kind(source, _source_kind(source_type), field="source").value
        except QaTraceError as exc:
            raise DraftError(exc.message, field="source") from None
    if source_type not in {"req", "api", "ui", "bug", "std", "ex"}:
        raise DraftError(f"unknown source type {source_type!r}", field="type")
    identifier = new_id(
        kind if kind != "source" else _source_kind(source_type),
        module_name,
        uuid4(),
    )
    target = _draft_path(root_path, batch_name, kind, identifier)
    if target.exists():
        raise DraftIdConflictError(f"{identifier} already exists as a draft", path=target)
    payload = _skeleton(
        kind,
        identifier,
        module=module_name,
        title=title,
        testpoint=testpoint,
        source=source,
        source_type=source_type,
        today=today if today is not None else date.today(),
    )
    return _write_yaml(target, payload)


def _source_kind(source_type: str) -> IdKind:
    return {
        "req": IdKind.REQ,
        "api": IdKind.API,
        "ui": IdKind.UI,
        "bug": IdKind.BUG,
        "std": IdKind.STD,
        "ex": IdKind.EX,
    }.get(source_type, IdKind.UI)


def add_draft(
    root: str | Path,
    file: str | Path,
    *,
    batch: str = DEFAULT_BATCH,
    kind: str | None = None,
) -> Path:
    """Copy an externally written YAML document into a draft batch."""
    root_path = Path(root)
    if not (root_path / PROJECT_FILE).is_file():
        raise DraftError(f"no {PROJECT_FILE} in {root_path}", path=root_path)
    project = load_project(root_path)
    source_path = Path(file)
    if not source_path.is_file():
        raise DraftError(f"{source_path} is not a file", path=source_path)
    raw = load_yaml_document(source_path)
    if not isinstance(raw, Mapping):
        raise SchemaError("the file root must be a mapping", path=source_path)
    validate_schema_version(raw.get("schema_version"), path=source_path)
    declared = raw.get("id")
    try:
        parsed = parse_id(declared, path=source_path, field="id")
    except QaTraceError as exc:
        raise DraftError(exc.message, path=source_path, field="id") from None
    resolved_kind = _kind_for_id_kind(parsed.kind)
    if kind is not None and kind != resolved_kind:
        raise DraftError(
            f"{parsed.value} is a {resolved_kind} ID, not a {kind} ID",
            path=source_path,
            field="id",
        )
    batch_name = _check_batch(batch)
    identifier = parsed.value
    target = _draft_path(root_path, batch_name, resolved_kind, identifier)
    for other in load_all_drafts(root_path):
        if other.entity_id == identifier:
            raise DraftIdConflictError(
                f"{identifier} already exists as a draft in batch {other.batch!r}",
                path=other.path,
            )
    formal = (
        project.sources.get(identifier)
        or project.testpoints.get(identifier)
        or project.cases.get(identifier)
    )
    base = raw.get("base_content_hash")
    base_content_hash = base if isinstance(base, str) and base.strip() else None
    if formal is not None:
        if base_content_hash is None:
            raise DraftIdConflictError(
                (
                    f"{identifier} already exists in the formal library; an update draft "
                    "must declare base_content_hash"
                ),
                path=source_path,
                field="base_content_hash",
            )
        current = content_hash(formal)
        if base_content_hash != current:
            raise DraftBaseMismatchError(
                (
                    f"base_content_hash does not match the current content of {identifier}; "
                    "re-read the formal entity before editing it"
                ),
                path=source_path,
                field="base_content_hash",
            )
    elif base_content_hash is not None:
        raise DraftError(
            f"base_content_hash is declared but {identifier} is not in the formal library",
            path=source_path,
            field="base_content_hash",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(source_path.read_bytes())
    except OSError as exc:  # pragma: no cover - disk failure
        raise DraftError(f"cannot write {target}: {exc}", path=target) from exc
    return target


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """The result of one approve/reject call."""

    entity_id: str
    kind: str
    mode: str
    path: str | None
    reviewer: str | None
    reviewed_at: str
    content_hash: str | None = None
    dependency_hash: str | None = None
    note: str | None = None
    needs_recheck: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this outcome."""
        return {
            "review_version": REVIEW_VERSION,
            "id": self.entity_id,
            "kind": self.kind,
            "mode": self.mode,
            "path": self.path,
            "reviewed_by": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "content_hash": self.content_hash,
            "dependency_hash": self.dependency_hash,
            "note": self.note,
            "needs_recheck": self.needs_recheck,
        }


def _source_blockers(source: Source) -> tuple[str, ...]:
    blockers: list[str] = []
    if source.status is not EntityStatus.ACTIVE:
        blockers.append(f"source {source.id} is deprecated")
    if source.confidence is not Confidence.CONFIRMED:
        blockers.append(
            f"source {source.id} is only observed; confirm the expected basis first"
        )
    if source.stale:
        blockers.append(
            f"source {source.id} is stale; clear its stale flag explicitly before "
            "re-reviewing the downstream asset"
        )
    return tuple(blockers)


def _review_blockers(
    project: Project, entity: Source | TestPoint | Case, graph: TraceGraph
) -> tuple[str, ...]:
    """Return the business reasons that forbid approving ``entity``."""
    blockers: list[str] = []
    if isinstance(entity, Case):
        for testpoint_id in entity.testpoints:
            testpoint = project.testpoints.get(testpoint_id)
            if testpoint is None:
                blockers.append(
                    f"test point {testpoint_id} does not exist yet; approve it first"
                )
                continue
            if testpoint.status is not ReviewStatus.REVIEWED:
                blockers.append(
                    f"test point {testpoint_id} is {testpoint.status.value}; review it first"
                )
        for source_id in graph.case_sources(entity.id):
            source = project.sources.get(source_id)
            if source is not None:
                blockers.extend(_source_blockers(source))
        return tuple(blockers)
    if isinstance(entity, TestPoint):
        for source_id in entity.sources:
            source = project.sources.get(source_id)
            if source is None:
                blockers.append(f"source {source_id} does not exist yet; create it first")
            else:
                blockers.extend(_source_blockers(source))
        return tuple(blockers)
    blockers.append(
        f"source {entity.id} has no review status; review the test points or cases that "
        "depend on it"
    )
    return tuple(blockers)


def _dependency_blockers(
    project: Project, entity: Source | TestPoint | Case
) -> tuple[str, ...]:
    """Return references that exist only as drafts (or not at all)."""
    blockers: list[str] = []
    if isinstance(entity, Case):
        for testpoint_id in entity.testpoints:
            if testpoint_id not in project.testpoints:
                blockers.append(
                    f"test point {testpoint_id} is still a draft or missing; approve it first"
                )
        for source_id in entity.sources:
            if source_id not in project.sources:
                blockers.append(
                    f"source {source_id} is still a draft or missing; approve it first"
                )
    elif isinstance(entity, TestPoint):
        for source_id in entity.sources:
            if source_id not in project.sources:
                blockers.append(
                    f"source {source_id} is still a draft or missing; approve it first"
                )
    return tuple(blockers)


def _promote(project: Project, draft: DraftEntity) -> tuple[Path, Project]:
    """Write the draft into the formal collection and reload the project."""
    payload = dict(draft.raw)
    payload.pop("base_content_hash", None)
    if draft.kind in {"testpoint", "case"}:
        payload["status"] = ReviewStatus.REVIEWED.value
    target = project.root / COLLECTION_BY_KIND[draft.kind] / f"{draft.entity_id}.yaml"
    _write_yaml(target, payload)
    reloaded = load_project(project.root)
    return target, reloaded


def _approve_draft(
    project: Project,
    index: ProjectIndex,
    draft: DraftEntity,
    *,
    reviewer: str | None,
    note: str | None,
    now: str,
) -> ReviewOutcome:
    if draft.rejected:
        raise ReviewBlockedError(
            (
                f"draft {draft.entity_id} was rejected; change the draft content or add "
                "it again before approving it"
            ),
            path=draft.path,
            field="id",
        )
    if not draft.valid:
        problems = "; ".join(error.format() for error in draft.errors) or "unreadable"
        raise ReviewBlockedError(
            f"draft {draft.entity_id} is not a valid {draft.kind}: {problems}",
            path=draft.path,
            field="id",
        )
    entity = draft.entity
    assert entity is not None  # narrowed by draft.valid
    formal = (
        project.sources.get(draft.entity_id)
        or project.testpoints.get(draft.entity_id)
        or project.cases.get(draft.entity_id)
    )
    if formal is not None:
        if draft.base_content_hash is None:
            raise DraftIdConflictError(
                (
                    f"{draft.entity_id} already exists in the formal library; an update "
                    "draft must declare base_content_hash"
                ),
                path=draft.path,
                field="base_content_hash",
            )
        if draft.base_content_hash != content_hash(formal):
            raise DraftBaseMismatchError(
                (
                    f"base_content_hash does not match the current content of "
                    f"{draft.entity_id}; the formal entity changed after the draft was written"
                ),
                path=draft.path,
                field="base_content_hash",
            )
    blockers = list(_dependency_blockers(project, entity))
    if blockers:
        raise ReviewBlockedError(
            "cannot promote: " + "; ".join(blockers), path=draft.path, field="id"
        )
    diagnostics = _batch_diagnostics(project, [draft])
    errors = [item for item in diagnostics if item.severity is Severity.ERROR]
    if errors:
        detail = "; ".join(item.format() for item in errors)
        raise ReviewBlockedError(
            f"cannot promote {draft.entity_id}: {detail}", path=draft.path, field="id"
        )
    candidate = candidate_project(project, [draft])
    if draft.kind == "source":
        # A source has no review status: promoting it accepts the entity into the
        # formal library and records its baseline, without claiming a review.
        target, reloaded = _promote(project, draft)
        fingerprint = fingerprint_project(reloaded)[draft.entity_id]
        updated = upsert_baseline(index, {draft.entity_id: fingerprint}, now=now)
        updated = clear_draft_record(updated, draft.key)
        write_index(updated, now=now)
        draft.path.unlink(missing_ok=True)
        _prune_empty_dirs(draft.path.parent, stop=reloaded.root / DRAFT_DIRNAME)
        return ReviewOutcome(
            entity_id=draft.entity_id,
            kind=draft.kind,
            mode=MODE_PROMOTED,
            path=relative_path(target, reloaded.root),
            reviewer=reviewer,
            reviewed_at=now,
            content_hash=fingerprint.content_hash,
            dependency_hash=fingerprint.dependency_hash,
            note=note,
            needs_recheck=False,
        )
    blockers = list(
        _review_blockers(candidate, promoted_entity(entity), TraceGraph(candidate))
    )
    if blockers:
        raise ReviewBlockedError(
            f"cannot approve {draft.entity_id}: " + "; ".join(blockers),
            path=draft.path,
            field="id",
        )
    target, reloaded = _promote(project, draft)
    fingerprint = fingerprint_project(reloaded)[draft.entity_id]
    updated = upsert_review(index, fingerprint, reviewer=reviewer, note=note, now=now)
    updated = clear_draft_record(updated, draft.key)
    write_index(updated, now=now)
    draft.path.unlink(missing_ok=True)
    _prune_empty_dirs(draft.path.parent, stop=reloaded.root / DRAFT_DIRNAME)
    rechecks = recheck_map(reloaded)
    return ReviewOutcome(
        entity_id=draft.entity_id,
        kind=draft.kind,
        mode=MODE_PROMOTED,
        path=relative_path(target, reloaded.root),
        reviewer=reviewer,
        reviewed_at=now,
        content_hash=fingerprint.content_hash,
        dependency_hash=fingerprint.dependency_hash,
        note=note,
        needs_recheck=draft.entity_id in rechecks,
    )


def _prune_empty_dirs(directory: Path, *, stop: Path) -> None:
    """Remove empty directories from ``directory`` up to (not including) ``stop``."""
    current = directory
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _re_review(
    project: Project,
    index: ProjectIndex,
    entity_id: str,
    *,
    reviewer: str | None,
    note: str | None,
    now: str,
) -> ReviewOutcome:
    entity = (
        project.sources.get(entity_id)
        or project.testpoints.get(entity_id)
        or project.cases.get(entity_id)
    )
    if entity is None:
        raise EntityNotFoundError(
            f"{entity_id} is neither a draft nor an entity of this project", field="id"
        )
    if isinstance(entity, Source):
        raise ReviewBlockedError(
            (
                f"source {entity.id} has no review status; review the test points or cases "
                "that depend on it"
            ),
            field="id",
        )
    if entity.status is ReviewStatus.DEPRECATED:
        raise ReviewBlockedError(
            f"{entity_id} is deprecated; re-review a live entity", field="id"
        )
    graph = TraceGraph(project)
    related = {entity_id}
    if isinstance(entity, Case):
        related.update(entity.testpoints)
        related.update(entity.sources)
        related.update(graph.case_sources(entity_id))
    else:
        related.update(entity.sources)
    errors = [
        item
        for item in (*check_graph(project, graph), *check_markers(project))
        if item.severity is Severity.ERROR and item.entity_id in related
    ]
    if errors:
        detail = "; ".join(item.format() for item in errors)
        raise ReviewBlockedError(
            f"cannot re-review {entity_id}: {detail}", field="id"
        )
    blockers = _review_blockers(project, entity, graph)
    if blockers:
        raise ReviewBlockedError(
            f"cannot re-review {entity_id}: " + "; ".join(blockers), field="id"
        )
    fingerprint = fingerprint_project(project)[entity_id]
    updated = upsert_review(index, fingerprint, reviewer=reviewer, note=note, now=now)
    write_index(updated, now=now)
    rechecks = recheck_map(project, graph)
    return ReviewOutcome(
        entity_id=entity_id,
        kind=fingerprint.kind,
        mode=MODE_REVIEWED,
        path=relative_path(project.files.get(entity_id), project.root),
        reviewer=reviewer,
        reviewed_at=now,
        content_hash=fingerprint.content_hash,
        dependency_hash=fingerprint.dependency_hash,
        note=note,
        needs_recheck=entity_id in rechecks,
    )


def approve(
    root: str | Path,
    entity_id: str,
    *,
    batch: str | None = None,
    reviewer: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> ReviewOutcome:
    """Promote one draft, or re-review one formal test point/case."""
    moment = now if now is not None else utc_now()
    project = load_project(root)
    index = require_compatible(load_index(project.root, project_id=project.config.project_id))
    matches = _select_drafts(project.root, entity_id, batch=batch, index=index)
    if matches:
        draft = _one_draft(matches, entity_id, batch)
        return _approve_draft(
            project, index, draft, reviewer=reviewer, note=note, now=moment
        )
    return _re_review(project, index, entity_id, reviewer=reviewer, note=note, now=moment)


def reject(
    root: str | Path,
    entity_id: str,
    *,
    batch: str | None = None,
    reviewer: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> ReviewOutcome:
    """Record the rejection of one draft; the file stays in ``draft/``."""
    moment = now if now is not None else utc_now()
    project = load_project(root)
    index = require_compatible(load_index(project.root, project_id=project.config.project_id))
    draft = find_draft(project.root, entity_id, batch=batch, index=index)
    if draft.file_hash is None:  # pragma: no cover - the file was just read
        raise DraftError(f"cannot read {draft.path}", path=draft.path)
    record = DraftRecord(
        batch=draft.batch,
        entity_id=draft.entity_id,
        kind=draft.kind,
        file_hash=draft.file_hash,
        reviewed_by=reviewer,
        reviewed_at=moment,
        note=note,
    )
    updated = record_draft_rejection(index, record)
    write_index(updated, now=moment)
    return ReviewOutcome(
        entity_id=draft.entity_id,
        kind=draft.kind,
        mode="rejected",
        path=relative_path(draft.path, project.root),
        reviewer=reviewer,
        reviewed_at=moment,
        note=note,
    )


@dataclass(frozen=True, slots=True)
class DraftListing:
    """The result of ``qa trace review list``."""

    root: Path
    project_id: str | None
    drafts: tuple[DraftEntity, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Return counts per draft state."""
        return {
            "drafts": len(self.drafts),
            "pending": sum(1 for item in self.drafts if not item.rejected),
            "rejected": sum(1 for item in self.drafts if item.rejected),
            "invalid": sum(1 for item in self.drafts if not item.valid),
            "batches": len({item.batch for item in self.drafts}),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this listing."""
        return {
            "review_version": REVIEW_VERSION,
            "project": {"id": self.project_id, "root": self.root.as_posix()},
            "counts": self.counts,
            "batches": sorted({item.batch for item in self.drafts}),
            "drafts": [item.to_dict(root=self.root) for item in self.drafts],
        }


def list_drafts(root: str | Path, *, batch: str | None = None) -> DraftListing:
    """Return every draft of a project (or one batch)."""
    project = load_project(root)
    index = require_compatible(load_index(project.root, project_id=project.config.project_id))
    if batch is not None:
        drafts = load_batch(project.root, _check_batch(batch), index=index)
    else:
        drafts = load_all_drafts(project.root, index=index)
    return DraftListing(root=project.root, project_id=project.config.project_id, drafts=drafts)


def render_draft_list(listing: DraftListing) -> str:
    """Render a draft listing as aligned plain text."""
    project_id = listing.project_id or "<unknown>"
    counts = listing.counts
    lines = [
        f"qa-trace review: {project_id}",
        (
            "  drafts              "
            f"{counts['drafts']} in {counts['batches']} batch(es); "
            f"{counts['pending']} pending, {counts['rejected']} rejected, "
            f"{counts['invalid']} invalid"
        ),
    ]
    if not listing.drafts:
        lines.append("  (no drafts)")
        return "\n".join(lines)
    for item in listing.drafts:
        state = "rejected" if item.rejected else "pending"
        if not item.valid:
            state += "/invalid"
        lines.append(
            f"    {item.batch}/{item.entity_id}  {item.kind}  {state}"
        )
        if not item.valid:
            for error in item.errors:
                lines.append(f"      {error.format()}")
    return "\n".join(lines)


def render_review_outcome(outcome: ReviewOutcome) -> str:
    """Render an approve/reject outcome as one aligned line."""
    lines = [
        f"qa-trace review {outcome.mode}: {outcome.entity_id}",
        f"  kind                {outcome.kind}",
        f"  path                {outcome.path}",
        f"  reviewer            {outcome.reviewer or '<unnamed>'}",
        f"  reviewed at         {outcome.reviewed_at}",
    ]
    if outcome.content_hash is not None:
        lines.append(f"  content hash        {outcome.content_hash}")
    if outcome.dependency_hash is not None:
        lines.append(f"  dependency hash     {outcome.dependency_hash}")
    if outcome.mode == "rejected":
        lines.append("  status              rejected (stays in draft/)")
    else:
        state = "needs re-check" if outcome.needs_recheck else "current"
        lines.append(f"  state               {state}")
    if outcome.note:
        lines.append(f"  note                {outcome.note}")
    return "\n".join(lines)


__all__ = [
    "COLLECTION_BY_KIND",
    "DEFAULT_BATCH",
    "MODE_PROMOTED",
    "MODE_REVIEWED",
    "REVIEW_VERSION",
    "DraftEntity",
    "DraftListing",
    "ReviewOutcome",
    "add_draft",
    "approve",
    "candidate_project",
    "check_draft_batches",
    "find_draft",
    "list_batches",
    "list_drafts",
    "load_all_drafts",
    "load_batch",
    "new_draft",
    "promoted_entity",
    "reject",
    "render_draft_list",
    "render_review_outcome",
]
