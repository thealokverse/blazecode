from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from blazecode.config.settings import config_home

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "target",
        ".eggs",
        "eggs",
        ".idea",
        ".vscode",
        "vendor",
        "coverage",
        "htmlcov",
        ".next",
        ".nuxt",
        ".turbo",
        ".gradle",
        "site-packages",
    }
)
_BINARY_EXT = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".bz2",
        ".xz",
        ".7z",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".pyc",
        ".pyo",
        ".class",
        ".o",
        ".a",
        ".wasm",
        ".mp3",
        ".mp4",
        ".mov",
        ".wav",
        ".lock",
    }
)
_SYMBOLS = (
    (re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M), {".py"}),
    (
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_]\w*)",
            re.M,
        ),
        {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
    ),
    (re.compile(r"^\s*(?:func|type)\s+(?:\([^)]+\)\s+)?([A-Za-z_]\w*)", re.M), {".go"}),
    (
        re.compile(
            r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_]\w*)",
            re.M,
        ),
        {".rs"},
    ),
)
_MAX_WALK = 4_000
_MAX_FILES = 220
_MAX_FILE_BYTES = 400_000
_MAX_SYMBOLS = 8
_MAP_CHARS = 6_000


def build_repo_map(cwd: Path, *, trusted: bool = True) -> str:
    if not trusted:
        return ""
    try:
        root = cwd.expanduser().resolve()
    except OSError:
        return ""
    if not root.is_dir():
        return ""
    fingerprint = _fingerprint(root)
    cached = _read_cache(root, fingerprint)
    if cached is not None:
        return cached
    try:
        rendered = _render_map(root)
    except OSError:
        return ""
    _write_cache(root, fingerprint, rendered)
    return rendered


def _render_map(root: Path) -> str:
    files = _list_files(root)
    lines: list[str] = []
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
        except OSError:
            continue
        if size > _MAX_FILE_BYTES:
            continue
        symbols = _symbols(path)
        suffix = f"  { _kind(path) } { _fmt_size(size) }"
        if symbols:
            lines.append(f"{relative}{suffix}")
            for name in symbols:
                lines.append(f"  {name}")
        else:
            lines.append(f"{relative}{suffix}")
        if sum(len(line) + 1 for line in lines) >= _MAP_CHARS:
            lines.append("…")
            break
    return "\n".join(lines)


def _list_files(root: Path) -> list[Path]:
    listing = _run_git(root, "ls-files", "-co", "--exclude-standard")
    if listing is not None:
        files: list[Path] = []
        for line in listing.splitlines():
            if not line or line.endswith("/"):
                continue
            path = root / line
            if _skip_file(path):
                continue
            try:
                if path.is_file():
                    files.append(path)
            except OSError:
                continue
            if len(files) >= _MAX_FILES:
                break
        return files
    return _walk(root)


def _walk(root: Path) -> list[Path]:
    files: list[Path] = []
    visited = 0
    ignore = _gitignore(root)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIRS
            and not name.startswith(".")
            and not _is_config_home(current / name)
        ]
        for name in filenames:
            visited += 1
            if visited > _MAX_WALK or len(files) >= _MAX_FILES:
                return files
            if name.startswith("."):
                continue
            path = current / name
            relative = path.relative_to(root).as_posix()
            if ignore(relative) or _skip_file(path):
                continue
            files.append(path)
    return files


def _skip_file(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_EXT or _is_config_home(path):
        return True
    parts = set(path.parts)
    return bool(parts & _SKIP_DIRS)


def _is_config_home(path: Path) -> bool:
    try:
        home = config_home().resolve()
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == home or resolved.is_relative_to(home)



def _symbols(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    pattern = next((regex for regex, exts in _SYMBOLS if suffix in exts), None)
    if pattern is None:
        return []
    try:
        data = path.read_bytes()[:64_000]
    except OSError:
        return []
    if b"\x00" in data:
        return []
    text = data.decode("utf-8", errors="replace")
    names: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        name = next((group for group in match.groups() if group), None)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= _MAX_SYMBOLS:
            break
    return names


def _kind(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}b"
    if size < 1024 * 1024:
        return f"{size // 1024}kb"
    return f"{size // (1024 * 1024)}mb"


def _fingerprint(root: Path) -> str:
    head = _run_git(root, "rev-parse", "HEAD") or ""
    status = _run_git(root, "status", "--porcelain") or ""
    if head or status:
        payload = f"{head}\n{status}"
    else:
        try:
            stat = root.stat()
            payload = f"{stat.st_mtime_ns}:{stat.st_ino}"
        except OSError:
            payload = str(root)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:20]


def _cache_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return config_home() / "cache" / f"repomap_{digest}.json"


def _read_cache(root: Path, fingerprint: str) -> str | None:
    path = _cache_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("fingerprint") != fingerprint:
        return None
    text = raw.get("map")
    return text if isinstance(text, str) else None


def _write_cache(root: Path, fingerprint: str, rendered: str) -> None:
    path = _cache_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(
            json.dumps({"fingerprint": fingerprint, "map": rendered}),
            encoding="utf-8",
        )
        path.chmod(0o600)
    except OSError:
        return


def _gitignore(root: Path) -> callable:
    path = root / ".gitignore"
    patterns: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or text.startswith("!"):
                continue
            patterns.append(text.rstrip("/"))
    except OSError:
        return lambda _relative: False

    def ignored(relative: str) -> bool:
        name = Path(relative).name
        return any(
            _match(relative, pattern) or _match(name, pattern) for pattern in patterns
        )

    return ignored


def _match(value: str, pattern: str) -> bool:
    if pattern.startswith("/"):
        pattern = pattern[1:]
    try:
        return Path(value).match(pattern)
    except ValueError:
        return False


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
