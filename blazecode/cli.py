"""Typer command-line entry point."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from blazecode import __version__
from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import Settings
from blazecode.onboarding import needs_onboarding, run_onboarding
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore
from blazecode.ui.render import Renderer
from blazecode.ui.repl import run_repl

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"blazecode {__version__}")
        raise typer.Exit()


async def _run(
    settings: Settings, prompt: str | None, console: Console
) -> None:
    """Launch the interactive REPL or execute one non-interactive turn."""
    if prompt is None:
        await run_repl(settings)
        return
    # Headless (-p): bypass the REPL entirely, auto-approve tools, stream to stdout.
    renderer = Renderer(console)
    agent = AgentLoop(
        settings,
        Path.cwd().resolve(),
        SessionStore(),
        ApprovalManager("auto"),
        renderer,
    )
    await agent.run(prompt)


@app.callback()
def main(
    prompt: Annotated[
        str | None,
        typer.Option("-p", "--print", help="Run one prompt non-interactively."),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Override the configured model.")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Override the configured provider."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True),
    ] = False,
) -> None:
    """Start Blazecode or run a single prompt."""
    del version
    console = Console(force_terminal=sys.stdout.isatty())
    try:
        settings = run_onboarding(console=console) if needs_onboarding() else Settings.load()
        if provider:
            selected = settings.provider(provider)
            settings.default_provider = selected.name
            if model is None and settings.default_model not in selected.models:
                settings.default_model = selected.models[0]
        if model:
            if model not in settings.provider().models:
                raise ValueError(
                    f"model {model!r} is not configured for "
                    f"{settings.default_provider!r}"
                )
            settings.default_model = model
        asyncio.run(_run(settings, prompt, console))
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"Configuration error: {exc}", style="red")
        raise typer.Exit(2) from exc
