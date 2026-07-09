"""Slash-command completion."""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion, CompleteEvent, FuzzyWordCompleter
from prompt_toolkit.document import Document

COMMANDS: dict[str, str] = {
    "/help": "List commands",
    "/status": "Show provider, model, approval mode, tokens, and Blaze state",
    "/provider": "Add or switch provider",
    "/models": "List or switch models",
    "/skills": "List skills; /skills add <path> installs one",
    "/export": "Export this session to Markdown",
    "/clear": "Start a fresh session",
    "/resume": "Resume a saved session",
    "/exit": "Quit Blazecode",
}


class SlashCommandCompleter(Completer):
    """Fuzzy command completer that activates only when the line starts with /."""

    def __init__(self) -> None:
        self._inner = FuzzyWordCompleter(
            list(COMMANDS),
            meta_dict=COMMANDS,
            WORD=True,
        )

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        line = document.current_line_before_cursor
        if not line.startswith("/"):
            return
        yield from self._inner.get_completions(document, complete_event)


def slash_completer() -> Completer:
    """Build the fuzzy popup completer used by the REPL."""
    return SlashCommandCompleter()
