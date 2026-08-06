from __future__ import annotations

import json
from collections.abc import Sequence

from blazecode.session.message import Message


def estimate_tokens(messages: Sequence[Message]) -> int:
    if not messages:
        return 0
    total_token_usage = sum((message.input_tokens or 0) + (message.output_tokens or 0) for message in messages)
    if total_token_usage > 0 and len(messages) > 1:
        return total_token_usage
    characters = 0
    for message in messages:
        characters += 8  # role / framing overhead
        if message.content:
            characters += len(message.content)
        if message.tool_calls:
            # rough size of tool call payloads without a full dump
            try:
                characters += len(json.dumps(message.tool_calls, ensure_ascii=False))
            except (TypeError, ValueError):
                characters += 64 * len(message.tool_calls)
        if message.tool_call_id:
            characters += len(message.tool_call_id)
        if message.name:
            characters += len(message.name)
    return max(1, (characters + 3) // 4)


def compact_messages(
    messages: Sequence[Message], max_tokens: int, recent_messages: int = 20
) -> list[Message]:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    values = list(messages)
    if estimate_tokens(values) <= max_tokens:
        return _drop_orphans(values)

    system = next((message for message in values if message.role == "system"), None)
    body = [message for message in values if message is not system]
    current_user = max(
        (index for index, message in enumerate(body) if message.role == "user"),
        default=max(0, len(body) - 1),
    )
    start = min(current_user, max(0, len(body) - recent_messages))
    keep = body[start:]

    # shrink from the left; re estimate only the kept window
    while keep and estimate_tokens(([system] if system else []) + keep) > max_tokens:
        if start >= current_user:
            break
        keep.pop(0)
        start += 1

    keep = _drop_orphans(keep)
    if start > 0 and body[:start]:
        note = Message(
            role="system",
            content=(
                f"[context compacted: omitted {start} earlier messages; "
                "critical decisions and the current task are preserved]"
            ),
        )
        if system is not None:
            return [system, note, *keep]
        return [note, *keep]
    return ([system] if system else []) + keep


def _drop_orphans(messages: list[Message]) -> list[Message]:
    keep = list(messages)
    while keep and keep[0].role == "tool":
        keep.pop(0)

    repaired: list[Message] = []
    pending_ids: set[str] = set()
    assistant_index: int | None = None

    def finalize_assistant() -> None:
        nonlocal pending_ids, assistant_index
        if assistant_index is None:
            pending_ids = set()
            return
        message = repaired[assistant_index]
        if not message.tool_calls:
            pending_ids = set()
            assistant_index = None
            return
        if not pending_ids:
            assistant_index = None
            return
        answered = [
            call
            for call in message.tool_calls
            if isinstance(call, dict)
            and call.get("id")
            and str(call.get("id")) not in pending_ids
        ]
        if answered:
            repaired[assistant_index] = Message(
                role=message.role,
                content=message.content,
                tool_calls=answered,
                tool_call_id=message.tool_call_id,
                name=message.name,
                created_at=message.created_at,
            )
        elif message.content:
            repaired[assistant_index] = Message(
                role=message.role,
                content=message.content,
                tool_calls=[],
                tool_call_id=message.tool_call_id,
                name=message.name,
                created_at=message.created_at,
            )
        else:
            repaired.pop(assistant_index)
        pending_ids = set()
        assistant_index = None

    for message in keep:
        if message.role == "assistant" and message.tool_calls:
            finalize_assistant()
            pending_ids = {
                str(call.get("id", ""))
                for call in message.tool_calls
                if isinstance(call, dict) and call.get("id")
            }
            repaired.append(message)
            assistant_index = len(repaired) - 1
            continue
        if message.role == "tool":
            call_id = message.tool_call_id or ""
            if pending_ids and call_id and call_id not in pending_ids:
                continue
            if not pending_ids and call_id:
                # no assistant parent in window
                continue
            repaired.append(message)
            if call_id:
                pending_ids.discard(call_id)
            continue
        finalize_assistant()
        repaired.append(message)
    finalize_assistant()
    return repaired
