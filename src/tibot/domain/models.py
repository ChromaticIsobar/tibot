"""Domain models with no Telegram or persistence dependencies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class GameMode(StrEnum):
    MILTY = "milty"
    WHOLE_BOARD = "whole_board"


class GameStatus(StrEnum):
    ROSTER = "roster"
    DRAFTING = "drafting"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class PickKind(StrEnum):
    FACTION = "faction"
    SLICE = "slice"
    SEAT = "seat"


class BoardRole(StrEnum):
    SYSTEM = "system"
    HOME_PLACEHOLDER = "home_placeholder"
    HOME_SYSTEM = "home_system"
    HYPERLANE = "hyperlane"
    GAP = "gap"


class BoardGeometry(StrEnum):
    TRIANGLE_3 = "triangle_3"
    RECTANGLE_4 = "rectangle_4"
    HYPERLANE_5 = "hyperlane_5"
    HEXAGON_6 = "hexagon_6"


@dataclass(frozen=True, slots=True, order=True)
class BoardPosition:
    radius: int
    angle: int

    @property
    def key(self) -> str:
        return f"{self.radius},{self.angle}"


@dataclass(frozen=True, slots=True)
class BoardTile:
    position: BoardPosition
    tile_id: str | None
    role: BoardRole = BoardRole.SYSTEM
    rotation: int = 0


@dataclass(slots=True)
class BoardLayout:
    geometry: BoardGeometry
    player_count: int
    tiles: list[BoardTile] = field(default_factory=list)

    def tile_at(self, position: BoardPosition) -> BoardTile | None:
        return next((tile for tile in self.tiles if tile.position == position), None)

    def replace(self, position: BoardPosition, tile_id: str, role: BoardRole) -> None:
        self.tiles = [
            BoardTile(position, tile_id, role, tile.rotation)
            if tile.position == position
            else tile
            for tile in self.tiles
        ]


@dataclass(frozen=True, slots=True)
class Faction:
    name: str
    home_system: str


@dataclass(frozen=True, slots=True)
class Tile:
    id: str
    color: str
    resources: int
    influence: int
    wormhole: str | None = None
    anomaly: str | None = None
    planets: int = 0
    specialties: int = 0
    legendary: int = 0
    stations: int = 0

    @property
    def value(self) -> int:
        return self.resources + self.influence


@dataclass(frozen=True, slots=True)
class Slice:
    id: int
    tiles: tuple[str, ...]
    resources: int
    influence: int
    wormholes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Seat:
    number: int
    is_speaker: bool = False


@dataclass(slots=True)
class Player:
    id: int | None
    display_name: str
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    faction: str | None = None
    slice_id: int | None = None
    seat: int | None = None

    @property
    def is_placeholder(self) -> bool:
        return self.telegram_user_id is None


@dataclass(slots=True)
class GeneratedSetup:
    seed: int
    factions: list[Faction] = field(default_factory=list)
    slices: list[Slice] = field(default_factory=list)
    board: BoardLayout | None = None
    order: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float | None = None
    report: list[dict[str, float | int]] = field(default_factory=list)
    speaker_player_id: int | None = None
    speaker_seed: int | None = None
    board_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GeneratedSetup:
        raw_board = value.get("board")
        board = _board_from_dict(raw_board, len(value.get("order", [])))
        return cls(
            seed=int(value["seed"]),
            factions=[Faction(**item) for item in value.get("factions", [])],
            slices=[
                Slice(
                    id=int(item["id"]),
                    tiles=tuple(item["tiles"]),
                    resources=int(item["resources"]),
                    influence=int(item["influence"]),
                    wormholes=tuple(item.get("wormholes", [])),
                )
                for item in value.get("slices", [])
            ],
            board=board,
            order=[int(item) for item in value.get("order", [])],
            warnings=[str(item) for item in value.get("warnings", [])],
            score=value.get("score"),
            report=list(value.get("report", [])),
            speaker_player_id=value.get("speaker_player_id"),
            speaker_seed=value.get("speaker_seed"),
            board_only=bool(value.get("board_only", False)),
        )


@dataclass(slots=True)
class Game:
    id: int
    chat_id: int
    mode: GameMode
    status: GameStatus
    revision: int
    created_by: int
    players: list[Player] = field(default_factory=list)
    setup: GeneratedSetup | None = None
    previous_setup: GeneratedSetup | None = None


@dataclass(slots=True)
class DraftState:
    player_order: tuple[int, ...]
    required_kinds: tuple[PickKind, ...] = (
        PickKind.FACTION,
        PickKind.SLICE,
        PickKind.SEAT,
    )
    pick_index: int = 0

    @property
    def sequence(self) -> tuple[int, ...]:
        return tuple(
            player_id
            for round_index in range(len(self.required_kinds))
            for player_id in (
                self.player_order
                if round_index % 2 == 0
                else tuple(reversed(self.player_order))
            )
        )

    @property
    def current_player_id(self) -> int | None:
        sequence = self.sequence
        return sequence[self.pick_index] if self.pick_index < len(sequence) else None

    @property
    def complete(self) -> bool:
        return self.pick_index >= len(self.sequence)

    def advance(self) -> None:
        if self.complete:
            raise ValueError("Draft is already complete")
        self.pick_index += 1


def _board_from_dict(value: Any, player_count: int) -> BoardLayout | None:
    if value is None:
        return None
    if isinstance(value, dict) and "geometry" in value:
        return BoardLayout(
            geometry=BoardGeometry(value["geometry"]),
            player_count=int(value["player_count"]),
            tiles=[
                BoardTile(
                    position=BoardPosition(**item["position"]),
                    tile_id=item.get("tile_id"),
                    role=BoardRole(item.get("role", BoardRole.SYSTEM)),
                    rotation=int(item.get("rotation", 0)),
                )
                for item in value.get("tiles", [])
            ],
        )
    if isinstance(value, dict):
        geometry = {
            3: BoardGeometry.TRIANGLE_3,
            4: BoardGeometry.RECTANGLE_4,
            5: BoardGeometry.HYPERLANE_5,
            6: BoardGeometry.HEXAGON_6,
        }.get(player_count, BoardGeometry.HEXAGON_6)
        return BoardLayout(
            geometry=geometry,
            player_count=player_count,
            tiles=[
                BoardTile(BoardPosition(*map(int, key.split(","))), str(tile_id))
                for key, tile_id in value.items()
            ],
        )
    raise ValueError("Invalid board layout")
