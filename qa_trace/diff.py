"""``qa trace diff``: compare the trace library against a git base ref.

P5 (plan section 8, "CI, independently schedulable") answers one question for a
pull request: *did this change make the library worse?*  The base side is
materialised from git with ``git archive`` into a temporary directory — the
worktree is only ever read, never checked out or touched — and both sides are
checked with the same :func:`qa_trace.check.run_check` and summarised with
:func:`qa_trace.report.build_report`.  The comparison reads those two documents
and nothing else, so ``diff`` cannot drift from ``check``/``report``.

Exit codes (plan section 4, design section 4):

``0``
    no regression: no new error diagnostic, no metric that got worse by more
    than the tolerance, no new dangling reference, no new orphan case,
``1``
    regression, including a head library that is structurally broken (a new
    error is a new error, whatever broke it),
``2``
    input/tool failure: the project directory is missing, it is not inside a
    git work tree, ``--base`` cannot be resolved to a commit, the project does
    not exist at that commit, or git itself cannot run.

The tolerance is expressed in percentage points and defaults to ``0``; set
``thresholds.diff_coverage_tolerance`` in ``project.yaml`` or pass
``--coverage-tolerance``.  The JSON document is the CI contract: every key is
always present, ratios keep ``numerator``/``denominator``/``percent`` and add
``comparable``/``delta_percent``/``regression`` so a consumer never has to
re-derive a policy.  Temporary paths never appear in the document.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .check import CheckResult, run_check
from .diagnostics import Severity
from .errors import (
    DiffBaseMissingError,
    DiffBaseUnknownError,
    DiffGitError,
    DiffInputError,
    DiffNotGitError,
    ProjectError,
)
from .report import build_report
from .rules import dangling_codes

#: Version of the ``diff`` JSON document.
DIFF_VERSION = 1

#: Allowed metric worsening, in percentage points, when neither the CLI nor
#: ``project.yaml`` sets one.
DEFAULT_COVERAGE_TOLERANCE = 0.0

#: ``project.yaml`` threshold key holding the default tolerance.
TOLERANCE_KEY = "diff_coverage_tolerance"

#: ``(section, ratio key, label, higher_is_worse)`` for every compared ratio.
#: The four headline metrics stay separate (spec section 4); requirement and
#: behavior compare their reviewed *and* current-valid form (plan section 5).
_RATIOS: tuple[tuple[str, str, str, bool], ...] = (
    ("requirement", "reviewed", "requirement reviewed", False),
    ("requirement", "current_valid", "requirement current-valid", False),
    ("behavior", "reviewed", "behavior reviewed", False),
    ("behavior", "current_valid", "behavior current-valid", False),
    ("automation", "reviewed", "automation reviewed", False),
    ("orphan", "library", "orphan library", True),
)


@dataclass(frozen=True, slots=True)
class RepoContext:
    """Where the project sits inside a git work tree."""

    root: Path
    path_in_repo: str = ""

    @property
    def selector(self) -> str:
        """Return the project path as a git pathspec (``.`` for the repo root)."""
        return self.path_in_repo or "."

    @property
    def project_yaml(self) -> str:
        """Return the ``project.yaml`` path relative to the repository root."""
        return f"{self.path_in_repo}/project.yaml" if self.path_in_repo else "project.yaml"


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run one git command without a shell and without raising on failure."""
    try:
        return subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DiffGitError("the git executable was not found on PATH") from exc
    except OSError as exc:
        raise DiffGitError(f"cannot run git: {exc}") from exc


