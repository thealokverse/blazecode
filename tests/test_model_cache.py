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
)


def test_provider_preset_order() -> None:
    names = [item[1] for item in PROVIDER_PRESETS]
    assert names == [
        "openai",
        "google",
        "openrouter",
        "groq",
        "zai",
        "kimi",
        "ollama",
    ]


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
