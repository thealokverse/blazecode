from __future__ import annotations

from functools import lru_cache
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

import httpx

from blazecode.config.settings import Model, Models, config_home

DEFAULT_CONTEXT_WINDOW = 128_000
MODEL_CACHE_TTL_SECONDS = 3600
MODEL_SELECTION_LIMIT = 6
MODEL_ENTRIES_CACHE_SECONDS = 24 * 3600  # 24 hours

# substring keys; longer keys win via length-sorted match in context_window()
CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5": 400_000,
    "gpt-4.1": 1_047_576,
    "o4-mini": 200_000,
    "o3": 200_000,
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude": 200_000,
    "gemini-2.5": 1_048_576,
    "gemini-2.0": 1_048_576,
    "gemini-3": 1_048_576,
    "gemini": 1_048_576,
    "glm-4.7": 200_000,
    "glm-4.6": 200_000,
    "glm-4.5": 128_000,
    "glm-4": 128_000,
    "deepseek": 128_000,
    "kimi": 128_000,
    "moonshot": 128_000,
    "minimax": 128_000,
    "qwen": 128_000,
    "grok": 128_000,
}


class KeyPolicy(Enum):
    NONE = "none"  # local provider, no key (ollama)
    ENV = "env"  # preferred env var, else prompt once at onboarding
    PROMPT = "prompt"  # always prompt; blank or env:VAR allowed (custom)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    label: str
    name: str
    base_url: str | None = None  # None => prompt at onboarding
    env_var: str | None = None
    key_policy: KeyPolicy = KeyPolicy.ENV
    ask_models: bool = False  # prompt for model ids (custom)


