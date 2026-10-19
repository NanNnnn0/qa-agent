"""Pinned API runs: preflight, snapshot, fixed template, batching and masking.

A pinned run differs from the legacy in-process run in five ways that the API
testing plan requires: it refuses to start unless every selected case is ready,
it records which case revision each test executed, it runs the cases through the
fixed pytest template instead of the caller's process, it splits more than one
batch instead of silently truncating, and it masks every credential before the
report is persisted.
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
from nanobot.qa.runner import looks_like_environment_error, placeholders
from nanobot.qa.store import QaStore
from nanobot.qa.validation import (
    QaError,
    QaNotFoundError,
    QaValidationError,
)

TEMPLATE_VERSION = "1"
BATCH_SIZE = 200
MAX_CASES_PER_RUN = 2000
BATCH_TIMEOUT_S = 900
_PAGE_SIZE = 500
_TEMPLATE_PATH = Path(__file__).with_name("templates") / "case_template.py"
# The template subprocess must import the same package as this process. Without
# it, a worktree run would execute the deployed checkout's older runner.
_PACKAGE_ROOT = str(Path(nanobot.__file__).resolve().parent.parent)


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
) -> dict[str, Any]:
    """Report everything that would stop a run, before any request is sent."""
    project = store.get_project(project_id)
    base_url = project.get("base_url") or ""
    cases = _select_cases(store, project_id, case_ids, kind)
    variables = {
        str(key): str(value) for key, value in (project.get("default_env") or {}).items()
    }
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for case in cases:
        reasons = _case_problems(store, case, variables)
        if reasons:
            blocked.append({
                "case_id": case["id"],
                "code": case["code"],
                "title": case["title"],
                "reasons": reasons,
            })
        else:
            ready.append({"case_id": case["id"], "code": case["code"], "title": case["title"]})
    blockers: list[str] = []
    if not base_url:
        blockers.append("project has no base_url configured")
    if not cases:
        blockers.append("no cases selected for this run")
    try:
        AuthProvider(auth, base_url=base_url or "http://127.0.0.1").validate()
    except QaError as exc:
        blockers.append(f"auth: {exc}")
    return {
        "project_id": project_id,
        "base_url": base_url,
        "case_count": len(cases),
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


def _snapshot(store: QaStore, cases: list[dict[str, Any]]) -> dict[str, Any]:
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
    return {"template_version": TEMPLATE_VERSION, "cases": entries}


# -- execution -------------------------------------------------------------


def execute_pinned(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    auth: dict[str, Any] | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "agent",
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    """Run ready cases through the fixed template and persist one run row."""
    checked = preflight(store, project_id, case_ids=case_ids, kind=kind, auth=auth)
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
    cases = _select_cases(store, project_id, case_ids, kind)
    base_url = project.get("base_url") or ""
    variables = {
        str(key): str(value) for key, value in (project.get("default_env") or {}).items()
    }
    snapshot = _snapshot(store, cases)
    run = store.create_run(
        project_id,
        case_ids=[case["id"] for case in cases],
        name=name,
        environment=environment,
        trigger=trigger,
    )
    provider = AuthProvider(auth, base_url=base_url)
    try:
        headers = provider.headers()
    except QaError as exc:
        report = mask_payload(_failure_report(provider.kind, str(exc), snapshot), provider.secrets())
        return store.finish_run(
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

    started_ms = int(time.time() * 1000)
    started = time.perf_counter()
    tests: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    logs: list[str] = []
    size = max(1, min(int(batch_size or BATCH_SIZE), MAX_CASES_PER_RUN))
    for start in range(0, len(cases), size):
        chunk = cases[start:start + size]
        chunk_tests, batch, log_text = _run_batch(
            base_url, chunk, variables, headers, index=len(batches) + 1,
        )
        tests.extend(chunk_tests)
        batches.append(batch)
        if log_text:
            logs.append(log_text)
    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = _summary(tests, duration_ms, len(batches))
    report_payload = {
        "reportFormat": "qa-agent.api.v1",
        "template_version": TEMPLATE_VERSION,
        "snapshot": snapshot,
        "auth": {"kind": provider.kind},
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
        report=mask_payload(report_payload, provider.secrets()),
        log=mask_text("\n".join(logs), provider.secrets()),
    )


def _run_batch(
    base_url: str,
    cases: list[dict[str, Any]],
    variables: dict[str, str],
    headers: dict[str, str],
    *,
    index: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
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
        for item in results:
            item["classification"] = _classify(item)
        batch = {
            "index": index,
            "cases": len(cases),
            "reported": len(reported),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        log_text = (stdout or "")[-40_000:]
        if stderr:
            log_text += f"\n[stderr]\n{stderr[-20_000:]}"
        return results, batch, log_text


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


def _classify(test: dict[str, Any]) -> str:
    status = test.get("status")
    if status == "passed":
        return "passed"
    if status == "skipped":
        return "skipped"
    if status == "error":
        if looks_like_environment_error(str(test.get("message", ""))):
            return "env_blocked"
        return "config_error"
    return "assertion_failed"


def _summary(
    tests: list[dict[str, Any]], duration_ms: int, batch_count: int,
) -> dict[str, Any]:
    return {
        "tests": len(tests),
        "passed": sum(1 for test in tests if test["status"] == "passed"),
        "failed": sum(1 for test in tests if test["status"] == "failed"),
        "skipped": sum(1 for test in tests if test["status"] == "skipped"),
        "error": sum(1 for test in tests if test["status"] == "error"),
        "duration": duration_ms,
        "batches": batch_count,
    }


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
            "code": test.get("code"),
            "title": test.get("title"),
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
        "snapshot": report.get("snapshot") or {},
        "failed_tests": failed_tests,
    }
