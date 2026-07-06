"""Slash-command completion."""

from __future__ import annotations

from prompt_toolkit.completion import FuzzyWordCompleter

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


def slash_completer() -> FuzzyWordCompleter:
    """Build the fuzzy popup completer used by the REPL."""
    return FuzzyWordCompleter(
        list(COMMANDS),
        meta_dict=COMMANDS,
        WORD=True,
    )
