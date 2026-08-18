from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches

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
    "/status": "provider, model, approval, tokens",
    "/approval": "on confirm · off autonomous",
    "/provider": "switch or add provider",
    "/models": "switch model",
    "/skills": "list or load a skill",
    "/compact": "summarize older context",
    "/export": "write session markdown",
    "/clear": "start a fresh session",
    "/resume": "open a saved session",
    "/exit": "quit",
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


def suggest_command(text: str) -> str | None:
    token = text.strip().split(None, 1)[0] if text.strip() else ""
    if not token:
        return None
    matches = get_close_matches(token, COMMANDS, n=1, cutoff=0.55)
    return matches[0] if matches else None


@Condition
def complete_slash_commands_while_typing() -> bool:
    return is_slash_command(get_app().current_buffer.document)
