"""Reusable first-run and provider setup flow."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from prompt_toolkit import prompt
from rich.console import Console
from rich.prompt import IntPrompt, Prompt

from blazecode.config.settings import Provider, Settings, config_path
from blazecode.mascot import FACES, State

PRESETS = {
    1: ("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    2: ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    3: ("local", "http://localhost:11434/v1", None),
}


def verify_provider(base_url: str, api_key: str) -> list[str]:
    """Synchronously verify a provider and return its model identifiers."""
    key = api_key
    if key.startswith("env:"):
        key = os.environ.get(key[4:], "")
    headers = (
        {"Authorization": f"Bearer {key}"} if key and key != "none" else {}
    )
    with httpx.Client(timeout=15.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        return [
            str(model["id"])
            for model in response.json().get("data", [])
            if isinstance(model, dict) and model.get("id")
        ]


def run_onboarding(
    existing: Settings | None = None, console: Console | None = None
) -> Settings:
    """Configure, verify, and select one provider."""
    output = console or Console()
    output.print(f"\n  blaze {FACES[State.IDLE]}", style="bright_cyan")
    if existing is None:
        output.print(
            "\n  Welcome to Blazecode!\n"
            "  Let's get you set up. This takes about 30 seconds.\n"
        )
    while True:
        output.print(
            "  Which provider are you using?\n"
            "  1. OpenAI\n"
            "  2. OpenRouter\n"
            "  3. Ollama (local)\n"
            "  4. Other (custom base URL)\n"
        )
        choice = IntPrompt.ask("  ›", choices=["1", "2", "3", "4"], console=output)
        try:
            provider = _collect_provider(choice, output)
            output.print("\n  Fetching available models...")
            fetched = verify_provider(provider.base_url, provider.api_key)
            output.print("  ✓ Key verified")
            break
        except Exception as exc:
            output.print(
                f"  ✗ Could not verify provider: {_friendly_error(exc)}", style="red"
            )
            output.print("  Please try again.\n")
    if fetched:
        provider.models = fetched
    if not provider.models:
        output.print("  ✗ Provider returned no models.", style="red")
        return run_onboarding(existing, output)
    visible = provider.models[:30]
    for index, model in enumerate(visible, start=1):
        output.print(f"  {index}. {model}")
    selected = IntPrompt.ask(
        "  ›", choices=[str(index) for index in range(1, len(visible) + 1)], console=output
    )
    model = visible[selected - 1]
    if existing is None:
        settings = Settings(provider.name, model, providers=[provider])
    else:
        settings = existing
        settings.upsert_provider(provider, model)
    destination = settings.save()
    output.print(
        f"\n  ✓ Setup complete — blaze {FACES[State.SUCCESS]}\n"
        f"  Config: {destination}\n"
    )
    return settings


def switch_or_add_provider(
    settings: Settings, console: Console | None = None
) -> Settings:
    """Switch to a configured provider or launch the add-provider flow."""
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
    if choice in PRESETS:
        name, base_url, variable = PRESETS[choice]
        if variable is None:
            return Provider(name, base_url, "none", [])
        current = os.environ.get(variable)
        if current:
            use_env = Prompt.ask(
                f"  Use ${variable}?", choices=["y", "n"], default="y", console=console
            )
            if use_env == "y":
                return Provider(name, base_url, f"env:{variable}", [])
        key = prompt(f"  Enter your {name} API key:\n  › ", is_password=True).strip()
        if not key:
            raise ValueError("an API key is required")
        return Provider(name, base_url, key, [])
    name = Prompt.ask("  Provider name", console=console).strip()
    base_url = Prompt.ask("  OpenAI-compatible base URL", console=console).strip()
    model_text = Prompt.ask(
        "  Model IDs (comma-separated; fetched list is preferred)",
        default="",
        console=console,
    )
    models = [item.strip() for item in model_text.split(",") if item.strip()]
    key = prompt("  API key (blank for none, or env:VARIABLE):\n  › ", is_password=True)
    return Provider(name, base_url, key.strip() or "none", models)


def _friendly_error(exc: Exception) -> str:
    lines = str(exc).splitlines()
    message = lines[0] if lines else exc.__class__.__name__
    return message[:160]


def needs_onboarding(path: Path | None = None) -> bool:
    """Return whether configuration is absent."""
    return not (path or config_path()).is_file()
