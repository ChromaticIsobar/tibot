"""Pillow rendering for generated boards and slice previews."""

from __future__ import annotations

import io
import math
from collections.abc import Mapping
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class BoardRenderer:
    def __init__(self, tile_dir: Path, asset_dir: Path | None = None) -> None:
        self.tile_dir = tile_dir
        self.asset_dir = asset_dir or Path(__file__).resolve().parents[1] / "assets"

    def render_board(self, board: Mapping[str, str]) -> bytes:
        size = 280
        centers = [self._center(key, size) for key in board]
        min_x = min(x for x, _ in centers) - size // 2
        min_y = min(y for _, y in centers) - size // 2
        max_x = max(x for x, _ in centers) + size // 2
        max_y = max(y for _, y in centers) + size // 2
        canvas = Image.new("RGBA", (max_x - min_x, max_y - min_y), (10, 13, 20, 255))
        for (_position, tile_id), (x, y) in zip(board.items(), centers, strict=True):
            tile = self._tile(tile_id, size)
            canvas.alpha_composite(tile, (x - size // 2 - min_x, y - size // 2 - min_y))
        return self._png(canvas)

    def render_slice(self, tile_ids: tuple[str, ...]) -> bytes:
        size = 260
        canvas = Image.new("RGBA", (size * 3, size * 3), (10, 13, 20, 255))
        positions = ((1, 1), (1, 0), (2, 1), (2, 2), (1, 2))
        for tile_id, (column, row) in zip(tile_ids, positions, strict=True):
            tile = self._tile(tile_id, size)
            canvas.alpha_composite(tile, (column * size // 2, row * size * 3 // 4))
        return self._png(canvas)

    def _tile(self, tile_id: str, size: int) -> Image.Image:
        path = self.tile_dir / f"ST_{tile_id}.png"
        if not path.exists():
            path = self.asset_dir / "no_tile.png"
        image = Image.open(path).convert("RGBA")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        layer = Image.new("RGBA", (size, size))
        layer.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
        draw = ImageDraw.Draw(layer)
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype(str(self.asset_dir / "Handel Gothic D Bold.otf"), 22)
        except OSError:
            fallback = ImageFont.load_default()
            font = fallback
        draw.text(
            (size // 2, size - 24),
            tile_id,
            anchor="mm",
            font=font,
            fill="white",
            stroke_width=2,
            stroke_fill="black",
        )
        return layer

    @staticmethod
    def _center(position: str, size: int) -> tuple[int, int]:
        q, r = map(int, position.split(","))
        return (
            round(size * math.sqrt(3) * (q + r / 2)),
            round(size * 1.5 * r),
        )

    @staticmethod
    def _png(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, "PNG", optimize=True)
        return output.getvalue()
