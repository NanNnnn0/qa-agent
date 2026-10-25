"""Load a qa-trace project directory into validated entities.

A project lives at ``projects/<project-id>/`` and contains ``project.yaml`` plus
the ``sources/``, ``testpoints/`` and ``cases/`` collections.  Every collection
file is named after the ID it declares (``cases/TC-LOGIN-003.yaml``).

The loader validates one entity at a time and collects every error it finds, so
a broken project reports all problems instead of only the first one.
:func:`load_project` raises the single error directly when there is exactly one
and a :class:`~qa_trace.errors.QaTraceGroupError` otherwise; :func:`collect_errors`
returns the diagnostics without raising, which is what the CLI uses.

P0 stops at the document level.  Reference existence, the graph traversal and
the checklist rules live in :mod:`qa_trace.rules`, the metrics in
:mod:`qa_trace.metrics` and the script-marker cross-check in P2.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import (
    DuplicateIdError,
    FieldInvalidError,
    FieldMissingError,
    FileIdMismatchError,
    ProjectError,
    QaTraceError,
    QaTraceGroupError,
    SchemaError,
    YamlDuplicateKeyError,
    YamlError,
)
from .models import Case, Source, TestPoint, validate_schema_version

PROJECT_FILE = "project.yaml"

COLLECTIONS: tuple[str, ...] = ("sources", "testpoints", "cases")

#: Directory (inside a project) holding draft batches; never part of the library.
DRAFT_DIRNAME = "draft"

YAML_SUFFIXES: tuple[str, ...] = (".yaml", ".yml")

_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_PROJECT_KEYS = {"schema_version", "project_id", "name", "modules", "thresholds", "strict"}

#: Default maximum share of reviewed cases that may carry priority P0.
DEFAULT_P0_RATIO_MAX = 0.2


class _DuplicateKeyError(Exception):
    """Raised by the strict YAML loader when a mapping repeats a key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of dropping data."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise _DuplicateKeyError(str(key))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _load_yaml_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise YamlError(f"cannot read file: {exc}", path=path) from exc
    try:
        return yaml.load(text, Loader=_StrictLoader)
    except _DuplicateKeyError as exc:
        raise YamlDuplicateKeyError(
            f"duplicate mapping key {exc.key!r}", path=path, field=exc.key
        ) from None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1} column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise YamlError(f"invalid YAML{location}: {problem}", path=path) from None


