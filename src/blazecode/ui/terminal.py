"""Terminal UI: Codex-style scrolling REPL, mascot states, slash commands."""
from __future__ import annotations

import asyncio
import datetime as _dt
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from blazecode import __version__
from blazecode.core.config import SKILLS_PATH
from blazecode.core.events import (
    Error as ErrorEvent,
    TextDelta,
    ToolCallApprovalNeeded,
    ToolCallRequested,
    ToolResult,
    TurnCompleted,
)
from blazecode.core.permissions import PermissionPolicy
from blazecode.engine.loop import Agent
from blazecode.engine.session import Session
from blazecode.providers.registry import PROVIDERS, SHORTCUTS, resolve_model
from blazecode.tools.registry import mascot_for

# ---- Mascot faces ----

FACE_IDLE      = "(•‿•)"
FACE_THINKING  = "(•̀ᴗ•́)"
FACE_SEARCHING = "(⌕‿⌕)"
FACE_EDITING   = "(⌐■_■)"
FACE_DEBUGGING = "(ಠ_ಠ)"
FACE_SUCCESS   = "(ᵔ◡ᵔ)"
FACE_ERROR     = "(╥﹏╥)"

SLASH_COMMANDS = [
    "/help", "/status", "/provider", "/models", "/skills",
    "/export", "/clear", "/resume", "/yolo", "/exit",
]

HISTORY_PATH = Path.home() / ".blazecode" / "history"

PROMPT_STYLE = Style([("", "bg:#2b2b2b")])


# ---- Header ----

def _shorten_model(name: str) -> str:
    """Strip the provider prefix; show only the model name."""
    if "/" in name:
        return name.rsplit("/", 1)[-1]
    return name


def _shorten_dir(p: str) -> str:
    """Replace home directory prefix with ~."""
    home = str(Path.home())
    if p.startswith(home):
        return "~" + p[len(home):]
    return p


def render_header(
    console: Console,
    *,
    provider: str,
    model: str,
    cwd: str,
    version: str = __version__,
) -> None:
    display_model = _shorten_model(model)
    display_dir = _shorten_dir(cwd)
    lines = [
        f">_ BlazeCode (v{version})",
        "",
        f"provider:  {provider}",
        f"model:     {display_model}",
        f"directory: {display_dir}",
    ]
    width = max(60, max(len(l) for l in lines) + 6)
    console.print("┌" + "─" * (width - 2) + "┐")
    for l in lines:
        padding = width - 4 - len(l)
        console.print(f"│  {l}{' ' * padding}│")
    console.print("└" + "─" * (width - 2) + "┘")


# ---- Prompt session ----

def _build_prompt_session() -> PromptSession[str]:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    completer = WordCompleter(SLASH_COMMANDS, ignore_case=True)
    return PromptSession(
        history=FileHistory(str(HISTORY_PATH)),
        completer=completer,
        multiline=False,
        complete_while_typing=True,
        style=PROMPT_STYLE,
    )


# ---- Approval prompt ----

def _format_diff_preview(text: str) -> Text:
    out = Text()
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(line + "\n", style="dim bold")
        elif line.startswith("@@"):
            out.append(line + "\n", style="cyan")
        elif line.startswith("+"):
            out.append(line + "\n", style="green")
        elif line.startswith("-"):
            out.append(line + "\n", style="red")
        elif line.startswith(("shell", "edit", "write")):
            out.append(line + "\n", style="yellow")
        else:
            out.append(line + "\n", style="dim")
    return out


async def _ask_approval(console: Console, name: str, preview: str) -> bool | str:
    console.print()
    console.rule(f"[bold yellow]approval needed: {name}[/]", align="left")
    console.print(_format_diff_preview(preview))
    console.print()
    session = _build_prompt_session()
    loop = asyncio.get_running_loop()

    def _ask() -> str:
        try:
            return session.prompt("Allow this action? [y/n/a=always for this session] > ")
        except (EOFError, KeyboardInterrupt):
            return "n"

    answer = await loop.run_in_executor(None, _ask)
    a = answer.strip().lower()
    if a in ("y", "yes"):
        return True
    if a in ("a", "always"):
        return "always"
    return False


