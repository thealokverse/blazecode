"""Shared pytest fixtures for blazecode tests."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """A test fixture that makes `Path.cwd()` return an isolated temp directory.

    All tools that use `Path.cwd()` for relative paths will operate inside
    this directory.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path
