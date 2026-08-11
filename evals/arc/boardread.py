"""Exact object listing for a 64x64 ARC board, at zero action cost (issue #177).

The measured level-2 failure on `sb26` was not a mechanics failure. The agent already
knew drag-and-drop. It read the tray with a hand-rolled colour filter, dropped a cyan
piece because cyan was also scenery on level 1, ended up with six pieces for seven slots,
and then its own consistency guard refused to act. Seven turns, two actions each, nothing
learned.

The obvious remedy is to re-probe the level mechanically. That works and it is what
`rsi_agent` does, but it is expensive in the only currency the benchmark counts: RHAE
charges every input that alters game state, and level 2 of `sb26` has a human baseline of
28 actions. A 150-action probe caps that level at (28/178)^2, about 2 percent of what it
could have scored.

Connected-component analysis of `grid()` costs **nothing**. It is arithmetic on an array
the agent already holds. It answers the exact question the parser got wrong -- what
discrete objects are on this board, where, and what colour -- without touching the game.

So the paid probe is the fallback, not the first move.
"""
from __future__ import annotations

import numpy as np

MAX_COMPONENTS = 80
BACKGROUND_SHARE = 0.25  # a colour covering more than this of the board is scenery


def _components(grid: np.ndarray, colour: int) -> list[dict]:
    """4-connected blobs of one colour. Iterative flood fill; 4096 cells, so trivial."""
    mask = grid == colour
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y0, x0 in zip(*np.where(mask)):
        if seen[y0, x0]:
            continue
        stack = [(int(y0), int(x0))]
        seen[y0, x0] = True
        cells = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1]:
                    if mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        ys = [c[0] for c in cells]
        xs = [c[1] for c in cells]
        out.append(
            {
                "colour": int(colour),
                "y0": min(ys), "y1": max(ys), "x0": min(xs), "x1": max(xs),
                "cy": (min(ys) + max(ys)) // 2,
                "cx": (min(xs) + max(xs)) // 2,
                "px": len(cells),
            }
        )
    return out


def objects(grid: np.ndarray, min_px: int = 4) -> list[dict]:
    """Every discrete blob on the board, background colours excluded.

    Background is detected by area share rather than hardcoded, because which colour is
    scenery differs per game and per level. Hardcoding it is precisely the bug this
    module exists to remove: level 1's scenery colour was level 2's piece.
    """
    total = grid.size
    found: list[dict] = []
    for colour in np.unique(grid):
        if (grid == colour).sum() > total * BACKGROUND_SHARE:
            continue
        found.extend(c for c in _components(grid, int(colour)) if c["px"] >= min_px)
    found.sort(key=lambda c: (c["cy"], c["cx"]))
    return found[:MAX_COMPONENTS]


def rows(found: list[dict], tol: int = 3) -> list[dict]:
    """Group blobs into horizontal bands. These boards are laid out in rows."""
    bands: list[dict] = []
    for blob in found:
        for band in bands:
            if abs(band["cy"] - blob["cy"]) <= tol:
                band["items"].append(blob)
                band["cy"] = sum(b["cy"] for b in band["items"]) // len(band["items"])
                break
        else:
            bands.append({"cy": blob["cy"], "items": [blob]})
    for band in bands:
        band["items"].sort(key=lambda b: b["cx"])
    return sorted(bands, key=lambda b: b["cy"])


def describe(grid: np.ndarray) -> str:
    """Compact, exact board description for the model prompt.

    Deliberately states the piece and slot counts as a separate line. The observed
    level-2 loss was six pieces placed into seven slots, and nobody counted.
    """
    found = objects(grid)
    if not found:
        return "BOARD OBJECTS: none found (board may be blank or all one colour)."

    lines = [
        "BOARD OBJECTS (computed exactly from grid(), zero actions spent). "
        "TRUST THIS OVER THE IMAGE and over any parser you wrote on an earlier level:"
    ]
    for band in rows(found):
        parts = [
            f"c{b['colour']}@({b['cx']},{b['cy']})[{b['x0']}-{b['x1']}x{b['y0']}-{b['y1']},{b['px']}px]"
            for b in band["items"]
        ]
        colours = sorted({b["colour"] for b in band["items"]})
        lines.append(
            f"  row y~{band['cy']}: {len(band['items'])} objects, colours {colours}"
        )
        lines.append("      " + "  ".join(parts))

    by_colour: dict[int, int] = {}
    for b in found:
        by_colour[b["colour"]] = by_colour.get(b["colour"], 0) + 1
    lines.append(
        f"  totals: {len(found)} objects, counts per colour "
        f"{dict(sorted(by_colour.items()))}"
    )
    return "\n".join(lines)


def diff(before: np.ndarray, after: np.ndarray) -> str:
    """What an action actually changed, as a bounding box. Free, and it is the fact."""
    ys, xs = np.where(before != after)
    if not len(ys):
        return "nothing changed"
    return (
        f"{len(ys)} cells changed in box x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}"
    )
