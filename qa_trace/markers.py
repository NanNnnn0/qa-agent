"""Static ``@pytest.mark.case(...)`` lint (spec section 3, rule 9).

The case YAML is the single source of truth: an automated case declares
``automation.script: <file>::<nodeid>`` and the script declares the case back
with ``@pytest.mark.case("TC-...")``.  ``qa trace check`` reads the target file
with :mod:`ast` and never imports or executes test code (plan section 4: the fast
check is static), then reports both directions of a disagreement:

* the case is automated by a script that carries no marker for it
  (``TRACE_MARKER_MISMATCH``),
* a marker names a case that does not bind this file
  (``TRACE_MARKER_ORPHAN``),
* a marker names a malformed ID or an ID that is not a case of this project
  (``TRACE_MARKER_UNKNOWN``).

A target file that cannot be read or parsed is ``TRACE_MARKER_UNREADABLE``.  The
plan calls the whole family ``TRACE_MARKER_MISMATCH``; the three narrower codes
are what the CLI emits so that the failing side is obvious from the code alone.

Only files that some automated case binds are scanned.  A marker that sits in a
file no case points at is invisible to this check; proving that needs a pytest
collection, which the fast check deliberately does not run.  Everything here is
derived: no YAML or Python file is modified.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .bindings import ScriptTarget, resolve_script_target
from .diagnostics import Diagnostic, Severity, relative_path, sort_diagnostics
from .errors import QaTraceError
from .ids import IdKind, ensure_kind
from .loader import Project
from .models import AutomationStatus, Case, ScriptBinding

#: Spec rule number implemented by this module.
MARKER_RULE_NUMBER = 9

#: An automated case has no marker for itself in its script.
MARKER_MISMATCH = "TRACE_MARKER_MISMATCH"
#: A marker names a case that does not bind the file it sits in.
MARKER_ORPHAN = "TRACE_MARKER_ORPHAN"
#: A marker names a malformed ID or an ID the project does not define.
MARKER_UNKNOWN = "TRACE_MARKER_UNKNOWN"
#: A bound script cannot be read or parsed, so its markers cannot be checked.
MARKER_UNREADABLE = "TRACE_MARKER_UNREADABLE"

#: Every code this module can emit, in documentation order.
MARKER_CODES: tuple[str, ...] = (
    MARKER_MISMATCH,
    MARKER_ORPHAN,
    MARKER_UNKNOWN,
    MARKER_UNREADABLE,
)

#: The pytest marker name the plugin and the lint share.
MARKER_NAME = "case"


@dataclass(frozen=True, slots=True)
class CaseMarker:
    """One ``@pytest.mark.case(...)`` decorator found by the AST scan."""

    nodeid: str
    case_ids: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    line: int = 0


@dataclass(frozen=True, slots=True)
class MarkerScan:
    """The markers and function nodeids of one Python file."""

    path: Path
    markers: tuple[CaseMarker, ...] = ()
    defined_nodeids: tuple[str, ...] = ()
    error: str | None = None

    @property
    def case_ids(self) -> tuple[str, ...]:
        """Every valid case ID named by a marker, in source order."""
        seen: list[str] = []
        for marker in self.markers:
            for case_id in marker.case_ids:
                if case_id not in seen:
                    seen.append(case_id)
        return tuple(seen)

    def markers_for(self, case_id: str) -> tuple[CaseMarker, ...]:
        """Return the markers that name ``case_id``."""
        return tuple(
            marker for marker in self.markers if case_id in marker.case_ids
        )

    def nodeids_for(self, case_id: str) -> tuple[str, ...]:
        """Return the nodeids whose markers name ``case_id``."""
        return tuple(
            dict.fromkeys(marker.nodeid for marker in self.markers_for(case_id))
        )


def _is_case_marker(node: ast.expr) -> bool:
    """Return whether ``node`` is the ``pytest.mark.case`` attribute chain."""
    if not isinstance(node, ast.Attribute) or node.attr != MARKER_NAME:
        return False
    owner = node.value
    if not isinstance(owner, ast.Attribute) or owner.attr != "mark":
        return False
    base = owner.value
    return isinstance(base, ast.Name) and base.id == "pytest"


def _case_marker_args(node: ast.expr) -> tuple[ast.expr, ...] | None:
    """Return the marker arguments, or ``None`` when ``node`` is not a marker."""
    if isinstance(node, ast.Call) and _is_case_marker(node.func):
        return tuple(node.args)
    if _is_case_marker(node):
        # ``@pytest.mark.case`` without a call: the marker carries no ID.
        return ()
    return None


def _describe(node: ast.expr) -> str:
    """Return a short readable form of an AST expression."""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is best effort
        return type(node).__name__


def _read_case_args(
    args: tuple[ast.expr, ...], keywords: tuple[ast.keyword, ...] = ()
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split marker arguments into canonical case IDs and invalid notes."""
    case_ids: list[str] = []
    invalid: list[str] = []
    for argument in args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            text = argument.value.strip()
            if not text:
                invalid.append("an empty case ID")
                continue
            try:
                parsed = ensure_kind(text, IdKind.CASE)
            except QaTraceError:
                invalid.append(f"{text!r} is not a valid case ID")
                continue
            if parsed.value not in case_ids:
                case_ids.append(parsed.value)
        else:
            invalid.append(f"{_describe(argument)} is not a literal case ID")
    for keyword in keywords:
        invalid.append(f"keyword argument {keyword.arg!r} is not supported")
    if not args and not keywords:
        invalid.append("@pytest.mark.case needs at least one case ID")
    return tuple(case_ids), tuple(invalid)


