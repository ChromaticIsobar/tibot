from __future__ import annotations

from tibot.domain.models import Game, GameMode, GameStatus, GeneratedSetup, PickKind, Player
from tibot.telegram.callbacks import SetupCallback
from tibot.telegram.handlers import _pick_log_text
from tibot.telegram.views import draft_keyboard, game_text, mode_keyboard, roster_keyboard


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


def test_active_setup_keyboards_offer_a_new_setup() -> None:
    game = Game(1, -1, GameMode.MILTY, GameStatus.ROSTER, 1, 1)
    roster_labels = [
        button.text for row in roster_keyboard(game).inline_keyboard for button in row
    ]
    draft_labels = [
        button.text
        for row in draft_keyboard(
            game,
            Player(1, "A"),
            {kind: [] for kind in PickKind},
        ).inline_keyboard
        for button in row
    ]
    assert "Start new setup" in roster_labels
    assert "Start new setup" in draft_labels


def test_pick_log_distinguishes_own_and_proxy_picks() -> None:
    linked = Player(1, "Alice", telegram_user_id=10)
    placeholder = Player(2, "Charlie")
    assert _pick_log_text(linked, PickKind.FACTION, "Xxcha", 10, "Alice") == (
        "<b>Alice</b> chose faction: <b>Xxcha</b>."
    )
    assert _pick_log_text(placeholder, PickKind.FACTION, "Xxcha", 20, "Bob") == (
        "<b>Charlie</b> had their faction picked by <b>Bob</b>: <b>Xxcha</b>."
    )


def test_current_picker_uses_linked_telegram_handle() -> None:
    game = Game(1, -1, GameMode.MILTY, GameStatus.DRAFTING, 1, 1)
    linked = Player(1, "Alice Example", telegram_user_id=10, telegram_username="alice")
    placeholder = Player(2, "Offline Player")
    assert "Current pick: <b>@alice</b>" in game_text(game, linked)
    assert "Current pick: <b>Offline Player</b>" in game_text(game, placeholder)
