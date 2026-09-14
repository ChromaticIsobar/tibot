from __future__ import annotations

from pathlib import Path

import pytest

from tibot.domain import ContentCatalog
from tibot.domain.layouts import layout_for
from tibot.domain.models import Game, GameMode, GameStatus, PickKind, Player
from tibot.import_draft import _complete_roster, _prepare
from tibot.infrastructure.database import GameRepository


def _external_board(catalog: ContentCatalog) -> dict[str, object]:
    spec = layout_for(5)
    systems = [
        tile.id
        for color, amount in (("blue", 15), ("red", 10))
        for tile in tuple(
            item
            for item in catalog.tiles.values()
            if item.color == color and item.id not in {"18", "81", "82", "112"}
        )[:amount]
    ]
    tiles: list[dict[str, object]] = [
        {"radius": 0, "angle": 0, "tile_id": "112", "rotation": 0}
    ]
    tiles.extend(
        {
            "radius": position.radius,
            "angle": position.angle,
            "tile_id": f"<Player {index}>",
            "rotation": 0,
        }
        for index, position in enumerate(spec.homes, 1)
    )
    tiles.extend(
        {
            "radius": position.radius,
            "angle": position.angle,
            "tile_id": tile_id,
            "rotation": rotation,
        }
        for position, tile_id, rotation in spec.hyperlanes
    )
    tiles.extend(
        {
            "radius": position.radius,
            "angle": position.angle,
            "tile_id": tile_id,
            "rotation": 0,
        }
        for position, tile_id in zip(spec.systems, systems, strict=True)
    )
    return {
        "format": "twilightimperiumgm.whole-board.v1",
        "player_count": 5,
        "seed": 224156299170888033155132413247621606676,
        "score": 182.64,
        "warnings": [],
        "draft_order": ["@two", "@five", "@three", "@one", "@four"],
        "faction_pool": [faction.name for faction in catalog.factions[:7]],
        "tiles": tiles,
    }


@pytest.mark.asyncio
async def test_import_external_draft_and_resume_next_pick(tmp_path: Path) -> None:
    catalog = ContentCatalog.load()
    repository = GameRepository(tmp_path / "import.db")
    await repository.open()
    game = await repository.create_game(-100, 10, GameMode.WHOLE_BOARD)
    await repository.add_player(game.id, "@one", 10, "one")
    for name in ("@two", "@three", "@four", "@five"):
        await repository.add_player(game.id, name)
    loaded_game = await repository.get_game(game.id)
    assert loaded_game is not None
    data = _external_board(catalog)
    faction_pool = data["faction_pool"]
    assert isinstance(faction_pool, list)
    selected_faction = str(faction_pool[0])
    picks = [
        "@two|seat|2",
        f"@five|faction|{selected_faction}",
        "@three|seat|4",
    ]

    setup, draft, parsed = _prepare(loaded_game, data, picks, catalog)
    game = await repository.save_generation(
        loaded_game, setup, GameStatus.DRAFTING, draft
    )
    for pick in parsed:
        assert pick.player.id is not None
        game = await repository.pick(
            game,
            pick.player.id,
            pick.kind,
            pick.value,
            pick.player.telegram_user_id or game.created_by,
        )

    resumed = await repository.get_game(game.id)
    assert resumed is not None and resumed.setup is not None
    assert resumed.setup.seed == 224156299170888033155132413247621606676
    state = await repository.get_draft(game.id)
    next_player = next(player for player in resumed.players if player.id == state.current_player_id)
    assert next_player.display_name == "@one"
    assert state.pick_index == 3
    assert selected_faction not in await repository.available_options(
        game.id, PickKind.FACTION
    )
    await repository.close()


def test_import_rejects_out_of_order_pick() -> None:
    catalog = ContentCatalog.load()
    game = Game(
        1,
        -1,
        GameMode.WHOLE_BOARD,
        GameStatus.ROSTER,
        1,
        10,
        [
            Player(index, f"@{name}")
            for index, name in enumerate(
                ("one", "two", "three", "four", "five"), 1
            )
        ],
    )
    with pytest.raises(ValueError, match="out of draft order"):
        _prepare(game, _external_board(catalog), ["@one|seat|2"], catalog)


@pytest.mark.asyncio
async def test_import_completes_roster_from_explicit_order(tmp_path: Path) -> None:
    repository = GameRepository(tmp_path / "roster.db")
    await repository.open()
    game = await repository.create_game(-100, 10, GameMode.WHOLE_BOARD)
    await repository.add_player(game.id, "Alice", 10, "alice")
    loaded = await repository.get_game(game.id)
    assert loaded is not None

    completed = await _complete_roster(
        repository, loaded, ["@alice", "@bob", "@carol", "@dave", "@erin"]
    )

    assert len(completed.players) == 5
    assert completed.players[0].telegram_user_id == 10
    assert {player.telegram_username for player in completed.players} == {
        "alice",
        "bob",
        "carol",
        "dave",
        "erin",
    }
    await repository.close()


@pytest.mark.asyncio
async def test_import_refuses_unrelated_roster_player(tmp_path: Path) -> None:
    repository = GameRepository(tmp_path / "unrelated.db")
    await repository.open()
    game = await repository.create_game(-100, 10, GameMode.WHOLE_BOARD)
    await repository.add_player(game.id, "Mallory")
    loaded = await repository.get_game(game.id)
    assert loaded is not None

    with pytest.raises(ValueError, match="absent from --order"):
        await _complete_roster(
            repository, loaded, ["@alice", "@bob", "@carol", "@dave", "@erin"]
        )
    await repository.close()
