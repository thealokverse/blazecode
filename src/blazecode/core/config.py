"""Configuration: load and save ~/.blazecode/config.toml.

TOML schema:

    [default]
    model = "claude"
    permission = "ask"
    max_iterations = 25

    [providers.openai]
    api_key = "sk-..."

API keys from TOML set env vars only if not already in os.environ, so real
env vars always win.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover
    import tomli as _toml  # type: ignore[no-redef]

CONFIG_PATH = Path.home() / ".blazecode" / "config.toml"
PROJECT_CONFIG_PATH = Path.cwd() / ".blazecode.toml"
SKILLS_PATH = Path.home() / ".blazecode" / "skills.md"

from blazecode.providers.registry import PROVIDERS

_PROVIDER_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass
class Config:
    model: str = "gpt"
    permission: str = "ask"
    max_iterations: int = 25
    provider_keys: dict[str, str] = field(default_factory=dict)

    def is_configured(self) -> bool:
        """True if we have a model AND either keys exist or model uses a keyless provider."""
        if not self.model:
            return False
        if self.provider_keys:
            return True
        prov = self.provider_prefix()
        info = PROVIDERS.get(prov)
        if info and not info.needs_key:
            return True
        return False

    def provider_prefix(self) -> str:
        """Extract the provider prefix from the model string (before first /)."""
        if "/" in self.model:
            return self.model.split("/", 1)[0].lower()
        m = self.model.lower()
        if m.startswith("gpt"):
            return "openai"
        if m.startswith("claude"):
            return "anthropic"
        if m.startswith("gemini"):
            return "gemini"
        return "unknown"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return _toml.load(f)


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    default = data.get("default", {})
    if default:
        lines.append("[default]")
        for k in ("model", "permission", "max_iterations"):
            if k in default:
                v = default[k]
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                else:
                    lines.append(f"{k} = {v}")
        lines.append("")
    providers = data.get("providers", {})
    if providers:
        for name, block in providers.items():
            lines.append(f"[providers.{name}]")
            for k, v in block.items():
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_config(
    *,
    global_path: Path | None = None,
    project_path: Path | None = None,
) -> Config:
    global_path = global_path or CONFIG_PATH
    project_path = project_path if project_path is not None else PROJECT_CONFIG_PATH

    global_doc = _read_toml(global_path)
    project_doc = _read_toml(project_path)

    cfg = Config()
    for doc in (global_doc, project_doc):
        if not isinstance(doc, dict):
            continue
        d = doc.get("default", {})
        if isinstance(d, dict):
            if "model" in d and isinstance(d["model"], str):
                cfg.model = d["model"]
            if "permission" in d and isinstance(d["permission"], str):
                cfg.permission = d["permission"]
            if "max_iterations" in d:
                try:
                    cfg.max_iterations = int(d["max_iterations"])
                except (TypeError, ValueError):
                    pass
        provs = doc.get("providers", {})
        if isinstance(provs, dict):
            for name, block in provs.items():
                if not isinstance(block, dict):
                    continue
                api_key = block.get("api_key")
                if isinstance(api_key, str) and api_key:
                    cfg.provider_keys[name] = api_key
    return cfg


def save_config(cfg: Config, *, path: Path | None = None) -> Path:
    """Persist config to disk. Used by the onboarding wizard."""
    path = path or CONFIG_PATH
    data: dict[str, Any] = {
        "default": {
            "model": cfg.model,
            "permission": cfg.permission,
            "max_iterations": cfg.max_iterations,
        },
        "providers": {
            name: {"api_key": key} for name, key in cfg.provider_keys.items()
        },
    }
    _write_toml(path, data)
    return path


def apply_env(cfg: Config) -> list[str]:
    """Set provider env vars from config; never override an existing real value."""
    set_vars: list[str] = []
    for provider, key in cfg.provider_keys.items():
        env_name = _PROVIDER_ENV.get(provider)
        if not env_name or os.environ.get(env_name):
            continue
        os.environ[env_name] = key
        set_vars.append(env_name)
    return set_vars


__all__ = [
    "Config",
    "load_config",
    "save_config",
    "apply_env",
    "CONFIG_PATH",
    "SKILLS_PATH",
]
