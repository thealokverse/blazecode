from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from blazecode.config.settings import config_home

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


class SkillLoader:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._cache: dict[str, Skill] | None = None
        self._summary: str | None = None

    @property
    def roots(self) -> tuple[Path, Path]:
        return config_home() / "skills", self.cwd / ".blazecode" / "skills"

    def invalidate(self) -> None:
        self._cache = None
        self._summary = None

    def discover(self) -> dict[str, Skill]:
        if self._cache is not None:
            return self._cache
        found: dict[str, Skill] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                name, description = _metadata(skill_file)
                if not _valid_skill_name(name):
                    continue
                found[name] = Skill(name, description, skill_file)
        self._cache = found
        return found

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
            if words & name_terms or len(description_matches) >= 2:
                selected.append(skill)
        return selected

    def add(self, source: Path) -> Skill:
        source = source.expanduser().resolve()
        skill_file = source / "SKILL.md"
        if not skill_file.is_file():
            raise ValueError(f"{source} does not contain SKILL.md")
        name, _ = _metadata(skill_file)
        if not _valid_skill_name(name):
            raise ValueError(
                f"invalid skill name {name!r}; use letters, digits, '.', '_' or '-'"
            )
        root = self.roots[0].resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = (root / name).resolve()
        if not destination.is_relative_to(root) or destination == root:
            raise ValueError(f"skill path escapes skills directory: {name!r}")
        if destination.exists():
            raise FileExistsError(f"skill already exists: {name}")
        shutil.copytree(source, destination)
        self.invalidate()
        return self.discover()[name]


def _valid_skill_name(name: str) -> bool:
    return bool(name) and bool(_SKILL_NAME_RE.fullmatch(name))


def _metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    default_name = path.parent.name
    name = default_name
    description = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
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
        body = re.sub(r"\A---.*?---", "", text, count=1, flags=re.DOTALL).strip()
        description = next(
            (line.lstrip("# ").strip() for line in body.splitlines() if line.strip()),
            "No description",
        )
    return name, description