# ---- Skill loading ----

def _load_skills_text() -> str:
    if not SKILLS_PATH.exists():
        return ""
    try:
        return SKILLS_PATH.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


# ---- Slash commands ----

def _help_text() -> str:
    return "\n".join([
        "[bold]slash commands[/]",
        "  /help            show this help",
        "  /status          show the current header (provider, model, cwd, mode)",
        "  /provider        switch provider (re-runs onboarding for API key)",
        "  /models          list and switch models for the current provider",
        "  /skills          load ~/.blazecode/skills.md into the system prompt",
        "  /export <path>   export the current session as JSON or Markdown",
        "  /clear           clear the visible screen",
        "  /resume          pick a previous session to resume",
        "  /yolo            toggle auto-approve for this session",
        "  /exit            quit blazecode",
        "",
        "[dim]approval prompt answers:[/]",
        "  y / yes          approve this one",
        "  n / no           deny",
        "  a / always       approve all future tool calls this session",
    ])


async def _list_models_for_provider(console: Console, provider: str) -> list[str]:
    info = PROVIDERS.get(provider)
    if info:
        return list(info.examples)
    return sorted(SHORTCUTS.keys())


def _resolve_session_meta(agent: Agent) -> tuple[str, str, str]:
    info = agent.session_info()
    return info.provider, info.model, str(Path.cwd())


# ---- REPL ----

async def run_repl(agent: Agent) -> int:
    console = Console()
    provider, model, cwd = _resolve_session_meta(agent)
    render_header(console, provider=provider, model=model, cwd=cwd)

    # Load skills into the system prompt on startup if a skills file exists.
    skills = _load_skills_text()
    if skills:
        msgs = agent.session.to_messages()
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = (msgs[0].get("content") or "") + "\n\n# Skills\n" + skills

    prompt_session = _build_prompt_session()
    console.print()

    while True:
        try:
            user_input = await prompt_session.prompt_async(f"{FACE_IDLE} ❯ ")
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n  [cyan]{FACE_IDLE}[/] bye.")
            return 0

        text = user_input.strip()
        if not text:
            continue

        if text.startswith("/"):
            handled = await _handle_slash(agent, text, console)
            if handled == "exit":
                return 0
            continue

        await _run_turn(agent, text, console)


async def _handle_slash(agent: Agent, text: str, console: Console) -> str | None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        console.print(f"  [cyan]{FACE_IDLE}[/] bye.")
        return "exit"

    if cmd == "/clear":
        console.clear()
        return None

    if cmd == "/help":
        console.print(_help_text())
        return None

    if cmd == "/status":
        provider, model, cwd = _resolve_session_meta(agent)
        console.print()
        render_header(console, provider=provider, model=model, cwd=cwd)
        return None

    if cmd == "/yolo":
        if agent.permission.mode == "auto":
            agent.permission.set_mode("ask")
            console.print(f"  [yellow]{FACE_IDLE}[/] auto-approve [bold]disabled[/].")
        else:
            agent.permission.set_mode("auto")
            console.print(
                f"  [bold yellow]{FACE_IDLE}[/] auto-approve [bold]enabled[/]. "
                "all file writes and shell commands will run without confirmation."
            )
        return None

    if cmd == "/model" or cmd == "/models":
        await _cmd_models(agent, arg, console)
        return None

    if cmd == "/provider":
        await _cmd_provider(agent, arg, console)
        return None

    if cmd == "/skills":
        await _cmd_skills(agent, console)
        return None

    if cmd == "/export":
        await _cmd_export(agent, arg, console)
        return None

    if cmd == "/resume":
        await _cmd_resume(agent, console)
        return None

    console.print(f"  [red]{FACE_ERROR}[/] unknown command: {cmd}. try /help")
    return None


