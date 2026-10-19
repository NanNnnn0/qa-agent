
"""QA project binding for WebUI chat sessions.

A chat can be bound to one QA project. The binding lives in session metadata
under ``qa_project`` and is copied into the turn metadata, where the runtime
context provider and the ``qa_*`` tools read it. Unbound chats keep the plain
coding-assistant behaviour: nothing is injected and no tool default changes.
"""

from __future__ import annotations

from typing import Any

from nanobot.runtime_context import RuntimeContextBlock, wrap_runtime_context_lines

QA_PROJECT_METADATA_KEY = "qa_project"


def normalize_binding(value: Any) -> dict[str, str] | None:
    """Return a validated ``{id,key,name}`` binding, or ``None``."""
    if not isinstance(value, dict):
        return None
    project_id = value.get("id")
    if not isinstance(project_id, str) or not project_id.strip():
        return None
    return {
        "id": project_id.strip(),
        "key": str(value.get("key") or ""),
        "name": str(value.get("name") or ""),
    }


def binding_payload(project: dict[str, Any]) -> dict[str, str]:
    """Build the session binding stored for one QA project row."""
    return {
        "id": str(project.get("id") or ""),
        "key": str(project.get("key") or ""),
        "name": str(project.get("name") or ""),
    }


def bound_project_id(metadata: Any) -> str | None:
    """Return the bound project id from turn/session metadata."""
    if not isinstance(metadata, dict):
        return None
    binding = normalize_binding(metadata.get(QA_PROJECT_METADATA_KEY))
    return binding["id"] if binding is not None else None


async def qa_project_context(ctx: Any) -> RuntimeContextBlock | None:
    """Inject the QA workflow contract for a bound chat (None when unbound)."""
    metadata = getattr(ctx, "metadata", None)
    binding = normalize_binding((metadata or {}).get(QA_PROJECT_METADATA_KEY))
    if binding is None:
        return None
    label = binding["key"] or binding["id"]
    lines = [
        f"This chat is bound to QA project {label} ({binding['id']}).",
        "Functional and API cases must be created through the qa_case tool: the QA case library "
        "(YAML under the project root) is the source of truth. Do not only write test files into "
        "the repository.",
        "Automation scripts must be registered with qa_script (file_path inside the project repo) "
        "and executed with qa_run; link the cases they cover.",
        "Follow the qa-functional-testing and qa-automation skills, and report the case codes and "
        "script paths you created.",
    ]
    return RuntimeContextBlock(
        source="qa_project",
        content=wrap_runtime_context_lines(lines),
    )
