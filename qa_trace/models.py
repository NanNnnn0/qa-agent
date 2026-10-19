"""Validated entity models for the qa-trace library.

P0 freezes the document shape and its required fields.  Models are immutable
dataclasses and ``from_dict`` is the only supported way to build one from YAML:
it validates types, enumerations, required fields and the ID grammar, and raises
:class:`~qa_trace.errors.QaTraceError` subclasses that carry the file path and
the field path (``steps[1].expected``).

Keys P0 does not know are preserved in ``extra`` instead of being rejected, so a
later phase can add fields without invalidating existing documents.  Business
validity (review hashes, stale propagation, coverage) is deliberately *not*
computed here; see ``docs/design/qa-trace.md``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from .errors import (
    DirectReasonMissingError,
    EnumValueError,
    EvidenceMissingError,
    FieldInvalidError,
    FieldMissingError,
    IdTypeMismatchError,
    LinkMissingError,
    SchemaVersionError,
    ScriptBindingError,
    StepExpectedMissingError,
)
from .ids import SOURCE_KINDS, IdKind, ensure_kind, parse_id

#: The only document version this build understands.
SCHEMA_VERSION = 1

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvidenceType(StrEnum):
    """Kind of evidence that backs a source."""

    DOCUMENT = "document"
    OPENAPI = "openapi"
    UI_CAPTURE = "ui_capture"
    ISSUE = "issue"
    STANDARD = "standard"
    EXPLORATION = "exploration"


class EvidenceVerification(StrEnum):
    """How far an evidence reference was checked."""

    LOCAL = "verified_local"
    EXTERNAL = "external_unverified"


class SourceType(StrEnum):
    """The root kinds of the trace chain."""

    REQ = "req"
    API = "api"
    UI = "ui"
    BUG = "bug"
    STD = "std"
    EX = "ex"


class EntityStatus(StrEnum):
    """Lifecycle of a source."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class Confidence(StrEnum):
    """``observed`` records a fact; only ``confirmed`` may back reviewed cases."""

    OBSERVED = "observed"
    CONFIRMED = "confirmed"


class ReviewStatus(StrEnum):
    """Lifecycle of a test point or case."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    DEPRECATED = "deprecated"


class Method(StrEnum):
    """Test-design method of a test point."""

    EQUIVALENCE = "equivalence"
    BOUNDARY = "boundary"
    SCENARIO = "scenario"
    STATE = "state"
    ORTHOGONAL = "orthogonal"
    ERROR_GUESS = "error-guess"


class Risk(StrEnum):
    """Risk level of a test point or of a case that hangs directly off a source."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(StrEnum):
    """Execution priority of a case."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseType(StrEnum):
    """Test category of a case."""

    FUNCTIONAL = "functional"
    API = "api"
    UI = "ui"
    SECURITY = "security"
    COMPAT = "compat"
    PERF = "perf"


class AutomationStatus(StrEnum):
    """Automation state of a case."""

    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    MANUAL = "manual"


class Outcome(StrEnum):
    """Outcome of one executed case instance."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAILED = "xfailed"
    XPASSED = "xpassed"
    CANCELLED = "cancelled"


class FailureStage(StrEnum):
    """pytest phase in which a result failed."""

    SETUP = "setup"
    CALL = "call"
    TEARDOWN = "teardown"


def validate_schema_version(
    value: Any, *, path: str | None = None, field: str = "schema_version"
) -> int:
    """Validate a document's ``schema_version`` and return it."""
    if value is None:
        raise FieldMissingError("schema_version is required", path=path, field=field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldInvalidError("schema_version must be an integer", path=path, field=field)
    if value != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"unsupported schema_version {value}; this build reads {SCHEMA_VERSION}",
            path=path,
            field=field,
        )
    return value


