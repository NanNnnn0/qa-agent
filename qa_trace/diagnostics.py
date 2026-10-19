"""Severity-tagged diagnostics shared by the checker, the rules and the report.

P0 reported problems as :class:`~qa_trace.errors.QaTraceError` raised by the
loader.  P1 has to report three severities (error / warn / info) in one stable
machine shape, so the checker converts loader errors and graph-rule findings
into the same :class:`Diagnostic`.

Rule codes stay in the ``TRACE_*`` namespace owned by :mod:`qa_trace.errors`;
the P1 graph rules add their own codes there.  Paths are reported relative to the
project root in POSIX form so that Windows and Linux output is identical.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import QaTraceError


class Severity(StrEnum):
    """How badly a diagnostic blocks the library."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"


#: Sort key for diagnostics: errors first, then warnings, then information.
SEVERITY_RANK: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARN: 1,
    Severity.INFO: 2,
}

#: Codes that mean "the tool could not read its input", not "the library is
#: wrong".  They map to exit code 2 (plan section 4) instead of 1.
INPUT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "TRACE_PROJECT_INVALID",
        "TRACE_SCHEMA_INVALID",
        "TRACE_SCHEMA_VERSION",
        "TRACE_YAML_INVALID",
        "TRACE_YAML_DUPLICATE_KEY",
        # P3: the derived index and the run history are tool inputs, not assets.
        "TRACE_INDEX_INVALID",
        "TRACE_DRAFT_INVALID",
        "TRACE_RUN_NOT_FOUND",
        "TRACE_RUN_INVALID",
        # P5: git, the base ref and the archived tree are tool inputs.
        "TRACE_DIFF_NOT_GIT",
        "TRACE_DIFF_BASE_UNKNOWN",
        "TRACE_DIFF_BASE_MISSING",
        "TRACE_DIFF_GIT_FAILED",
        "TRACE_DIFF_INVALID",
    }
)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One rule finding, ready for text and JSON output."""

    code: str
    severity: Severity
    message: str
    path: str | None = None
    field: str | None = None
    entity_id: str | None = None
    suggestion: str | None = None

    def format(self) -> str:
        """Return the single-line form printed by the CLI."""
        location = self.path or ""
        if self.field:
            location = f"{location}:{self.field}" if location else self.field
        head = f"{self.severity.value.upper():<5} {self.code}"
        if location:
            return f"{head} {location}: {self.message}"
        return f"{head} {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this diagnostic."""
        return {
            "severity": self.severity.value,
            "code": self.code,
            "entity_id": self.entity_id,
            "path": self.path,
            "field": self.field,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def relative_path(path: str | Path | None, root: Path) -> str | None:
    """Return ``path`` relative to ``root`` in POSIX form when it is inside it."""
    if path is None:
        return None
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return candidate.as_posix()
    if str(relative) == ".":
        # The path *is* the project root (a missing project directory).
        return candidate.as_posix()
    return relative.as_posix()


def from_error(
    error: QaTraceError, *, root: Path, entity_id: str | None = None
) -> Diagnostic:
    """Convert a loader error into an ``error`` diagnostic."""
    return Diagnostic(
        code=error.code,
        severity=Severity.ERROR,
        message=error.message,
        path=relative_path(error.path, root),
        field=error.field,
        entity_id=entity_id,
    )


def sort_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Order diagnostics deterministically: severity, path, code, field."""
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                SEVERITY_RANK[item.severity],
                item.path or "",
                item.code,
                item.field or "",
                item.entity_id or "",
                item.message,
            ),
        )
    )


def count_by_severity(diagnostics: Iterable[Diagnostic]) -> dict[str, int]:
    """Return ``{"error": n, "warn": n, "info": n}``."""
    counts = {severity.value: 0 for severity in Severity}
    for diagnostic in diagnostics:
        counts[diagnostic.severity.value] += 1
    return counts


def exit_code(diagnostics: Iterable[Diagnostic], *, strict: bool = False) -> int:
    """Map diagnostics to the process exit code of the ``qa`` CLI.

    ``2`` is reserved for input/tool failures, ``1`` for rule violations and
    ``0`` for a clean library.  Warnings only fail the run when the project
    configuration (or ``--strict``) asks for it.
    """
    items = tuple(diagnostics)
    if any(
        item.severity is Severity.ERROR and item.code in INPUT_ERROR_CODES for item in items
    ):
        return 2
    if any(item.severity is Severity.ERROR for item in items):
        return 1
    if strict and any(item.severity is Severity.WARN for item in items):
        return 1
    return 0