def load_yaml_document(path: str | Path) -> Any:
    """Read one YAML document with the loader's strict (duplicate-key) rules."""
    return _load_yaml_file(Path(path))


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Contents of ``project.yaml``."""

    schema_version: int
    project_id: str
    name: str | None = None
    modules: tuple[str, ...] = ()
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    strict: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def p0_ratio_max(self) -> float:
        """Maximum share of reviewed cases that may carry priority P0."""
        return float(self.thresholds.get("p0_ratio_max", DEFAULT_P0_RATIO_MAX))

    @property
    def manual_p0_max_days(self) -> int | None:
        """Configured manual-P0 aging limit; P1 cannot compute the age yet."""
        value = self.thresholds.get("manual_p0_max_days")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class Project:
    """A fully validated project library."""

    root: Path
    config: ProjectConfig
    sources: Mapping[str, Source] = field(default_factory=dict)
    testpoints: Mapping[str, TestPoint] = field(default_factory=dict)
    cases: Mapping[str, Case] = field(default_factory=dict)
    files: Mapping[str, Path] = field(default_factory=dict)

    def entity_count(self) -> int:
        """Return the number of loaded entities across all collections."""
        return len(self.sources) + len(self.testpoints) + len(self.cases)


def _read_str_tuple(value: Any, *, path: Path, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise FieldInvalidError(f"{field_name} must be a list", path=path, field=field_name)
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise FieldInvalidError(
                f"{field_name} entries must be non-empty strings",
                path=path,
                field=f"{field_name}[{index}]",
            )
        items.append(item.strip())
    return tuple(items)


def _validate_thresholds(thresholds: Mapping[str, Any], *, path: Path) -> dict[str, Any]:
    """Validate the threshold block and return it with defaults filled in."""
    resolved = dict(thresholds)
    raw_ratio = resolved.get("p0_ratio_max", DEFAULT_P0_RATIO_MAX)
    if isinstance(raw_ratio, bool) or not isinstance(raw_ratio, (int, float)):
        raise ProjectError(
            "thresholds.p0_ratio_max must be a number between 0 and 1",
            path=path,
            field="thresholds.p0_ratio_max",
        )
    ratio = float(raw_ratio)
    if not 0.0 <= ratio <= 1.0:
        raise ProjectError(
            "thresholds.p0_ratio_max must be between 0 and 1",
            path=path,
            field="thresholds.p0_ratio_max",
        )
    resolved["p0_ratio_max"] = ratio
    raw_days = resolved.get("manual_p0_max_days")
    if raw_days is not None and (
        isinstance(raw_days, bool) or not isinstance(raw_days, int) or raw_days < 1
    ):
        raise ProjectError(
            "thresholds.manual_p0_max_days must be a positive integer",
            path=path,
            field="thresholds.manual_p0_max_days",
        )
    return resolved


def _config_from_mapping(data: Mapping[str, Any], path: Path) -> ProjectConfig:
    """Validate an already-parsed ``project.yaml`` mapping."""
    schema_version = validate_schema_version(data.get("schema_version"), path=path)
    project_id = data.get("project_id")
    if project_id is None:
        raise FieldMissingError("project_id is required", path=path, field="project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise FieldInvalidError("project_id must be a non-empty string", path=path, field="project_id")
    project_id = project_id.strip()
    if not _PROJECT_ID_PATTERN.match(project_id):
        raise FieldInvalidError(
            "project_id may only use letters, digits, dot, dash and underscore",
            path=path,
            field="project_id",
        )
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise FieldInvalidError("name must be a string", path=path, field="name")
    thresholds = data.get("thresholds")
    if thresholds is None:
        thresholds = {}
    if not isinstance(thresholds, Mapping):
        raise FieldInvalidError("thresholds must be a mapping", path=path, field="thresholds")
    strict = data.get("strict", False)
    if strict is None:
        strict = False
    if not isinstance(strict, bool):
        raise FieldInvalidError("strict must be true or false", path=path, field="strict")
    return ProjectConfig(
        schema_version=schema_version,
        project_id=project_id,
        name=name.strip() if isinstance(name, str) and name.strip() else None,
        modules=_read_str_tuple(data.get("modules"), path=path, field_name="modules"),
        thresholds=_validate_thresholds(thresholds, path=path),
        strict=strict,
        extra={key: value for key, value in data.items() if key not in _PROJECT_KEYS},
    )


def _load_config(root: Path) -> ProjectConfig:
    path = root / PROJECT_FILE
    if not path.is_file():
        raise ProjectError(f"{PROJECT_FILE} is required in a project directory", path=path)
    data = _load_yaml_file(path)
    if not isinstance(data, Mapping):
        raise SchemaError("the file root must be a mapping", path=path)
    return _config_from_mapping(data, path)


def _check_file_name(path: Path, entity_id: str) -> None:
    if path.stem != entity_id:
        raise FileIdMismatchError(
            f"file {path.name} declares id {entity_id}; expected {entity_id}.yaml",
            path=path,
            field="id",
        )


def scan_collection(
    directory: Path,
    model: type[Source] | type[TestPoint] | type[Case],
    *,
    errors: list[QaTraceError],
    seen: dict[str, Path],
    files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Load one collection directory, collecting errors instead of raising.

    Public because P3 draft batches validate a candidate library the same way
    the formal library is loaded; ``seen`` lets the caller pre-seed the IDs that
    must not repeat.
    """
    entities: dict[str, Any] = {}
    if not directory.is_dir():
        return entities
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in YAML_SUFFIXES
    )
    for path in candidates:
        try:
            data = _load_yaml_file(path)
            if not isinstance(data, Mapping):
                raise SchemaError("the file root must be a mapping", path=path)
            entity = model.from_dict(data, path=path)
            _check_file_name(path, entity.id)
            if entity.id in seen:
                raise DuplicateIdError(
                    f"id {entity.id} is already defined in {seen[entity.id]}",
                    path=path,
                    field="id",
                )
        except QaTraceError as exc:
            errors.append(exc)
            continue
        seen[entity.id] = path
        if files is not None:
            files[entity.id] = path
        entities[entity.id] = entity
    return entities


@dataclass(frozen=True, slots=True)
class _ScanResult:
    config: ProjectConfig | None
    sources: dict[str, Source]
    testpoints: dict[str, TestPoint]
    cases: dict[str, Case]
    files: dict[str, Path]
    errors: tuple[QaTraceError, ...]


