"""Telegram commands and inline-button handlers."""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from tibot.application.service import GameService
from tibot.domain.models import Game, GameMode, GameStatus, PickKind
from tibot.infrastructure.database import ConflictError
from tibot.telegram.callbacks import RandomCallback, SetupCallback
from tibot.telegram.views import (
    complete_keyboard,
    draft_keyboard,
    game_text,
    mode_keyboard,
    random_keyboard,
    roster_keyboard,
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
            "/generate [SEED] [factions=N] [slices=N] - generate with overrides\n"
            "/board [SEED] - generate only a whole board\n"
            "/claim NAME - claim a placeholder\n"
            "/randomize - standalone randomizers\n"
            "/result - show the active setup",
            parse_mode="HTML",
        )

    @router.message(Command("setup"))
    async def setup_command(message: Message) -> None:
        if message.chat.type == "private":
            await message.answer("Add me to a group chat to prepare a game.")
            return
        game = await service.repository.get_active(message.chat.id)
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
            await _run_message(message, service.generate_board_only(game, seed), service)
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))

    @router.message(Command("randomize"))
    async def randomize_command(message: Message) -> None:
        await message.answer("Choose a randomizer:", reply_markup=random_keyboard())

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
        try:
            if callback_data.action == "new":
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
                if callback_data.action == "advanced":
                    await query.answer()
                    await _edit_game(query, game, service, advanced=True)
                    return
                if callback_data.action == "help_add":
                    await query.answer(
                        "Send /addplayer NAME or /addplayer @handle",
                        show_alert=True,
                    )
                    return
                if callback_data.action == "help_generate":
                    await query.answer(
                        "Send /generate [SEED] [factions=N] [slices=N], or /board [SEED]",
                        show_alert=True,
                    )
                    return
                game = await _apply_setup_action(query, callback_data, game, service)
            await query.answer()
            publish_board = callback_data.action in {"generate", "reroll"}
            await _edit_game(query, game, service, publish_board=publish_board)
        except (ValueError, ConflictError) as exc:
            await query.answer(str(exc), show_alert=True)
        except Exception:
            logger.exception("Setup callback failed")
            await query.answer("The setup could not be updated. Try again.", show_alert=True)

    @router.callback_query(RandomCallback.filter())
    async def random_callback(query: CallbackQuery, callback_data: RandomCallback) -> None:
        game = await service.repository.get_active(query.message.chat.id) if query.message else None
        try:
            if callback_data.action == "factions":
                result = service.generator.random_factions(callback_data.value)
                text = "\n".join(f"{i}. {f.name}" for i, f in enumerate(result.factions, 1))
            else:
                if game is None or not game.players:
                    raise ValueError("This randomizer needs an active setup roster")
                player_ids = [player.id for player in game.players if player.id is not None]
                result = service.generator.random_order(player_ids)
                names = {player.id: player.display_name for player in game.players}
                ordered = [names[player_id] for player_id in result.order]
                if callback_data.action == "speaker":
                    text = f"Speaker: {ordered[0]}"
                else:
                    text = "\n".join(f"{i}. {name}" for i, name in enumerate(ordered, 1))
            await query.answer()
            if query.message:
                await query.message.answer(
                    f"{text}\n\nSeed: <code>{result.seed}</code>", parse_mode="HTML"
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
    if data.action == "cancel":
        await service.repository.cancel(game)
        game.status = GameStatus.CANCELLED
        return game
    if data.action in {kind.value for kind in PickKind}:
        return await service.pick(game, PickKind(data.action), data.value, user.id)
    raise ValueError("Unknown setup action")


async def _send_game(message: Message, game: Game, service: GameService) -> None:
    draft_player, markup = await _screen(game, service)
    await message.answer(
        game_text(game, draft_player),
        parse_mode="HTML",
        reply_markup=markup,
    )
    await _send_board(message, game, service)


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
    await query.message.edit_text(
        game_text(game, draft_player), parse_mode="HTML", reply_markup=markup
    )
    if publish_board or game.status is GameStatus.COMPLETE:
        await _send_board(query.message, game, service)


async def _screen(  # type: ignore[no-untyped-def]
    game: Game, service: GameService, *, advanced: bool = False
):
    if game.status is GameStatus.ROSTER:
        return None, roster_keyboard(game, advanced)
    if game.status is GameStatus.DRAFTING:
        draft = await service.repository.get_draft(game.id)
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


async def _run_message(message: Message, operation, service: GameService) -> None:  # type: ignore[no-untyped-def]
    try:
        game = await operation
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
