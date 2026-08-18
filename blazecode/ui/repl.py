from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.text import Text

from blazecode.agent.loop import AgentLoop
from blazecode.agent.prompts import git_oneline
from blazecode.config.settings import APPROVAL_MODES, Settings, config_home
from blazecode.context.compaction import estimate_tokens
from blazecode.context.skills import discover_skills, load_skill, select_skills
from blazecode.mascot import State, blaze
from blazecode.onboarding import switch_or_add_provider
from blazecode.permissions.approval import ApprovalCallback, ApprovalManager
from blazecode.permissions.trust import display_path, grant_trust, is_trusted
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.ui.completer import (
    complete_slash_commands_while_typing,
    slash_completer,
    suggest_command,
)
from blazecode.ui.interact import (
    MenuCancelled,
    ask_index,
    complete_menu,
    menu_session,
)
from blazecode.ui.markdown import render_markdown
from blazecode.ui.render import Renderer, render_header, render_status
from blazecode.ui.theme import ACCENT, ERROR, MUTED, WARN

_PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold ansicyan",
        "face": "ansicyan",
        "mark": "ansicyan",
    }
)


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
        style=_PROMPT_STYLE,
        prompt_continuation=lambda width, _line, _wrap: " " * max(width, 0),
    )
    dialog = menu_session()
    trusted = await _ensure_trust(working, console, dialog)
    approval = ApprovalManager(
        settings.approval_mode,
        _interactive_approver(dialog, renderer),
    )
    agent = AgentLoop(settings, working, store, approval, renderer, trusted=trusted)
    render_header(
        console,
        settings.default_model,
        working,
        git_line=git_oneline(working),
        trusted=trusted,
        provider=settings.default_provider,
    )
    if store.path.exists() and agent.messages:
        console.print(
            f"  Resumed {store.session_id}  ·  {len(agent.messages)} messages",
            style=MUTED,
        )
        console.print()
        _render_resumed_history(console, agent.messages)
    else:
        console.print("  Type a task, or / for commands.", style=MUTED)
        console.print()
    while True:
        blaze.set_state(State.IDLE)
        try:
            text = (
                await session.prompt_async(
                    [
                        ("class:prompt", "blaze "),
                        ("class:face", f"{blaze.face} "),
                        ("class:mark", "❯ "),
                    ],
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
        except KeyboardInterrupt:
            agent.request_cancel()
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, KeyboardInterrupt):
                    pass
            console.print("Interrupted.", style=WARN)
            blaze.set_state(State.IDLE)
        except asyncio.CancelledError:
            agent.request_cancel()
            console.print("Interrupted.", style=WARN)
            blaze.set_state(State.IDLE)
        except Exception as exc:
            console.print(f"Agent error: {exc}", style=ERROR)
            blaze.set_state(State.ERROR)
        finally:
            renderer.pause_activity()


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
        render_status(
            console,
            session=store.session_id,
            provider=settings.default_provider,
            model=settings.default_model,
            approval=settings.approval_mode,
            workspace="trusted" if agent._trusted else "untrusted",
            tokens=estimate_tokens(agent.messages),
            state=blaze.state.value,
            face=blaze.face,
            git_line=git_oneline(agent.cwd),
            todos=agent.todos.render(),
        )
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
    elif command in {"/skills", "/skill"} or command.startswith("/skill:"):
        _show_skills(agent, console, command, argument)
    elif command == "/compact":
        summary = agent.compact_now()
        console.print("  compacted", style=MUTED)
        console.print()
        console.print(summary)
    elif command == "/export":
        destination = Path(argument).expanduser() if argument else None
        try:
            path = store.export_markdown(agent.messages, destination)
            console.print(f"  Exported to {path}", style=MUTED)
        except OSError as exc:
            console.print(f"Export failed: {exc}", style=ERROR)
    elif command == "/clear":
        store.replace_with_new()
        agent.replace_messages([])
        console.print("Started a fresh session.")
    elif command == "/resume":
        await complete_menu(console, _resume_session(store, agent, console, dialog))
    else:
        hint = suggest_command(command)
        if hint:
            console.print(f"Unknown command: {command}. Did you mean {hint}?", style=ERROR)
        else:
            console.print(f"Unknown command: {command}", style=ERROR)
    return False, settings


def _set_approval(settings: Settings, argument: str, console: Console) -> Settings:
    token = argument.lower().strip()
    if not token:
        state = "on" if settings.approval_mode == "on" else "off"
        console.print(f"Approval: {state}")
        console.print("Usage: /approval on | /approval off")
        return settings
    if token not in APPROVAL_MODES:
        console.print("Usage: /approval on | /approval off", style=ERROR)
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
        console.print("No models configured. Use /provider to add one.", style=ERROR)
        return settings
    picked = await ask_index(
        session, console, provider.models, current=settings.default_model
    )
    settings.default_model = provider.models[picked - 1]
    settings.save()
    console.print(f"  Model: {settings.default_model}", style=MUTED)
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
        console.print(f"Could not resume session: {exc}", style=ERROR)
        return
    agent.replace_messages(messages)
    console.print(f"  Resumed {store.session_id}.", style=MUTED)


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
    for message in messages:
        if message.role == "user" and message.content:
            console.print()
            try:
                prompt_text = Text()
                prompt_text.append(f"blaze {blaze.face} ❯ ", style=ACCENT)
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


async def _ensure_trust(
    cwd: Path, console: Console, session: PromptSession[str]
) -> bool:
    if is_trusted(cwd):
        return True
    console.print()
    console.print("  Blazecode wants to work in:", style=MUTED)
    console.print()
    console.print(f"    {display_path(cwd)}", style=ACCENT)
    console.print()
    console.print(
        "  Trust this directory? Writes, edits, and shell stay blocked until you do.",
        style=MUTED,
    )
    try:
        picked = await ask_index(session, console, ["Trust", "Don't trust"])
    except (MenuCancelled, EOFError, KeyboardInterrupt):
        return False
    if picked != 1:
        console.print(
            "  Workspace left untrusted. Mutating tools are blocked.", style=MUTED
        )
        return False
    try:
        grant_trust(cwd)
    except (OSError, ValueError) as exc:
        console.print(f"Could not save trust: {exc}", style=ERROR)
        return False
    console.print("  Trusted.", style=MUTED)
    return True


def _show_skills(
    agent: AgentLoop, console: Console, command: str, argument: str
) -> None:
    name = argument
    if command.startswith("/skill:"):
        name = command.split(":", 1)[1].strip() or argument
    catalog = discover_skills(agent.cwd, trusted=agent._trusted)
    if name:
        selected = next((skill for skill in catalog if skill.name == name), None)
        if selected is None:
            matches = select_skills(catalog, name, limit=1)
            selected = matches[0] if matches else None
        if selected is None:
            console.print(f"Unknown skill: {name}", style=ERROR)
            return
        try:
            body = load_skill(selected)
        except OSError as exc:
            console.print(f"Could not load skill: {exc}", style=ERROR)
            return
        console.print(f"  {selected.name}", style=ACCENT)
        console.print(f"  {selected.description}", style=MUTED)
        console.print()
        console.print(body)
        return
    if not catalog:
        console.print("No skills found.")
        return
    for skill in catalog:
        line = Text()
        line.append(f"  {skill.name}", style=ACCENT)
        line.append(f"  · {skill.origin}", style=MUTED)
        console.print(line)
        if skill.description:
            console.print(f"    {skill.description}", style=MUTED)
