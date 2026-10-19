"""Coverage and health metrics, computed exactly as plan section 5 defines them.

Denominators are the *formal library* only: active sources and non-deprecated
cases.  ``draft/`` batches and deprecated sources never enter the numbers, so a
pile of drafts cannot raise coverage.  Only ``reviewed`` cases count, and a
reviewed case only counts when the whole path it uses is legal:

* the source is ``active`` and ``confirmed`` (an ``observed`` source is not a
  basis for a reviewed expectation),
* the test point on the path is ``reviewed`` (a reviewed case behind a draft
  test point covers nothing),
* a case that hangs directly off a source must declare ``direct_reason``.

``reviewed`` and ``current_valid`` are reported separately: the second one also
drops paths through a stale source.  Content/dependency hashes that decide
whether a review is still current arrive with P3, so ``current_valid`` is only
"no stale source on the path" today.

The four headline numbers (requirement coverage, behavior coverage, automation
rate, orphan rate) are separate keys on purpose.  There is deliberately no
combined "coverage" scalar to divide the team's attention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bindings import resolve_script_target
from .graph import TraceGraph, TracePath
from .loader import Project
from .models import (
    AutomationStatus,
    Case,
    Confidence,
    EntityStatus,
    Priority,
    ReviewStatus,
    Source,
    SourceType,
)

#: Source types that make up the behavior denominator (spec section 4).
BEHAVIOR_TYPES: tuple[SourceType, ...] = (SourceType.UI, SourceType.API)


@dataclass(frozen=True, slots=True)
class Ratio:
    """A numerator, its denominator and the percentage between them."""

    numerator: int
    denominator: int

    @property
    def percent(self) -> float | None:
        """Percentage rounded to two decimals, or ``None`` when the denominator is 0."""
        if self.denominator == 0:
            return None
        return round(100 * self.numerator / self.denominator, 2)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this ratio."""
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "percent": self.percent,
        }


def _active_sources(project: Project) -> list[Source]:
    return [
        source
        for source in (project.sources[key] for key in sorted(project.sources))
        if source.status is EntityStatus.ACTIVE
    ]


def _library_cases(project: Project) -> list[Case]:
    """Cases of the formal library: everything that is not deprecated."""
    return [
        case
        for case in (project.cases[key] for key in sorted(project.cases))
        if case.status is not ReviewStatus.DEPRECATED
    ]


def _reviewed_cases(project: Project) -> list[Case]:
    return [case for case in _library_cases(project) if case.status is ReviewStatus.REVIEWED]


def path_is_legal(
    project: Project, case: Case, path: TracePath, *, current_only: bool = False
) -> bool:
    """Return whether ``path`` can carry reviewed coverage for ``case``."""
    source = project.sources.get(path.source_id)
    if source is None:
        return False
    if source.status is not EntityStatus.ACTIVE:
        return False
    if source.confidence is not Confidence.CONFIRMED:
        return False
    if path.testpoint_id is not None:
        testpoint = project.testpoints.get(path.testpoint_id)
        if testpoint is None or testpoint.status is not ReviewStatus.REVIEWED:
            return False
    elif case.direct_reason is None:
        return False
    if current_only and source.stale:
        return False
    return True


def _covered(
    project: Project, graph: TraceGraph, candidates: set[str], *, current_only: bool
) -> set[str]:
    covered: set[str] = set()
    for case in _reviewed_cases(project):
        for path in graph.case_paths(case.id):
            if path.source_id not in candidates or path.source_id in covered:
                continue
            if path_is_legal(project, case, path, current_only=current_only):
                covered.add(path.source_id)
    return covered


def _coverage_block(
    project: Project,
    graph: TraceGraph,
    *,
    label: str,
    kinds: tuple[SourceType, ...],
) -> dict[str, Any]:
    active = _active_sources(project)
    candidates = {source.id for source in active if source.type in kinds}
    reviewed = _covered(project, graph, candidates, current_only=False)
    current = _covered(project, graph, candidates, current_only=True)
    unconfirmed = sorted(
        source.id
        for source in active
        if source.type in kinds and source.confidence is not Confidence.CONFIRMED
    )
    return {
        "label": label,
        "types": [kind.value for kind in kinds],
        "reviewed": Ratio(len(reviewed), len(candidates)).to_dict(),
        "current_valid": Ratio(len(current), len(candidates)).to_dict(),
        "uncovered": sorted(candidates - reviewed),
        "unconfirmed_sources": unconfirmed,
    }


def _binding_ok(project: Project, case: Case) -> bool:
    binding = case.automation.script
    if binding is None:
        return False
    return resolve_script_target(project.root, binding).ok


