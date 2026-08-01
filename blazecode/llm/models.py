from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from blazecode.config.settings import config_home

DEFAULT_CONTEXT_WINDOW = 128_000
MODEL_CACHE_TTL_SECONDS = 3600

CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "o4-mini": 200_000,
    "o3": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-opus-4": 200_000,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "glm-4.7": 200_000,
    "glm-4.6": 200_000,
    "glm-4.5": 128_000,
    "glm-4": 128_000,
}

# ordered onboarding presets: display name, provider name, base url, env var or none
PROVIDER_PRESETS: list[tuple[str, str, str, str | None]] = [
    ("OpenAI", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    (
        "Google",
        "google",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    ("OpenRouter", "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    ("Groq", "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ("Z.ai", "zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
    ("Kimi", "kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    ("Ollama", "ollama", "http://localhost:11434/v1", None),
]


def context_window(model: str) -> int:
    if model in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[model]
    lowered = model.lower()
    for key, value in CONTEXT_WINDOWS.items():
        if key in lowered:
            return value
    return DEFAULT_CONTEXT_WINDOW


def _cache_path(base_url: str) -> Path:
    safe = "".join(ch if ch.isalnum() else "_" for ch in base_url.lower())[:120]
    return config_home() / "cache" / f"models_{safe}.json"


def load_cached_models(base_url: str, *, ttl: int = MODEL_CACHE_TTL_SECONDS) -> list[str] | None:
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
        payload: dict[str, Any] = {
            "fetched_at": time.time(),
            "base_url": base_url,
            "models": models,
        }
        temporary.write_text(json.dumps(payload), encoding="utf-8")
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
    models: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            models.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        identifier = item.get("id") or item.get("name") or item.get("model")
        if identifier:
            models.append(str(identifier))
    return sorted(set(models))


def rank_models(models: list[str], *, prefer: str | None = None) -> list[str]:
    # stable sort that surfaces common coding models without dropping any
    prefer_l = (prefer or "").lower()

    def score(model: str) -> tuple[int, str]:
        lowered = model.lower()
        rank = 50
        if prefer_l and prefer_l in lowered:
            rank -= 40
        for token, weight in (
            ("coder", -12),
            ("code", -10),
            ("sonnet", -8),
            ("gpt-4.1", -8),
            ("gpt-4o", -6),
            ("gemini-2.5", -6),
            ("opus", -5),
            ("flash", -3),
            ("mini", -1),
            ("embed", 30),
            ("tts", 30),
            ("whisper", 30),
            ("image", 25),
            ("vision", 8),
            ("moderation", 30),
        ):
            if token in lowered:
                rank += weight
        return rank, lowered

    return sorted(models, key=score)
