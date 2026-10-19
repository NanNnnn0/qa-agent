"""The ``qa`` command line: ``trace check|report|diff|impact|stale|draft|review|failure``.

Exit codes are the contract from plan section 4 and are shared by every command:

``0``
    the command succeeded and found nothing that blocks (for ``stale``: nothing
    changed and nothing needs a re-check; for ``diff``: no regression),
``1``
    a rule/asset problem: rule violations, an unknown ID, an invalid or
    conflicting draft, a case the run never executed, changed entities that need
    attention, a diff that found a new error/dangling reference/orphan or a
    coverage drop beyond the tolerance,
``2``
    input/tool failure: unreadable project directory, YAML, schema version,
    derived index, run manifest, or (``diff``) no git work tree, an unknown
    ``--base`` ref, a project absent at that ref.

``report`` still emits its full document before exiting ``1``, so a broken
library can be inspected and gated at the same time.  ``diff`` does the same and
still prints its JSON before exiting ``1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .check import CheckResult, run_check
from .diagnostics import INPUT_ERROR_CODES, from_error
from .diff import compute_diff, render_diff
from .drafts import (
    DEFAULT_BATCH,
    add_draft,
    approve,
    list_drafts,
    new_draft,
    reject,
    render_draft_list,
    render_review_outcome,
)
from .errors import EntityNotFoundError, QaTraceError
from .failure import compute_failure, render_failure
from .impact import compute_impact, render_impact
from .loader import load_project
from .report import build_report, render_report
from .staleness import compute_stale, render_stale


def _run_check(args: argparse.Namespace) -> int:
    result = run_check(Path(args.project), include_drafts=args.include_draft)
    if not result.diagnostics:
        print("OK")
        return result.exit_code
    _print_diagnostics(result)
    return result.exit_code


def _run_report(args: argparse.Namespace) -> int:
    result = run_check(Path(args.project))
    report = build_report(result)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    return result.exit_code


def _run_diff(args: argparse.Namespace) -> int:
    result = compute_diff(
        Path(args.project),
        args.base,
        coverage_tolerance=args.coverage_tolerance,
    )
    print(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_diff(result)
    )
    return result.exit_code


def _run_impact(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    result = compute_impact(
        project, source=args.source, testpoint=args.testpoint, case=args.case
    )
    if result is None:
        selector = args.source or args.testpoint or args.case
        kind = "source" if args.source else "test point" if args.testpoint else "case"
        raise EntityNotFoundError(f"{selector} is not a {kind} of this project", field="id")
    print(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_impact(result)
    )
    return 0


def _run_stale(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    report = compute_stale(project, write=args.write)
    print(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_stale(report)
    )
    return report.exit_code


def _run_draft_new(args: argparse.Namespace) -> int:
    path = new_draft(
        Path(args.project),
        kind=args.kind,
        module=args.module,
        batch=args.batch,
        title=args.title,
        testpoint=args.testpoint,
        source=args.source,
        source_type=args.source_type,
    )
    print(f"draft written: {path.as_posix()}")
    return 0


def _run_draft_add(args: argparse.Namespace) -> int:
    path = add_draft(
        Path(args.project), Path(args.file), batch=args.batch, kind=args.kind
    )
    print(f"draft written: {path.as_posix()}")
    return 0


def _run_review_list(args: argparse.Namespace) -> int:
    listing = list_drafts(Path(args.project), batch=args.batch)
    print(
        json.dumps(listing.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_draft_list(listing)
    )
    return 0


def _run_review_approve(args: argparse.Namespace) -> int:
    outcome = approve(
        Path(args.project),
        args.id,
        batch=args.batch,
        reviewer=args.reviewer,
        note=args.note,
    )
    print(
        json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_review_outcome(outcome)
    )
    return 0


def _run_review_reject(args: argparse.Namespace) -> int:
    outcome = reject(
        Path(args.project),
        args.id,
        batch=args.batch,
        reviewer=args.reviewer,
        note=args.note,
    )
    print(
        json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_review_outcome(outcome)
    )
    return 0


def _run_failure(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    report = compute_failure(project, args.run, case_id=args.case)
    print(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json
        else render_failure(report)
    )
    return report.exit_code


def _print_diagnostics(result: CheckResult) -> None:
    for diagnostic in result.diagnostics:
        print(diagnostic.format())


def _input_failure(error: QaTraceError, root: Path) -> int:
    """Report an error that escaped the command and map it to its exit code."""
    print(from_error(error, root=root).format())
    return 2 if error.code in INPUT_ERROR_CODES else 1


def _add_project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        required=True,
        metavar="PATH",
        help="path to projects/<project-id>",
    )


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the stable JSON document instead of text",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``qa`` command."""
    parser = argparse.ArgumentParser(
        prog="qa",
        description="Traceable QA asset tooling (qa_trace).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    trace = commands.add_parser("trace", help="trace-chain commands")
    trace_commands = trace.add_subparsers(dest="trace_command", required=True)

    check = trace_commands.add_parser(
        "check", help="validate a project library (document and graph rules)"
    )
    _add_project(check)
    check.add_argument(
        "--include-draft",
        action="store_true",
        help="also validate draft/ batches on their candidate graphs",
    )
    check.set_defaults(handler=_run_check)

    report = trace_commands.add_parser(
        "report", help="print coverage, gaps and dead assets for a project"
    )
    _add_project(report)
    _add_json(report)
    report.set_defaults(handler=_run_report)

    diff = trace_commands.add_parser(
        "diff",
        help="compare the library with a git base ref and gate on regressions",
    )
    _add_project(diff)
    diff.add_argument(
        "--base",
        required=True,
        metavar="REF",
        help="git ref to compare against (for example origin/main or a commit SHA)",
    )
    diff.add_argument(
        "--coverage-tolerance",
        type=float,
        default=None,
        metavar="POINTS",
        help=(
            "allowed coverage drop in percentage points "
            "(default: thresholds.diff_coverage_tolerance, else 0)"
        ),
    )
    _add_json(diff)
    diff.set_defaults(handler=_run_diff)

    impact = trace_commands.add_parser(
        "impact",
        help="list the test points, cases and scripts below a source, test point or case",
    )
    _add_project(impact)
    target = impact.add_mutually_exclusive_group(required=True)
    target.add_argument("--source", metavar="ID", help="a REQ/API/UI/BUG/STD/EX source")
    target.add_argument("--testpoint", metavar="ID", help="a TP-* test point")
    target.add_argument("--case", metavar="ID", help="a TC-* case")
    _add_json(impact)
    impact.set_defaults(handler=_run_impact)

    stale = trace_commands.add_parser(
        "stale",
        help="compare content/dependency hashes with the recorded baseline",
    )
    _add_project(stale)
    stale.add_argument(
        "--write",
        action="store_true",
        help="record the current fingerprints as the new baseline (never approves anything)",
    )
    _add_json(stale)
    stale.set_defaults(handler=_run_stale)

    failure = trace_commands.add_parser(
        "failure", help="map the failed results of a run back to the trace chain"
    )
    _add_project(failure)
    failure.add_argument(
        "--run", required=True, metavar="RUN_ID", help="run ID under runs/, or a manifest path"
    )
    failure.add_argument("--case", metavar="ID", help="only report this case")
    _add_json(failure)
    failure.set_defaults(handler=_run_failure)

    draft = trace_commands.add_parser("draft", help="write draft entities (agent-facing)")
    draft_commands = draft.add_subparsers(dest="draft_command", required=True)

    draft_new = draft_commands.add_parser(
        "new", help="write a starter draft with a fresh UUID4 ID"
    )
    _add_project(draft_new)
    draft_new.add_argument(
        "--kind",
        required=True,
        choices=("source", "testpoint", "case"),
        help="entity kind to draft",
    )
    draft_new.add_argument("--module", required=True, metavar="LOGIN", help="module segment")
    draft_new.add_argument(
        "--batch", default=DEFAULT_BATCH, metavar="ID", help=f"draft batch (default {DEFAULT_BATCH})"
    )
    draft_new.add_argument("--title", metavar="TEXT", help="starter title")
    draft_new.add_argument("--testpoint", metavar="ID", help="TP-* the case depends on")
    draft_new.add_argument("--source", metavar="ID", help="source the draft depends on")
    draft_new.add_argument(
        "--type",
        dest="source_type",
        default="ui",
        choices=("req", "api", "ui", "bug", "std", "ex"),
        help="source type for --kind source (default ui)",
    )
    draft_new.set_defaults(handler=_run_draft_new)

    draft_add = draft_commands.add_parser(
        "add", help="copy an externally written YAML document into a draft batch"
    )
    _add_project(draft_add)
    draft_add.add_argument("--file", required=True, metavar="PATH", help="YAML document to add")
    draft_add.add_argument(
        "--batch", default=DEFAULT_BATCH, metavar="ID", help=f"draft batch (default {DEFAULT_BATCH})"
    )
    draft_add.add_argument(
        "--kind", choices=("source", "testpoint", "case"), help="expected kind (checked)"
    )
    draft_add.set_defaults(handler=_run_draft_add)

    review = trace_commands.add_parser("review", help="list, approve or reject drafts")
    review_commands = review.add_subparsers(dest="review_command", required=True)

    review_list = review_commands.add_parser("list", help="list drafts and their state")
    _add_project(review_list)
    review_list.add_argument("--batch", metavar="ID", help="only this batch")
    _add_json(review_list)
    review_list.set_defaults(handler=_run_review_list)

    review_approve = review_commands.add_parser(
        "approve", help="promote a draft, or re-review a formal test point/case"
    )
    _add_project(review_approve)
    review_approve.add_argument("--id", required=True, metavar="ID", help="entity ID")
    review_approve.add_argument("--batch", metavar="ID", help="only this batch")
    review_approve.add_argument("--reviewer", metavar="NAME", help="declared reviewer identity")
    review_approve.add_argument("--note", metavar="TEXT", help="review note")
    _add_json(review_approve)
    review_approve.set_defaults(handler=_run_review_approve)

    review_reject = review_commands.add_parser("reject", help="record the rejection of a draft")
    _add_project(review_reject)
    review_reject.add_argument("--id", required=True, metavar="ID", help="entity ID")
    review_reject.add_argument("--batch", metavar="ID", help="only this batch")
    review_reject.add_argument("--reviewer", metavar="NAME", help="declared reviewer identity")
    review_reject.add_argument("--note", metavar="TEXT", help="rejection reason")
    _add_json(review_reject)
    review_reject.set_defaults(handler=_run_review_reject)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.project)
    try:
        return int(args.handler(args))
    except QaTraceError as exc:
        return _input_failure(exc, root)


if __name__ == "__main__":
    sys.exit(main())