def _as_list(value: Any, key: str, path: str | None, field_name: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FieldInvalidError(f"{key} must be a list", path=path, field=field_name)
    return list(value)


class _Reader:
    """Field access that attaches ``path`` and the field path to every failure."""

    __slots__ = ("_data", "_path", "_prefix")

    def __init__(self, data: Mapping[str, Any], *, path: str | None, prefix: str = "") -> None:
        self._data = data
        self._path = path
        self._prefix = prefix

    @property
    def path(self) -> str | None:
        return self._path

    def field(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def require_str(self, key: str) -> str:
        value = self.get(key)
        field_name = self.field(key)
        if value is None:
            raise FieldMissingError(f"{key} is required", path=self._path, field=field_name)
        if not isinstance(value, str):
            raise FieldInvalidError(
                f"{key} must be a string, got {type(value).__name__}",
                path=self._path,
                field=field_name,
            )
        text = value.strip()
        if not text:
            raise FieldInvalidError(f"{key} must not be blank", path=self._path, field=field_name)
        return text

    def optional_str(self, key: str) -> str | None:
        value = self.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise FieldInvalidError(
                f"{key} must be a string, got {type(value).__name__}",
                path=self._path,
                field=self.field(key),
            )
        return value.strip() or None

    def optional_bool(self, key: str, default: bool) -> bool:
        value = self.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise FieldInvalidError(
                f"{key} must be true or false", path=self._path, field=self.field(key)
            )
        return value

    def optional_int(self, key: str, default: int) -> int:
        value = self.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise FieldInvalidError(
                f"{key} must be an integer", path=self._path, field=self.field(key)
            )
        return value

    def require_list(self, key: str) -> list[Any]:
        value = self.get(key)
        if value is None:
            raise FieldMissingError(f"{key} is required", path=self._path, field=self.field(key))
        return _as_list(value, key, self._path, self.field(key))

    def optional_list(self, key: str) -> list[Any]:
        value = self.get(key)
        if value is None:
            return []
        return _as_list(value, key, self._path, self.field(key))

    def require_mapping(self, key: str) -> Mapping[str, Any]:
        value = self.get(key)
        if value is None:
            raise FieldMissingError(f"{key} is required", path=self._path, field=self.field(key))
        if not isinstance(value, Mapping):
            raise FieldInvalidError(
                f"{key} must be a mapping", path=self._path, field=self.field(key)
            )
        return value

    def optional_mapping(self, key: str) -> Mapping[str, Any] | None:
        value = self.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise FieldInvalidError(
                f"{key} must be a mapping", path=self._path, field=self.field(key)
            )
        return value

    def enum(
        self,
        key: str,
        enum_type: type[StrEnum],
        *,
        default: StrEnum | None = None,
        required: bool = True,
    ) -> Any:
        value = self.get(key)
        field_name = self.field(key)
        if value is None:
            if not required:
                return default
            raise FieldMissingError(f"{key} is required", path=self._path, field=field_name)
        if not isinstance(value, str):
            raise FieldInvalidError(
                f"{key} must be a string, got {type(value).__name__}",
                path=self._path,
                field=field_name,
            )
        lookup = {member.value.casefold(): member for member in enum_type}
        member = lookup.get(value.strip().casefold())
        if member is None:
            allowed = ", ".join(sorted(member.value for member in enum_type))
            raise EnumValueError(
                f"{key}={value!r} is not one of: {allowed}", path=self._path, field=field_name
            )
        return member

    def date(self, key: str, *, required: bool = False) -> date | None:
        value = self.get(key)
        field_name = self.field(key)
        if value is None:
            if required:
                raise FieldMissingError(f"{key} is required", path=self._path, field=field_name)
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                raise FieldInvalidError(
                    f"{key} must be an ISO date (YYYY-MM-DD)", path=self._path, field=field_name
                ) from None
        raise FieldInvalidError(
            f"{key} must be an ISO date (YYYY-MM-DD)", path=self._path, field=field_name
        )

    def datetime(self, key: str, *, required: bool = False) -> datetime | None:
        value = self.get(key)
        field_name = self.field(key)
        if value is None:
            if required:
                raise FieldMissingError(f"{key} is required", path=self._path, field=field_name)
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                raise FieldInvalidError(
                    f"{key} must be an ISO 8601 datetime", path=self._path, field=field_name
                ) from None
        raise FieldInvalidError(
            f"{key} must be an ISO 8601 datetime", path=self._path, field=field_name
        )

    def require_datetime(self, key: str) -> datetime:
        value = self.datetime(key, required=True)
        if value is None:  # pragma: no cover - required=True raises above
            raise FieldMissingError(f"{key} is required", path=self._path, field=self.field(key))
        return value

    def extra(self, known: set[str]) -> dict[str, Any]:
        return {key: value for key, value in self._data.items() if key not in known}


_EVIDENCE_KEYS = {"type", "locator", "description", "sha256", "verified"}


@dataclass(frozen=True, slots=True)
class Evidence:
    """One verifiable pointer that backs a source."""

    type: EvidenceType
    locator: str
    description: str | None = None
    sha256: str | None = None
    verified: EvidenceVerification | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, path: str | None = None, prefix: str = "evidence"
    ) -> Evidence:
        if not isinstance(data, Mapping):
            raise FieldInvalidError(
                "evidence entry must be a mapping", path=path, field=prefix
            )
        reader = _Reader(data, path=path, prefix=f"{prefix}.")
        sha256 = reader.optional_str("sha256")
        if sha256 is not None:
            sha256 = sha256.lower()
            if not _SHA256_PATTERN.match(sha256):
                raise FieldInvalidError(
                    "sha256 must be 64 lowercase hexadecimal characters",
                    path=path,
                    field=reader.field("sha256"),
                )
        return cls(
            type=reader.enum("type", EvidenceType),
            locator=reader.require_str("locator"),
            description=reader.optional_str("description"),
            sha256=sha256,
            verified=reader.enum("verified", EvidenceVerification, required=False),
            extra=reader.extra(_EVIDENCE_KEYS),
        )


def _read_evidence(reader: _Reader) -> tuple[Evidence, ...]:
    raw = reader.get("evidence")
    field_name = reader.field("evidence")
    if raw is None:
        raise EvidenceMissingError(
            "evidence is required: a source without evidence is not a root",
            path=reader.path,
            field=field_name,
        )
    items = _as_list(raw, "evidence", reader.path, field_name)
    if not items:
        raise EvidenceMissingError(
            "evidence must contain at least one entry", path=reader.path, field=field_name
        )
    return tuple(
        Evidence.from_dict(item, path=reader.path, prefix=f"evidence[{index}]")
        for index, item in enumerate(items)
    )


_SOURCE_KEYS = {
    "schema_version",
    "id",
    "type",
    "title",
    "evidence",
    "status",
    "confidence",
    "module",
    "url",
    "app_version",
    "observed_at",
    "stale",
    "owner",
    "note",
}


@dataclass(frozen=True, slots=True)
class Source:
    """A root of the trace chain: requirement, contract, observation or defect."""

    id: str
    type: SourceType
    title: str
    evidence: tuple[Evidence, ...]
    status: EntityStatus = EntityStatus.ACTIVE
    confidence: Confidence = Confidence.OBSERVED
    module: str | None = None
    url: str | None = None
    app_version: str | None = None
    observed_at: date | None = None
    stale: bool = False
    owner: str | None = None
    note: str | None = None
    schema_version: int = SCHEMA_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> Source:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("source document must be a mapping", path=path, field="id")
        reader = _Reader(data, path=path)
        schema_version = validate_schema_version(
            reader.get("schema_version"), path=path, field=reader.field("schema_version")
        )
        source_type = reader.enum("type", SourceType)
        parsed = ensure_kind(reader.require_str("id"), source_type.value, path=path, field="id")
        title = reader.require_str("title")
        evidence = _read_evidence(reader)
        status = reader.enum("status", EntityStatus, default=EntityStatus.ACTIVE, required=False)
        confidence = reader.enum(
            "confidence", Confidence, default=Confidence.OBSERVED, required=False
        )
        url = reader.optional_str("url")
        app_version = reader.optional_str("app_version")
        observed_at = reader.date("observed_at")
        if source_type is SourceType.UI:
            # The specification requires path, version, date and a capture for UI
            # observations; without them the root degrades into "I remember".
            if url is None:
                raise FieldMissingError(
                    "ui sources need the observed url", path=path, field="url"
                )
            if app_version is None:
                raise FieldMissingError(
                    "ui sources need app_version", path=path, field="app_version"
                )
            if observed_at is None:
                raise FieldMissingError(
                    "ui sources need observed_at", path=path, field="observed_at"
                )
        return cls(
            id=parsed.value,
            type=source_type,
            title=title,
            evidence=evidence,
            status=status,
            confidence=confidence,
            module=reader.optional_str("module"),
            url=url,
            app_version=app_version,
            observed_at=observed_at,
            stale=reader.optional_bool("stale", False),
            owner=reader.optional_str("owner"),
            note=reader.optional_str("note"),
            schema_version=schema_version,
            extra=reader.extra(_SOURCE_KEYS),
        )


def _read_ref_list(
    reader: _Reader,
    key: str,
    *,
    kinds: frozenset[IdKind] | tuple[IdKind, ...],
    required: bool = True,
) -> tuple[str, ...]:
    raw = reader.get(key)
    field_name = reader.field(key)
    if raw is None:
        if required:
            raise FieldMissingError(f"{key} is required", path=reader.path, field=field_name)
        return ()
    refs: list[str] = []
    for index, item in enumerate(_as_list(raw, key, reader.path, field_name)):
        item_field = f"{field_name}[{index}]"
        if not isinstance(item, str):
            raise FieldInvalidError(
                f"{key} entries must be ID strings", path=reader.path, field=item_field
            )
        parsed = parse_id(item.strip(), path=reader.path, field=item_field)
        if parsed.kind not in kinds:
            allowed = ", ".join(sorted(kind.value for kind in kinds))
            raise IdTypeMismatchError(
                f"{parsed.value} is not a valid {key} target (expected: {allowed})",
                path=reader.path,
                field=item_field,
            )
        refs.append(parsed.value)
    return tuple(refs)


_TESTPOINT_KEYS = {
    "schema_version",
    "id",
    "title",
    "sources",
    "method",
    "risk",
    "status",
    "module",
    "owner",
    "tags",
    "note",
}


@dataclass(frozen=True, slots=True)
class TestPoint:
    """A test idea derived from at least one source."""

    id: str
    title: str
    sources: tuple[str, ...]
    method: Method
    risk: Risk
    status: ReviewStatus
    module: str | None = None
    owner: str | None = None
    tags: tuple[str, ...] = ()
    note: str | None = None
    schema_version: int = SCHEMA_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> TestPoint:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("test point document must be a mapping", path=path, field="id")
        reader = _Reader(data, path=path)
        schema_version = validate_schema_version(
            reader.get("schema_version"), path=path, field=reader.field("schema_version")
        )
        parsed = ensure_kind(reader.require_str("id"), IdKind.TESTPOINT, path=path, field="id")
        title = reader.require_str("title")
        sources = _read_ref_list(reader, "sources", kinds=SOURCE_KINDS)
        if not sources:
            raise FieldMissingError(
                "a test point needs at least one source", path=path, field="sources"
            )
        return cls(
            id=parsed.value,
            title=title,
            sources=sources,
            method=reader.enum("method", Method),
            risk=reader.enum("risk", Risk),
            status=reader.enum("status", ReviewStatus),
            module=reader.optional_str("module"),
            owner=reader.optional_str("owner"),
            tags=_read_tags(reader),
            note=reader.optional_str("note"),
            schema_version=schema_version,
            extra=reader.extra(_TESTPOINT_KEYS),
        )


def _read_tags(reader: _Reader) -> tuple[str, ...]:
    tags: list[str] = []
    for index, item in enumerate(reader.optional_list("tags")):
        if not isinstance(item, str) or not item.strip():
            raise FieldInvalidError(
                "tags must be non-empty strings",
                path=reader.path,
                field=f"{reader.field('tags')}[{index}]",
            )
        tags.append(item.strip())
    return tuple(tags)


@dataclass(frozen=True, slots=True)
class Step:
    """One action plus the observable result it must produce."""

    action: str
    expected: str

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, path: str | None = None, prefix: str = "steps"
    ) -> Step:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("a step must be a mapping", path=path, field=prefix)
        reader = _Reader(data, path=path, prefix=f"{prefix}.")
        action = reader.require_str("action")
        expected_field = f"{prefix}.expected"
        raw_expected = data.get("expected")
        if raw_expected is None:
            raise StepExpectedMissingError(
                "every step needs an expected result", path=path, field=expected_field
            )
        if not isinstance(raw_expected, str):
            raise FieldInvalidError(
                "expected must be a string", path=path, field=expected_field
            )
        expected = raw_expected.strip()
        if not expected:
            raise StepExpectedMissingError(
                "expected must not be blank", path=path, field=expected_field
            )
        return cls(action=action, expected=expected)


