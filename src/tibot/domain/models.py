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
    board: dict[str, str] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GeneratedSetup:
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
            board={str(k): str(v) for k, v in value.get("board", {}).items()},
            order=[int(item) for item in value.get("order", [])],
            warnings=[str(item) for item in value.get("warnings", [])],
            score=value.get("score"),
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
    pick_index: int = 0

    @property
    def sequence(self) -> tuple[int, ...]:
        return self.player_order + tuple(reversed(self.player_order)) + self.player_order

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

