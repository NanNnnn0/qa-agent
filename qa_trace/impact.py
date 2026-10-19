"""``qa trace impact``: what hangs below a source, test point or case.

The query reuses :class:`qa_trace.graph.TraceGraph` (the same reverse indexes the
checker and the report use) instead of walking the files again, and reuses
:func:`qa_trace.staleness.recheck_map` for the "needs re-check" column, so the
answer cannot drift from ``qa trace stale``.

Exit codes: ``0`` the ID exists and its impact is printed, ``1`` the ID is not an
entity of that kind in this project, ``2`` input/tool failure (project, YAML,
index).

Deletion and renaming are deliberately *not* handled here: the query answers for
the library as it is now.  Following a removed entity needs the baseline graph
(plan section 6), which is not part of P3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bindings import resolve_script_target
from .graph import TraceGraph
from .loader import Project
from .models import Case
from .staleness import recheck_map

#: Version of the ``impact`` JSON document.
IMPACT_VERSION = 1

TARGET_SOURCE = "source"
TARGET_TESTPOINT = "testpoint"
TARGET_CASE = "case"


def _testpoint_entry(project: Project, testpoint_id: str) -> dict[str, Any]:
    testpoint = project.testpoints.get(testpoint_id)
    if testpoint is None:
        return {
            "id": testpoint_id,
            "exists": False,
            "title": None,
            "status": None,
            "method": None,
            "risk": None,
        }
    return {
        "id": testpoint.id,
        "exists": True,
        "title": testpoint.title,
        "status": testpoint.status.value,
        "method": testpoint.method.value,
        "risk": testpoint.risk.value,
    }


def _source_entry(project: Project, source_id: str) -> dict[str, Any]:
    source = project.sources.get(source_id)
    if source is None:
        return {
            "id": source_id,
            "exists": False,
            "type": None,
            "title": None,
            "status": None,
            "confidence": None,
            "stale": None,
        }
    return {
        "id": source.id,
        "exists": True,
        "type": source.type.value,
        "title": source.title,
        "status": source.status.value,
        "confidence": source.confidence.value,
        "stale": source.stale,
    }


def _script_entry(project: Project, case: Case) -> dict[str, Any] | None:
    binding = case.automation.script
    if binding is None:
        return None
    target = resolve_script_target(project.root, binding)
    return {
        "case_id": case.id,
        "binding": binding.script,
        "file": binding.file,
        "nodeid": binding.nodeid,
        "resolves": target.ok,
        "problem": None if target.ok else target.message,
    }


def _case_entry(
    project: Project,
    case: Case,
    *,
    paths: tuple[tuple[str, str | None], ...],
    rechecks: dict[str, Any],
) -> dict[str, Any]:
    recheck = rechecks.get(case.id)
    return {
        "id": case.id,
        "title": case.title,
        "status": case.status.value,
        "priority": case.priority.value,
        "automation": case.automation.status.value,
        "script": (
            case.automation.script.script if case.automation.script is not None else None
        ),
        "needs_recheck": recheck is not None,
        "reasons": list(recheck.reasons) if recheck is not None else [],
        "changed_ids": list(recheck.changed_ids) if recheck is not None else [],
        "via": [
            {"source_id": source_id, "testpoint_id": testpoint_id}
            for source_id, testpoint_id in paths
        ],
    }


@dataclass(frozen=True, slots=True)
class ImpactResult:
    """The answer of one impact query."""

    root: str
    project_id: str | None
    target_id: str
    target_kind: str
    testpoints: tuple[dict[str, Any], ...]
    cases: tuple[dict[str, Any], ...]
    scripts: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...]

    @property
    def empty(self) -> bool:
        """Whether the target has nothing below it."""
        return not self.cases and not self.testpoints

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this result."""
        return {
            "impact_version": IMPACT_VERSION,
            "project": {"id": self.project_id, "root": self.root},
            "target": {"id": self.target_id, "kind": self.target_kind},
            "counts": {
                "testpoints": len(self.testpoints),
                "cases": len(self.cases),
                "scripts": len(self.scripts),
                "needs_recheck": sum(1 for item in self.cases if item["needs_recheck"]),
            },
            "testpoints": list(self.testpoints),
            "cases": list(self.cases),
            "scripts": list(self.scripts),
            "sources": list(self.sources),
        }


