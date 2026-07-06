"""State machine for the Blaze mascot."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """States represented by Blaze's face."""

    IDLE = "idle"
    THINKING = "thinking"
    SEARCHING = "searching"
    EDITING = "editing"
    DEBUGGING = "debugging"
    SUCCESS = "success"
    ERROR = "error"


FACES: dict[State, str] = {
    State.IDLE: "(•‿•)",
    State.THINKING: "(•̀ᴗ•́)",
    State.SEARCHING: "(⌕‿⌕)",
    State.EDITING: "(⌐■_■)",
    State.DEBUGGING: "(ಠ_ಠ)",
    State.SUCCESS: "(ᵔ◡ᵔ)",
    State.ERROR: "(╥﹏╥)",
}


class Mascot:
    """Hold and update the agent's current visible state."""

    def __init__(self) -> None:
        self._state = State.IDLE

    @property
    def state(self) -> State:
        """Return the current state."""
        return self._state

    @property
    def face(self) -> str:
        """Return the face for the current state."""
        return FACES[self._state]

    def set_state(self, state: State) -> None:
        """Transition Blaze to ``state``."""
        self._state = state


blaze = Mascot()

