"""TIBot process entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from tibot.application import GameService
from tibot.config import Settings
from tibot.domain import ContentCatalog, SetupGenerator
from tibot.domain.rendering import BoardRenderer
from tibot.infrastructure import GameRepository
from tibot.telegram import create_router


async def run() -> None:
    settings = Settings.from_environment()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    catalog = ContentCatalog.load()
    repository = GameRepository(settings.database_path)
    await repository.open()
    service = GameService(
        repository,
        SetupGenerator(catalog),
        BoardRenderer(catalog.tile_image_dir, Path(__file__).parent / "assets"),
    )
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(service))
    await bot.set_my_commands(
        [
            BotCommand(command="setup", description="Create or resume a game setup"),
            BotCommand(command="addplayer", description="Add a handle or placeholder"),
            BotCommand(command="removeplayer", description="Remove a roster player"),
            BotCommand(command="undo", description="Undo the latest or a selected draft choice"),
            BotCommand(command="generate", description="Generate with seed or pool overrides"),
            BotCommand(command="board", description="Generate only a whole board"),
            BotCommand(command="claim", description="Claim a placeholder seat"),
            BotCommand(command="randomize", description="Open standalone randomizers"),
            BotCommand(command="choice", description="Choose from newline-separated options"),
            BotCommand(command="die", description="Roll a number from 1 through N"),
            BotCommand(command="result", description="Show the active setup"),
            BotCommand(command="help", description="Show help"),
        ]
    )
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await repository.close()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
