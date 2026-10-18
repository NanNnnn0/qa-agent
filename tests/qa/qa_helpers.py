"""Shared helpers for the QA platform tests."""

from __future__ import annotations

from typing import Any

from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest

MUTATION_REQUEST_ATTR = "_nanobot_webui_mutation_request"
MUTATION_PAYLOAD_ATTR = "_nanobot_webui_mutation_payload"


def make_request(path: str, payload: dict[str, Any] | None = None) -> WsRequest:
    """Build the synthetic request the WebUI mutation channel produces."""
    request = WsRequest(path, Headers())
    if payload is not None:
        setattr(request, MUTATION_REQUEST_ATTR, True)
        setattr(request, MUTATION_PAYLOAD_ATTR, dict(payload))
    return request
