"""SQLite repository for durable setup workflows."""

from __future__ import annotations

import asyncio
import json
from importlib import resources
from pathlib import Path

import aiosqlite

from tibot.domain.models import (
    DraftState,
    Game,
    GameMode,
    GameStatus,
    GeneratedSetup,
    PickKind,
    Player,
)
from tibot.infrastructure.sql_loader import load_queries

SQL = load_queries()

class ConflictError(RuntimeError):
    """The requested state transition lost an optimistic concurrency race."""


class GameRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        sql_root = resources.files("tibot.infrastructure.sql")
        configure_sql = sql_root.joinpath("configure.sql").read_text(encoding="utf-8")
        await self._connection.executescript(configure_sql)
        initial_sql = sql_root.joinpath("001_initial.sql").read_text(encoding="utf-8")
        await self._connection.executescript(initial_sql)
        version_cursor = await self._connection.execute(SQL["healthcheck"])
        version_row = await version_cursor.fetchone()
        version = int(version_row["version"]) if version_row else 1
        migrations = sorted(
            (item for item in sql_root.iterdir() if item.name[:3].isdigit()),
            key=lambda item: item.name,
        )
        for migration in migrations:
            migration_version = int(migration.name[:3])
            if migration_version > version:
                await self._connection.executescript(migration.read_text(encoding="utf-8"))
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Repository is not open")
        return self._connection

    async def create_game(self, chat_id: int, creator_id: int, mode: GameMode) -> Game:
        async with self._lock:
            await self.connection.execute(
                SQL["archive_active_games"],
                (chat_id,),
            )
            cursor = await self.connection.execute(
                SQL["create_game"],
                (chat_id, mode.value, GameStatus.ROSTER.value, creator_id),
            )
            await self.connection.commit()
            game_id = cursor.lastrowid
            assert game_id is not None
        game = await self.get_game(game_id)
        assert game is not None
        return game

    async def get_active(self, chat_id: int) -> Game | None:
        cursor = await self.connection.execute(
            SQL["get_active_game_id"],
            (chat_id,),
        )
        row = await cursor.fetchone()
        return await self.get_game(int(row["id"])) if row else None

    async def get_latest(self, chat_id: int) -> Game | None:
        cursor = await self.connection.execute(
            SQL["get_latest_game_id"], (chat_id,)
        )
        row = await cursor.fetchone()
        return await self.get_game(int(row["id"])) if row else None

    async def get_game(self, game_id: int) -> Game | None:
        cursor = await self.connection.execute(SQL["get_game"], (game_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        players_cursor = await self.connection.execute(
            SQL["get_players"], (game_id,)
        )
        players = [_player_from_row(item) for item in await players_cursor.fetchall()]
        return Game(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            mode=GameMode(row["mode"]),
            status=GameStatus(row["status"]),
            revision=int(row["revision"]),
            created_by=int(row["created_by"]),
            players=players,
            setup=_setup_from_json(row["setup_json"]),
            previous_setup=_setup_from_json(row["previous_setup_json"]),
        )

    async def add_player(
        self,
        game_id: int,
        display_name: str,
        telegram_user_id: int | None = None,
        telegram_username: str | None = None,
    ) -> Player:
        async with self._lock:
            cursor = await self.connection.execute(
                SQL["get_game_status"], (game_id,)
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != GameStatus.ROSTER.value:
                raise ValueError("Players can only be added while building the roster")
            count_cursor = await self.connection.execute(
                SQL["count_players"], (game_id,)
            )
            count_row = await count_cursor.fetchone()
            assert count_row is not None
            if int(count_row["count"]) >= 6:
                raise ValueError("A game can have at most 6 players")
            try:
                inserted = await self.connection.execute(
                    SQL["add_player"],
                    (game_id, display_name.strip(), telegram_user_id, telegram_username),
                )
            except aiosqlite.IntegrityError as exc:
                raise ValueError("That player is already in the roster") from exc
            await self._bump(game_id)
            await self.connection.commit()
            player_id = inserted.lastrowid
            assert player_id is not None
        return Player(player_id, display_name.strip(), telegram_user_id, telegram_username)

    async def remove_user(self, game_id: int, telegram_user_id: int) -> bool:
        async with self._lock:
            cursor = await self.connection.execute(
                SQL["remove_user"],
                (game_id, telegram_user_id, game_id),
            )
            if cursor.rowcount:
                await self._bump(game_id)
                await self.connection.commit()
            return bool(cursor.rowcount)

    async def claim(self, game_id: int, name: str, user_id: int, username: str | None) -> None:
        async with self._lock:
            try:
                cursor = await self.connection.execute(
                    SQL["claim_player"],
                    (user_id, username, game_id, name.strip()),
                )
            except aiosqlite.IntegrityError as exc:
                raise ValueError("You already occupy a seat") from exc
            if cursor.rowcount != 1:
                raise ValueError("No unclaimed placeholder has that name")
            await self._bump(game_id)
            await self.connection.commit()

    async def save_generation(
        self,
        game: Game,
        setup: GeneratedSetup,
        status: GameStatus,
        draft: DraftState | None = None,
    ) -> Game:
        async with self._lock:
            encoded = json.dumps(setup.to_dict(), separators=(",", ":"))
            order = json.dumps(draft.player_order) if draft else None
            cursor = await self.connection.execute(
                SQL["save_generation"],
                (
                    encoded,
                    setup.seed,
                    status.value,
                    order,
                    draft.pick_index if draft else 0,
                    game.id,
                    game.revision,
                ),
            )
            if cursor.rowcount != 1:
                await self.connection.rollback()
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.execute(
                SQL["retire_results"], (game.id,)
            )
            await self.connection.execute(
                SQL["add_result"],
                (game.id, setup.seed, encoded),
            )
            await self.connection.execute(
                SQL["clear_options"], (game.id,)
            )
            if status is GameStatus.DRAFTING:
                for faction in setup.factions:
                    await self.connection.execute(
                        SQL["add_faction_option"],
                        (game.id, faction.name, json.dumps({"home_system": faction.home_system})),
                    )
                for item in setup.slices:
                    await self.connection.execute(
                        SQL["add_slice_option"],
                        (game.id, str(item.id), json.dumps({"tiles": item.tiles})),
                    )
                for seat in range(1, len(game.players) + 1):
                    await self.connection.execute(
                        SQL["add_seat_option"],
                        (game.id, str(seat)),
                    )
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def get_draft(self, game_id: int) -> DraftState:
        cursor = await self.connection.execute(
            SQL["get_draft"], (game_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["draft_order_json"] is None:
            raise ValueError("Game does not have an active draft")
        required = (
            (PickKind.FACTION, PickKind.SLICE, PickKind.SEAT)
            if GameMode(row["mode"]) is GameMode.MILTY
            else (PickKind.FACTION, PickKind.SEAT)
        )
        return DraftState(
            tuple(json.loads(row["draft_order_json"])),
            required,
            int(row["draft_pick_index"]),
        )

    async def reset_completed_draft(self, game: Game) -> Game:
        async with self._lock:
            cursor = await self.connection.execute(
                SQL["reset_completed_game"], (game.id, game.revision)
            )
            if cursor.rowcount != 1:
                await self.connection.rollback()
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.execute(SQL["reset_player_picks"], (game.id,))
            await self.connection.execute(SQL["clear_draft_picks"], (game.id,))
            await self.connection.execute(SQL["clear_options"], (game.id,))
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def finalize_setup(self, game: Game) -> Game:
        if game.setup is None:
            raise ValueError("Game has no generated setup")
        encoded = json.dumps(game.setup.to_dict(), separators=(",", ":"))
        async with self._lock:
            cursor = await self.connection.execute(
                SQL["finalize_setup"],
                (encoded, game.id, game.revision),
            )
            if cursor.rowcount != 1:
                await self.connection.rollback()
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.execute(
                SQL["update_current_result"],
                (encoded, game.id),
            )
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def available_options(self, game_id: int, kind: PickKind) -> list[str]:
        cursor = await self.connection.execute(
            SQL["get_available_options"],
            (game_id, kind.value),
        )
        return [str(row["option_key"]) for row in await cursor.fetchall()]

    async def pick(
        self,
        game: Game,
        player_id: int,
        kind: PickKind,
        option_key: str,
        picked_by: int,
    ) -> Game:
        async with self._lock:
            draft = await self.get_draft(game.id)
            if draft.current_player_id != player_id:
                raise ConflictError("It is no longer that player's turn")
            player = next((item for item in game.players if item.id == player_id), None)
            if player is None:
                raise ValueError("Player is not in this game")
            if player.telegram_user_id is not None and player.telegram_user_id != picked_by:
                raise ValueError("Only that player can make this pick")
            current_value = {
                PickKind.FACTION: player.faction,
                PickKind.SLICE: player.slice_id,
                PickKind.SEAT: player.seat,
            }[kind]
            if current_value is not None:
                raise ValueError(f"Player already has a {kind.value}")
            option_cursor = await self.connection.execute(
                SQL["consume_option"],
                (game.id, kind.value, option_key),
            )
            if option_cursor.rowcount != 1:
                raise ConflictError("That option is no longer available")
            value: str | int = option_key if kind is PickKind.FACTION else int(option_key)
            update_query = {
                PickKind.FACTION: SQL["set_player_faction"],
                PickKind.SLICE: SQL["set_player_slice"],
                PickKind.SEAT: SQL["set_player_seat"],
            }[kind]
            await self.connection.execute(
                update_query, (value, player_id)
            )
            await self.connection.execute(
                SQL["add_draft_pick"],
                (game.id, player_id, kind.value, option_key, picked_by),
            )
            draft.advance()
            status = GameStatus.COMPLETE if draft.complete else GameStatus.DRAFTING
            cursor = await self.connection.execute(
                SQL["advance_draft"],
                (draft.pick_index, status.value, game.id, game.revision),
            )
            if cursor.rowcount != 1:
                await self.connection.rollback()
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def cancel(self, game: Game) -> None:
        async with self._lock:
            cursor = await self.connection.execute(
                SQL["cancel_game"],
                (game.id, game.revision),
            )
            if cursor.rowcount != 1:
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.commit()

    async def _bump(self, game_id: int) -> None:
        await self.connection.execute(
            SQL["bump_game"],
            (game_id,),
        )


def _setup_from_json(value: str | None) -> GeneratedSetup | None:
    return GeneratedSetup.from_dict(json.loads(value)) if value else None


def _player_from_row(row: aiosqlite.Row) -> Player:
    return Player(
        id=int(row["id"]),
        display_name=str(row["display_name"]),
        telegram_user_id=row["telegram_user_id"],
        telegram_username=row["telegram_username"],
        faction=row["faction"],
        slice_id=row["slice_id"],
        seat=row["seat"],
    )
