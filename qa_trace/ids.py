"""ID grammar, prefix/type mapping and ID generation for qa-trace assets.

The canonical shape is ``<PREFIX>-<MODULE>-<SEQ>``.  The module segment is
optional so the legacy two-part IDs already used in the specification
(``REQ-12``) stay valid.  The sequence is either a short decimal number
(``003``) or a full lowercase UUID4, which is what :func:`new_id` emits for new
entities so that parallel branches cannot fight over a counter.

``parse_id`` is strict (canonical uppercase form only); ``normalize_id`` accepts
sloppy input and returns the canonical form.  Both raise
:class:`~qa_trace.errors.IdError` with code ``TRACE_ID_INVALID``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

from .errors import IdError, IdTypeMismatchError

ID_PREFIXES: tuple[str, ...] = ("REQ", "API", "UI", "BUG", "STD", "EX", "TP", "TC")

MODULE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")

_UUID4_BODY = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_SEQ_BODY = rf"(?:[0-9]{{1,6}}|{_UUID4_BODY})"

ID_PATTERN = re.compile(
    rf"^(?P<prefix>{'|'.join(ID_PREFIXES)})-"
    rf"(?:(?P<module>[A-Z][A-Z0-9_]{{0,31}})-)?"
    rf"(?P<seq>{_SEQ_BODY})$"
)

_UUID4_PATTERN = re.compile(rf"^{_UUID4_BODY}$")
_ID_PATTERN_LOOSE = re.compile(ID_PATTERN.pattern, re.IGNORECASE)


class IdKind(StrEnum):
    """The entity kinds that own IDs."""

    REQ = "req"
    API = "api"
    UI = "ui"
    BUG = "bug"
    STD = "std"
    EX = "ex"
    TESTPOINT = "testpoint"
    CASE = "case"


PREFIX_BY_KIND: dict[IdKind, str] = {
    IdKind.REQ: "REQ",
    IdKind.API: "API",
    IdKind.UI: "UI",
    IdKind.BUG: "BUG",
    IdKind.STD: "STD",
    IdKind.EX: "EX",
    IdKind.TESTPOINT: "TP",
    IdKind.CASE: "TC",
}

KIND_BY_PREFIX: dict[str, IdKind] = {
    prefix: kind for kind, prefix in PREFIX_BY_KIND.items()
}

#: Kinds that may appear in a ``sources`` reference.
SOURCE_KINDS: frozenset[IdKind] = frozenset(
    {IdKind.REQ, IdKind.API, IdKind.UI, IdKind.BUG, IdKind.STD, IdKind.EX}
)


@dataclass(frozen=True, slots=True)
class ParsedId:
    """The segments of one validated ID."""

    prefix: str
    kind: IdKind
    module: str | None
    seq: str

    @property
    def is_uuid(self) -> bool:
        """Whether the sequence segment is a UUID4 rather than a counter."""
        return bool(_UUID4_PATTERN.match(self.seq))

    @property
    def value(self) -> str:
        """The canonical text form of this ID."""
        if self.module is None:
            return f"{self.prefix}-{self.seq}"
        return f"{self.prefix}-{self.module}-{self.seq}"

    def __str__(self) -> str:
        return self.value


def _canonical(match: re.Match[str]) -> str:
    prefix = match.group("prefix").upper()
    module = match.group("module")
    seq = match.group("seq").lower()
    if module is None:
        return f"{prefix}-{seq}"
    return f"{prefix}-{module.upper()}-{seq}"


def _invalid(value: object, *, path: str | None, field: str) -> IdError:
    return IdError(f"{value!r} is not a valid qa-trace ID", path=path, field=field)


def parse_id(value: object, *, path: str | None = None, field: str = "id") -> ParsedId:
    """Parse one ID in canonical form, or raise :class:`IdError`."""
    if not isinstance(value, str):
        raise _invalid(value, path=path, field=field)
    match = ID_PATTERN.match(value)
    if match is None:
        raise _invalid(value, path=path, field=field)
    prefix = match.group("prefix")
    return ParsedId(
        prefix=prefix,
        kind=KIND_BY_PREFIX[prefix],
        module=match.group("module"),
        seq=match.group("seq"),
    )


def normalize_id(value: object, *, path: str | None = None, field: str = "id") -> str:
    """Return the canonical form of an ID written in any letter case."""
    if not isinstance(value, str):
        raise _invalid(value, path=path, field=field)
    match = _ID_PATTERN_LOOSE.match(value.strip())
    if match is None:
        raise _invalid(value, path=path, field=field)
    return _canonical(match)


def is_valid_id(value: object) -> bool:
    """Return whether ``value`` is a well-formed ID."""
    try:
        parse_id(value)
    except IdError:
        return False
    return True


def _coerce_kind(kind: IdKind | str, *, path: str | None = None) -> IdKind:
    if isinstance(kind, IdKind):
        return kind
    text = str(kind).strip()
    if text.upper() in KIND_BY_PREFIX:
        return KIND_BY_PREFIX[text.upper()]
    try:
        return IdKind(text.lower())
    except ValueError:
        raise IdError(
            f"unknown entity kind {kind!r}; expected one of "
            f"{', '.join(sorted(kind.value for kind in IdKind))}",
            path=path,
            field="kind",
        ) from None


def prefix_for_kind(kind: IdKind | str) -> str:
    """Return the ID prefix that owns ``kind``."""
    return PREFIX_BY_KIND[_coerce_kind(kind)]


def kind_for_prefix(prefix: str) -> IdKind:
    """Return the entity kind for ``prefix``, or raise :class:`IdError`."""
    kind = KIND_BY_PREFIX.get(prefix.strip().upper())
    if kind is None:
        raise IdError(
            f"unknown ID prefix {prefix!r}; expected one of {', '.join(ID_PREFIXES)}",
            field="id",
        )
    return kind


def _format_seq(seq: int | str | uuid.UUID, *, path: str | None) -> str:
    if isinstance(seq, uuid.UUID):
        if seq.version != 4:
            raise IdError("only UUID4 sequences are supported", path=path, field="seq")
        return str(seq)
    if isinstance(seq, bool):
        raise IdError("sequence must be a positive integer or a UUID4", path=path, field="seq")
    if isinstance(seq, int):
        if seq < 1 or seq > 999_999:
            raise IdError("sequence must be between 1 and 999999", path=path, field="seq")
        return f"{seq:03d}"
    text = str(seq).strip()
    if text.isdigit():
        return _format_seq(int(text), path=path)
    lowered = text.lower()
    if _UUID4_PATTERN.match(lowered):
        return lowered
    raise IdError(
        "sequence must be a positive integer or a UUID4", path=path, field="seq"
    )


def new_id(
    kind: IdKind | str,
    module: str | None,
    seq: int | str | uuid.UUID,
    *,
    path: str | None = None,
) -> str:
    """Build a new ID for ``kind`` in ``module``.

    ``seq`` is zero-padded to three digits when it is a counter, so ``3`` becomes
    ``TC-LOGIN-003``.  New entities should pass ``uuid.uuid4()`` instead of a
    counter: the plan forbids deriving IDs from "max + 1" because branches race.
    """
    resolved = _coerce_kind(kind, path=path)
    prefix = PREFIX_BY_KIND[resolved]
    if module is None:
        raise IdError("module is required to build an ID", path=path, field="module")
    module_text = str(module).strip().upper()
    if not MODULE_PATTERN.match(module_text):
        raise IdError(
            f"{module!r} is not a valid module segment (uppercase letters, "
            "digits and underscores, starting with a letter)",
            path=path,
            field="module",
        )
    return f"{prefix}-{module_text}-{_format_seq(seq, path=path)}"


def ensure_kind(
    value: object,
    kind: IdKind | str,
    *,
    path: str | None = None,
    field: str = "id",
) -> ParsedId:
    """Parse ``value`` and require it to belong to ``kind``."""
    parsed = parse_id(value, path=path, field=field)
    expected = _coerce_kind(kind, path=path)
    if parsed.kind is not expected:
        raise IdTypeMismatchError(
            f"{parsed.value} is a {parsed.kind.value} ID, expected a {expected.value} ID",
            path=path,
            field=field,
        )
    return parsed
