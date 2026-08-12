from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    path = ROOT / name
    assert path.exists(), f"{name} missing from repo root"
    return path.read_text(encoding="utf-8")


def test_install_sh_unchanged_guarantees() -> None:
    sh = _read("install.sh")
    # linux/macos installer must keep its core behaviour
    assert "thealokverse/blazecode" in sh
    assert "sys.version_info >= (3, 11)" in sh
    assert "--uninstall" in sh
    assert "${HOME}/.local/share/blazecode" in sh
    assert "BLAZECODE_PYTHON" in sh
    # never deletes user data
    assert "rm -rf \"${HOME}/.blazecode\"" not in sh
    assert "preserved ${HOME}/.blazecode" in sh
    # isolated env + launcher
    assert "-m venv" in sh
    assert "-m blazecode" in sh


def test_install_ps1_exists_and_has_core_markers() -> None:
    ps = _read("install.ps1")
    assert ps.startswith("#Requires -Version 5.1")
    assert "thealokverse/blazecode" in ps
    # python 3.11+ validation
    assert "sys.version_info >= (3, 11)" in ps
    assert "Python 3.11+ is required" in ps
    # isolated venv install
    assert "-m venv" in ps
    assert "-m blazecode" in ps
    # PATH exposure
    assert "blazecode.cmd" in ps
    assert "[Environment]::SetEnvironmentVariable('Path'" in ps
    # uninstall + idempotent update
    assert "Invoke-Uninstall" in ps
    assert "BLAZECODE_UNINSTALL" in ps
    assert ".old" in ps  # swap-aside update without corrupting prior install
    # piped install command documented in-script
    assert "irm https://raw.githubusercontent.com/thealokverse/blazecode/main/install.ps1" in ps


@pytest.mark.parametrize("name", ["install.sh", "install.ps1"])
def test_installers_never_delete_user_data(name: str) -> None:
    text = _read(name)
    # no removal of the ~/.blazecode config/session/skill directory
    assert not re.search(r"(rm -rf|Remove-Item)[^\n]*\.blazecode", text)
    if name == "install.ps1":
        # uninstall path explicitly preserves user data
        assert "preserved" in text


def test_installers_share_repo_and_python_floor() -> None:
    sh = _read("install.sh")
    ps = _read("install.ps1")
    assert "thealokverse/blazecode" in sh and "thealokverse/blazecode" in ps
    assert "(3, 11)" in sh and "(3, 11)" in ps
