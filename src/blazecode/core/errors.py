"""BlazeCode internal error types.

Every exception coming out of a tool or the provider client is translated into
one of these so the UI can render a clear, actionable message without the
process crashing.
"""

from __future__ import annotations


class BlazeError(Exception):
    """Base class for all BlazeCode-internal errors."""


class ProviderError(BlazeError):
    """A provider call failed. `recoverable` says whether retry could help."""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class ModelNotFoundError(ProviderError):
    """The requested model is not known to the provider."""

    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False)


__all__ = [
    "BlazeError",
    "ProviderError",
    "ModelNotFoundError",
]
