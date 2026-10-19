"""One entry point for "is this library valid?" used by the CLI and, in P4, the workbench.

The order is the one plan section 4 prescribes: safe parsing and schema first,
then the graph rules, then the script bindings and their pytest markers, then the
metrics.  A structural error stops the run before the graph rules because the
graph would be built from a half-loaded library; those errors are reported
instead of being hidden behind a green coverage line.

The marker lint (P2, spec rule 9) reads the bound scripts with :mod:`ast`; it
never imports or executes test code, which is what makes ``qa trace check`` the
fast path.

P3 adds ``include_drafts``: each draft batch is validated on its own candidate
graph (formal library + that batch).  Drafts are *excluded* by default, so an
unfinished batch can never make the formal library look broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .diagnostics import (
    Diagnostic,
    Severity,
    count_by_severity,
    exit_code,
    from_error,
    sort_diagnostics,
)
from .drafts import check_draft_batches
from .graph import TraceGraph
from .loader import Project, scan_project
from .markers import check_markers
from .rules import check_graph


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Everything one ``qa trace check`` knows about a project directory."""

    root: Path
    diagnostics: tuple[Diagnostic, ...]
    project: Project | None = None
    graph: TraceGraph | None = None
    strict: bool = False
    include_drafts: bool = False

    @property
    def valid(self) -> bool:
        """Whether the library has no error-level diagnostic."""
        return not any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def counts(self) -> dict[str, int]:
        """Number of diagnostics per severity."""
        return count_by_severity(self.diagnostics)

    @property
    def exit_code(self) -> int:
        """The process exit code this result maps to."""
        return exit_code(self.diagnostics, strict=self.strict)

    def errors(self) -> tuple[Diagnostic, ...]:
        """Return only the error-level diagnostics."""
        return tuple(
            item for item in self.diagnostics if item.severity is Severity.ERROR
        )


def run_check(root: str | Path, *, include_drafts: bool = False) -> CheckResult:
    """Load a project, run the graph rules, the marker lint and (optionally) drafts."""
    project_root = Path(root)
    outcome = scan_project(project_root)
    if outcome.project is None:
        diagnostics = sort_diagnostics(
            from_error(error, root=project_root) for error in outcome.errors
        )
        return CheckResult(
            root=project_root,
            diagnostics=diagnostics,
            strict=bool(outcome.config.strict) if outcome.config is not None else False,
            include_drafts=include_drafts,
        )
    project = outcome.project
    graph = TraceGraph(project)
    diagnostics: list[Diagnostic] = [
        *check_graph(project, graph),
        *check_markers(project),
    ]
    if include_drafts:
        diagnostics.extend(check_draft_batches(project))
    return CheckResult(
        root=project_root,
        diagnostics=sort_diagnostics(diagnostics),
        project=project,
        graph=graph,
        strict=project.config.strict,
        include_drafts=include_drafts,
    )
