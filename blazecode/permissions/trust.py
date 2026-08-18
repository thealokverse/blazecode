from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from blazecode.config.settings import config_home


def trust_store_path() -> Path:
    return config_home() / "trusted.json"


def canonical_path(path: Path) -> Path:
    return path.expanduser().resolve()


def workspace_root(cwd: Path) -> Path:
    resolved = canonical_path(cwd)
    git_root = _git_toplevel(resolved)
    if git_root is not None and _is_within(resolved, git_root):
        return git_root
    return resolved


def is_trusted(cwd: Path) -> bool:
    try:
        target = canonical_path(cwd)
    except OSError:
        return False
    for entry in load_trusted():
        try:
            root = Path(entry)
            if target == root or _is_within(target, root):
                return True
        except OSError:
            continue
    return False


def grant_trust(cwd: Path) -> Path:
    root = workspace_root(cwd)
    if root.anchor == str(root) or str(root) in {"/", "\\"}:
        raise ValueError("refusing to trust a filesystem root")
    entries = load_trusted()
    token = str(root)
    if token not in entries:
        entries.append(token)
        _save(entries)
    return root


def load_trusted() -> list[str]:
    path = trust_store_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    values = raw.get("directories", raw) if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def display_path(path: Path) -> str:
    resolved = canonical_path(path)
    home = Path.home().resolve()
    if resolved == home:
        return "~"
    try:
        return "~/" + str(resolved.relative_to(home))
    except ValueError:
        return str(resolved)


def _save(entries: list[str]) -> None:
    destination = trust_store_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"directories": entries}
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


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except (OSError, ValueError):
        return False


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except OSError:
        return None
