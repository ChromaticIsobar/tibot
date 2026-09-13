"""Authoritative radial board layouts for each supported player count."""

from __future__ import annotations

import math
from dataclasses import dataclass

from tibot.domain.models import BoardGeometry, BoardPosition


@dataclass(frozen=True, slots=True)
class LayoutSpec:
    geometry: BoardGeometry
    homes: tuple[BoardPosition, ...]
    systems: tuple[BoardPosition, ...]
    gaps: tuple[BoardPosition, ...] = ()
    hyperlanes: tuple[tuple[BoardPosition, str, int], ...] = ()
    regions: tuple[tuple[BoardPosition, ...], ...] = ()


def layout_for(player_count: int) -> LayoutSpec:
    try:
        return _LAYOUTS[player_count]
    except KeyError as exc:
        raise ValueError("A board requires 3 to 6 players") from exc


def slice_layout_for(player_count: int) -> LayoutSpec:
    try:
        return _SLICE_LAYOUTS[player_count]
    except KeyError as exc:
        raise ValueError("A board requires 3 to 6 players") from exc


def slice_preview_positions(player_count: int) -> tuple[BoardPosition, ...]:
    try:
        return _SLICE_PREVIEWS[player_count]
    except KeyError as exc:
        raise ValueError("A slice requires 3 to 6 players") from exc


def offset_position(center: BoardPosition, offset: tuple[int, int]) -> BoardPosition:
    radius = center.radius + offset[0]
    angle = ((center.angle * radius) // center.radius + offset[1]) % (radius * 6)
    return BoardPosition(radius, angle)


def axial(position: BoardPosition) -> tuple[int, int]:
    directions = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0))
    q = r = 0
    for direction in path_from_center(position.radius, position.angle):
        dq, dr = directions[direction]
        q += dq
        r += dr
    return q, r


def adjacent(left: BoardPosition, right: BoardPosition) -> bool:
    lq, lr = axial(left)
    rq, rr = axial(right)
    dq, dr = lq - rq, lr - rr
    return max(abs(dq), abs(dr), abs(dq + dr)) == 1


def path_from_center(radius: int, angle: int) -> list[int]:
    if radius < 1:
        return []
    path = path_from_center(radius - 1, math.floor(angle * (radius - 1) / radius))
    path.append(math.ceil(angle / radius) % 6)
    return path


def _all_positions() -> tuple[BoardPosition, ...]:
    return tuple(
        BoardPosition(radius, angle)
        for radius in range(1, 4)
        for angle in range(radius * 6)
    )


def _nearest_regions(
    homes: tuple[BoardPosition, ...], systems: tuple[BoardPosition, ...]
) -> tuple[tuple[BoardPosition, ...], ...]:
    home_axial = [axial(home) for home in homes]
    buckets: list[list[BoardPosition]] = [[] for _ in homes]

    def distances(position: BoardPosition) -> list[int]:
        q, r = axial(position)
        return [
            max(abs(q - hq), abs(r - hr), abs(q + r - hq - hr))
            for hq, hr in home_axial
        ]

    capacity = len(systems) // len(homes)
    ordered = sorted(
        systems,
        key=lambda position: sorted(distances(position))[1] - min(distances(position)),
        reverse=True,
    )
    for position in ordered:
        values = distances(position)
        available = [index for index, bucket in enumerate(buckets) if len(bucket) < capacity]
        selected = min(available, key=lambda index: (values[index], index))
        buckets[selected].append(position)
    return tuple(tuple(bucket) for bucket in buckets)


_ALL = _all_positions()

_HOMES_3 = tuple(BoardPosition(3, angle) for angle in (3, 9, 15))
_GAPS_3 = tuple(
    BoardPosition(3, (sector * 6 + offset) % 18)
    for sector in range(3)
    for offset in (-1, 0, 1)
)
_SYSTEMS_3 = tuple(
    position
    for position in _ALL
    if position not in _HOMES_3 and position not in _GAPS_3
)

_HOMES_4 = tuple(BoardPosition(3, angle) for angle in (4, 8, 13, 17))
_SYSTEMS_4 = tuple(position for position in _ALL if position not in _HOMES_4)

_HOMES_5 = tuple(BoardPosition(3, angle) for angle in (12, 15, 0, 3, 6))
_HYPERLANES_5 = tuple(
    (BoardPosition(*position), tile_id, 0)
    for position, tile_id in zip(
        ((1, 3), (2, 5), (3, 8), (3, 9), (3, 10), (2, 7)),
        ("85A", "88A", "83A", "86A", "84A", "87A"),
        strict=True,
    )
)
_OFFSETS_5 = (
    ((0, 1), (-1, 0), (0, -1), (-2, 0), (-1, 1)),
    ((0, 1), (-1, 0), (0, -1), (-2, 0), (-1, 1)),
    ((0, 1), (-1, 0), (0, -1), (-2, 0), (-1, 1)),
    ((0, 1), (-1, 0), (0, -1), (-2, 0), (-1, 1)),
    ((0, 1), (-1, 0), (0, -1), (-2, 0), (-1, 2)),
)
_REGIONS_5 = tuple(
    tuple(offset_position(home, offset) for offset in offsets)
    for home, offsets in zip(_HOMES_5, _OFFSETS_5, strict=True)
)
_SYSTEMS_5 = tuple(position for region in _REGIONS_5 for position in region)

