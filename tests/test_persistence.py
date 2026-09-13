from __future__ import annotations

from pathlib import Path

import pytest

from tibot.application import GameService
from tibot.domain import ContentCatalog, SetupGenerator
from tibot.domain.models import BoardRole, GameMode, GameStatus, PickKind
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
    resumed = await repository.get_active(-100)
    assert resumed is not None and resumed.id == game_id
    game = await service.join(resumed, 22, "Future Player", "future_player")
    assert len(game.players) == 2
    claimed = next(player for player in game.players if player.telegram_user_id == 22)
    assert claimed.display_name == "@future_player"
    await repository.close()


@pytest.mark.asyncio
async def test_joined_player_can_remove_exact_roster_name(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "remove-player.db")
    game = await service.begin(-150, 11, "Creator", "creator", GameMode.MILTY)
    game = await service.add_placeholder(game, "Offline Player")
    game = await service.add_placeholder(game, "Third")
    game = await service.remove_player(game, "offline player", 11)
    assert [player.display_name for player in game.players] == ["Creator", "Third"]

    game = await service.add_placeholder(game, "Replacement")
    game = await service.generate(game, seed=10)
    with pytest.raises(ValueError, match="No roster player"):
        await service.remove_player(game, "Third", 11)
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
    assert game.setup.board is not None
    assert sum(
        tile.role is BoardRole.HOME_SYSTEM for tile in game.setup.board.tiles
    ) == 3
    speaker = next(player for player in game.players if player.seat == 1)
    assert game.setup.speaker_player_id == speaker.id
    assert game.setup.speaker_seed is None
    assert await service.render_result(game)
    await repository.close()


@pytest.mark.asyncio
async def test_whole_board_reroll_retains_previous_result(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "whole.db")
    game = await service.begin(-300, 1, "One", "one", GameMode.WHOLE_BOARD)
    game = await service.add_placeholder(game, "Two")
    game = await service.add_placeholder(game, "Three")
    game = await service.generate(game, seed=100)
    assert game.status is GameStatus.DRAFTING
    assert game.setup is not None and game.setup.seed == 100
    assert game.setup.speaker_player_id is None

    while game.status is GameStatus.DRAFTING:
        draft = await repository.get_draft(game.id)
        player = next(item for item in game.players if item.id == draft.current_player_id)
        kind = next(
            candidate
            for candidate, current in (
                (PickKind.FACTION, player.faction),
                (PickKind.SEAT, player.seat),
            )
            if current is None
        )
        option = (await repository.available_options(game.id, kind))[0]
        game = await service.pick(game, kind, option, player.telegram_user_id or 1)

    assert game.status is GameStatus.COMPLETE
    assert game.setup is not None
    assert game.setup.speaker_player_id in {player.id for player in game.players}
    assert game.setup.speaker_seed is not None
    assert game.setup.board is not None
    assert sum(
        tile.role is BoardRole.HOME_SYSTEM for tile in game.setup.board.tiles
    ) == 3

    rerolled = await service.reroll(game)
    assert rerolled.setup is not None and rerolled.setup.seed != 100
    assert rerolled.previous_setup is not None and rerolled.previous_setup.seed == 100
    assert rerolled.status is GameStatus.DRAFTING
    assert rerolled.setup.speaker_player_id is None
    assert all(
        player.faction is None and player.slice_id is None and player.seat is None
        for player in rerolled.players
    )
    await repository.close()


@pytest.mark.asyncio
async def test_migration_archives_incompatible_active_drafts(tmp_path: Path) -> None:
    path = tmp_path / "migration.db"
    repository, service = await _service(path)
    game = await service.begin(-400, 1, "One", "one", GameMode.WHOLE_BOARD)
    game = await service.add_placeholder(game, "Two")
    game = await service.add_placeholder(game, "Three")
    game = await service.generate(game, seed=200)
    assert game.status is GameStatus.DRAFTING
    sql_root = Path(__file__).parent / "sql"
    await repository.connection.execute(
        (sql_root / "downgrade_to_v1.sql").read_text(encoding="utf-8")
    )
    await repository.connection.commit()
    await repository.close()

    repository, _ = await _service(path)
    migrated = await repository.get_game(game.id)
    assert migrated is not None
    assert migrated.status is GameStatus.ARCHIVED
    cursor = await repository.connection.execute(
        (sql_root / "schema_version_count.sql").read_text(encoding="utf-8")
    )
    version_row = await cursor.fetchone()
    assert version_row is not None and version_row[0] == 1
    await repository.close()


@pytest.mark.asyncio
async def test_whole_board_can_complete_without_a_draft(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "board-only.db")
    game = await service.begin(-500, 1, "One", "one", GameMode.WHOLE_BOARD)
    game = await service.add_placeholder(game, "Two")
    game = await service.add_placeholder(game, "Three")
    game = await service.generate_board_only(game, seed=300)
    assert game.status is GameStatus.COMPLETE
    assert game.setup is not None and game.setup.board_only
    assert game.setup.seed == 300
    assert game.setup.order == []
    assert game.setup.factions == []
    assert game.setup.speaker_player_id is None
    assert await service.render_result(game)
    rerolled = await service.reroll(game)
    assert rerolled.status is GameStatus.COMPLETE
    assert rerolled.setup is not None and rerolled.setup.board_only
    assert rerolled.previous_setup is not None and rerolled.previous_setup.seed == 300
    await repository.close()


@pytest.mark.asyncio
async def test_new_setup_rejects_superseded_generation(tmp_path: Path) -> None:
    repository, service = await _service(tmp_path / "replacement.db")
    old = await service.begin(-600, 1, "One", "one", GameMode.MILTY)
    old = await service.add_placeholder(old, "Two")
    old = await service.add_placeholder(old, "Three")

    replacement = await service.begin(-600, 1, "One", "one", GameMode.WHOLE_BOARD)
    assert replacement.status is GameStatus.ROSTER
    archived = await repository.get_game(old.id)
    assert archived is not None and archived.status is GameStatus.ARCHIVED
    with pytest.raises(ConflictError, match="changed"):
        await service.generate(old, seed=400)

    active = await repository.get_active(-600)
    assert active is not None and active.id == replacement.id
    await repository.close()
