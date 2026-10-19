"""Atomic YAML document writing shared by every writer of the library.

Draft batches and the YAML case store both write whole documents.  The file is
written to a temporary sibling, flushed, fsynced and moved into place with
``os.replace`` so a crash never leaves a half-written case (or a case that reads
as valid YAML but is missing its steps).  The document keeps the author's key
order (``sort_keys=False``) because these files are reviewed by humans too.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


def dump_yaml(payload: Mapping[str, Any]) -> str:
    """Return the canonical YAML text of one document."""
    return yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def write_yaml(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` to ``path`` atomically and return the final path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = dump_yaml(payload)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = ["dump_yaml", "write_yaml"]
