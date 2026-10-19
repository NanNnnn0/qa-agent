"""Run manifest assembly and atomic writing (plan section 3.5, P2).

A run manifest is the immutable record of one pytest session: which cases ran,
with which outcome, in which environment, against which snapshot of the library.
The plugin collects raw reports and hands them to this module, which keeps the
JSON shape stable and writes the file atomically so an interrupted writer can
never leave a half-written manifest behind.

The manifest reuses the P0 :class:`~qa_trace.models.Run` shape for the keys that
model owns (``run_id``, ``project_id``, ``started_at``, ``finished_at``,
``results``), so ``Run.from_dict(manifest)`` parses a manifest written here.
Everything P2 adds (per-case aggregation, summary, snapshot, pytest context) is
an extra key that the model keeps in ``extra``.

Two rules from plan section 3.5 are enforced here rather than in the plugin:

* one parametrised instance failing must not let the case aggregate look green
  (:func:`worst_outcome`), and
* an interrupted session keeps its manifest and is reported as ``incomplete``
  (:func:`run_status`), never as a success.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import FailureStage, Outcome

#: Version of the manifest document written by the plugin.
MANIFEST_VERSION = 1

#: Failure text is truncated to this many characters before it is stored.
MAX_ERROR_SUMMARY = 2000

_TRUNCATION_MARKER = "\n... (truncated)"

#: Outcomes ordered from least to most severe.  The aggregate of a case is the
#: most severe outcome of its instances, so one failing parameter cannot be
#: hidden behind a passing one.
OUTCOME_ORDER: tuple[Outcome, ...] = (
    Outcome.CANCELLED,
    Outcome.SKIPPED,
    Outcome.XFAILED,
    Outcome.PASSED,
    Outcome.XPASSED,
    Outcome.FAILED,
    Outcome.ERROR,
)
_OUTCOME_RANK: dict[Outcome, int] = {
    outcome: index for index, outcome in enumerate(OUTCOME_ORDER)
}

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
STATUS_COLLECT_ONLY = "collect_only"

#: pytest exit statuses that mean the session did not run to completion.
INCOMPLETE_EXIT_STATUSES: frozenset[int] = frozenset({2, 3})


@dataclass(frozen=True, slots=True)
class NodeResult:
    """One executed pytest node, already mapped to its qa-trace case IDs."""

    nodeid: str
    case_ids: tuple[str, ...]
    outcome: Outcome
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    failure_stage: FailureStage | None = None
    error_summary: str | None = None


def truncate_error(
    message: str | None, limit: int = MAX_ERROR_SUMMARY
) -> str | None:
    """Return ``message`` shortened to ``limit`` characters, or ``None``.

    The head of a traceback carries the assertion and the location, so the tail
    is what gets dropped.  A truncation marker makes the loss explicit.
    """
    if message is None:
        return None
    text = message.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    head = text[: max(0, limit - len(_TRUNCATION_MARKER))]
    return head + _TRUNCATION_MARKER


def worst_outcome(outcomes: Iterable[Outcome]) -> Outcome:
    """Return the most severe outcome; ``cancelled`` for an empty input."""
    worst = Outcome.CANCELLED
    for outcome in outcomes:
        if _OUTCOME_RANK[outcome] > _OUTCOME_RANK[worst]:
            worst = outcome
    return worst


def run_status(exitstatus: int, *, collect_only: bool = False) -> str:
    """Map a pytest exit status to the manifest ``status``."""
    if collect_only:
        return STATUS_COLLECT_ONLY
    if int(exitstatus) in INCOMPLETE_EXIT_STATUSES:
        return STATUS_INCOMPLETE
    return STATUS_COMPLETE


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sort_key(result: NodeResult) -> tuple[float, str]:
    started = result.started_at.timestamp() if result.started_at is not None else 0.0
    return (started, result.nodeid)


def aggregate_cases(results: Sequence[NodeResult]) -> list[dict[str, Any]]:
    """Group node results by case ID and return one aggregate per case.

    A node that declares several case IDs contributes to each of them.  The
    aggregate outcome is the worst instance outcome, and the counts keep the
    per-instance detail visible.
    """
    grouped: dict[str, list[NodeResult]] = {}
    for result in results:
        for case_id in result.case_ids:
            grouped.setdefault(case_id, []).append(result)
    cases: list[dict[str, Any]] = []
    for case_id in sorted(grouped):
        entries = grouped[case_id]
        counts = {outcome.value: 0 for outcome in OUTCOME_ORDER}
        for entry in entries:
            counts[entry.outcome.value] += 1
        summary = next(
            (entry.error_summary for entry in entries if entry.error_summary), None
        )
        cases.append(
            {
                "case_id": case_id,
                "outcome": worst_outcome(entry.outcome for entry in entries).value,
                "counts": counts,
                "nodeids": sorted({entry.nodeid for entry in entries}),
                "attempts": len(entries),
                "duration_ms": sum(entry.duration_ms for entry in entries),
                "error_summary": summary,
            }
        )
    return cases


def _result_rows(results: Sequence[NodeResult]) -> list[dict[str, Any]]:
    """Expand node results into one row per (case ID, attempt), in run order."""
    attempts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=_sort_key):
        for case_id in result.case_ids:
            attempts[case_id] = attempts.get(case_id, 0) + 1
            rows.append(
                {
                    "case_id": case_id,
                    "nodeid": result.nodeid,
                    "attempt": attempts[case_id],
                    "outcome": result.outcome.value,
                    "started_at": _isoformat(result.started_at),
                    "finished_at": _isoformat(result.finished_at),
                    "duration_ms": result.duration_ms,
                    "failure_stage": (
                        result.failure_stage.value
                        if result.failure_stage is not None
                        else None
                    ),
                    "error_summary": result.error_summary,
                }
            )
    rows.sort(key=lambda row: (row["case_id"], row["attempt"], row["nodeid"]))
    return rows


def build_manifest(
    *,
    run_id: str,
    project_id: str,
    project_path: str | None,
    status: str,
    exitstatus: int,
    started_at: datetime,
    finished_at: datetime,
    environment: str | None,
    tool_version: str,
    code_commit: str | None,
    asset_snapshot: Mapping[str, Any] | None,
    script_digest: Mapping[str, Any] | None,
    results: Sequence[NodeResult],
    unmapped_nodeids: Sequence[str] = (),
    collected: int | None = None,
    pytest_version: str | None = None,
    rootdir: str | None = None,
    args: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble the stable manifest document for one run."""
    rows = _result_rows(results)
    cases = aggregate_cases(results)
    outcomes = {outcome.value: 0 for outcome in OUTCOME_ORDER}
    for row in rows:
        outcomes[row["outcome"]] += 1
    collected_nodes = (
        collected
        if collected is not None
        else len({result.nodeid for result in results})
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "project_id": project_id,
        "project_path": project_path,
        "status": status,
        "exitstatus": int(exitstatus),
        "started_at": _isoformat(started_at),
        "finished_at": _isoformat(finished_at),
        "tool": {"name": "qa_trace", "version": tool_version},
        "tool_version": tool_version,
        "environment": environment,
        "code_commit": code_commit,
        "script_digest": dict(script_digest) if script_digest is not None else None,
        "asset_snapshot": dict(asset_snapshot) if asset_snapshot else {},
        "summary": {
            "collected": collected_nodes,
            "results": len(rows),
            "cases": len(cases),
            "outcomes": outcomes,
        },
        "results": rows,
        "cases": cases,
        "unmapped_nodeids": sorted(unmapped_nodeids),
        "pytest": {
            "version": pytest_version,
            "rootdir": rootdir,
            "args": list(args),
        },
    }


def write_manifest(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` to ``path`` atomically and return the final path.

    The document is written to a hidden temporary file in the target directory,
    flushed to disk and then moved over the destination with :func:`os.replace`,
    which is atomic on the same filesystem.  A crash mid-write leaves either the
    previous manifest or no manifest, never a truncated JSON document.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target
