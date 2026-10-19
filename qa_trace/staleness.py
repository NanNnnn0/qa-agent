"""Hash-based staleness: what changed, and which cases need a re-check.

``qa trace stale`` answers two questions from the derived index
(:mod:`qa_trace.index`):

* **what changed** — every entity whose content hash or dependency fingerprint
  differs from the recorded baseline, plus entities that appeared or disappeared;
* **what needs a re-check** — every reviewed case whose own content, dependency
  fingerprint or upstream ``stale`` flag no longer matches its review record.

Nothing is written back to the YAML library.  ``--write`` records the current
fingerprints as the new *baseline*; it never overwrites an existing review
record, so it cannot turn an unreviewed change into an approved one.  The honest
way to clear a re-check is ``qa trace review approve``.

Exit codes: ``0`` nothing changed and nothing needs a re-check, ``1`` either is
non-empty, ``2`` input/tool failure (unreadable or incompatible index).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .graph import TraceGraph
from .hashing import (
    FINGERPRINT_VERSION,
    Fingerprint,
    changed_upstream,
    fingerprint_project,
)
from .index import ProjectIndex, load_index, require_compatible, upsert_baseline, write_index
from .loader import Project
from .models import ReviewStatus

#: Version of the ``stale`` JSON document.
STALE_VERSION = 1

#: The entity's own content differs from the recorded fingerprint.
REASON_CONTENT_CHANGED = "content_changed"
#: An upstream entity changed, so the dependency fingerprint moved.
REASON_DEPENDENCY_CHANGED = "dependency_changed"
#: An upstream source carries the manual ``stale`` flag.
REASON_SOURCE_STALE = "source_stale"
#: The case is reviewed but no review record exists yet.
REASON_NO_REVIEW = "no_review_baseline"

BASELINE_RECORDED = "recorded"
BASELINE_MISSING = "missing"


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ChangedEntity:
    """One entity whose recorded fingerprint no longer matches."""

    entity_id: str
    kind: str
    content_changed: bool
    dependency_changed: bool
    in_baseline: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this change."""
        return {
            "id": self.entity_id,
            "kind": self.kind,
            "content_changed": self.content_changed,
            "dependency_changed": self.dependency_changed,
            "in_baseline": self.in_baseline,
        }


