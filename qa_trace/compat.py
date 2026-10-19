"""Compatibility mapping between the YAML case model and the legacy SQLite shape.

The QA platform shipped its test cases in SQLite first: ``cases.kind`` was one of
``api``/``ui``/``manual`` and ``cases.status`` one of ``draft``/``ready``/
``deprecated``.  The trace library owns a richer vocabulary (``CaseType`` has
``functional``/``security``/``compat``/``perf`` next to ``api``/``ui``; a case is
``draft``/``reviewed``/``deprecated``).  YAML is the single source of truth now,
but the agent tool and ``/api/qa/cases*`` keep answering in the legacy field
names, so exactly one module defines the translation and nothing else guesses.

The mapping is deliberately lossy in one direction only:

===========  ==========================  ==================================
SQLite kind  Trace type                  Note
===========  ==========================  ==================================
``api``      ``api``                     lossless
``ui``       ``ui``                      lossless
``manual``   ``functional``              a manual functional test; the trace
                                         case carries
                                         ``automation.status: manual``
===========  ==========================  ==================================

The reverse direction widens ``functional``/``security``/``compat``/``perf`` to
``manual`` because the legacy enum has no slot for them.  Callers that need the
exact trace type read ``type`` from the case record; the widened kind only exists
so old filters and old clients keep working.

Status is a plain rename (``ready`` ⇄ ``reviewed``); the YAML value is the
authoritative one, ``status_legacy`` is what old clients compare against.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Legacy SQLite ``kind`` -> trace ``type``.
TYPE_BY_KIND: Mapping[str, str] = {
    "api": "api",
    "ui": "ui",
    "manual": "functional",
}

#: Trace ``type`` -> legacy SQLite ``kind`` (several types share ``manual``).
KIND_BY_TYPE: Mapping[str, str] = {
    "api": "api",
    "ui": "ui",
    "functional": "manual",
    "security": "manual",
    "compat": "manual",
    "perf": "manual",
}

#: Legacy SQLite ``status`` -> trace review status.
STATUS_BY_LEGACY: Mapping[str, str] = {
    "draft": "draft",
    "ready": "reviewed",
    "deprecated": "deprecated",
}

#: Trace review status -> legacy SQLite ``status``.
LEGACY_BY_STATUS: Mapping[str, str] = {
    "draft": "draft",
    "reviewed": "ready",
    "deprecated": "deprecated",
}

#: Accepted legacy kind values (what the agent tool and the HTTP API validate).
LEGACY_KINDS: tuple[str, ...] = ("api", "ui", "manual")

#: Accepted legacy status values.
LEGACY_STATUSES: tuple[str, ...] = ("draft", "ready", "deprecated")


def type_for_kind(kind: str | None, *, default: str = "api") -> str:
    """Return the trace ``type`` for a legacy ``kind``."""
    if kind is None:
        return default
    return TYPE_BY_KIND.get(kind.strip().lower(), default)


def kind_for_type(case_type: str | None, *, default: str = "manual") -> str:
    """Return the legacy ``kind`` for a trace ``type``."""
    if case_type is None:
        return default
    return KIND_BY_TYPE.get(case_type.strip().lower(), default)


def status_for_legacy(status: str | None, *, default: str = "draft") -> str:
    """Return the trace review status for a legacy ``status``."""
    if status is None:
        return default
    return STATUS_BY_LEGACY.get(status.strip().lower(), default)


def legacy_for_status(status: str | None, *, default: str = "draft") -> str:
    """Return the legacy ``status`` for a trace review status."""
    if status is None:
        return default
    return LEGACY_BY_STATUS.get(status.strip().lower(), default)


def automation_for_kind(
    kind: str | None, *, explicit: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the ``automation`` block for a newly written case.

    A structured API case is ``todo`` (the runner can execute it, nothing binds
    it to pytest yet); ``ui``/``manual`` cases are ``manual``.  An explicit block
    always wins over the derived one.
    """
    if explicit is not None and explicit:
        return dict(explicit)
    if (kind or "api").strip().lower() == "api":
        return {"status": "todo"}
    return {"status": "manual"}


__all__ = [
    "KIND_BY_TYPE",
    "LEGACY_BY_STATUS",
    "LEGACY_KINDS",
    "LEGACY_STATUSES",
    "STATUS_BY_LEGACY",
    "TYPE_BY_KIND",
    "automation_for_kind",
    "kind_for_type",
    "legacy_for_status",
    "status_for_legacy",
    "type_for_kind",
]
