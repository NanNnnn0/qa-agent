"""Normalize API reference material into catalog operations and diffs.

The catalog is derived data: a parsed OpenAPI document, or a path registered by
an Agent, becomes a list of operation records and the store decides what changed.
Everything here is deterministic and side-effect free, so ingesting the same
material twice produces the same identity and the same content hashes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from nanobot.qa.util import sha256_json
from nanobot.qa.validation import (
    HTTP_METHODS,
    QaValidationError,
    normalize_api_operation,
    normalize_evidence,
    optional_text,
)

_METHOD_KEYS = tuple(method.lower() for method in HTTP_METHODS)
_OPENAPI_PREFIXES = ("3.0", "3.1")
# Spec fields compared when reporting what changed between two catalog versions.
_SPEC_FIELDS = (
    "operation_id", "summary", "description", "tags", "parameters",
    "request_body", "responses", "deprecated", "security",
)


def load_document(payload: Any) -> dict[str, Any]:
    """Parse a JSON or YAML document; an already parsed mapping passes through."""
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, (str, bytes)):
        raise QaValidationError("document must be a mapping, a JSON string or YAML text")
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    if not text.strip():
        raise QaValidationError("document is empty")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise QaValidationError("document must parse to a JSON object")
    return parsed


def configured_roots() -> list[str]:
    """Reference roots the caller may read, from ``NANOBOT_QA_SPEC_ROOTS``.

    The variable holds ``os.pathsep``-separated directories. An empty result means
    no local reference may be read at all, so a path-based ingest fails loudly
    instead of reading whatever the process can reach.
    """
    raw = os.environ.get("NANOBOT_QA_SPEC_ROOTS", "")
    return [item.strip() for item in raw.split(os.pathsep) if item.strip()]


def read_local_source(path: str, *, allowed_roots: Iterable[str]) -> tuple[str, dict[str, str]]:
    """Read a reference file that lives inside one of the allowed roots.

    Remote references are never fetched: the caller registers a local path and the
    path is rejected as soon as it leaves the configured roots.
    """
    roots = [Path(root).resolve() for root in allowed_roots]
    if not roots:
        raise QaValidationError("no reference roots are configured")
    resolved = Path(path).expanduser().resolve()
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise QaValidationError(f"reference '{path}' is outside the allowed roots")
    if not resolved.is_file():
        raise QaValidationError(f"reference '{path}' does not exist")
    text = resolved.read_text(encoding="utf-8")
    return text, {
        "kind": "spec",
        "ref": str(resolved),
        "version": sha256_json(text)[:12],
    }


def parse_openapi(document: Any, *, source: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Turn an OpenAPI 3.0/3.1 document into normalized catalog operations."""
    parsed = load_document(document)
    version = parsed.get("openapi")
    if not isinstance(version, str) or not version.startswith(_OPENAPI_PREFIXES):
        raise QaValidationError("document must declare openapi 3.0.x or 3.1.x")
    paths = parsed.get("paths")
    if not isinstance(paths, dict):
        raise QaValidationError("document must contain a 'paths' object")
    base_evidence = normalize_evidence([source]) if source else []
    operations: list[dict[str, Any]] = []
    for template in sorted(paths):
        item = paths[template]
        if not isinstance(item, dict):
            raise QaValidationError(f"paths['{template}'] must be an object")
        for method in _METHOD_KEYS:
            node = item.get(method)
            if not isinstance(node, dict):
                continue
            operations.append(_operation(template, method, node, version, base_evidence))
    if not operations:
        raise QaValidationError("document contains no operations")
    return operations


def operation_hash(operation: dict[str, Any]) -> str:
    """Hash the fields that define an operation's content, ignoring timestamps."""
    return sha256_json({
        "method": operation["method"],
        "path": operation["path"],
        "operation_id": operation.get("operation_id", ""),
        "summary": operation.get("summary", ""),
        "spec": operation.get("spec") or {},
    })


def diff_operations(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare stored catalog rows with a freshly normalized batch.

    ``missing`` entries are reported, never deleted: a reference dropping an
    endpoint invalidates it for new work but leaves existing cases pointing at it.
    """
    stored = {(row["method"], row["path"]): row for row in existing}
    incoming_by_key = {(item["method"], item["path"]): item for item in incoming}
    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged = 0
    for key, operation in incoming_by_key.items():
        row = stored.get(key)
        if row is None:
            added.append(operation)
            continue
        if operation_hash(operation) == row["content_hash"]:
            unchanged += 1
            continue
        before = {field: (row.get("spec") or {}).get(field) for field in _SPEC_FIELDS}
        after = {field: (operation.get("spec") or {}).get(field) for field in _SPEC_FIELDS}
        fields = sorted(
            {field for field in _SPEC_FIELDS if before[field] != after[field]}
            | {
                field for field in ("operation_id", "summary")
                if row.get(field, "") != operation.get(field, "")
            }
        )
        changed.append({"id": row["id"], "operation": operation, "fields": fields})
    missing = [
        {"id": row["id"], "method": row["method"], "path": row["path"]}
        for key, row in stored.items()
        if key not in incoming_by_key and row.get("status", "active") == "active"
    ]
    return {"added": added, "changed": changed, "missing": missing, "unchanged": unchanged}


def _operation(
    template: str,
    method: str,
    node: dict[str, Any],
    version: str,
    base_evidence: list[dict[str, str]],
) -> dict[str, Any]:
    spec = {
        "operation_id": optional_text(node.get("operationId"), "operationId", max_length=200),
        "summary": optional_text(node.get("summary"), "summary", max_length=500),
        "description": optional_text(node.get("description"), "description", max_length=4000),
        "tags": [str(tag) for tag in node.get("tags") or [] if isinstance(tag, (str, int))],
        "parameters": node.get("parameters") if isinstance(node.get("parameters"), list) else [],
        "request_body": node.get("requestBody") if isinstance(node.get("requestBody"), dict) else {},
        "responses": node.get("responses") if isinstance(node.get("responses"), dict) else {},
        "deprecated": bool(node.get("deprecated", False)),
        "security": node.get("security") if isinstance(node.get("security"), list) else [],
    }
    evidence = [*base_evidence, {
        "kind": "openapi",
        "ref": f"#/paths/{_escape_pointer(template)}/{method}",
        "version": version,
    }]
    return normalize_api_operation({
        "method": method.upper(),
        "path": template,
        "operation_id": spec["operation_id"],
        "summary": spec["summary"],
        "spec": spec,
        "evidence": evidence,
    })


def _escape_pointer(token: str) -> str:
    """Escape a path template for a JSON pointer reference."""
    return token.replace("~", "~0").replace("/", "~1")
