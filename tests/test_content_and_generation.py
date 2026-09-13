from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from tibot.domain import ContentCatalog, ContentError, SetupGenerator
from tibot.domain.layouts import layout_for
from tibot.domain.models import BoardGeometry, BoardPosition, BoardRole, Player
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
    expected_size = 8 if player_count in (3, 4) else 5
    assert all(len(item.tiles) == expected_size for item in first.slices)
    assert sorted(first.order) == players


@pytest.mark.parametrize(
    ("player_count", "geometry", "systems", "homes", "gaps", "hyperlanes"),
    (
        (3, BoardGeometry.TRIANGLE_3, 24, 3, 9, 0),
        (4, BoardGeometry.RECTANGLE_4, 32, 4, 0, 0),
        (5, BoardGeometry.HYPERLANE_5, 25, 5, 0, 6),
        (6, BoardGeometry.HEXAGON_6, 30, 6, 0, 0),
    ),
)
def test_player_specific_geometry(
    player_count: int,
    geometry: BoardGeometry,
    systems: int,
    homes: int,
    gaps: int,
    hyperlanes: int,
) -> None:
    spec = layout_for(player_count)
    assert spec.geometry is geometry
    assert len(spec.systems) == systems
    assert len(spec.homes) == homes
    assert len(spec.gaps) == gaps
    assert len(spec.hyperlanes) == hyperlanes
    assert len(set(spec.systems)) == systems


def test_three_player_geometry_is_the_original_sparse_triangle() -> None:
    spec = layout_for(3)
    assert spec.homes == tuple(BoardPosition(3, angle) for angle in (3, 9, 15))
    assert set(spec.gaps) == {
        BoardPosition(3, angle) for angle in (17, 0, 1, 5, 6, 7, 11, 12, 13)
    }
    assert all(len(region) == 8 for region in spec.regions)


def test_five_player_hyperlanes_match_the_original_layout() -> None:
    assert layout_for(5).hyperlanes == tuple(
        (BoardPosition(*position), tile_id, 0)
        for position, tile_id in zip(
            ((1, 3), (2, 5), (3, 8), (3, 9), (3, 10), (2, 7)),
            ("85A", "88A", "83A", "86A", "84A", "87A"),
            strict=True,
        )
    )


@pytest.mark.parametrize(
    ("player_count", "blue", "red", "anomalies"),
    ((3, 14, 10, 6), (4, 20, 12, 9), (5, 15, 10, 5), (6, 18, 12, 6)),
)
def test_whole_board_is_seeded_and_has_expected_composition(
    catalog: ContentCatalog,
    player_count: int,
    blue: int,
    red: int,
    anomalies: int,
) -> None:
    generator = SetupGenerator(catalog)
    players = list(range(1, player_count + 1))
    first = generator.whole_board(players, seed=9876)
    second = generator.whole_board(players, seed=9876)
    assert first.to_dict() == second.to_dict()
    assert first.board is not None
    systems = [
        tile
        for tile in first.board.tiles
        if tile.role is BoardRole.SYSTEM and tile.position.radius > 0
    ]
    assert len(systems) == blue + red
    assert len({tile.tile_id for tile in systems}) == len(systems)
    tiles = [catalog.tiles[str(item.tile_id)] for item in systems]
    assert sum(tile.color == "blue" for tile in tiles) == blue
    assert sum(tile.color == "red" for tile in tiles) == red
    assert sum(tile.anomaly is not None for tile in tiles) == anomalies
    assert sum(tile.wormhole == "alpha" for tile in tiles) == 2
    assert sum(tile.wormhole == "beta" for tile in tiles) == 2
    assert sorted(first.order) == players


def test_player_count_validation(catalog: ContentCatalog) -> None:
    generator = SetupGenerator(catalog)
    with pytest.raises(ValueError, match="3 to 6"):
        generator.milty([1, 2], seed=1)
    with pytest.raises(ValueError, match="unique"):
        generator.whole_board([1, 2, 2], seed=1)


def test_custom_slice_and_faction_pool_sizes(catalog: ContentCatalog) -> None:
    setup = SetupGenerator(catalog).milty(
        [1, 2, 3], seed=7, faction_count=7, slice_count=5
    )
    assert len(setup.factions) == 7
    assert len(setup.slices) == 5


def test_slice_board_preview_appears_after_a_slice_gets_a_seat(
    catalog: ContentCatalog,
) -> None:
    generator = SetupGenerator(catalog)
    setup = generator.milty([1, 2, 3], seed=8)
    players = [Player(1, "One"), Player(2, "Two"), Player(3, "Three")]
    assert generator.preview_board(setup, players) is None
    players[0].slice_id = setup.slices[0].id
    players[0].seat = 2
    preview = generator.preview_board(setup, players)
    assert preview is not None
    assert sum(tile.role is BoardRole.SYSTEM for tile in preview.tiles) == 9


def test_missing_submodule_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="submodule update --init --recursive"):
        ContentCatalog.load(tmp_path / "missing")


@pytest.mark.parametrize("player_count", range(3, 7))
def test_renderer_produces_tightly_cropped_native_png(
    catalog: ContentCatalog, player_count: int
) -> None:
    setup = SetupGenerator(catalog).whole_board(
        list(range(1, player_count + 1)), seed=42
    )
    assert setup.board is not None
    data = BoardRenderer(catalog.tile_image_dir).render_board(setup.board)
    image = Image.open(io.BytesIO(data))
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.mode == "RGBA"
    assert 1_800 <= image.width <= 2_100
    assert 1_850 <= image.height <= 2_300
    assert len(data) > 100_000
