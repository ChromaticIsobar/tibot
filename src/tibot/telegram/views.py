"""Text and keyboard construction for Telegram setup screens."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tibot.domain.models import Game, GameMode, GameStatus, PickKind, Player
from tibot.telegram.callbacks import RandomCallback, SetupCallback


def mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Slices",
        callback_data=SetupCallback(game_id=0, revision=0, action="new", value="milty"),
    )
    builder.button(
        text="Whole board",
        callback_data=SetupCallback(game_id=0, revision=0, action="new", value="whole_board"),
    )
    builder.adjust(1)
    return builder.as_markup()


def game_text(game: Game, draft_player: Player | None = None) -> str:
    title = "Slices" if game.mode is GameMode.MILTY else "Whole board"
    lines = [f"<b>{title}</b>", f"Status: {game.status.value.replace('_', ' ').title()}", ""]
    lines.append(f"Players ({len(game.players)}/6):")
    for index, player in enumerate(game.players, start=1):
        marker = " (placeholder)" if player.is_placeholder else ""
        picks = ", ".join(
            value
            for value in (
                player.faction,
                f"Slice {player.slice_id}" if player.slice_id else None,
                f"Seat {player.seat}" if player.seat else None,
            )
            if value
        )
        lines.append(f"{index}. {player.display_name}{marker}" + (f" - {picks}" if picks else ""))
    if game.status is GameStatus.ROSTER:
        lines.extend(("", "Join with the button or use /addplayer NAME."))
    if draft_player is not None:
        lines.extend(("", f"Current pick: <b>{draft_player.display_name}</b>"))
    if game.setup is not None:
        lines.extend(("", f"Seed: <code>{game.setup.seed}</code>"))
        names = {player.id: player.display_name for player in game.players}
        if game.setup.order:
            lines.extend(("", "Draft order:"))
            lines.extend(
                f"{index}. {names[player_id]}"
                for index, player_id in enumerate(game.setup.order, start=1)
            )
        if game.status is GameStatus.DRAFTING and game.setup.slices:
            lines.append("")
            lines.extend(
                f"Slice {item.id}: {', '.join(item.tiles)} "
                f"({item.resources} resources / {item.influence} influence)"
                for item in game.setup.slices
            )
        if game.mode is GameMode.WHOLE_BOARD and game.setup.factions:
            lines.extend(("", "Faction pool:"))
            lines.extend(f"- {faction.name}" for faction in game.setup.factions)
        if game.setup.speaker_player_id is not None:
            lines.extend(("", f"Speaker: <b>{names[game.setup.speaker_player_id]}</b>"))
            if game.setup.speaker_seed is not None:
                lines.append(f"Speaker seed: <code>{game.setup.speaker_seed}</code>")
        diagnostics: list[str] = []
        if game.setup.score is not None:
            diagnostics.append(f"Board score: {game.setup.score}")
        diagnostics.extend(f"Warning: {warning}" for warning in game.setup.warnings)
        if diagnostics:
            lines.extend(("", f"<tg-spoiler>{'\n'.join(diagnostics)}</tg-spoiler>"))
    return "\n".join(lines)


def roster_keyboard(game: Game, advanced: bool = False) -> InlineKeyboardMarkup:
    rows = [
            [
                _button(game, "Join", "join"),
                _button(game, "Leave", "leave"),
            ],
            [_button(game, "Generate setup", "generate")],
        ]
    if game.mode is GameMode.WHOLE_BOARD:
        rows.append([_button(game, "Board only (Twilight's Fall)", "board_only")])
    rows.append([_button(game, "Advanced commands", "advanced")])
    if advanced:
        rows.extend(
            [
                [_button(game, "Manual player", "help_add")],
                [_button(game, "Seed and pool sizes", "help_generate")],
            ]
        )
    rows.append([_button(game, "Cancel", "cancel")])
    rows.append([_button(game, "Start new setup", "new_setup")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_keyboard(
    game: Game,
    player: Player,
    options: dict[PickKind, list[str]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if player.faction is None:
        for value in options[PickKind.FACTION]:
            builder.button(text=value, callback_data=_callback(game, "faction", value))
    if player.slice_id is None:
        for value in options[PickKind.SLICE]:
            builder.button(text=f"Slice {value}", callback_data=_callback(game, "slice", value))
    if player.seat is None:
        for value in options[PickKind.SEAT]:
            label = f"Seat {value}"
            if game.mode is GameMode.MILTY and value == "1":
                label += " (Speaker)"
            builder.button(text=label, callback_data=_callback(game, "seat", value))
    builder.button(text="Start new setup", callback_data=_callback(game, "new_setup", "_"))
    builder.adjust(1)
    return builder.as_markup()


def complete_keyboard(game: Game) -> InlineKeyboardMarkup | None:
    if game.mode is not GameMode.WHOLE_BOARD:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[_button(game, "Reroll", "reroll")]])


def random_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for count in range(3, 9):
        builder.button(
            text=f"{count} factions",
            callback_data=RandomCallback(action="factions", value=count),
        )
    builder.button(text="Player order", callback_data=RandomCallback(action="order", value=0))
    builder.button(text="Speaker", callback_data=RandomCallback(action="speaker", value=0))
    builder.button(text="Seating order", callback_data=RandomCallback(action="seating", value=0))
    builder.adjust(2)
    return builder.as_markup()


def _button(game: Game, text: str, action: str, value: str = "_") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=_callback(game, action, value))


def _callback(game: Game, action: str, value: str) -> str:
    return SetupCallback(
        game_id=game.id,
        revision=game.revision,
        action=action,
        value=value,
    ).pack()
