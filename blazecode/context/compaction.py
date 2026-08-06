from __future__ import annotations

import json
from collections.abc import Sequence

from blazecode.llm.models import get_model_entry_by_id
from blazecode.session.message import Message


def estimate_tokens(messages: Sequence[Message]) -> int:
    if not messages:
        return 0
    # last provider-reported prompt size is the best live signal
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.input_tokens:
            later = messages[index + 1 :]
            return (
                int(message.input_tokens)
                + int(message.output_tokens or 0)
                + (_char_tokens(later) if later else 0)
            )
    return _char_tokens(messages)

def estimate_cost(messages: Sequence[Message], model_name: str) -> float:
    if not messages:
        return 0.0
    model_id = model_name.split("/")[-1]
    model_entry = get_model_entry_by_id(model_id)
    total_input_tokens = sum(message.input_tokens or 0 for message in messages)
    total_output_tokens = sum(message.output_tokens or 0 for message in messages)
    if model_entry and model_entry.pricing:
        input_price = model_entry.pricing.get("prompt", 0.0)
        output_price = model_entry.pricing.get("completion", 0.0)
        cost = (total_input_tokens * float(input_price)) + (total_output_tokens * float(output_price))
        return cost
    return 0.0

def _char_tokens(messages: Sequence[Message]) -> int:
    characters = 0
    for message in messages:
        characters += 8  # role / framing overhead
        if message.content:
            characters += len(message.content)
        if message.tool_calls:
            try:
                characters += len(json.dumps(message.tool_calls, ensure_ascii=False))
            except (TypeError, ValueError):
                characters += 64 * len(message.tool_calls)
        if message.tool_call_id:
            characters += len(message.tool_call_id)
        if message.name:
            characters += len(message.name)
    return max(1, (characters + 3) // 4) if messages else 0


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
    if not body:
        return [system] if system else []

    # pin the latest user turn and as much trailing context as fits
    current_user = max(
        (index for index, message in enumerate(body) if message.role == "user"),
        default=len(body) - 1,
    )
    start = min(current_user, max(0, len(body) - recent_messages))
    keep = body[start:]

    while len(keep) > 1 and estimate_tokens(([system] if system else []) + keep) > max_tokens:
        # never drop the current user turn or anything after it
        if start >= current_user:
            break
        keep.pop(0)
        start += 1

    keep = _drop_orphans(keep)
    head: list[Message] = [system] if system else []
    if start > 0:
        omitted = start
        # one-line recovery hint so the model knows history was trimmed
        head.append(
            Message(
                role="system",
                content=(
                    f"[context compacted: omitted {omitted} earlier messages; "
                    "retain goals, decisions, and the active task from what remains]"
                ),
            )
        )
    return head + keep


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
                input_tokens=message.input_tokens,
                output_tokens=message.output_tokens,
            )
        elif message.content:
            repaired[assistant_index] = Message(
                role=message.role,
                content=message.content,
                tool_calls=[],
                tool_call_id=message.tool_call_id,
                name=message.name,
                created_at=message.created_at,
                input_tokens=message.input_tokens,
                output_tokens=message.output_tokens,
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
                continue
            repaired.append(message)
            if call_id:
                pending_ids.discard(call_id)
            continue
        finalize_assistant()
        repaired.append(message)
    finalize_assistant()
    return repaired
