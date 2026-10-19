"""Pinned API runs: preflight, snapshot, fixed template, batching and masking.

A pinned run differs from the legacy in-process run in five ways that the API
testing plan requires: it refuses to start unless every selected case is ready,
it records which case revision each test executed, it runs the cases through the
fixed pytest template instead of the caller's process, it splits more than one
batch instead of silently truncating, and it masks every credential before the
report is persisted.

A run may carry an ordered plan with ``setup``, ``cases`` and ``cleanup`` phases.
Steps reference a case id and optionally the revision they were written against;
values extracted in an earlier phase are available to later phases as
``run.<name>``. A failed setup step skips the cases phase but cleanup still runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import nanobot
from nanobot.qa.auth import AuthProvider, mask_payload, mask_text
from nanobot.qa.run_queue import shared_scheduler
from nanobot.qa.runner import looks_like_environment_error, placeholders
from nanobot.qa.store import QaStore
from nanobot.qa.validation import (
    QaError,
    QaNotFoundError,
    QaValidationError,
)

TEMPLATE_VERSION = "1"
PLAN_VERSION = "1"
PLAN_PHASES = ("setup", "cases", "cleanup")
BATCH_SIZE = 200
MAX_CASES_PER_RUN = 2000
BATCH_TIMEOUT_S = 900
_PAGE_SIZE = 500
_TEMPLATE_PATH = Path(__file__).with_name("templates") / "case_template.py"
# The template subprocess must import the same package as this process. Without
# it, a worktree run would execute the deployed checkout's older runner.
_PACKAGE_ROOT = str(Path(nanobot.__file__).resolve().parent.parent)


# -- plan ------------------------------------------------------------------


def normalize_plan(plan: Any) -> dict[str, Any]:
    """Validate an ordered plan and return ``{version, setup, cases, cleanup}``."""
    if plan is None:
        return {"version": PLAN_VERSION, "setup": [], "cases": [], "cleanup": []}
    if not isinstance(plan, dict):
        raise QaValidationError("plan must be a JSON object")
    unknown = set(plan) - {"version", *PLAN_PHASES}
    if unknown:
        raise QaValidationError(f"plan has unknown fields: {', '.join(sorted(unknown))}")
    version = plan.get("version", PLAN_VERSION)
    if not isinstance(version, str) or not version.strip():
        raise QaValidationError("plan.version must be a non-empty string")
    normalized: dict[str, Any] = {"version": version.strip()}
    for phase in PLAN_PHASES:
        steps = plan.get(phase) or []
        if not isinstance(steps, list):
            raise QaValidationError(f"plan.{phase} must be an array")
        seen: set[str] = set()
        phase_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise QaValidationError(f"plan.{phase}[{index}] must be an object")
            extra = set(step) - {"case_id", "revision"}
            if extra:
                raise QaValidationError(
                    f"plan.{phase}[{index}] has unknown fields: {', '.join(sorted(extra))}"
                )
            case_id = step.get("case_id")
            if not isinstance(case_id, str) or not case_id.strip():
                raise QaValidationError(f"plan.{phase}[{index}].case_id is required")
            revision = step.get("revision")
            if revision is not None and (
                not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
            ):
                raise QaValidationError(
                    f"plan.{phase}[{index}].revision must be a positive integer"
                )
            key = case_id.strip()
            if key in seen:
                raise QaValidationError(f"plan.{phase} repeats case '{key}'")
            seen.add(key)
            phase_steps.append({"case_id": key, "revision": revision})
        normalized[phase] = phase_steps
    if not normalized["cases"] and not normalized["setup"]:
        raise QaValidationError("plan needs at least one setup step or one case")
    return normalized


def _plan_phases(
    store: QaStore, project_id: str, plan: Any,
) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    normalized = normalize_plan(plan)
    phases: dict[str, list[dict[str, Any]]] = {}
    for phase in PLAN_PHASES:
        steps: list[dict[str, Any]] = []
        for index, step in enumerate(normalized[phase]):
            case = store.get_case(step["case_id"])
            if case["project_id"] != project_id:
                raise QaValidationError(
                    f"plan.{phase}[{index}] case '{step['case_id']}' does not belong "
                    "to this project"
                )
            steps.append({"case": case, "revision": step["revision"]})
        phases[phase] = steps
    return normalized["version"], phases


def _revision_problem(
    store: QaStore, case: dict[str, Any], pinned: int | None,
) -> str | None:
    if pinned is None:
        return None
    revisions = store.list_case_revisions(case["id"], limit=1)["items"]
    current = int(revisions[0]["revision"]) if revisions else 0
    if pinned != current:
        return (
            f"plan pins revision {pinned} but the case is at revision {current}; "
            "re-validate the plan against the current case"
        )
    return None


# -- selection -------------------------------------------------------------


def _select_cases(
    store: QaStore,
    project_id: str,
    case_ids: list[str] | None,
    kind: str | None,
) -> list[dict[str, Any]]:
    if case_ids:
        cases: list[dict[str, Any]] = []
        for case_id in case_ids:
            case = store.get_case(case_id)
            if case["project_id"] != project_id:
                raise QaValidationError(f"case '{case_id}' does not belong to this project")
            cases.append(case)
        if len(cases) > MAX_CASES_PER_RUN:
            raise QaValidationError(
                f"at most {MAX_CASES_PER_RUN} cases can run at once; narrow the selection"
            )
        return cases
    total = store.list_cases(project_id=project_id, kind=kind, limit=1)["total"]
    if total > MAX_CASES_PER_RUN:
        raise QaValidationError(
            f"{total} cases selected, at most {MAX_CASES_PER_RUN} can run at once; "
            "narrow the selection"
        )
    cases = []
    offset = 0
    while offset < total:
        page = store.list_cases(
            project_id=project_id, kind=kind, limit=_PAGE_SIZE, offset=offset,
        )
        if not page["items"]:
            break
        cases.extend(page["items"])
        offset += len(page["items"])
    return cases


# -- preflight -------------------------------------------------------------


def preflight(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    auth: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report everything that would stop a run, before any request is sent."""
    if plan is not None and case_ids:
        raise QaValidationError("pass either plan or case_ids, not both")
    project = store.get_project(project_id)
    base_url = project.get("base_url") or ""
    if plan is not None:
        plan_version, phases = _plan_phases(store, project_id, plan)
    else:
        plan_version = PLAN_VERSION
        phases = {
            "setup": [],
            "cases": [
                {"case": case, "revision": None}
                for case in _select_cases(store, project_id, case_ids, kind)
            ],
            "cleanup": [],
        }
    variables = {
        str(key): str(value) for key, value in (project.get("default_env") or {}).items()
    }
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for phase in PLAN_PHASES:
        for index, step in enumerate(phases[phase]):
            case = step["case"]
            reasons = _case_problems(store, case, variables)
            pinned = _revision_problem(store, case, step["revision"])
            if pinned:
                reasons.append(pinned)
            entry = {
                "phase": phase,
                "index": index,
                "case_id": case["id"],
                "code": case["code"],
                "title": case["title"],
            }
            if reasons:
                blocked.append({**entry, "reasons": reasons})
            else:
                ready.append(entry)
    total = sum(len(phases[phase]) for phase in PLAN_PHASES)
    blockers: list[str] = []
    if not base_url:
        blockers.append("project has no base_url configured")
    if not total:
        blockers.append("no cases selected for this run")
    try:
        AuthProvider(auth, base_url=base_url or "http://127.0.0.1").validate()
    except QaError as exc:
        blockers.append(f"auth: {exc}")
    return {
        "project_id": project_id,
        "base_url": base_url,
        "plan_version": plan_version,
        "phases": {phase: len(phases[phase]) for phase in PLAN_PHASES},
        "case_count": total,
        "ready": ready,
        "blocked": blocked,
        "blockers": blockers,
        "ok": not blockers and not blocked,
        "template_version": TEMPLATE_VERSION,
    }