def _read_steps(reader: _Reader) -> tuple[Step, ...]:
    field_name = reader.field("steps")
    raw = reader.get("steps")
    if raw is None:
        raise FieldMissingError("steps is required", path=reader.path, field=field_name)
    items = _as_list(raw, "steps", reader.path, field_name)
    if not items:
        raise FieldMissingError(
            "steps must contain at least one step", path=reader.path, field=field_name
        )
    return tuple(
        Step.from_dict(item, path=reader.path, prefix=f"steps[{index}]")
        for index, item in enumerate(items)
    )


@dataclass(frozen=True, slots=True)
class ScriptBinding:
    """The pytest node a case is bound to (``<file>::<nodeid>``)."""

    file: str
    nodeid: str

    @property
    def script(self) -> str:
        """The binding in ``<file>::<nodeid>`` form."""
        return f"{self.file}::{self.nodeid}"

    @classmethod
    def parse(
        cls,
        raw: Any,
        *,
        path: str | None = None,
        field: str = "automation.script",
    ) -> ScriptBinding:
        if not isinstance(raw, str):
            raise ScriptBindingError(
                "script must be a '<file>::<nodeid>' string", path=path, field=field
            )
        text = raw.strip()
        parts = text.split("::")
        if len(parts) < 2 or any(not part.strip() for part in parts):
            raise ScriptBindingError(
                "script must be '<file>::<nodeid>' with both halves filled",
                path=path,
                field=field,
            )
        # Class-based and parametrised nodeids keep extra ``::`` segments.
        return cls(
            file=parts[0].strip(),
            nodeid="::".join(part.strip() for part in parts[1:]),
        )


