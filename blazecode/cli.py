from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated
import httpx

import typer
from rich.console import Console

from blazecode import __version__
from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import Model, Models, Settings
from blazecode.onboarding import needs_onboarding, run_onboarding
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore
from blazecode.ui.render import Renderer
from blazecode.ui.repl import run_repl
from blazecode.llm.models import fetch_models_entries

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": []},
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
    await fetch_models_entries()
    if prompt is None:
        await run_repl(settings)
        return
    # headless (-p): approval on without a callback denies shell commands
    renderer = Renderer(console, interactive=False)
    agent = AgentLoop(
        settings,
        Path.cwd().resolve(),
        SessionStore(),
        ApprovalManager(settings.approval_mode),
        renderer,
    )
    await agent.run(prompt)


@app.callback()
def main(
    prompt: Annotated[
        str | None,
        typer.Option("-p", help="Run one prompt non-interactively."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True),
    ] = False,
) -> None:
    del version
    console = Console(force_terminal=sys.stdout.isatty())
    try:
        settings = run_onboarding(console=console) if needs_onboarding() else Settings.load()
        asyncio.run(_run(settings, prompt, console))
    except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
        console.print(f"Configuration error: {exc}", style="red")
        raise typer.Exit(2) from exc
