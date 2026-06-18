"""Tests for the provider registry (model-string resolution + shortcuts)."""

import pytest

from blazecode.engine.errors import ModelNotFoundError
from blazecode.providers.registry import (
    SHORTCUTS,
    provider_from_model,
    resolve_model,
)


def test_resolve_shortcuts():
    assert resolve_model("gpt") == "gpt-5"
    assert resolve_model("claude") == "anthropic/claude-sonnet-4-6"
    assert resolve_model("gemini") == "gemini/gemini-2.5-pro"
    assert resolve_model("groq") == "groq/llama-3.3-70b-versatile"
    assert resolve_model("ollama") == "ollama/llama3"


def test_resolve_passthrough_with_provider_prefix():
    assert resolve_model("openai/gpt-4o") == "openai/gpt-4o"
    assert resolve_model("anthropic/claude-3-7-sonnet-latest") == "anthropic/claude-3-7-sonnet-latest"


def test_resolve_unknown_raises():
    with pytest.raises(ModelNotFoundError) as excinfo:
        resolve_model("totallynotreal")
    msg = str(excinfo.value)
    assert "unknown" in msg.lower()
    assert "claude" in msg  # at least one known shortcut listed


def test_resolve_empty_raises():
    with pytest.raises(ModelNotFoundError):
        resolve_model("")


def test_provider_from_model():
    assert provider_from_model("gpt-5") == "openai"
    assert provider_from_model("claude-sonnet-4-6") == "anthropic"
    assert provider_from_model("gemini-2.5-pro") == "google"
    assert provider_from_model("openrouter/foo") == "openrouter"
    assert provider_from_model("ollama/llama3") == "ollama"
    assert provider_from_model("weird-model") == "unknown"


def test_shortcuts_table_shape():
    assert isinstance(SHORTCUTS, dict)
    assert len(SHORTCUTS) >= 5
    for k, v in SHORTCUTS.items():
        assert isinstance(k, str) and isinstance(v, str)
        assert v  # non-empty