_AUTOMATION_KEYS = {"status", "script"}


@dataclass(frozen=True, slots=True)
class Automation:
    """How (or whether) a case is automated."""

    status: AutomationStatus
    script: ScriptBinding | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> Automation:
        if not isinstance(data, Mapping):
            raise FieldInvalidError(
                "automation must be a mapping", path=path, field="automation"
            )
        reader = _Reader(data, path=path, prefix="automation.")
        status = reader.enum("status", AutomationStatus)
        raw_script = reader.optional_str("script")
        script = (
            ScriptBinding.parse(raw_script, path=path, field="automation.script")
            if raw_script is not None
            else None
        )
        if status is AutomationStatus.DONE and script is None:
            raise FieldMissingError(
                "automation.status=done needs a pytest script binding",
                path=path,
                field="automation.script",
            )
        return cls(status=status, script=script, extra=reader.extra(_AUTOMATION_KEYS))


_CASE_KEYS = {
    "schema_version",
    "id",
    "code",
    "title",
    "testpoints",
    "sources",
    "direct_reason",
    "priority",
    "type",
    "steps",
    "status",
    "automation",
    "risk",
    "preconditions",
    "postconditions",
    "expected",
    "api",
    "data",
    "owner",
    "tags",
    "note",
    "legacy_id",
}


