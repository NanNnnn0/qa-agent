"""Fixtures for QA platform tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from nanobot.qa import demo_server
from nanobot.qa.store import QaStore

#: The committed demo project ships an intentionally failing pytest script; it is
#: data for the trace tests, not part of the QA suite (its assertion is meant to
#: produce the recorded failure manifest).
collect_ignore_glob = ["fixtures/trace/*/scripts/*"]


@pytest.fixture(autouse=True)
def qa_case_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the YAML case library at a per-test directory.

    Cases are files now, so every test must write them somewhere disposable;
    ``NANOBOT_QA_TRACE_ROOT`` is the documented override and the adapter reads it
    on each call.
    """
    root = tmp_path / "qa-workbench" / "projects"
    monkeypatch.setenv("NANOBOT_QA_TRACE_ROOT", str(root))
    monkeypatch.setenv("NANOBOT_QA_PROJECTS_ROOT", str(tmp_path / "qa-projects"))
    return root


@pytest.fixture
def store(tmp_path: Path) -> Iterator[QaStore]:
    instance = QaStore(tmp_path / "qa.sqlite3")
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def project(store: QaStore) -> dict[str, Any]:
    return store.create_project(
        key="shop",
        name="Demo Shop",
        base_url="http://127.0.0.1:8799",
    )


@pytest.fixture
def demo_api() -> Iterator[str]:
    """Run the demo shop API on an ephemeral port and reset its stock."""
    demo_server._PRODUCTS["A-1"]["stock"] = 5
    demo_server._PRODUCTS["B-2"]["stock"] = 0
    demo_server._ORDERS.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.DemoHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
