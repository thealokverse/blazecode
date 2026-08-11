from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from blazecode.config.settings import config_home

DEFAULT_CONTEXT_WINDOW = 128_000
MODEL_CACHE_TTL_SECONDS = 3600
MODEL_SELECTION_LIMIT = 6


@dataclass(frozen=True, slots=True)
class ModelInfo:
    # curated metadata used for ranking and context windows
    id: str
    provider: str
    context_window: int = DEFAULT_CONTEXT_WINDOW
    tools: bool = True
    reasoning: bool = False
    vision: bool = False
    deprecated: bool = False


# known models blazecode actually uses for windows/ranking; ids are substrings
KNOWN_MODELS: tuple[ModelInfo, ...] = (
    # openai
    ModelInfo("gpt-5.6-sol", "openai", 1_048_576, reasoning=True, vision=True),
    ModelInfo("gpt-5.6-terra", "openai", 1_048_576, reasoning=True, vision=True),
    ModelInfo("gpt-5.6-luna", "openai", 1_048_576, reasoning=True, vision=True),
    ModelInfo("gpt-5.6", "openai", 1_048_576, reasoning=True, vision=True),
    ModelInfo("gpt-5.2", "openai", 400_000, reasoning=True, vision=True),
    ModelInfo("gpt-5", "openai", 400_000, reasoning=True, vision=True),
    ModelInfo("gpt-4.1", "openai", 1_047_576, vision=True),
    ModelInfo("o4-mini", "openai", 200_000, reasoning=True),
    ModelInfo("o3", "openai", 200_000, reasoning=True),
    # anthropic
    ModelInfo("claude-fable-5", "anthropic", 1_000_000, reasoning=True, vision=True),
    ModelInfo("claude-opus-5", "anthropic", 1_000_000, reasoning=True, vision=True),
    ModelInfo("claude-sonnet-5", "anthropic", 1_000_000, reasoning=True, vision=True),
    ModelInfo("claude-haiku-4-5", "anthropic", 200_000, reasoning=True, vision=True),
    ModelInfo("claude-opus-4", "anthropic", 200_000, reasoning=True, vision=True),
    ModelInfo("claude-sonnet-4", "anthropic", 200_000, reasoning=True, vision=True),
    ModelInfo("claude", "anthropic", 200_000, vision=True),
    # google
    ModelInfo("gemini-3", "google", 1_048_576, vision=True),
    ModelInfo("gemini-2.5", "google", 1_048_576, vision=True),
    ModelInfo("gemini-2.0", "google", 1_048_576, vision=True),
    ModelInfo("gemini", "google", 1_048_576, vision=True),
    # deepseek
    ModelInfo("deepseek-v4-pro", "deepseek", 128_000, reasoning=True),
    ModelInfo("deepseek-v4-flash", "deepseek", 128_000, reasoning=True),
    ModelInfo("deepseek-r1", "deepseek", 128_000, reasoning=True),
    ModelInfo("deepseek-v3", "deepseek", 128_000),
    ModelInfo("deepseek", "deepseek", 128_000),
    # groq hosted
    ModelInfo("llama-3.3-70b", "groq", 131_072),
    ModelInfo("llama-3.1-8b", "groq", 131_072),
    ModelInfo("gpt-oss-120b", "groq", 131_072, reasoning=True),
    ModelInfo("gpt-oss-20b", "groq", 131_072, reasoning=True),
    # others common via openrouter / vendor apis
    ModelInfo("glm-4.7", "zai", 200_000),
    ModelInfo("glm-4.6", "zai", 200_000),
    ModelInfo("glm-4.5", "zai", 128_000),
    ModelInfo("glm-4", "zai", 128_000),
    ModelInfo("kimi", "kimi", 128_000),
    ModelInfo("moonshot", "kimi", 128_000),
    ModelInfo("minimax", "minimax", 128_000),
    ModelInfo("qwen", "qwen", 128_000),
    ModelInfo("grok", "xai", 128_000),
)

# longest id first for substring match
_CONTEXT_LOOKUP: tuple[tuple[str, int], ...] = tuple(
    sorted(
        ((model.id, model.context_window) for model in KNOWN_MODELS),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


class KeyPolicy(Enum):
    NONE = "none"
    ENV = "env"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    label: str
    name: str
    base_url: str | None = None
    env_var: str | None = None
    key_policy: KeyPolicy = KeyPolicy.ENV
    ask_models: bool = False


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
    ("gpt-5.6-sol", -30),
    ("gpt-5.6-terra", -26),
    ("gpt-5.6", -24),
    ("gpt-5.2", -23),
    ("gpt-5", -22),
    ("claude-fable-5", -28),
    ("claude-opus-5", -26),
    ("claude-sonnet-5", -24),
    ("claude-opus-4", -22),
    ("claude-sonnet-4", -20),
    ("claude-haiku-4-5", -12),
    ("gemini-3", -20),
    ("gemini-2.5", -16),
    ("deepseek-v4-pro", -18),
    ("deepseek-v4-flash", -14),
    ("deepseek-r1", -14),
    ("deepseek-v3", -14),
    ("gpt-oss-120b", -15),
    ("llama-3.3-70b", -12),
    ("grok-4", -16),
    ("glm-4.7", -16),
    ("kimi-k2", -15),
    ("qwen3", -14),
    ("opus", -8),
    ("sonnet", -7),
    ("pro", -5),
    ("flash", 3),
    ("mini", 6),
    ("nano", 8),
    ("luna", 4),
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
    "cyber",
    "daybreak",
)

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
    for key, window in _CONTEXT_LOOKUP:
        if key in lowered:
            return window
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
    unique = list(dict.fromkeys(model.strip() for model in models if model.strip()))
    relevant = [m for m in unique if not _has_token(m, _IRRELEVANT)]
    current = [m for m in relevant if not _has_token(m, _DEPRECATED)]
    ranked = rank_models(current or relevant)
    if ranked and all("glm-" in m.lower() for m in ranked):
        return ranked
    return ranked[:limit]


def _has_token(model: str, tokens: tuple[str, ...]) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in tokens)
