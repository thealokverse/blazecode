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
    settings: Settings,
    prompt: str | None,
    console: Console,
    store: SessionStore | None = None,
) -> None:
    store = store or SessionStore()
    if prompt is None:
        await run_repl(settings, store=store)
        return
    renderer = Renderer(console, interactive=False)
    agent = AgentLoop(
        settings,
        Path.cwd().resolve(),
        store,
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
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume the latest session."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True),
    ] = False,
) -> None:
    del version
    is_tty = sys.stdout.isatty()
    console = Console(force_terminal=is_tty)

    resolved_store: SessionStore | None = None
    if resume:
        raw_store = SessionStore()
        sessions = raw_store.list_sessions()
        if not sessions:
            console.print("No saved sessions.", style="red")
            raise typer.Exit(2)
        raw_store.resume(sessions[0].session_id)
        resolved_store = raw_store

    try:
        settings = run_onboarding(console=console) if needs_onboarding() else Settings.load()
        asyncio.run(_run(settings, prompt, console, store=resolved_store))
    except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
        console.print(f"Configuration error: {exc}", style="red")
        raise typer.Exit(2) from exc
