"""Discover and selectively load SKILL.md instructions."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from blazecode.config.settings import config_home


@dataclass(frozen=True, slots=True)
class Skill:
    """Metadata and source path for one skill."""

    name: str
    description: str
    path: Path

    def read(self) -> str:
        """Read the complete skill instructions."""
        return self.path.read_text(encoding="utf-8")


class SkillLoader:
    """Load global skills, then project-local overrides."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()

    @property
    def roots(self) -> tuple[Path, Path]:
        """Return global and project-local skill roots."""
        return config_home() / "skills", self.cwd / ".blazecode" / "skills"

    def discover(self) -> dict[str, Skill]:
        """Discover valid skill directories in precedence order."""
        found: dict[str, Skill] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                name, description = _metadata(skill_file)
                found[name] = Skill(name, description, skill_file)
        return found

    def summary(self) -> str:
        """Build cheap skill metadata for the system prompt."""
        skills = self.discover()
        if not skills:
            return "No skills are currently installed."
        lines = [
            f"- {skill.name}: {skill.description}"
            for skill in sorted(skills.values(), key=lambda item: item.name)
        ]
        return "Available skills (load only when relevant):\n" + "\n".join(lines)

    def relevant(self, prompt: str) -> list[Skill]:
        """Select skills whose names or description terms match this turn."""
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
        """Copy a skill directory into the global skill root."""
        source = source.expanduser().resolve()
        skill_file = source / "SKILL.md"
        if not skill_file.is_file():
            raise ValueError(f"{source} does not contain SKILL.md")
        name, _ = _metadata(skill_file)
        destination = self.roots[0] / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            raise FileExistsError(f"skill already exists: {name}")
        shutil.copytree(source, destination)
        return self.discover()[name]


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
                    name = value.strip().strip("\"'")
                elif key.strip() == "description":
                    description = value.strip().strip("\"'")
    if not description:
        body = re.sub(r"\A---.*?---", "", text, count=1, flags=re.DOTALL).strip()
        description = next(
            (line.lstrip("# ").strip() for line in body.splitlines() if line.strip()),
            "No description",
        )
    return name, description