@dataclass(frozen=True, slots=True)
class Recheck:
    """One reviewed case that must be re-checked, with the concrete reasons."""

    case_id: str
    reasons: tuple[str, ...]
    changed_ids: tuple[str, ...] = ()
    reviewed_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this re-check."""
        return {
            "case_id": self.case_id,
            "reasons": list(self.reasons),
            "changed_ids": list(self.changed_ids),
            "reviewed_by": self.reviewed_by,
        }


def reviewed_entity_ids(project: Project) -> set[str]:
    """Return the test points and cases that declare ``status: reviewed``."""
    reviewed = {
        testpoint_id
        for testpoint_id, testpoint in project.testpoints.items()
        if testpoint.status is ReviewStatus.REVIEWED
    }
    reviewed.update(
        case_id
        for case_id, case in project.cases.items()
        if case.status is ReviewStatus.REVIEWED
    )
    return reviewed


def compare_fingerprints(
    fingerprints: Mapping[str, Fingerprint], index: ProjectIndex
) -> tuple[tuple[ChangedEntity, ...], tuple[str, ...]]:
    """Compare current fingerprints with the baseline.

    Returns the changed entities (in ID order) and the IDs that exist in the
    baseline but no longer in the library (deleted or renamed).
    """
    changed: list[ChangedEntity] = []
    for entity_id in sorted(fingerprints):
        fingerprint = fingerprints[entity_id]
        recorded = index.baseline.get(entity_id)
        if recorded is None:
            changed.append(
                ChangedEntity(
                    entity_id=entity_id,
                    kind=fingerprint.kind,
                    content_changed=True,
                    dependency_changed=True,
                    in_baseline=False,
                )
            )
            continue
        content_changed = recorded.content_hash != fingerprint.content_hash
        dependency_changed = recorded.dependency_hash != fingerprint.dependency_hash
        if content_changed or dependency_changed:
            changed.append(
                ChangedEntity(
                    entity_id=entity_id,
                    kind=fingerprint.kind,
                    content_changed=content_changed,
                    dependency_changed=dependency_changed,
                    in_baseline=True,
                )
            )
    removed = tuple(sorted(set(index.baseline) - set(fingerprints)))
    return tuple(changed), removed


def index_has_state(index: ProjectIndex) -> bool:
    """Whether the index has ever recorded anything for this project."""
    return bool(index.baseline or index.reviews)


def derive_rechecks(
    project: Project,
    graph: TraceGraph,
    fingerprints: Mapping[str, Fingerprint],
    index: ProjectIndex,
) -> tuple[Recheck, ...]:
    """Return the reviewed cases whose review is no longer current.

    A case needs a re-check when its own content moved, when its dependency
    fingerprint moved (any upstream change), when an upstream source carries the
    manual ``stale`` flag, or — once the project has a recorded baseline — when it
    has no review record at all.  Before the first ``qa trace stale --write`` the
    library predates P3, so a missing review record is not reported as a
    re-check; the report says ``baseline: missing`` instead.
    """
    track_reviews = index_has_state(index)
    rechecks: list[Recheck] = []
    for case_id in sorted(project.cases):
        case = project.cases[case_id]
        if case.status is not ReviewStatus.REVIEWED:
            continue
        fingerprint = fingerprints.get(case_id)
        if fingerprint is None:  # pragma: no cover - every case is fingerprinted
            continue
        reasons: list[str] = []
        changed_ids: list[str] = []
        record = index.reviews.get(case_id)
        if record is None:
            if track_reviews:
                reasons.append(REASON_NO_REVIEW)
        else:
            if record.content_hash != fingerprint.content_hash:
                reasons.append(REASON_CONTENT_CHANGED)
                changed_ids.append(case_id)
            if record.dependency_hash != fingerprint.dependency_hash:
                reasons.append(REASON_DEPENDENCY_CHANGED)
                changed_ids.extend(changed_upstream(record.upstream, fingerprint.upstream))
        for source_id in graph.case_sources(case_id):
            if project.sources[source_id].stale:
                if REASON_SOURCE_STALE not in reasons:
                    reasons.append(REASON_SOURCE_STALE)
                if source_id not in changed_ids:
                    changed_ids.append(source_id)
        if not reasons:
            continue
        rechecks.append(
            Recheck(
                case_id=case_id,
                reasons=tuple(reasons),
                changed_ids=tuple(dict.fromkeys(changed_ids)),
                reviewed_by=record.reviewed_by if record is not None else None,
            )
        )
    return tuple(rechecks)


@dataclass(frozen=True, slots=True)
class StaleReport:
    """The result of one ``qa trace stale`` invocation."""

    root: Path
    project_id: str | None
    baseline: str
    fingerprint_version: int
    changed: tuple[ChangedEntity, ...]
    removed: tuple[str, ...]
    needs_recheck: tuple[Recheck, ...]
    reviewed_cases: int
    adopted: int
    named_reviews: int
    written: bool
    recorded: int
    index_path: str | None

    @property
    def exit_code(self) -> int:
        """Return 1 when something changed or needs a re-check, else 0."""
        return 1 if self.changed or self.removed or self.needs_recheck else 0

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this report."""
        return {
            "stale_version": STALE_VERSION,
            "project": {"id": self.project_id, "root": self.root.as_posix()},
            "baseline": self.baseline,
            "fingerprint_version": self.fingerprint_version,
            "written": self.written,
            "recorded": self.recorded,
            "index": self.index_path,
            "counts": {
                "changed": len(self.changed),
                "removed": len(self.removed),
                "needs_recheck": len(self.needs_recheck),
                "reviewed_cases": self.reviewed_cases,
                "adopted_reviews": self.adopted,
                "named_reviews": self.named_reviews,
            },
            "changed": [item.to_dict() for item in self.changed],
            "removed": list(self.removed),
            "needs_recheck": [item.to_dict() for item in self.needs_recheck],
        }


