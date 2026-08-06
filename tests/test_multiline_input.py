from __future__ import annotations

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from blazecode.ui import repl
from blazecode.ui.repl import _enable_shift_enter, _input_bindings


def test_enter_sends_and_shift_enter_newlines() -> None:
    bindings = _input_bindings()
    assert isinstance(bindings, KeyBindings)
    key_sets = {binding.keys for binding in bindings.bindings}
    assert (Keys.ControlM,) in key_sets  # enter -> send
    assert (Keys.F24,) in key_sets  # shift+enter alias -> newline


def test_shift_enter_sequences_registered() -> None:
    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES

    _enable_shift_enter()
    assert ANSI_SEQUENCES.get("\x1b[13;2u") == Keys.F24
    assert ANSI_SEQUENCES.get("\x1b[27;2;13~") == Keys.F24


def test_repl_has_no_bottom_toolbar() -> None:
    source = open(repl.__file__, encoding="utf-8").read()
    assert "multiline=True" in source
    assert "bottom_toolbar" not in source
    assert "_toolbar" not in source
