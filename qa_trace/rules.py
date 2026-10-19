"""P1 graph rules: reference integrity, orphans and checklist rules 10-13.

The rules run on a fully loaded library, after the P0 document rules.  They
answer the questions a document-level check cannot:

* does every declared reference resolve, and to the right kind of thing
  (``sources``, ``testpoints``, ``automation.script``)?
* can every case be traced up to at least one source?
* what is the P0 ratio, which sources are dead ends, which cases must be
  re-checked because an upstream source went stale, and which cases hang off a
  source without saying why?

Everything here is derived at run time.  Nothing is written back to the YAML
files: ``needs_recheck`` and the metrics exist only in the report (spec section
3, "派生状态不写回文件").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .bindings import resolve_script_target
from .diagnostics import Diagnostic, Severity, relative_path, sort_diagnostics
from .errors import (
    CaseOrphanError,
    DirectReasonMissingError,
    ReferenceMissingError,
    ReferenceOutsideProjectError,
    ReferenceTypeMismatchError,
)
from .graph import TraceGraph
from .loader import Project
from .models import Case, EntityStatus, Priority, ReviewStatus, Source, TestPoint

#: Warn-level code: too many reviewed cases carry priority P0 (spec rule 10).
P0_RATIO_HIGH = "TRACE_P0_RATIO_HIGH"
#: Info-level code: an active source has nothing below it (spec rule 11).
SOURCE_NO_DOWNSTREAM = "TRACE_SOURCE_NO_DOWNSTREAM"
#: Info-level code: an active source only has draft downstream entities.
SOURCE_DRAFT_ONLY = "TRACE_SOURCE_DRAFT_ONLY"
#: Info-level code: a stale source puts its downstream cases up for re-check.
NEEDS_RECHECK = "TRACE_NEEDS_RECHECK"

#: Every rule code P1 can emit, in documentation order.
RULE_CODES: tuple[str, ...] = (
    ReferenceMissingError.code,
    ReferenceTypeMismatchError.code,
    ReferenceOutsideProjectError.code,
    CaseOrphanError.code,
    P0_RATIO_HIGH,
    SOURCE_NO_DOWNSTREAM,
    SOURCE_DRAFT_ONLY,
    NEEDS_RECHECK,
    DirectReasonMissingError.code,
)

#: The checklist rule number behind each P1 code (spec section 3).
RULE_NUMBERS: Mapping[str, int] = {
    ReferenceMissingError.code: 2,
    ReferenceTypeMismatchError.code: 2,
    ReferenceOutsideProjectError.code: 2,
    CaseOrphanError.code: 3,
    P0_RATIO_HIGH: 10,
    SOURCE_NO_DOWNSTREAM: 11,
    SOURCE_DRAFT_ONLY: 11,
    NEEDS_RECHECK: 12,
    DirectReasonMissingError.code: 13,
}

_CREATE_OR_FIX = "create the missing entity or fix the reference"


def _file(project: Project, entity_id: str) -> str | None:
    """Return the project-relative POSIX path of one entity file."""
    return relative_path(project.files.get(entity_id), project.root)


def _error(code: str, message: str, **kwargs: Any) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message, **kwargs)


def _reference_code(project: Project, identifier: str) -> str:
    """Classify a reference that is missing from its expected collection."""
    if identifier in project.testpoints or identifier in project.cases:
        return ReferenceTypeMismatchError.code
    return ReferenceMissingError.code


def _check_testpoint_sources(
    project: Project, testpoint: TestPoint, diagnostics: list[Diagnostic]
) -> None:
    for index, source_id in enumerate(testpoint.sources):
        if source_id in project.sources:
            continue
        code = _reference_code(project, source_id)
        if code == ReferenceTypeMismatchError.code:
            message = f"reference {source_id} is not a source; expected a source entity"
            suggestion = "point the test point at a REQ/API/UI/BUG/STD/EX source"
        else:
            message = f"source {source_id} referenced here is not defined"
            suggestion = _CREATE_OR_FIX
        diagnostics.append(
            _error(
                code,
                message,
                path=_file(project, testpoint.id),
                field=f"sources[{index}]",
                entity_id=testpoint.id,
                suggestion=suggestion,
            )
        )


def _check_case_links(project: Project, case: Case, diagnostics: list[Diagnostic]) -> None:
    path = _file(project, case.id)
    for index, testpoint_id in enumerate(case.testpoints):
        if testpoint_id in project.testpoints:
            continue
        code = _reference_code(project, testpoint_id)
        if code == ReferenceTypeMismatchError.code:
            message = f"reference {testpoint_id} is not a test point"
            suggestion = "point the case at a TP-* test point"
        else:
            message = f"test point {testpoint_id} referenced here is not defined"
            suggestion = _CREATE_OR_FIX
        diagnostics.append(
            _error(
                code,
                message,
                path=path,
                field=f"testpoints[{index}]",
                entity_id=case.id,
                suggestion=suggestion,
            )
        )
    for index, source_id in enumerate(case.sources):
        if source_id in project.sources:
            continue
        code = _reference_code(project, source_id)
        if code == ReferenceTypeMismatchError.code:
            message = f"reference {source_id} is not a source"
            suggestion = "point the case at a REQ/API/UI/BUG/STD/EX source"
        else:
            message = f"source {source_id} referenced here is not defined"
            suggestion = _CREATE_OR_FIX
        diagnostics.append(
            _error(
                code,
                message,
                path=path,
                field=f"sources[{index}]",
                entity_id=case.id,
                suggestion=suggestion,
            )
        )


def _check_case_script(project: Project, case: Case, diagnostics: list[Diagnostic]) -> None:
    binding = case.automation.script
    if binding is None:
        return
    target = resolve_script_target(project.root, binding)
    if target.ok:
        return
    diagnostics.append(
        _error(
            target.code or ReferenceMissingError.code,
            target.message,
            path=_file(project, case.id),
            field="automation.script",
            entity_id=case.id,
            suggestion="fix automation.script or create the script it names",
        )
    )


def _check_orphans(
    project: Project, graph: TraceGraph, diagnostics: list[Diagnostic]
) -> None:
    for case in _sorted_cases(project):
        if not graph.is_orphan(case.id):
            continue
        diagnostics.append(
            _error(
                CaseOrphanError.code,
                f"case {case.id} cannot be traced to any source",
                path=_file(project, case.id),
                field="testpoints",
                entity_id=case.id,
                suggestion=(
                    "attach a test point that references an existing source, or declare a "
                    "direct source with a direct_reason"
                ),
            )
        )


def _check_p0_ratio(project: Project, diagnostics: list[Diagnostic]) -> None:
    reviewed = [case for case in _sorted_cases(project) if case.status is ReviewStatus.REVIEWED]
    if not reviewed:
        return
    p0_cases = [case for case in reviewed if case.priority is Priority.P0]
    ratio = len(p0_cases) / len(reviewed)
    threshold = project.config.p0_ratio_max
    if ratio <= threshold:
        return
    diagnostics.append(
        Diagnostic(
            code=P0_RATIO_HIGH,
            severity=Severity.WARN,
            message=(
                f"P0 cases are {len(p0_cases)}/{len(reviewed)} ({ratio:.2%}) of reviewed cases; "
                f"threshold is {threshold:.2%}"
            ),
            path="project.yaml",
            field="thresholds.p0_ratio_max",
            suggestion="lower the priority of the extra P0 cases or raise thresholds.p0_ratio_max",
        )
    )


def _check_source_downstream(
    project: Project, graph: TraceGraph, diagnostics: list[Diagnostic]
) -> None:
    for source in _sorted_sources(project):
        if source.status is not EntityStatus.ACTIVE:
            continue
        testpoints = graph.downstream_testpoints(source.id)
        cases = graph.downstream_cases(source.id)
        path = _file(project, source.id)
        if not testpoints and not cases:
            diagnostics.append(
                Diagnostic(
                    code=SOURCE_NO_DOWNSTREAM,
                    severity=Severity.INFO,
                    message=f"source {source.id} has no downstream test point or case",
                    path=path,
                    field="id",
                    entity_id=source.id,
                    suggestion="add a test point or a direct case, or deprecate the source",
                )
            )
            continue
        if any(project.cases[case_id].status is ReviewStatus.REVIEWED for case_id in cases):
            continue
        diagnostics.append(
            Diagnostic(
                code=SOURCE_DRAFT_ONLY,
                severity=Severity.INFO,
                message=f"source {source.id} only has draft downstream cases",
                path=path,
                field="id",
                entity_id=source.id,
                suggestion="review the downstream cases so the source counts as covered",
            )
        )


def _check_stale(
    project: Project, graph: TraceGraph, diagnostics: list[Diagnostic]
) -> None:
    for source in _sorted_sources(project):
        if not source.stale:
            continue
        for case_id in graph.downstream_cases(source.id):
            if project.cases[case_id].status is ReviewStatus.DEPRECATED:
                continue
            diagnostics.append(
                Diagnostic(
                    code=NEEDS_RECHECK,
                    severity=Severity.INFO,
                    message=f"source {source.id} is stale; case {case_id} needs re-check",
                    path=_file(project, case_id),
                    field="id",
                    entity_id=case_id,
                    suggestion="re-check the case against the current source and clear its stale flag",
                )
            )


def _check_direct_reason(project: Project, diagnostics: list[Diagnostic]) -> None:
    # The loader already rejects this shape as TRACE_DIRECT_REASON_MISSING (an
    # error, see models.Case.from_dict), so the CLI never reaches this rule.  It
    # stays as a warn-level check because the specification lists rule 13 as a
    # warning and because P3 draft batches build graphs from injected entities.
    for case in _sorted_cases(project):
        if not case.sources or case.direct_reason is not None:
            continue
        diagnostics.append(
            Diagnostic(
                code=DirectReasonMissingError.code,
                severity=Severity.WARN,
                message=f"case {case.id} references sources directly without a direct_reason",
                path=_file(project, case.id),
                field="direct_reason",
                entity_id=case.id,
                suggestion="explain why the case hangs off a source instead of a test point",
            )
        )


def _sorted_cases(project: Project) -> list[Case]:
    return [project.cases[key] for key in sorted(project.cases)]


def _sorted_sources(project: Project) -> list[Source]:
    return [project.sources[key] for key in sorted(project.sources)]


def _sorted_testpoints(project: Project) -> list[TestPoint]:
    return [project.testpoints[key] for key in sorted(project.testpoints)]


def check_graph(project: Project, graph: TraceGraph | None = None) -> tuple[Diagnostic, ...]:
    """Run every P1 graph rule and return the diagnostics in stable order."""
    active_graph = graph if graph is not None else TraceGraph(project)
    diagnostics: list[Diagnostic] = []
    for testpoint in _sorted_testpoints(project):
        _check_testpoint_sources(project, testpoint, diagnostics)
    for case in _sorted_cases(project):
        _check_case_links(project, case, diagnostics)
        _check_case_script(project, case, diagnostics)
    _check_orphans(project, active_graph, diagnostics)
    _check_p0_ratio(project, diagnostics)
    _check_source_downstream(project, active_graph, diagnostics)
    _check_stale(project, active_graph, diagnostics)
    _check_direct_reason(project, diagnostics)
    return sort_diagnostics(diagnostics)


def rule_number(code: str) -> int | None:
    """Return the spec checklist rule number behind a P1 code."""
    return RULE_NUMBERS.get(code)


def dangling_codes() -> Iterable[str]:
    """Return the codes that count as a dangling reference."""
    return (
        ReferenceMissingError.code,
        ReferenceTypeMismatchError.code,
        ReferenceOutsideProjectError.code,
    )