def _automation_block(project: Project, reviewed: list[Case]) -> dict[str, Any]:
    implemented = [
        case
        for case in reviewed
        if case.automation.status is AutomationStatus.DONE and _binding_ok(project, case)
    ]
    unresolved = sorted(
        case.id
        for case in reviewed
        if case.automation.status is AutomationStatus.DONE and not _binding_ok(project, case)
    )
    return {
        "label": "automation",
        "reviewed": Ratio(len(implemented), len(reviewed)).to_dict(),
        # P2 lints the markers statically, but the fast check still does not run
        # pytest collection, so the rate stays provisional (plan section 5: a CI
        # report must do the full binding verification).
        "provisional": True,
        "provisional_reason": (
            "markers are linted statically (ast); pytest collection and execution "
            "are not part of qa trace check"
        ),
        "unresolved_scripts": unresolved,
    }


def _orphan_block(project: Project, graph: TraceGraph, library: list[Case]) -> dict[str, Any]:
    orphans = sorted(case.id for case in library if graph.is_orphan(case.id))
    return {
        "label": "orphan",
        "library": Ratio(len(orphans), len(library)).to_dict(),
        "case_ids": orphans,
    }


def _requirement_gaps(
    project: Project, graph: TraceGraph, reviewed: list[Case], coverage: dict[str, Any]
) -> dict[str, Any]:
    uncovered = list(coverage["requirement"]["uncovered"])
    without_requirement: list[str] = []
    for case in reviewed:
        reachable = graph.case_sources(case.id)
        if not reachable:
            # An orphan is a structural error, not a requirement gap.
            continue
        if any(project.sources[source_id].type is SourceType.REQ for source_id in reachable):
            continue
        without_requirement.append(case.id)
    return {
        "uncovered_requirements": uncovered,
        "cases_without_requirement_root": sorted(without_requirement),
        # Spec section 4 defines the gap count as reviewed cases whose only roots
        # are non-req; plan section 5 keeps the uncovered requirements as a
        # second, separate list.
        "count": len(without_requirement),
        "uncovered_requirement_count": len(uncovered),
    }


def _dead_assets(
    project: Project, graph: TraceGraph, reviewed: list[Case]
) -> dict[str, Any]:
    without_downstream = sorted(
        source.id
        for source in _active_sources(project)
        if not graph.downstream_testpoints(source.id) and not graph.downstream_cases(source.id)
    )
    deprecated_cases = sorted(
        case.id
        for case in (project.cases[key] for key in sorted(project.cases))
        if case.status is ReviewStatus.DEPRECATED
    )
    manual_p0 = sorted(
        case.id
        for case in reviewed
        if case.priority is Priority.P0 and case.automation.status is AutomationStatus.MANUAL
    )
    return {
        "sources_without_downstream": without_downstream,
        "deprecated_cases": deprecated_cases,
        "manual_p0_cases": {
            "status": "unknown",
            "candidates": manual_p0,
            "note": (
                "manual aging needs the automation status change time, which P1 does not "
                "record; only the current manual P0 cases are listed"
            ),
        },
        # Only the buckets that can be decided without history are counted.
        "count": len(without_downstream) + len(deprecated_cases),
        "count_is_partial": True,
    }


def needs_recheck(project: Project, graph: TraceGraph) -> list[dict[str, Any]]:
    """Return the derived re-check list for stale sources (never written back)."""
    reasons: dict[str, list[dict[str, str]]] = {}
    for source_id in sorted(project.sources):
        source = project.sources[source_id]
        if not source.stale:
            continue
        for case_id in graph.downstream_cases(source_id):
            if project.cases[case_id].status is ReviewStatus.DEPRECATED:
                continue
            reasons.setdefault(case_id, []).append(
                {"source_id": source_id, "reason": "stale"}
            )
    return [
        {"case_id": case_id, "reasons": reasons[case_id]} for case_id in sorted(reasons)
    ]


def compute_metrics(project: Project, graph: TraceGraph) -> dict[str, Any]:
    """Compute the report body: coverage, requirement gaps, dead assets, re-checks."""
    reviewed = _reviewed_cases(project)
    library = _library_cases(project)
    requirement = _coverage_block(
        project, graph, label="requirement", kinds=(SourceType.REQ,)
    )
    behavior = _coverage_block(project, graph, label="behavior", kinds=BEHAVIOR_TYPES)
    coverage = {
        "requirement": requirement,
        "behavior": behavior,
        "automation": _automation_block(project, reviewed),
        "orphan": _orphan_block(project, graph, library),
    }
    gaps = _requirement_gaps(project, graph, reviewed, coverage)
    return {
        "counts": {
            "sources": len(project.sources),
            "active_sources": len(_active_sources(project)),
            "testpoints": len(project.testpoints),
            "cases": len(project.cases),
            "library_cases": len(library),
            "reviewed_cases": len(reviewed),
        },
        "coverage": coverage,
        "requirement_gaps": gaps,
        "requirement_gap_count": gaps["count"],
        "dead_assets": _dead_assets(project, graph, reviewed),
        "needs_recheck": needs_recheck(project, graph),
    }
