from __future__ import annotations

import pytest

from tibot.domain.models import DraftState, PickKind


def test_three_pass_snake_sequence() -> None:
    draft = DraftState((10, 20, 30))
    assert draft.sequence == (10, 20, 30, 30, 20, 10, 10, 20, 30)
    visited = []
    while not draft.complete:
        visited.append(draft.current_player_id)
        draft.advance()
    assert tuple(visited) == draft.sequence
    assert draft.current_player_id is None
    with pytest.raises(ValueError, match="already complete"):
        draft.advance()


def test_two_pass_snake_sequence() -> None:
    draft = DraftState((10, 20, 30), (PickKind.FACTION, PickKind.SEAT))
    assert draft.sequence == (10, 20, 30, 30, 20, 10)
