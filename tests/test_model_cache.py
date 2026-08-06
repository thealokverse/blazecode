from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from blazecode.llm.client import list_models
from blazecode.llm.models import (
    PROVIDER_PRESETS,
    load_cached_models,
    normalize_model_ids,
    rank_models,
    save_cached_models,
    select_models,
)


def test_provider_preset_order() -> None:
    names = [preset.name for preset in PROVIDER_PRESETS]
    labels = [preset.label for preset in PROVIDER_PRESETS]
    assert names == [
        "openai",
        "anthropic",
        "google",
        "openrouter",
        "groq",
        "zai",
        "kimi",
        "deepseek",
        "minimax",
        "ollama",
        "",
    ]
    assert labels == [
        "OpenAI",
        "Anthropic",
        "Google",
        "OpenRouter",
        "Groq",
        "Z.ai",
        "Kimi",
        "DeepSeek",
        "MiniMax",
        "Ollama",
        "Custom (OpenAI-compatible)",
    ]


def test_provider_presets_are_well_formed() -> None:
    names = [preset.name for preset in PROVIDER_PRESETS]
    assert len(names) == len(set(names))
    for preset in PROVIDER_PRESETS:
        if preset.base_url:
            assert preset.base_url.startswith(("http://", "https://"))


def test_normalize_and_rank_models() -> None:
    models = normalize_model_ids(
        {
            "data": [
                {"id": "vendor/embed-model"},
                {"id": "vendor/gpt-4.1-coder"},
                {"name": "other-model"},
            ]
        }
    )
    ranked = rank_models(models)
    assert ranked[0] == "vendor/gpt-4.1-coder"
    assert "vendor/embed-model" in ranked


def test_model_selection_keeps_current_text_models_and_caps_large_catalogs() -> None:
    models = [
        "openai/gpt-4o",
        "openai/gpt-5.2-codex",
        "openai/gpt-5.2",
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "google/gemini-3-pro",
        "z-ai/glm-4.7",
        "openai/text-embedding-3-large",
        "openai/gpt-image-1",
        "openai/omni-moderation-latest",
        "openai/whisper-1",
    ]
    selected = select_models(models)
    assert len(selected) == 6
    assert "openai/gpt-5.2-codex" in selected
    assert "openai/gpt-4o" not in selected
    assert not {"embedding", "image", "moderation", "whisper"} & {
        token for model in selected for token in model.lower().split("-")
    }


def test_model_selection_keeps_all_relevant_small_provider_models() -> None:
    models = [f"glm-4.{version}" for version in range(8)]
    assert select_models(models) == list(reversed(models))


def test_model_cache_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    save_cached_models("https://example.test/v1", ["m2", "m1"])
    assert load_cached_models("https://example.test/v1") == ["m2", "m1"]


@pytest.mark.asyncio
async def test_list_models_falls_back_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    save_cached_models("https://example.test/v1", ["cached-model"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "down"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = await list_models(
            "https://example.test/v1", None, client=client, use_cache=True
        )
    assert models == ["cached-model"]