def _walk_body(
    body: list[ast.stmt],
    prefix: tuple[str, ...],
    markers: list[CaseMarker],
    defined: list[str],
) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            _walk_body(node.body, (*prefix, node.name), markers, defined)
            continue
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodeid = "::".join((*prefix, node.name))
        defined.append(nodeid)
        for decorator in node.decorator_list:
            args = _case_marker_args(decorator)
            if args is None:
                continue
            keywords = (
                tuple(decorator.keywords) if isinstance(decorator, ast.Call) else ()
            )
            case_ids, invalid = _read_case_args(args, keywords)
            markers.append(
                CaseMarker(
                    nodeid=nodeid,
                    case_ids=case_ids,
                    invalid=invalid,
                    line=getattr(decorator, "lineno", 0),
                )
            )


def scan_markers(path: str | Path) -> MarkerScan:
    """Read one Python file and return its ``case`` markers without importing it."""
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return MarkerScan(path=source_path, error=f"cannot read the file: {exc}")
    try:
        tree = ast.parse(text, filename=str(source_path))
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return MarkerScan(
            path=source_path, error=f"cannot parse the file ({location}): {exc.msg}"
        )
    markers: list[CaseMarker] = []
    defined: list[str] = []
    _walk_body(tree.body, (), markers, defined)
    return MarkerScan(
        path=source_path, markers=tuple(markers), defined_nodeids=tuple(defined)
    )


def normalize_nodeid(nodeid: str) -> str:
    """Drop a parametrisation suffix so ``test_x[1]`` matches ``test_x``."""
    text = nodeid.strip()
    if "[" in text:
        text = text.split("[", 1)[0]
    return text.strip()


def _case_path(project: Project, case: Case) -> str | None:
    return relative_path(project.files.get(case.id), project.root)


def _error(
    code: str, message: str, *, path: str | None, field: str | None, entity_id: str | None,
    suggestion: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        path=path,
        field=field,
        entity_id=entity_id,
        suggestion=suggestion,
    )


def _orphan_reason(
    project: Project, case: Case, target: ScriptTarget | None, script_path: str
) -> str:
    if case.automation.status is not AutomationStatus.DONE:
        return (
            f"case {case.id} is not automated "
            f"(automation.status={case.automation.status.value})"
        )
    binding = case.automation.script
    if binding is None:
        return f"case {case.id} has no automation.script"
    if target is None or not target.ok:
        return (
            f"case {case.id} binds {binding.script!r}, which does not resolve"
        )
    return (
        f"case {case.id} binds {binding.script!r}, not {script_path}"
    )


