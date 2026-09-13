"""Deterministic, player-count-specific setup generators."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from random import Random

from tibot.domain.content import ContentCatalog
from tibot.domain.layouts import adjacent, layout_for, slice_layout_for
from tibot.domain.models import (
    BoardLayout,
    BoardPosition,
    BoardRole,
    BoardTile,
    GeneratedSetup,
    Player,
    Slice,
    Tile,
)

_COMPOSITION = {3: (14, 10), 4: (20, 12), 5: (15, 10), 6: (18, 12)}
_ANOMALIES = {3: 6, 4: 9, 5: 5, 6: 6}
_SLICE_COMPOSITION = {3: (5, 3), 4: (5, 3), 5: (3, 2), 6: (3, 2)}
_EXCLUDED = {"18", "81", "82", "112"}


class SetupGenerator:
    def __init__(self, catalog: ContentCatalog, candidates: int = 1024) -> None:
        self.catalog = catalog
        self.candidates = candidates

    def milty(
        self,
        player_ids: Sequence[int],
        seed: int | None = None,
        faction_count: int | None = None,
        slice_count: int | None = None,
    ) -> GeneratedSetup:
        self._validate_players(player_ids)
        seed = seed if seed is not None else secrets.randbits(63)
        rng = Random(seed)
        count = len(player_ids)
        faction_count = faction_count if faction_count is not None else count + 2
        slice_count = slice_count if slice_count is not None else count + 1
        self._validate_pool_sizes(count, faction_count, slice_count)
        factions = rng.sample(list(self.catalog.factions), faction_count)
        slices = self._balanced_slices(rng, count, slice_count)
        order = list(player_ids)
        rng.shuffle(order)
        return GeneratedSetup(seed=seed, factions=factions, slices=slices, order=order)

    def whole_board(
        self,
        player_ids: Sequence[int],
        seed: int | None = None,
        faction_count: int | None = None,
    ) -> GeneratedSetup:
        self._validate_players(player_ids)
        seed = seed if seed is not None else secrets.randbits(63)
        rng = Random(seed)
        count = len(player_ids)
        faction_count = faction_count if faction_count is not None else count + 2
        self._validate_pool_sizes(count, faction_count)
        spec = layout_for(count)
        best: tuple[float, list[list[Tile]], list[dict[str, float | int]]] | None = None
        for _ in range(max(1, self.candidates)):
            selected = self._choose_whole_board_tiles(rng, count)
            if selected is None:
                continue
            rng.shuffle(selected)
            regions: list[list[Tile]] = []
            cursor = 0
            for positions in spec.regions:
                regions.append(selected[cursor : cursor + len(positions)])
                cursor += len(positions)
            score, report = self._score_regions(regions, spec.regions, spec.homes)
            if best is None or score < best[0]:
                best = score, [region[:] for region in regions], report
        if best is None:
            raise ValueError(f"Content cannot produce a legal {count}-player board")
        score, regions, report = best
        board = self._empty_layout(count)
        for positions, tiles in zip(spec.regions, regions, strict=True):
            for position, tile in zip(positions, tiles, strict=True):
                board.tiles.append(BoardTile(position, tile.id))
        order = list(player_ids)
        rng.shuffle(order)
        factions = rng.sample(list(self.catalog.factions), faction_count)
        return GeneratedSetup(
            seed=seed,
            factions=factions,
            board=board,
            order=order,
            warnings=self._warnings(regions, spec.regions, report),
            score=round(score, 2),
            report=report,
        )

    def finalize(
        self,
        setup: GeneratedSetup,
        players: Sequence[Player],
        *,
        random_speaker: bool,
    ) -> None:
        if any(player.faction is None or player.seat is None for player in players):
            raise ValueError("Every player needs a faction and seat")
        count = len(players)
        if setup.board is None:
            if any(player.slice_id is None for player in players):
                raise ValueError("Every player needs a slice")
            spec = slice_layout_for(count)
            setup.board = self._empty_layout(count, slices=True)
            slices = {item.id: item for item in setup.slices}
            for player in players:
                region = spec.regions[int(player.seat or 0) - 1]
                chosen = slices[int(player.slice_id or 0)]
                for position, tile_id in zip(region, chosen.tiles, strict=True):
                    setup.board.tiles.append(BoardTile(position, tile_id))
        homes = (
            slice_layout_for(count).homes if setup.slices else layout_for(count).homes
        )
        home_systems = {faction.name: faction.home_system for faction in self.catalog.factions}
        for player in players:
            home = homes[int(player.seat or 0) - 1]
            setup.board.replace(home, home_systems[str(player.faction)], BoardRole.HOME_SYSTEM)
        if random_speaker:
            setup.speaker_seed = secrets.randbits(63)
            setup.speaker_player_id = Random(setup.speaker_seed).choice(
                [int(player.id) for player in players if player.id is not None]
            )
        else:
            setup.speaker_player_id = next(
                int(player.id)
                for player in players
                if player.seat == 1 and player.id is not None
            )

    def preview_board(
        self, setup: GeneratedSetup, players: Sequence[Player]
    ) -> BoardLayout | None:
        if setup.board is None and not setup.slices:
            return None
        if setup.board is None and not any(player.seat is not None for player in players):
            return None
        count = len(players)
        spec = slice_layout_for(count) if setup.slices else layout_for(count)
        source = setup.board or self._empty_layout(count, slices=True)
        board = BoardLayout(source.geometry, source.player_count, list(source.tiles))
        slices = {item.id: item for item in setup.slices}
        homes = spec.homes
        home_systems = {faction.name: faction.home_system for faction in self.catalog.factions}
        for player in players:
            if player.seat is None:
                continue
            if player.slice_id is not None and setup.slices:
                region = spec.regions[player.seat - 1]
                chosen = slices[player.slice_id]
                occupied = {tile.position for tile in board.tiles}
                board.tiles.extend(
                    BoardTile(position, tile_id)
                    for position, tile_id in zip(region, chosen.tiles, strict=True)
                    if position not in occupied
                )
            if player.faction is not None:
                board.replace(
                    homes[player.seat - 1],
                    home_systems[player.faction],
                    BoardRole.HOME_SYSTEM,
                )
        return board

    def random_factions(self, count: int, seed: int | None = None) -> GeneratedSetup:
        if not 1 <= count <= len(self.catalog.factions):
            raise ValueError("Faction count is outside the available range")
        seed = seed if seed is not None else secrets.randbits(63)
        return GeneratedSetup(
            seed=seed,
            factions=Random(seed).sample(list(self.catalog.factions), count),
        )

    @staticmethod
    def random_order(player_ids: Sequence[int], seed: int | None = None) -> GeneratedSetup:
        if not player_ids:
            raise ValueError("At least one player is required")
        seed = seed if seed is not None else secrets.randbits(63)
        order = list(player_ids)
        Random(seed).shuffle(order)
        return GeneratedSetup(seed=seed, order=order)

    @staticmethod
    def random_choice(choices: Sequence[str], seed: int | None = None) -> tuple[str, int]:
        normalized = [choice.strip() for choice in choices if choice.strip()]
        if not normalized:
            raise ValueError("At least one non-empty choice is required")
        seed = seed if seed is not None else secrets.randbits(63)
        return Random(seed).choice(normalized), seed

    @staticmethod
    def random_die(sides: int, seed: int | None = None) -> tuple[int, int]:
        if sides < 1:
            raise ValueError("A die must have at least one side")
        seed = seed if seed is not None else secrets.randbits(63)
        return Random(seed).randint(1, sides), seed

    def _empty_layout(self, player_count: int, *, slices: bool = False) -> BoardLayout:
        spec = slice_layout_for(player_count) if slices else layout_for(player_count)
        tiles = [BoardTile(BoardPosition(0, 0), self._mecatol_id())]
        tiles.extend(
            BoardTile(position, None, BoardRole.HOME_PLACEHOLDER)
            for position in spec.homes
        )
        tiles.extend(BoardTile(position, None, BoardRole.GAP) for position in spec.gaps)
        tiles.extend(
            BoardTile(position, tile_id, BoardRole.HYPERLANE, rotation)
            for position, tile_id, rotation in spec.hyperlanes
        )
        return BoardLayout(spec.geometry, player_count, tiles)

    def _choose_whole_board_tiles(self, rng: Random, count: int) -> list[Tile] | None:
        blue_target, red_target = _COMPOSITION[count]
        eligible = self._eligible_tiles()
        chosen: list[Tile] = []
        for wormhole in ("alpha", "beta"):
            pool = [
                tile
                for tile in eligible
                if tile.wormhole == wormhole and tile.anomaly is None
            ]
            if len(pool) < 2:
                return None
            chosen.extend(rng.sample(pool, 2))
        anomaly_target = _ANOMALIES[count]
        anomaly_pool = [
            tile
            for tile in eligible
            if tile.anomaly
            and tile.wormhole not in ("alpha", "beta")
            and tile not in chosen
        ]
        needed = anomaly_target - sum(tile.anomaly is not None for tile in chosen)
        if needed < 0 or len(anomaly_pool) < needed:
            return None
        chosen.extend(rng.sample(anomaly_pool, needed))
        for color, target in (("blue", blue_target), ("red", red_target)):
            needed = target - sum(tile.color == color for tile in chosen)
            pool = [
                tile
                for tile in eligible
                if tile.color == color
                and tile.anomaly is None
                and tile.wormhole not in ("alpha", "beta")
                and tile not in chosen
            ]
            if needed < 0 or len(pool) < needed:
                return None
            chosen.extend(rng.sample(pool, needed))
        return chosen if len(chosen) == len(layout_for(count).systems) else None

    def _balanced_slices(self, rng: Random, player_count: int, count: int) -> list[Slice]:
        blue_count, red_count = _SLICE_COMPOSITION[player_count]
        blue = [tile for tile in self._eligible_tiles() if tile.color == "blue"]
        red = [tile for tile in self._eligible_tiles() if tile.color == "red"]
        best: tuple[float, list[list[Tile]]] | None = None
        for _ in range(512):
            selected_blue = rng.sample(blue, count * blue_count)
            selected_red = rng.sample(red, count * red_count)
            rng.shuffle(selected_blue)
            rng.shuffle(selected_red)
            groups = [
                selected_blue[i * blue_count : (i + 1) * blue_count]
                + selected_red[i * red_count : (i + 1) * red_count]
                for i in range(count)
            ]
            values = [sum(tile.value for tile in group) for group in groups]
            score = max(values) - min(values)
            score += 2 * sum(not any(tile.wormhole for tile in group) for group in groups)
            if best is None or score < best[0]:
                best = float(score), groups
        assert best is not None
        return [
            Slice(
                id=index,
                tiles=tuple(tile.id for tile in group),
                resources=sum(tile.resources for tile in group),
                influence=sum(tile.influence for tile in group),
                wormholes=tuple(tile.wormhole for tile in group if tile.wormhole),
            )
            for index, group in enumerate(best[1], start=1)
        ]

    def _score_regions(
        self,
        regions: list[list[Tile]],
        positions: tuple[tuple[BoardPosition, ...], ...],
        homes: tuple[BoardPosition, ...],
    ) -> tuple[float, list[dict[str, float | int]]]:
        report: list[dict[str, float | int]] = []
        for player, (tiles, region_positions, home) in enumerate(
            zip(regions, positions, homes, strict=True), 1
        ):
            metrics: dict[str, float | int] = {
                "player": player,
                "resources": sum(tile.resources for tile in tiles),
                "influence": sum(tile.influence for tile in tiles),
                "practical": sum(max(tile.resources, tile.influence) for tile in tiles),
                "planets": sum(tile.planets for tile in tiles),
                "specialties": sum(tile.specialties for tile in tiles),
                "legendary": sum(tile.legendary for tile in tiles),
                "stations": sum(tile.stations for tile in tiles),
                "anomalies": sum(tile.anomaly is not None for tile in tiles),
                "wormholes": sum(tile.wormhole in ("alpha", "beta") for tile in tiles),
                "home_anomalies": sum(
                    tile.anomaly is not None and adjacent(position, home)
                    for tile, position in zip(tiles, region_positions, strict=True)
                ),
            }
            report.append(metrics)

        def spread(key: str) -> float:
            values = [float(item[key]) for item in report]
            return max(values) - min(values)

        score = (
            24 * spread("practical") ** 2
            + 8 * spread("resources") ** 2
            + 8 * spread("influence") ** 2
            + 3 * spread("planets") ** 2
            + 5 * spread("specialties") ** 2
            + 12 * spread("legendary") ** 2
            + 12 * spread("stations") ** 2
            + 16 * spread("anomalies") ** 2
            + 14 * spread("wormholes") ** 2
            + 35 * sum(float(item["home_anomalies"]) for item in report)
        )
        flat = [
            (position, tile)
            for region_positions, tiles in zip(positions, regions, strict=True)
            for position, tile in zip(region_positions, tiles, strict=True)
        ]
        for index, (position, tile) in enumerate(flat):
            for other_position, other in flat[index + 1 :]:
                if not adjacent(position, other_position):
                    continue
                if tile.anomaly and other.anomaly:
                    score += 45
                if tile.wormhole in ("alpha", "beta") and tile.wormhole == other.wormhole:
                    score += 100
        return score, report

    def _warnings(
        self,
        regions: list[list[Tile]],
        positions: tuple[tuple[BoardPosition, ...], ...],
        report: list[dict[str, float | int]],
    ) -> list[str]:
        warnings: list[str] = []
        flat = [
            (position, tile)
            for region_positions, tiles in zip(positions, regions, strict=True)
            for position, tile in zip(region_positions, tiles, strict=True)
        ]
        anomaly_pairs = wormhole_pairs = 0
        for index, (position, tile) in enumerate(flat):
            for other_position, other in flat[index + 1 :]:
                if adjacent(position, other_position):
                    anomaly_pairs += int(bool(tile.anomaly and other.anomaly))
                    wormhole_pairs += int(
                        tile.wormhole in ("alpha", "beta")
                        and tile.wormhole == other.wormhole
                    )
        if anomaly_pairs:
            warnings.append(f"{anomaly_pairs} adjacent anomaly pair(s)")
        if wormhole_pairs:
            warnings.append(f"{wormhole_pairs} adjacent same-type wormhole pair(s)")
        if sum(int(item["home_anomalies"]) for item in report):
            warnings.append("one or more anomalies are adjacent to a home system")
        return warnings

    def _eligible_tiles(self) -> list[Tile]:
        return [
            tile
            for tile in self.catalog.tiles.values()
            if tile.id not in _EXCLUDED
            and tile.color in ("blue", "red")
            and tile.anomaly != "muaat-supernova"
        ]

    def _mecatol_id(self) -> str:
        return "112" if "112" in self.catalog.tiles else "18"

    def _validate_pool_sizes(
        self, player_count: int, faction_count: int, slice_count: int | None = None
    ) -> None:
        if not player_count <= faction_count <= len(self.catalog.factions):
            raise ValueError(
                f"Faction pool must contain {player_count} to {len(self.catalog.factions)} options"
            )
        if slice_count is not None and not player_count <= slice_count <= player_count + 2:
            raise ValueError(
                f"Slice pool must contain {player_count} to {player_count + 2} options"
            )

    @staticmethod
    def _validate_players(player_ids: Sequence[int]) -> None:
        if not 3 <= len(player_ids) <= 6:
            raise ValueError("A setup requires 3 to 6 players")
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("Players must be unique")
