"""Telegram commands and inline-button handlers."""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, LinkPreviewOptions, Message

from tibot.application.service import GameService
from tibot.domain.models import Game, GameMode, GameStatus, PickKind, Player
from tibot.infrastructure.database import ConflictError
from tibot.telegram.callbacks import RandomCallback, SetupCallback
from tibot.telegram.formatting import faction_link
from tibot.telegram.views import (
    complete_keyboard,
    draft_confirmation_keyboard,
    draft_keyboard,
    game_text,
    mode_keyboard,
    random_keyboard,
    roster_keyboard,
    seed_line,
)

logger = logging.getLogger(__name__)


def create_router(service: GameService) -> Router:
    router = Router(name="tibot")

    @router.message(Command("start", "help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "<b>TIBot</b> prepares 3-6 player Twilight Imperium games.\n\n"
            "/setup - create or resume a setup\n"
            "/addplayer NAME - add a handle or placeholder\n"
            "/removeplayer NAME - remove a roster player\n"
            "/undo - undo the latest draft choice\n"
            "/undo PLAYER CHOICE - rewind a specific faction, slice, or seat pick\n"
            "/generate [SEED] [factions=N] [slices=N] - generate with overrides\n"
            "/board [SEED] - generate only a whole board\n"
            "/claim NAME - claim a placeholder\n"
            "/randomize - standalone randomizers\n"
            "/choice - choose from non-empty lines\n"
            "/die N - roll a number from 1 through N\n"
            "/result - show the active setup",
            parse_mode="HTML",
        )

    @router.message(Command("setup"))
    async def setup_command(message: Message, command: CommandObject) -> None:
        if message.chat.type == "private":
            await message.answer("Add me to a group chat to prepare a game.")
            return
        game = await service.repository.get_active(message.chat.id)
        if command.args and command.args.strip().casefold() == "new":
            if game is not None and not _joined(game, _message_user(message).id):
                await message.answer("Join the active setup before replacing it.")
                return
            await message.answer("Choose a new setup mode:", reply_markup=mode_keyboard())
            return
        if game is None:
            await message.answer("Choose a setup mode:", reply_markup=mode_keyboard())
        else:
            await _send_game(message, game, service)

    @router.message(Command("addplayer"))
    async def add_player_command(message: Message, command: CommandObject) -> None:
        game = await service.repository.get_active(message.chat.id)
        if game is None:
            await message.answer("Start a setup first with /setup.")
            return
        user = _message_user(message)
        if not _joined(game, user.id):
            await message.answer("Only joined players can add placeholders.")
            return
        name = (command.args or "").strip()
        if not name:
            await message.answer("Usage: /addplayer NAME or /addplayer @handle")
            return
        await _run_message(message, service.add_placeholder(game, name), service)

    @router.message(Command("removeplayer"))
    async def remove_player_command(message: Message, command: CommandObject) -> None:
        game = await _controlled_roster(message, service)
        if game is None:
            return
        name = (command.args or "").strip()
        if not name:
            await message.answer("Usage: /removeplayer NAME")
            return
        await _run_message(
            message,
            service.remove_player(game, name, _message_user(message).id),
            service,
        )

    @router.message(Command("claim"))
    async def claim_command(message: Message, command: CommandObject) -> None:
        game = await service.repository.get_active(message.chat.id)
        if game is None:
            await message.answer("There is no active setup.")
            return
        name = (command.args or "").strip()
        if not name:
            await message.answer("Usage: /claim NAME")
            return
        user = _message_user(message)
        try:
            await service.repository.claim(
                game.id, name, user.id, user.username
            )
            await message.answer(f"Claimed {html.escape(name)}.")
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("generate"))
    async def generate_command(message: Message, command: CommandObject) -> None:
        game = await _controlled_roster(message, service)
        if game is None:
            return
        try:
            seed, factions, slices = _generation_arguments(command.args)
            await _run_message(
                message,
                service.generate(game, seed, factions, slices),
                service,
                publish_slices=True,
                empty_game=game if _show_empty_board(game, "generate") else None,
            )
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("board"))
    async def board_command(message: Message, command: CommandObject) -> None:
        game = await _controlled_roster(message, service)
        if game is None:
            return
        try:
            seed = int(command.args) if command.args else None
            await _run_message(
                message,
                service.generate_board_only(game, seed),
                service,
            )
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("undo"))
    async def undo_command(message: Message, command: CommandObject) -> None:
        game = await service.repository.get_active(message.chat.id)
        if game is None or game.status is not GameStatus.DRAFTING:
            await message.answer("There is no active draft to rewind.")
            return
        user = _message_user(message)
        if not _joined(game, user.id):
            await message.answer("Join the setup before controlling it.")
            return
        try:
            if command.args and command.args.strip():
                player_name, kind = _undo_arguments(command.args)
                game, rewound = await service.undo_choice(
                    game, player_name, kind, user.id
                )
            else:
                game, player_name, kind = await service.undo_last_choice(game, user.id)
                rewound = 1
            suffix = "" if rewound == 1 else f" and {rewound - 1} later pick(s)"
            await message.answer(
                f"<b>{html.escape(user.full_name)}</b> rewound "
                f"<b>{html.escape(player_name)}</b>'s {kind.value} choice{suffix}.",
                parse_mode="HTML",
            )
            await _send_game(message, game, service)
        except (ValueError, ConflictError) as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("randomize"))
    async def randomize_command(message: Message) -> None:
        await message.answer("Choose a randomizer:", reply_markup=random_keyboard())

    @router.message(Command("choice"))
    async def choice_command(message: Message) -> None:
        try:
            choice, seed = service.generator.random_choice(_choice_lines(message.text))
            await message.answer(
                f"Choice: <b>{html.escape(choice)}</b>\n\n{seed_line(seed)}",
                parse_mode="HTML",
            )
        except ValueError as exc:
            await message.answer(
                f"{html.escape(str(exc))}\n\n"
                "Put each option on its own line after /choice."
            )

    @router.message(Command("die"))
    async def die_command(message: Message, command: CommandObject) -> None:
        try:
            if not command.args or len(command.args.split()) != 1:
                raise ValueError("Usage: /die N")
            result, seed = service.generator.random_die(int(command.args))
            await message.answer(
                f"d{int(command.args)}: <b>{result}</b>\n\n{seed_line(seed)}",
                parse_mode="HTML",
            )
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("result"))
    async def result_command(message: Message) -> None:
        game = await service.repository.get_latest(message.chat.id)
        if game is None:
            await message.answer("There is no setup in this chat yet.")
            return
        await _send_game(message, game, service)

    @router.callback_query(SetupCallback.filter())
    async def setup_callback(query: CallbackQuery, callback_data: SetupCallback) -> None:
        if query.message is None:
            return
        picked_player_id: int | None = None
        game: Game | None = None
        control_removed = False
        try:
            if callback_data.action == "new":
                await query.answer()
                if isinstance(query.message, Message):
                    await _dismiss_control(query.message)
                    control_removed = True
                game = await service.begin(
                    query.message.chat.id,
                    query.from_user.id,
                    query.from_user.full_name,
                    query.from_user.username,
                    GameMode(callback_data.value),
                )
            else:
                loaded_game = await service.repository.get_game(callback_data.game_id)
                if loaded_game is None or loaded_game.chat_id != query.message.chat.id:
                    raise ValueError("This setup no longer exists")
                game = loaded_game
                if game.revision != callback_data.revision:
                    raise ConflictError("This screen is stale; use /setup to refresh")
                if callback_data.action == "new_setup":
                    if not _joined(game, query.from_user.id):
                        raise ValueError("Join the setup before replacing it")
                    await query.answer()
                    if isinstance(query.message, Message):
                        await _replace_with_mode_picker(query.message)
                    return
                if callback_data.action == "advanced":
                    await query.answer()
                    if isinstance(query.message, Message):
                        await _dismiss_control(query.message)
                        control_removed = True
                    await _edit_game(query, game, service, advanced=True)
                    return
                if callback_data.action == "help_add":
                    await query.answer(
                        "Send /addplayer NAME, /addplayer @handle, or /removeplayer NAME",
                        show_alert=True,
                    )
                    return
                if callback_data.action == "help_generate":
                    await query.answer(
                        "Send /generate [SEED] [factions=N] [slices=N], or /board [SEED]",
                        show_alert=True,
                    )
                    return
                if callback_data.action in {kind.value for kind in PickKind}:
                    draft = await service.repository.get_draft(game.id)
                    picked_player_id = draft.current_player_id
                await query.answer()
                if isinstance(query.message, Message):
                    await _dismiss_control(query.message)
                    control_removed = True
                    if _show_empty_board(game, callback_data.action):
                        await _send_empty_board(query.message, game, service)
                game = await _apply_setup_action(query, callback_data, game, service)
            publish_board = callback_data.action in {"generate", "reroll"}
            if callback_data.action == "undo_last" and isinstance(query.message, Message):
                await query.message.answer("The last draft choice was undone.")
            if callback_data.action in {"start", "undo_last"}:
                publish_board = True
            if (
                callback_data.action == "generate"
                and game.setup is not None
                and game.setup.slices
                and isinstance(query.message, Message)
            ):
                await _send_slices(query.message, game, service)
            if picked_player_id is not None and isinstance(query.message, Message):
                kind = PickKind(callback_data.action)
                await _send_pick_log(
                    query.message,
                    game,
                    picked_player_id,
                    kind,
                    callback_data.value,
                    query.from_user.id,
                    query.from_user.full_name,
                )
                publish_board = _pick_changes_board(game, picked_player_id)
            await _edit_game(query, game, service, publish_board=publish_board)
        except (ValueError, ConflictError) as exc:
            if control_removed and isinstance(query.message, Message):
                await query.message.answer(html.escape(str(exc)))
                if game is not None:
                    current = await service.repository.get_game(game.id)
                    if current is not None:
                        await _send_game(query.message, current, service)
                else:
                    await query.message.answer(
                        "Choose a setup mode:", reply_markup=mode_keyboard()
                    )
            else:
                await query.answer(str(exc), show_alert=True)
        except Exception:
            logger.exception("Setup callback failed")
            if control_removed and isinstance(query.message, Message):
                await query.message.answer("The setup could not be updated. Try again.")
                if game is not None:
                    current = await service.repository.get_game(game.id)
                    if current is not None:
                        await _send_game(query.message, current, service)
                else:
                    await query.message.answer(
                        "Choose a setup mode:", reply_markup=mode_keyboard()
                    )
            else:
                await query.answer(
                    "The setup could not be updated. Try again.", show_alert=True
                )

    @router.callback_query(RandomCallback.filter())
    async def random_callback(query: CallbackQuery, callback_data: RandomCallback) -> None:
        game = await service.repository.get_active(query.message.chat.id) if query.message else None
        try:
            if callback_data.action == "factions":
                result = service.generator.random_factions(callback_data.value)
                text = "\n".join(
                    f"{i}. {faction_link(f.name)}" for i, f in enumerate(result.factions, 1)
                )
            else:
                if game is None or not game.players:
                    raise ValueError("This randomizer needs an active setup roster")
                player_ids = [player.id for player in game.players if player.id is not None]
                result = service.generator.random_order(player_ids)
                names = {player.id: player.display_name for player in game.players}
                ordered = [names[player_id] for player_id in result.order]
                if callback_data.action == "speaker":
                    text = f"Speaker: {ordered[0]}"
                elif callback_data.action == "player":
                    text = f"Random player: {ordered[0]}"
                else:
                    text = "\n".join(f"{i}. {name}" for i, name in enumerate(ordered, 1))
            await query.answer()
            if query.message:
                await query.message.answer(
                    f"{text}\n\n{seed_line(result.seed)}", parse_mode="HTML"
                )
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)

    return router


