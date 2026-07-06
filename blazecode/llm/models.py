"""Small model metadata registry."""

from __future__ import annotations

DEFAULT_CONTEXT_WINDOW = 128_000

CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4o": 128_000,
}


def context_window(model: str) -> int:
    """Return known context capacity or a conservative default."""
    return CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)

