from blazecode.mascot import FACES, Mascot, State


def test_every_mascot_state_has_a_distinct_face() -> None:
    assert set(FACES) == set(State)
    assert len(set(FACES.values())) == len(State)
    mascot = Mascot()
    assert mascot.state is State.IDLE
    mascot.set_state(State.EDITING)
    assert mascot.face == "(⌐■_■)"

