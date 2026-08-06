from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from blazecode.config.settings import config_home

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_SKILL_BYTES = 64 * 1024
_BUILTIN_ROOT = Path(__file__).with_name("builtin")


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    path: Path

    def read(self) -> str:
        try:
            return _read_skill(self.path)
        except (OSError, UnicodeError, ValueError):
            return ""


class SkillLoader:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._cache: dict[str, Skill] | None = None
        self._summary: str | None = None
        self._issues: list[str] = []

    @property
    def roots(self) -> tuple[Path, Path, Path]:
        return (
            _BUILTIN_ROOT,
            config_home() / "skills",
            self.cwd / ".blazecode" / "skills",
        )

    @property
    def install_root(self) -> Path:
        return config_home() / "skills"

    def invalidate(self) -> None:
        self._cache = None
        self._summary = None
        self._issues = []

    def discover(self) -> dict[str, Skill]:
        if self._cache is not None:
            return self._cache
        found: dict[str, Skill] = {}
        self._issues = []
        for root in self.roots:
            if not root.is_dir():
                continue
            skill_files = [
                *sorted(root.glob("*.md")),
                *sorted(root.glob("*/SKILL.md")),
            ]
            names_in_root: set[str] = set()
            for skill_file in skill_files:
                try:
                    name, description = _metadata(skill_file)
                except (OSError, UnicodeError, ValueError) as exc:
                    self._issues.append(f"{skill_file}: {exc}")
                    continue
                if not _valid_skill_name(name):
                    self._issues.append(f"{skill_file}: invalid skill name {name!r}")
                    continue
                if name in names_in_root:
                    self._issues.append(f"{skill_file}: duplicate skill name {name!r}")
                    continue
                names_in_root.add(name)
                # Later roots are user scopes and deliberately override built-ins.
                found[name] = Skill(name, description, skill_file)
        self._cache = found
        return found

    def issues(self) -> list[str]:
        self.discover()
        return list(self._issues)

    def summary(self) -> str:
        if self._summary is not None:
            return self._summary
        skills = self.discover()
        if not skills:
            self._summary = "No skills are currently installed."
            return self._summary
        lines = [
            f"- {skill.name}: {skill.description}"
            for skill in sorted(skills.values(), key=lambda item: item.name)
        ]
        self._summary = "Available skills (load only when relevant):\n" + "\n".join(
            lines
        )
        return self._summary

    def relevant(self, prompt: str) -> list[Skill]:
        words = set(re.findall(r"[a-z0-9]+", prompt.lower()))
        selected: list[Skill] = []
        for skill in self.discover().values():
            name_terms = set(re.findall(r"[a-z0-9]+", skill.name.lower()))
            description_terms = set(
                re.findall(r"[a-z0-9]+", skill.description.lower())
            )
            description_matches = words & {
                word for word in description_terms if len(word) >= 5
            }
            name_matches = any(
                len(word) >= 3
                and any(
                    term.startswith(word) or word.startswith(term)
                    for term in name_terms
                )
                for word in words
            )
            if name_matches or len(description_matches) >= 2:
                selected.append(skill)
        return selected

    def add(self, source: Path) -> Skill:
        source = source.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"skill source not found: {source}")
        if source.is_file():
            if source.suffix.lower() != ".md":
                raise ValueError("skill files must use the .md extension")
            skill_file = source
        elif source.is_dir():
            skill_file = source / "SKILL.md"
            if not skill_file.is_file():
                raise ValueError(f"{source} must contain SKILL.md")
        else:
            raise ValueError(f"{source} must be a Markdown file or skill directory")
        name, _ = _metadata(skill_file)
        if not _valid_skill_name(name):
            raise ValueError(
                f"invalid skill name {name!r}; use letters, digits, '.', '_' or '-'"
            )
        root = self.install_root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = (root / source.name).resolve()
        if not destination.is_relative_to(root) or destination == root:
            raise ValueError(f"skill path escapes skills directory: {name!r}")
        if destination.exists():
            raise FileExistsError(f"skill already exists: {name}")
        if source.is_file():
            shutil.copy2(source, destination)
        else:
            shutil.copytree(source, destination)
        self.invalidate()
        description = _metadata(destination if source.is_file() else destination / "SKILL.md")[1]
        return Skill(name, description, destination if source.is_file() else destination / "SKILL.md")


def _valid_skill_name(name: str) -> bool:
    return bool(name) and bool(_SKILL_NAME_RE.fullmatch(name))


def _metadata(path: Path) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("must be a regular Markdown file")
    text = _read_skill(path)
    default_name = path.stem if path.name != "SKILL.md" else path.parent.name
    name = default_name
    description = ""
    body = text
    if text.startswith("---\n"):
        separator = text.find("\n---", 4)
        if separator != -1:
            metadata = text[4:separator]
            body = text[separator + 4 :].lstrip("\r\n")
            for line in metadata.splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                if key.strip() == "name":
                    candidate = value.strip().strip("\"'")
                    if candidate:
                        name = candidate
                elif key.strip() == "description":
                    description = value.strip().strip("\"'")
    if not description:
        description = next(
            (line.lstrip("# ").strip() for line in body.splitlines() if line.strip()),
            "No description",
        )
    description = " ".join(description.split())[:200] or "No description"
    return name, description


def _read_skill(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        raise
    if size < 1:
        raise ValueError("skill file is empty")
    if size > _MAX_SKILL_BYTES:
        raise ValueError(f"skill file exceeds {_MAX_SKILL_BYTES // 1024} KiB")
    return path.read_text(encoding="utf-8")
