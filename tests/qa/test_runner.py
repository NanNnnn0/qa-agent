"""Tests for the API case runner and execution service."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.qa import service
from nanobot.qa.runner import (
    CaseExecutionError,
    CaseRunner,
    json_path_get,
    json_path_tokens,
    render,
)
from nanobot.qa.store import QaStore


def test_json_path_parser_and_lookup() -> None:
    data = {"data": {"items": [{"id": 7}], "meta": {"ok": True}}}
    assert json_path_tokens("$.data.items[0].id") == ["data", "items", 0, "id"]
    assert json_path_get(data, "$.data.items[0].id") == 7
    assert json_path_get(data, '$["data"]["meta"]["ok"]') is True
    with pytest.raises(KeyError):
        json_path_get(data, "$.data.missing")
    with pytest.raises(CaseExecutionError):
        json_path_tokens("data.items")
    with pytest.raises(CaseExecutionError):
        json_path_tokens("$.data..x")


def test_render_substitutes_variables_recursively() -> None:
    assert render({"a": "{{host}}/x", "b": ["{{token}}", 2]}, {"host": "h", "token": "t"}) == {
        "a": "h/x",
        "b": ["t", 2],
    }
    assert render("{{missing}}", {}) == "{{missing}}"


def test_runner_marks_passed_and_failed(store: QaStore, project: dict, demo_api: str) -> None:
    passing = store.create_case(
        project["id"],
        title="product list",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [
                {"type": "status", "expect": 200},
                {"type": "json_path", "path": "$.items", "op": "exists"},
                {"type": "json_path", "path": "$.code", "op": "equals", "expect": 0},
            ],
        },
    )
    failing = store.create_case(
        project["id"],
        title="wrong expectation",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 500}],
        },
    )
    report = CaseRunner(demo_api).run_cases([passing, failing])
    assert report["summary"]["tests"] == 2
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 1
    failed_test = next(test for test in report["tests"] if test["status"] == "failed")
    assert failed_test["checks"][0]["actual"] == 200
    assert "expected 500" in failed_test["message"]


def test_runner_interpolates_case_variables(store: QaStore, project: dict, demo_api: str) -> None:
    case = store.create_case(
        project["id"],
        title="order with variable sku",
        api={
            "request": {
                "method": "POST",
                "path": "/api/orders",
                "headers": {"Content-Type": "application/json"},
                "body": {"sku": "{{sku}}", "qty": 1},
            },
            "assertions": [
                {"type": "status", "expect": 201},
                {"type": "json_path", "path": "$.data.sku", "op": "equals", "expect": "A-1"},
            ],
            "variables": {"sku": "A-1"},
        },
    )
    report = CaseRunner(demo_api).run_cases([case])
    assert report["tests"][0]["status"] == "passed", report["tests"][0]


def test_runner_reports_connection_errors(
    store: QaStore, project: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    def raise_connect_error(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "request", raise_connect_error)
    case = store.create_case(
        project["id"],
        title="unreachable",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    report = CaseRunner("http://127.0.0.1:1", timeout_s=2).run_cases([case])
    assert report["tests"][0]["status"] == "error"
    assert "ConnectError" in report["tests"][0]["message"]


def test_execute_cases_persists_run(store: QaStore, project: dict, demo_api: str) -> None:
    store.update_project(project["id"], base_url=demo_api)
    store.create_case(
        project["id"],
        title="ok",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    run = service.execute_cases(store, project["id"], kind="api")
    assert run["status"] == "passed"
    assert run["passed"] == 1
    stored = store.get_run(run["id"])
    assert stored["report"]["summary"]["tests"] == 1
    assert stored["finished_at"]


def test_execute_cases_flags_blocked_environment(
    store: QaStore, project: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    def raise_connect_error(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "request", raise_connect_error)
    store.update_project(project["id"], base_url="http://127.0.0.1:1")
    store.create_case(
        project["id"],
        title="unreachable service",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    run = service.execute_cases(store, project["id"], kind="api")
    assert run["status"] == "blocked_by_env"
    assert run["errors"] == 1


def test_execute_cases_requires_base_url(store: QaStore, project: dict) -> None:
    store.update_project(project["id"], base_url="")
    store.create_case(project["id"], title="x", kind="api")
    with pytest.raises(Exception) as excinfo:
        service.execute_cases(store, project["id"], kind="api")
    assert "base_url" in str(excinfo.value)


def test_execute_pytest_script(store: QaStore, project: dict, tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_demo.py"
    target.write_text(
        "def test_one():\n    assert True\n\n"
        "def test_two():\n    assert False, 'boom'\n",
        encoding="utf-8",
    )
    store.update_project(project["id"], repo_path=str(tmp_path))
    script = store.create_script(
        project["id"], name="demo", framework="pytest",
        file_path="tests/test_demo.py", content=target.read_text(encoding="utf-8"),
    )
    run = service.execute_script(store, project["id"], script["id"], timeout_s=120)
    assert run["status"] == "failed"
    assert run["passed"] == 1
    assert run["failed"] == 1
    names = {test["name"] for test in run["report"]["tests"]}
    assert any("test_one" in name for name in names)
