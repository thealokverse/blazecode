"""Load and save Blazecode's JSON configuration."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APPROVAL_MODES = {"ask", "auto", "plan"}


def config_home() -> Path:
    """Return Blazecode's state directory."""
    override = os.environ.get("BLAZECODE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".blazecode"


def config_path() -> Path:
    """Return the JSON configuration path."""
    return config_home() / "config.json"


@dataclass(slots=True)
class Provider:
    """An OpenAI-compatible provider configured by the user."""

    name: str
    base_url: str
    api_key: str = "none"
    models: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Provider":
        """Build a provider from decoded JSON."""
        return cls(
            name=str(value["name"]).strip(),
            base_url=str(value["base_url"]).rstrip("/"),
            api_key=str(value.get("api_key", "none")),
            models=[str(model) for model in value.get("models", [])],
        )

    def resolved_api_key(self) -> str | None:
        """Resolve an environment-backed key without exposing it."""
        if self.api_key == "none" or not self.api_key:
            return None
        if self.api_key.startswith("env:"):
            variable = self.api_key[4:]
            value = os.environ.get(variable)
            if not value:
                raise ValueError(f"environment variable {variable} is not set")
            return value
        return self.api_key

    def masked_api_key(self) -> str:
        """Return a safe representation of this provider's key."""
        if self.api_key.startswith("env:") or self.api_key == "none":
            return self.api_key
        if len(self.api_key) <= 8:
            return "••••"
        return f"{self.api_key[:3]}...{self.api_key[-4:]}"


@dataclass(slots=True)
class Settings:
    """Top-level Blazecode settings."""

    default_provider: str
    default_model: str
    approval_mode: str = "ask"
    providers: list[Provider] = field(default_factory=list)
    context_window: int = 128_000
    compaction_ratio: float = 0.7

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Load settings from disk and validate their references."""
        source = path or config_path()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"configuration not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {source}: {exc}") from exc
        providers = [Provider.from_dict(item) for item in raw.get("providers", [])]
        settings = cls(
            default_provider=str(raw.get("default_provider", "")),
            default_model=str(raw.get("default_model", "")),
            approval_mode=str(raw.get("approval_mode", "ask")),
            providers=providers,
            context_window=int(raw.get("context_window", 128_000)),
            compaction_ratio=float(raw.get("compaction_ratio", 0.7)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate configuration invariants."""
        if self.approval_mode not in APPROVAL_MODES:
            raise ValueError(
                f"approval_mode must be one of {', '.join(sorted(APPROVAL_MODES))}"
            )
        names = [provider.name for provider in self.providers]
        if any(not provider.name or not provider.base_url for provider in self.providers):
            raise ValueError("every provider requires a name and base_url")
        if any(
            not provider.base_url.startswith(("http://", "https://"))
            for provider in self.providers
        ):
            raise ValueError("provider base_url must use http or https")
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique")
        if not self.providers:
            raise ValueError("at least one provider is required")
        if self.default_provider not in names:
            raise ValueError(f"unknown default provider: {self.default_provider}")
        provider = self.provider()
        if self.default_model not in provider.models:
            raise ValueError(
                f"model {self.default_model!r} is not configured for "
                f"provider {provider.name!r}"
            )
        if self.context_window < 1:
            raise ValueError("context_window must be positive")
        if not 0 < self.compaction_ratio <= 1:
            raise ValueError("compaction_ratio must be between 0 and 1")

    def provider(self, name: str | None = None) -> Provider:
        """Return a configured provider by name."""
        target = name or self.default_provider
        for provider in self.providers:
            if provider.name == target:
                return provider
        raise ValueError(f"unknown provider: {target}")

    def save(self, path: Path | None = None) -> Path:
        """Atomically save configuration with owner-only permissions."""
        destination = path or config_path()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = asdict(self)
        temporary = destination.with_suffix(".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, destination)
        destination.chmod(0o600)
        return destination

    def upsert_provider(self, provider: Provider, model: str) -> None:
        """Add or replace a provider and make it active."""
        self.providers = [
            current for current in self.providers if current.name != provider.name
        ]
        self.providers.append(provider)
        self.default_provider = provider.name
        self.default_model = model
        self.validate()