async def _apply_setup_action(
    query: CallbackQuery,
    data: SetupCallback,
    game: Game,
    service: GameService,
) -> Game:
    user = query.from_user
    if data.action == "join":
        return await service.join(game, user.id, user.full_name, user.username)
    if data.action == "leave":
        return await service.leave(game, user.id)
    if not _joined(game, user.id):
        raise ValueError("Join the setup before controlling it")
    if data.action == "generate":
        return await service.generate(game)
    if data.action == "board_only":
        return await service.generate_board_only(game)
    if data.action == "reroll":
        return await service.reroll(game)
    if data.action == "start":
        return await service.confirm_start(game, user.id)
    if data.action == "undo_last":
        updated, _, _ = await service.undo_last_choice(game, user.id)
        return updated
    if data.action == "cancel":
        await service.repository.cancel(game)
        game.status = GameStatus.CANCELLED
        return game
    if data.action in {kind.value for kind in PickKind}:
        return await service.pick(game, PickKind(data.action), data.value, user.id)
    raise ValueError("Unknown setup action")


async def _send_game(message: Message, game: Game, service: GameService) -> None:
    await _send_board(message, game, service)
    draft_player, markup = await _screen(game, service)
    await message.answer(
        game_text(game, draft_player),
        parse_mode="HTML",
        reply_markup=markup,
        link_preview_options=_recap_link_preview(game),
    )


