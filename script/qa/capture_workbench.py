"""Render full Birkin workbench frames to PNG evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SIZES = ((60, 20), (80, 24), (120, 30), (160, 40))
_BG = "#12110f"
_FG = "#eee9df"
_MUTED = "#b9ad95"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", size)


def capture(output: Path, columns: int, rows: int) -> Path:
    from birkin import workbench
    from birkin.runtime import build_session

    session = build_session()
    lines = workbench.render(
        workbench.snapshot(session),
        workbench.initial_state(),
        (columns, rows),
        color=False,
    )
    font = _font(16)
    cell = 10
    line_height = 24
    margin = 16
    image = Image.new(
        "RGB",
        (margin * 2 + columns * cell, margin * 2 + rows * line_height),
        _BG,
    )
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines[:rows]):
        color = _MUTED if index == 1 else _FG
        draw.text((margin, margin + index * line_height), line, font=font, fill=color)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for columns, rows in _SIZES:
        capture(args.output / f"terminal-{columns}x{rows}.png", columns, rows)


if __name__ == "__main__":
    main()
