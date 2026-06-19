"""Session: in-memory OpenAI-format chat history with JSONL persistence.

Context truncation uses a character-based token estimate (~4 chars per token)
and trims the oldest non-system messages when nearing the limit. The estimate
is deliberately conservative (over-counts) so we never blow past a model's
context window by accident.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SESSIONS_DIR = Path.home() / ".blazecode" / "sessions"


def make_session_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


@dataclass
class TokenStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.total_tokens += int(usage.get("total_tokens") or 0)
        cost = usage.get("cost_usd")
        if isinstance(cost, (int, float)):
            self.cost_usd += float(cost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class SessionPaths:
    base_dir: Path = field(default_factory=lambda: _ensure_dir())

    def path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"


def _ensure_dir() -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR


class Session:
    """In-memory OpenAI-format chat history, persisted as JSONL."""

    SYSTEM_ROLE = "system"

    def __init__(
        self,
        *,
        model: str,
        provider: str,
        session_id: str | None = None,
        paths: SessionPaths | None = None,
    ) -> None:
        self.session_id = session_id or make_session_id()
        self.model = model
        self.provider = provider
        self._messages: list[dict[str, Any]] = []
        self._stats = TokenStats()
        self._paths = paths or SessionPaths()

    # ---- message access ----

    def append(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            raise TypeError("message must be a dict")
        if "role" not in message:
            raise ValueError("message must have a 'role' key")
        self._messages.append(message)

    def replace_system(self, content: str) -> None:
        """Replace or insert a single system message at index 0."""
        if self._messages and self._messages[0].get("role") == self.SYSTEM_ROLE:
            self._messages[0]["content"] = content
        else:
            self._messages.insert(0, {"role": self.SYSTEM_ROLE, "content": content})

    def to_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    @property
    def stats(self) -> TokenStats:
        return self._stats

    def record_usage(self, usage: dict[str, Any]) -> None:
        self._stats.add(usage)

    # ---- persistence ----

    def persist(self) -> Path:
        path = self._paths.path(self.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for msg in self._messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.write(
                json.dumps(
                    {
                        "_summary": True,
                        "session_id": self.session_id,
                        "model": self.model,
                        "provider": self.provider,
                        "stats": self._stats.to_dict(),
                    }
                )
                + "\n"
            )
        return path

    @classmethod
    def resume(cls, session_id: str, *, paths: SessionPaths | None = None) -> "Session":
        paths = paths or SessionPaths()
        path = paths.path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"no such session: {session_id} (looked in {path})")
        messages: list[dict[str, Any]] = []
        model = "unknown"
        provider = "unknown"
        stats = TokenStats()
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("_summary"):
                    model = obj.get("model", model)
                    provider = obj.get("provider", provider)
                    s = obj.get("stats") or {}
                    stats.input_tokens = int(s.get("input_tokens", 0))
                    stats.output_tokens = int(s.get("output_tokens", 0))
                    stats.total_tokens = int(s.get("total_tokens", 0))
                    stats.cost_usd = float(s.get("cost_usd", 0.0))
                    continue
                messages.append(obj)
        s = cls(model=model, provider=provider, session_id=session_id, paths=paths)
        s._messages = messages
        s._stats = stats
        return s

    @staticmethod
    def list_saved(paths: SessionPaths | None = None) -> list[dict[str, Any]]:
        paths = paths or SessionPaths()
        if not paths.base_dir.exists():
            return []
        out: list[dict[str, Any]] = []
        for p in sorted(
            paths.base_dir.glob("*.jsonl"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            try:
                first_user = None
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        if obj.get("_summary"):
                            continue
                        if obj.get("role") == "user" and isinstance(
                            obj.get("content"), str
                        ):
                            first_user = obj["content"]
                            break
                stat = p.stat()
                preview = (first_user or "").replace("\n", " ")[:80]
                out.append(
                    {
                        "session_id": p.stem,
                        "modified": stat.st_mtime,
                        "size_bytes": stat.st_size,
                        "first_message": preview,
                    }
                )
            except (OSError, json.JSONDecodeError):
                continue
        return out

    # ---- context truncation ----

    def token_count(self, model: str) -> int:
        """Estimate token count for the current history.

        Uses a conservative character-based estimate (~4 chars per token) so
        we never blow past a model's context window. Each tool message and
        each tool call's serialized JSON counts as text.
        """
        chars = 0
        for m in self._messages:
            content = m.get("content")
            if isinstance(content, str):
                chars += len(content)
            else:
                try:
                    chars += len(json.dumps(content))
                except Exception:
                    chars += 0
            # Tool calls add overhead even when their content is empty.
            if m.get("tool_calls"):
                try:
                    chars += len(json.dumps(m["tool_calls"]))
                except Exception:
                    chars += 0
        # +500 token budget for the JSON tool schemas the SDK sends with
        # every request.
        return max(1, chars // 4) + 500

    def truncate_if_needed(
        self,
        *,
        model: str,
        context_window: int = 128_000,
        keep_last_n_exchanges: int = 6,
        soft_fraction: float = 0.8,
    ) -> bool:
        """Trim oldest non-system messages when over `soft_fraction` of context.

        Always keeps: the system prompt (and any other system messages) and the
        last `keep_last_n_exchanges` user/assistant exchanges (each exchange is
        a user + assistant + any interleaved tool messages).

        Returns True if anything was trimmed.
        """
        budget = max(1, int(context_window * soft_fraction))
        if self.token_count(model) <= budget:
            return False

        system_msgs = [
            m for m in self._messages if m.get("role") == self.SYSTEM_ROLE
        ]
        non_system = [
            m for m in self._messages if m.get("role") != self.SYSTEM_ROLE
        ]
        keep_n = keep_last_n_exchanges * 3  # rough budget per exchange
        if len(non_system) <= keep_n:
            return False
        keep = non_system[-keep_n:]
        self._messages = system_msgs + keep
        return True


__all__ = [
    "Session",
    "SessionPaths",
    "TokenStats",
    "make_session_id",
    "SESSIONS_DIR",
]
