"""Append-only JSONL session persistence."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from blazecode.config.settings import config_home
from blazecode.session.message import Message


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Summary of a saved session."""

    session_id: str
    path: Path
    modified_at: datetime
    title: str
    message_count: int


class SessionStore:
    """Persist messages as one JSON object per line."""

    def __init__(
        self, session_id: str | None = None, directory: Path | None = None
    ) -> None:
        self.directory = directory or config_home() / "sessions"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.session_id = session_id or self.new_id()
        self.path = self.directory / f"{self.session_id}.jsonl"

    @staticmethod
    def new_id() -> str:
        """Create a sortable, collision-resistant session identifier."""
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{uuid.uuid4().hex[:8]}"

    def append(self, message: Message) -> None:
        """Append a single message without rewriting prior records."""
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
            handle.flush()

    def load(self) -> list[Message]:
        """Load every valid message from this session."""
        if not self.path.exists():
            return []
        messages: list[Message] = []
        for number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                value = json.loads(line)
                messages.append(Message.from_dict(value))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(
                    f"invalid session record {self.path}:{number}: {exc}"
                ) from exc
        return messages

    def replace_with_new(self) -> None:
        """Point this store at a fresh session without deleting the old one."""
        self.session_id = self.new_id()
        self.path = self.directory / f"{self.session_id}.jsonl"

    def resume(self, session_id: str) -> list[Message]:
        """Switch to an existing session and load it."""
        if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id):
            raise ValueError("invalid session id")
        candidate = self.directory / f"{session_id}.jsonl"
        if not candidate.is_file():
            raise FileNotFoundError(f"session not found: {session_id}")
        self.session_id = session_id
        self.path = candidate
        return self.load()

    def list_sessions(self) -> list[SessionInfo]:
        """List saved sessions newest first."""
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
        return sorted(sessions, key=lambda item: item.modified_at, reverse=True)

    def export_markdown(
        self, messages: list[Message], destination: Path | None = None
    ) -> Path:
        """Export a readable Markdown transcript."""
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
