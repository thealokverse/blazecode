from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from blazecode.config.settings import Provider, Settings
from blazecode.ui import repl


def test_approval_on_off_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    settings = Settings(
        "p",
        "m",
        "auto",
        [Provider("p", "https://example.test/v1", "none", ["m"])],
    )
    settings.save(tmp_path / "config.json")
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    updated = repl._set_approval(settings, "on", console)
    assert updated.approval_mode == "ask"
    updated = repl._set_approval(updated, "off", console)
    assert updated.approval_mode == "auto"
    updated = repl._set_approval(updated, "plan", console)
    assert updated.approval_mode == "plan"
    repl._set_approval(updated, "", console)
    assert "Approval:" in stream.getvalue()