def _stdout(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stdout.decode("utf-8", errors="replace")


def _stderr(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stderr.decode("utf-8", errors="replace")


def find_repository(project_root: str | Path) -> RepoContext:
    """Return the work tree that contains ``project_root``.

    Raises :class:`~qa_trace.errors.DiffNotGitError` when the directory is not
    inside a git work tree (plan section 8: a workspace without git cannot claim
    PR checking).
    """
    directory = Path(project_root)
    top = _git(directory, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        detail = _stderr(top).strip() or "not a git work tree"
        raise DiffNotGitError(
            f"{directory.as_posix()} is not inside a git work tree: {detail}",
            path=directory,
        )
    root = Path(_stdout(top).strip())
    prefix_result = _git(directory, "rev-parse", "--show-prefix")
    prefix = _stdout(prefix_result).strip() if prefix_result.returncode == 0 else ""
    return RepoContext(root=root, path_in_repo=prefix.rstrip("/"))


def resolve_commit(context: RepoContext, ref: str) -> str:
    """Resolve ``ref`` to a full commit SHA, or fail with exit code 2."""
    result = _git(context.root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    sha = _stdout(result).strip()
    if result.returncode != 0 or not sha:
        raise DiffBaseUnknownError(
            f"cannot resolve --base {ref!r} to a commit in {context.root.as_posix()}",
            field="base",
        )
    return sha


def head_commit(context: RepoContext) -> str | None:
    """Return the current ``HEAD`` commit, or ``None`` when there is no commit."""
    result = _git(context.root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    sha = _stdout(result).strip()
    return sha or None


def _require_project_at(context: RepoContext, commit: str) -> None:
    result = _git(context.root, "cat-file", "-e", f"{commit}:{context.project_yaml}")
    if result.returncode != 0:
        raise DiffBaseMissingError(
            f"the project is absent at {commit[:12]}: {context.project_yaml}",
            path=context.project_yaml,
        )


def _extract(data: bytes, destination: Path) -> None:
    """Extract a git archive tar stream, refusing paths that escape ``destination``."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError as exc:
        raise DiffGitError(f"git archive produced an unreadable tar stream: {exc}") from exc
    with archive:
        members = []
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise DiffGitError(f"git archive produced an unsafe path: {member.name!r}")
            if member.isfile() or member.isdir():
                members.append(member)
        try:
            archive.extractall(destination, members=members, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.11.4 has no filter argument
            archive.extractall(destination, members=members)


def materialize_tree(context: RepoContext, commit: str, destination: str | Path) -> Path:
    """Write the project subtree at ``commit`` under ``destination`` and return its root."""
    target = Path(destination)
    args = ["archive", "--format=tar", commit]
    if context.path_in_repo:
        args.extend(["--", context.path_in_repo])
    result = _git(context.root, *args)
    if result.returncode != 0:
        raise DiffGitError(
            f"git archive failed for {commit[:12]}: {_stderr(result).strip()}",
            path=context.root,
        )
    _extract(result.stdout, target)
    project_root = target / context.path_in_repo if context.path_in_repo else target
    if not (project_root / "project.yaml").is_file():
        raise DiffBaseMissingError(
            f"the archived tree has no project.yaml at {context.selector}", path=project_root
        )
    return project_root


@dataclass(frozen=True, slots=True)
class SideSnapshot:
    """The comparable part of one ``build_report`` document."""

    valid: bool
    counts: dict[str, Any]
    coverage: dict[str, Any] | None
    requirement_gaps: dict[str, Any] | None
    dangling_count: int
    orphan_case_ids: tuple[str, ...]
    needs_recheck: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]
    metrics_suppressed: str | None


def _diagnostic_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(item.get("severity") or ""),
        str(item.get("code") or ""),
        str(item.get("entity_id") or ""),
        str(item.get("path") or ""),
        str(item.get("field") or ""),
        str(item.get("message") or ""),
    )


def _diagnostic_label(item: dict[str, Any]) -> str:
    code = str(item.get("code") or "?")
    target = item.get("entity_id") or item.get("path")
    return f"{code} {target}" if target else code


def _snapshot(report: dict[str, Any]) -> SideSnapshot:
    coverage = report.get("coverage")
    orphan_ids: tuple[str, ...] = ()
    if isinstance(coverage, dict):
        orphan_block = coverage.get("orphan")
        if isinstance(orphan_block, dict):
            orphan_ids = tuple(orphan_block.get("case_ids") or ())
    gaps = report.get("requirement_gaps")
    raw_items = (report.get("diagnostics") or {}).get("items") or []
    diagnostics = tuple(
        sorted(
            (
                {
                    "severity": item.get("severity"),
                    "code": item.get("code"),
                    "entity_id": item.get("entity_id"),
                    "path": item.get("path"),
                    "field": item.get("field"),
                    "message": item.get("message"),
                }
                for item in raw_items
            ),
            key=_diagnostic_key,
        )
    )
    rechecks = tuple(
        sorted(
            str(item.get("case_id"))
            for item in (report.get("needs_recheck") or [])
            if isinstance(item, dict) and item.get("case_id")
        )
    )
    return SideSnapshot(
        valid=bool(report.get("valid")),
        counts=dict(report.get("counts") or {}),
        coverage=coverage if isinstance(coverage, dict) else None,
        requirement_gaps=gaps if isinstance(gaps, dict) else None,
        dangling_count=int(report.get("dangling_count") or 0),
        orphan_case_ids=orphan_ids,
        needs_recheck=rechecks,
        diagnostics=diagnostics,
        metrics_suppressed=report.get("metrics_suppressed"),
    )


def _ratio_block(block: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not block:
        return None
    ratio = block.get(key)
    if not isinstance(ratio, dict):
        return None
    return {
        "numerator": ratio.get("numerator"),
        "denominator": ratio.get("denominator"),
        "percent": ratio.get("percent"),
    }


def _compare_ratio(
    base_ratio: dict[str, Any] | None,
    head_ratio: dict[str, Any] | None,
    tolerance: float,
    *,
    higher_is_worse: bool,
) -> dict[str, Any]:
    """Compare two ratios; a ``null`` percent on either side is not comparable."""
    base_pct = base_ratio["percent"] if base_ratio else None
    head_pct = head_ratio["percent"] if head_ratio else None
    comparable = base_pct is not None and head_pct is not None
    delta = round(head_pct - base_pct, 2) if comparable else None
    if not comparable:
        worsening = None
    elif higher_is_worse:
        worsening = round(head_pct - base_pct, 2)
    else:
        worsening = round(base_pct - head_pct, 2)
    return {
        "base": base_ratio,
        "head": head_ratio,
        "comparable": comparable,
        "delta_percent": delta,
        "worsening_points": worsening,
        "regression": bool(comparable and worsening is not None and worsening > tolerance),
    }


def _compare_ratios(
    base: SideSnapshot, head: SideSnapshot, tolerance: float
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    sections: dict[str, Any] = {}
    regressed: list[tuple[str, dict[str, Any]]] = []
    for section, key, label, higher_is_worse in _RATIOS:
        base_block = base.coverage.get(section) if base.coverage else None
        head_block = head.coverage.get(section) if head.coverage else None
        comparison = _compare_ratio(
            _ratio_block(base_block, key),
            _ratio_block(head_block, key),
            tolerance,
            higher_is_worse=higher_is_worse,
        )
        sections.setdefault(section, {})[key] = comparison
        if comparison["regression"]:
            regressed.append((label, comparison))
    return sections, regressed


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _ratio_percent(comparison: dict[str, Any], side: str) -> float | None:
    ratio = comparison.get(side)
    return ratio.get("percent") if isinstance(ratio, dict) else None


def _build_reasons(
    base: SideSnapshot,
    head: SideSnapshot,
    new_diagnostics: tuple[dict[str, Any], ...],
    regressed: list[tuple[str, dict[str, Any]]],
    tolerance: float,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    new_errors = [
        item for item in new_diagnostics if item.get("severity") == Severity.ERROR.value
    ]
    if new_errors:
        reasons.append(
            {
                "code": "new_errors",
                "message": f"{len(new_errors)} new error diagnostic(s)",
                "items": [_diagnostic_label(item) for item in new_errors],
            }
        )
    dangling = set(dangling_codes())
    new_dangling = [item for item in new_errors if item.get("code") in dangling]
    if head.dangling_count > base.dangling_count or new_dangling:
        reasons.append(
            {
                "code": "new_dangling",
                "message": f"dangling references {base.dangling_count} -> {head.dangling_count}",
                "items": [_diagnostic_label(item) for item in new_dangling],
            }
        )
    added_orphans = sorted(set(head.orphan_case_ids) - set(base.orphan_case_ids))
    if added_orphans:
        reasons.append(
            {
                "code": "new_orphan",
                "message": f"{len(added_orphans)} new orphan case(s)",
                "items": added_orphans,
            }
        )
    coverage_drops = [item for item in regressed if not item[0].startswith("orphan")]
    if coverage_drops:
        reasons.append(
            {
                "code": "coverage_drop",
                "message": (
                    f"{len(coverage_drops)} coverage metric(s) dropped by more than "
                    f"{tolerance:g} point(s)"
                ),
                "items": [
                    f"{label}: {_pct(_ratio_percent(comparison, 'base'))} -> "
                    f"{_pct(_ratio_percent(comparison, 'head'))}"
                    for label, comparison in coverage_drops
                ],
            }
        )
    orphan_rates = [item for item in regressed if item[0].startswith("orphan")]
    if orphan_rates:
        reasons.append(
            {
                "code": "orphan_rate",
                "message": (
                    f"orphan rate rose by more than {tolerance:g} point(s)"
                ),
                "items": [
                    f"{label}: {_pct(_ratio_percent(comparison, 'base'))} -> "
                    f"{_pct(_ratio_percent(comparison, 'head'))}"
                    for label, comparison in orphan_rates
                ],
            }
        )
    return reasons


def _gap_block(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not block:
        return None
    return {
        "count": block.get("count"),
        "uncovered_requirement_count": block.get("uncovered_requirement_count"),
        "uncovered_requirements": list(block.get("uncovered_requirements") or []),
        "cases_without_requirement_root": list(
            block.get("cases_without_requirement_root") or []
        ),
    }


def _gap_lists(block: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if not block:
        return [], []
    return (
        list(block.get("uncovered_requirements") or []),
        list(block.get("cases_without_requirement_root") or []),
    )


def _resolve_tolerance(
    head_result: CheckResult, explicit: float | None
) -> tuple[float, str]:
    """Return ``(tolerance, source)``; CLI beats project config beats the default."""
    if explicit is not None:
        value = float(explicit)
        if value < 0:
            raise DiffInputError(
                "--coverage-tolerance must be zero or positive", field="coverage-tolerance"
            )
        return value, "cli"
    config = head_result.project.config if head_result.project is not None else None
    raw = None if config is None else config.thresholds.get(TOLERANCE_KEY)
    if raw is None:
        return DEFAULT_COVERAGE_TOLERANCE, "default"
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise DiffInputError(
            f"thresholds.{TOLERANCE_KEY} must be a non-negative number",
            field=f"thresholds.{TOLERANCE_KEY}",
        )
    return float(raw), "project"


def _tool_block() -> dict[str, str]:
    from . import __version__

    return {"name": "qa_trace", "version": __version__}


@dataclass(frozen=True, slots=True)
class DiffResult:
    """The outcome of one ``qa trace diff``.

    ``document`` is the stable JSON shape; the dataclass only carries it so the
    text renderer and the exit code cannot disagree with the JSON.
    """

    document: dict[str, Any]

    @property
    def regression(self) -> bool:
        """Whether the head side made the library worse."""
        return bool(self.document.get("regression"))

    @property
    def exit_code(self) -> int:
        """The process exit code: 0 clean, 1 regression (2 is raised, never returned)."""
        return int(self.document.get("exit_code") or 0)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this diff."""
        return self.document


def compute_diff(
    project_root: str | Path,
    base: str,
    *,
    coverage_tolerance: float | None = None,
    repository: RepoContext | None = None,
) -> DiffResult:
    """Compare the project at ``base`` with the worktree copy of the project."""
    project_dir = Path(project_root)
    if not project_dir.is_dir():
        raise ProjectError(f"project directory not found: {project_dir}", path=project_dir)
    context = repository if repository is not None else find_repository(project_dir)
    base_commit = resolve_commit(context, base)
    head = head_commit(context)
    _require_project_at(context, base_commit)

    head_result = run_check(project_dir)
    tolerance, tolerance_source = _resolve_tolerance(head_result, coverage_tolerance)
    head_snapshot = _snapshot(build_report(head_result))

    with tempfile.TemporaryDirectory(prefix="qa-trace-diff-") as tmp:
        base_root = materialize_tree(context, base_commit, Path(tmp))
        base_report = build_report(run_check(base_root))
    base_snapshot = _snapshot(base_report)

    project_id = (
        head_result.project.config.project_id
        if head_result.project is not None
        else (base_report.get("project") or {}).get("id")
    )

    base_keys = {_diagnostic_key(item) for item in base_snapshot.diagnostics}
    head_keys = {_diagnostic_key(item) for item in head_snapshot.diagnostics}
    new_diagnostics = tuple(
        item for item in head_snapshot.diagnostics if _diagnostic_key(item) not in base_keys
    )
    resolved_diagnostics = tuple(
        item for item in base_snapshot.diagnostics if _diagnostic_key(item) not in head_keys
    )

    coverage, regressed = _compare_ratios(base_snapshot, head_snapshot, tolerance)
    reasons = _build_reasons(base_snapshot, head_snapshot, new_diagnostics, regressed, tolerance)

    count_keys = sorted(set(base_snapshot.counts) | set(head_snapshot.counts))
    counts = {
        "base": base_snapshot.counts,
        "head": head_snapshot.counts,
        "delta": {
            key: int(head_snapshot.counts.get(key) or 0)
            - int(base_snapshot.counts.get(key) or 0)
            for key in count_keys
        },
    }

    base_gaps = _gap_block(base_snapshot.requirement_gaps)
    head_gaps = _gap_block(head_snapshot.requirement_gaps)
    base_uncovered, base_without_req = _gap_lists(base_snapshot.requirement_gaps)
    head_uncovered, head_without_req = _gap_lists(head_snapshot.requirement_gaps)
    gaps = {
        "base": base_gaps,
        "head": head_gaps,
        "new_uncovered_requirements": sorted(set(head_uncovered) - set(base_uncovered)),
        "resolved_uncovered_requirements": sorted(set(base_uncovered) - set(head_uncovered)),
        "new_cases_without_requirement_root": sorted(
            set(head_without_req) - set(base_without_req)
        ),
        "resolved_cases_without_requirement_root": sorted(
            set(base_without_req) - set(head_without_req)
        ),
    }

    added_rechecks = sorted(
        set(head_snapshot.needs_recheck) - set(base_snapshot.needs_recheck)
    )
    rechecks = {
        "base": list(base_snapshot.needs_recheck),
        "head": list(head_snapshot.needs_recheck),
        "added": added_rechecks,
        "removed": sorted(set(base_snapshot.needs_recheck) - set(head_snapshot.needs_recheck)),
    }

    added_orphans = sorted(
        set(head_snapshot.orphan_case_ids) - set(base_snapshot.orphan_case_ids)
    )
    orphans = {
        "base": list(base_snapshot.orphan_case_ids),
        "head": list(head_snapshot.orphan_case_ids),
        "added": added_orphans,
        "removed": sorted(
            set(base_snapshot.orphan_case_ids) - set(head_snapshot.orphan_case_ids)
        ),
        "counts": {
            "base": len(base_snapshot.orphan_case_ids),
            "head": len(head_snapshot.orphan_case_ids),
        },
    }

    document: dict[str, Any] = {
        "diff_version": DIFF_VERSION,
        "tool": _tool_block(),
        "project": {
            "id": project_id,
            "root": project_dir.as_posix(),
            "repo_root": context.root.as_posix(),
            "path_in_repo": context.selector,
        },
        "base": {
            "ref": base,
            "commit": base_commit,
            "valid": base_snapshot.valid,
            "metrics_available": base_snapshot.coverage is not None,
            "metrics_suppressed": base_snapshot.metrics_suppressed,
            "counts": base_snapshot.counts,
            "dangling_count": base_snapshot.dangling_count,
        },
        "head": {
            "commit": head,
            "valid": head_snapshot.valid,
            "metrics_available": head_snapshot.coverage is not None,
            "metrics_suppressed": head_snapshot.metrics_suppressed,
            "counts": head_snapshot.counts,
            "dangling_count": head_snapshot.dangling_count,
        },
        "tolerance": {"coverage_points": tolerance, "source": tolerance_source},
        "regression": bool(reasons),
        "exit_code": 1 if reasons else 0,
        "reasons": reasons,
        "diagnostics": {
            "new": list(new_diagnostics),
            "resolved": list(resolved_diagnostics),
            "unchanged_count": len(head_snapshot.diagnostics) - len(new_diagnostics),
            "counts": {
                "base": len(base_snapshot.diagnostics),
                "head": len(head_snapshot.diagnostics),
            },
        },
        "counts": counts,
        "coverage": coverage,
        "dangling": {
            "base": base_snapshot.dangling_count,
            "head": head_snapshot.dangling_count,
            "delta": head_snapshot.dangling_count - base_snapshot.dangling_count,
            "new": head_snapshot.dangling_count > base_snapshot.dangling_count,
        },
        "orphan": orphans,
        "requirement_gaps": gaps,
        "needs_recheck": rechecks,
    }
    return DiffResult(document=document)


def _short_commit(commit: Any) -> str:
    if not isinstance(commit, str) or not commit:
        return "uncommitted"
    return commit[:8]


def _side_line(label: str, block: dict[str, Any]) -> str:
    counts = block.get("counts") or {}
    state = "valid" if block.get("valid") else "INVALID"
    return (
        f"  {label:<26}{state}  "
        f"{counts.get('sources', 0)} source(s), "
        f"{counts.get('testpoints', 0)} testpoint(s), "
        f"{counts.get('cases', 0)} case(s) "
        f"({counts.get('reviewed_cases', 0)} reviewed)"
    )


def _ratio_line(label: str, comparison: dict[str, Any]) -> str:
    base_text = _pct(_ratio_percent(comparison, "base"))
    head_text = _pct(_ratio_percent(comparison, "head"))
    delta = comparison.get("delta_percent")
    if not comparison.get("comparable"):
        detail = "not comparable"
    else:
        detail = f"{delta:+.2f} pt"
    mark = "  REGRESSED" if comparison.get("regression") else ""
    return f"  {label:<26}{base_text} -> {head_text}  ({detail}){mark}"


def render_diff(result: DiffResult) -> str:
    """Render a diff document as aligned plain text."""
    document = result.document
    project = document.get("project") or {}
    base = document.get("base") or {}
    head = document.get("head") or {}
    identifier = project.get("id") or "<unknown>"
    lines = [
        f"qa-trace diff: {identifier}  "
        f"{base.get('ref') or '?'} ({_short_commit(base.get('commit'))}) -> "
        f"{_short_commit(head.get('commit'))}"
    ]
    lines.append(_side_line("base", base))
    lines.append(_side_line("head", head))

    coverage = document.get("coverage") or {}
    for section, key, label, _higher_is_worse in _RATIOS:
        comparison = (coverage.get(section) or {}).get(key)
        if comparison is not None:
            lines.append(_ratio_line(label, comparison))

    dangling = document.get("dangling") or {}
    lines.append(
        f"  {'dangling refs':<26}{dangling.get('base')} -> {dangling.get('head')}  "
        f"({int(dangling.get('delta') or 0):+d}){'  NEW' if dangling.get('new') else ''}"
    )
    orphan = document.get("orphan") or {}
    lines.append(
        f"  {'orphan cases':<26}{len(orphan.get('base') or [])} -> "
        f"{len(orphan.get('head') or [])}  (+{len(orphan.get('added') or [])})"
    )
    diagnostics = document.get("diagnostics") or {}
    lines.append(
        f"  {'diagnostics':<26}+{len(diagnostics.get('new') or [])} new, "
        f"-{len(diagnostics.get('resolved') or [])} resolved, "
        f"{diagnostics.get('unchanged_count', 0)} unchanged"
    )
    rechecks = document.get("needs_recheck") or {}
    lines.append(
        f"  {'needs re-check':<26}{len(rechecks.get('base') or [])} -> "
        f"{len(rechecks.get('head') or [])}  (+{len(rechecks.get('added') or [])})"
    )
    gaps = document.get("requirement_gaps") or {}
    lines.append(
        f"  {'requirement gaps':<26}{_gap_text(gaps.get('base'))} -> "
        f"{_gap_text(gaps.get('head'))}  "
        f"(+{len(gaps.get('new_uncovered_requirements') or [])} uncovered requirement(s))"
    )
    tolerance = document.get("tolerance") or {}
    lines.append(
        f"  {'tolerance':<26}{float(tolerance.get('coverage_points') or 0):g} point(s) "
        f"({tolerance.get('source')})"
    )

    reasons = document.get("reasons") or []
    if document.get("regression"):
        lines.append(
            f"  {'regression':<26}YES ({len(reasons)} reason(s)), exit {result.exit_code}"
        )
        for reason in reasons:
            lines.append(f"    {reason['code']}: {reason['message']}")
            for item in reason.get("items") or []:
                lines.append(f"      {item}")
    else:
        lines.append(f"  {'regression':<26}no, exit 0")
    return "\n".join(lines)


def _gap_text(block: dict[str, Any] | None) -> str:
    if not block:
        return "N/A"
    return (
        f"{block.get('count', 0)} case(s) / "
        f"{block.get('uncovered_requirement_count', 0)} uncovered"
    )


__all__ = [
    "DEFAULT_COVERAGE_TOLERANCE",
    "DIFF_VERSION",
    "TOLERANCE_KEY",
    "DiffResult",
    "RepoContext",
    "compute_diff",
    "find_repository",
    "head_commit",
    "materialize_tree",
    "render_diff",
    "resolve_commit",
]