def _read_api_spec(reader: _Reader) -> Mapping[str, Any] | None:
    """Validate the optional structured API block stored on a case.

    The block is the executable contract the httpx runner consumes
    (``request``/``assertions``/``variables``).  The full normalisation lives in
    the product layer (``nanobot.qa.validation.validate_api_spec``); the library
    only refuses shapes that could never execute, so a hand-written YAML case
    fails at load time instead of at run time.
    """
    raw = reader.optional_mapping("api")
    if raw is None:
        return None
    if not raw:
        return None
    request = raw.get("request")
    if request is not None:
        if not isinstance(request, Mapping):
            raise FieldInvalidError(
                "api.request must be a mapping", path=reader.path, field="api.request"
            )
        path = request.get("path")
        if not isinstance(path, str) or not path.strip():
            raise FieldInvalidError(
                "api.request.path must be a non-empty string",
                path=reader.path,
                field="api.request.path",
            )
        method = request.get("method", "GET")
        if not isinstance(method, str) or not method.strip():
            raise FieldInvalidError(
                "api.request.method must be a string", path=reader.path, field="api.request.method"
            )
    assertions = raw.get("assertions")
    if assertions is not None and not isinstance(assertions, Sequence):
        raise FieldInvalidError(
            "api.assertions must be a list", path=reader.path, field="api.assertions"
        )
    variables = raw.get("variables")
    if variables is not None and not isinstance(variables, Mapping):
        raise FieldInvalidError(
            "api.variables must be a mapping", path=reader.path, field="api.variables"
        )
    return dict(raw)


