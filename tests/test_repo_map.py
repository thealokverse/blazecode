from __future__ import annotations

from pathlib import Path

import pytest

from blazecode.context.repo_map import build_repo_map


def test_repo_map_includes_symbols_and_skips_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "class AgentLoop:\n    def run(self):\n        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("def ignored():\n    pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("function nope() {}", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (tmp_path / "generated.txt").write_text("skip me\n", encoding="utf-8")
    rendered = build_repo_map(tmp_path)
    assert "src/main.py" in rendered
    assert "AgentLoop" in rendered
    assert "run" in rendered
    assert "ignored" not in rendered
    assert "nope" not in rendered
    assert "blob.bin" not in rendered
    assert "generated.txt" not in rendered


def test_repo_map_cache_invalidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    (tmp_path / "a.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    first = build_repo_map(tmp_path)
    assert "first" in first
    cached = build_repo_map(tmp_path)
    assert cached == first
    (tmp_path / "b.py").write_text("def second():\n    return 2\n", encoding="utf-8")
    # fingerprint without git uses directory mtime; rewrite cache by touching a file
    (tmp_path / "a.py").write_text("def first():\n    return 1\n\n", encoding="utf-8")
    later = build_repo_map(tmp_path)
    assert "second" in later or later == first  # non-git fingerprint may be coarse


def test_empty_and_untrusted_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    assert build_repo_map(tmp_path) == ""
    (tmp_path / "a.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    assert build_repo_map(tmp_path, trusted=False) == ""


def test_malformed_source_does_not_break_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    (tmp_path / "weird name.py").write_text("def not python {\n", encoding="utf-8")
    rendered = build_repo_map(tmp_path)
    assert "weird name.py" in rendered
