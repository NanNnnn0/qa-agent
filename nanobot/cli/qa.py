"""``nanobot qa`` CLI: bootstrap, inspect and run the QA platform."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

qa_app = typer.Typer(help="QA Agent: projects, cases, scripts, runs and dispatch tasks.")


def _store():
    from nanobot.qa import shared_store

    return shared_store()


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


@qa_app.command("status")
def qa_status() -> None:
    """Show the QA database path and headline counts."""
    store = _store()
    _print({"store": str(store.path), "counts": store.overview()["counts"]})


@qa_app.command("seed")
def qa_seed(
    base_url: str = typer.Option(
        "http://127.0.0.1:8799", "--base-url", help="Base URL the demo project points at."
    ),
) -> None:
    """Create the demo project, cases, script and dispatch tasks."""
    from nanobot.qa.seed import seed_demo

    _print(seed_demo(_store(), base_url=base_url))


@qa_app.command("demo-server")
def qa_demo_server(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8799, "--port"),
) -> None:
    """Serve the demo shop API used by the seeded cases."""
    from nanobot.qa.demo_server import serve

    serve(host=host, port=port)


@qa_app.command("mcp")
def qa_mcp() -> None:
    """Run the QA MCP server over stdio (for external MCP clients)."""
    import asyncio

    from nanobot.qa.mcp_server import main

    asyncio.run(main())


@qa_app.command("projects")
def qa_projects() -> None:
    """List projects with health counts."""
    _print({"projects": _store().list_projects()})


@qa_app.command("cases")
def qa_cases(
    project: str | None = typer.Option(None, "--project", help="Project key or id."),
    kind: str | None = typer.Option(None, "--kind", help="api | ui | manual"),
    query: str | None = typer.Option(None, "--query", "-q"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List test cases."""
    store = _store()
    project_id = None
    if project:
        project_id = _resolve_project_id(store, project)
    result = store.list_cases(project_id=project_id, kind=kind, query=query, limit=limit)
    _print({
        "total": result["total"],
        "cases": [
            {
                "code": case["code"],
                "title": case["title"],
                "kind": case["kind"],
                "priority": case["priority"],
                "status": case["status"],
                "id": case["id"],
            }
            for case in result["items"]
        ],
    })


@qa_app.command("tasks")
def qa_tasks(
    project: str | None = typer.Option(None, "--project"),
    status: str | None = typer.Option(None, "--status"),
    limit: int = typer.Option(30, "--limit"),
) -> None:
    """List dispatch tasks."""
    store = _store()
    project_id = _resolve_project_id(store, project) if project else None
    _print(store.list_tasks(project_id=project_id, status=status, limit=limit))


@qa_app.command("run")
def qa_run(
    project: str = typer.Option(..., "--project", help="Project key or id."),
    case: list[str] = typer.Option(None, "--case", help="Case id (repeatable)."),
    script: str | None = typer.Option(None, "--script", help="Run a pytest script id."),
    kind: str | None = typer.Option(None, "--kind", help="Run all cases of this kind."),
    name: str = typer.Option("", "--name", help="Run name shown in the workbench."),
    environment: str = typer.Option("", "--environment", help="Environment label."),
) -> None:
    """Execute cases or a pytest script and print the run result."""
    from nanobot.qa import service

    store = _store()
    project_id = _resolve_project_id(store, project)
    if script:
        run = service.execute_script(
            store, project_id, script, name=name, environment=environment,
        )
    else:
        run = service.execute_cases(
            store, project_id, case_ids=list(case) if case else None, kind=kind,
            name=name, environment=environment,
        )
    summary = {
        "run": run["id"],
        "name": run.get("name", ""),
        "environment": run.get("environment", ""),
        "status": run["status"],
        "passed": run["passed"],
        "failed": run["failed"],
        "errors": run["errors"],
        "duration_ms": run["duration_ms"],
        "tests": [
            {
                "name": test.get("code") or test.get("name"),
                "status": test.get("status"),
                "message": (test.get("message") or "")[:200],
            }
            for test in (run.get("report") or {}).get("tests", [])
        ],
    }
    _print(summary)


@qa_app.command("import-junit")
def qa_import_junit(
    project: str = typer.Option(..., "--project", help="Project key or id."),
    file: Path = typer.Option(..., "--file", "-f", help="JUnit XML file from CI."),
    name: str = typer.Option("", "--name", help="Run name, e.g. 'pipeline #42'."),
    environment: str = typer.Option("", "--environment", help="Environment label."),
    trigger: str = typer.Option("ci", "--trigger", help="manual | ci | agent | schedule"),
) -> None:
    """Import a CI JUnit XML report as a run (CI entry point)."""
    from nanobot.qa import service

    if not file.is_file():
        raise typer.BadParameter(f"file not found: {file}")
    store = _store()
    project_id = _resolve_project_id(store, project)
    run = service.ingest_junit(
        store, project_id,
        xml=file.read_text(encoding="utf-8"),
        name=name, environment=environment, trigger=trigger,
    )
    _print({
        "run": run["id"],
        "name": run["name"],
        "environment": run["environment"],
        "trigger": run["trigger"],
        "status": run["status"],
        "passed": run["passed"],
        "failed": run["failed"],
        "skipped": run["skipped"],
    })


def _resolve_project_id(store: Any, value: str) -> str:
    if value.startswith("proj_"):
        return value
    return store.get_project_by_key(value)["id"]