def _resolve_target(
    project: Project, *, source: str | None, testpoint: str | None, case: str | None
) -> tuple[str, str] | None:
    """Return ``(kind, id)`` for the requested selector, or ``None`` when absent."""
    if source is not None:
        return (TARGET_SOURCE, source) if source in project.sources else None
    if testpoint is not None:
        return (TARGET_TESTPOINT, testpoint) if testpoint in project.testpoints else None
    if case is not None:
        return (TARGET_CASE, case) if case in project.cases else None
    return None


def compute_impact(
    project: Project,
    *,
    source: str | None = None,
    testpoint: str | None = None,
    case: str | None = None,
    graph: TraceGraph | None = None,
) -> ImpactResult | None:
    """Return the impact of one entity, or ``None`` when the ID is unknown."""
    resolved = _resolve_target(project, source=source, testpoint=testpoint, case=case)
    if resolved is None:
        return None
    kind, target_id = resolved
    active_graph = graph if graph is not None else TraceGraph(project)
    rechecks = recheck_map(project, active_graph)

    testpoint_ids: tuple[str, ...] = ()
    case_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    path_filter: tuple[str, str | None] | None = None
    path_testpoint: str | None = None

    if kind == TARGET_SOURCE:
        testpoint_ids = active_graph.downstream_testpoints(target_id)
        case_ids = active_graph.downstream_cases(target_id)
        source_ids = (target_id,)
        path_filter = (target_id, None)
    elif kind == TARGET_TESTPOINT:
        testpoint = project.testpoints[target_id]
        testpoint_ids = (target_id,)
        case_ids = active_graph.cases_of_testpoint(target_id)
        source_ids = testpoint.sources
        path_testpoint = target_id
    else:
        target_case = project.cases[target_id]
        testpoint_ids = target_case.testpoints
        case_ids = (target_id,)
        source_ids = active_graph.case_sources(target_id)

    cases: list[dict[str, Any]] = []
    scripts: list[dict[str, Any]] = []
    for case_id in case_ids:
        case = project.cases[case_id]
        paths: list[tuple[str, str | None]] = []
        for path in active_graph.case_paths(case_id):
            if path_filter is not None and path.source_id != path_filter[0]:
                continue
            if path_testpoint is not None and path.testpoint_id != path_testpoint:
                continue
            paths.append((path.source_id, path.testpoint_id))
        cases.append(_case_entry(project, case, paths=tuple(paths), rechecks=rechecks))
        script = _script_entry(project, case)
        if script is not None:
            scripts.append(script)

    return ImpactResult(
        root=project.root.as_posix(),
        project_id=project.config.project_id,
        target_id=target_id,
        target_kind=kind,
        testpoints=tuple(_testpoint_entry(project, item) for item in testpoint_ids),
        cases=tuple(cases),
        scripts=tuple(scripts),
        sources=tuple(_source_entry(project, item) for item in source_ids),
    )


def render_impact(result: ImpactResult) -> str:
    """Render an impact result as aligned plain text."""
    project_id = result.project_id or "<unknown>"
    lines = [
        f"qa-trace impact: {project_id}",
        f"  target              {result.target_kind} {result.target_id}",
    ]
    if result.sources:
        lines.append("  sources             " + ", ".join(item["id"] for item in result.sources))
    if result.testpoints:
        lines.append(f"  test points         {len(result.testpoints)}")
        for item in result.testpoints:
            state = item["status"] or "missing"
            lines.append(f"    {item['id']}  {state}  {item['title'] or ''}".rstrip())
    else:
        lines.append("  test points         0")
    if result.cases:
        lines.append(f"  cases               {len(result.cases)}")
        for item in result.cases:
            marker = "RECHECK" if item["needs_recheck"] else "current"
            detail = f"  ({', '.join(item['reasons'])})" if item["reasons"] else ""
            lines.append(
                f"    {item['id']}  {item['status']}  {marker}  "
                f"{item['priority']}  {item['title']}{detail}"
            )
    else:
        lines.append("  cases               0")
    if result.scripts:
        lines.append(f"  scripts             {len(result.scripts)}")
        for item in result.scripts:
            state = "resolves" if item["resolves"] else f"BROKEN: {item['problem']}"
            lines.append(f"    {item['case_id']}  {item['binding']}  ({state})")
    else:
        lines.append("  scripts             0")
    return "\n".join(lines)


__all__ = [
    "IMPACT_VERSION",
    "TARGET_CASE",
    "TARGET_SOURCE",
    "TARGET_TESTPOINT",
    "ImpactResult",
    "compute_impact",
    "render_impact",
]
