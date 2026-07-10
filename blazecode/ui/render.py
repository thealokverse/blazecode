"""Rich rendering for streaming text, tools, and diffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from blazecode import __version__
from blazecode.mascot import FACES, Mascot, State, blaze
from blazecode.tools.base import ToolResult
from blazecode.ui.theme import ACCENT, ERROR, MUTED, SUCCESS

_STATUS: dict[State, str] = {
    State.THINKING: "thinking...",
    State.SEARCHING: "searching...",
    State.EDITING: "writing...",
    State.DEBUGGING: "debugging...",
}


class Renderer:
    """Render observer callbacks from the agent loop."""

    def __init__(self, console: Console | None = None, mascot: Mascot = blaze) -> None:
        self.console = console or Console()
        self.mascot = mascot
        self._buffer = ""
        self._live: Live | None = None
        self._activity: str | None = None

    def on_response_start(self) -> None:
        """Start a fresh live response region with a thinking status."""
        self._stop_live()
        self._buffer = ""
        self._activity = _STATUS.get(State.THINKING)
        self._live = Live(
            self._renderable(),
            console=self.console,
            refresh_per_second=20,
            transient=False,
        )
        self._live.start()

    def on_state(self, state: State) -> None:
        """Update the live mascot state and activity label."""
        if state in _STATUS and not self._buffer:
            self._activity = _STATUS[state]
        if self._live:
            self._live.update(self._renderable(), refresh=True)

    def on_text(self, text: str) -> None:
        """Append streamed model text, wiping any status label."""
        self._buffer += text
        self._activity = None
        if self._live:
            try:
                self._live.update(self._renderable(), refresh=True)
            except Exception:
                pass

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Render a stateful tool activity line before the result."""
        self._stop_live()
        self._activity = None
        verb = _STATUS.get(self.mascot.state) or f"{_tool_verb(name)}..."
        target = _tool_target(name, arguments)
        self.console.print(
            Text.assemble(
                ("blaze ", MUTED),
                (self.mascot.face + " ", ACCENT),
                (verb, "bold"),
                (f"  {target}" if target else "", MUTED),
            )
        )

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        """Render tool output or an edit diff."""
        if result.diff:
            try:
                self.console.print(Syntax(result.diff, "diff", theme="ansi_dark"))
            except Exception:
                self.console.print(result.diff)
        elif result.is_error:
            self.console.print(f"  {result.content}", style=ERROR)
        else:
            summary = result.content
            if len(summary) > 1200:
                summary = summary[:1200] + "\n… output truncated in display"
            self.console.print(Text("  " + summary.replace("\n", "\n  "), style=MUTED))

    def on_error(self, message: str) -> None:
        """Render an unrecoverable failure."""
        self._stop_live()
        self._activity = None
        self.console.print(f"blaze {self.mascot.face} {message}", style=ERROR)

    def on_complete(self) -> None:
        """Finalize any active live region and show the success face."""
        self._stop_live()
        self._activity = None
        if self.mascot.state == State.SUCCESS:
            self.console.print(
                f"blaze {self.mascot.face}", style=SUCCESS, highlight=False
            )

    def approve(self, name: str, arguments: dict[str, Any]) -> bool:
        """Ask the user before a mutating tool call."""
        from rich.prompt import Confirm

        target = _tool_target(name, arguments)
        return Confirm.ask(f"Allow [bold]{name}[/bold] {target}?", default=False)

    def _renderable(self) -> Group:
        if self._buffer:
            label = Text(f"blaze {self.mascot.face}", style=ACCENT)
            body = _safe_markdown(self._buffer)
            return Group(label, body)
        status = self._activity or "…"
        return Group(Text(f"blaze {self.mascot.face} {status}", style=ACCENT))

    def _stop_live(self) -> None:
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None


def render_header(console: Console, model: str, cwd: Path) -> None:
    """Print the Codex-style startup status box (REPL only)."""
    home = Path.home().resolve()
    resolved = cwd.resolve()
    if resolved == home:
        directory = "~"
    else:
        try:
            directory = "~/" + str(resolved.relative_to(home))
        except ValueError:
            directory = str(resolved)

    face = FACES[State.THINKING]
    body = Text()
    body.append(f"{face} Blazecode (v{__version__})\n\n", style="bold")
    body.append("model:     ", style=MUTED)
    body.append(f"{model}", style=ACCENT)
    body.append("   /model to change\n", style=MUTED)
    body.append("directory: ", style=MUTED)
    body.append(directory, style=ACCENT)
    console.print(
        Panel(
            body,
            border_style=ACCENT,
            padding=(0, 1),
            expand=False,
        )
    )
    console.print()


def _safe_markdown(text: str) -> RenderableType:
    """Render markdown, tolerating incomplete fences and malformed fragments."""
    display = text
    if display.count("```") % 2 == 1:
        display = display + "\n```"
    try:
        return Markdown(display)
    except Exception:
        return Text(text)


def _tool_target(name: str, arguments: dict[str, Any]) -> str:
    for key in ("path", "command"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value if len(value) <= 120 else value[:117] + "…"
    try:
        safe = {
            key: ("…" if key in {"content", "new_string", "old_string"} else value)
            for key, value in arguments.items()
        }
        return json.dumps(safe, ensure_ascii=False, default=str)[:120]
    except (TypeError, ValueError):
        return "{…}"


def _tool_verb(name: str) -> str:
    return {
        "read": "searching",
        "grep": "searching",
        "write": "writing",
        "edit": "writing",
        "bash": "debugging",
    }.get(name, name)
