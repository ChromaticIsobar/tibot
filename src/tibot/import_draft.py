"""Import an externally generated whole-board draft into a roster game."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tibot.domain.content import ContentCatalog
from tibot.domain.layouts import layout_for
from tibot.domain.models import (
    BoardLayout,
    BoardPosition,
    BoardRole,
    BoardTile,
    DraftState,
    Faction,
    Game,
    GameMode,
    GameStatus,
    GeneratedSetup,
    PickKind,
    Player,
)
from tibot.infrastructure.database import GameRepository
from tibot.telegram.formatting import LEGACY_FACTION_NAMES


@dataclass(frozen=True, slots=True)
class ImportedPick:
    player: Player
    kind: PickKind
    value: str


def _player_id(player: Player) -> int:
    if player.id is None:
        raise ValueError(f"Player is not persisted: {player.display_name}")
    return player.id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="JSON exported by random5wholeboard.py")
    parser.add_argument("--database", type=Path, required=True, help="TIBot SQLite database")
    parser.add_argument(
        "--game-id",
        type=int,
        help="Roster-phase game ID; inferred when exactly one roster game exists",
    )
    parser.add_argument(
        "--order",
        nargs=5,
        metavar=("P1", "P2", "P3", "P4", "P5"),
        help="Override the exported draft order with five player references",
    )
    parser.add_argument(
        "--pick",
        action="append",
        default=[],
        metavar="PLAYER|KIND|VALUE",
        help="Existing pick in chronological order; repeat for every pick",
    )
    return parser


def _player(game: Game, reference: str) -> Player:
    wanted = reference.strip().removeprefix("@").casefold()
    matches = [
        player
        for player in game.players
        if wanted
        in {
            player.display_name.strip().removeprefix("@").casefold(),
            (player.telegram_username or "").strip().removeprefix("@").casefold(),
        }
    ]
    if len(matches) != 1:
        raise ValueError(f"Player reference must match exactly one roster entry: {reference}")
    return matches[0]


def _faction(reference: str, catalog: ContentCatalog) -> Faction:
    wanted = LEGACY_FACTION_NAMES.get(reference.strip(), reference.strip()).casefold()
    matches = [
        faction
        for faction in catalog.factions
        if faction.name.casefold() == wanted
        or faction.name.removeprefix("The ").casefold() == wanted
        or faction.name.casefold().endswith(f" {wanted}")
    ]
    if len(matches) != 1:
        raise ValueError(f"Faction must match exactly one catalog entry: {reference}")
    return matches[0]


def _board(data: dict[str, Any], catalog: ContentCatalog) -> BoardLayout:
    if data.get("format") != "twilightimperiumgm.whole-board.v1":
        raise ValueError("Unsupported external board format")
    if int(data.get("player_count", 0)) != 5:
        raise ValueError("This importer requires a five-player board")
    spec = layout_for(5)
    expected = {
        BoardPosition(0, 0),
        *spec.homes,
        *spec.systems,
        *(position for position, _, _ in spec.hyperlanes),
    }
    raw_tiles = data.get("tiles")
    if not isinstance(raw_tiles, list):
        raise ValueError("External board tiles must be a list")
    by_position: dict[BoardPosition, dict[str, Any]] = {}
    for raw in raw_tiles:
        if not isinstance(raw, dict):
            raise ValueError("Every external board tile must be an object")
        position = BoardPosition(int(raw["radius"]), int(raw["angle"]))
        if position in by_position:
            raise ValueError(f"Duplicate board position: {position.key}")
        by_position[position] = raw
    if set(by_position) != expected:
        raise ValueError("External board positions do not match five-player geometry")

    hyperlanes = {position: (tile_id, rotation) for position, tile_id, rotation in spec.hyperlanes}
    tiles: list[BoardTile] = []
    system_ids: list[str] = []
    for position in sorted(expected):
        raw = by_position[position]
        tile_id = str(raw["tile_id"])
        rotation = int(raw.get("rotation", 0))
        if position in spec.homes:
            tiles.append(BoardTile(position, None, BoardRole.HOME_PLACEHOLDER))
        elif position in hyperlanes:
            expected_tile, expected_rotation = hyperlanes[position]
            if (tile_id, rotation) != (expected_tile, expected_rotation):
                raise ValueError(f"Incorrect hyperlane at {position.key}")
            tiles.append(BoardTile(position, tile_id, BoardRole.HYPERLANE, rotation))
        else:
            if tile_id not in catalog.tiles:
                raise ValueError(f"Unknown system tile: {tile_id}")
            tiles.append(BoardTile(position, tile_id))
            if position in spec.systems:
                system_ids.append(tile_id)
    if len(set(system_ids)) != 25:
        raise ValueError("Five-player board must contain 25 unique system tiles")
    colors = [catalog.tiles[tile_id].color for tile_id in system_ids]
    if colors.count("blue") != 15 or colors.count("red") != 10:
        raise ValueError("Five-player board must contain 15 blue and 10 red systems")
    return BoardLayout(spec.geometry, 5, tiles)


def _prepare(
    game: Game,
    data: dict[str, Any],
    raw_picks: list[str],
    catalog: ContentCatalog,
) -> tuple[GeneratedSetup, DraftState, list[ImportedPick]]:
    if game.mode is not GameMode.WHOLE_BOARD or game.status is not GameStatus.ROSTER:
        raise ValueError("Target game must be a whole-board roster")
    if len(game.players) != 5 or any(player.id is None for player in game.players):
        raise ValueError("Target roster must contain exactly five persisted players")
    order = tuple(_player(game, str(name)) for name in data["draft_order"])
    if len(order) != 5 or len({player.id for player in order}) != 5:
        raise ValueError("Draft order must contain every roster player exactly once")
    factions = [_faction(str(name), catalog) for name in data["faction_pool"]]
    if len(factions) < 5 or len({faction.name for faction in factions}) != len(factions):
        raise ValueError("Faction pool must contain at least five unique factions")
    draft = DraftState(
        tuple(_player_id(player) for player in order),
        (PickKind.FACTION, PickKind.SEAT),
    )
    parsed: list[ImportedPick] = []
    owned: dict[int, set[PickKind]] = {_player_id(player): set() for player in game.players}
    available_factions = {faction.name for faction in factions}
    available_seats = {str(seat) for seat in range(1, 6)}
    for raw_pick in raw_picks:
        parts = [part.strip() for part in raw_pick.split("|")]
        if len(parts) != 3:
            raise ValueError(f"Pick must use PLAYER|KIND|VALUE: {raw_pick}")
        player = _player(game, parts[0])
        kind = PickKind(parts[1].casefold())
        if kind not in (PickKind.FACTION, PickKind.SEAT):
            raise ValueError(f"Whole-board drafts cannot import {kind.value} picks")
        if player.id != draft.current_player_id:
            raise ValueError(f"Pick is out of draft order: {raw_pick}")
        if kind in owned[_player_id(player)]:
            raise ValueError(f"Player already owns {kind.value}: {parts[0]}")
        value = _faction(parts[2], catalog).name if kind is PickKind.FACTION else parts[2]
        available = available_factions if kind is PickKind.FACTION else available_seats
        if value not in available:
            raise ValueError(f"Unavailable {kind.value}: {parts[2]}")
        available.remove(value)
        owned[_player_id(player)].add(kind)
        parsed.append(ImportedPick(player, kind, value))
        draft.advance()
    setup = GeneratedSetup(
        seed=int(data["seed"]),
        factions=factions,
        board=_board(data, catalog),
        order=[_player_id(player) for player in order],
        warnings=[str(item) for item in data.get("warnings", [])],
        score=float(data["score"]) if data.get("score") is not None else None,
    )
    draft.pick_index = 0
    return setup, draft, parsed


async def _run(args: argparse.Namespace) -> None:
    data = json.loads(args.export.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("External export must contain a JSON object")
    if args.order:
        data["draft_order"] = args.order
    catalog = ContentCatalog.load()
    repository = GameRepository(args.database)
    await repository.open()
    try:
        game_id = args.game_id
        if game_id is None:
            candidates = await repository.list_roster_games()
            if len(candidates) != 1:
                summary = ", ".join(
                    f"game {candidate} (chat {chat})" for candidate, chat in candidates
                ) or "none"
                raise ValueError(
                    "Could not infer one roster game; pass --game-id. "
                    f"Candidates: {summary}"
                )
            game_id = candidates[0][0]
        game = await repository.get_game(game_id)
        if game is None:
            raise ValueError(f"Game {game_id} does not exist")
        setup, draft, picks = _prepare(game, data, args.pick, catalog)
        game = await repository.save_generation(game, setup, GameStatus.DRAFTING, draft)
        for pick in picks:
            assert pick.player.id is not None
            picked_by = pick.player.telegram_user_id or game.created_by
            game = await repository.pick(game, pick.player.id, pick.kind, pick.value, picked_by)
        current = await repository.get_draft(game.id)
        if current.complete:
            print(f"Imported game {game.id}; draft choices are complete")
        else:
            next_player = next(
                player.display_name
                for player in game.players
                if player.id == current.current_player_id
            )
            print(f"Imported game {game.id}; next pick: {next_player}")
    finally:
        await repository.close()


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
