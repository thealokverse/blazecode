"""Tests for the six tools."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from blazecode.tools.edit import EditTool
from blazecode.tools.glob_tool import GlobTool
from blazecode.tools.grep import GrepTool
from blazecode.tools.read import ReadTool
from blazecode.tools.registry import ToolRegistry, mascot_for
from blazecode.tools.shell import ShellTool
from blazecode.tools.write import WriteTool


def _run(coro):
    return asyncio.run(coro)


def test_read_basic(tmp_cwd):
    (tmp_cwd / "hello.txt").write_text("a\nb\nc\nd\n")
    out = _run(ReadTool().run(path="hello.txt"))
    assert "a" in out and "d" in out
    assert "1\t" in out and "4\t" in out


def test_read_nonexistent(tmp_cwd):
    out = _run(ReadTool().run(path="nope.txt"))
    assert "error" in out.lower()


def test_read_line_range(tmp_cwd):
    (tmp_cwd / "f.txt").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    out = _run(ReadTool().run(path="f.txt", start_line=3, end_line=5))
    assert "line 3" in out and "line 5" in out
    assert "line 1" not in out and "line 10" not in out


def test_read_truncates_large_file(tmp_cwd):
    (tmp_cwd / "big.txt").write_text("\n".join(f"x{i}" for i in range(5000)))
    out = _run(ReadTool().run(path="big.txt"))
    assert "truncated" in out


def test_write_creates_file(tmp_cwd):
    out = _run(WriteTool().run(path="out/new.txt", content="hello\nworld\n"))
    assert "wrote" in out
    assert (tmp_cwd / "out" / "new.txt").read_text() == "hello\nworld\n"


def test_write_overwrites(tmp_cwd):
    p = tmp_cwd / "f.txt"
    p.write_text("old")
    _run(WriteTool().run(path=str(p), content="new"))
    assert p.read_text() == "new"


def test_edit_unique_match(tmp_cwd):
    p = tmp_cwd / "f.py"
    p.write_text("def hello():\n    return 1\n")
    out = _run(EditTool().run(path=str(p), old_string="return 1", new_string="return 42"))
    assert "edited" in out
    assert p.read_text() == "def hello():\n    return 42\n"


def test_edit_no_match(tmp_cwd):
    p = tmp_cwd / "f.py"
    p.write_text("foo\nbar\n")
    out = _run(EditTool().run(path=str(p), old_string="baz", new_string="qux"))
    assert "not found" in out
    assert p.read_text() == "foo\nbar\n"


def test_edit_multiple_matches(tmp_cwd):
    p = tmp_cwd / "f.py"
    p.write_text("x = 1\nx = 1\n")
    out = _run(EditTool().run(path=str(p), old_string="x = 1", new_string="x = 2"))
    assert "matches 2" in out
    assert p.read_text() == "x = 1\nx = 1\n"


def test_edit_missing_file(tmp_cwd):
    out = _run(EditTool().run(path="nope.txt", old_string="a", new_string="b"))
    assert "not found" in out.lower()


def test_glob_matches(tmp_cwd):
    (tmp_cwd / "a.py").write_text("")
    (tmp_cwd / "b.py").write_text("")
    (tmp_cwd / "sub").mkdir()
    (tmp_cwd / "sub" / "c.py").write_text("")
    out = _run(GlobTool().run(pattern="**/*.py"))
    assert "a.py" in out and "b.py" in out and "sub/c.py" in out


def test_glob_respects_gitignore(tmp_cwd):
    (tmp_cwd / ".gitignore").write_text("ignored.py\n")
    (tmp_cwd / "kept.py").write_text("")
    (tmp_cwd / "ignored.py").write_text("")
    out = _run(GlobTool().run(pattern="*.py"))
    assert "kept.py" in out and "ignored.py" not in out


def test_glob_no_match(tmp_cwd):
    assert "no matches" in _run(GlobTool().run(pattern="*.zzz"))


def test_grep_finds_matches(tmp_cwd):
    (tmp_cwd / "a.py").write_text("hello world\nfoo bar\nhello again\n")
    out = _run(GrepTool().run(pattern="hello"))
    assert "a.py:1" in out and "a.py:3" in out


def test_grep_no_match(tmp_cwd):
    (tmp_cwd / "a.py").write_text("nothing here\n")
    assert "no matches" in _run(GrepTool().run(pattern="zzznothing"))


def test_shell_success(tmp_cwd):
    out = _run(ShellTool().run(command=f"echo hi > {tmp_cwd/'out.txt'}"))
    assert "exit 0" in out
    assert (tmp_cwd / "out.txt").read_text().strip() == "hi"


def test_shell_nonzero_exit(tmp_cwd):
    assert "exit 7" in _run(ShellTool().run(command="exit 7"))


def test_shell_timeout(tmp_cwd):
    assert "timed out" in _run(ShellTool().run(command="sleep 5", timeout=1)).lower()


def test_shell_empty_command(tmp_cwd):
    out = _run(ShellTool().run(command="   "))
    assert "required" in out.lower()


def test_registry_schemas():
    schemas = ToolRegistry().schemas()
    names = sorted(s["function"]["name"] for s in schemas)
    assert names == ["edit", "glob", "grep", "read", "shell", "write"]
    for s in schemas:
        assert s["type"] == "function" and "description" in s["function"]


def test_registry_preview_for_edit(tmp_cwd):
    p = tmp_cwd / "f.txt"
    p.write_text("hello world\n")
    preview = ToolRegistry().preview(
        "edit", {"path": str(p), "old_string": "hello", "new_string": "bye"}
    )
    assert "edit" in preview and "hello" in preview and "bye" in preview


def test_approval_flags():
    assert ReadTool().requires_approval is False
    assert WriteTool().requires_approval is True
    assert EditTool().requires_approval is True
    assert GlobTool().requires_approval is False
    assert GrepTool().requires_approval is False
    assert ShellTool().requires_approval is True


def test_mascot_for():
    assert "Searching" not in mascot_for("read")  # just ensure no crash, has a face
    assert mascot_for("shell")
    assert mascot_for("write")
    assert mascot_for("read")
    assert mascot_for("glob")
    assert mascot_for("grep")
    assert mascot_for("edit")
