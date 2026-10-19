"""Resolve ``automation.script`` to a file inside the project library.

P1 only checks that the declared target exists, is a Python file and lives
inside the project root.  The pytest marker cross-check (rule 9) needs
collection and arrives with the P2 plugin; until then the automation rate is
reported as ``provisional``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ScriptBinding


@dataclass(frozen=True, slots=True)
class ScriptTarget:
    """The outcome of resolving one script binding."""

    ok: bool
    path: Path | None = None
    code: str | None = None
    message: str = ""


def resolve_script_target(root: Path, binding: ScriptBinding) -> ScriptTarget:
    """Resolve ``binding.file`` against the project root and classify the result."""
    raw = binding.file.strip()
    if not raw:
        return ScriptTarget(False, code="TRACE_REF_MISSING", message="script path is blank")
    declared = Path(raw)
    resolved = (declared if declared.is_absolute() else root / declared).resolve()
    try:
        root_resolved = root.resolve()
    except OSError:  # pragma: no cover - an unreadable root is reported by the loader
        root_resolved = root
    try:
        inside = resolved.is_relative_to(root_resolved)
    except (OSError, ValueError):  # pragma: no cover - different drives on Windows
        inside = False
    if not inside:
        return ScriptTarget(
            False,
            code="TRACE_REF_OUTSIDE_PROJECT",
            message=f"script target {raw!r} is outside the project directory",
        )
    if not resolved.is_file():
        return ScriptTarget(
            False,
            code="TRACE_REF_MISSING",
            message=f"script target {raw!r} does not exist",
        )
    if resolved.suffix.lower() != ".py":
        return ScriptTarget(
            False,
            code="TRACE_REF_TYPE_MISMATCH",
            message=f"script target {raw!r} is not a Python file",
        )
    return ScriptTarget(True, path=resolved)
