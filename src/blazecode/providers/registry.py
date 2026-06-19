"""Provider registry: friendly shortcuts, known models, base URLs, env hints."""

from __future__ import annotations

from dataclasses import dataclass

from blazecode.core.errors import ModelNotFoundError


@dataclass(frozen=True)
class ProviderInfo:
    shortcut: str
    name: str
    base_url: str
    examples: tuple[str, ...]
    env_var: str | None
    needs_key: bool = True
    notes: str = ""


SHORTCUTS: dict[str, str] = {
    "gpt": "gpt-4o",
    "gpt4": "gpt-4o",
    "gpt-4o": "gpt-4o",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "claude": "anthropic/claude-sonnet-4-6",
    "claude-opus": "anthropic/claude-opus-4-6",
    "claude-haiku": "anthropic/claude-haiku-4-5",
    "gemini": "gemini/gemini-2.5-pro",
    "gemini-flash": "gemini/gemini-2.5-flash",
    "groq": "groq/llama-3.3-70b-versatile",
    "groq-fast": "groq/llama-3.1-8b-instant",
    "ollama": "ollama/llama3",
    "ollama-codellama": "ollama/codellama",
    "openrouter": "openrouter/anthropic/claude-sonnet-4-6",
}


PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        shortcut="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        examples=("gpt-4o", "gpt-4.1", "gpt-4.1-mini"),
        env_var="OPENAI_API_KEY",
    ),
    "anthropic": ProviderInfo(
        shortcut="anthropic",
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        examples=(
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-haiku-4-5",
        ),
        env_var="ANTHROPIC_API_KEY",
    ),
    "gemini": ProviderInfo(
        shortcut="gemini",
        name="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        examples=("gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash"),
        env_var="GEMINI_API_KEY",
    ),
    "groq": ProviderInfo(
        shortcut="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        examples=("groq/llama-3.3-70b-versatile", "groq/llama-3.1-8b-instant"),
        env_var="GROQ_API_KEY",
    ),
    "openrouter": ProviderInfo(
        shortcut="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        examples=(
            "openrouter/anthropic/claude-sonnet-4-6",
            "openrouter/openai/gpt-4o",
            "openrouter/google/gemini-2.0-flash-exp:free",
        ),
        env_var="OPENROUTER_API_KEY",
    ),
    "ollama": ProviderInfo(
        shortcut="ollama",
        name="Ollama (local)",
        base_url="http://localhost:11434/v1",
        examples=("ollama/llama3", "ollama/codellama"),
        env_var=None,
        needs_key=False,
        notes="No API key needed; requires a running Ollama server (http://localhost:11434).",
    ),
}


def provider_shortcut_for_model(model: str) -> str:
    """Return the provider label for an OpenAI model string."""
    m = model.lower()
    if "/" in m:
        return m.split("/", 1)[0]
    if m.startswith("gpt"):
        return "openai"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gemini"):
        return "gemini"
    return "unknown"


def resolve_model(name: str) -> str:
    """Resolve a shortcut or pass through a full model string."""
    if not name:
        raise ModelNotFoundError("model name is empty")
    if "/" in name:
        return name
    if name in SHORTCUTS:
        return SHORTCUTS[name]
    if any(ch.isdigit() for ch in name) or "-" in name:
        return name
    known = ", ".join(sorted(SHORTCUTS.keys()))
    raise ModelNotFoundError(
        f"unknown model shortcut: {name!r}. "
        f"Supported shortcuts: {known}. "
        "Or pass a full model string with a provider prefix "
        "(e.g. 'openai/gpt-4o')."
    )


def env_for_provider(provider: str) -> str | None:
    info = PROVIDERS.get(provider)
    return info.env_var if info else None


def base_url_for_provider(provider: str) -> str | None:
    info = PROVIDERS.get(provider)
    return info.base_url if info else None


__all__ = [
    "SHORTCUTS",
    "PROVIDERS",
    "ProviderInfo",
    "provider_shortcut_for_model",
    "resolve_model",
    "env_for_provider",
    "base_url_for_provider",
]
