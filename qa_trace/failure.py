"""``qa trace failure``: map a run's failed results back to the trace chain.

The manifest written by the P2 plugin is the historical truth: it froze the
case/script binding and the library snapshot before the run.  This module reads
that manifest and, for every failed or errored result, walks

``case -> test point(s) -> source(s)``

using the **run-time** snapshot when the manifest has one, so a case that was
edited or deleted afterwards still explains what failed and against which
requirement.  It then reports the difference to the current library (did the case
file change since the run?) and the current ``needs_recheck`` state.

The latest run of each case is read from ``runs/*/manifest.json``; a manifest that
cannot be parsed is skipped for that lookup (the explicitly requested run is never
skipped — it raises instead).

Exit codes: ``0`` the run was read and its failures are printed (possibly none),
``1`` ``--case`` names a case the run did not execute, ``2`` the run manifest is
missing or unreadable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import RunInvalidError, RunNotFoundError
from .graph import TraceGraph
from .hashing import DIGEST_VERSION, sha256_bytes, sha256_file_digest
from .loader import Project
from .models import Case, Outcome
from .staleness import recheck_map

#: Version of the ``failure`` JSON document.
FAILURE_VERSION = 1

#: Directory holding run manifests inside a project.
RUNS_DIRNAME = "runs"

#: File name of one run manifest.
MANIFEST_FILENAME = "manifest.json"

#: Outcomes that count as a failure worth tracing.
FAILURE_OUTCOMES: frozenset[str] = frozenset(
    {Outcome.FAILED.value, Outcome.ERROR.value}
)


def resolve_manifest(project_root: str | Path, run: str) -> Path:
    """Return the manifest path of ``run`` (an ID or a file/directory path)."""
    root = Path(project_root)
    candidate = Path(run)
    if candidate.is_file():
        return candidate
    if candidate.is_dir() and (candidate / MANIFEST_FILENAME).is_file():
        return candidate / MANIFEST_FILENAME
    path = root / RUNS_DIRNAME / run / MANIFEST_FILENAME
    if path.is_file():
        return path
    raise RunNotFoundError(
        f"no run manifest for {run!r} (looked in {path})", path=path
    )


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Read one manifest, raising :class:`RunInvalidError` when it is unusable."""
    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunNotFoundError(f"cannot read the run manifest: {exc}", path=manifest_path) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunInvalidError(
            f"run manifest is not valid JSON: {exc}", path=manifest_path
        ) from None
    if not isinstance(data, Mapping):
        raise RunInvalidError("run manifest root must be a mapping", path=manifest_path)
    if not isinstance(data.get("run_id"), str) or not data["run_id"]:
        raise RunInvalidError(
            "run manifest needs a run_id", path=manifest_path, field="run_id"
        )
    results = data.get("results")
    if results is None:
        results = []
    if not isinstance(results, list):
        raise RunInvalidError(
            "results must be a list", path=manifest_path, field="results"
        )
    payload = dict(data)
    payload["results"] = results
    return payload


def _result_rows(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in manifest.get("results", []) if isinstance(row, Mapping)]


