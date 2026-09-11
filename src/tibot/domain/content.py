"""Validated access to submodule-backed game content."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tibot.domain.models import Faction, Tile


class ContentError(RuntimeError):
    """Raised when the content submodule is missing or malformed."""


@dataclass(frozen=True, slots=True)
class ContentCatalog:
    root: Path
    factions: tuple[Faction, ...]
    tiles: dict[str, Tile]
    tile_image_dir: Path

    @classmethod
    def load(cls, root: Path | None = None) -> ContentCatalog:
        content_root = root or _default_content_root()
        data_dir = content_root / "src" / "data"
        tile_dir = content_root / "public" / "tiles"
        race_path = data_dir / "raceData.json"
        tile_path = data_dir / "tileData.json"
        missing = [path for path in (race_path, tile_path, tile_dir) if not path.exists()]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise ContentError(
                f"TI4 content is missing ({names}). Clone with --recurse-submodules or run "
                "'git submodule update --init --recursive'."
            )
        try:
            races = _read_json(race_path)
            tile_data = _read_json(tile_path)
            factions = _parse_factions(races)
            tiles = _parse_tiles(tile_data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ContentError(f"Invalid TI4 content: {exc}") from exc
        if not factions or not tiles:
            raise ContentError("TI4 content did not contain factions and tiles")
        return cls(content_root, factions, tiles, tile_dir)


def _default_content_root() -> Path:
    configured = os.getenv("TIBOT_CONTENT_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "modules" / "ti4"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _parse_factions(data: dict[str, Any]) -> tuple[Faction, ...]:
    names = [str(item) for key in ("races", "pokRaces", "teRaces") for item in data.get(key, [])]
    mapping = data.get("raceToHomeSystemMap")
    if not isinstance(mapping, dict):
        reverse = data.get("homeSystemToRaceMap", {})
        mapping = {str(name): str(system) for system, name in reverse.items()}
    return tuple(Faction(name=name, home_system=str(mapping.get(name, "0"))) for name in names)


def _parse_tiles(data: dict[str, Any]) -> dict[str, Tile]:
    all_tiles = data["all"]
    result: dict[str, Tile] = {}
    for tile_id, raw in all_tiles.items():
        planets = raw.get("planets", [])
        result[str(tile_id)] = Tile(
            id=str(tile_id),
            color=str(raw.get("type", "other")),
            resources=sum(int(planet.get("resources", 0)) for planet in planets),
            influence=sum(int(planet.get("influence", 0)) for planet in planets),
            wormhole=raw.get("wormhole"),
            anomaly=raw.get("anomaly"),
        )
    return result

