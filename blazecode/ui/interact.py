from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from prompt_toolkit import PromptSession
from prompt_toolkit.history import DummyHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console

T = TypeVar("T")


class MenuCancelled(Exception):
    """Esc or EOF left a menu or selector."""


def menu_bindings() -> KeyBindings:
    # esc goes back · ctrl+c stays the default interrupt
    bindings = KeyBindings()

    @bindings.add(Keys.Escape)
    def _back(event: object) -> None:
        event.app.exit(exception=MenuCancelled())  # type: ignore[attr-defined]

    return bindings


def menu_session() -> PromptSession[str]:
    return PromptSession(history=DummyHistory(), key_bindings=menu_bindings())


async def ask_line(
    session: PromptSession[str],
    message: str,
    *,
    password: bool = False,
    default: str = "",
) -> str:
    try:
        return await session.prompt_async(
            message,
            is_password=password,
            default=default,
            enable_history_search=False,
        )
    except EOFError as exc:
        raise MenuCancelled() from exc


async def ask_index(
    session: PromptSession[str],
    console: Console,
    options: list[str],
    *,
    current: str | None = None,
    prompt: str = "  › ",
) -> int:
    if not options:
        raise MenuCancelled()
    console.print()
    for index, option in enumerate(options, start=1):
        marker = " (current)" if option == current else ""
        console.print(f"  {index}. {option}{marker}")
    console.print("  Esc to go back", style="dim")
    console.print()
    valid = {str(index) for index in range(1, len(options) + 1)}
    while True:
        raw = (await ask_line(session, prompt)).strip()
        if raw in valid:
            return int(raw)
        console.print(f"  Enter 1–{len(options)}, or Esc to go back.", style="dim")


async def complete_menu(console: Console, awaitable: Awaitable[T]) -> T | None:
    try:
        return await awaitable
    except MenuCancelled:
        console.print("Back.", style="dim")
        return None
    except KeyboardInterrupt:
        console.print("Interrupted.", style="yellow")
        return None
