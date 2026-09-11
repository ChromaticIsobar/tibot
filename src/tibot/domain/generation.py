"""Deterministic setup generators."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from random import Random
from statistics import pstdev

from tibot.domain.content import ContentCatalog
from tibot.domain.models import GeneratedSetup, Player, Slice, Tile


class SetupGenerator:
    def __init__(self, catalog: ContentCatalog) -> None:
        self.catalog = catalog

    def milty(self, player_ids: Sequence[int], seed: int | None = None) -> GeneratedSetup:
        self._validate_players(player_ids)
        seed = seed if seed is not None else secrets.randbits(63)
        rng = Random(seed)
        slice_count = len(player_ids) + 1
        factions = rng.sample(list(self.catalog.factions), len(player_ids) + 2)
        slices = self._balanced_slices(rng, slice_count)
        order = list(player_ids)
        rng.shuffle(order)
        return GeneratedSetup(seed=seed, factions=factions, slices=slices, order=order)

    def whole_board(self, player_ids: Sequence[int], seed: int | None = None) -> GeneratedSetup:
        self._validate_players(player_ids)
        seed = seed if seed is not None else secrets.randbits(63)
        rng = Random(seed)
        blue = self._tiles("blue")
        red = self._tiles("red")
        chosen = rng.sample(blue, 12) + rng.sample(red, 6)
        rng.shuffle(chosen)
        positions = _radius_two_positions()
        center_id = "112" if "112" in self.catalog.tiles else "18"
        board = {"0,0": center_id}
        board.update({f"{q},{r}": tile.id for (q, r), tile in zip(positions, chosen, strict=True)})
        order = list(player_ids)
        rng.shuffle(order)
        factions = rng.sample(list(self.catalog.factions), len(player_ids) + 2)
        warnings = self._board_warnings(board)
        values = [tile.value for tile in chosen]
        score = round(sum(values) / len(values) - pstdev(values), 2)
        return GeneratedSetup(
            seed=seed,
            factions=factions,
            board=board,
            order=order,
            warnings=warnings,
            score=score,
        )

    def random_factions(self, count: int, seed: int | None = None) -> GeneratedSetup:
        if not 1 <= count <= len(self.catalog.factions):
            raise ValueError("Faction count is outside the available range")
        seed = seed if seed is not None else secrets.randbits(63)
        return GeneratedSetup(
            seed=seed,
            factions=Random(seed).sample(list(self.catalog.factions), count),
        )

    def assemble_milty(self, setup: GeneratedSetup, players: Sequence[Player]) -> None:
        """Assemble completed draft choices into a deterministic galaxy."""
        if any(
            player.faction is None or player.slice_id is None or player.seat is None
            for player in players
        ):
            raise ValueError("Every player needs a faction, slice, and seat")
        faction_home = {faction.name: faction.home_system for faction in self.catalog.factions}
        slice_by_id = {item.id: item for item in setup.slices}
        ordered = sorted(players, key=lambda player: player.seat or 0)
        home_candidates = ((3, 0), (0, 3), (-3, 3), (-3, 0), (0, -3), (3, -3))
        home_indices = [round(index * 6 / len(ordered)) % 6 for index in range(len(ordered))]
        open_positions = [
            (q, r)
            for q in range(-3, 4)
            for r in range(-3, 4)
            if 1 <= max(abs(q), abs(r), abs(q + r)) <= 3
            and (q, r) not in home_candidates
        ]
        board = {"0,0": "112" if "112" in self.catalog.tiles else "18"}
        for player, home_index in zip(ordered, home_indices, strict=True):
            home = home_candidates[home_index]
            home_angle = _position_angle(home)
            ranked = sorted(
                open_positions,
                key=lambda position: (
                    _angle_distance(_position_angle(position), home_angle),
                    -max(abs(position[0]), abs(position[1]), abs(sum(position))),
                ),
            )
            chosen_positions = ranked[:5]
            for position in chosen_positions:
                open_positions.remove(position)
            selected_slice = slice_by_id[int(player.slice_id or 0)]
            for position, tile_id in zip(chosen_positions, selected_slice.tiles, strict=True):
                board[f"{position[0]},{position[1]}"] = tile_id
            board[f"{home[0]},{home[1]}"] = faction_home[str(player.faction)]
        setup.board = board

    @staticmethod
    def random_order(player_ids: Sequence[int], seed: int | None = None) -> GeneratedSetup:
        if not player_ids:
            raise ValueError("At least one player is required")
        seed = seed if seed is not None else secrets.randbits(63)
        order = list(player_ids)
        Random(seed).shuffle(order)
        return GeneratedSetup(seed=seed, order=order)

    def _balanced_slices(self, rng: Random, count: int) -> list[Slice]:
        best: tuple[float, list[list[Tile]]] | None = None
        blue = self._tiles("blue")
        red = self._tiles("red")
        for _ in range(512):
            selected_blue = rng.sample(blue, count * 3)
            selected_red = rng.sample(red, count * 2)
            rng.shuffle(selected_blue)
            rng.shuffle(selected_red)
            groups = [
                selected_blue[i * 3 : i * 3 + 3] + selected_red[i * 2 : i * 2 + 2]
                for i in range(count)
            ]
            values = [sum(tile.value for tile in group) for group in groups]
            wormhole_penalty = sum(
                2 for group in groups if not any(tile.wormhole for tile in group)
            )
            score = pstdev(values) + wormhole_penalty
            if best is None or score < best[0]:
                best = score, groups
        assert best is not None
        slices: list[Slice] = []
        for index, group in enumerate(best[1], start=1):
            slices.append(
                Slice(
                    id=index,
                    tiles=tuple(tile.id for tile in group),
                    resources=sum(tile.resources for tile in group),
                    influence=sum(tile.influence for tile in group),
                    wormholes=tuple(tile.wormhole for tile in group if tile.wormhole),
                )
            )
        return slices

    def _tiles(self, color: str) -> list[Tile]:
        return [tile for tile in self.catalog.tiles.values() if tile.color == color]

    def _board_warnings(self, board: dict[str, str]) -> list[str]:
        warnings: list[str] = []
        for position, tile_id in board.items():
            tile = self.catalog.tiles[tile_id]
            if not tile.wormhole:
                continue
            q, r = map(int, position.split(","))
            for dq, dr in ((1, 0), (0, 1), (-1, 1)):
                neighbor_id = board.get(f"{q + dq},{r + dr}")
                if neighbor_id and self.catalog.tiles[neighbor_id].wormhole == tile.wormhole:
                    warnings.append(f"Adjacent {tile.wormhole} wormholes at {position}")
        return warnings

    @staticmethod
    def _validate_players(player_ids: Sequence[int]) -> None:
        if not 3 <= len(player_ids) <= 6:
            raise ValueError("A setup requires 3 to 6 players")
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("Players must be unique")


def _radius_two_positions() -> list[tuple[int, int]]:
    return [
        (q, r)
        for q in range(-2, 3)
        for r in range(-2, 3)
        if (q, r) != (0, 0) and max(abs(q), abs(r), abs(q + r)) <= 2
    ]


def _position_angle(position: tuple[int, int]) -> float:
    import math

    q, r = position
    return math.atan2(1.5 * r, math.sqrt(3) * (q + r / 2))


def _angle_distance(left: float, right: float) -> float:
    import math

    return abs((left - right + math.pi) % (2 * math.pi) - math.pi)