def _case_problems(
    store: QaStore, case: dict[str, Any], variables: dict[str, str],
) -> list[str]:
    problems: list[str] = []
    if case.get("kind") != "api":
        problems.append(f"kind is '{case.get('kind')}', only api cases execute here")
    if case.get("status") != "ready":
        problems.append(f"status is '{case.get('status')}', only ready cases execute")
    api = case.get("api") or {}
    request = api.get("request") or {}
    if not request:
        problems.append("case has no api.request")
    if not (api.get("assertions") or []):
        problems.append("case has no assertions")
    merged = {
        **variables,
        **{str(key): str(value) for key, value in (api.get("variables") or {}).items()},
    }
    for name in sorted(set(placeholders(request))):
        if name.startswith("run."):
            # Produced by an earlier case in the same run; resolved at run time.
            continue
        if name not in merged:
            problems.append(f"unresolved variable '{name}'")
    problems.extend(_catalog_problems(store, case))
    return problems


def _catalog_problems(store: QaStore, case: dict[str, Any]) -> list[str]:
    try:
        metadata = store.get_case_metadata(case["id"])
    except QaNotFoundError:
        return []
    operation_id = metadata.get("operation_id")
    if not operation_id:
        return []
    try:
        operation = store.get_api_operation(operation_id)
    except QaNotFoundError:
        return ["case references a catalog operation that no longer exists"]
    if operation.get("status") != "active":
        return [f"case references catalog operation '{operation['path']}' marked missing"]
    return []