async def _cmd_models(agent: Agent, arg: str, console: Console) -> None:
    info = agent.session_info()
    provider = info.provider
    models = await _list_models_for_provider(console, provider)
    if not models:
        console.print(f"  [yellow]{FACE_IDLE}[/] no models for provider {provider!r}.")
        return
    console.print(f"  [bold]available models[/] for provider [cyan]{provider}[/]:")
    for i, m in enumerate(models, 1):
        marker = " (current)" if m == info.model else ""
        console.print(f"   {i}. {m}{marker}")
    if not arg:
        return
    # User supplied a target: either a number or a name.
    chosen: str | None = None
    try:
        idx = int(arg) - 1
        if 0 <= idx < len(models):
            chosen = models[idx]
    except ValueError:
        chosen = arg if arg in models else None
    if not chosen:
        console.print(f"  [red]{FACE_ERROR}[/] no such model: {arg!r}")
        return
    try:
        resolved = resolve_model(chosen)
    except Exception as exc:
        console.print(f"  [red]{FACE_ERROR}[/] {exc}")
        return
    agent.options.model = resolved
    agent.session.model = resolved
    console.print(f"  [green]{FACE_SUCCESS}[/] switched model to [bold]{resolved}[/]")


async def _cmd_provider(agent: Agent, arg: str, console: Console) -> None:
    provider_keys = sorted(PROVIDERS.keys())
    if not arg:
        console.print("  [bold]providers[/]:")
        for i, k in enumerate(provider_keys, 1):
            console.print(f"   {i}. {PROVIDERS[k].name}  [dim]({k})[/]")
        console.print("\n  usage: /provider <name-or-number>")
        return
    chosen: str | None = None
    try:
        idx = int(arg) - 1
        if 0 <= idx < len(provider_keys):
            chosen = provider_keys[idx]
    except ValueError:
        chosen = arg if arg in PROVIDERS else None
    if not chosen:
        console.print(f"  [red]{FACE_ERROR}[/] unknown provider: {arg!r}")
        return

    info = PROVIDERS[chosen]
    needs_key = info.needs_key
    api_key = ""
    if needs_key:
        api_key = await _prompt_secret(
            f"enter {info.env_var} (input hidden, leave blank to cancel)"
        )
        if not api_key:
            console.print(f"  [yellow]{FACE_IDLE}[/] cancelled.")
            return
    # Save to config.toml and env.
    from blazecode.core.config import CONFIG_PATH, apply_env, load_config, save_config
    cfg = load_config()
    if needs_key and api_key:
        cfg.provider_keys[chosen] = api_key
    cfg.model = info.examples[0]
    save_config(cfg, path=CONFIG_PATH)
    apply_env(cfg)

    agent.options.model = info.examples[0]
    agent.session.model = info.examples[0]
    agent.session.provider = chosen
    console.print(f"  [green]{FACE_SUCCESS}[/] provider set to [bold]{info.name}[/] (default model: {info.examples[0]})")


async def _cmd_skills(agent: Agent, console: Console) -> None:
    if not SKILLS_PATH.exists():
        SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SKILLS_PATH.write_text(
            "# Skills\n\n"
            "Add project-specific rules or commands here. Their contents are appended\n"
            "to BlazeCode's system prompt on startup and when /skills is invoked.\n",
            encoding="utf-8",
        )
        console.print(f"  [cyan]{FACE_IDLE}[/] created {SKILLS_PATH}")
    text = _load_skills_text()
    if not text:
        console.print(f"  [yellow]{FACE_IDLE}[/] skills file is empty.")
        return
    msgs = agent.session.to_messages()
    if msgs and msgs[0].get("role") == "system":
        content = msgs[0].get("content") or ""
        if "# Skills" not in content:
            msgs[0]["content"] = content + "\n\n# Skills\n" + text
            console.print(f"  [green]{FACE_SUCCESS}[/] skills loaded into system prompt.")
        else:
            console.print(f"  [cyan]{FACE_IDLE}[/] skills already loaded.")
    else:
        agent.session.replace_system("# Skills\n" + text)
        console.print(f"  [green]{FACE_SUCCESS}[/] skills installed as system prompt.")


async def _cmd_export(agent: Agent, arg: str, console: Console) -> None:
    target = Path(arg).expanduser() if arg else (Path.cwd() / f"{agent.session.session_id}.md")
    msgs = agent.session.to_messages()
    lines: list[str] = [f"# BlazeCode session {agent.session.session_id}", ""]
    for m in msgs:
        role = m.get("role", "?")
        content = m.get("content", "")
        if role == "tool":
            lines.append(f"### tool ({m.get('tool_call_id', '')})")
            lines.append("```\n" + str(content) + "\n```")
        else:
            lines.append(f"## {role}")
            lines.append(str(content))
        lines.append("")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"  [green]{FACE_SUCCESS}[/] exported session to [bold]{target}[/]")


