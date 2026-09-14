from __future__ import annotations

import pytest

from tibot.domain.content import ContentCatalog
from tibot.domain.models import (
    Faction,
    Game,
    GameMode,
    GameStatus,
    GeneratedSetup,
    PickKind,
    Player,
)
from tibot.telegram.callbacks import SetupCallback
from tibot.telegram.formatting import FACTION_WIKI_LINKS, faction_link
from tibot.telegram.handlers import (
    _choice_lines,
    _pick_log_text,
    _recap_link_preview,
    _show_empty_board,
    _undo_arguments,
)
from tibot.telegram.views import (
    draft_confirmation_keyboard,
    draft_keyboard,
    game_text,
    mode_keyboard,
    roster_keyboard,
    seed_line,
)


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
    assert "<tg-spoiler>Seed: 2</tg-spoiler>" in text
    assert "<tg-spoiler>Board score: 4.5\nWarning: check this</tg-spoiler>" in text


def test_seed_line_hides_the_complete_line() -> None:
    assert seed_line(8169840071781047999) == (
        "<tg-spoiler>Seed: 8169840071781047999</tg-spoiler>"
    )
    assert seed_line(42, "Speaker seed") == (
        "<tg-spoiler>Speaker seed: 42</tg-spoiler>"
    )


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


def test_completed_draft_offers_start_and_undo_last_choice() -> None:
    game = Game(1, -1, GameMode.MILTY, GameStatus.DRAFTING, 3, 1)
    labels = [
        button.text
        for row in draft_confirmation_keyboard(game).inline_keyboard
        for button in row
    ]
    assert labels == ["Start", "Undo last choice", "Start new setup"]


def test_pick_log_distinguishes_own_and_proxy_picks() -> None:
    linked = Player(1, "Alice", telegram_user_id=10)
    placeholder = Player(2, "Charlie")
    assert _pick_log_text(
        linked, PickKind.FACTION, "The Xxcha Kingdom", 10, "Alice"
    ) == (
        "<b>Alice</b> chose faction: <b>"
        '<a href="https://twilight-imperium.fandom.com/wiki/The_Xxcha_Kingdom">'
        "The Xxcha Kingdom</a></b>."
    )
    assert _pick_log_text(
        placeholder, PickKind.FACTION, "The Xxcha Kingdom", 20, "Bob"
    ) == (
        "<b>Charlie</b> had their faction picked by <b>Bob</b>: <b>"
        '<a href="https://twilight-imperium.fandom.com/wiki/The_Xxcha_Kingdom">'
        "The Xxcha Kingdom</a></b>."
    )


def test_faction_links_include_irregular_wiki_pages() -> None:
    assert faction_link("The Universities of Jol-Nar") == (
        '<a href="https://twilight-imperium.fandom.com/wiki/'
        'The_Universities_of_Jol-Nar">The Universities of Jol-Nar</a>'
    )
    assert FACTION_WIKI_LINKS["The L1Z1X Mindnet"].endswith("/The_L1Z1X_Mindnet")
    assert FACTION_WIKI_LINKS["The Firmament"].endswith(
        "/The_Firmament_/_The_Obsidian"
    )
    with pytest.raises(ValueError, match="Missing wiki link"):
        faction_link("Unknown <Faction>")


def test_every_catalog_faction_has_a_wiki_link() -> None:
    catalog_names = {faction.name for faction in ContentCatalog.load().factions}
    assert set(FACTION_WIKI_LINKS) == catalog_names


def test_legacy_faction_names_link_with_canonical_display_names() -> None:
    assert faction_link("The Lizix Mindnet") == (
        '<a href="https://twilight-imperium.fandom.com/wiki/The_L1Z1X_Mindnet">'
        "The L1Z1X Mindnet</a>"
    )
    assert "The Mahact Gene-Sorcerers</a>" in faction_link(
        "The Mahact Gene-sorcerers"
    )
    assert faction_link("The Vuil'raith Cabal") == (
        '<a href="https://twilight-imperium.fandom.com/wiki/The_Vuil%27Raith_Cabal">'
        "The Vuil&#x27;Raith Cabal</a>"
    )


def test_current_picker_uses_linked_telegram_handle() -> None:
    game = Game(1, -1, GameMode.MILTY, GameStatus.DRAFTING, 1, 1)
    linked = Player(1, "Alice Example", telegram_user_id=10, telegram_username="alice")
    placeholder = Player(2, "Offline Player")
    assert "Current pick: <b>@alice</b>" in game_text(game, linked)
    assert "Current pick: <b>Offline Player</b>" in game_text(game, placeholder)


def test_draft_recap_disables_faction_link_previews() -> None:
    drafting = Game(1, -1, GameMode.MILTY, GameStatus.DRAFTING, 1, 1)
    complete = Game(2, -1, GameMode.MILTY, GameStatus.COMPLETE, 1, 1)
    options = _recap_link_preview(drafting)
    assert options is not None and options.is_disabled
    assert _recap_link_preview(complete) is None


def test_slice_draft_recap_includes_faction_pool() -> None:
    game = Game(1, -1, GameMode.MILTY, GameStatus.DRAFTING, 1, 1)
    game.setup = GeneratedSetup(
        seed=2,
        factions=[Faction("The Xxcha Kingdom", "14")],
    )

    text = game_text(game)

    assert "Faction pool:" in text
    assert "The_Xxcha_Kingdom" in text


def test_only_slice_generation_previews_an_empty_board() -> None:
    slices = Game(1, -1, GameMode.MILTY, GameStatus.ROSTER, 1, 1)
    whole = Game(2, -1, GameMode.WHOLE_BOARD, GameStatus.ROSTER, 1, 1)
    assert _show_empty_board(slices, "generate")
    assert not _show_empty_board(whole, "generate")
    assert not _show_empty_board(whole, "board_only")
    assert not _show_empty_board(whole, "reroll")


def test_choice_parser_uses_nonempty_lines() -> None:
    assert _choice_lines("/choice First\n\n Second \nThird") == [
        "First",
        "Second",
        "Third",
    ]


def test_undo_arguments_support_player_names_with_spaces() -> None:
    assert _undo_arguments("Offline Player faction") == (
        "Offline Player",
        PickKind.FACTION,
    )
    with pytest.raises(ValueError, match="faction, slice, or seat"):
        _undo_arguments("Offline Player color")