def _snapshot_relations(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = manifest.get("asset_snapshot")
    if not isinstance(snapshot, Mapping):
        return {}
    relations = snapshot.get("relations")
    return relations if isinstance(relations, Mapping) else {}


def _snapshot_testpoint_sources(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = manifest.get("asset_snapshot")
    if not isinstance(snapshot, Mapping):
        return {}
    relations = snapshot.get("testpoint_sources")
    return relations if isinstance(relations, Mapping) else {}


def _case_digests(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = manifest.get("asset_snapshot")
    if not isinstance(snapshot, Mapping):
        return {}
    cases = snapshot.get("cases")
    return cases if isinstance(cases, Mapping) else {}


def _digest_version(manifest: Mapping[str, Any]) -> int | None:
    """Return the digest recipe the manifest was frozen with, if it says so."""
    snapshot = manifest.get("asset_snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    version = snapshot.get("digest_version")
    return version if isinstance(version, int) else None


def _run_summary(manifest: Mapping[str, Any], path: Path) -> dict[str, Any]:
    return {
        "run_id": manifest.get("run_id"),
        "path": path.as_posix(),
        "status": manifest.get("status"),
        "exitstatus": manifest.get("exitstatus"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "environment": manifest.get("environment"),
        "app_version": manifest.get("app_version"),
        "code_commit": manifest.get("code_commit"),
        "tool_version": manifest.get("tool_version"),
    }


def _failed_rows(manifest: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in _result_rows(manifest):
        case_id = row.get("case_id")
        outcome = row.get("outcome")
        if not isinstance(case_id, str) or outcome not in FAILURE_OUTCOMES:
            continue
        grouped.setdefault(case_id, []).append(row)
    return grouped


def _result_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "nodeid": row.get("nodeid"),
        "attempt": row.get("attempt"),
        "outcome": row.get("outcome"),
        "failure_stage": row.get("failure_stage"),
        "duration_ms": row.get("duration_ms"),
        "started_at": row.get("started_at"),
        "error_summary": row.get("error_summary"),
    }


def _run_time_chain(
    project: Project,
    manifest: Mapping[str, Any],
    case_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Return ``(testpoint_ids, source_ids, origin)`` for a case at run time."""
    relations = _snapshot_relations(manifest)
    relation = relations.get(case_id)
    if isinstance(relation, Mapping):
        testpoints = tuple(
            item for item in relation.get("testpoints", []) if isinstance(item, str)
        )
        direct = tuple(item for item in relation.get("sources", []) if isinstance(item, str))
        sources: list[str] = list(direct)
        by_testpoint = _snapshot_testpoint_sources(manifest)
        for testpoint_id in testpoints:
            recorded = by_testpoint.get(testpoint_id)
            if isinstance(recorded, list):
                sources.extend(item for item in recorded if isinstance(item, str))
            else:
                # The snapshot predates P3's testpoint_sources key; fall back to
                # the current library for that hop and say so.
                current = project.testpoints.get(testpoint_id)
                if current is not None:
                    sources.extend(current.sources)
        return testpoints, tuple(dict.fromkeys(sources)), "snapshot"
    case = project.cases.get(case_id)
    if case is None:
        return (), (), "missing"
    sources = TraceGraph(project).case_sources(case_id)
    return case.testpoints, sources, "current"


def _current_case_state(project: Project, manifest: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    case: Case | None = project.cases.get(case_id)
    if case is None:
        return {
            "exists": False,
            "status": None,
            "changed_since_run": None,
            "needs_recheck": False,
            "reasons": [],
            "changed_ids": [],
        }
    recorded = _case_digests(manifest).get(case_id)
    version = _digest_version(manifest)
    path = project.files.get(case_id)
    raw: bytes | None = None
    if path is not None:
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover - the file was just loaded
            raw = None
    # A manifest frozen before digest version 2 hashed raw bytes, so it is only
    # reproducible on the checkout that produced it; keep that comparison for old
    # manifests and use the line-ending independent digest for new ones.
    if raw is None:
        current = None
    elif version is None or version < DIGEST_VERSION:
        current = sha256_bytes(raw)
    elif version == DIGEST_VERSION:
        current = sha256_file_digest(raw)
    else:  # pragma: no cover - a manifest from a newer tool
        current = None
    comparable = isinstance(recorded, str) and current is not None
    return {
        "exists": True,
        "status": case.status.value,
        "changed_since_run": None if not comparable else recorded != current,
        "needs_recheck": False,
        "reasons": [],
        "changed_ids": [],
    }


def latest_runs(project: Project) -> dict[str, dict[str, Any]]:
    """Return the latest run of each case, newest first by finish time then run ID."""
    runs_dir = project.root / RUNS_DIRNAME
    if not runs_dir.is_dir():
        return {}
    candidates: list[tuple[tuple[str, str], Mapping[str, Any], Path]] = []
    for manifest_path in sorted(runs_dir.glob(f"*/{MANIFEST_FILENAME}")):
        try:
            manifest = load_manifest(manifest_path)
        except RunNotFoundError:  # pragma: no cover - the glob found it
            continue
        except RunInvalidError:
            continue
        finished = manifest.get("finished_at") or manifest.get("started_at") or ""
        if not isinstance(finished, str):
            finished = ""
        candidates.append(((finished, str(manifest.get("run_id"))), manifest, manifest_path))
    candidates.sort(key=lambda item: item[0])
    latest: dict[str, dict[str, Any]] = {}
    for _key, manifest, manifest_path in candidates:
        for row in _result_rows(manifest):
            case_id = row.get("case_id")
            if not isinstance(case_id, str):
                continue
            latest[case_id] = {
                "run_id": manifest.get("run_id"),
                "finished_at": manifest.get("finished_at"),
                "status": manifest.get("status"),
                "outcome": row.get("outcome"),
                "nodeid": row.get("nodeid"),
                "path": manifest_path.as_posix(),
            }
    return latest


@dataclass(frozen=True, slots=True)
class FailureReport:
    """The result of one ``qa trace failure`` query."""

    root: Path
    project_id: str | None
    run: dict[str, Any]
    failures: tuple[dict[str, Any], ...] = ()
    requested_case: str | None = None
    case_missing: bool = False
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """Return 1 when the requested case never ran, else 0."""
        return 1 if self.case_missing else 0

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this report."""
        return {
            "failure_version": FAILURE_VERSION,
            "project": {"id": self.project_id, "root": self.root.as_posix()},
            "run": self.run,
            "requested_case": self.requested_case,
            "case_missing": self.case_missing,
            "counts": self.counts,
            "failures": list(self.failures),
        }


def compute_failure(
    project: Project, run: str, *, case_id: str | None = None
) -> FailureReport:
    """Map the failed results of one run back to the trace chain."""
    manifest_path = resolve_manifest(project.root, run)
    manifest = load_manifest(manifest_path)
    rows = _result_rows(manifest)
    failed = _failed_rows(manifest)
    executed = {
        row.get("case_id") for row in rows if isinstance(row.get("case_id"), str)
    }
    rechecks = recheck_map(project)
    latest = latest_runs(project)
    selected = sorted(failed)
    case_missing = False
    if case_id is not None:
        if case_id not in executed:
            case_missing = True
            selected = []
        else:
            selected = [case_id] if case_id in failed else []
    failures: list[dict[str, Any]] = []
    for failed_case in selected:
        testpoints, sources, origin = _run_time_chain(project, manifest, failed_case)
        current = _current_case_state(project, manifest, failed_case)
        recheck = rechecks.get(failed_case)
        if recheck is not None:
            current["needs_recheck"] = True
            current["reasons"] = list(recheck.reasons)
            current["changed_ids"] = list(recheck.changed_ids)
        failures.append(
            {
                "case_id": failed_case,
                "results": [_result_detail(row) for row in failed[failed_case]],
                "chain": {
                    "origin": origin,
                    "testpoints": [
                        {
                            "id": testpoint_id,
                            "exists": testpoint_id in project.testpoints,
                            "title": (
                                project.testpoints[testpoint_id].title
                                if testpoint_id in project.testpoints
                                else None
                            ),
                            "status": (
                                project.testpoints[testpoint_id].status.value
                                if testpoint_id in project.testpoints
                                else None
                            ),
                        }
                        for testpoint_id in testpoints
                    ],
                    "sources": [
                        {
                            "id": source_id,
                            "exists": source_id in project.sources,
                            "type": (
                                project.sources[source_id].type.value
                                if source_id in project.sources
                                else None
                            ),
                            "status": (
                                project.sources[source_id].status.value
                                if source_id in project.sources
                                else None
                            ),
                            "confidence": (
                                project.sources[source_id].confidence.value
                                if source_id in project.sources
                                else None
                            ),
                            "stale": (
                                project.sources[source_id].stale
                                if source_id in project.sources
                                else None
                            ),
                        }
                        for source_id in sources
                    ],
                },
                "current": current,
                "last_run": latest.get(failed_case),
            }
        )
    counts = {
        "results": len(rows),
        "failed_results": sum(len(items) for items in failed.values()),
        "failed_cases": len(failed),
        "reported_cases": len(failures),
    }
    return FailureReport(
        root=project.root,
        project_id=project.config.project_id,
        run=_run_summary(manifest, manifest_path),
        failures=tuple(failures),
        requested_case=case_id,
        case_missing=case_missing,
        counts=counts,
    )


def render_failure(report: FailureReport) -> str:
    """Render a failure report as aligned plain text."""
    project_id = report.project_id or "<unknown>"
    run = report.run
    lines = [
        f"qa-trace failure: {project_id}",
        (
            "  run                 "
            f"{run.get('run_id')} ({run.get('status')}, exitstatus {run.get('exitstatus')})"
        ),
        f"  started             {run.get('started_at')}",
        f"  environment         {run.get('environment')}",
        f"  manifest            {run.get('path')}",
        (
            "  results             "
            f"{report.counts.get('results', 0)} result(s), "
            f"{report.counts.get('failed_results', 0)} failed, "
            f"{report.counts.get('failed_cases', 0)} case(s)"
        ),
    ]
    if report.case_missing:
        lines.append(
            f"  requested case      {report.requested_case} did not run in this run"
        )
        return "\n".join(lines)
    if not report.failures:
        lines.append("  failures            none")
        return "\n".join(lines)
    for item in report.failures:
        lines.append("")
        lines.append(f"  case {item['case_id']}")
        chain = item["chain"]
        for result in item["results"]:
            lines.append(
                f"    result            {result['outcome']} "
                f"({result['failure_stage'] or 'no stage'}) "
                f"{result['nodeid']} attempt {result['attempt']}"
            )
        for testpoint in chain["testpoints"]:
            state = testpoint["status"] or "missing"
            lines.append(f"    test point        {testpoint['id']}  {state}")
        for source in chain["sources"]:
            state = source["status"] or "missing"
            lines.append(
                f"    source            {source['id']}  {state}  "
                f"{source['type'] or '-'}  stale={source['stale']}"
            )
        current = item["current"]
        changed = current["changed_since_run"]
        lines.append(
            "    current           "
            + ("missing from the library" if not current["exists"] else current["status"])
            + ("" if changed is None else f", changed since run={changed}")
        )
        if current["needs_recheck"]:
            lines.append(
                "    needs re-check    "
                + ", ".join(current["reasons"])
                + (
                    f": {', '.join(current['changed_ids'])}"
                    if current["changed_ids"]
                    else ""
                )
            )
        last = item.get("last_run") or {}
        if last:
            lines.append(
                f"    last run          {last.get('run_id')} "
                f"{last.get('outcome')} at {last.get('finished_at')}"
            )
    return "\n".join(lines)


__all__ = [
    "FAILURE_OUTCOMES",
    "FAILURE_VERSION",
    "MANIFEST_FILENAME",
    "RUNS_DIRNAME",
    "FailureReport",
    "compute_failure",
    "latest_runs",
    "load_manifest",
    "render_failure",
    "resolve_manifest",
]