async def _cmd_resume(agent: Agent, console: Console) -> None:
    rows = Session.list_saved()
    if not rows:
        console.print(f"  [yellow]{FACE_IDLE}[/] no saved sessions.")
        return
    console.print("  [bold]saved sessions[/]:")
    for i, r in enumerate(rows[:20], 1):
        ts = _dt.datetime.fromtimestamp(r["modified"]).strftime("%Y-%m-%d %H:%M")
        preview = (r["first_message"] or "(no user message)")[:50]
        console.print(f"   {i:>2}. {r['session_id']}  [dim]{ts}[/]  {preview}")
    choice = await _prompt_text("resume which? (number or session id, blank to cancel) > ")
    if not choice:
        return
    sid: str | None = None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(rows):
            sid = rows[idx]["session_id"]
    except ValueError:
        sid = choice if any(r["session_id"] == choice for r in rows) else None
    if not sid:
        console.print(f"  [red]{FACE_ERROR}[/] no such session: {choice!r}")
        return
    try:
        new_session = Session.resume(sid)
    except Exception as exc:
        console.print(f"  [red]{FACE_ERROR}[/] could not resume: {exc}")
        return
    agent.session._messages = new_session.to_messages()  # noqa: SLF001
    agent.session._stats = new_session.stats  # noqa: SLF001
    console.print(f"  [green]{FACE_SUCCESS}[/] resumed session [bold]{sid}[/]")


# ---- Streaming renderer ----

async def _run_turn(agent: Agent, user_input: str, console: Console) -> None:
    console.print()
    console.print(f"  [cyan]{FACE_IDLE}[/] [bold]you[/]")
    console.print(f"  {user_input}")
    console.print()

    full_text_parts: list[str] = []
    last_mascot = FACE_THINKING

    def _face_for_tool(name: str) -> str:
        nonlocal last_mascot
        face = mascot_for(name) or last_mascot
        last_mascot = face
        return face

    try:
        with patch_stdout():
            async for ev in agent.run_turn(user_input):
                if isinstance(ev, TextDelta):
                    console.print(ev.content, end="")
                    full_text_parts.append(ev.content)
                elif isinstance(ev, ToolCallRequested):
                    face = _face_for_tool(ev.name)
                    summary = _summarize_tool(ev.name, ev.arguments)
                    console.print(f"\n  [yellow]{face}[/] [dim]{summary}[/]")
                elif isinstance(ev, ToolCallApprovalNeeded):
                    decision = await _ask_approval(console, ev.name, ev.preview)
                    if decision == "always":
                        agent.permission.approve_all_for_session()
                        console.print(f"  [green]{FACE_SUCCESS}[/] approved (always for this session)")
                        agent.approve(ev.id, True)
                    elif decision:
                        console.print(f"  [green]{FACE_SUCCESS}[/] approved")
                        agent.approve(ev.id, True)
                    else:
                        console.print(f"  [red]{FACE_ERROR}[/] denied")
                        agent.approve(ev.id, False)
                elif isinstance(ev, ToolResult):
                    if ev.error:
                        console.print(f"\n  [red]{FACE_ERROR}[/] {ev.name}: {ev.output[:200]}")
                    else:
                        snippet = ev.output.splitlines()[0] if ev.output else "(no output)"
                        if len(snippet) > 120:
                            snippet = snippet[:117] + "..."
                        console.print(f"  [dim]→ {snippet}[/]")
                elif isinstance(ev, TurnCompleted):
                    usage = ev.usage or {}
                    if usage.get("total_tokens"):
                        console.print(
                            f"\n  [dim](tokens: in={usage.get('input_tokens', 0)}, "
                            f"out={usage.get('output_tokens', 0)})[/]"
                        )
                elif isinstance(ev, ErrorEvent):
                    console.print(f"\n  [red]{FACE_ERROR}[/] {ev.message}")
                    if not ev.recoverable:
                        console.print(f"  [dim](turn aborted)[/]")
    except KeyboardInterrupt:
        console.print(f"\n  [yellow]{FACE_ERROR}[/] interrupted.")
        return
    except Exception as exc:
        console.print(f"\n  [red]{FACE_ERROR}[/] {exc}")
        return

    console.print()
    # Final markdown re-render for syntax-highlighted code blocks.
    full_text = "".join(full_text_parts)
    if full_text.strip():
        console.print(Markdown(full_text))


