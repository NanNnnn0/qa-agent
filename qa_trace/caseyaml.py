"""Case documents as files: the layout and shape of the YAML case source.

A case is one YAML document named after its ID.  Where the file lives *is* its
review state, which is what makes the file tree readable without a database:

``cases/<ID>.yaml``
    a reviewed case, part of the formal library (it may be loaded into a
    ``Project``; the trace rules then need test points or sources).
``draft/<batch>/cases/<ID>.yaml``
    an unreviewed case.  Drafts are invisible to ``qa trace check`` unless
    ``--include-draft`` is passed, and a draft may still be missing its trace
    link (that is the state a migrated SQLite case starts in).
``tombstones/<ID>.yaml``
    a deleted case.  Its ID is retired and never handed out again; the document
    keeps ``status: deprecated`` plus a ``tombstone`` block so the deletion is
    explained rather than forgotten.

The module only knows the file layout and the document shape; it does not know
the legacy SQLite vocabulary (that is :mod:`qa_trace.compat`) and it does not
touch the derived index (that belongs to the product layer).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .compat import kind_for_type, type_for_kind
from .ids import MODULE_PATTERN, IdKind, parse_id
from .loader import DRAFT_DIRNAME, YAML_SUFFIXES, load_yaml_document
from .models import _CASE_KEYS, AutomationStatus, CaseType, Priority, ReviewStatus, Risk
from .yamlfile import write_yaml

#: Every key a case document may carry; anything else is preserved as-is.
KNOWN_CASE_KEYS: frozenset[str] = frozenset(_CASE_KEYS)

#: Directory (inside a project) holding reviewed cases.
CASES_DIRNAME = "cases"

#: Directory (inside a project) holding tombstones of deleted cases.
TOMBSTONES_DIRNAME = "tombstones"

#: Batch name used by the workbench when the caller does not pick one.
DEFAULT_CASE_BATCH = "workbench"

#: Accepted case codes (the human-facing number, not the trace ID).
CASE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")

#: Maximum sequence number of a counter-style ID.
MAX_SEQ = 999_999


class CaseDocumentError(ValueError):
    """Raised when a case document could never be a valid case."""


def case_module(project_key: str) -> str:
    """Return the module segment used in new case IDs for ``project_key``.

    The ID grammar only allows ``[A-Z][A-Z0-9_]*``, while a project key may also
    contain dashes, so ``my-shop`` becomes ``MY_SHOP`` (``TC-MY_SHOP-001``).
    """
    module = re.sub(r"[^A-Z0-9_]", "_", (project_key or "").strip().upper())
    if not MODULE_PATTERN.match(module):
        raise CaseDocumentError(f"{project_key!r} cannot be used as an ID module")
    return module


def _clean(value: Any) -> Any:
    """Return ``value`` without empty strings/containers (YAML stays compact)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        return dict(value) or None
    if isinstance(value, (list, tuple)):
        return list(value) or None
    return value


