"""Predictable token estimation and history truncation."""

from __future__ import annotations

import json
from collections.abc import Sequence

from blazecode.session.message import Message


def estimate_tokens(messages: Sequence[Message]) -> int:
    """Estimate message tokens using a conservative character heuristic."""
    characters = sum(
        len(json.dumps(message.to_dict(api=True), ensure_ascii=False))
        for message in messages
    )
    return max(1, (characters + 3) // 4) if messages else 0


def compact_messages(
    messages: Sequence[Message], max_tokens: int, recent_messages: int = 20
) -> list[Message]:
    """Keep the system prompt, current task, and newest complete context."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    values = list(messages)
    if estimate_tokens(values) <= max_tokens:
        return values
    system = next((message for message in values if message.role == "system"), None)
    body = [message for message in values if message is not system]
    current_user = max(
        (index for index, message in enumerate(body) if message.role == "user"),
        default=max(0, len(body) - 1),
    )
    start = min(current_user, max(0, len(body) - recent_messages))
    keep = body[start:]

    while keep and estimate_tokens(([system] if system else []) + keep) > max_tokens:
        if start >= current_user:
            break
        keep.pop(0)
        start += 1

    # A tool result is invalid without the assistant call that introduced it.
    while keep and keep[0].role == "tool":
        keep.pop(0)

    return ([system] if system else []) + keep