def _summarize_tool(name: str, args: dict[str, Any]) -> str:
    if name == "read" and "path" in args:
        return f"read {args['path']}"
    if name == "write" and "path" in args:
        return f"write {args['path']}"
    if name == "edit" and "path" in args:
        return f"edit {args['path']}"
    if name == "glob" and "pattern" in args:
        return f"glob {args['pattern']}"
    if name == "grep" and "pattern" in args:
        return f"grep {args['pattern']}"
    if name == "shell" and "command" in args:
        cmd = str(args["command"])
        return f"shell: {cmd[:60]}{'...' if len(cmd) > 60 else ''}"
    return name


__all__ = ["run_repl", "run_headless", "render_header", "SLASH_COMMANDS"]


async def _prompt_text(prompt: str) -> str:
    """Prompt for visible text input. Returns '' if cancelled."""
    session = _build_prompt_session()
    loop = asyncio.get_running_loop()

    def _ask() -> str:
        try:
            return session.prompt(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    return (await loop.run_in_executor(None, _ask)).strip()


async def _prompt_secret(prompt: str) -> str:
    """Prompt for a hidden secret. Returns '' if cancelled or unavailable."""
    try:
        from prompt_toolkit import prompt as _pt_prompt
    except ImportError:
        return await _prompt_text(prompt)
    loop = asyncio.get_running_loop()

    def _ask() -> str:
        try:
            return _pt_prompt(prompt, is_password=True)
        except (EOFError, KeyboardInterrupt):
            return ""

    return (await loop.run_in_executor(None, _ask)).strip()


async def run_headless(agent: Agent, prompt: str) -> int:
    """Run one turn non-interactively, stream to stdout, exit.

    Approval prompts are auto-denied (use the REPL for interactive flow).
    """
    console = Console()
    err: str | None = None
    try:
        with patch_stdout():
            async for ev in agent.run_turn(prompt):
                if isinstance(ev, TextDelta):
                    console.print(ev.content, end="")
                elif isinstance(ev, ToolCallRequested):
                    face = mascot_for(ev.name) or FACE_THINKING
                    console.print(f"\n  [dim]{face} {_summarize_tool(ev.name, ev.arguments)}[/]")
                elif isinstance(ev, ToolCallApprovalNeeded):
                    agent.approve(ev.id, False)
                    console.print(f"\n  [yellow]{FACE_DEBUGGING}[/] denied (headless auto-denies approvals)")
                elif isinstance(ev, ToolResult):
                    if ev.error:
                        console.print(f"\n  [red]{FACE_ERROR}[/] {ev.name}: {ev.output[:200]}")
                    else:
                        snippet = ev.output.splitlines()[0] if ev.output else ""
                        if len(snippet) > 120:
                            snippet = snippet[:117] + "..."
                        if snippet:
                            console.print(f"  [dim]→ {snippet}[/]")
                elif isinstance(ev, ErrorEvent):
                    err = ev.message
                    console.print(f"\n  [red]{FACE_ERROR}[/] {ev.message}")
                elif isinstance(ev, TurnCompleted):
                    usage = ev.usage or {}
                    if usage.get("total_tokens"):
                        console.print(
                            f"\n  [dim](tokens: in={usage.get('input_tokens', 0)}, "
                            f"out={usage.get('output_tokens', 0)})[/]"
                        )
    except KeyboardInterrupt:
        console.print(f"\n  [yellow]{FACE_ERROR}[/] interrupted.")
        return 130
    except Exception as exc:
        console.print(f"\n  [red]{FACE_ERROR}[/] {exc}")
        return 1
    console.print()
    return 1 if err else 0
