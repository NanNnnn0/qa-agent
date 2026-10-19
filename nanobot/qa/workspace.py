
"""Dedicated workspace directories for QA projects.

A QA project owns one directory so chats bound to it have a stable workspace
and the conversation sidebar groups their chats under that project. Creating a
project without an explicit ``repo_path`` allocates
``<workspace>/qa-projects/<key>``; the directory is never moved when the key
changes, so existing chats keep working.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from nanobot.config.paths import get_workspace_path

QA_PROJECTS_ROOT_ENV = "NANOBOT_QA_PROJECTS_ROOT"
_PROJECTS_SUBDIR = "qa-projects"


def projects_root() -> Path:
    """Root that holds auto-created project workspaces."""
    override = os.environ.get(QA_PROJECTS_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return get_workspace_path() / _PROJECTS_SUBDIR


def project_directory_name(key: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(key or "").strip().lower())
    return slug.strip("-._") or "project"


def ensure_project_directory(key: str) -> str:
    """Create and return the dedicated directory for a project key."""
    directory = projects_root() / project_directory_name(key)
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def ensure_project_workspace(project: dict) -> str:
    """Return the project's workspace path, allocating one when it is empty.

    A user-provided ``repo_path`` is never created here: it may point at a
    checkout that does not exist yet, and inventing it would hide a typo.
    """
    existing = str(project.get("repo_path") or "").strip()
    if existing:
        return existing
    return ensure_project_directory(str(project.get("key") or project.get("id") or ""))
