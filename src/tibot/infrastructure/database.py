"""SQLite repository for durable setup workflows."""

from __future__ import annotations

import asyncio
import json
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    seed INTEGER,
    setup_json TEXT,
    previous_setup_json TEXT,
    draft_order_json TEXT,
    draft_pick_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_game_per_chat
ON games(chat_id) WHERE status IN ('roster', 'drafting');
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    telegram_user_id INTEGER,
    telegram_username TEXT,
    faction TEXT,
    slice_id INTEGER,
    seat INTEGER,
    UNIQUE(game_id, display_name COLLATE NOCASE),
    UNIQUE(game_id, telegram_user_id)
);
CREATE TABLE IF NOT EXISTS generated_options (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    option_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(game_id, kind, option_key)
);
CREATE TABLE IF NOT EXISTS draft_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    kind TEXT NOT NULL,
    option_key TEXT NOT NULL,
    picked_by INTEGER NOT NULL,
    picked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, player_id, kind),
    UNIQUE(game_id, kind, option_key)
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    seed INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


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
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.executescript(SCHEMA)
        await self._connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (1)")
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
                "UPDATE games SET status='archived', revision=revision+1 "
                "WHERE chat_id=? AND status IN ('roster','drafting')",
                (chat_id,),
            )
            cursor = await self.connection.execute(
                "INSERT INTO games(chat_id, mode, status, created_by) VALUES (?, ?, ?, ?)",
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
            "SELECT id FROM games WHERE chat_id=? AND status IN ('roster','drafting') "
            "ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return await self.get_game(int(row["id"])) if row else None

    async def get_latest(self, chat_id: int) -> Game | None:
        cursor = await self.connection.execute(
            "SELECT id FROM games WHERE chat_id=? ORDER BY id DESC LIMIT 1", (chat_id,)
        )
        row = await cursor.fetchone()
        return await self.get_game(int(row["id"])) if row else None

    async def get_game(self, game_id: int) -> Game | None:
        cursor = await self.connection.execute("SELECT * FROM games WHERE id=?", (game_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        players_cursor = await self.connection.execute(
            "SELECT * FROM players WHERE game_id=? ORDER BY id", (game_id,)
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
                "SELECT status FROM games WHERE id=?", (game_id,)
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != GameStatus.ROSTER.value:
                raise ValueError("Players can only be added while building the roster")
            count_cursor = await self.connection.execute(
                "SELECT COUNT(*) AS count FROM players WHERE game_id=?", (game_id,)
            )
            count_row = await count_cursor.fetchone()
            assert count_row is not None
            if int(count_row["count"]) >= 6:
                raise ValueError("A game can have at most 6 players")
            try:
                inserted = await self.connection.execute(
                    "INSERT INTO players(game_id, display_name, telegram_user_id, "
                    "telegram_username) "
                    "VALUES (?, ?, ?, ?)",
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
                "DELETE FROM players WHERE game_id=? AND telegram_user_id=? "
                "AND EXISTS(SELECT 1 FROM games WHERE id=? AND status='roster')",
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
                    "UPDATE players SET telegram_user_id=?, telegram_username=? "
                    "WHERE game_id=? AND display_name=? COLLATE NOCASE "
                    "AND telegram_user_id IS NULL",
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
                "UPDATE games SET previous_setup_json=setup_json, setup_json=?, seed=?, status=?, "
                "draft_order_json=?, draft_pick_index=?, revision=revision+1, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?",
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
                "UPDATE results SET is_current=0 WHERE game_id=?", (game.id,)
            )
            await self.connection.execute(
                "INSERT INTO results(game_id, seed, payload_json) VALUES (?, ?, ?)",
                (game.id, setup.seed, encoded),
            )
            await self.connection.execute(
                "DELETE FROM generated_options WHERE game_id=?", (game.id,)
            )
            if status is GameStatus.DRAFTING:
                for faction in setup.factions:
                    await self.connection.execute(
                        "INSERT INTO generated_options VALUES (?, 'faction', ?, ?, 1)",
                        (game.id, faction.name, json.dumps({"home_system": faction.home_system})),
                    )
                for item in setup.slices:
                    await self.connection.execute(
                        "INSERT INTO generated_options VALUES (?, 'slice', ?, ?, 1)",
                        (game.id, str(item.id), json.dumps({"tiles": item.tiles})),
                    )
                for seat in range(1, len(game.players) + 1):
                    await self.connection.execute(
                        "INSERT INTO generated_options VALUES (?, 'seat', ?, '{}', 1)",
                        (game.id, str(seat)),
                    )
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def get_draft(self, game_id: int) -> DraftState:
        cursor = await self.connection.execute(
            "SELECT draft_order_json, draft_pick_index FROM games WHERE id=?", (game_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["draft_order_json"] is None:
            raise ValueError("Game does not have an active draft")
        return DraftState(tuple(json.loads(row["draft_order_json"])), int(row["draft_pick_index"]))

    async def finalize_setup(self, game: Game) -> Game:
        if game.setup is None:
            raise ValueError("Game has no generated setup")
        encoded = json.dumps(game.setup.to_dict(), separators=(",", ":"))
        async with self._lock:
            cursor = await self.connection.execute(
                "UPDATE games SET setup_json=?, revision=revision+1, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND revision=?",
                (encoded, game.id, game.revision),
            )
            if cursor.rowcount != 1:
                await self.connection.rollback()
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.execute(
                "UPDATE results SET payload_json=? WHERE game_id=? AND is_current=1",
                (encoded, game.id),
            )
            await self.connection.commit()
        updated = await self.get_game(game.id)
        assert updated is not None
        return updated

    async def available_options(self, game_id: int, kind: PickKind) -> list[str]:
        cursor = await self.connection.execute(
            "SELECT option_key FROM generated_options WHERE game_id=? AND kind=? AND available=1 "
            "ORDER BY option_key COLLATE NOCASE",
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
            field = {
                PickKind.FACTION: "faction",
                PickKind.SLICE: "slice_id",
                PickKind.SEAT: "seat",
            }[kind]
            if getattr(player, field) is not None:
                raise ValueError(f"Player already has a {kind.value}")
            option_cursor = await self.connection.execute(
                "UPDATE generated_options SET available=0 WHERE game_id=? AND kind=? "
                "AND option_key=? AND available=1",
                (game.id, kind.value, option_key),
            )
            if option_cursor.rowcount != 1:
                raise ConflictError("That option is no longer available")
            value: str | int = option_key if kind is PickKind.FACTION else int(option_key)
            await self.connection.execute(
                f"UPDATE players SET {field}=? WHERE id=?", (value, player_id)
            )
            await self.connection.execute(
                "INSERT INTO draft_picks(game_id, player_id, kind, option_key, picked_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (game.id, player_id, kind.value, option_key, picked_by),
            )
            draft.advance()
            status = GameStatus.COMPLETE if draft.complete else GameStatus.DRAFTING
            cursor = await self.connection.execute(
                "UPDATE games SET draft_pick_index=?, status=?, revision=revision+1, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?",
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
                "UPDATE games SET status='cancelled', revision=revision+1 "
                "WHERE id=? AND revision=?",
                (game.id, game.revision),
            )
            if cursor.rowcount != 1:
                raise ConflictError("This setup changed; refresh and try again")
            await self.connection.commit()

    async def _bump(self, game_id: int) -> None:
        await self.connection.execute(
            "UPDATE games SET revision=revision+1, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
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
