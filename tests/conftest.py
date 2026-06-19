"""Shared pytest fixtures."""
import pytest


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """Chdir into an isolated temp directory for the duration of the test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
