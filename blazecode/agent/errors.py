from __future__ import annotations

from enum import Enum


class FailureKind(str, Enum):
    USER_ABORT = "user_abort"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMIT = "rate_limit"
    NETWORK_ERROR = "network_error"
    INVALID_MODEL_RESPONSE = "invalid_model_response"
    CONTEXT_OVERFLOW = "context_overflow"
    AUTH_ERROR = "auth_error"
    INTERNAL_ERROR = "internal_error"


RETRYABLE = frozenset(
    {
        FailureKind.RATE_LIMIT,
        FailureKind.NETWORK_ERROR,
        FailureKind.CONTEXT_OVERFLOW,
    }
)

_AUTH = ("401", "403", "invalid api key", "unauthorized", "authentication", "auth")
_RATE = ("429", "rate limit", "too many requests")
_OVERFLOW = (
    "context length",
    "context window",
    "maximum context",
    "too many tokens",
    "token limit",
    "context_length_exceeded",
    "string too long",
    "request too large",
)
_NETWORK = (
    "connection",
    "connect timeout",
    "connect error",
    "network",
    "temporarily unavailable",
    "reset by peer",
    "broken pipe",
    "unreachable",
    "name or service not known",
    "dns",
    "timed out",
    "timeout",
    "502",
    "503",
    "504",
    "http 408",
    "http 409",
    "http 425",
    "http 500",
)
_ABORT = ("interrupt", "cancelled", "canceled", "user abort", "aborted")
_EMPTY = ("empty model", "empty response", "no content")


def classify_error(message: str) -> FailureKind:
    text = (message or "").lower()
    if not text:
        return FailureKind.INVALID_MODEL_RESPONSE
    if any(token in text for token in _ABORT):
        return FailureKind.USER_ABORT
    if any(token in text for token in _AUTH):
        return FailureKind.AUTH_ERROR
    if any(token in text for token in _RATE):
        return FailureKind.RATE_LIMIT
    if any(token in text for token in _OVERFLOW):
        return FailureKind.CONTEXT_OVERFLOW
    if "tool timed out" in text or "command timed out" in text:
        return FailureKind.TOOL_TIMEOUT
    if any(token in text for token in _NETWORK):
        return FailureKind.NETWORK_ERROR
    if any(token in text for token in _EMPTY):
        return FailureKind.INVALID_MODEL_RESPONSE
    if text.startswith("provider failure") or text.startswith("provider "):
        return FailureKind.PROVIDER_ERROR
    return FailureKind.PROVIDER_ERROR


def should_retry(kind: FailureKind, attempt: int, limit: int = 3) -> bool:
    return kind in RETRYABLE and 0 <= attempt < limit


def backoff_seconds(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** max(0, attempt)))