def _scan_project(root: Path) -> _ScanResult:
    errors: list[QaTraceError] = []
    config: ProjectConfig | None = None
    try:
        config = _load_config(root)
    except QaTraceError as exc:
        errors.append(exc)
    seen: dict[str, Path] = {}
    files: dict[str, Path] = {}
    sources = scan_collection(
        root / "sources", Source, errors=errors, seen=seen, files=files
    )
    testpoints = scan_collection(
        root / "testpoints", TestPoint, errors=errors, seen=seen, files=files
    )
    cases = scan_collection(root / "cases", Case, errors=errors, seen=seen, files=files)
    return _ScanResult(
        config=config,
        sources=sources,
        testpoints=testpoints,
        cases=cases,
        files=files,
        errors=tuple(errors),
    )


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """One non-raising scan: the library when it is whole, plus every error."""

    root: Path
    config: ProjectConfig | None = None
    project: Project | None = None
    errors: tuple[QaTraceError, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the library loaded without a single error."""
        return self.project is not None and not self.errors


def scan_project(root: str | Path) -> ScanOutcome:
    """Load a project without raising; ``outcome.project`` is ``None`` on errors."""
    project_root = Path(root)
    if not project_root.is_dir():
        return ScanOutcome(
            root=project_root,
            errors=(
                ProjectError(f"project directory not found: {project_root}", path=project_root),
            ),
        )
    scan = _scan_project(project_root)
    if scan.errors:
        return ScanOutcome(root=project_root, config=scan.config, errors=scan.errors)
    if scan.config is None:  # pragma: no cover - a missing config is an error above
        return ScanOutcome(
            root=project_root,
            errors=(ProjectError("project configuration could not be loaded", path=project_root),),
        )
    return ScanOutcome(
        root=project_root,
        config=scan.config,
        project=Project(
            root=project_root,
            config=scan.config,
            sources=scan.sources,
            testpoints=scan.testpoints,
            cases=scan.cases,
            files=scan.files,
        ),
    )


def load_project_from_documents(
    root: str | Path,
    documents: Iterable[tuple[str, Path, Mapping[str, Any]]],
) -> ScanOutcome:
    """Build a :class:`Project` from YAML mappings that are already parsed.

    ``documents`` carries ``(entity_type, path, document)`` where entity_type is
    ``project``, ``source``, ``testpoint`` or ``case``.  It must contain the
    formal library only (no drafts or tombstones); the caller has already read
    the files, so this function never touches the filesystem.  Validation is the
    same one :func:`load_project` applies: model construction, file-name/ID
    agreement and duplicate-ID detection.
    """
    project_root = Path(root)
    errors: list[QaTraceError] = []
    project_document: Mapping[str, Any] | None = None
    grouped: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
        "source": [],
        "testpoint": [],
        "case": [],
    }
    for entity_type, path, document in documents:
        if entity_type == "project":
            project_document = document
        elif entity_type in grouped:
            grouped[entity_type].append((Path(path), document))
    config: ProjectConfig | None = None
    if project_document is None:
        errors.append(
            ProjectError(
                f"{PROJECT_FILE} is required in a project directory",
                path=project_root / PROJECT_FILE,
            )
        )
    else:
        try:
            config = _config_from_mapping(
                project_document, project_root / PROJECT_FILE
            )
        except QaTraceError as exc:
            errors.append(exc)
    seen: dict[str, Path] = {}
    files: dict[str, Path] = {}
    built: dict[str, dict[str, Any]] = {
        "source": {},
        "testpoint": {},
        "case": {},
    }
    for entity_type, model in (
        ("source", Source),
        ("testpoint", TestPoint),
        ("case", Case),
    ):
        for path, document in grouped[entity_type]:
            try:
                if not isinstance(document, Mapping):
                    raise SchemaError("the file root must be a mapping", path=path)
                entity = model.from_dict(document, path=path)
                _check_file_name(path, entity.id)
                if entity.id in seen:
                    raise DuplicateIdError(
                        f"id {entity.id} is already defined in {seen[entity.id]}",
                        path=path,
                        field="id",
                    )
            except QaTraceError as exc:
                errors.append(exc)
                continue
            seen[entity.id] = path
            files[entity.id] = path
            built[entity_type][entity.id] = entity
    if errors or config is None:
        return ScanOutcome(root=project_root, config=config, errors=tuple(errors))
    return ScanOutcome(
        root=project_root,
        config=config,
        project=Project(
            root=project_root,
            config=config,
            sources=built["source"],
            testpoints=built["testpoint"],
            cases=built["case"],
            files=files,
        ),
    )


def collect_errors(root: str | Path) -> tuple[QaTraceError, ...]:
    """Validate a project directory and return every diagnostic it finds."""
    return scan_project(root).errors


def load_project(root: str | Path) -> Project:
    """Load and validate a project, raising on the first problem set found."""
    project_root = Path(root)
    if not project_root.is_dir():
        raise ProjectError(
            f"project directory not found: {project_root}", path=project_root
        )
    scan = _scan_project(project_root)
    if scan.errors:
        if len(scan.errors) == 1:
            raise scan.errors[0]
        raise QaTraceGroupError(scan.errors)
    if scan.config is None:  # pragma: no cover - a missing config is an error above
        raise ProjectError("project configuration could not be loaded", path=project_root)
    return Project(
        root=project_root,
        config=scan.config,
        sources=scan.sources,
        testpoints=scan.testpoints,
        cases=scan.cases,
        files=scan.files,
    )