# onboarding order; Custom stays last
PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset("OpenAI", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    ProviderPreset("Anthropic", "anthropic", env_var="ANTHROPIC_API_KEY"),
    ProviderPreset(
        "Google",
        "google",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    ProviderPreset(
        "OpenRouter", "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"
    ),
    ProviderPreset("Groq", "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ProviderPreset("Z.ai", "zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
    ProviderPreset("Kimi", "kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    ProviderPreset(
        "DeepSeek", "deepseek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"
    ),
    ProviderPreset(
        "MiniMax", "minimax", "https://api.minimaxi.com/v1", "MINIMAX_API_KEY"
    ),
    ProviderPreset(
        "Ollama", "ollama", "http://localhost:11434/v1", key_policy=KeyPolicy.NONE
    ),
    ProviderPreset(
        "Custom (OpenAI-compatible)", "", key_policy=KeyPolicy.PROMPT, ask_models=True
    ),
)

# lower rank = better for agent work
_RANK_BOOSTS: tuple[tuple[str, int], ...] = (
    ("codex", -40),
    ("coder", -35),
    ("code", -20),
    ("gpt-5", -24),
    ("claude-opus-4", -22),
    ("claude-sonnet-4", -20),
    ("gemini-3", -20),
    ("gemini-2.5", -16),
    ("grok-4", -16),
    ("glm-4.7", -16),
    ("kimi-k2", -15),
    ("deepseek-r1", -14),
    ("deepseek-v3", -14),
    ("qwen3", -14),
    ("opus", -8),
    ("sonnet", -7),
    ("pro", -5),
    ("flash", 3),
    ("mini", 6),
    ("nano", 8),
)

_IRRELEVANT = (
    "audio",
    "dall-e",
    "embedding",
    "image",
    "moderation",
    "music",
    "realtime",
    "rerank",
    "speech",
    "sora",
    "transcri",
    "tts",
    "veo",
    "video",
    "voice",
    "whisper",
)

# drop stale chat models from large catalogs (self-hosted keeps them via fallback)
_DEPRECATED = (
    "-alpha",
    "-beta",
    "babbage",
    "chatgpt-",
    "claude-1",
    "claude-2",
    "claude-3-",
    "code-davinci",
    "curie",
    "davinci",
    "deprecated",
    "gemini-1",
    "gpt-3",
    "gpt-4",
    "legacy",
    "palm",
    "preview",
    "retired",
)


def context_window(model: str) -> int:
    lowered = model.lower()
    if lowered in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[lowered]
    model_entries = get_model_entries()
    if model_entries and model in model_entries.data:
        model_id = model.split("/")[-1]
        entry = model_entries.data[model_id]
        if isinstance(entry, Model) and entry.context_length:
            return entry.context_length
    # longest substring first so glm-4.7 beats glm-4
    for key in sorted(CONTEXT_WINDOWS, key=len, reverse=True):
        if key in lowered:
            return CONTEXT_WINDOWS[key]
    return DEFAULT_CONTEXT_WINDOW


def _cache_path(base_url: str) -> Path:
    safe = "".join(ch if ch.isalnum() else "_" for ch in base_url.lower())[:120]
    return config_home() / "cache" / f"models_{safe}.json"


def load_cached_models(
    base_url: str, *, ttl: int = MODEL_CACHE_TTL_SECONDS
) -> list[str] | None:
    path = _cache_path(base_url)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        stamped = float(payload.get("fetched_at", 0))
    except (TypeError, ValueError):
        return None
    if ttl > 0 and (time.time() - stamped) > ttl:
        return None
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        return None
    return [str(item) for item in models if item]


def save_cached_models(base_url: str, models: list[str]) -> None:
    if not models:
        return
    path = _cache_path(base_url)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "base_url": base_url,
                    "models": models,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        path.chmod(0o600)
    except OSError:
        return


def normalize_model_ids(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    data = raw.get("data", raw.get("models", []))
    if isinstance(data, dict):
        data = data.get("data", [])
    if not isinstance(data, list):
        return []
    found: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            found.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        identifier = item.get("id") or item.get("name") or item.get("model")
        if identifier:
            found.append(str(identifier))
    return sorted(set(found))


def rank_models(models: list[str], *, prefer: str | None = None) -> list[str]:
    prefer_l = (prefer or "").lower()

    def score(model: str) -> tuple[int, tuple[int, ...], str]:
        lowered = model.lower()
        rank = 50
        if prefer_l and prefer_l in lowered:
            rank -= 40
        for token, weight in _RANK_BOOSTS:
            if token in lowered:
                rank += weight
        versions = tuple(-int(value) for value in re.findall(r"\d+", lowered))
        return rank, versions, lowered

    return sorted(models, key=score)


def select_models(models: list[str], *, limit: int = MODEL_SELECTION_LIMIT) -> list[str]:
    """Compact, current list for the agent model picker."""
    unique = list(dict.fromkeys(model.strip() for model in models if model.strip()))
    relevant = [m for m in unique if not _has_token(m, _IRRELEVANT)]
    current = [m for m in relevant if not _has_token(m, _DEPRECATED)]
    # small/self-hosted catalogs may only expose older still-usable models
    ranked = rank_models(current or relevant)
    if ranked and all("glm-" in m.lower() for m in ranked):
        return ranked
    return ranked[:limit]


def _has_token(model: str, tokens: tuple[str, ...]) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in tokens)

@lru_cache(maxsize=1)
def get_model_entries() -> Models | None:
    models = Models.load()
    if models.data:
        return models
    return None

def get_model_entry_by_id(model_id: str) -> Model | None:
    models = get_model_entries()
    if models is None:
        return None
    data = models.data.get(model_id)
    return data if isinstance(data, Model) else None

async def fetch_models_entries(n: int = 100) -> None:
    models: Models = Models().load() if Models.load().data else Models()
    if models.last_updated and (time.time() - models.last_updated) < MODEL_ENTRIES_CACHE_SECONDS:
        print("Using cached model entries; last updated:", time.ctime(models.last_updated))
        print("wait for another", MODEL_ENTRIES_CACHE_SECONDS - (time.time() - models.last_updated))
        return
    else:
        print("Fetching model entries from OpenRouter...")
    with httpx.Client(timeout=5.0) as client:
        response = client.get(f"https://openrouter.ai/api/v1/models?limit={n}")
        response.raise_for_status()
        response_data: dict[str, list[dict[str, str]]] = response.json()
        data = response_data["data"]
        for model_entry in data:
            id = model_entry.get("id", "").split("/")[-1]
            provider = model_entry.get("id", "").split("/")[0]
            name = model_entry.get("name", "")
            context_length = int(model_entry.get("context_length", 0))
            pricing = cast(dict[str, Any], model_entry.get("pricing", {}))
            model = Model(
                provider=provider,
                id=id,
                name=name,
                context_length=context_length,
                pricing=pricing,
            )
            models.data[model.id] = model
    models.save()
