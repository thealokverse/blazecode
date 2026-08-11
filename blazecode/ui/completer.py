from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    FuzzyWordCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition

COMMANDS: dict[str, str] = {
    "/status": "Show provider, model, approval, tokens, and Blaze state",
    "/approval": "Autonomy: /approval on (confirm every tool) | off (auto)",
    "/provider": "Add or switch provider",
    "/models": "List or switch models",
    "/export": "Export this session to Markdown",
    "/clear": "Start a fresh session",
    "/resume": "Resume a saved session",
    "/exit": "Quit Blazecode",
}


class SlashCommandCompleter(Completer):
    def __init__(self) -> None:
        self._inner = FuzzyWordCompleter(
            list(COMMANDS),
            meta_dict=COMMANDS,
            WORD=True,
        )

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        if not is_slash_command(document):
            return
        yield from self._inner.get_completions(document, complete_event)


def slash_completer() -> Completer:
    return SlashCommandCompleter()


def is_slash_command(document: Document) -> bool:
    return document.current_line_before_cursor.startswith("/")


@Condition
def complete_slash_commands_while_typing() -> bool:
    return is_slash_command(get_app().current_buffer.document)
