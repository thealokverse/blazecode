from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console

from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import APPROVAL_MODES, Settings, config_home
from blazecode.context.compaction import estimate_tokens
from blazecode.mascot import State, blaze
from blazecode.onboarding import switch_or_add_provider
from blazecode.permissions.approval import ApprovalCallback, ApprovalManager
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.ui.completer import complete_slash_commands_while_typing, slash_completer
from blazecode.ui.interact import (
    MenuCancelled,
    ask_index,
    complete_menu,
    menu_session,
)
from blazecode.ui.markdown import render_markdown
from blazecode.ui.render import Renderer, render_header


async def run_repl(
    settings: Settings, cwd: Path | None = None, store: SessionStore | None = None
) -> None:
    working = (cwd or Path.cwd()).resolve()
    console = Console()
    renderer = Renderer(console)
    store = store or SessionStore()
    history_path = config_home() / "history"
    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        completer=slash_completer(),
        complete_while_typing=complete_slash_commands_while_typing,
        complete_in_thread=True,
        multiline=True,
        key_bindings=_input_bindings(),
        prompt_continuation=lambda width, _line, _wrap: " " * max(width, 0),
    )
    dialog = menu_session()
    approval = ApprovalManager(
        settings.approval_mode,
        _interactive_approver(dialog, renderer),
    )
    agent = AgentLoop(settings, working, store, approval, renderer)
    render_header(console, settings.default_model, working)
    if store.path.exists() and agent.messages:
        console.print(
            f"Resumed {store.session_id} ({len(agent.messages)} messages)",
            style="dim",
        )
        _render_resumed_history(console, agent.messages)
    while True:
        blaze.set_state(State.IDLE)
        try:
            text = (
                await session.prompt_async(
                    [("class:prompt", f"blaze {blaze.face} ❯ ")],
                )
            ).strip()
        except EOFError:
            console.print()
            console.print("Bye! Catch you later.")
            return
        except KeyboardInterrupt:
            # normal repl: ctrl+c exits cleanly
            console.print()
            console.print("Bye! Catch you later.")
            return
        if not text:
            continue
        if text.startswith("/"):
            should_exit, settings = await _command(
                text, settings, agent, store, console, dialog
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
        except (asyncio.CancelledError, KeyboardInterrupt):
            agent.request_cancel()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            console.print("Interrupted.", style="yellow")
            blaze.set_state(State.IDLE)
        except Exception as exc:
            console.print(f"Agent error: {exc}", style="red")
            blaze.set_state(State.ERROR)


_SHIFT_ENTER_READY = False


def _input_bindings() -> KeyBindings:
    # enter sends · shift+enter newline · ctrl+c cancels (default)
    _enable_shift_enter()
    bindings = KeyBindings()

    @bindings.add("enter", eager=True)
    def _send(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("f24", eager=True)
    def _newline(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


def _enable_shift_enter() -> None:
    global _SHIFT_ENTER_READY
    if _SHIFT_ENTER_READY:
        return
    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    from prompt_toolkit.keys import Keys

    for sequence in (
        "\x1b[13;2u",
        "\x1b[27;2;13~",
        "\x1b[13;2~",
    ):
        ANSI_SEQUENCES[sequence] = Keys.F24
    _SHIFT_ENTER_READY = True


async def _command(
    text: str,
    settings: Settings,
    agent: AgentLoop,
    store: SessionStore,
    console: Console,
    dialog: PromptSession[str],
) -> tuple[bool, Settings]:
    command, _, argument = text.partition(" ")
    argument = argument.strip()
    if command == "/exit":
        console.print("Bye! Catch you later.")
        return True, settings
    if command == "/status":
        console.print(
            f"Session: {store.session_id}\n"
            f"Provider: {settings.default_provider}\n"
            f"Model: {settings.default_model}\n"
            f"Approval: {settings.approval_mode}\n"
            f"Session tokens: {estimate_tokens(agent.messages)}\n"
            f"Blaze: {blaze.state.value} {blaze.face}"
        )
        todos = agent.todos.render()
        if todos:
            console.print(todos)
    elif command == "/approval":
        settings = _set_approval(settings, argument, console)
    elif command == "/provider":
        updated = await complete_menu(
            console, switch_or_add_provider(settings, console, dialog)
        )
        if updated is not None:
            settings = updated
    elif command == "/models":
        updated = await complete_menu(
            console, _switch_model(settings, console, dialog)
        )
        if updated is not None:
            settings = updated
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
        await complete_menu(console, _resume_session(store, agent, console, dialog))
    else:
        console.print(f"Unknown command: {command}", style="red")
    return False, settings


def _set_approval(settings: Settings, argument: str, console: Console) -> Settings:
    token = argument.lower().strip()
    if not token:
        state = "on" if settings.approval_mode == "on" else "off"
        console.print(f"Approval: {state}")
        console.print("Usage: /approval on | /approval off")
        return settings
    if token not in APPROVAL_MODES:
        console.print("Usage: /approval on | /approval off", style="red")
        return settings
    settings.approval_mode = token
    settings.save()
    if token == "on":
        console.print("Approval on. confirm before every tool.")
    else:
        console.print("Approval off. tools run without prompts (autonomous).")
    return settings


async def _switch_model(
    settings: Settings, console: Console, session: PromptSession[str]
) -> Settings:
    provider = settings.provider()
    if not provider.models:
        console.print("No models configured. Use /provider to add one.", style="red")
        return settings
    picked = await ask_index(
        session, console, provider.models, current=settings.default_model
    )
    settings.default_model = provider.models[picked - 1]
    settings.save()
    console.print(f"Model: {settings.default_model}")
    return settings


async def _resume_session(
    store: SessionStore,
    agent: AgentLoop,
    console: Console,
    session: PromptSession[str],
) -> None:
    sessions = store.list_sessions()
    if not sessions:
        console.print("No saved sessions.")
        return
    labels = [
        f"{item.title} "
        f"({item.modified_at:%Y-%m-%d %H:%M}, {item.message_count} messages)"
        for item in sessions
    ]
    picked = await ask_index(session, console, labels)
    try:
        messages = store.resume(sessions[picked - 1].session_id)
    except (OSError, ValueError) as exc:
        console.print(f"Could not resume session: {exc}", style="red")
        return
    agent.replace_messages(messages)
    console.print(f"Resumed {store.session_id}.")


def _interactive_approver(
    session: PromptSession[str], renderer: Renderer
) -> ApprovalCallback:
    async def approve(name: str, arguments: dict[str, Any]) -> bool:
        target = renderer.tool_target(name, arguments)
        renderer.pause_activity()
        try:
            answer = await session.prompt_async(f"Run {target}? [y/N] ")
        except (EOFError, MenuCancelled):
            return False
        finally:
            renderer.resume_activity()
        return answer.strip().lower() in {"y", "yes"}

    return approve


def _render_resumed_history(console: Console, messages: list[Message]) -> None:
    from rich.text import Text

    for message in messages:
        if message.role == "user" and message.content:
            console.print()
            try:
                prompt_text = Text()
                prompt_text.append(f"blaze {blaze.face} ❯ ", style="bold cyan")
                prompt_text.append(message.content)
                console.print(prompt_text)
            except Exception:
                console._buffer.clear()
                print(
                    f"blaze > {message.content.encode('ascii', 'replace').decode('ascii')}"
                )
        elif message.role == "assistant" and message.content:
            console.print()
            try:
                console.print(render_markdown(message.content))
            except Exception:
                console._buffer.clear()
                print(message.content.encode("ascii", "replace").decode("ascii"))
