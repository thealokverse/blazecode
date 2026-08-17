from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import PromptSession
from rich.console import Console

from blazecode.config.settings import Provider, Settings, config_path
from blazecode.llm.client import list_models
from blazecode.llm.models import (
    KeyPolicy,
    PROVIDER_PRESETS,
    ProviderPreset,
)
from blazecode.mascot import FACES, State
from blazecode.ui.interact import MenuCancelled, ask_index, ask_line, menu_session


async def verify_provider(base_url: str, api_key: str) -> list[str]:
    key = api_key
    if key.startswith("env:"):
        key = os.environ.get(key[4:], "")
    resolved = None if not key or key == "none" else key
    return await list_models(base_url, resolved)


async def run_onboarding(
    existing: Settings | None = None,
    console: Console | None = None,
    session: PromptSession[str] | None = None,
) -> Settings:
    output = console or Console()
    session = session or menu_session()
    output.print(f"\n  blaze {FACES[State.IDLE]}", style="bright_cyan")
    if existing is None:
        output.print(
            "\n  Welcome to Blazecode!\n"
            "  Let's get you set up. This takes about 30 seconds.\n"
        )
    while True:
        output.print("  Which provider are you using?")
        labels = [preset.label for preset in PROVIDER_PRESETS]
        choice = await ask_index(session, output, labels)
        try:
            provider = await _collect_provider(choice, output, session)
            output.print("\n  Fetching recommended models...")
            fetched = await verify_provider(provider.base_url, provider.api_key)
            if fetched:
                provider.models = fetched
            if not provider.models:
                output.print("  ✗ Provider returned no usable text models.", style="red")
                output.print("  Please try again.\n")
                continue
            output.print("  ✓ Key verified")
            break
        except MenuCancelled:
            raise
        except Exception as exc:
            output.print(
                f"  ✗ Could not verify provider: {_friendly_error(exc)}", style="red"
            )
            output.print("  Please try again.\n")
    selected = await ask_index(session, output, provider.models)
    model = provider.models[selected - 1]
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


async def switch_or_add_provider(
    settings: Settings,
    console: Console | None = None,
    session: PromptSession[str] | None = None,
) -> Settings:
    output = console or Console()
    session = session or menu_session()
    labels = [provider.name for provider in settings.providers]
    labels.append("Add a provider")
    choice = await ask_index(
        session, output, labels, current=settings.default_provider
    )
    if choice == len(labels):
        return await run_onboarding(settings, output, session)
    provider = settings.providers[choice - 1]
    if not provider.models:
        output.print("  That provider has no configured models; configure it again.")
        return await run_onboarding(settings, output, session)
    settings.default_provider = provider.name
    if settings.default_model not in provider.models:
        settings.default_model = provider.models[0]
    settings.save()
    output.print(f"  Switched to {provider.name} / {settings.default_model}")
    return settings


async def _collect_provider(
    choice: int, console: Console, session: PromptSession[str]
) -> Provider:
    if not (1 <= choice <= len(PROVIDER_PRESETS)):
        raise ValueError(f"unknown provider choice: {choice}")
    preset = PROVIDER_PRESETS[choice - 1]
    name = preset.name or (await ask_line(session, "  Provider name: ")).strip()
    if not name:
        raise ValueError("a provider name is required")
    if preset.base_url:
        base_url = preset.base_url
    elif preset.name == "anthropic":
        base_url = (
            await ask_line(session, "  OpenAI-compatible Anthropic base URL: ")
        ).strip()
    else:
        base_url = (await ask_line(session, "  OpenAI-compatible base URL: ")).strip()
    if not base_url:
        raise ValueError("a base URL is required")
    api_key = await _collect_api_key(preset, session)
    models: list[str] = []
    if preset.ask_models:
        model_text = (
            await ask_line(
                session,
                "  Model IDs (comma-separated; fetched list is preferred): ",
            )
        ).strip()
        models = [item.strip() for item in model_text.split(",") if item.strip()]
    return Provider(name, base_url.rstrip("/"), api_key, models)


async def _collect_api_key(preset: ProviderPreset, session: PromptSession[str]) -> str:
    if preset.key_policy is KeyPolicy.NONE:
        return "none"
    if (
        preset.key_policy is KeyPolicy.ENV
        and preset.env_var
        and os.environ.get(preset.env_var)
    ):
        use_env = (
            await ask_line(session, f"  Use ${preset.env_var}? [Y/n] ")
        ).strip().lower()
        if use_env in {"", "y", "yes"}:
            return f"env:{preset.env_var}"
    if preset.key_policy is KeyPolicy.PROMPT:
        answer = await ask_line(
            session,
            "  API key (blank for none, or env:VARIABLE): ",
            password=True,
        )
        return answer.strip() or "none"
    answer = (
        await ask_line(
            session,
            f"  Enter your {preset.label} API key: ",
            password=True,
        )
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