# -- snapshot --------------------------------------------------------------


def _snapshot(
    store: QaStore,
    cases: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pin the case revisions and the template version this run executed."""
    entries = []
    for case in cases:
        revisions = store.list_case_revisions(case["id"], limit=1)["items"]
        entries.append({
            "case_id": case["id"],
            "code": case["code"],
            "revision": int(revisions[0]["revision"]) if revisions else 0,
            "content_hash": revisions[0]["content_hash"] if revisions else "",
        })
    payload: dict[str, Any] = {"template_version": TEMPLATE_VERSION, "cases": entries}
    if plan is not None:
        payload["plan"] = plan
    return payload


def _plan_snapshot(
    version: str, phases: dict[str, list[dict[str, Any]]], revisions: dict[str, int],
) -> dict[str, Any]:
    return {
        "version": version,
        "phases": {
            phase: [
                {
                    "case_id": step["case"]["id"],
                    "revision": revisions.get(step["case"]["id"], 0),
                }
                for step in phases[phase]
            ]
            for phase in PLAN_PHASES
        },
    }


# -- execution -------------------------------------------------------------


def _prepare_run(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    auth: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "agent",
) -> dict[str, Any]:
    """Validate, snapshot and create the run row.

    Authentication happens here so a bad login fails the start call instead of
    surfacing later in a background thread. ``finished`` marks a prepared run
    that already carries its final state.
    """
    checked = preflight(
        store, project_id, case_ids=case_ids, kind=kind, auth=auth, plan=plan,
    )
    if checked["blockers"]:
        raise QaValidationError("; ".join(checked["blockers"]))
    if checked["blocked"]:
        detail = "; ".join(
            f"{item['code']}: {', '.join(item['reasons'])}"
            for item in checked["blocked"][:10]
        )
        raise QaValidationError(
            f"{len(checked['blocked'])} case(s) cannot run: {detail}"
        )
    project = store.get_project(project_id)
    if plan is not None:
        plan_version, phases = _plan_phases(store, project_id, plan)
    else:
        plan_version = PLAN_VERSION
        phases = {
            "setup": [],
            "cases": [
                {"case": case, "revision": None}
                for case in _select_cases(store, project_id, case_ids, kind)
            ],
            "cleanup": [],
        }
    ordered = [step["case"] for phase in PLAN_PHASES for step in phases[phase]]
    base_url = project.get("base_url") or ""
    snapshot = _snapshot(store, ordered)
    if plan is not None:
        revisions = {entry["case_id"]: entry["revision"] for entry in snapshot["cases"]}
        snapshot["plan"] = _plan_snapshot(plan_version, phases, revisions)
    run = store.create_run(
        project_id,
        case_ids=[case["id"] for case in ordered],
        name=name,
        environment=environment,
        trigger=trigger,
    )
    provider = AuthProvider(auth, base_url=base_url)
    try:
        headers = provider.headers()
    except QaError as exc:
        report = mask_payload(
            _failure_report(provider.kind, str(exc), snapshot), provider.secrets()
        )
        finished = store.finish_run(
            run["id"],
            status="error",
            passed=0,
            failed=0,
            errors=1,
            skipped=0,
            duration_ms=0,
            report=report,
            log="",
        )
        return {"run": finished, "finished": True}
    return {
        "run": run,
        "finished": False,
        "store": store,
        "base_url": base_url,
        "phases": phases,
        "variables": {
            str(key): str(value)
            for key, value in (project.get("default_env") or {}).items()
        },
        "headers": headers,
        "secrets": provider.secrets(),
        "snapshot": snapshot,
        "plan_version": plan_version,
        "auth_kind": provider.kind,
    }


def _execute_run(prepared: dict[str, Any], *, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Execute a prepared run and finish its row."""
    store: QaStore = prepared["store"]
    run = prepared["run"]
    phases = prepared["phases"]
    base_url = prepared["base_url"]
    headers = prepared["headers"]
    secrets = prepared["secrets"]
    variables = dict(prepared["variables"])
    snapshot = prepared["snapshot"]
    plan_version = prepared["plan_version"]
    started_ms = int(time.time() * 1000)
    started = time.perf_counter()
    tests: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    logs: list[str] = []
    size = max(1, min(int(batch_size or BATCH_SIZE), MAX_CASES_PER_RUN))
    setup_failed = False
    for phase in PLAN_PHASES:
        steps = phases[phase]
        if not steps:
            continue
        if phase == "cases" and setup_failed:
            tests.extend(
                _skipped(step["case"], phase, "a setup step failed") for step in steps
            )
            continue
        index = 0
        while index < len(steps):
            chunk = steps[index:index + size]
            chunk_tests, batch, log_text, extracted = _run_batch(
                base_url,
                [step["case"] for step in chunk],
                variables,
                headers,
                index=len(batches) + 1,
                phase=phase,
            )
            tests.extend(chunk_tests)
            batches.append(batch)
            if log_text:
                logs.append(log_text)
            variables.update(
                {f"run.{key}": str(value) for key, value in extracted.items()}
            )
            if phase == "setup" and any(
                test["status"] != "passed" for test in chunk_tests
            ):
                setup_failed = True
                tests.extend(
                    _skipped(step["case"], phase, "an earlier setup step failed")
                    for step in steps[index + len(chunk):]
                )
                break
            index += len(chunk)
    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = _summary(tests, duration_ms, len(batches))
    report_payload = {
        "reportFormat": "qa-agent.api.v1",
        "template_version": TEMPLATE_VERSION,
        "plan_version": plan_version,
        "snapshot": snapshot,
        "auth": {"kind": prepared.get("auth_kind", "none")},
        "batches": batches,
        "summary": summary,
        "tests": tests,
        "startedAt": started_ms,
        "finishedAt": started_ms + duration_ms,
    }
    return store.finish_run(
        run["id"],
        status=_run_status(tests, summary),
        passed=summary["passed"],
        failed=summary["failed"],
        errors=summary["error"],
        skipped=summary["skipped"],
        duration_ms=duration_ms,
        report=mask_payload(report_payload, secrets),
        log=mask_text("\n".join(logs), secrets),
    )


def execute_pinned(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    auth: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "agent",
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    """Run ready cases now and return the finished run."""
    prepared = _prepare_run(
        store,
        project_id,
        case_ids=case_ids,
        kind=kind,
        auth=auth,
        plan=plan,
        name=name,
        environment=environment,
        trigger=trigger,
    )
    if prepared["finished"]:
        return prepared["run"]
    return _execute_run(prepared, batch_size=batch_size)


def execute_pinned_async(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    auth: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "agent",
    batch_size: int = BATCH_SIZE,
    scheduler: Any = None,
) -> dict[str, Any]:
    """Create the run and execute it on the project's queue.

    Returns the ``running`` row. Preflight and authentication already passed, so
    a caller that got a run id can poll it instead of waiting.
    """
    prepared = _prepare_run(
        store,
        project_id,
        case_ids=case_ids,
        kind=kind,
        auth=auth,
        plan=plan,
        name=name,
        environment=environment,
        trigger=trigger,
    )
    if prepared["finished"]:
        return prepared["run"]
    runner = scheduler if scheduler is not None else shared_scheduler()
    runner.submit(
        project_id,
        lambda: _execute_run(prepared, batch_size=batch_size),
    )
    return prepared["run"]


def wait_for_run(
    store: QaStore,
    run_id: str,
    *,
    timeout_s: float = 300.0,
    interval_s: float = 0.05,
) -> dict[str, Any]:
    """Block until a run leaves the ``running`` state."""
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while True:
        run = store.get_run(run_id)
        if run["status"] != "running":
            return run
        if time.monotonic() >= deadline:
            raise QaValidationError(
                f"run '{run_id}' is still running after {timeout_s:.0f}s"
            )
        time.sleep(interval_s)


def _run_batch(
    base_url: str,
    cases: list[dict[str, Any]],
    variables: dict[str, str],
    headers: dict[str, str],
    *,
    index: int,
    phase: str = "cases",
) -> tuple[list[dict[str, Any]], dict[str, Any], str, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=f"qa-run-{index}-") as tmp:
        directory = Path(tmp)
        template_target = directory / "test_qa_cases.py"
        template_target.write_text(_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        context_path = directory / "context.json"
        context_path.write_text(
            json.dumps(
                {
                    "base_url": base_url,
                    "variables": variables,
                    "headers": headers,
                    "cases": cases,
                    "template_version": TEMPLATE_VERSION,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result_path = directory / "result.json"
        existing_path = os.environ.get("PYTHONPATH", "")
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [item for item in (_PACKAGE_ROOT, existing_path) if item]
            ),
            "QA_RUN_CONTEXT": str(context_path),
            "QA_RUN_RESULT": str(result_path),
        }
        command = [
            sys.executable, "-m", "pytest", str(template_target),
            "-q", "-p", "no:cacheprovider", "-p", "no:qa_trace",
        ]
        started = time.perf_counter()
        stdout = ""
        stderr = ""
        exit_code = -1
        try:
            completed = subprocess.run(
                command,
                cwd=str(directory),
                capture_output=True,
                text=True,
                timeout=BATCH_TIMEOUT_S,
                env=env,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "")
        duration_ms = int((time.perf_counter() - started) * 1000)
        results = _read_results(result_path)
        reported = {str(item.get("case_id")) for item in results}
        for case in cases:
            if case["id"] in reported:
                continue
            results.append({
                "case_id": case["id"],
                "code": case["code"],
                "title": case["title"],
                "status": "error",
                "duration_ms": 0,
                "message": "the run template did not report this case",
                "checks": [],
            })
        extracted: dict[str, Any] = {}
        for item in results:
            item["phase"] = phase
            item["classification"] = _classify(item, phase)
            extracted.update(item.get("extracted") or {})
        batch = {
            "index": index,
            "phase": phase,
            "cases": len(cases),
            "reported": len(reported),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        log_text = (stdout or "")[-40_000:]
        if stderr:
            log_text += f"\n[stderr]\n{stderr[-20_000:]}"
        return results, batch, log_text, extracted


def _read_results(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _skipped(case: dict[str, Any], phase: str, reason: str) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "code": case["code"],
        "title": case["title"],
        "status": "skipped",
        "duration_ms": 0,
        "message": reason,
        "checks": [],
        "phase": phase,
        "classification": "dependency_blocked",
    }


def _classify(test: dict[str, Any], phase: str = "cases") -> str:
    status = test.get("status")
    if status == "passed":
        return "passed"
    if status == "skipped":
        return "skipped"
    if phase == "cleanup":
        return "cleanup_failed"
    if status == "error":
        if looks_like_environment_error(str(test.get("message", ""))):
            return "env_blocked"
        return "config_error"
    return "assertion_failed"


def _summary(
    tests: list[dict[str, Any]], duration_ms: int, batch_count: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "tests": len(tests),
        "passed": sum(1 for test in tests if test["status"] == "passed"),
        "failed": sum(1 for test in tests if test["status"] == "failed"),
        "skipped": sum(1 for test in tests if test["status"] == "skipped"),
        "error": sum(1 for test in tests if test["status"] == "error"),
        "duration": duration_ms,
        "batches": batch_count,
    }
    phases: dict[str, Any] = {}
    for phase in PLAN_PHASES:
        subset = [test for test in tests if test.get("phase") == phase]
        if not subset:
            continue
        phases[phase] = {
            "tests": len(subset),
            "passed": sum(1 for test in subset if test["status"] == "passed"),
            "failed": sum(1 for test in subset if test["status"] == "failed"),
            "skipped": sum(1 for test in subset if test["status"] == "skipped"),
            "error": sum(1 for test in subset if test["status"] == "error"),
        }
    if phases:
        summary["phases"] = phases
    return summary


def _run_status(tests: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    if summary["failed"] == 0 and summary["error"] == 0:
        return "passed"
    if summary["passed"] == 0 and summary["failed"] == 0 and summary["error"]:
        errored = [test for test in tests if test["status"] == "error"]
        if all(test.get("classification") == "env_blocked" for test in errored):
            return "blocked_by_env"
    return "failed"


def _failure_report(
    kind: str, message: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reportFormat": "qa-agent.api.v1",
        "template_version": TEMPLATE_VERSION,
        "plan_version": PLAN_VERSION,
        "snapshot": snapshot,
        "auth": {"kind": kind},
        "classification": "auth_failed",
        "message": message,
        "batches": [],
        "summary": {
            "tests": 0, "passed": 0, "failed": 0, "skipped": 0,
            "error": 1, "duration": 0, "batches": 0,
        },
        "tests": [],
    }


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a run for tool output; the full report stays in the store."""
    report = run.get("report") or {}
    summary = report.get("summary") or {}
    failed_tests = [
        {
            "phase": test.get("phase", ""),
            "code": test.get("code"),
            "title": test.get("title"),
            "status": test.get("status"),
            "classification": test.get("classification"),
            "message": str(test.get("message") or "")[:500],
        }
        for test in report.get("tests") or []
        if test.get("status") != "passed"
    ]
    return {
        "id": run["id"],
        "project_id": run["project_id"],
        "status": run["status"],
        "name": run.get("name", ""),
        "environment": run.get("environment", ""),
        "trigger": run.get("trigger", ""),
        "passed": run.get("passed", 0),
        "failed": run.get("failed", 0),
        "errors": run.get("errors", 0),
        "skipped": run.get("skipped", 0),
        "duration_ms": run.get("duration_ms", 0),
        "started_at": run.get("started_at", ""),
        "finished_at": run.get("finished_at", ""),
        "summary": summary,
        "batches": report.get("batches") or [],
        "template_version": report.get("template_version", ""),
        "plan_version": report.get("plan_version", ""),
        "snapshot": report.get("snapshot") or {},
        "failed_tests": failed_tests,
    }