async def _edit_game(
    query: CallbackQuery,
    game: Game,
    service: GameService,
    *,
    publish_board: bool = False,
    advanced: bool = False,
) -> None:
    if not isinstance(query.message, Message):
        return
    draft_player, markup = await _screen(game, service, advanced=advanced)
    if publish_board or game.status is GameStatus.COMPLETE:
        await _send_board(query.message, game, service)
    await query.message.answer(
        game_text(game, draft_player),
        parse_mode="HTML",
        reply_markup=markup,
        link_preview_options=_recap_link_preview(game),
    )


def _recap_link_preview(game: Game) -> LinkPreviewOptions | None:
    if game.status is GameStatus.DRAFTING:
        return LinkPreviewOptions(is_disabled=True)
    return None


def _show_empty_board(game: Game, action: str) -> bool:
    return game.mode is GameMode.MILTY and action == "generate"


async def _screen(  # type: ignore[no-untyped-def]
    game: Game, service: GameService, *, advanced: bool = False
):
    if game.status is GameStatus.ROSTER:
        return None, roster_keyboard(game, advanced)
    if game.status is GameStatus.DRAFTING:
        draft = await service.repository.get_draft(game.id)
        if draft.complete:
            return None, draft_confirmation_keyboard(game)
        player = next(item for item in game.players if item.id == draft.current_player_id)
        options = {
            kind: await service.repository.available_options(game.id, kind) for kind in PickKind
        }
        return player, draft_keyboard(game, player, options)
    return None, complete_keyboard(game)


