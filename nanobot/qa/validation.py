"""Validation and normalization for QA platform entities.

The module is intentionally dependency-free so the SQLite store, the agent
tools, the HTTP API and the MCP server all validate through one contract.
Deterministic artifacts are the point: the model must emit these shapes.
"""

from __future__ import annotations

import re
from typing import Any

PROJECT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")
CASE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")

CASE_KINDS = ("api", "ui", "manual")
CASE_PRIORITIES = ("P0", "P1", "P2", "P3")
CASE_STATUSES = ("draft", "ready", "deprecated")
CASE_SOURCES = ("manual", "ai", "import")

TASK_ROLES = ("orchestrator", "api", "ui", "automation", "review")
TASK_STATUSES = ("queued", "running", "needs_review", "blocked", "done", "failed", "cancelled")
SCRIPT_FRAMEWORKS = ("pytest", "playwright", "postman", "http", "karate")
RUN_STATUSES = ("running", "passed", "failed", "error", "blocked_by_env", "cancelled")
RUN_TRIGGERS = ("manual", "ci", "agent", "schedule")

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

ASSERTION_TYPES = ("status", "json_path", "header", "response_time_ms", "body_contains")
ASSERTION_OPS = ("equals", "exists", "contains", "gt", "lt", "matches")


class QaError(Exception):
    """Base error for QA platform operations."""


class QaValidationError(QaError):
    """The caller supplied an invalid field; maps to HTTP 400."""


class QaNotFoundError(QaError):
    """The requested entity does not exist; maps to HTTP 404."""


class QaConflictError(QaError):
    """The operation conflicts with current state; maps to HTTP 409."""


def require_text(value: Any, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QaValidationError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > max_length:
        raise QaValidationError(f"{field} must be at most {max_length} characters")
    return text


def optional_text(value: Any, field: str, *, max_length: int = 20_000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise QaValidationError(f"{field} must be a string")
    if len(value) > max_length:
        raise QaValidationError(f"{field} must be at most {max_length} characters")
    return value


def require_enum(value: Any, field: str, allowed: tuple[str, ...], *, default: str | None = None) -> str:
    if value is None:
        if default is not None:
            return default
        raise QaValidationError(f"{field} is required")
    if not isinstance(value, str) or value not in allowed:
        raise QaValidationError(f"{field} must be one of {', '.join(allowed)}")
    return value


def normalize_project_key(value: Any) -> str:
    if not isinstance(value, str) or not PROJECT_KEY_RE.match(value.strip()):
        raise QaValidationError(
            "key must start with a letter and contain 2-32 letters, digits, '_' or '-'"
        )
    return value.strip().upper()


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",")]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        raw = [item.strip() for item in value]
    else:
        raise QaValidationError("tags must be a list of strings")
    seen: list[str] = []
    for tag in raw:
        if tag and tag not in seen:
            seen.append(tag[:64])
    if len(seen) > 32:
        raise QaValidationError("at most 32 tags are allowed")
    return seen


def normalize_json_object(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise QaValidationError(f"{field} must be a JSON object")
    return value


def _string_map(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise QaValidationError(f"{field} must be a JSON object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise QaValidationError(f"{field} keys must be strings")
        result[key] = "" if item is None else str(item)
    return result


def validate_api_spec(api: Any) -> dict[str, Any]:
    """Validate the structured API-case contract used by the built-in runner."""
    if api is None or api == {}:
        return {}
    if not isinstance(api, dict):
        raise QaValidationError("api must be a JSON object")
    request = api.get("request")
    if not isinstance(request, dict):
        raise QaValidationError("api.request must be a JSON object")
    method = str(request.get("method") or "GET").upper()
    if method not in HTTP_METHODS:
        raise QaValidationError(f"api.request.method must be one of {', '.join(HTTP_METHODS)}")
    path = request.get("path")
    if not isinstance(path, str) or not path.strip():
        raise QaValidationError("api.request.path must be a non-empty string")
    body = request.get("body")
    if body is not None and not isinstance(body, (dict, list, str, int, float, bool)):
        raise QaValidationError("api.request.body must be JSON-serializable")

    assertions = api.get("assertions", [])
    if not isinstance(assertions, list):
        raise QaValidationError("api.assertions must be an array")
    normalized_assertions: list[dict[str, Any]] = []
    for index, assertion in enumerate(assertions):
        if not isinstance(assertion, dict):
            raise QaValidationError(f"api.assertions[{index}] must be an object")
        kind = assertion.get("type")
        if kind not in ASSERTION_TYPES:
            raise QaValidationError(
                f"api.assertions[{index}].type must be one of {', '.join(ASSERTION_TYPES)}"
            )
        item: dict[str, Any] = {"type": kind}
        if kind == "status":
            expect = assertion.get("expect", 200)
            if not isinstance(expect, int) or isinstance(expect, bool):
                raise QaValidationError(f"api.assertions[{index}].expect must be an integer")
            item["expect"] = expect
        elif kind == "json_path":
            path_value = assertion.get("path")
            if not isinstance(path_value, str) or not path_value.startswith("$"):
                raise QaValidationError(
                    f"api.assertions[{index}].path must be a JSONPath string starting with '$'"
                )
            op = assertion.get("op", "equals")
            if op not in ASSERTION_OPS:
                raise QaValidationError(
                    f"api.assertions[{index}].op must be one of {', '.join(ASSERTION_OPS)}"
                )
            item["path"] = path_value
            item["op"] = op
            if op != "exists":
                item["expect"] = assertion.get("expect")
        elif kind == "header":
            name = assertion.get("name")
            if not isinstance(name, str) or not name.strip():
                raise QaValidationError(f"api.assertions[{index}].name is required")
            if "contains" not in assertion and "equals" not in assertion:
                raise QaValidationError(
                    f"api.assertions[{index}] needs 'contains' or 'equals'"
                )
            item["name"] = name.strip().lower()
            if "equals" in assertion:
                item["equals"] = assertion["equals"]
            else:
                item["contains"] = assertion.get("contains", "")
        elif kind == "response_time_ms":
            maximum = assertion.get("max", 3000)
            if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or maximum <= 0:
                raise QaValidationError(f"api.assertions[{index}].max must be a positive number")
            item["max"] = maximum
        elif kind == "body_contains":
            text = assertion.get("text")
            if not isinstance(text, str) or not text:
                raise QaValidationError(f"api.assertions[{index}].text is required")
            item["text"] = text
        normalized_assertions.append(item)

    spec: dict[str, Any] = {
        "request": {
            "method": method,
            "path": path.strip(),
            "headers": _string_map(request.get("headers"), "api.request.headers"),
            "query": _string_map(request.get("query"), "api.request.query"),
            "body": body,
        },
        "assertions": normalized_assertions,
        "variables": _string_map(api.get("variables"), "api.variables"),
    }
    return spec


def validate_steps(steps: Any) -> list[dict[str, str]]:
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise QaValidationError("steps must be an array")
    normalized: list[dict[str, str]] = []
    for index, step in enumerate(steps):
        if isinstance(step, str):
            normalized.append({"action": step, "expected": ""})
            continue
        if not isinstance(step, dict):
            raise QaValidationError(f"steps[{index}] must be an object")
        action = step.get("action")
        if not isinstance(action, str) or not action.strip():
            raise QaValidationError(f"steps[{index}].action is required")
        expected = step.get("expected", "")
        if not isinstance(expected, str):
            raise QaValidationError(f"steps[{index}].expected must be a string")
        normalized.append({"action": action.strip(), "expected": expected.strip()})
    return normalized


def case_prefix(project_key: str) -> str:
    return project_key.upper()