def case_document(
    *,
    case_id: str,
    title: str,
    priority: str,
    case_type: str,
    status: str,
    steps: Sequence[Mapping[str, Any]],
    automation: Mapping[str, Any],
    code: str | None = None,
    testpoints: Sequence[str] = (),
    sources: Sequence[str] = (),
    direct_reason: str | None = None,
    risk: str | None = None,
    preconditions: str | None = None,
    postconditions: str | None = None,
    expected: str | None = None,
    api: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    owner: str | None = None,
    tags: Sequence[str] = (),
    note: str | None = None,
    legacy_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical ``Case`` document for one case.

    The key order is the one a reviewer reads top-down (identity, trace link,
    classification, steps, executable contract, bookkeeping); ``write_yaml``
    keeps it.  Optional fields are omitted instead of written as ``null`` so a
    hand-edited file stays terse.
    """
    parsed = parse_id(case_id, field="id")
    if parsed.kind is not IdKind.CASE:
        raise CaseDocumentError(f"{case_id} is not a case ID")
    if not title.strip():
        raise CaseDocumentError("a case needs a title")
    if priority not in {item.value for item in Priority}:
        raise CaseDocumentError(f"unknown priority {priority!r}")
    if case_type not in {item.value for item in CaseType}:
        raise CaseDocumentError(f"unknown type {case_type!r}")
    if status not in {item.value for item in ReviewStatus}:
        raise CaseDocumentError(f"unknown status {status!r}")
    if not steps:
        raise CaseDocumentError("a case needs at least one step")
    document: dict[str, Any] = {"schema_version": 1, "id": case_id}
    for key, value in (("code", code), ("legacy_id", legacy_id)):
        cleaned = _clean(value)
        if cleaned is not None:
            document[key] = cleaned
    document["title"] = title.strip()
    testpoint_values = [item for item in testpoints if item]
    source_values = [item for item in sources if item]
    if testpoint_values:
        document["testpoints"] = testpoint_values
    if source_values:
        document["sources"] = source_values
        reason = _clean(direct_reason)
        if reason is not None:
            document["direct_reason"] = reason
    document["priority"] = priority
    document["type"] = case_type
    document["status"] = status
    risk_value = _clean(risk)
    if risk_value is not None:
        if risk_value not in {item.value for item in Risk}:
            raise CaseDocumentError(f"unknown risk {risk_value!r}")
        document["risk"] = risk_value
    document["steps"] = [dict(step) for step in steps]
    document["automation"] = dict(automation)
    for key, value in (
        ("preconditions", preconditions),
        ("postconditions", postconditions),
        ("expected", expected),
        ("api", api),
        ("data", data),
        ("owner", owner),
        ("note", note),
    ):
        cleaned = _clean(value)
        if cleaned is not None:
            document[key] = cleaned
    tag_values = [item for item in tags if item]
    if tag_values:
        document["tags"] = tag_values
    if extra:
        for key, value in extra.items():
            if key in KNOWN_CASE_KEYS or key in document:
                continue
            cleaned = _clean(value)
            if cleaned is not None:
                document[key] = cleaned
    return document


def automation_block(status: str, script: str | None = None) -> dict[str, Any]:
    """Return an ``automation`` mapping for one case."""
    if status not in {item.value for item in AutomationStatus}:
        raise CaseDocumentError(f"unknown automation status {status!r}")
    block: dict[str, Any] = {"status": status}
    if script is not None:
        block["script"] = script
    return block


def derive_case_type(kind: str | None) -> str:
    """Return the trace ``type`` for a legacy ``kind``."""
    return type_for_kind(kind)


def legacy_kind(case_type: str | None) -> str:
    """Return the legacy ``kind`` for a trace ``type``."""
    return kind_for_type(case_type)


def read_case_document(path: str | Path) -> dict[str, Any]:
    """Read one case document (strict YAML: duplicate keys are refused)."""
    data = load_yaml_document(path)
    if not isinstance(data, Mapping):
        raise CaseDocumentError(f"{Path(path).name} is not a mapping")
    return dict(data)


def write_case_document(path: str | Path, document: Mapping[str, Any]) -> Path:
    """Write one case document atomically."""
    return write_yaml(path, document)


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in YAML_SUFFIXES
    )


def draft_batches(project_root: str | Path) -> tuple[str, ...]:
    """Return the draft batch names of a project, sorted."""
    root = Path(project_root) / DRAFT_DIRNAME
    if not root.is_dir():
        return ()
    return tuple(
        sorted(path.name for path in root.iterdir() if path.is_dir())
    )


def case_files(
    project_root: str | Path,
    *,
    include_drafts: bool = True,
    include_tombstones: bool = False,
) -> list[tuple[Path, str | None]]:
    """Return ``(path, batch)`` for every case document of a project.

    ``batch`` is ``None`` for a reviewed case and for a tombstone; drafts carry
    the batch directory they live in.
    """
    root = Path(project_root)
    found: list[tuple[Path, str | None]] = [
        (path, None) for path in _yaml_files(root / CASES_DIRNAME)
    ]
    if include_drafts:
        for batch in draft_batches(root):
            directory = root / DRAFT_DIRNAME / batch / CASES_DIRNAME
            found.extend((path, batch) for path in _yaml_files(directory))
    if include_tombstones:
        found.extend((path, None) for path in _yaml_files(root / TOMBSTONES_DIRNAME))
    return found


def iter_case_documents(
    project_root: str | Path,
    *,
    include_drafts: bool = True,
    include_tombstones: bool = False,
) -> Iterator[tuple[Path, str | None, dict[str, Any]]]:
    """Yield every case document of a project with its path and batch."""
    for path, batch in case_files(
        project_root,
        include_drafts=include_drafts,
        include_tombstones=include_tombstones,
    ):
        try:
            document = read_case_document(path)
        except (OSError, ValueError):
            continue
        yield path, batch, document


def case_id_of(document: Mapping[str, Any], *, fallback: str | None = None) -> str | None:
    """Return the ID a case document declares, or ``fallback``."""
    value = document.get("id")
    return value if isinstance(value, str) and value.strip() else fallback


def case_numbers(project_root: str | Path, module: str) -> int:
    """Return the highest numeric sequence used by ``module`` in a project.

    Drafts and tombstones count: a deleted ID is retired, never re-issued.
    """
    highest = 0
    for path, _ in case_files(project_root, include_drafts=True, include_tombstones=True):
        try:
            parsed = parse_id(path.stem)
        except Exception:  # noqa: BLE001 - a foreign file in cases/ is not fatal here
            continue
        if parsed.kind is not IdKind.CASE or parsed.module != module:
            continue
        if parsed.seq.isdigit():
            highest = max(highest, int(parsed.seq))
    return highest


def next_case_id(
    project_root: str | Path,
    *,
    project_key: str,
    taken: Iterable[str] = (),
) -> str:
    """Return the next free ``TC-<MODULE>-<seq>`` ID of a project.

    The sequence is the highest one seen on disk (or in ``taken``) plus one, so
    IDs are readable (``TC-SHOP-003``) instead of random.  There is no ID
    allocation ledger yet, so two concurrent writers can race for the same
    number (documented limitation); the write itself is atomic and the loader
    rejects the duplicate file name.
    """
    module = case_module(project_key)
    highest = case_numbers(project_root, module)
    for value in taken:
        try:
            parsed = parse_id(value)
        except Exception:  # noqa: BLE001 - a non-ID is simply not a case number
            continue
        if parsed.kind is IdKind.CASE and parsed.module == module and parsed.seq.isdigit():
            highest = max(highest, int(parsed.seq))
    if highest >= MAX_SEQ:
        raise CaseDocumentError(f"case ID space exhausted in module {module}")
    return f"TC-{module}-{highest + 1:03d}"


def case_relative_path(path: Path, project_root: str | Path) -> str:
    """Return ``path`` relative to the project root as a POSIX string."""
    try:
        return path.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def case_path_for(
    project_root: str | Path,
    case_id: str,
    *,
    status: str,
    batch: str | None = None,
) -> Path:
    """Return where a case document with ``status`` belongs."""
    root = Path(project_root)
    if status == ReviewStatus.REVIEWED.value:
        return root / CASES_DIRNAME / f"{case_id}.yaml"
    if status == ReviewStatus.DEPRECATED.value:
        return root / TOMBSTONES_DIRNAME / f"{case_id}.yaml"
    return root / DRAFT_DIRNAME / (batch or DEFAULT_CASE_BATCH) / CASES_DIRNAME / (
        f"{case_id}.yaml"
    )


__all__ = [
    "CASES_DIRNAME",
    "CASE_CODE_PATTERN",
    "DEFAULT_CASE_BATCH",
    "KNOWN_CASE_KEYS",
    "MAX_SEQ",
    "TOMBSTONES_DIRNAME",
    "CaseDocumentError",
    "automation_block",
    "case_document",
    "case_files",
    "case_id_of",
    "case_module",
    "case_numbers",
    "case_path_for",
    "case_relative_path",
    "derive_case_type",
    "draft_batches",
    "iter_case_documents",
    "legacy_kind",
    "next_case_id",
    "read_case_document",
    "write_case_document",
]