def _check_case_markers(
    project: Project,
    case: Case,
    scan: MarkerScan,
    binding: ScriptBinding,
    diagnostics: list[Diagnostic],
) -> None:
    """Require the bound case to carry its own marker in the bound script."""
    if not scan.nodeids_for(case.id):
        diagnostics.append(
            _error(
                MARKER_MISMATCH,
                (
                    f"case {case.id} is automated by {binding.script!r} "
                    f"but that file has no @pytest.mark.case({case.id!r}) marker"
                ),
                path=_case_path(project, case),
                field="automation.script",
                entity_id=case.id,
                suggestion=(
                    "add the marker to the bound test, or point automation.script at "
                    "the test that carries it"
                ),
            )
        )
        return
    expected = normalize_nodeid(binding.nodeid)
    defined = {normalize_nodeid(item) for item in scan.defined_nodeids}
    if expected not in defined:
        # The binding is not a plain function of this file (dynamic generation,
        # plugin-provided items, ...); the file-level marker is the best a static
        # check can prove.  Collection would be needed to go further.
        return
    attached = {
        normalize_nodeid(item) for item in scan.nodeids_for(case.id)
    }
    if expected in attached:
        return
    where = ", ".join(sorted({marker.nodeid for marker in scan.markers_for(case.id)}))
    diagnostics.append(
        _error(
            MARKER_MISMATCH,
            (
                f"the marker for {case.id} sits on {where}, but automation.script "
                f"binds {binding.nodeid!r}"
            ),
            path=_case_path(project, case),
            field="automation.script",
            entity_id=case.id,
            suggestion="move the marker onto the bound test or fix automation.script",
        )
    )


def check_markers(project: Project) -> tuple[Diagnostic, ...]:
    """Run the rule 9 marker lint over every automated case of a project."""
    diagnostics: list[Diagnostic] = []
    scans: dict[Path, MarkerScan] = {}
    bound: dict[Path, dict[str, str]] = {}
    targets: dict[str, ScriptTarget] = {}
    unreadable: set[Path] = set()

    for case_id in sorted(project.cases):
        case = project.cases[case_id]
        binding = case.automation.script
        if binding is None:
            continue
        target = resolve_script_target(project.root, binding)
        targets[case_id] = target
        if (
            case.automation.status is not AutomationStatus.DONE
            or not target.ok
            or target.path is None
        ):
            # A broken or missing script is already TRACE_REF_MISSING /
            # TRACE_REF_OUTSIDE_PROJECT from the P1 rules; do not double report.
            continue
        path = target.path
        bound.setdefault(path, {})[case.id] = binding.nodeid
        scan = scans.get(path)
        if scan is None:
            scan = scan_markers(path)
            scans[path] = scan
        if scan.error is not None:
            if path not in unreadable:
                unreadable.add(path)
                script_path = relative_path(path, project.root) or path.as_posix()
                diagnostics.append(
                    _error(
                        MARKER_UNREADABLE,
                        f"{script_path} cannot be read for marker lint: {scan.error}",
                        path=script_path,
                        field=None,
                        entity_id=case.id,
                        suggestion="fix the syntax error so the marker can be checked",
                    )
                )
            continue
        _check_case_markers(project, case, scan, binding, diagnostics)

    for path in sorted(bound, key=lambda item: item.as_posix()):
        scan = scans.get(path)
        if scan is None or scan.error is not None:
            continue
        script_path = relative_path(path, project.root) or path.as_posix()
        owners = bound[path]
        for marker in scan.markers:
            for note in marker.invalid:
                diagnostics.append(
                    _error(
                        MARKER_UNKNOWN,
                        f"{note} in {marker.nodeid} (line {marker.line})",
                        path=script_path,
                        field=marker.nodeid,
                        entity_id=None,
                        suggestion=(
                            "markers must carry one or more literal TC-* case IDs"
                        ),
                    )
                )
            for case_id in marker.case_ids:
                case = project.cases.get(case_id)
                if case is None:
                    diagnostics.append(
                        _error(
                            MARKER_UNKNOWN,
                            (
                                f"marker names {case_id}, which is not a case of this "
                                f"project (line {marker.line})"
                            ),
                            path=script_path,
                            field=marker.nodeid,
                            entity_id=case_id,
                            suggestion="add the case or remove the stale marker",
                        )
                    )
                    continue
                if case_id in owners:
                    # The case does bind this file; a nodeid mismatch is reported
                    # once by _check_case_markers, not again here.
                    continue
                diagnostics.append(
                    _error(
                        MARKER_ORPHAN,
                        (
                            f"marker names {case_id}, but that case does not bind "
                            f"{script_path}: "
                            f"{_orphan_reason(project, case, targets.get(case_id), script_path)} "
                            f"(line {marker.line})"
                        ),
                        path=script_path,
                        field=marker.nodeid,
                        entity_id=case_id,
                        suggestion=(
                            "point automation.script at this test or remove the marker"
                        ),
                    )
                )

    unique: list[Diagnostic] = []
    seen: set[tuple[str, str | None, str | None, str]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.path,
            diagnostic.field,
            diagnostic.message,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return sort_diagnostics(unique)
