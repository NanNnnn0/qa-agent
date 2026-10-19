"""P4: the workbench adapter over ``qa_trace`` (``/api/qa/trace/*``).

The adapter must not re-implement any trace rule, so these tests mostly assert
that the *library's* answer reaches the workbench unchanged, plus the parts the
adapter does own: project resolution, error mapping and the three mutations.

Everything runs against a temporary project root (a copy of the committed
``qa-workbench/projects/login-lock`` demo plus a second, unrelated project), so a
test never writes to the repository.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest
from qa_helpers import make_request

from nanobot.qa.http import QA_MUTATION_PATHS, QA_WRITE_PATHS, QaApi
from nanobot.qa.store import QaStore
from nanobot.qa.trace_api import TRACE_ROOT_ENV, TraceApi, default_trace_root
from nanobot.qa.validation import (
    QaConflictError,
    QaNotFoundError,
    QaValidationError,
)
from qa_trace import run_check

REPO_ROOT = Path(__file__).resolve().parents[2]
# A pristine copy lives in the test fixtures so demos and live edits of
# qa-workbench/projects/login-lock cannot break these tests.
DEMO_PROJECT = REPO_ROOT / "tests" / "qa" / "fixtures" / "trace" / "login-lock"


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def _write_minimal_project(root: Path, project_id: str) -> Path:
    """Write a second, unrelated project so selection and isolation are testable."""
    project = root / project_id
    _write(
        project / "project.yaml",
        f"""
        schema_version: 1
        project_id: {project_id}
        name: {project_id} library
        modules: [OTHER]
        """,
    )
    _write(
        project / "sources" / "REQ-OTHER-01.yaml",
        """
        schema_version: 1
        id: REQ-OTHER-01
        type: req
        module: OTHER
        title: Another requirement
        evidence:
          - type: document
            locator: docs/other.md#1
        status: active
        confidence: confirmed
        """,
    )
    _write(
        project / "testpoints" / "TP-OTHER-001.yaml",
        """
        schema_version: 1
        id: TP-OTHER-001
        title: Another test point
        sources: [REQ-OTHER-01]
        method: boundary
        risk: high
        status: reviewed
        """,
    )
    _write(
        project / "cases" / "TC-OTHER-001.yaml",
        """
        schema_version: 1
        id: TC-OTHER-001
        title: Another case
        testpoints: [TP-OTHER-001]
        priority: P2
        type: functional
        status: reviewed
        steps:
          - action: call the endpoint
            expected: HTTP 200 and a JSON body
        automation:
          status: manual
        """,
    )
    return project


@pytest.fixture
def trace_root(tmp_path: Path) -> Path:
    """A temporary root holding a copy of the demo project and a second project."""
    root = tmp_path / "projects"
    root.mkdir()
    shutil.copytree(
        DEMO_PROJECT,
        root / "login-lock",
        ignore=shutil.ignore_patterns(".qa-trace", "__pycache__"),
    )
    _write_minimal_project(root, "other")
    return root


@pytest.fixture
def api(trace_root: Path) -> TraceApi:
    return TraceApi(trace_root)


def _run_id(project: Path) -> str:
    runs = sorted((project / "runs").glob("*/manifest.json"))
    assert runs, "the demo project must ship a recorded run manifest"
    return runs[-1].parent.name


# -- project resolution ----------------------------------------------------


def test_default_root_is_env_overridable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(TRACE_ROOT_ENV, str(tmp_path))
    assert default_trace_root() == tmp_path
    monkeypatch.delenv(TRACE_ROOT_ENV)
    assert default_trace_root().as_posix().endswith("qa-workbench/projects")


def test_list_projects_reports_counts_and_errors(api: TraceApi, trace_root: Path) -> None:
    listing = api.list_projects()
    assert listing["root"] == trace_root.as_posix()
    entries = {item["id"]: item for item in listing["projects"]}
    assert set(entries) == {"login-lock", "other"}
    assert entries["login-lock"]["valid"] is True
    assert entries["login-lock"]["name"] == "登录锁定演示库（qa-trace P4）"
    assert entries["login-lock"]["counts"] == {"sources": 2, "testpoints": 1, "cases": 1}
    assert entries["other"]["counts"] == {"sources": 1, "testpoints": 1, "cases": 1}


def test_list_projects_marks_a_broken_project(api: TraceApi, trace_root: Path) -> None:
    broken = trace_root / "broken"
    _write(broken / "project.yaml", "schema_version: 1\n")
    entry = next(item for item in api.list_projects()["projects"] if item["id"] == "broken")
    assert entry["valid"] is False
    assert "TRACE_" in entry["error"]


def test_default_project_is_the_first_directory(api: TraceApi) -> None:
    # No project id: the first directory (sorted) is used, never another project.
    assert api.summary()["project"]["id"] == "login-lock"


def test_unknown_and_malformed_project_ids_are_rejected(api: TraceApi) -> None:
    with pytest.raises(QaNotFoundError):
        api.resolve_project("does-not-exist")
    with pytest.raises(QaValidationError):
        api.resolve_project("../escape")
    with pytest.raises(QaNotFoundError):
        TraceApi(api.root / "missing-root").resolve_project(None)


def test_project_data_does_not_leak_between_projects(api: TraceApi) -> None:
    login = api.tree("login-lock")
    other = api.tree("other")
    assert login["counts"]["cases"] == 1
    assert other["counts"]["cases"] == 1
    assert "TC-LOGIN-003" not in json.dumps(other, ensure_ascii=False)
    assert "TC-OTHER-001" not in json.dumps(login, ensure_ascii=False)


# -- reads -----------------------------------------------------------------


def test_summary_keeps_the_four_metrics_separate(api: TraceApi) -> None:
    payload = api.summary("login-lock")
    assert payload["valid"] is True
    assert payload["metrics_suppressed"] is None
    coverage = payload["coverage"]
    assert set(coverage) == {"requirement", "behavior", "automation", "orphan"}
    # No combined "total coverage" scalar: the spec forbids merging the numbers.
    assert not any(key in coverage for key in ("total", "overall", "coverage"))

    assert coverage["requirement"]["reviewed"] == {
        "numerator": 1,
        "denominator": 1,
        "percent": 100.0,
    }
    assert coverage["behavior"]["reviewed"]["numerator"] == 1
    assert coverage["automation"]["reviewed"] == {
        "numerator": 1,
        "denominator": 1,
        "percent": 100.0,
    }
    assert coverage["automation"]["provisional"] is True
    assert coverage["orphan"]["library"] == {
        "numerator": 0,
        "denominator": 1,
        "percent": 0.0,
    }
    assert payload["counts"]["reviewed_cases"] == 1
    assert payload["counts"]["dangling_references"] == 0
    assert payload["diagnostics"]["counts"] == {"error": 0, "warn": 0, "info": 0}

    # Derived blocks the workbench cards and panels need.
    assert payload["stale"]["baseline"] == "missing"
    assert payload["stale"]["counts"]["changed"] >= 4
    assert payload["drafts"]["counts"]["pending"] == 1
    assert payload["runs"]["counts"]["failed_cases"] == 1


def test_summary_reports_a_broken_library_without_raising(api: TraceApi, trace_root: Path) -> None:
    broken = trace_root / "broken"
    _write(broken / "project.yaml", "schema_version: 1\nproject_id: broken\n")
    # A case without steps is a document-level error: the loader refuses it, so
    # the summary must report the diagnostics instead of raising.
    _write(
        broken / "cases" / "TC-BROKEN-001.yaml",
        """
        schema_version: 1
        id: TC-BROKEN-001
        title: no steps
        testpoints: [TP-BROKEN-001]
        priority: P1
        type: functional
        status: reviewed
        automation:
          status: manual
        """,
    )
    payload = api.summary("broken")
    assert payload["valid"] is False
    assert payload["coverage"] is None
    assert payload["metrics_suppressed"]
    assert payload["diagnostics"]["counts"]["error"] >= 1
    # The chain itself cannot be rendered from a half-loaded library.
    with pytest.raises(QaValidationError):
        api.tree("broken")


def test_tree_returns_the_whole_chain(api: TraceApi) -> None:
    tree = api.tree("login-lock")
    assert tree["counts"] == {
        "sources": 2,
        "testpoints": 1,
        "cases": 1,
        "scripts": 1,
        "orphans": 0,
    }
    source = next(item for item in tree["sources"] if item["id"] == "UI-LOGIN-02")
    assert source["type"] == "ui"
    assert source["status"] == "active"
    assert source["confidence"] == "confirmed"
    assert source["stale"] is False
    assert source["evidence"][0]["locator"] == "artifacts/ui/login-lock-5x.png"

    testpoint = source["testpoints"][0]
    assert testpoint["id"] == "TP-LOGIN-005"
    assert testpoint["status"] == "reviewed"
    assert testpoint["risk"] == "high"

    case = testpoint["cases"][0]
    assert case["id"] == "TC-LOGIN-003"
    assert case["status"] == "reviewed"
    assert case["needs_recheck"] is False
    assert case["script"] == {
        "case_id": "TC-LOGIN-003",
        "binding": "scripts/test_login.py::test_lock_after_5_failures",
        "file": "scripts/test_login.py",
        "nodeid": "test_lock_after_5_failures",
        "resolves": True,
        "problem": None,
    }
    assert tree["scripts"][0]["resolves"] is True


def test_impact_by_source_and_by_case(api: TraceApi) -> None:
    by_source = api.impact("login-lock", source="REQ-LOGIN-01")
    assert by_source["target"] == {"id": "REQ-LOGIN-01", "kind": "source"}
    assert [item["id"] for item in by_source["testpoints"]] == ["TP-LOGIN-005"]
    assert [item["id"] for item in by_source["cases"]] == ["TC-LOGIN-003"]
    assert by_source["cases"][0]["via"] == [
        {"source_id": "REQ-LOGIN-01", "testpoint_id": "TP-LOGIN-005"}
    ]
    assert by_source["scripts"][0]["nodeid"] == "test_lock_after_5_failures"

    by_case = api.impact("login-lock", case="TC-LOGIN-003")
    assert by_case["target"]["kind"] == "case"
    assert {item["id"] for item in by_case["sources"]} == {"REQ-LOGIN-01", "UI-LOGIN-02"}


def test_impact_unknown_id_is_a_404(api: TraceApi) -> None:
    with pytest.raises(QaNotFoundError):
        api.impact("login-lock", source="REQ-LOGIN-999")
    with pytest.raises(QaNotFoundError):
        api.impact("login-lock", case="TC-LOGIN-999")


def test_runs_and_failure_trace_the_chain(api: TraceApi, trace_root: Path) -> None:
    run_id = _run_id(trace_root / "login-lock")
    runs = api.runs("login-lock")
    assert runs["counts"]["runs"] == 1
    item = runs["items"][0]
    assert item["run_id"] == run_id
    assert item["status"] == "complete"
    assert item["exitstatus"] == 1
    assert item["failed_cases"] == 1
    assert item["failed_case_ids"] == ["TC-LOGIN-003"]
    assert item["path"] == f"runs/{run_id}/manifest.json"

    failure = api.failure("login-lock", run=run_id)
    assert failure["case_missing"] is False
    assert failure["counts"]["failed_cases"] == 1
    reported = failure["failures"][0]
    assert reported["case_id"] == "TC-LOGIN-003"
    assert reported["results"][0]["outcome"] == "failed"
    assert reported["chain"]["origin"] == "snapshot"
    assert [item["id"] for item in reported["chain"]["testpoints"]] == ["TP-LOGIN-005"]
    assert {item["id"] for item in reported["chain"]["sources"]} == {
        "REQ-LOGIN-01",
        "UI-LOGIN-02",
    }
    assert reported["current"]["status"] == "reviewed"
    assert reported["current"]["changed_since_run"] is False

    missing_case = api.failure("login-lock", run=run_id, case="TC-LOGIN-004")
    assert missing_case["case_missing"] is True


def test_failure_requires_an_existing_run(api: TraceApi) -> None:
    with pytest.raises(QaValidationError):
        api.failure("login-lock", run=None)
    with pytest.raises(QaNotFoundError):
        api.failure("login-lock", run="nope")


# -- mutations -------------------------------------------------------------


def test_stale_write_records_a_baseline_and_never_approves(
    api: TraceApi, trace_root: Path
) -> None:
    before = api.stale("login-lock")
    assert before["baseline"] == "missing"
    assert before["counts"]["changed"] >= 4

    written = api.stale_write({"project": "login-lock"})["stale"]
    assert written["written"] is True
    assert written["recorded"] == 4
    assert written["baseline"] == "recorded"

    after = api.stale("login-lock")
    assert after["counts"]["changed"] == 0
    assert after["counts"]["needs_recheck"] == 0

    # Change one source title: only its real downstream needs a re-check.
    source = trace_root / "login-lock" / "sources" / "UI-LOGIN-02.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "登录失败 5 次触发账号锁定", "登录失败 5 次触发账号锁定（v3.5 文案）"
        ),
        encoding="utf-8",
    )
    changed = api.stale("login-lock")
    # compare_fingerprints reports in ID order; all three are the real downstream.
    assert [item["id"] for item in changed["changed"]] == [
        "TC-LOGIN-003",
        "TP-LOGIN-005",
        "UI-LOGIN-02",
    ]
    rechecks = changed["needs_recheck"]
    assert [item["case_id"] for item in rechecks] == ["TC-LOGIN-003"]
    assert rechecks[0]["reasons"] == ["dependency_changed"]
    assert rechecks[0]["changed_ids"] == ["TP-LOGIN-005"]

    # Recording a new baseline answers "what changed"; it does not clear a review.
    api.stale_write({"project": "login-lock"})
    still_stale = api.stale("login-lock")
    assert still_stale["counts"]["changed"] == 0
    assert still_stale["counts"]["needs_recheck"] == 1

    # The honest way to clear it is a review decision.
    outcome = api.review_approve(
        {"project": "login-lock", "id": "TC-LOGIN-003", "reviewer": "qa.zhang"}
    )["review"]
    assert outcome["mode"] == "reviewed"
    assert outcome["reviewed_by"] == "qa.zhang"
    assert outcome["needs_recheck"] is False
    assert api.stale("login-lock")["needs_recheck"] == []
    # The tree agrees with the stale report (both use the same recheck map).
    case = api.tree("login-lock")["sources"][0]["testpoints"][0]["cases"][0]
    assert case["needs_recheck"] is False


def test_impact_reports_the_recheck_state(api: TraceApi, trace_root: Path) -> None:
    api.stale_write({"project": "login-lock"})
    source = trace_root / "login-lock" / "sources" / "REQ-LOGIN-01.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "连续 5 次登录失败后锁定账号 15 分钟", "连续 5 次登录失败后锁定账号 30 分钟"
        ),
        encoding="utf-8",
    )
    impact = api.impact("login-lock", source="REQ-LOGIN-01")
    assert impact["cases"][0]["needs_recheck"] is True
    assert impact["cases"][0]["reasons"] == ["dependency_changed"]
    assert impact["counts"]["needs_recheck"] == 1


def test_draft_approve_promotes_and_writes_the_formal_library(
    api: TraceApi, trace_root: Path
) -> None:
    listing = api.drafts("login-lock")
    assert listing["counts"]["drafts"] == 1
    draft = listing["drafts"][0]
    assert draft["id"] == "TC-LOGIN-004"
    assert draft["kind"] == "case"
    assert draft["status"] == "pending"
    assert draft["valid"] is True

    outcome = api.review_approve(
        {
            "project": "login-lock",
            "id": "TC-LOGIN-004",
            "batch": "login-lock",
            "reviewer": "qa.li",
            "note": "补充锁定期间的回归",
        }
    )["review"]
    assert outcome["mode"] == "promoted"
    assert outcome["path"] == "cases/TC-LOGIN-004.yaml"
    assert outcome["reviewed_by"] == "qa.li"
    assert (trace_root / "login-lock" / "cases" / "TC-LOGIN-004.yaml").is_file()
    assert not (trace_root / "login-lock" / "draft" / "login-lock" / "cases" / "TC-LOGIN-004.yaml").exists()
    assert api.drafts("login-lock")["counts"]["drafts"] == 0
    assert api.tree("login-lock")["counts"]["cases"] == 2


def test_draft_reject_keeps_the_file_and_blocks_approval(
    api: TraceApi, trace_root: Path
) -> None:
    outcome = api.review_reject(
        {
            "project": "login-lock",
            "id": "TC-LOGIN-004",
            "batch": "login-lock",
            "reviewer": "qa.zhang",
            "note": "缺少锁定期间的正确密码断言",
        }
    )["review"]
    assert outcome["mode"] == "rejected"
    draft_path = trace_root / "login-lock" / "draft" / "login-lock" / "cases" / "TC-LOGIN-004.yaml"
    assert draft_path.is_file()

    listing = api.drafts("login-lock")
    assert listing["drafts"][0]["status"] == "rejected"
    with pytest.raises(QaConflictError):
        api.review_approve({"project": "login-lock", "id": "TC-LOGIN-004"})


def test_review_unknown_id_is_a_404(api: TraceApi) -> None:
    with pytest.raises(QaNotFoundError):
        api.review_approve({"project": "login-lock", "id": "TC-LOGIN-999"})
    with pytest.raises(QaValidationError):
        api.review_approve({"project": "login-lock"})


# -- HTTP wiring -----------------------------------------------------------


async def _dispatch(api: QaApi, request: Any, path: str | None = None) -> Any:
    from nanobot.webui.http_utils import parse_request_path

    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got if path is None else path)


async def test_trace_reads_require_the_api_token(store: QaStore, trace_root: Path) -> None:
    api = QaApi(store, check_api_token=lambda request: False, trace_root=trace_root)
    response = await _dispatch(api, make_request("/api/qa/trace/summary"))
    assert response.status_code == 401


async def test_trace_routes_serve_the_library(store: QaStore, trace_root: Path) -> None:
    api = QaApi(store, trace_root=trace_root)

    response = await _dispatch(api, make_request("/api/qa/trace/projects"))
    assert _body(response)["projects"][0]["id"] == "login-lock"

    response = await _dispatch(api, make_request("/api/qa/trace/summary?project=login-lock"))
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["coverage"]["requirement"]["reviewed"]["percent"] == 100.0

    response = await _dispatch(
        api, make_request("/api/qa/trace/tree?project=login-lock")
    )
    assert _body(response)["counts"]["cases"] == 1

    response = await _dispatch(
        api, make_request("/api/qa/trace/impact?project=login-lock&source=REQ-LOGIN-01")
    )
    assert _body(response)["target"]["id"] == "REQ-LOGIN-01"

    response = await _dispatch(api, make_request("/api/qa/trace/stale?project=login-lock"))
    assert _body(response)["baseline"] == "missing"

    response = await _dispatch(api, make_request("/api/qa/trace/drafts?project=login-lock"))
    assert _body(response)["drafts"][0]["id"] == "TC-LOGIN-004"

    response = await _dispatch(api, make_request("/api/qa/trace/runs?project=login-lock"))
    run_id = _body(response)["items"][0]["run_id"]

    response = await _dispatch(
        api,
        make_request(f"/api/qa/trace/failure?project=login-lock&run={run_id}"),
    )
    assert _body(response)["failures"][0]["case_id"] == "TC-LOGIN-003"


async def test_trace_unknown_route_is_a_404(store: QaStore, trace_root: Path) -> None:
    api = QaApi(store, trace_root=trace_root)
    response = await _dispatch(api, make_request("/api/qa/trace/nope"))
    assert response.status_code == 404


async def test_trace_error_mapping(store: QaStore, trace_root: Path) -> None:
    api = QaApi(store, trace_root=trace_root)
    response = await _dispatch(api, make_request("/api/qa/trace/summary?project=nope"))
    assert response.status_code == 404
    response = await _dispatch(
        api, make_request("/api/qa/trace/failure?project=login-lock&run=nope")
    )
    assert response.status_code == 404
    response = await _dispatch(api, make_request("/api/qa/trace/failure?project=login-lock"))
    assert response.status_code == 400


async def test_trace_mutations_need_the_websocket_channel(
    store: QaStore, trace_root: Path
) -> None:
    api = QaApi(store, trace_root=trace_root)
    # A plain HTTP POST is refused: writes only travel the mutation channel.
    response = await _dispatch(
        api, make_request("/api/qa/trace/stale/write"), "/api/qa/trace/stale/write"
    )
    assert response.status_code == 405


async def test_trace_mutations_go_through_the_mutation_channel(
    store: QaStore, trace_root: Path
) -> None:
    api = QaApi(store, trace_root=trace_root)
    response = await _dispatch(
        api,
        make_request("/api/qa/trace/stale/write", {"project": "login-lock"}),
        "/api/qa/trace/stale/write",
    )
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["stale"]["written"] is True

    response = await _dispatch(
        api,
        make_request(
            "/api/qa/trace/review/approve",
            {"project": "login-lock", "id": "TC-LOGIN-004", "batch": "login-lock"},
        ),
        "/api/qa/trace/review/approve",
    )
    assert _body(response)["review"]["mode"] == "promoted"


async def test_trace_reject_mutation_goes_through_the_mutation_channel(
    store: QaStore, trace_root: Path
) -> None:
    api = QaApi(store, trace_root=trace_root)
    response = await _dispatch(
        api,
        make_request(
            "/api/qa/trace/review/reject",
            {"project": "login-lock", "id": "TC-LOGIN-004", "batch": "login-lock"},
        ),
        "/api/qa/trace/review/reject",
    )
    assert _body(response)["review"]["mode"] == "rejected"


def test_trace_mutations_are_registered_for_the_websocket_allowlist() -> None:
    expected = {
        "qa.trace.stale_write": "/api/qa/trace/stale/write",
        "qa.trace.review_approve": "/api/qa/trace/review/approve",
        "qa.trace.review_reject": "/api/qa/trace/review/reject",
    }
    for action, path in expected.items():
        assert QA_MUTATION_PATHS[action] == path
        assert path in QA_WRITE_PATHS

    # The WebUI transport builds its allowlist from QA_MUTATION_PATHS, so the
    # three actions must be callable through `webui_request` without touching
    # ws_http by hand.
    from nanobot.webui.ws_http import _WEBUI_MUTATION_PATHS

    for action, path in expected.items():
        assert _WEBUI_MUTATION_PATHS[action] == path


# -- the committed demo project --------------------------------------------


def test_committed_demo_project_is_clean_and_has_a_run() -> None:
    result = run_check(DEMO_PROJECT)
    assert result.valid is True
    assert result.diagnostics == ()
    assert (DEMO_PROJECT / "runs").is_dir()
    assert sorted((DEMO_PROJECT / "runs").glob("*/manifest.json"))

    api = TraceApi(DEMO_PROJECT.parent)
    summary = api.summary("login-lock")
    assert summary["valid"] is True
    run_id = api.runs("login-lock")["items"][0]["run_id"]
    failure = api.failure("login-lock", run=run_id)
    assert failure["failures"][0]["case_id"] == "TC-LOGIN-003"