@dataclass(frozen=True, slots=True)
class Case:
    """An executable test case traced to test points or, exceptionally, sources.

    ``code``, ``expected``, ``api`` and ``legacy_id`` exist for the workbench and
    the agent-tool compatibility layer: ``code`` is the human-facing case number
    (``SHOP-API-001``), ``expected`` the case-level expected result next to the
    per-step expectations, ``api`` the structured request/assertion contract the
    httpx runner executes, and ``legacy_id`` the SQLite row a case was migrated
    from.  YAML stays the single source of truth: none of them are derived.
    """

    id: str
    title: str
    priority: Priority
    type: CaseType
    steps: tuple[Step, ...]
    status: ReviewStatus
    automation: Automation
    testpoints: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    direct_reason: str | None = None
    risk: Risk | None = None
    code: str | None = None
    preconditions: str | None = None
    postconditions: str | None = None
    expected: str | None = None
    api: Mapping[str, Any] | None = None
    legacy_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    owner: str | None = None
    tags: tuple[str, ...] = ()
    note: str | None = None
    schema_version: int = SCHEMA_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> Case:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("case document must be a mapping", path=path, field="id")
        reader = _Reader(data, path=path)
        schema_version = validate_schema_version(
            reader.get("schema_version"), path=path, field=reader.field("schema_version")
        )
        parsed = ensure_kind(reader.require_str("id"), IdKind.CASE, path=path, field="id")
        title = reader.require_str("title")
        priority = reader.enum("priority", Priority)
        case_type = reader.enum("type", CaseType)
        steps = _read_steps(reader)
        status = reader.enum("status", ReviewStatus)
        automation = Automation.from_dict(reader.require_mapping("automation"), path=path)
        testpoints = _read_ref_list(
            reader, "testpoints", kinds=(IdKind.TESTPOINT,), required=False
        )
        sources = _read_ref_list(reader, "sources", kinds=SOURCE_KINDS, required=False)
        direct_reason = reader.optional_str("direct_reason")
        if not testpoints and not sources:
            raise LinkMissingError(
                "a case needs testpoints or direct sources", path=path, field="testpoints"
            )
        if sources and direct_reason is None:
            raise DirectReasonMissingError(
                "a case that references sources directly must explain why",
                path=path,
                field="direct_reason",
            )
        risk = reader.enum("risk", Risk, required=False)
        if not testpoints and risk is None:
            raise FieldMissingError(
                "a case without a test point must declare risk", path=path, field="risk"
            )
        data_value = reader.optional_mapping("data") or {}
        return cls(
            id=parsed.value,
            title=title,
            priority=priority,
            type=case_type,
            steps=steps,
            status=status,
            automation=automation,
            testpoints=testpoints,
            sources=sources,
            direct_reason=direct_reason,
            risk=risk,
            code=reader.optional_str("code"),
            preconditions=reader.optional_str("preconditions"),
            postconditions=reader.optional_str("postconditions"),
            expected=reader.optional_str("expected"),
            api=_read_api_spec(reader),
            legacy_id=reader.optional_str("legacy_id"),
            data=data_value,
            owner=reader.optional_str("owner"),
            tags=_read_tags(reader),
            note=reader.optional_str("note"),
            schema_version=schema_version,
            extra=reader.extra(_CASE_KEYS),
        )


