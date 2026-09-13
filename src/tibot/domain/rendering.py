"""Tightly cropped Pillow rendering for radial Twilight Imperium boards."""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tibot.domain.layouts import layout_for, path_from_center, slice_preview_positions
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
_CAPTION_OPACITY = round(255 * 0.75)


class BoardRenderer:
    def __init__(self, tile_dir: Path, asset_dir: Path | None = None) -> None:
        self.tile_dir = tile_dir
        self.asset_dir = asset_dir or Path(__file__).resolve().parents[1] / "assets"

    def render_board(
        self,
        board: BoardLayout,
        home_labels: dict[BoardPosition, str] | None = None,
        edge: int = 180,
        margin: int = 24,
    ) -> bytes:
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
            if tile.role is BoardRole.HOME_PLACEHOLDER and home_labels:
                caption = home_labels.get(tile.position, caption)
            if tile.rotation:
                image = image.rotate(tile.rotation, expand=False)
            left = x - tile_width // 2 - min_x + margin
            top = y - tile_height // 2 - min_y + margin
            canvas.alpha_composite(image, (left, top))
            self._caption(
                canvas,
                (left + tile_width // 2, top + tile_height // 2),
                caption,
                round(edge * 0.33),
                round(tile_width * 0.82),
            )
        return self._png(canvas)

    def render_slice(self, tile_ids: tuple[str, ...], player_count: int) -> bytes:
        edge = 150
        positions = slice_preview_positions(player_count)
        if len(positions) != len(tile_ids) + 1:
            raise ValueError("Slice tile count does not match its geometry")
        tiles = [BoardTile(positions[0], None, BoardRole.HOME_PLACEHOLDER)]
        tiles.extend(
            BoardTile(position, tile_id)
            for position, tile_id in zip(positions[1:], tile_ids, strict=True)
        )
        width, height = round(2 * edge * 1.003 + 2), round(_SQRT_3 * edge * 1.003 + 2)
        centers = {tile.position: self._center(tile.position, edge) for tile in tiles}
        min_x = min(x for x, _ in centers.values()) - width // 2
        max_x = max(x for x, _ in centers.values()) + width // 2
        min_y = min(y for _, y in centers.values()) - height // 2
        max_y = max(y for _, y in centers.values()) + height // 2
        margin = 20
        canvas = Image.new(
            "RGBA",
            (max_x - min_x + 2 * margin, max_y - min_y + 2 * margin),
            (10, 13, 20, 255),
        )
        for tile in tiles:
            image, caption = self._tile_image(tile, (), (width, height))
            x, y = centers[tile.position]
            left = x - width // 2 - min_x + margin
            top = y - height // 2 - min_y + margin
            canvas.alpha_composite(image, (left, top))
            self._caption(
                canvas,
                (left + width // 2, top + height // 2),
                caption,
                round(edge * 0.33),
                round(width * 0.82),
            )
        return self._png(canvas)

    def _tile_image(
        self,
        tile: BoardTile,
        homes: tuple[BoardPosition, ...],
        size: tuple[int, int],
    ) -> tuple[Image.Image, str]:
        if tile.role is BoardRole.HOME_PLACEHOLDER:
            path = self.tile_dir / "ST_0.png"
            caption = (
                f"SEAT {homes.index(tile.position) + 1}"
                if tile.position in homes
                else "HOME"
            )
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
        font_size: int,
        max_width: int,
    ) -> None:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = self._fitted_font(caption, font_size, max_width)
        draw.text(
            position,
            caption,
            anchor="mm",
            font=font,
            fill=(255, 255, 255, _CAPTION_OPACITY),
            stroke_width=max(2, math.ceil(font_size * 0.1)),
            stroke_fill=(0, 0, 0, _CAPTION_OPACITY),
        )
        image.alpha_composite(overlay)

    def _fitted_font(
        self, caption: str, default_size: int, max_width: int
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        path = str(self.asset_dir / "Handel Gothic D Bold.otf")
        for size in range(default_size, 11, -1):
            try:
                font = ImageFont.truetype(path, size)
            except OSError:
                return ImageFont.load_default()
            left, _, right, _ = font.getbbox(caption, stroke_width=max(2, math.ceil(size * 0.1)))
            if right - left <= max_width:
                return font
        return ImageFont.truetype(path, 12)

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
