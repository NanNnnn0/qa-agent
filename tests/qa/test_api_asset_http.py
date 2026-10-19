"""Read routes for the API asset catalog and case revisions."""

from __future__ import annotations

import json
from typing import Any

from qa_helpers import make_request

from nanobot.qa import catalog
from nanobot.qa.http import QaApi
from nanobot.qa.store import QaStore

SPEC = {
    "openapi": "3.0.3",
    "paths": {
        "/api/products": {
            "get": {"operationId": "listProducts", "summary": "List products"},
        },
    },
}


def _body(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


async def _dispatch(api: QaApi, request: Any) -> Any:
    from nanobot.webui.http_utils import parse_request_path

    got, _ = parse_request_path(request.path)
    return await api.dispatch(None, request, got)


async def test_operation_routes(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))

    listing = _body(await _dispatch(
        api, make_request(f"/api/qa/api-operations?project_id={project['id']}"),
    ))
    assert listing["ok"] is True
    assert listing["total"] == 1
    operation = listing["items"][0]
    assert operation["path"] == "/api/products"

    detail = _body(await _dispatch(
        api, make_request(f"/api/qa/api-operations/{operation['id']}"),
    ))
    assert detail["operation"]["method"] == "GET"
    assert detail["operation"]["spec"]["operation_id"] == "listProducts"
    assert detail["operation"]["evidence"][0]["kind"] == "openapi"


async def test_operation_listing_filters(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    store.ingest_api_operations(project["id"], catalog.parse_openapi(SPEC))
    empty = _body(await _dispatch(
        api, make_request(f"/api/qa/api-operations?project_id={project['id']}&method=POST"),
    ))
    assert empty["total"] == 0
    missing = _body(await _dispatch(
        api, make_request(f"/api/qa/api-operations?project_id={project['id']}&status=missing"),
    ))
    assert missing["total"] == 0


async def test_case_revision_routes(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    case = store.create_case(
        project["id"],
        title="products",
        kind="api",
        status="ready",
        api={
            "request": {"method": "GET", "path": "/api/products"},
            "assertions": [{"type": "status", "expect": 200}],
        },
    )
    store.update_case(case["id"], title="products v2")

    listing = _body(await _dispatch(
        api, make_request(f"/api/qa/cases/{case['id']}/revisions"),
    ))
    assert listing["total"] == 2
    assert [item["revision"] for item in listing["items"]] == [2, 1]
    assert listing["items"][0]["change_source"] == "edit"

    detail = _body(await _dispatch(
        api, make_request(f"/api/qa/cases/{case['id']}/revisions/1"),
    ))
    assert detail["revision"]["snapshot"]["title"] == "products"


async def test_unknown_operation_is_404(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    response = await _dispatch(api, make_request("/api/qa/api-operations/op_missing"))
    assert response.status_code == 404


async def test_bad_revision_is_400(store: QaStore, project: dict) -> None:
    api = QaApi(store)
    case = store.create_case(project["id"], title="products", kind="api")
    response = await _dispatch(
        api, make_request(f"/api/qa/cases/{case['id']}/revisions/not-a-number"),
    )
    assert response.status_code == 400