_RESULT_KEYS = {
    "case_id",
    "nodeid",
    "outcome",
    "attempt",
    "started_at",
    "finished_at",
    "failure_stage",
    "error_summary",
    "evidence",
}


@dataclass(frozen=True, slots=True)
class CaseResult:
    """The outcome of one executed case instance (one pytest nodeid run)."""

    case_id: str
    nodeid: str
    outcome: Outcome
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_stage: FailureStage | None = None
    error_summary: str | None = None
    evidence: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> CaseResult:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("case result must be a mapping", path=path, field="case_id")
        reader = _Reader(data, path=path)
        parsed = ensure_kind(reader.require_str("case_id"), IdKind.CASE, path=path, field="case_id")
        nodeid = reader.require_str("nodeid")
        outcome = reader.enum("outcome", Outcome)
        attempt = reader.optional_int("attempt", 1)
        if attempt < 1:
            raise FieldInvalidError("attempt must be >= 1", path=path, field="attempt")
        started_at = reader.datetime("started_at")
        finished_at = reader.datetime("finished_at")
        if started_at is not None and finished_at is not None:
            same_awareness = (started_at.tzinfo is None) == (finished_at.tzinfo is None)
            if same_awareness and finished_at < started_at:
                raise FieldInvalidError(
                    "finished_at must not precede started_at", path=path, field="finished_at"
                )
        failure_stage = reader.enum("failure_stage", FailureStage, required=False)
        if outcome in (Outcome.FAILED, Outcome.ERROR) and failure_stage is None:
            raise FieldMissingError(
                "a failed result needs failure_stage", path=path, field="failure_stage"
            )
        evidence: list[str] = []
        for index, item in enumerate(reader.optional_list("evidence")):
            if not isinstance(item, str) or not item.strip():
                raise FieldInvalidError(
                    "evidence entries must be non-empty strings",
                    path=path,
                    field=f"evidence[{index}]",
                )
            evidence.append(item.strip())
        return cls(
            case_id=parsed.value,
            nodeid=nodeid,
            outcome=outcome,
            attempt=attempt,
            started_at=started_at,
            finished_at=finished_at,
            failure_stage=failure_stage,
            error_summary=reader.optional_str("error_summary"),
            evidence=tuple(evidence),
            extra=reader.extra(_RESULT_KEYS),
        )


_RUN_KEYS = {
    "run_id",
    "project_id",
    "started_at",
    "finished_at",
    "environment",
    "app_version",
    "tool_version",
    "code_commit",
    "asset_snapshot",
    "results",
}


@dataclass(frozen=True, slots=True)
class Run:
    """One immutable execution record.

    P0 only fixes the shape; writing and publishing runs is a P2 concern, so
    ``tool_version`` and ``code_commit`` stay optional here.
    """

    run_id: str
    project_id: str
    started_at: datetime
    results: tuple[CaseResult, ...] = ()
    finished_at: datetime | None = None
    environment: str | None = None
    app_version: str | None = None
    tool_version: str | None = None
    code_commit: str | None = None
    asset_snapshot: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> Run:
        if not isinstance(data, Mapping):
            raise FieldInvalidError("run manifest must be a mapping", path=path, field="run_id")
        reader = _Reader(data, path=path)
        run_id = reader.require_str("run_id")
        project_id = reader.require_str("project_id")
        started_at = reader.require_datetime("started_at")
        finished_at = reader.datetime("finished_at")
        if finished_at is not None:
            same_awareness = (started_at.tzinfo is None) == (finished_at.tzinfo is None)
            if same_awareness and finished_at < started_at:
                raise FieldInvalidError(
                    "finished_at must not precede started_at", path=path, field="finished_at"
                )
        results = tuple(
            CaseResult.from_dict(item, path=path) for item in reader.optional_list("results")
        )
        return cls(
            run_id=run_id,
            project_id=project_id,
            started_at=started_at,
            results=results,
            finished_at=finished_at,
            environment=reader.optional_str("environment"),
            app_version=reader.optional_str("app_version"),
            tool_version=reader.optional_str("tool_version"),
            code_commit=reader.optional_str("code_commit"),
            asset_snapshot=reader.optional_mapping("asset_snapshot") or {},
            extra=reader.extra(_RUN_KEYS),
        )
