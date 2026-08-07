from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import DummyHistory, FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.prompt import IntPrompt

from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import APPROVAL_MODES, Settings, config_home
from blazecode.context.compaction import estimate_tokens
from blazecode.mascot import State, blaze
from blazecode.onboarding import switch_or_add_provider
from blazecode.permissions.approval import ApprovalCallback, ApprovalManager
from blazecode.session.store import SessionStore
from blazecode.ui.completer import complete_slash_commands_while_typing, slash_completer
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
    approval_session: PromptSession[str] = PromptSession(history=DummyHistory())
    approval = ApprovalManager(
        settings.approval_mode,
        _interactive_approver(approval_session, renderer),
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
        except (asyncio.CancelledError, KeyboardInterrupt):
            agent.request_cancel()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            console.print("Interrupted.", style="yellow")
            blaze.set_state(State.IDLE)


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
    # prompt_toolkit has no s-enter; map common terminal sequences to f24
    global _SHIFT_ENTER_READY
    if _SHIFT_ENTER_READY:
        return
    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    from prompt_toolkit.keys import Keys

    for sequence in (
        "\x1b[13;2u",  # kitty / foot / wezterm
        "\x1b[27;2;13~",  # xterm modifyOtherKeys
        "\x1b[13;2~",
    ):
        ANSI_SEQUENCES[sequence] = Keys.F24
    _SHIFT_ENTER_READY = True


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
    if command == "/status":
        console.print(
            f"Session: {store.session_id}\n"
            f"Provider: {settings.default_provider}\n"
            f"Model: {settings.default_model}\n"
            f"Approval: {settings.approval_mode}\n"
            f"Session tokens: {estimate_tokens(agent.messages)}\n"
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
            source_text = argument[4:].strip()
            if not source_text:
                console.print("Usage: /skills add <file.md or directory>", style="red")
                return False, settings
            source = Path(source_text)
            try:
                skill = agent.skills.add(source)
                agent.reload_skills()
                console.print(f"Added {skill.name}: {skill.description}")
            except (OSError, ValueError, FileExistsError) as exc:
                console.print(f"Could not add skill: {exc}", style="red")
        else:
            agent.reload_skills()
            skills = agent.skills.discover()
            if not skills:
                console.print("No skills loaded.")
            else:
                for skill in sorted(skills.values(), key=lambda item: item.name.lower()):
                    console.print(f"- {skill.name}: {skill.description}")
            issues = agent.skills.issues()
            for issue in issues:
                console.print(f"Skipped skill: {issue}", style="yellow")
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
            try:
                messages = store.resume(sessions[selected - 1].session_id)
            except (OSError, ValueError) as exc:
                console.print(f"Could not resume session: {exc}", style="red")
            else:
                agent.replace_messages(messages)
                console.print(f"Resumed {store.session_id}.")
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
        console.print("Approval on. shell commands will ask for confirmation.")
    else:
        console.print("Approval off. tools run without prompts.")
    return settings


def _interactive_approver(
    session: PromptSession[str], renderer: Renderer
) -> ApprovalCallback:
    async def approve(name: str, arguments: dict[str, Any]) -> bool:
        target = renderer.tool_target(name, arguments)
        renderer.pause_activity()
        try:
            answer = await session.prompt_async(f"Run {target}? [y/N] ")
        except (EOFError, KeyboardInterrupt):
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
                print(f"blaze > {message.content.encode('ascii', 'replace').decode('ascii')}")
        elif message.role == "assistant" and message.content:
            console.print()
            try:
                console.print(render_markdown(message.content))
            except Exception:
                console._buffer.clear()
                print(message.content.encode("ascii", "replace").decode("ascii"))





