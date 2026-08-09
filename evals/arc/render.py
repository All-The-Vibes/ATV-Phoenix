"""Render an ARC-AGI-3 frame as a PNG for a vision model.

The text sketch in `llm_agent` was the wrong call. ARC is a spatial benchmark: the
whole point is perceiving structure in a grid, and a colour histogram plus row runs
destroys exactly the structure being tested. Prime Agent's reported 95.5 came from a
model that could see the board.

Cells are drawn as flat squares with a grid overlay and coordinate rulers every 8
cells, because the model has to name click coordinates and counting unlabelled squares
in an image is its own failure mode.

The palette is fixed and stated to the model in the prompt, so "colour 3" in prose and
the colour on screen are the same fact.
"""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image, ImageDraw

# ARC's 16-value palette. Index is the cell value the environment reports.
PALETTE = [
    (0, 0, 0),        # 0  black
    (0, 116, 217),    # 1  blue
    (255, 65, 54),    # 2  red
    (46, 204, 64),    # 3  green
    (255, 220, 0),    # 4  yellow
    (170, 170, 170),  # 5  grey
    (240, 18, 190),   # 6  magenta
    (255, 133, 27),   # 7  orange
    (127, 219, 255),  # 8  cyan
    (135, 12, 37),    # 9  maroon
    (255, 255, 255),  # 10 white
    (100, 65, 165),   # 11 purple
    (0, 128, 128),    # 12 teal
    (160, 90, 44),    # 13 brown
    (60, 60, 60),     # 14 dark grey
    (200, 200, 120),  # 15 sand
]

CELL = 10          # pixels per cell -> 64*10 = 640px board
MARGIN = 26        # room for coordinate rulers
RULER_EVERY = 8


def to_grid(frame) -> np.ndarray:
    grid = np.array(frame, dtype=np.int8)
    if grid.ndim == 3:
        grid = grid[0]
    return grid


def render_png(frame) -> bytes:
    grid = to_grid(frame)
    rows, cols = grid.shape
    width = cols * CELL + MARGIN
    height = rows * CELL + MARGIN
    img = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(img)

    for y in range(rows):
        for x in range(cols):
            value = int(grid[y, x]) % len(PALETTE)
            x0 = MARGIN + x * CELL
            y0 = MARGIN + y * CELL
            draw.rectangle([x0, y0, x0 + CELL - 1, y0 + CELL - 1], fill=PALETTE[value])

    # Grid lines every RULER_EVERY cells, so the model can count in blocks of 8.
    for x in range(0, cols + 1, RULER_EVERY):
        px = MARGIN + x * CELL
        draw.line([(px, MARGIN), (px, MARGIN + rows * CELL)], fill=(90, 90, 90))
        draw.text((px + 1, 6), str(x), fill=(210, 210, 210))
    for y in range(0, rows + 1, RULER_EVERY):
        py = MARGIN + y * CELL
        draw.line([(MARGIN, py), (MARGIN + cols * CELL, py)], fill=(90, 90, 90))
        draw.text((3, py + 1), str(y), fill=(210, 210, 210))

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def data_url(frame) -> str:
    encoded = base64.b64encode(render_png(frame)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def palette_legend(frame) -> str:
    """Name only the colours actually present, so the legend stays short."""
    grid = to_grid(frame)
    names = [
        "black", "blue", "red", "green", "yellow", "grey", "magenta", "orange",
        "cyan", "maroon", "white", "purple", "teal", "brown", "dark-grey", "sand",
    ]
    present = sorted({int(v) for v in np.unique(grid)})
    return ", ".join(f"{v}={names[v % len(names)]}" for v in present)
