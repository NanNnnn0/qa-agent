"""The run manifest has to freeze a library that every checkout can reproduce.

A manifest recorded on a Windows checkout used to hash raw bytes, so the same
repository on Linux (LF) reported every case as "changed since run" -- and the
committed demo manifest made that assertion fail for anyone who cloned it.
"""

from __future__ import annotations

from pathlib import Path

from qa_trace.hashing import DIGEST_VERSION, sha256_bytes, sha256_file_digest


def test_text_digest_ignores_line_endings() -> None:
    lf = "id: TC-X-001\nsteps:\n  - action: GET /x\n".encode()
    crlf = lf.replace(b"\n", b"\r\n")
    assert sha256_file_digest(lf) == sha256_file_digest(crlf)
    assert sha256_bytes(lf) != sha256_bytes(crlf)


def test_binary_digest_is_byte_exact() -> None:
    payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert sha256_file_digest(payload) == sha256_bytes(payload)


def test_digest_version_is_recorded_in_the_snapshot(tmp_path: Path) -> None:
    from qa_trace.pytest_plugin import _snapshot_library

    project_dir = tmp_path / "proj"
    (project_dir / "cases").mkdir(parents=True)
    (project_dir / "project.yaml").write_text(
        "schema_version: 1\nproject_id: proj\nname: Proj\n", encoding="utf-8"
    )
    (project_dir / "cases" / "TC-PROJ-001.yaml").write_text(
        "schema_version: 1\nid: TC-PROJ-001\nmodule: PROJ\ntitle: t\n"
        "priority: P2\ntype: api\nstatus: reviewed\n"
        "testpoints:\n  - TP-PROJ-001\n"
        "steps:\n  - action: a\n    expected: b\n"
        "automation:\n  status: todo\n",
        encoding="utf-8",
    )

    from qa_trace.loader import load_project

    snapshot = _snapshot_library(load_project(project_dir))
    assert snapshot["digest_version"] == DIGEST_VERSION
    digest = snapshot["cases"]["TC-PROJ-001"]
    assert digest == sha256_file_digest((project_dir / "cases" / "TC-PROJ-001.yaml").read_bytes())