_HOMES_6 = tuple(BoardPosition(3, angle) for angle in range(0, 18, 3))
_SYSTEMS_6 = tuple(position for position in _ALL if position not in _HOMES_6)

_LAYOUTS = {
    3: LayoutSpec(
        BoardGeometry.TRIANGLE_3,
        _HOMES_3,
        _SYSTEMS_3,
        _GAPS_3,
        regions=_nearest_regions(_HOMES_3, _SYSTEMS_3),
    ),
    4: LayoutSpec(
        BoardGeometry.RECTANGLE_4,
        _HOMES_4,
        _SYSTEMS_4,
        regions=_nearest_regions(_HOMES_4, _SYSTEMS_4),
    ),
    5: LayoutSpec(
        BoardGeometry.HYPERLANE_5,
        _HOMES_5,
        _SYSTEMS_5,
        hyperlanes=_HYPERLANES_5,
        regions=_REGIONS_5,
    ),
    6: LayoutSpec(
        BoardGeometry.HEXAGON_6,
        _HOMES_6,
        _SYSTEMS_6,
        regions=_nearest_regions(_HOMES_6, _SYSTEMS_6),
    ),
}

_SLICE_HOMES_4 = tuple(BoardPosition(3, angle) for angle in (11, 16, 2, 7))
_OFFSETS_3 = (
    (0, 1),
    (-1, 1),
    (-2, 0),
    (-1, -1),
    (0, -1),
    (-1, 0),
    (-2, -1),
    (-1, 2),
)
_OFFSETS_4_EVEN = (
    (0, 1),
    (-1, 1),
    (-1, 0),
    (0, -1),
    (-1, 2),
    (-2, 1),
    (-2, 0),
    (0, -2),
)
_OFFSETS_4_ODD = (
    (0, 1),
    (-1, 1),
    (-1, 0),
    (0, -1),
    (0, 2),
    (-1, 2),
    (-2, 1),
    (0, -2),
)
_OFFSETS_6 = ((0, 1), (-1, 1), (-2, 0), (-1, 0), (0, -1))


def _regions_from_offsets(
    homes: tuple[BoardPosition, ...],
    offsets: tuple[tuple[tuple[int, int], ...], ...],
) -> tuple[tuple[BoardPosition, ...], ...]:
    return tuple(
        tuple(offset_position(home, offset) for offset in shape)
        for home, shape in zip(homes, offsets, strict=True)
    )


_SLICE_REGIONS_3 = _regions_from_offsets(_HOMES_3, (_OFFSETS_3,) * 3)
_SLICE_REGIONS_4 = _regions_from_offsets(
    _SLICE_HOMES_4,
    (_OFFSETS_4_ODD, _OFFSETS_4_EVEN, _OFFSETS_4_ODD, _OFFSETS_4_EVEN),
)
_SLICE_REGIONS_6 = _regions_from_offsets(_HOMES_6, (_OFFSETS_6,) * 6)

_SLICE_LAYOUTS = {
    3: LayoutSpec(
        BoardGeometry.TRIANGLE_3,
        _HOMES_3,
        tuple(position for region in _SLICE_REGIONS_3 for position in region),
        _GAPS_3,
        regions=_SLICE_REGIONS_3,
    ),
    4: LayoutSpec(
        BoardGeometry.RECTANGLE_4,
        _SLICE_HOMES_4,
        tuple(position for region in _SLICE_REGIONS_4 for position in region),
        regions=_SLICE_REGIONS_4,
    ),
    5: _LAYOUTS[5],
    6: LayoutSpec(
        BoardGeometry.HEXAGON_6,
        _HOMES_6,
        tuple(position for region in _SLICE_REGIONS_6 for position in region),
        regions=_SLICE_REGIONS_6,
    ),
}

_SLICE_PREVIEWS = {
    3: tuple(
        BoardPosition(*position)
        for position in ((1, 3), (1, 4), (1, 5), (1, 0), (1, 1), (1, 2), (0, 0), (2, 1), (2, 10))
    ),
    4: tuple(
        BoardPosition(*position)
        for position in ((0, 0), (1, 4), (1, 5), (1, 0), (1, 1), (2, 9), (2, 10), (2, 11), (2, 1))
    ),
    5: tuple(
        BoardPosition(*position)
        for position in ((1, 3), (1, 4), (0, 0), (1, 2), (1, 0), (1, 5))
    ),
    6: tuple(
        BoardPosition(*position)
        for position in ((1, 3), (1, 4), (1, 5), (1, 0), (0, 0), (1, 2))
    ),
}
