"""Tests for the provider registry."""
import pytest

from blazecode.core.errors import ModelNotFoundError
from blazecode.providers.registry import (
    PROVIDERS,
    SHORTCUTS,
    provider_shortcut_for_model,
    resolve_model,
)


def test_resolve_shortcuts():
    assert resolve_model("gpt") == "gpt-4o"
    assert resolve_model("claude") == "anthropic/claude-sonnet-4-6"
    assert resolve_model("gemini") == "gemini/gemini-2.5-pro"
    assert resolve_model("groq") == "groq/llama-3.3-70b-versatile"
    assert resolve_model("ollama") == "ollama/llama3"


def test_resolve_passthrough():
    assert resolve_model("openai/gpt-4o") == "openai/gpt-4o"
    assert resolve_model("anthropic/claude-3-7-sonnet-latest") == "anthropic/claude-3-7-sonnet-latest"


def test_resolve_unknown_raises():
    with pytest.raises(ModelNotFoundError) as excinfo:
        resolve_model("totallynotreal")
    msg = str(excinfo.value)
    assert "unknown" in msg.lower()
    assert "claude" in msg


def test_resolve_empty_raises():
    with pytest.raises(ModelNotFoundError):
        resolve_model("")


def test_provider_shortcut_from_model():
    assert provider_shortcut_for_model("gpt-4o") == "openai"
    assert provider_shortcut_for_model("claude-sonnet-4-6") == "anthropic"
    assert provider_shortcut_for_model("gemini-2.5-pro") == "gemini"
    assert provider_shortcut_for_model("openrouter/foo") == "openrouter"
    assert provider_shortcut_for_model("ollama/llama3") == "ollama"
    assert provider_shortcut_for_model("weird-model") == "unknown"


def test_providers_have_examples():
    for name, info in PROVIDERS.items():
        assert info.examples
        assert isinstance(info.needs_key, bool)
