"""Tests for the session-scoped `/think` reasoning-effort command."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_think
from nanobot.command.router import CommandContext
from nanobot.config.schema import ModelPresetConfig
from nanobot.session.model_selection import (
    SESSION_REASONING_EFFORT_METADATA_KEY,
    reasoning_effort_from_metadata,
)
from nanobot.webui.session_projection import WebUISessionProjection


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "base-model"
    provider.generation = SimpleNamespace(
        max_tokens=123, temperature=0.1, reasoning_effort=None,
    )
    return provider


def _make_loop(tmp_path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets={
            "default": ModelPresetConfig(
                model="base-model", max_tokens=123, context_window_tokens=1000,
            ),
        },
    )


def _ctx(loop: AgentLoop, args: str = "") -> CommandContext:
    raw = f"/think {args}".strip()
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


def _metadata(loop: AgentLoop) -> dict:
    return loop.sessions.get_or_create("cli:direct").metadata


@pytest.mark.asyncio
async def test_think_status_shows_default_and_options(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    out = await cmd_think(_ctx(loop))
    assert "Current: `default`" in out.content
    assert "none, minimal, low, medium, high" in out.content
    assert "/think default" in out.content
    assert out.metadata == {"render_as": "text"}


@pytest.mark.asyncio
async def test_think_sets_and_applies_the_session_override(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_think(_ctx(loop, "high"))

    assert "Set thinking effort to `high`" in out.content
    assert reasoning_effort_from_metadata(_metadata(loop)) == "high"
    assert _metadata(loop)[SESSION_REASONING_EFFORT_METADATA_KEY] == "high"

    runtime = await loop.runtime_for_session(loop.sessions.get_or_create("cli:direct"))
    assert runtime.generation.reasoning_effort == "high"


@pytest.mark.asyncio
async def test_think_default_clears_the_override(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    await cmd_think(_ctx(loop, "low"))

    out = await cmd_think(_ctx(loop, "default"))

    assert "Cleared the session thinking effort" in out.content
    assert reasoning_effort_from_metadata(_metadata(loop)) is None
    runtime = await loop.runtime_for_session(loop.sessions.get_or_create("cli:direct"))
    assert runtime.generation.reasoning_effort is None


@pytest.mark.asyncio
async def test_think_rejects_unknown_values(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    out = await cmd_think(_ctx(loop, "turbo"))
    assert "Could not set thinking effort" in out.content
    assert "turbo" not in _metadata(loop).values()


@pytest.mark.asyncio
async def test_attach_fields_expose_the_override(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    await cmd_think(_ctx(loop, "medium"))

    projection = WebUISessionProjection(loop.sessions)
    fields = await projection.attach_fields("cli:direct")
    assert fields["reasoning_effort"] == "medium"
