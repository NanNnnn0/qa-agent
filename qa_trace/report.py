"""The ``qa trace report`` payload: one stable JSON document plus a text view.

The JSON shape is the interface the workbench will consume in P4, so it is
versioned (``report_version``) and every key is always present: a suppressed
metric is ``null`` rather than missing, which keeps downstream code from
guessing.  Paths are project-relative POSIX strings, so the same fixture
produces byte-identical output on Windows and Linux.

A structurally broken library reports ``valid: false`` and suppresses coverage
on purpose (plan section 4): printing a percentage for a half-loaded graph would
turn a broken chain into a reassuring number.
"""

from __future__ import annotations

from typing import Any

from .check import CheckResult
from .diagnostics import Severity
from .metrics import compute_metrics
from .rules import dangling_codes

#: Version of the JSON report shape.
REPORT_VERSION = 1


def _tool_block() -> dict[str, str]:
    from . import __version__

    return {"name": "qa_trace", "version": __version__}


def _project_block(result: CheckResult) -> dict[str, Any]:
    config = result.project.config if result.project is not None else None
    return {
        "id": config.project_id if config is not None else None,
        "name": config.name if config is not None else None,
        "root": result.root.as_posix(),
    }


def build_report(result: CheckResult) -> dict[str, Any]:
    """Build the JSON-ready report for one check result."""
    counts = result.counts
    dangling = sum(
        1
        for item in result.diagnostics
        if item.severity is Severity.ERROR and item.code in dangling_codes()
    )
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "tool": _tool_block(),
        "project": _project_block(result),
        "valid": result.valid,
        "counts": {},
        "coverage": None,
        "requirement_gaps": None,
        "requirement_gap_count": None,
        "dangling_count": dangling,
        "dead_assets": None,
        "needs_recheck": [],
        "metrics_suppressed": None,
        "diagnostics": {
            "counts": counts,
            "items": [item.to_dict() for item in result.diagnostics],
        },
    }
    if result.project is not None and result.graph is not None:
        metrics = compute_metrics(result.project, result.graph)
        report["counts"] = metrics["counts"]
        report["counts"]["dangling_references"] = dangling
        report["needs_recheck"] = metrics["needs_recheck"]
        if result.valid:
            report["coverage"] = metrics["coverage"]
            report["requirement_gaps"] = metrics["requirement_gaps"]
            report["requirement_gap_count"] = metrics["requirement_gap_count"]
            report["dead_assets"] = metrics["dead_assets"]
        else:
            errors = counts.get(Severity.ERROR.value, 0)
            report["metrics_suppressed"] = (
                f"library has {errors} structural error(s); fix them before reading metrics"
            )
    else:
        report["metrics_suppressed"] = "the project library could not be loaded"
    return report


def _ratio_text(value: dict[str, Any] | None) -> str:
    if not value:
        return "N/A"
    percent = value.get("percent")
    shown = "N/A" if percent is None else f"{percent:.2f}%"
    return f"{value['numerator']}/{value['denominator']} = {shown}"


def _diagnostic_line(item: dict[str, Any]) -> str:
    location = item.get("path") or ""
    field = item.get("field")
    if field:
        location = f"{location}:{field}" if location else field
    head = f"  {str(item['severity']).upper():<5} {item['code']}"
    return f"{head} {location}: {item['message']}" if location else f"{head} {item['message']}"


def render_report(report: dict[str, Any]) -> str:
    """Render a report dictionary as aligned plain text."""
    project = report.get("project") or {}
    identifier = project.get("id") or "<unknown>"
    state = "valid" if report.get("valid") else "INVALID"
    lines = [f"qa-trace report: {identifier} ({state})"]

    counts = report.get("counts") or {}
    if counts:
        lines.append(
            "  entities            "
            f"{counts.get('sources', 0)} source(s), "
            f"{counts.get('testpoints', 0)} testpoint(s), "
            f"{counts.get('cases', 0)} case(s) "
            f"({counts.get('reviewed_cases', 0)} reviewed)"
        )

    coverage = report.get("coverage")
    if not coverage:
        lines.append(f"  metrics             suppressed: {report.get('metrics_suppressed')}")
    else:
        requirement = coverage["requirement"]
        behavior = coverage["behavior"]
        automation = coverage["automation"]
        orphan = coverage["orphan"]
        lines.append(
            "  requirement cover.  "
            f"reviewed {_ratio_text(requirement['reviewed'])}   "
            f"current-valid {_ratio_text(requirement['current_valid'])}"
        )
        lines.append(
            "  behavior cover.     "
            f"reviewed {_ratio_text(behavior['reviewed'])}   "
            f"current-valid {_ratio_text(behavior['current_valid'])}"
        )
        lines.append(
            "  automation rate     "
            f"reviewed {_ratio_text(automation['reviewed'])}   (provisional)"
        )
        lines.append(f"  orphan rate         {_ratio_text(orphan['library'])}")
        gaps = report.get("requirement_gaps") or {}
        lines.append(
            "  requirement gaps    "
            f"{gaps.get('count', 0)} reviewed case(s) without a REQ root, "
            f"{gaps.get('uncovered_requirement_count', 0)} uncovered requirement(s)"
        )
        lines.append(f"  dangling references {report.get('dangling_count', 0)}")
        dead = report.get("dead_assets") or {}
        manual = dead.get("manual_p0_cases") or {}
        lines.append(
            "  dead assets         "
            f"{dead.get('count', 0)} known "
            f"({len(dead.get('sources_without_downstream') or [])} source(s) without downstream, "
            f"{len(dead.get('deprecated_cases') or [])} deprecated case(s)); "
            f"manual P0 aging {manual.get('status', 'unknown')} "
            f"({len(manual.get('candidates') or [])} candidate(s))"
        )
        rechecks = report.get("needs_recheck") or []
        if rechecks:
            lines.append(
                "  needs re-check      "
                + ", ".join(item["case_id"] for item in rechecks)
            )

    diagnostics = report.get("diagnostics") or {}
    items = diagnostics.get("items") or []
    if items:
        severity_counts = diagnostics.get("counts") or {}
        lines.append(
            "  diagnostics         "
            f"error {severity_counts.get('error', 0)}  "
            f"warn {severity_counts.get('warn', 0)}  "
            f"info {severity_counts.get('info', 0)}"
        )
        lines.append("")
        lines.extend(_diagnostic_line(item) for item in items)
    return "\n".join(lines)
