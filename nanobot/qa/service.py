"""High-level QA operations shared by the HTTP API and the agent tools."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

from defusedxml import ElementTree

from nanobot.qa import execution
from nanobot.qa.store import QaStore
from nanobot.qa.validation import QaValidationError


def execute_cases(
    store: QaStore,
    project_id: str,
    *,
    case_ids: list[str] | None = None,
    kind: str | None = None,
    task_id: str | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "manual",
) -> dict[str, Any]:
    """Run ready API cases through the pinned pipeline.

    This is the stable entry point for the WebUI, the CLI, the ``qa_run`` tool and
    scheduled runs. Execution itself lives in :mod:`nanobot.qa.execution`, so
    preflight, the pinned snapshot, batching, masking and classification have one
    implementation instead of two. Only ``ready`` cases execute; a blocked case
    fails the call with the case codes and reasons instead of running a subset.
    """
    run = execution.execute_pinned(
        store,
        project_id,
        case_ids=case_ids,
        kind=kind,
        name=name,
        environment=environment,
        trigger=trigger,
    )
    if task_id:
        store.add_artifact(
            task_id,
            kind="run",
            ref_id=run["id"],
            title=f"run {run['id']} ({run['status']})",
        )
    return run


def _junit_tests(root: Any) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        classname = case.get("classname") or ""
        duration = float(case.get("time") or 0) * 1000
        status = "passed"
        message = ""
        trace = ""
        for child in case:
            tag = child.tag.lower()
            if tag in {"failure", "error"}:
                status = "failed"
                message = (child.get("message") or child.text or "")[:1000]
                trace = (child.text or "")[:4000]
            elif tag == "skipped":
                status = "skipped"
                message = (child.get("message") or "")[:1000]
        tests.append({
            "name": f"{classname}::{name}" if classname else name,
            "status": status,
            "duration": int(duration),
            "message": message,
            "trace": trace,
        })
    return tests


def parse_junit_text(xml_text: str) -> list[dict[str, Any]]:
    """Parse a JUnit XML document from a CI job into runner-shaped tests."""
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise QaValidationError("xml is required")
    if len(xml_text.encode("utf-8")) > 2_000_000:
        raise QaValidationError("junit xml must be at most 2 MB")
    try:
        root = ElementTree.fromstring(xml_text)
    except (ElementTree.ParseError, ExpatError) as exc:
        raise QaValidationError(f"invalid JUnit XML: {exc}") from exc
    return _junit_tests(root)


def _parse_junit(path: Path) -> list[dict[str, Any]]:
    try:
        tree = ElementTree.parse(path)
    except (ElementTree.ParseError, ExpatError, OSError):
        return []
    return _junit_tests(tree.getroot())


def ingest_junit(
    store: QaStore,
    project_id: str,
    *,
    xml: str,
    name: str = "",
    environment: str = "",
    trigger: str = "ci",
    task_id: str | None = None,
) -> dict[str, Any]:
    """Persist a CI-produced JUnit XML result as a run.

    This is the CI entry point: external pipelines push their report here so the
    workbench shows the same run history as agent-executed suites.
    """
    store.get_project(project_id)
    tests = parse_junit_text(xml)
    if not tests:
        raise QaValidationError("junit xml contains no testcase elements")
    passed = sum(1 for test in tests if test["status"] == "passed")
    failed = sum(1 for test in tests if test["status"] == "failed")
    skipped = sum(1 for test in tests if test["status"] == "skipped")
    duration_ms = sum(int(test.get("duration") or 0) for test in tests)
    run = store.create_run(
        project_id,
        name=name or "CI import",
        environment=environment,
        trigger=trigger,
        status="running",
    )
    report = {
        "reportFormat": "junit",
        "summary": {
            "tests": len(tests), "passed": passed, "failed": failed,
            "skipped": skipped, "error": 0, "duration": duration_ms,
        },
        "tests": tests,
    }
    finished = store.finish_run(
        run["id"],
        status="passed" if failed == 0 else "failed",
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_ms=duration_ms,
        report=report,
    )
    if task_id:
        store.add_artifact(task_id, kind="run", ref_id=finished["id"],
                           title=f"CI run {finished['id']}")
    return finished


def execute_script(
    store: QaStore,
    project_id: str,
    script_id: str,
    *,
    timeout_s: int = 900,
    task_id: str | None = None,
    name: str = "",
    environment: str = "",
    trigger: str = "manual",
) -> dict[str, Any]:
    """Run a pytest-framework script in a subprocess and persist the result."""
    project = store.get_project(project_id)
    script = store.get_script(script_id)
    if script["project_id"] != project_id:
        raise QaValidationError("script does not belong to this project")
    if script["framework"] != "pytest":
        raise QaValidationError(
            f"framework '{script['framework']}' cannot be executed yet; use pytest scripts"
        )
    target = Path(script["file_path"])
    if not target.is_absolute():
        repo_root = Path(project.get("repo_path") or ".")
        target = (repo_root / target).resolve()
    if not target.is_file():
        raise QaValidationError(f"script file not found: {target}")

    run = store.create_run(
        project_id, script_id=script_id, case_ids=script["case_ids"],
        name=name, environment=environment, trigger=trigger,
    )
    with tempfile.TemporaryDirectory(prefix="qa-junit-") as tmp:
        junit = Path(tmp) / "junit.xml"
        command = [
            sys.executable, "-m", "pytest", str(target),
            "-q", f"--junitxml={junit}",
        ]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(target.parent),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            stdout, stderr = completed.stdout, completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            return store.finish_run(
                run["id"], status="error", errors=1,
                duration_ms=int((time.perf_counter() - started) * 1000),
                log=f"pytest timed out after {timeout_s}s",
                report={"reportFormat": "qa-agent.pytest.v1", "tests": []},
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        tests = _parse_junit(junit) if junit.is_file() else []
        passed = sum(1 for test in tests if test["status"] == "passed")
        failed = sum(1 for test in tests if test["status"] == "failed")
        skipped = sum(1 for test in tests if test["status"] == "skipped")
        status = "passed" if exit_code == 0 and failed == 0 else "failed"
        if exit_code != 0 and not tests:
            status = "error"
        report = {
            "reportFormat": "qa-agent.pytest.v1",
            "summary": {
                "tests": len(tests), "passed": passed, "failed": failed,
                "skipped": skipped, "error": 0, "duration": duration_ms,
            },
            "tests": tests,
            "command": " ".join(command),
            "exitCode": exit_code,
        }
        log = (stdout or "")[-100_000:] + (("\n[stderr]\n" + stderr[-20_000:]) if stderr else "")
        finished = store.finish_run(
            run["id"], status=status, passed=passed, failed=failed, skipped=skipped,
            duration_ms=duration_ms, report=report, log=log,
        )
    if task_id:
        store.add_artifact(task_id, kind="run", ref_id=finished["id"],
                           title=f"run {finished['id']} ({status})")
    return finished

