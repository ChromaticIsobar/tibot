"""Pure Twilight Imperium setup domain."""

from tibot.domain.content import ContentCatalog, ContentError
from tibot.domain.generation import SetupGenerator
from tibot.domain.models import (
    BoardGeometry,
    BoardLayout,
    BoardPosition,
    BoardRole,
    BoardTile,
    DraftState,
    Faction,
    Game,
    GameMode,
    GameStatus,
    GeneratedSetup,
    Player,
    Seat,
    Slice,
)

__all__ = [
    "BoardGeometry",
    "BoardLayout",
    "BoardPosition",
    "BoardRole",
    "BoardTile",
    "ContentCatalog",
    "ContentError",
    "DraftState",
    "Faction",
    "Game",
    "GameMode",
    "GameStatus",
    "GeneratedSetup",
    "Player",
    "Seat",
    "SetupGenerator",
    "Slice",
]
