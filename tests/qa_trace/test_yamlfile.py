"""Tests for the shared atomic YAML writer (``qa_trace.yamlfile``).

Every writer of the library (draft promotion, the YAML case store, the SQLite
migration) goes through this one function, so these tests pin the two properties
the rest of the code relies on: the document keeps the author's key order, and a
failed write leaves the previous file (and no temporary file) behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from qa_trace.yamlfile import dump_yaml, write_yaml


def _payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "TC-LOGIN-003",
        "title": "密码连续错误 5 次锁定账号",
        "steps": [{"action": "输入错误密码", "expected": "剩余次数减一"}],
    }


def test_dump_yaml_keeps_key_order_and_writes_block_style() -> None:
    text = dump_yaml(_payload())
    assert text.startswith("schema_version: 1\nid: TC-LOGIN-003\n")
    assert "title: 密码连续错误 5 次锁定账号" in text
    # Block style, not the one-line ``{...}`` form.
    assert "- action: 输入错误密码" in text
    assert text.endswith("\n")


def test_dump_yaml_is_parseable_and_round_trips(tmp_path: Path) -> None:
    path = write_yaml(tmp_path / "case.yaml", _payload())
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == _payload()


def test_write_yaml_creates_missing_directories_and_returns_the_path(
    tmp_path: Path,
) -> None:
    target = tmp_path / "draft" / "batch-1" / "cases" / "TC-LOGIN-003.yaml"
    returned = write_yaml(target, _payload())
    assert returned == target
    assert target.is_file()


def test_write_yaml_overwrites_atomically_and_leaves_no_temporary_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "case.yaml"
    write_yaml(target, {"schema_version": 1, "id": "TC-LOGIN-003", "title": "old"})
    write_yaml(target, {"schema_version": 1, "id": "TC-LOGIN-003", "title": "new"})

    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert payload["title"] == "new"
    leftovers = [
        path.name for path in target.parent.iterdir() if path.name != target.name
    ]
    assert leftovers == []


def test_a_failed_write_keeps_the_previous_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "case.yaml"
    write_yaml(target, {"schema_version": 1, "id": "TC-LOGIN-003", "title": "before"})
    before = target.read_text(encoding="utf-8")

    def explode(payload: Any) -> str:
        raise RuntimeError("serialisation failed")

    monkeypatch.setattr("qa_trace.yamlfile.dump_yaml", explode)
    with pytest.raises(RuntimeError):
        write_yaml(target, {"schema_version": 1, "id": "TC-LOGIN-003", "title": "after"})

    assert target.read_text(encoding="utf-8") == before
    assert [path.name for path in target.parent.iterdir()] == [target.name]


def test_a_failure_while_replacing_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "case.yaml"

    def explode(source: Any, destination: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("qa_trace.yamlfile.os.replace", explode)
    with pytest.raises(OSError):
        write_yaml(target, _payload())

    assert not target.exists()
    assert [path.name for path in target.parent.iterdir()] == []
