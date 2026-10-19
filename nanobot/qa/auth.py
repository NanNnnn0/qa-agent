"""Credentials for API runs: resolve references, obtain a token, mask it.

A run never persists a credential. Auth config either references an environment
variable (``env:NAME``) or holds a literal, the provider obtains at most one token
per run, and everything written to the run report passes through
:func:`mask_payload` first.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import httpx

from nanobot.qa.runner import json_path_get
from nanobot.qa.validation import (
    QaError,
    QaValidationError,
    optional_text,
    require_enum,
)

AUTH_KINDS = ("none", "bearer", "login")
MASK = "***"
_ENV_PREFIX = "env:"


class QaAuthError(QaError):
    """The run could not authenticate: the login endpoint or the credentials are wrong."""


def resolve_secret(value: Any, field: str) -> str:
    """Resolve a literal or an ``env:NAME`` reference to a non-empty secret."""
    text = optional_text(value, field, max_length=4000).strip()
    if not text:
        raise QaValidationError(f"{field} is required")
    if not text.startswith(_ENV_PREFIX):
        return text
    name = text[len(_ENV_PREFIX):].strip()
    if not name:
        raise QaValidationError(f"{field} must name an environment variable after 'env:'")
    secret = os.environ.get(name, "")
    if not secret:
        raise QaValidationError(f"environment variable '{name}' is empty or unset")
    return secret


def mask_text(text: str, secrets: Iterable[str]) -> str:
    masked = str(text)
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        masked = masked.replace(secret, MASK)
    return masked


def mask_payload(payload: Any, secrets: Iterable[str]) -> Any:
    """Replace every occurrence of a secret inside a JSON-like payload."""
    ordered = [item for item in secrets if item]
    if not ordered:
        return payload
    if isinstance(payload, str):
        return mask_text(payload, ordered)
    if isinstance(payload, dict):
        return {key: mask_payload(value, ordered) for key, value in payload.items()}
    if isinstance(payload, list):
        return [mask_payload(item, ordered) for item in payload]
    return payload


class AuthProvider:
    """Resolve the headers one run needs, and remember the secrets to mask.

    ``config`` is the ``auth`` object of a run request::

        {"kind": "bearer", "token": "env:QA_TOKEN"}
        {"kind": "login", "path": "/api/login",
         "body": {"user": "env:QA_USER", "password": "env:QA_PASS"},
         "token_path": "$.data.token"}
    """

    def __init__(
        self,
        config: dict[str, Any] | None,
        *,
        base_url: str,
        timeout_s: float = 15.0,
    ) -> None:
        if config is not None and not isinstance(config, dict):
            raise QaValidationError("auth must be a JSON object")
        self.config = dict(config or {})
        self.kind = require_enum(
            self.config.get("kind"), "auth.kind", AUTH_KINDS, default="none",
        )
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._headers: dict[str, str] = {}
        self._secrets: list[str] = []
        self._resolved = False

    def validate(self) -> None:
        """Check the config and its references without contacting the target."""
        if self.kind == "none":
            return
        if self.kind == "bearer":
            resolve_secret(self.config.get("token"), "auth.token")
            return
        path, body, token_path = self._login_parts()
        self._resolve_refs(body)
        if not token_path:
            raise QaValidationError("auth.token_path is required for a login")

    def headers(self) -> dict[str, str]:
        if not self._resolved:
            self._headers = self._obtain()
            self._resolved = True
        return dict(self._headers)

    def secrets(self) -> list[str]:
        return [secret for secret in self._secrets if secret]

    def _obtain(self) -> dict[str, str]:
        if self.kind == "none":
            return {}
        if self.kind == "bearer":
            token = resolve_secret(self.config.get("token"), "auth.token")
            self._secrets.append(token)
            return {self._header_name(): f"{self._prefix()}{token}"}
        return self._login()

    def _login(self) -> dict[str, str]:
        path, body, token_path = self._login_parts()
        payload = self._resolve_refs(body)
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise QaAuthError(f"login request failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise QaAuthError(f"login returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise QaAuthError("login response is not JSON") from exc
        try:
            token = json_path_get(data, token_path)
        except KeyError as exc:
            raise QaAuthError(f"login response has no value at {token_path}") from exc
        token_text = str(token)
        if not token_text:
            raise QaAuthError(f"login token at {token_path} is empty")
        self._secrets.append(token_text)
        return {self._header_name(): f"{self._prefix()}{token_text}"}

    def _login_parts(self) -> tuple[str, dict[str, Any], str]:
        path = optional_text(self.config.get("path"), "auth.path", max_length=500).strip()
        if not path:
            raise QaValidationError("auth.path is required for a login")
        body = self.config.get("body")
        if not isinstance(body, dict):
            raise QaValidationError("auth.body must be a JSON object")
        token_path = optional_text(
            self.config.get("token_path"), "auth.token_path", max_length=200,
        ).strip()
        return path, body, token_path

    def _resolve_refs(self, value: Any) -> Any:
        """Resolve ``env:NAME`` references inside the login body, keeping secrets."""
        if isinstance(value, str):
            if value.startswith(_ENV_PREFIX):
                secret = resolve_secret(value, "auth.body")
                self._secrets.append(secret)
                return secret
            return value
        if isinstance(value, dict):
            return {key: self._resolve_refs(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_refs(item) for item in value]
        return value

    def _header_name(self) -> str:
        return optional_text(
            self.config.get("header"), "auth.header", max_length=100,
        ).strip() or "Authorization"

    def _prefix(self) -> str:
        if "prefix" not in self.config:
            return "Bearer "
        return optional_text(self.config.get("prefix"), "auth.prefix", max_length=100)
