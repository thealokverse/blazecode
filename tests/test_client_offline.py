"""Tests for the offline-safe ProviderClient (no real API calls)."""

from __future__ import annotations

import asyncio
import os

import pytest

from blazecode.providers.client import ProviderClient, Turn
from blazecode.core.events import Error as ErrorEvent


async def test_stream_yields_error_on_bad_auth(monkeypatch):
    """When the provider returns an auth error, stream() yields an Error, never raises."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-this-is-not-a-real-key")
    pc = ProviderClient()
    pieces: list[object] = []
    try:
        async for p in pc.stream(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        ):
            pieces.append(p)
    except Exception as exc:
        pytest.fail(f"stream() raised: {type(exc).__name__}: {exc}")
    errors = [p for p in pieces if isinstance(p, ErrorEvent)]
    assert errors, f"expected an Error event, got {[type(p).__name__ for p in pieces]}"
    assert errors[0].recoverable is False  # auth errors are terminal


async def test_stream_yields_error_on_unreachable_host(monkeypatch):
    """When the network is down, stream() yields an Error, never raises."""
    monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:1")  # bad port
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    pc = ProviderClient()
    pieces: list[object] = []
    try:
        async for p in pc.stream(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
        ):
            pieces.append(p)
    except Exception as exc:
        pytest.fail(f"stream() raised: {type(exc).__name__}: {exc}")
    assert any(isinstance(p, ErrorEvent) for p in pieces), (
        f"expected an Error event, got {[type(p).__name__ for p in pieces]}"
    )


async def test_complete_returns_text_with_error_prefix_on_failure(monkeypatch):
    """complete() never raises; on failure the returned Turn.text starts with 'error:'."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    pc = ProviderClient()
    turn = await pc.complete(
        model="openrouter/anthropic/claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert isinstance(turn, Turn)
    assert turn.text.startswith("error:")


async def test_test_connection_reports_missing_key(monkeypatch):
    """test_connection catches missing API key without raising."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    pc = ProviderClient()
    ok, msg = await pc.test_connection("gpt-4o")
    assert ok is False
    assert "OPENAI_API_KEY" in msg


async def test_test_connection_ollama_no_key_needed(monkeypatch):
    """test_connection for ollama reports success without needing a key."""
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    pc = ProviderClient()
    ok, msg = await pc.test_connection("ollama/llama3")
    assert ok is True
    assert "ollama" in msg.lower()


async def test_stream_handles_text_then_error(monkeypatch):
    """If the stream yields text and then errors out, text is yielded first, then Error."""
    from openai import APIConnectionError

    class _FakeStream:
        def __init__(self):
            self.calls = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            self.calls += 1
            if self.calls == 1:
                chunk = type("C", (), {})()
                chunk.choices = [
                    type(
                        "Ch",
                        (),
                        {
                            "delta": type(
                                "D", (), {"content": "Hello ", "tool_calls": None}
                            )(),
                            "finish_reason": None,
                        },
                    )()
                ]
                chunk.usage = None
                return chunk
            raise APIConnectionError(request=None)

    import blazecode.providers.client as pc_mod
    orig_create = pc_mod.AsyncOpenAI

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def _create(self, **kwargs):
            if kwargs.get("stream"):
                resp = _FakeStream()

                async def _gen():
                    async for c in resp:
                        yield c

                return _gen()
            return None

        @property
        def chat(self):
            return type(
                "Chat",
                (),
                {"completions": type("C", (), {"create": self._create})()},
            )()

    pc_mod.AsyncOpenAI = _FakeClient
    try:
        pc = pc_mod.ProviderClient()
        pieces: list[object] = []
        async for p in pc.stream(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        ):
            pieces.append(p)
        text_chunks = [p for p in pieces if isinstance(p, str)]
        errors = [p for p in pieces if isinstance(p, ErrorEvent)]
        assert text_chunks, "expected at least one text chunk"
        assert text_chunks[0] == "Hello "
        assert errors, "expected an Error event after the text"
    finally:
        pc_mod.AsyncOpenAI = orig_create
