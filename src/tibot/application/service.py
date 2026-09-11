"""Use cases shared by Telegram and tests."""

from __future__ import annotations

import asyncio

from tibot.domain.generation import SetupGenerator
from tibot.domain.models import DraftState, Game, GameMode, GameStatus, PickKind
from tibot.domain.rendering import BoardRenderer
from tibot.infrastructure.database import GameRepository


class GameService:
    def __init__(
        self,
        repository: GameRepository,
        generator: SetupGenerator,
        renderer: BoardRenderer,
    ) -> None:
        self.repository = repository
        self.generator = generator
        self.renderer = renderer

    async def begin(
        self,
        chat_id: int,
        creator_id: int,
        creator_name: str,
        username: str | None,
        mode: GameMode,
    ) -> Game:
        game = await self.repository.create_game(chat_id, creator_id, mode)
        await self.repository.add_player(game.id, creator_name, creator_id, username)
        refreshed = await self.repository.get_game(game.id)
        assert refreshed is not None
        return refreshed

    async def join(self, game: Game, user_id: int, name: str, username: str | None) -> Game:
        handle = f"@{username}".casefold() if username else None
        placeholder = next(
            (
                player
                for player in game.players
                if player.is_placeholder
                and handle
                and player.display_name.casefold() == handle
            ),
            None,
        )
        if placeholder is not None:
            await self.repository.claim(game.id, placeholder.display_name, user_id, username)
            return await self._required_game(game.id)
        await self.repository.add_player(game.id, name, user_id, username)
        return await self._required_game(game.id)

    async def add_placeholder(self, game: Game, name: str) -> Game:
        self._require_controller(game, None)
        if not name.strip() or len(name.strip()) > 40:
            raise ValueError("Player names must contain 1 to 40 characters")
        await self.repository.add_player(game.id, name.strip())
        return await self._required_game(game.id)

    async def leave(self, game: Game, user_id: int) -> Game:
        if not await self.repository.remove_user(game.id, user_id):
            raise ValueError("You are not a removable player in this roster")
        return await self._required_game(game.id)

    async def generate(self, game: Game, seed: int | None = None) -> Game:
        self._require_controller(game, None)
        if any(player.id is None for player in game.players):
            raise RuntimeError("Persisted players must have IDs")
        ids = [player.id for player in game.players if player.id is not None]
        if game.mode is GameMode.MILTY:
            setup = await asyncio.to_thread(self.generator.milty, ids, seed)
            draft = DraftState(tuple(setup.order))
            return await self.repository.save_generation(game, setup, GameStatus.DRAFTING, draft)
        setup = await asyncio.to_thread(self.generator.whole_board, ids, seed)
        return await self.repository.save_generation(game, setup, GameStatus.COMPLETE)

    async def reroll(self, game: Game) -> Game:
        if game.status is GameStatus.DRAFTING:
            raise ValueError("A draft cannot be rerolled after picking has started")
        return await self.generate(game)

    async def pick(
        self,
        game: Game,
        kind: PickKind,
        value: str,
        acting_user_id: int,
    ) -> Game:
        if game.status is not GameStatus.DRAFTING:
            raise ValueError("This game does not have an active draft")
        draft = await self.repository.get_draft(game.id)
        player_id = draft.current_player_id
        if player_id is None:
            raise ValueError("Draft is already complete")
        self._require_controller(game, acting_user_id)
        updated = await self.repository.pick(game, player_id, kind, value, acting_user_id)
        if updated.status is GameStatus.COMPLETE:
            assert updated.setup is not None
            await asyncio.to_thread(self.generator.assemble_milty, updated.setup, updated.players)
            updated = await self.repository.finalize_setup(updated)
        return updated

    async def render_result(self, game: Game) -> bytes | None:
        if game.setup is None or not game.setup.board:
            return None
        return await asyncio.to_thread(self.renderer.render_board, game.setup.board)

    @staticmethod
    def _require_controller(game: Game, user_id: int | None) -> None:
        if user_id is not None and not any(
            player.telegram_user_id == user_id for player in game.players
        ):
            raise ValueError("Only joined players can control this setup")

    async def _required_game(self, game_id: int) -> Game:
        game = await self.repository.get_game(game_id)
        if game is None:
            raise ValueError("Game no longer exists")
        return game
