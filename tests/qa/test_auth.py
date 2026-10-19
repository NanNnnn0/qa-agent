"""Tests for run credentials: resolution, login and masking."""

from __future__ import annotations

import pytest

from nanobot.qa.auth import (
    AuthProvider,
    QaAuthError,
    mask_payload,
    mask_text,
    resolve_secret,
)
from nanobot.qa.validation import QaValidationError


def test_resolve_secret_handles_literals_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_secret("plain", "token") == "plain"
    monkeypatch.setenv("QA_TOKEN", "from-env")
    assert resolve_secret("env:QA_TOKEN", "token") == "from-env"
    with pytest.raises(QaValidationError):
        resolve_secret("env:QA_TOKEN_MISSING", "token")
    with pytest.raises(QaValidationError):
        resolve_secret("", "token")


def test_bearer_provider_and_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QA_TOKEN", "secret-token")
    provider = AuthProvider({"kind": "bearer", "token": "env:QA_TOKEN"}, base_url="http://x")
    assert provider.headers() == {"Authorization": "Bearer secret-token"}
    assert provider.secrets() == ["secret-token"]
    assert mask_payload({"a": ["secret-token", "other"]}, provider.secrets()) == {
        "a": ["***", "other"]
    }
    assert mask_text("token=secret-token", provider.secrets()) == "token=***"


def test_bearer_honours_a_custom_header_and_prefix() -> None:
    provider = AuthProvider(
        {"kind": "bearer", "token": "t", "header": "X-Api-Key", "prefix": ""},
        base_url="http://x",
    )
    assert provider.headers() == {"X-Api-Key": "t"}


def test_validate_does_not_send_a_request() -> None:
    provider = AuthProvider(
        {
            "kind": "login",
            "path": "/api/login",
            "body": {"user": "u", "password": "p"},
            "token_path": "$.data.token",
        },
        base_url="http://127.0.0.1:1",
    )
    provider.validate()


def test_login_provider_obtains_a_token(demo_api: str) -> None:
    provider = AuthProvider(
        {
            "kind": "login",
            "path": "/api/login",
            "body": {"user": "qa", "password": "qa-pass"},
            "token_path": "$.data.token",
        },
        base_url=demo_api,
    )
    headers = provider.headers()
    token = provider.secrets()[0]
    assert token.startswith("tok_")
    assert headers["Authorization"] == f"Bearer {token}"


def test_login_body_reads_env_references(
    demo_api: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QA_USER", "qa")
    monkeypatch.setenv("QA_PASS", "qa-pass")
    provider = AuthProvider(
        {
            "kind": "login",
            "path": "/api/login",
            "body": {"user": "env:QA_USER", "password": "env:QA_PASS"},
            "token_path": "$.data.token",
        },
        base_url=demo_api,
    )
    assert provider.headers()["Authorization"].startswith("Bearer tok_")
    assert "qa-pass" in provider.secrets()


def test_login_failure_is_an_auth_error(demo_api: str) -> None:
    provider = AuthProvider(
        {
            "kind": "login",
            "path": "/api/login",
            "body": {"user": "qa", "password": "wrong"},
            "token_path": "$.data.token",
        },
        base_url=demo_api,
    )
    with pytest.raises(QaAuthError):
        provider.headers()


def test_login_requires_a_token_path() -> None:
    provider = AuthProvider(
        {"kind": "login", "path": "/api/login", "body": {"user": "qa"}},
        base_url="http://x",
    )
    with pytest.raises(QaValidationError):
        provider.validate()


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(QaValidationError):
        AuthProvider({"kind": "magic"}, base_url="http://x")
