"""The trace chain: agent-written sources/test points, links and the ready rule."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import nanobot.qa as qa_package
from nanobot.agent.tools.qa import QaCaseTool, QaProjectTool
from nanobot.agent.tools.qa_testpoint import QaTestpointTool
from nanobot.qa import shared_store, testpoints
from nanobot.qa.case_files import CaseFiles
from nanobot.qa.validation import QaValidationError
from qa_trace.drafts import approve
from qa_trace.loader import load_yaml_document

EVIDENCE = [{"type": "openapi", "locator": "#/paths/~1api~1auth~1register/post"}]


@pytest.fixture(autouse=True)
def qa_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "qa.sqlite3"
    monkeypatch.setenv("NANOBOT_QA_DB", str(path))
    qa_package._STORE_CACHE.clear()
    yield path
    qa_package._STORE_CACHE.clear()


def _json(result: Any) -> dict[str, Any]:
    return json.loads(str(result))


async def _project() -> str:
    payload = _json(
        await QaProjectTool().execute(
            "create", key="chain", name="Chain", base_url="http://127.0.0.1:8799",
        )
    )
    return payload["project"]["id"]


def _directory(project_id: str) -> Path:
    store = shared_store()
    return CaseFiles(store).project_dir(store.get_project(project_id))


async def _source(project_id: str) -> dict[str, Any]:
    return testpoints.create_source(
        shared_store(),
        project_id,
        source_type="api",
        title="register contract",
        evidence=EVIDENCE,
        confidence="confirmed",
    )


async def _formal_chain(project_id: str) -> tuple[str, str]:
    """Create an approved source and test point; return both ids."""
    store = shared_store()
    source = await _source(project_id)
    approve(_directory(project_id), source["id"], reviewer="qa")
    testpoint = testpoints.create_testpoint(
        store,
        project_id,
        title="username boundary",
        sources=[source["id"]],
        method="boundary",
        risk="low",
    )
    approve(_directory(project_id), testpoint["id"], reviewer="qa")
    return source["id"], testpoint["id"]


def _project_sync() -> str:
    """Create a project through the tool without an event loop."""
    import asyncio

    return asyncio.run(_project())


def asyncio_run(coroutine: Any) -> Any:
    """Run one tool coroutine from a synchronous test."""
    import asyncio

    return asyncio.run(coroutine)


def sync_case_create(**fields: Any) -> Any:
    """Run the case tool synchronously (the tool itself is async)."""
    return asyncio_run(QaCaseTool().execute("create", **fields))


async def test_source_draft_is_written_under_the_agent_batch() -> None:
    project_id = await _project()
    created = await QaTestpointTool().execute(
        action="create",
        entity="source",
        project_id=project_id,
        source_type="api",
        title="register contract",
        evidence=EVIDENCE,
        confidence="confirmed",
    )
    payload = _json(created)
    assert payload["draft"] is True
    assert payload["id"].startswith("API-CHAIN-")
    assert payload["batch"] == testpoints.AGENT_BATCH
    assert (_directory(project_id) / payload["path"]).is_file()


async def test_a_testpoint_cannot_link_a_source_that_is_still_a_draft() -> None:
    project_id = await _project()
    source = await _source(project_id)
    with pytest.raises(QaValidationError) as error:
        testpoints.create_testpoint(
            shared_store(),
            project_id,
            title="username boundary",
            sources=[source["id"]],
        )
    assert "still a draft" in str(error.value)


async def test_approved_chain_accepts_a_ready_case() -> None:
    project_id = await _project()
    _, testpoint_id = await _formal_chain(project_id)
    created = await QaCaseTool().execute(
        "create",
        project_id=project_id,
        title="username 2 chars",
        kind="api",
        status="ready",
        testpoints=[testpoint_id],
        api={
            "request": {"method": "POST", "path": "/api/auth/register"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    payload = _json(created)
    assert payload["case"]["testpoints"] == [testpoint_id]
    assets = testpoints.list_assets(shared_store(), project_id)
    assert assets["counts"]["sources"] == 1
    assert assets["counts"]["testpoints"] == 1
    assert assets["testpoints"][0]["case_count"] == 1


async def test_ready_case_without_a_link_is_refused() -> None:
    project_id = await _project()
    result = await QaCaseTool().execute(
        "create",
        project_id=project_id,
        title="unlinked",
        kind="api",
        status="ready",
    )
    assert str(result).startswith("Error:")
    assert "must link at least one test point" in str(result)


async def test_a_draft_case_may_stay_unlinked_and_be_attached_later() -> None:
    project_id = await _project()
    _, testpoint_id = await _formal_chain(project_id)
    created = _json(
        await QaCaseTool().execute(
            "create", project_id=project_id, title="unlinked draft", kind="api",
        )
    )
    case_id = created["case"]["id"]
    assets = testpoints.list_assets(shared_store(), project_id)
    assert [item["case_id"] for item in assets["unlinked_cases"]] == [case_id]

    attached = await QaTestpointTool().execute(
        action="attach", testpoint_id=testpoint_id, case_ids=[case_id],
    )
    assert _json(attached)["count"] == 1
    stored = CaseFiles(shared_store()).get_case(case_id)
    assert stored["testpoints"] == [testpoint_id]
    assets = testpoints.list_assets(shared_store(), project_id)
    assert assets["unlinked_cases"] == []


async def test_a_direct_source_link_needs_a_reason() -> None:
    project_id = await _project()
    source = await _source(project_id)
    approve(_directory(project_id), source["id"], reviewer="qa")
    result = await QaCaseTool().execute(
        "create",
        project_id=project_id,
        title="direct source",
        kind="api",
        status="ready",
        sources=[source["id"]],
    )
    assert "direct_reason" in str(result)

    accepted = _json(
        await QaCaseTool().execute(
            "create",
            project_id=project_id,
            title="direct source with reason",
            kind="api",
            status="ready",
            sources=[source["id"]],
            direct_reason="no test point for this one-off reproduction",
            risk="low",
        )
    )
    assert accepted["case"]["sources"] == [source["id"]]


async def test_list_assets_reports_sources_and_drafts() -> None:
    project_id = await _project()
    await _source(project_id)
    payload = _json(
        await QaTestpointTool().execute(
            action="list", entity="draft", project_id=project_id,
        )
    )
    assert payload["count"] == 1
    assert payload["drafts"][0]["kind"] == "source"
    sources = _json(
        await QaTestpointTool().execute(
            action="list", entity="source", project_id=project_id,
        )
    )
    assert sources["count"] == 0  # still a draft, not formal yet

def _grouped_chain(project_id: str) -> tuple[str, str]:
    """Approve a source and one grouped test point under it."""
    store = shared_store()
    source = testpoints.create_source(
        store,
        project_id,
        source_type="api",
        title="register contract",
        evidence=EVIDENCE,
        confidence="confirmed",
    )
    approve(_directory(project_id), source["id"], reviewer="qa")
    testpoint = testpoints.create_testpoint(
        store,
        project_id,
        title="username boundary",
        sources=[source["id"]],
        method="boundary",
        risk="low",
        group=" 登录模块 / 注册界面 ",
        note="2 字符和 20 字符都能注册成功",
    )
    approve(_directory(project_id), testpoint["id"], reviewer="qa")
    return source["id"], testpoint["id"]


def test_group_is_normalised_and_listed_with_a_readable_code() -> None:
    project_id = _project_sync()
    source = testpoints.create_source(
        shared_store(),
        project_id,
        source_type="api",
        title="register contract",
        evidence=EVIDENCE,
        confidence="confirmed",
    )
    approve(_directory(project_id), source["id"], reviewer="qa")
    first = testpoints.create_testpoint(
        shared_store(),
        project_id,
        title="username boundary",
        sources=[source["id"]],
        group=" 登录模块 / 注册界面 ",
    )
    approve(_directory(project_id), first["id"], reviewer="qa")
    second = testpoints.create_testpoint(
        shared_store(),
        project_id,
        title="login smoke",
        sources=[source["id"]],
        group="登录模块>登录界面",
    )
    approve(_directory(project_id), second["id"], reviewer="qa")

    assets = testpoints.list_assets(shared_store(), project_id)
    by_id = {item["id"]: item for item in assets["testpoints"]}
    assert by_id[first["id"]]["group"] == "登录模块/注册界面"
    assert by_id[second["id"]]["group"] == "登录模块/登录界面"
    # Codes are display-only ordinals in id order; the trace id stays the key.
    ordered = sorted(by_id, key=lambda item: item)
    assert [by_id[item]["code"] for item in ordered] == ["TP-01", "TP-02"]
    assert by_id[first["id"]]["id"].startswith("TP-CHAIN-")
    # Stable across reads: the ordinal is derived, never stored.
    again = testpoints.list_assets(shared_store(), project_id)
    assert {item["id"]: item["code"] for item in again["testpoints"]} == {
        item: by_id[item]["code"] for item in by_id
    }


def test_the_tool_passes_group_into_the_draft() -> None:
    project_id = _project_sync()
    source = testpoints.create_source(
        shared_store(),
        project_id,
        source_type="api",
        title="register contract",
        evidence=EVIDENCE,
        confidence="confirmed",
    )
    approve(_directory(project_id), source["id"], reviewer="qa")
    created = _json(
        asyncio_run(
            QaTestpointTool().execute(
                action="create",
                entity="testpoint",
                project_id=project_id,
                title="username boundary",
                sources=[source["id"]],
                group="登录模块/注册界面",
                note="2 字符和 20 字符都能注册成功",
            )
        )
    )
    document = load_yaml_document(_directory(project_id) / created["path"])
    assert document["group"] == "登录模块/注册界面"
    assert document["note"] == "2 字符和 20 字符都能注册成功"


def test_group_rejects_too_many_levels() -> None:
    with pytest.raises(QaValidationError) as error:
        testpoints.normalize_group("a/b/c/d/e")
    assert "at most 4 levels" in str(error.value)


def test_case_payload_inherits_the_group_and_sources_of_its_testpoint() -> None:
    project_id = _project_sync()
    source_id, testpoint_id = _grouped_chain(project_id)
    created = _json(
        sync_case_create(
            project_id=project_id,
            title="username 2 chars",
            kind="api",
            status="ready",
            testpoints=[testpoint_id],
        )
    )
    case_id = created["case"]["id"]
    payload = CaseFiles(shared_store()).get_case(case_id)
    assert payload["group"] == "登录模块/注册界面"
    assert payload["sources"] == []  # nothing linked directly
    assert [item["id"] for item in payload["trace_sources"]] == [source_id]
    assert payload["trace_sources"][0]["direct"] is False
    assert payload["trace_sources"][0]["title"] == "register contract"
    assert payload["trace_testpoints"][0]["id"] == testpoint_id
    assert payload["trace_testpoints"][0]["code"] == "TP-01"
    assert payload["trace_testpoints"][0]["title"] == "username boundary"

    listed = CaseFiles(shared_store()).list_cases(project_id=project_id)["items"][0]
    assert listed["group"] == "登录模块/注册界面"
    assert listed["module_id"] == "登录模块"
    assert listed["testpoint_count"] == 1
    assert listed["source_count"] == 1
    assert listed["needs_links"] is False
    # The list is a summary: the resolved chain stays on the detail payload.
    assert "trace_sources" not in listed
    assert "api" not in listed


def test_covered_cases_carry_their_human_code() -> None:
    project_id = _project_sync()
    _, testpoint_id = _grouped_chain(project_id)
    created = _json(
        sync_case_create(
            project_id=project_id,
            title="username 2 chars",
            kind="api",
            status="ready",
            testpoints=[testpoint_id],
        )
    )
    assets = testpoints.list_assets(shared_store(), project_id)
    covered = assets["testpoints"][0]["cases"][0]
    assert covered["case_id"] == created["case"]["id"]
    assert covered["code"].startswith("CHAIN-API-")
