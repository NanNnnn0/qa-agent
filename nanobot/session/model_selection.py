"""Session-scoped model preset metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

# Session.metadata is public SDK data, so internal selectors use a reserved namespace.
SESSION_MODEL_PRESET_METADATA_KEY = "_nanobot_model_preset"
SESSION_REASONING_EFFORT_METADATA_KEY = "_nanobot_reasoning_effort"

#: Values accepted by `/think` and stored per session. `None` means "inherit the
#: model preset's own reasoning_effort".
REASONING_EFFORT_VALUES = (
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "adaptive",
)


def model_preset_from_metadata(metadata: object) -> str | None:
    """Read the canonical session preset name from persisted metadata."""
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[object, object], metadata)
    if SESSION_MODEL_PRESET_METADATA_KEY not in typed_metadata:
        return None
    value = typed_metadata[SESSION_MODEL_PRESET_METADATA_KEY]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session model preset must be a non-empty string")
    return value.strip()


def reasoning_effort_from_metadata(metadata: object) -> str | None:
    """Read the session-scoped reasoning-effort override, if any."""
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[object, object], metadata)
    if SESSION_REASONING_EFFORT_METADATA_KEY not in typed_metadata:
        return None
    value = typed_metadata[SESSION_REASONING_EFFORT_METADATA_KEY]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("session reasoning effort must be a string")
    normalized = value.strip().lower()
    return normalized or None
