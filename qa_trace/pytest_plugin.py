"""P2 pytest plugin: the ``case`` marker and run-manifest recording.

The plugin has two jobs:

1. **Marker validation.**  ``@pytest.mark.case("TC-...")`` links a test to one or
   more cases of the qa-trace library.  Arguments must be canonical ``TC-*`` IDs;
   with ``--qa-project`` they must also be cases the library defines.  A bad ID
   aborts collection with a usage error (exit code 4), so a typo can never
   silently produce an empty run record.
2. **Run recording.**  With ``--qa-project`` and/or ``--qa-run-dir`` the plugin
   writes ``runs/<run_id>/manifest.json`` after the session: outcomes per pytest
   node, a per-case aggregate (a failing parameter never aggregates to a pass),
   the frozen library snapshot, the collected-script digest and the git commit
   when one is available.  The write is atomic (:func:`qa_trace.runs.write_manifest`),
   and an interrupted session is recorded as ``incomplete`` rather than as a
   success.

The plugin never imports the project's test modules itself and never runs
pytest collection on its own; it only annotates the session the user already
started.  Without either option it registers the marker and validates IDs, and
writes nothing.

Installation: ``pyproject.toml`` declares the ``pytest11`` entry point, so a
``pip install -e .`` activates the plugin for every pytest run.  Until the
package is reinstalled (P2 deliberately does not trigger the WebUI build), load
it explicitly: ``pytest -p qa_trace.pytest_plugin ...``.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from . import __version__
from .diagnostics import from_error
from .errors import QaTraceError
from .ids import IdKind, ensure_kind
from .loader import Project, scan_project
from .markers import MARKER_NAME
from .models import FailureStage, Outcome
from .runs import (
    NodeResult,
    build_manifest,
    run_status,
    truncate_error,
    write_manifest,
)

#: Directory created under the project (or the run directory option).
RUNS_DIRNAME = "runs"

#: File name inside ``runs/<run_id>/``.
MANIFEST_FILENAME = "manifest.json"

_STATE_KEY = pytest.StashKey["_PluginState"]()

_FAILURE_STAGE_BY_WHEN: dict[str, FailureStage] = {
    "setup": FailureStage.SETUP,
    "call": FailureStage.CALL,
    "teardown": FailureStage.TEARDOWN,
}


@dataclass
class _NodeRun:
    """Accumulated reports for one pytest node."""

    nodeid: str
    case_ids: tuple[str, ...]
    started: float | None = None
    finished: float | None = None
    duration: float = 0.0
    outcome: Outcome | None = None
    stage: FailureStage | None = None
    summary: str | None = None


@dataclass
class _PluginState:
    """Per-session state; a nested pytest run gets its own instance."""

    project: Project | None = None
    project_path: Path | None = None
    run_dir: Path | None = None
    recording: bool = False
    aborted: bool = False
    run_id: str = ""
    started_at: datetime | None = None
    code_commit: str | None = None
    asset_snapshot: dict[str, Any] = field(default_factory=dict)
    script_digest: dict[str, Any] | None = None
    case_ids_by_nodeid: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    nodes: dict[str, _NodeRun] = field(default_factory=dict)
    rootdir: str | None = None
    args: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_run_id(moment: datetime) -> str:
    stamp = moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:  # pragma: no cover - a vanished file is not worth failing a run
        return None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.resolve().as_posix()


def _git_commit(path: Path | None) -> str | None:
    """Return the current commit of ``path``, or ``None`` when git is unavailable."""
    if path is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip().lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        return None
    return commit


def _snapshot_library(project: Project) -> dict[str, Any]:
    """Freeze the library as content digests plus the case relations.

    Plan section 3.5: the manifest is frozen before the run, and a workspace
    without Git identifies its snapshot by content digest rather than a fake
    commit.  Full file bodies are deliberately not copied here.

    P3 adds ``testpoint_sources`` so ``qa trace failure`` can resolve a case all
    the way up to its sources from the run-time snapshot instead of today's
    library.
    """
    def digest(entity_id: str) -> str | None:
        path = project.files.get(entity_id)
        return _sha256(path) if path is not None else None

    return {
        "project_id": project.config.project_id,
        "root": str(project.root),
        "sources": {key: digest(key) for key in sorted(project.sources)},
        "testpoints": {key: digest(key) for key in sorted(project.testpoints)},
        "cases": {key: digest(key) for key in sorted(project.cases)},
        "relations": {
            case_id: {
                "testpoints": list(project.cases[case_id].testpoints),
                "sources": list(project.cases[case_id].sources),
            }
            for case_id in sorted(project.cases)
        },
        "testpoint_sources": {
            testpoint_id: list(project.testpoints[testpoint_id].sources)
            for testpoint_id in sorted(project.testpoints)
        },
    }


def _script_digest(items: list[pytest.Item], rootpath: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    for item in items:
        path = getattr(item, "path", None)
        if path is None:  # pragma: no cover - very old pytest item shapes
            continue
        candidate = Path(path)
        if not candidate.is_file():
            continue
        key = _relative(candidate, rootpath)
        if key in files:
            continue
        digest = _sha256(candidate)
        if digest is not None:
            files[key] = digest
    if not files:
        return {"sha256": None, "files": {}}
    combined = hashlib.sha256()
    for key in sorted(files):
        combined.update(key.encode("utf-8"))
        combined.update(b"\0")
        combined.update(files[key].encode("ascii"))
    return {"sha256": combined.hexdigest(), "files": dict(sorted(files.items()))}


def _terminal_reporter(session: pytest.Session) -> Any:
    return session.config.pluginmanager.get_plugin("terminalreporter")


def _write_line(session: pytest.Session, message: str, *, red: bool = False) -> None:
    reporter = _terminal_reporter(session)
    if reporter is not None:
        reporter.write_line(message, red=red)
    else:  # pragma: no cover - only without the terminal plugin
        print(message, file=sys.stderr if red else sys.stdout)


def _report_summary(report: Any) -> str | None:
    text = getattr(report, "longreprtext", None)
    if not text:
        text = str(getattr(report, "longrepr", "") or "")
    return truncate_error(text or None)


def _apply_report(node: _NodeRun, report: Any) -> None:
    """Fold one pytest phase report into the accumulated node outcome."""
    start = getattr(report, "start", None)
    stop = getattr(report, "stop", None)
    if start is not None and (node.started is None or start < node.started):
        node.started = start
    if stop is not None and (node.finished is None or stop > node.finished):
        node.finished = stop
    node.duration += float(getattr(report, "duration", 0.0) or 0.0)

    wasxfail = getattr(report, "wasxfail", None)
    when = getattr(report, "when", "")
    stage = _FAILURE_STAGE_BY_WHEN.get(when)

    if when == "setup":
        if report.failed:
            node.outcome = Outcome.ERROR
            node.stage = stage
            node.summary = _report_summary(report)
        elif report.skipped:
            node.outcome = Outcome.XFAILED if wasxfail else Outcome.SKIPPED
            node.stage = None
            node.summary = _report_summary(report)
        return
    if when == "call":
        if report.failed:
            if wasxfail:
                # A strict xpass: the test passed although it was expected to fail.
                node.outcome = Outcome.XPASSED
                node.stage = None
                node.summary = None
            else:
                node.outcome = Outcome.FAILED
                node.stage = stage
                node.summary = _report_summary(report)
        elif report.skipped:
            node.outcome = Outcome.XFAILED if wasxfail else Outcome.SKIPPED
            node.stage = None
            node.summary = _report_summary(report)
        elif report.passed:
            node.outcome = Outcome.XPASSED if wasxfail else Outcome.PASSED
            node.stage = None
            node.summary = None
        return
    if when == "teardown" and report.failed:
        node.outcome = Outcome.ERROR
        node.stage = stage
        node.summary = _report_summary(report)


def _as_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the two qa-trace command line options."""
    group = parser.getgroup("qa-trace", "qa-trace run recording")
    group.addoption(
        "--qa-project",
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "qa-trace project directory (projects/<project-id>); validates marker "
            "case IDs against the library and defaults the run directory to <project>/runs"
        ),
    )
    group.addoption(
        "--qa-run-dir",
        action="store",
        default=None,
        metavar="DIR",
        help="directory receiving runs/<run_id>/manifest.json (default: <project>/runs)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker, load the library and decide where runs are recorded."""
    config.addinivalue_line(
        "markers",
        f"{MARKER_NAME}(*case_ids): link a test to qa-trace case IDs (TC-...)",
    )
    project_option = config.getoption("qa_project")
    run_dir_option = config.getoption("qa_run_dir")
    state = _PluginState(
        project_path=(
            Path(project_option).expanduser().resolve() if project_option else None
        ),
        rootdir=str(config.rootpath),
        args=[str(argument) for argument in config.invocation_params.args],
    )
    if state.project_path is not None:
        outcome = scan_project(state.project_path)
        if outcome.project is None:
            lines = [
                from_error(error, root=state.project_path).format()
                for error in outcome.errors
            ]
            raise pytest.UsageError(
                "qa_trace cannot load the project library:\n" + "\n".join(lines)
            )
        state.project = outcome.project
    if run_dir_option is not None:
        state.run_dir = Path(run_dir_option).expanduser().resolve()
        state.recording = True
    elif state.project_path is not None:
        state.run_dir = state.project_path / RUNS_DIRNAME
        state.recording = True
    config.stash[_STATE_KEY] = state


def pytest_sessionstart(session: pytest.Session) -> None:
    """Freeze the run identity and the library snapshot before any test runs."""
    state = session.config.stash.get(_STATE_KEY, None)
    if state is None:
        return
    state.started_at = _utcnow()
    state.run_id = _new_run_id(state.started_at)
    state.code_commit = _git_commit(state.project_path or Path.cwd())
    if state.project is not None:
        state.asset_snapshot = _snapshot_library(state.project)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Validate every ``case`` marker and remember the case IDs per node."""
    state = config.stash.get(_STATE_KEY, None)
    if state is None:
        return
    known = set(state.project.cases) if state.project is not None else None
    problems: list[str] = []
    for item in items:
        case_ids: list[str] = []
        for marker in item.iter_markers(name=MARKER_NAME):
            for raw in marker.args:
                if not isinstance(raw, str) or not raw.strip():
                    problems.append(
                        f"{item.nodeid}: @pytest.mark.case arguments must be "
                        "non-empty strings"
                    )
                    continue
                try:
                    parsed = ensure_kind(raw.strip(), IdKind.CASE)
                except QaTraceError as exc:
                    problems.append(f"{item.nodeid}: {exc.message}")
                    continue
                if known is not None and parsed.value not in known:
                    problems.append(
                        f"{item.nodeid}: unknown case id {parsed.value!r}"
                    )
                    continue
                if parsed.value not in case_ids:
                    case_ids.append(parsed.value)
        state.case_ids_by_nodeid[item.nodeid] = tuple(case_ids)
        if not case_ids:
            state.unmapped.append(item.nodeid)
    if problems:
        state.aborted = True
        raise pytest.UsageError(
            "qa_trace marker errors:\n" + "\n".join(sorted(problems))
        )


def pytest_collection_finish(session: pytest.Session) -> None:
    """Digest the collected test files, so the manifest can name the scripts."""
    state = session.config.stash.get(_STATE_KEY, None)
    if state is None or not state.recording:
        return
    state.script_digest = _script_digest(session.items, session.config.rootpath)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: Any) -> Any:
    """Record the final report of each phase; ``wasxfail`` only exists here."""
    outcome = yield
    report = outcome.get_result()
    state = item.config.stash.get(_STATE_KEY, None)
    if state is None or not state.recording or state.aborted:
        return
    if getattr(report, "when", "") not in _FAILURE_STAGE_BY_WHEN:
        return
    case_ids = state.case_ids_by_nodeid.get(item.nodeid, ())
    if not case_ids:
        return
    node = state.nodes.get(item.nodeid)
    if node is None:
        node = _NodeRun(nodeid=item.nodeid, case_ids=case_ids)
        state.nodes[item.nodeid] = node
    _apply_report(node, report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Publish the run manifest once, atomically, after the session."""
    state = session.config.stash.get(_STATE_KEY, None)
    if state is None or not state.recording or state.aborted:
        return
    if int(exitstatus) == int(pytest.ExitCode.USAGE_ERROR):
        # Collection was rejected; there is no run worth recording.
        return
    if state.run_dir is None:  # pragma: no cover - recording implies a run dir
        return
    finished_at = _utcnow()
    started_at = state.started_at or finished_at
    results = [
        NodeResult(
            nodeid=node.nodeid,
            case_ids=node.case_ids,
            outcome=node.outcome or Outcome.CANCELLED,
            started_at=_as_datetime(node.started),
            finished_at=_as_datetime(node.finished),
            duration_ms=max(0, round(node.duration * 1000)),
            failure_stage=node.stage,
            error_summary=node.summary,
        )
        for node in state.nodes.values()
    ]
    manifest = build_manifest(
        run_id=state.run_id or _new_run_id(finished_at),
        project_id=(
            state.project.config.project_id
            if state.project is not None
            else "unknown"
        ),
        project_path=str(state.project_path) if state.project_path else None,
        status=run_status(
            exitstatus, collect_only=bool(session.config.option.collectonly)
        ),
        exitstatus=int(exitstatus),
        started_at=started_at,
        finished_at=finished_at,
        environment=f"{sys.platform}/python-{platform.python_version()}",
        tool_version=__version__,
        code_commit=state.code_commit,
        asset_snapshot=state.asset_snapshot,
        script_digest=state.script_digest,
        results=results,
        unmapped_nodeids=state.unmapped,
        collected=len(state.case_ids_by_nodeid),
        pytest_version=pytest.__version__,
        rootdir=state.rootdir,
        args=state.args,
    )
    target = state.run_dir / manifest["run_id"] / MANIFEST_FILENAME
    try:
        write_manifest(target, manifest)
    except OSError as exc:
        _write_line(session, f"qa-trace could not write {target}: {exc}", red=True)
        return
    _write_line(session, f"qa-trace run manifest: {target}")


__all__ = [
    "MANIFEST_FILENAME",
    "MARKER_NAME",
    "RUNS_DIRNAME",
    "pytest_addoption",
    "pytest_collection_finish",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_runtest_makereport",
    "pytest_sessionfinish",
    "pytest_sessionstart",
]
