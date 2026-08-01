from __future__ import annotations

from enum import Enum


class State(str, Enum):
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
    def __init__(self) -> None:
        self._state = State.IDLE

    @property
    def state(self) -> State:
        return self._state

    @property
    def face(self) -> str:
        return FACES[self._state]

    def set_state(self, state: State) -> None:
        self._state = state


blaze = Mascot()
