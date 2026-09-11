from __future__ import annotations

from pathlib import Path

import pytest

from tibot.domain import ContentCatalog, ContentError, SetupGenerator
from tibot.domain.rendering import BoardRenderer


@pytest.fixture(scope="module")
def catalog() -> ContentCatalog:
    return ContentCatalog.load()


@pytest.mark.parametrize("player_count", range(3, 7))
def test_milty_presets_are_unique_and_reproducible(
    catalog: ContentCatalog, player_count: int
) -> None:
    generator = SetupGenerator(catalog)
    players = list(range(1, player_count + 1))

    first = generator.milty(players, seed=12345)
    second = generator.milty(players, seed=12345)

    assert first.to_dict() == second.to_dict()
    assert len(first.slices) == player_count + 1
    assert len(first.factions) == player_count + 2
    assert len({faction.name for faction in first.factions}) == player_count + 2
    tile_ids = [tile_id for item in first.slices for tile_id in item.tiles]
    assert len(tile_ids) == len(set(tile_ids))
    assert all(len(item.tiles) == 5 for item in first.slices)
    assert sorted(first.order) == players


@pytest.mark.parametrize("player_count", range(3, 7))
def test_whole_board_is_seeded_and_has_expected_composition(
    catalog: ContentCatalog, player_count: int
) -> None:
    generator = SetupGenerator(catalog)
    players = list(range(1, player_count + 1))

    first = generator.whole_board(players, seed=9876)
    second = generator.whole_board(players, seed=9876)

    assert first.to_dict() == second.to_dict()
    assert len(first.board) == 19
    assert len(set(first.board.values())) == 19
    colors = [
        catalog.tiles[tile_id].color
        for position, tile_id in first.board.items()
        if position != "0,0"
    ]
    assert colors.count("blue") == 12
    assert colors.count("red") == 6
    assert sorted(first.order) == players


def test_player_count_validation(catalog: ContentCatalog) -> None:
    generator = SetupGenerator(catalog)
    with pytest.raises(ValueError, match="3 to 6"):
        generator.milty([1, 2], seed=1)
    with pytest.raises(ValueError, match="unique"):
        generator.whole_board([1, 2, 2], seed=1)


def test_missing_submodule_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="submodule update --init --recursive"):
        ContentCatalog.load(tmp_path / "missing")


def test_renderer_produces_a_nonempty_png(catalog: ContentCatalog) -> None:
    setup = SetupGenerator(catalog).whole_board([1, 2, 3], seed=42)
    image = BoardRenderer(catalog.tile_image_dir).render_board(setup.board)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 100_000