async def _send_board(message: Message, game: Game, service: GameService) -> None:
    image = await service.render_result(game)
    if image:
        assert game.setup is not None
        await message.answer_photo(
            BufferedInputFile(image, filename=f"tibot-{game.setup.seed}.png")
        )


async def _send_empty_board(message: Message, game: Game, service: GameService) -> None:
    image = await service.render_empty_board(game)
    await message.answer_photo(
        BufferedInputFile(image, filename=f"tibot-empty-{len(game.players)}p.png")
    )


async def _send_slices(message: Message, game: Game, service: GameService) -> None:
    assert game.setup is not None
    slices = {item.id: item for item in game.setup.slices}
    for slice_id, image in await service.render_slices(game):
        item = slices[slice_id]
        await message.answer_photo(
            BufferedInputFile(image, filename=f"slice-{slice_id}.png"),
            caption=(
                f"<b>Slice {slice_id}</b>\n"
                f"{item.resources} resources / {item.influence} influence"
            ),
            parse_mode="HTML",
        )


async def _send_pick_log(
    message: Message,
    game: Game,
    player_id: int,
    kind: PickKind,
    value: str,
    actor_id: int,
    actor_name: str,
) -> None:
    player = next(item for item in game.players if item.id == player_id)
    await message.answer(
        _pick_log_text(player, kind, value, actor_id, actor_name),
        parse_mode="HTML",
    )


