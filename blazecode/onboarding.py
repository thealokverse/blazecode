from __future__ import annotations

import os
from pathlib import Path

import httpx
from prompt_toolkit import prompt
from rich.console import Console
from rich.prompt import IntPrompt, Prompt

from blazecode.config.settings import Provider, Settings, config_path
from blazecode.llm.models import (
    KeyPolicy,
    PROVIDER_PRESETS,
    ProviderPreset,
    load_cached_models,
    normalize_model_ids,
    save_cached_models,
    select_models,
)
from blazecode.mascot import FACES, State


def verify_provider(base_url: str, api_key: str) -> list[str]:
    key = api_key
    if key.startswith("env:"):
        key = os.environ.get(key[4:], "")
    headers = (
        {"Authorization": f"Bearer {key}"} if key and key != "none" else {}
    )
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://github.com/thealokverse/blazecode"
        headers["X-Title"] = "Blazecode"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/models", headers=headers
            )
            response.raise_for_status()
            models = select_models(normalize_model_ids(response.json()))
            if models:
                save_cached_models(base_url, models)
                return models
    except Exception as exc:
        cached = load_cached_models(base_url, ttl=0)
        if cached:
            return select_models(cached)
        raise exc
    cached = load_cached_models(base_url, ttl=0)
    if cached:
        return select_models(cached)
    return []


def run_onboarding(
    existing: Settings | None = None, console: Console | None = None
) -> Settings:
    output = console or Console()
    output.print(f"\n  blaze {FACES[State.IDLE]}", style="bright_cyan")
    if existing is None:
        output.print(
            "\n  Welcome to Blazecode!\n"
            "  Let's get you set up. This takes about 30 seconds.\n"
        )
    while True:
        output.print("  Which provider are you using?")
        for index, preset in enumerate(PROVIDER_PRESETS, start=1):
            output.print(f"  {index}. {preset.label}")
        output.print()
        choices = [str(value) for value in range(1, len(PROVIDER_PRESETS) + 1)]
        choice = IntPrompt.ask("  ›", choices=choices, console=output)
        try:
            provider = _collect_provider(choice, output)
            output.print("\n  Fetching recommended models...")
            fetched = verify_provider(provider.base_url, provider.api_key)
            if fetched:
                provider.models = fetched
            if not provider.models:
                output.print("  ✗ Provider returned no usable text models.", style="red")
                output.print("  Please try again.\n")
                continue
            output.print("  ✓ Key verified")
            break
        except Exception as exc:
            output.print(
                f"  ✗ Could not verify provider: {_friendly_error(exc)}", style="red"
            )
            output.print("  Please try again.\n")
    visible = provider.models
    for index, model in enumerate(visible, start=1):
        output.print(f"  {index}. {model}")
    selected = IntPrompt.ask(
        "  ›",
        choices=[str(index) for index in range(1, len(visible) + 1)],
        console=output,
    )
    model = visible[selected - 1]
    if existing is None:
        settings = Settings(provider.name, model, providers=[provider])
    else:
        settings = existing
        settings.upsert_provider(provider, model)
    destination = settings.save()
    output.print(
        f"\n  ✓ Setup complete. blaze {FACES[State.SUCCESS]}\n"
        f"  Config: {destination}\n"
    )
    return settings


def switch_or_add_provider(
    settings: Settings, console: Console | None = None
) -> Settings:
    output = console or Console()
    for index, provider in enumerate(settings.providers, start=1):
        marker = " *" if provider.name == settings.default_provider else ""
        output.print(f"  {index}. {provider.name}{marker}")
    add_index = len(settings.providers) + 1
    output.print(f"  {add_index}. Add a provider")
    choice = IntPrompt.ask(
        "  ›",
        choices=[str(index) for index in range(1, add_index + 1)],
        console=output,
    )
    if choice == add_index:
        return run_onboarding(settings, output)
    provider = settings.providers[choice - 1]
    if not provider.models:
        output.print("  That provider has no configured models; configure it again.")
        return run_onboarding(settings, output)
    settings.default_provider = provider.name
    if settings.default_model not in provider.models:
        settings.default_model = provider.models[0]
    settings.save()
    output.print(f"  Switched to {provider.name} / {settings.default_model}")
    return settings


def _collect_provider(choice: int, console: Console) -> Provider:
    if not (1 <= choice <= len(PROVIDER_PRESETS)):
        raise ValueError(f"unknown provider choice: {choice}")
    preset = PROVIDER_PRESETS[choice - 1]
    name = preset.name or Prompt.ask("  Provider name", console=console).strip()
    base_url = preset.base_url or Prompt.ask(
        "  OpenAI-compatible base URL", console=console
    ).strip()
    api_key = _collect_api_key(preset, console)
    models: list[str] = []
    if preset.ask_models:
        model_text = Prompt.ask(
            "  Model IDs (comma-separated; fetched list is preferred)",
            default="",
            console=console,
        )
        models = [item.strip() for item in model_text.split(",") if item.strip()]
    return Provider(name, base_url, api_key, models)


def _collect_api_key(preset: ProviderPreset, console: Console) -> str:
    if preset.key_policy is KeyPolicy.NONE:
        return "none"
    if (
        preset.key_policy is KeyPolicy.ENV
        and preset.env_var
        and os.environ.get(preset.env_var)
    ):
        use_env = Prompt.ask(
            f"  Use ${preset.env_var}?",
            choices=["y", "n"],
            default="y",
            console=console,
        )
        if use_env == "y":
            return f"env:{preset.env_var}"
    if preset.key_policy is KeyPolicy.PROMPT:
        answer = prompt(
            "  API key (blank for none, or env:VARIABLE):\n  › ",
            is_password=True,
        )
        return answer.strip() or "none"
    answer = prompt(
        f"  Enter your {preset.label} API key:\n  › ",
        is_password=True,
    ).strip()
    if not answer:
        raise ValueError("an API key is required")
    return answer


def _friendly_error(exc: Exception) -> str:
    lines = str(exc).splitlines()
    message = lines[0] if lines else exc.__class__.__name__
    return message[:160]


def needs_onboarding(path: Path | None = None) -> bool:
    return not (path or config_path()).is_file()
