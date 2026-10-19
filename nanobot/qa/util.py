"""Small shared helpers for the QA platform."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    """Return the current UTC time as a sortable ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Return a short, opaque, deterministic-format identifier."""
    return f"{prefix}_{secrets.token_hex(6)}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def sha256_json(value: Any) -> str:
    """Stable content hash for a JSON value; equal content means equal hash."""
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
