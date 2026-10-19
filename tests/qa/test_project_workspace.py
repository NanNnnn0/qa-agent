"""Tests for auto-created QA project workspaces."""

from __future__ import annotations

from pathlib import Path

from nanobot.qa.store import QaStore
from nanobot.qa.workspace import projects_root


def test_create_project_allocates_a_workspace(store: QaStore) -> None:
    project = store.create_project(key="Shop-App", name="Shop")
    path = Path(project["repo_path"])
    assert path.is_dir()
    assert path.name == "shop-app"
    assert path.parent == projects_root()


def test_explicit_repo_path_is_kept(store: QaStore, tmp_path: Path) -> None:
    target = tmp_path / "repo"
    project = store.create_project(
        key="explicit", name="Explicit", repo_path=str(target),
    )
    assert project["repo_path"] == str(target)
    # A user-provided checkout may not exist yet; we must not invent it.
    assert not target.exists()


def test_clearing_repo_path_reallocates(store: QaStore) -> None:
    project = store.create_project(key="clear-me", name="Clear")
    updated = store.update_project(project["id"], repo_path="")
    assert updated["repo_path"]
    assert Path(updated["repo_path"]).is_dir()


def test_migration_backfills_missing_workspaces(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("NANOBOT_QA_PROJECTS_ROOT", str(tmp_path / "qa-projects"))
    path = tmp_path / "qa.sqlite3"
    store = QaStore(path)
    project = store.create_project(key="old-project", name="Old")
    store._conn.execute(
        "UPDATE projects SET repo_path = '' WHERE id = ?", (project["id"],),
    )
    store._conn.execute("PRAGMA user_version = 3")
    store._conn.commit()
    store.close()

    reopened = QaStore(path)
    try:
        repo_path = reopened.get_project(project["id"])["repo_path"]
        assert repo_path.endswith("old-project")
        assert Path(repo_path).is_dir()
    finally:
        reopened.close()
