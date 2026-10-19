"""Shared helpers for the qa-trace tests: fixture copies and tree digests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_tree(source: Path, target: Path) -> Path:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    return target


@pytest.fixture
def copy_fixture(tmp_path: Path) -> Callable[[str], Path]:
    """Return a callable that copies one fixture project into ``tmp_path``."""
    def copy(name: str, *, as_name: str | None = None) -> Path:
        return _copy_tree(FIXTURES / name, tmp_path / (as_name or name))

    return copy


def tree_digest(root: Path, *, skip: tuple[str, ...] = ()) -> dict[str, str]:
    """Return ``relative posix path -> sha256`` for the files under ``root``."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if any(relative == item or relative.startswith(f"{item}/") for item in skip):
            continue
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


@pytest.fixture
def digest_tree() -> Callable[..., dict[str, str]]:
    """Return a callable computing the content digest of a directory tree."""
    return tree_digest
