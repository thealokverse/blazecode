"""Interactive prompt_toolkit REPL and slash commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.prompt import IntPrompt
from rich.table import Table

from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import APPROVAL_MODES, Settings, config_home
from blazecode.context.compaction import estimate_tokens
from blazecode.mascot import State, blaze
from blazecode.onboarding import switch_or_add_provider
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore
from blazecode.ui.completer import COMMANDS, slash_completer
from blazecode.ui.render import Renderer, render_header


async def run_repl(settings: Settings, cwd: Path | None = None) -> None:
    """Run the interactive Blazecode session."""
    working = (cwd or Path.cwd()).resolve()
    console = Console()
    renderer = Renderer(console)
    store = SessionStore()
    approval = ApprovalManager(settings.approval_mode, renderer.approve)
    agent = AgentLoop(settings, working, store, approval, renderer)
    history_path = config_home() / "history"
    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        completer=slash_completer(),
        complete_while_typing=True,
        complete_in_thread=True,
    )
    render_header(console, settings.default_model, working)
    while True:
        blaze.set_state(State.IDLE)
        try:
            text = (
                await session.prompt_async(
                    [("class:prompt", f"blaze {blaze.face} ❯ ")],
                )
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("Bye! Catch you later.")
            return
        if not text:
            continue
        if text.startswith("/"):
            should_exit, settings = await _command(
                text, settings, agent, store, renderer, console
            )
            if should_exit:
                return
            approval.mode = settings.approval_mode
            agent.settings = settings
            continue
        console.print()
        task = asyncio.create_task(agent.run(text))
        try:
            await task
        except asyncio.CancelledError:
            agent.request_cancel()
            console.print("Interrupted.", style="yellow")
        except KeyboardInterrupt:
            agent.request_cancel()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            console.print("\nInterrupted.", style="yellow")
            blaze.set_state(State.IDLE)


async def _command(
    text: str,
    settings: Settings,
    agent: AgentLoop,
    store: SessionStore,
    renderer: Renderer,
    console: Console,
) -> tuple[bool, Settings]:
    command, _, argument = text.partition(" ")
    argument = argument.strip()
    if command == "/exit":
        console.print("Bye! Catch you later.")
        return True, settings
    if command == "/help":
        table = Table(show_header=False, box=None)
        for name, description in COMMANDS.items():
            table.add_row(name, description)
        console.print(table)
    elif command == "/status":
        console.print(
            f"Provider: {settings.default_provider}\n"
            f"Model: {settings.default_model}\n"
            f"Approval: {settings.approval_mode}\n"
            f"Session tokens (estimated): {estimate_tokens(agent.messages)}\n"
            f"Blaze: {blaze.state.value} {blaze.face}"
        )
    elif command == "/approval":
        settings = _set_approval(settings, argument, console)
    elif command == "/provider":
        settings = await asyncio.to_thread(
            switch_or_add_provider, settings, console
        )
    elif command == "/models":
        provider = settings.provider()
        for index, model in enumerate(provider.models, start=1):
            marker = " *" if model == settings.default_model else ""
            console.print(f"{index}. {model}{marker}")
        selected = IntPrompt.ask(
            "Select model",
            choices=[str(index) for index in range(1, len(provider.models) + 1)],
            console=console,
        )
        settings.default_model = provider.models[selected - 1]
        settings.save()
    elif command == "/skills":
        if argument.startswith("add "):
            source = Path(argument[4:].strip())
            try:
                skill = agent.skills.add(source)
                agent.reload_skills()
                console.print(f"Added {skill.name}: {skill.description}")
            except (OSError, ValueError, FileExistsError) as exc:
                console.print(f"Could not add skill: {exc}", style="red")
        else:
            skills = agent.skills.discover()
            if not skills:
                console.print("No skills loaded.")
            for skill in skills.values():
                console.print(f"- {skill.name}: {skill.description}")
    elif command == "/export":
        destination = Path(argument).expanduser() if argument else None
        try:
            path = store.export_markdown(agent.messages, destination)
            console.print(f"Exported to {path}")
        except OSError as exc:
            console.print(f"Export failed: {exc}", style="red")
    elif command == "/clear":
        store.replace_with_new()
        agent.replace_messages([])
        console.print("Started a fresh session.")
    elif command == "/resume":
        sessions = store.list_sessions()
        if not sessions:
            console.print("No saved sessions.")
        else:
            for index, item in enumerate(sessions, start=1):
                console.print(
                    f"{index}. {item.title} "
                    f"({item.modified_at:%Y-%m-%d %H:%M}, {item.message_count} messages)"
                )
            selected = IntPrompt.ask(
                "Resume",
                choices=[str(index) for index in range(1, len(sessions) + 1)],
                console=console,
            )
            messages = store.resume(sessions[selected - 1].session_id)
            agent.replace_messages(messages)
            console.print(f"Resumed {store.session_id}.")
    else:
        console.print(f"Unknown command: {command}. Try /help.", style="red")
    return False, settings


def _set_approval(settings: Settings, argument: str, console: Console) -> Settings:
    """Apply /approval on|off (and optional explicit mode names)."""
    token = argument.lower()
    if not token:
        console.print(
            f"Approval: {settings.approval_mode} "
            f"({'on' if settings.approval_mode == 'ask' else 'off' if settings.approval_mode == 'auto' else settings.approval_mode})"
        )
        console.print("Usage: /approval on | /approval off")
        return settings
    mapping = {
        "on": "ask",
        "off": "auto",
        "ask": "ask",
        "auto": "auto",
        "plan": "plan",
    }
    mode = mapping.get(token)
    if mode is None or mode not in APPROVAL_MODES:
        console.print("Usage: /approval on | /approval off", style="red")
        return settings
    settings.approval_mode = mode
    settings.save()
    label = "on" if mode == "ask" else "off" if mode == "auto" else mode
    console.print(f"Approval {label} ({mode}).")
    return settings