def compute_stale(
    project: Project, *, write: bool = False, now: str | None = None
) -> StaleReport:
    """Compare the library with the index, optionally recording a new baseline."""
    moment = now if now is not None else utc_now()
    index = require_compatible(load_index(project.root, project_id=project.config.project_id))
    fingerprints = fingerprint_project(project)
    written = False
    recorded = 0
    if write:
        index = upsert_baseline(
            index,
            fingerprints,
            now=moment,
            adopt_ids=reviewed_entity_ids(project),
        )
        write_index(index, now=moment)
        written = True
        recorded = len(fingerprints)
    changed, removed = compare_fingerprints(fingerprints, index)
    graph = TraceGraph(project)
    rechecks = derive_rechecks(project, graph, fingerprints, index)
    reviewed_cases = sum(
        1 for case in project.cases.values() if case.status is ReviewStatus.REVIEWED
    )
    adopted = sum(1 for entry in index.reviews.values() if entry.adopted)
    named = sum(1 for entry in index.reviews.values() if entry.reviewed_by is not None)
    return StaleReport(
        root=project.root,
        project_id=project.config.project_id,
        baseline=BASELINE_RECORDED if index.exists else BASELINE_MISSING,
        fingerprint_version=FINGERPRINT_VERSION,
        changed=changed,
        removed=removed,
        needs_recheck=rechecks,
        reviewed_cases=reviewed_cases,
        adopted=adopted,
        named_reviews=named,
        written=written,
        recorded=recorded,
        index_path=index.path.as_posix() if index.exists else None,
    )


def recheck_map(
    project: Project, graph: TraceGraph | None = None
) -> dict[str, Recheck]:
    """Return ``case_id -> Recheck`` for the current library state.

    Used by ``impact`` and ``failure``; an unreadable index raises
    :class:`~qa_trace.errors.TraceIndexError` rather than pretending nothing is
    stale.
    """
    active_graph = graph if graph is not None else TraceGraph(project)
    index = require_compatible(load_index(project.root, project_id=project.config.project_id))
    fingerprints = fingerprint_project(project)
    return {
        item.case_id: item
        for item in derive_rechecks(project, active_graph, fingerprints, index)
    }


def render_stale(report: StaleReport) -> str:
    """Render a stale report as aligned plain text."""
    project_id = report.project_id or "<unknown>"
    lines = [f"qa-trace stale: {project_id}"]
    state = "recorded" if report.baseline == BASELINE_RECORDED else "missing (run --write)"
    lines.append(f"  baseline            {state}")
    if report.written:
        lines.append(f"  recorded            {report.recorded} entities")
    lines.append(
        "  reviews             "
        f"{report.named_reviews} named, {report.adopted} adopted, "
        f"{report.reviewed_cases} reviewed case(s)"
    )
    if report.changed:
        lines.append(f"  changed             {len(report.changed)}")
        for item in report.changed:
            flags = []
            if item.content_changed:
                flags.append("content")
            if item.dependency_changed:
                flags.append("dependency")
            if not item.in_baseline:
                flags.append("not in baseline")
            lines.append(
                f"    {item.kind:<9} {item.entity_id}  ({', '.join(flags)})"
            )
    else:
        lines.append("  changed             0")
    if report.removed:
        lines.append(f"  removed             {', '.join(report.removed)}")
    if report.needs_recheck:
        lines.append(f"  needs re-check      {len(report.needs_recheck)}")
        for item in report.needs_recheck:
            detail = ", ".join(item.reasons)
            if item.changed_ids:
                detail += f": {', '.join(item.changed_ids)}"
            lines.append(f"    {item.case_id}  ({detail})")
    else:
        lines.append("  needs re-check      0")
    return "\n".join(lines)


__all__ = [
    "BASELINE_MISSING",
    "BASELINE_RECORDED",
    "REASON_CONTENT_CHANGED",
    "REASON_DEPENDENCY_CHANGED",
    "REASON_NO_REVIEW",
    "REASON_SOURCE_STALE",
    "STALE_VERSION",
    "ChangedEntity",
    "Recheck",
    "StaleReport",
    "compare_fingerprints",
    "compute_stale",
    "derive_rechecks",
    "recheck_map",
    "render_stale",
    "reviewed_entity_ids",
    "utc_now",
]
