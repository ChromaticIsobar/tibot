from __future__ import annotations

from tibot.domain.models import Game, GameMode, GameStatus, GeneratedSetup, Player
from tibot.telegram.callbacks import SetupCallback
from tibot.telegram.views import game_text, mode_keyboard, roster_keyboard


def test_setup_callbacks_are_typed_and_fit_telegram_limit() -> None:
    game = Game(123, -100, GameMode.MILTY, GameStatus.ROSTER, 7, 1, [Player(1, "A")])
    markup = roster_keyboard(game)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks
    assert all(callback is not None and len(callback.encode()) <= 64 for callback in callbacks)
    first = callbacks[0]
    assert first is not None
    parsed = SetupCallback.unpack(first)
    assert parsed.game_id == 123
    assert parsed.revision == 7


def test_mode_keyboard_offers_both_workflows() -> None:
    labels = [button.text for row in mode_keyboard().inline_keyboard for button in row]
    assert labels == ["Slices", "Whole board"]


def test_score_and_warnings_are_hidden_as_spoilers() -> None:
    game = Game(1, -1, GameMode.WHOLE_BOARD, GameStatus.COMPLETE, 1, 1)
    game.setup = GeneratedSetup(seed=2, score=4.5, warnings=["check this"])
    text = game_text(game)
    assert "<tg-spoiler>Board score: 4.5\nWarning: check this</tg-spoiler>" in text
