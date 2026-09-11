from __future__ import annotations

from pathlib import Path

import pytest

from tibot.application import GameService
from tibot.domain import ContentCatalog, SetupGenerator
from tibot.domain.models import GameMode, GameStatus, PickKind
from tibot.domain.rendering import BoardRenderer
from tibot.infrastructure.database import ConflictError, GameRepository


async def _service(path: Path) -> tuple[GameRepository, GameService]:
    catalog = ContentCatalog.load()
    repository = GameRepository(path)
    await repository.open()
    return repository, GameService(
        repository,
        SetupGenerator(catalog),
        BoardRenderer(catalog.tile_image_dir),
    )


@pytest.mark.asyncio
async def test_roster_survives_restart_and_handle_placeholder_is_claimed(tmp_path: Path) -> None:
    path = tmp_path / "game.db"
    repository, service = await _service(path)
    game = await service.begin(-100, 11, "Creator", "creator", GameMode.MILTY)
    game = await service.add_placeholder(game, "@future_player")
    game_id = game.id
    await repository.close()

    repository, service = await _service(path)
    game = await repository.get_active(-100)
    assert game is not None and game.id == game_id
    game = await service.join(game, 22, "Future Player", "future_player")
    assert len(game.players) == 2
    claimed = next(player for player in game.players if player.telegram_user_id == 22)
    assert claimed.display_name == "@future_player"
    await repository.close()


@pytest.mark.asyncio
async def test_complete_milty_draft_and_reject_stale_revision(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "draft.db")
    game = await service.begin(-200, 101, "One", "one", GameMode.MILTY)
    game = await service.add_placeholder(game, "Two")
    game = await service.add_placeholder(game, "Three")
    stale = game
    game = await service.generate(game, seed=55)
    assert game.status is GameStatus.DRAFTING

    with pytest.raises(ConflictError, match="changed"):
        await service.generate(stale, seed=56)

    while game.status is GameStatus.DRAFTING:
        draft = await repository.get_draft(game.id)
        player = next(item for item in game.players if item.id == draft.current_player_id)
        kind = next(
            candidate
            for candidate, current in (
                (PickKind.FACTION, player.faction),
                (PickKind.SLICE, player.slice_id),
                (PickKind.SEAT, player.seat),
            )
            if current is None
        )
        option = (await repository.available_options(game.id, kind))[0]
        actor = player.telegram_user_id or 101
        game = await service.pick(game, kind, option, actor)

    assert game.status is GameStatus.COMPLETE
    assert all(player.faction and player.slice_id and player.seat for player in game.players)
    assert len({player.faction for player in game.players}) == 3
    assert len({player.slice_id for player in game.players}) == 3
    assert len({player.seat for player in game.players}) == 3
    assert game.setup is not None
    assert len(game.setup.board) == 19
    assert await service.render_result(game)
    await repository.close()


@pytest.mark.asyncio
async def test_whole_board_reroll_retains_previous_result(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "whole.db")
    game = await service.begin(-300, 1, "One", "one", GameMode.WHOLE_BOARD)
    game = await service.add_placeholder(game, "Two")
    game = await service.add_placeholder(game, "Three")
    game = await service.generate(game, seed=100)
    assert game.status is GameStatus.COMPLETE
    assert game.setup is not None and game.setup.seed == 100

    rerolled = await service.reroll(game)
    assert rerolled.setup is not None and rerolled.setup.seed != 100
    assert rerolled.previous_setup is not None and rerolled.previous_setup.seed == 100
    await repository.close()
