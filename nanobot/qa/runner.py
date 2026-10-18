"""Execute structured API test cases against a project base URL.

The runner is intentionally small and deterministic: cases carry the request
and assertions as JSON, so results never depend on model interpretation.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_INDEX_RE = re.compile(r"\[(\d+)\]")
_KEY_INDEX_RE = re.compile(r"\[\s*['\"]([^'\"]+)['\"]\s*\]")


class CaseExecutionError(ValueError):
    """A case cannot be executed as written."""


def render(value: Any, variables: dict[str, str]) -> Any:
    """Recursively substitute ``{{name}}`` placeholders in JSON-like values."""

    def substitute(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            return str(variables.get(name, match.group(0)))
        return TEMPLATE_RE.sub(replace, text)

    if isinstance(value, str):
        return substitute(value)
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    return value


def json_path_tokens(path: str) -> list[str | int]:
    """Parse the JSONPath subset we support: ``$.a.b[0]["c"]``."""
    if not path.startswith("$"):
        raise CaseExecutionError(f"JSONPath must start with '$': {path}")
    rest = path[1:]
    tokens: list[str | int] = []
    while rest:
        if rest.startswith("."):
            rest = rest[1:]
            match = re.match(r"[A-Za-z0-9_-]+", rest)
            if not match:
                raise CaseExecutionError(f"invalid JSONPath: {path}")
            tokens.append(match.group(0))
            rest = rest[match.end():]
            continue
        index_match = _INDEX_RE.match(rest)
        if index_match:
            tokens.append(int(index_match.group(1)))
            rest = rest[index_match.end():]
            continue
        key_match = _KEY_INDEX_RE.match(rest)
        if key_match:
            tokens.append(key_match.group(1))
            rest = rest[key_match.end():]
            continue
        raise CaseExecutionError(f"invalid JSONPath: {path}")
    return tokens


def json_path_get(data: Any, path: str) -> Any:
    """Return the value at ``path``; raises ``KeyError`` when it is absent."""
    current = data
    for token in json_path_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise KeyError(path)
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise KeyError(path)
            current = current[token]
    return current


def _compare(actual: Any, expected: Any, op: str) -> bool:
    if op == "equals":
        return actual == expected
    if op == "contains":
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, list):
            return expected in actual
        return False
    if op == "gt":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    if op == "matches":
        try:
            return re.search(str(expected), str(actual)) is not None
        except re.error:
            return False
    return False


def _check(assertion: dict[str, Any], response: httpx.Response, elapsed_ms: float,
           body_json: Any, body_error: str | None) -> dict[str, Any]:
    kind = assertion["type"]
    check: dict[str, Any] = {"type": kind}
    if kind == "status":
        actual = response.status_code
        check.update(expected=assertion["expect"], actual=actual,
                     passed=actual == assertion["expect"])
        return check
    if kind == "header":
        actual = response.headers.get(assertion["name"], "")
        if "equals" in assertion:
            passed = actual.lower() == str(assertion["equals"]).lower()
            check.update(expected=assertion["equals"], actual=actual, passed=passed)
        else:
            passed = str(assertion["contains"]).lower() in actual.lower()
            check.update(expected=f"contains {assertion['contains']}", actual=actual,
                         passed=passed)
        return check
    if kind == "response_time_ms":
        passed = elapsed_ms <= float(assertion["max"])
        check.update(expected=f"<= {assertion['max']}ms", actual=f"{elapsed_ms:.0f}ms",
                     passed=passed)
        return check
    if kind == "body_contains":
        actual = response.text
        passed = assertion["text"] in actual
        check.update(expected=f"contains {assertion['text']}", actual=actual[:200],
                     passed=passed)
        return check
    # json_path
    path = assertion["path"]
    op = assertion["op"]
    if body_error is not None:
        check.update(expected=path, actual=None, passed=False, error=body_error)
        return check
    try:
        actual = json_path_get(body_json, path)
    except (KeyError, CaseExecutionError):
        if op == "exists":
            check.update(expected="exists", actual=None, passed=False)
        else:
            check.update(expected=assertion.get("expect"), actual=None, passed=False,
                         error=f"missing JSONPath {path}")
        return check
    if op == "exists":
        check.update(expected="exists", actual=actual, passed=True)
        return check
    check.update(expected=assertion.get("expect"), actual=actual,
                 passed=_compare(actual, assertion.get("expect"), op))
    return check


class CaseRunner:
    """Run structured API cases with httpx."""

    def __init__(
        self,
        base_url: str,
        *,
        default_headers: dict[str, str] | None = None,
        timeout_s: float = 15.0,
        follow_redirects: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = dict(default_headers or {})
        self.timeout_s = timeout_s
        self.follow_redirects = follow_redirects

    def run_case(self, case: dict[str, Any], variables: dict[str, str] | None = None
                 ) -> dict[str, Any]:
        spec = case.get("api") or {}
        request = spec.get("request") or {}
        if not request:
            return {
                "case_id": case.get("id"),
                "code": case.get("code"),
                "title": case.get("title"),
                "status": "error",
                "duration_ms": 0,
                "message": "case has no api.request (not an executable API case)",
                "checks": [],
            }
        merged: dict[str, str] = dict(variables or {})
        merged.update({str(k): str(v) for k, v in (spec.get("variables") or {}).items()})
        request = render(request, merged)
        method = str(request.get("method", "GET")).upper()
        path = str(request.get("path", "/"))
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        headers = {**self.default_headers, **{
            str(k): str(v) for k, v in (request.get("headers") or {}).items()
        }}
        query = {str(k): str(v) for k, v in (request.get("query") or {}).items()}
        body = request.get("body")
        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=self.timeout_s,
                follow_redirects=self.follow_redirects,
            ) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    params=query,
                    json=body if isinstance(body, (dict, list)) else None,
                    content=body.encode("utf-8") if isinstance(body, str) else None,
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
        except httpx.HTTPError as exc:
            return {
                "case_id": case.get("id"),
                "code": case.get("code"),
                "title": case.get("title"),
                "status": "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "message": f"{type(exc).__name__}: {exc}",
                "request": {"method": method, "url": url},
                "checks": [],
            }

        body_json: Any = None
        body_error: str | None = None
        try:
            body_json = response.json()
        except ValueError:
            body_error = "response body is not valid JSON"
        checks = [
            _check(assertion, response, elapsed_ms, body_json, body_error)
            for assertion in (spec.get("assertions") or [])
        ]
        passed = all(check.get("passed") for check in checks)
        failed_checks = [check for check in checks if not check.get("passed")]
        message = ""
        if not passed:
            message = "; ".join(
                f"{check['type']} expected {check.get('expected')!r} got "
                f"{check.get('actual')!r}"[:300]
                for check in failed_checks
            )
        return {
            "case_id": case.get("id"),
            "code": case.get("code"),
            "title": case.get("title"),
            "status": "passed" if passed else "failed",
            "duration_ms": int(elapsed_ms),
            "message": message,
            "request": {"method": method, "url": url},
            "response": {
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "body_preview": response.text[:1000],
            },
            "checks": checks,
        }

    def run_cases(
        self, cases: list[dict[str, Any]], variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        started_ms = int(time.time() * 1000)
        started = time.perf_counter()
        tests = [self.run_case(case, variables) for case in cases]
        duration_ms = int((time.perf_counter() - started) * 1000)
        summary = {
            "tests": len(tests),
            "passed": sum(1 for test in tests if test["status"] == "passed"),
            "failed": sum(1 for test in tests if test["status"] == "failed"),
            "skipped": sum(1 for test in tests if test["status"] == "skipped"),
            "error": sum(1 for test in tests if test["status"] == "error"),
            "duration": duration_ms,
        }
        return {
            "reportFormat": "qa-agent.api.v1",
            "summary": summary,
            "tests": tests,
            "startedAt": started_ms,
            "finishedAt": started_ms + duration_ms,
        }