def _pick_log_text(
    player: Player,
    kind: PickKind,
    value: str,
    actor_id: int,
    actor_name: str,
) -> str:
    choice = f"Slice {value}" if kind is PickKind.SLICE else value
    player_name = html.escape(player.display_name)
    escaped_choice = (
        faction_link(value) if kind is PickKind.FACTION else html.escape(choice)
    )
    if player.telegram_user_id == actor_id:
        return f"<b>{player_name}</b> chose {kind.value}: <b>{escaped_choice}</b>."
    return (
        f"<b>{player_name}</b> had their {kind.value} picked by "
        f"<b>{html.escape(actor_name)}</b>: <b>{escaped_choice}</b>."
    )


def _pick_changes_board(game: Game, player_id: int) -> bool:
    player = next(item for item in game.players if item.id == player_id)
    return player.seat is not None


async def _run_message(  # type: ignore[no-untyped-def]
    message: Message,
    operation,
    service: GameService,
    *,
    publish_slices: bool = False,
    empty_game: Game | None = None,
) -> None:
    try:
        if empty_game is not None:
            await _send_empty_board(message, empty_game, service)
        game = await operation
        if publish_slices:
            await _send_slices(message, game, service)
        await _send_game(message, game, service)
    except (ValueError, ConflictError) as exc:
        await message.answer(html.escape(str(exc)))


def _joined(game: Game, user_id: int) -> bool:
    return any(player.telegram_user_id == user_id for player in game.players)


def _message_user(message: Message):  # type: ignore[no-untyped-def]
    if message.from_user is None:
        raise ValueError("This command requires a Telegram user")
    return message.from_user


async def _controlled_roster(message: Message, service: GameService) -> Game | None:
    game = await service.repository.get_active(message.chat.id)
    if game is None or game.status is not GameStatus.ROSTER:
        await message.answer("Start or resume a roster first with /setup.")
        return None
    user = _message_user(message)
    if not _joined(game, user.id):
        await message.answer("Join the setup before controlling it.")
        return None
    return game


def _generation_arguments(arguments: str | None) -> tuple[int | None, int | None, int | None]:
    seed = factions = slices = None
    for argument in (arguments or "").split():
        if argument.startswith("factions="):
            factions = int(argument.removeprefix("factions="))
        elif argument.startswith("slices="):
            slices = int(argument.removeprefix("slices="))
        elif seed is None:
            seed = int(argument)
        else:
            raise ValueError("Usage: /generate [SEED] [factions=N] [slices=N]")
    return seed, factions, slices


def _choice_lines(text: str | None) -> list[str]:
    if not text:
        return []
    first, *remaining = text.splitlines()
    first_choice = first.partition(" ")[2].strip()
    return [choice.strip() for choice in (first_choice, *remaining) if choice.strip()]


def _undo_arguments(arguments: str | None) -> tuple[str, PickKind]:
    if not arguments or len(arguments.rsplit(maxsplit=1)) != 2:
        raise ValueError("Usage: /undo PLAYER NAME <faction|slice|seat>")
    player_name, raw_kind = arguments.rsplit(maxsplit=1)
    try:
        return player_name.strip(), PickKind(raw_kind.casefold())
    except ValueError as exc:
        raise ValueError("Choice must be faction, slice, or seat") from exc


async def _replace_with_mode_picker(message: Message) -> None:
    await _dismiss_control(message)
    await message.answer("Choose a new setup mode:", reply_markup=mode_keyboard())


async def _dismiss_control(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        await message.edit_reply_markup(reply_markup=None)
