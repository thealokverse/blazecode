from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from blazecode.config.settings import config_home
from blazecode.session.message import Message


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: str
    path: Path
    modified_at: datetime
    title: str
    message_count: int


class SessionStore:
    def __init__(
        self, session_id: str | None = None, directory: Path | None = None
    ) -> None:
        self.directory = directory or config_home() / "sessions"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.session_id = session_id or self.new_id()
        self.path = self.directory / f"{self.session_id}.jsonl"

    @staticmethod
    def new_id() -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{uuid.uuid4().hex[:8]}"

    def append(self, message: Message) -> None:
        descriptor = os.open(
            self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
            handle.flush()
        self.path.chmod(0o600)

    def load(self) -> list[Message]:
        if not self.path.exists():
            return []
        messages: list[Message] = []
        had_invalid = False
        for number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                messages.append(Message.from_dict(value))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                had_invalid = True
                continue
        if had_invalid and not messages:
            raise ValueError(f"invalid session record {self.path}:{number}")
        return messages

    def replace_with_new(self) -> None:
        self.session_id = self.new_id()
        self.path = self.directory / f"{self.session_id}.jsonl"

    def resume(self, session_id: str) -> list[Message]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id):
            raise ValueError("invalid session id")
        candidate = self.directory / f"{session_id}.jsonl"
        if not candidate.is_file():
            raise FileNotFoundError(f"session not found: {session_id}")
        messages = SessionStore(session_id, self.directory).load()
        self.session_id = session_id
        self.path = candidate
        return messages

    def list_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        for path in self.directory.glob("*.jsonl"):
            try:
                messages = SessionStore(path.stem, self.directory).load()
            except (OSError, ValueError):
                continue
            first_user = next(
                (
                    message.content
                    for message in messages
                    if message.role == "user" and message.content
                ),
                "Untitled session",
            )
            title = " ".join(first_user.split())[:72]
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            sessions.append(
                SessionInfo(path.stem, path, modified, title, len(messages))
            )
        return sorted(
            sessions, key=lambda item: (item.modified_at, item.session_id), reverse=True
        )

    def export_markdown(
        self, messages: list[Message], destination: Path | None = None
    ) -> Path:
        target = destination or Path.cwd() / f"blazecode-{self.session_id}.md"
        chunks = [f"# Blazecode session {self.session_id}\n"]
        labels = {"user": "User", "assistant": "Blazecode", "tool": "Tool"}
        for message in messages:
            label = labels.get(message.role, message.role.title())
            if message.role == "tool" and message.name:
                label += f": {message.name}"
            chunks.append(f"## {label}\n")
            chunks.append((message.content or "") + "\n")
            if message.tool_calls:
                chunks.append("```json\n")
                chunks.append(json.dumps(message.tool_calls, indent=2) + "\n")
                chunks.append("```\n")
        target.write_text("\n".join(chunks), encoding="utf-8")
        return target
