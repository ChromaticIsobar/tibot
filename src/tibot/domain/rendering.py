"""Tightly cropped Pillow rendering for radial Twilight Imperium boards."""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tibot.domain.layouts import layout_for, path_from_center
from tibot.domain.models import BoardLayout, BoardPosition, BoardRole, BoardTile

_SQRT_3 = math.sqrt(3)
_DIRECTIONS = (
    (0.0, -_SQRT_3),
    (1.5, -_SQRT_3 / 2),
    (1.5, _SQRT_3 / 2),
    (0.0, _SQRT_3),
    (-1.5, _SQRT_3 / 2),
    (-1.5, -_SQRT_3 / 2),
)


class BoardRenderer:
    def __init__(self, tile_dir: Path, asset_dir: Path | None = None) -> None:
        self.tile_dir = tile_dir
        self.asset_dir = asset_dir or Path(__file__).resolve().parents[1] / "assets"

    def render_board(self, board: BoardLayout, edge: int = 180, margin: int = 24) -> bytes:
        visible = [tile for tile in board.tiles if tile.role is not BoardRole.GAP]
        if not visible:
            raise ValueError("Board has no visible tiles")
        tile_width = round(2 * edge * 1.003 + 2)
        tile_height = round(_SQRT_3 * edge * 1.003 + 2)
        centers = {tile.position: self._center(tile.position, edge) for tile in visible}
        min_x = min(x for x, _ in centers.values()) - tile_width // 2
        max_x = max(x for x, _ in centers.values()) + tile_width // 2
        min_y = min(y for _, y in centers.values()) - tile_height // 2
        max_y = max(y for _, y in centers.values()) + tile_height // 2
        canvas = Image.new(
            "RGBA",
            (max_x - min_x + 2 * margin, max_y - min_y + 2 * margin),
            (10, 13, 20, 255),
        )
        homes = layout_for(board.player_count).homes
        for tile in visible:
            x, y = centers[tile.position]
            image, caption = self._tile_image(tile, homes, (tile_width, tile_height))
            if tile.rotation:
                image = image.rotate(tile.rotation, expand=False)
            left = x - tile_width // 2 - min_x + margin
            top = y - tile_height // 2 - min_y + margin
            canvas.alpha_composite(image, (left, top))
            self._caption(canvas, (left + tile_width // 2, top + tile_height - 22), caption)
        return self._png(canvas)

    def render_slice(self, tile_ids: tuple[str, ...]) -> bytes:
        edge = 150
        width, height = round(2 * edge), round(_SQRT_3 * edge)
        columns = 3
        rows = math.ceil(len(tile_ids) / columns)
        canvas = Image.new("RGBA", (columns * width, rows * height), (10, 13, 20, 255))
        for index, tile_id in enumerate(tile_ids):
            tile = BoardTile(BoardPosition(0, 0), tile_id)
            image, caption = self._tile_image(tile, (), (width, height))
            left = index % columns * width
            top = index // columns * height
            canvas.alpha_composite(image, (left, top))
            self._caption(canvas, (left + width // 2, top + height - 18), caption, 18)
        return self._png(canvas)

    def _tile_image(
        self,
        tile: BoardTile,
        homes: tuple[BoardPosition, ...],
        size: tuple[int, int],
    ) -> tuple[Image.Image, str]:
        if tile.role is BoardRole.HOME_PLACEHOLDER:
            path = self.tile_dir / "ST_0.png"
            seat = homes.index(tile.position) + 1
            caption = f"SEAT {seat}"
        else:
            path = self.tile_dir / f"ST_{tile.tile_id}.png"
            caption = str(tile.tile_id or "")
        if not path.exists():
            path = self.asset_dir / "no_tile.png"
        return Image.open(path).convert("RGBA").resize(size, Image.Resampling.LANCZOS), caption

    def _caption(
        self,
        image: Image.Image,
        position: tuple[int, int],
        caption: str,
        font_size: int = 22,
    ) -> None:
        draw = ImageDraw.Draw(image)
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype(
                str(self.asset_dir / "Handel Gothic D Bold.otf"), font_size
            )
        except OSError:
            font = ImageFont.load_default()
        draw.text(
            position,
            caption,
            anchor="mm",
            font=font,
            fill="white",
            stroke_width=2,
            stroke_fill="black",
        )

    @staticmethod
    def _center(position: BoardPosition, edge: int) -> tuple[int, int]:
        x = y = 0.0
        for direction in path_from_center(position.radius, position.angle):
            dx, dy = _DIRECTIONS[direction]
            x += edge * dx
            y += edge * dy
        return round(x), round(y)

    @staticmethod
    def _png(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, "PNG", optimize=True)
        return output.getvalue()
