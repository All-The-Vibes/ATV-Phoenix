"""The frame-traversal rule, derived from the board and tested against the live game.

Nine prior runs treated the destination order as unknowable and searched it: one turn
spent 2,075 actions on 22 orderings and found nothing. The order was never hidden. It is
drawn on the board.

The layout is a tree of nested rectangular FRAMES. Each frame holds some destination pads
and, sometimes, a MARKER: a small ring whose colour is the outline colour of another
frame. A marker means "at this point in the walk, descend into the frame I name, finish
it, and come back". Reading the tree depth-first, left to right, yields the order in which
the clue sequence maps onto the pads.

Verified: level 2 has one marker (c14 at x=34 inside the c8 frame) and the traversal it
implies is exactly the arrangement that clears the level. Level 3 has two markers inside
the top frame naming two sibling frames below.

Nothing here is specific to sb26 beyond "the board is drawn with rectangles and rings",
which is the ARC visual vocabulary. There is no colour constant, no row index and no
action number in this file. It reads whatever frames exist and walks them.
"""
from __future__ import annotations

from evals.arc.boardread import objects


def _is_frame(blob, grid_h, grid_w):
    """A hollow rectangle: wide, tall, and mostly outline rather than fill."""
    h = blob["y1"] - blob["y0"] + 1
    w = blob["x1"] - blob["x0"] + 1
    if h < 5 or w < 5:
        return False
    if h >= grid_h - 2 and w >= grid_w - 2:
        return False  # the background, not a frame
    return blob["px"] < h * w * 0.75


def _inside(inner, outer):
    return (
        inner["x0"] >= outer["x0"] and inner["x1"] <= outer["x1"]
        and inner["y0"] >= outer["y0"] and inner["y1"] <= outer["y1"]
        and inner is not outer
    )


def budget(grid, full_colour=None, row=None):
    """The bar the board draws for your remaining moves: cells left, used and total.

    `mechanics.json` used to call this bar a TIMER that drains "as ticks pass", and told
    the agent to budget its turn against the clock. Measured against the live game, every
    part of that is wrong, and it was the most expensive thing left in the harness:

        click a tray piece (pick up) .... 0 cells
        click a pad (DROP a piece) ...... 1 cell
        submit .......................... 1 cell
        undo ............................ 0 cells
        click empty space ............... 0 cells
        doing nothing at all ............ 0 cells

    So it is not a clock. It is a MUTATION budget: it counts pieces dropped and boards
    submitted, and nothing else. 64 consecutive submits took a full bar to zero and the
    64th killed; 120 clicks on empty space and 199 undos moved it not at all.

    The consequence the agent was denied: looking is free. On an eight-pad level a full
    hypothesis costs nine cells -- eight drops and a submit -- so one life buys seven
    attempts, which is exactly the rate at which measured runs were dying on level 7
    (1,367 actions, 7 deaths, ~195 actions each). Believing the bar was a clock made the
    agent hurry through reads that cost nothing and rebuild whole boards that cost
    everything.

    Read from the drawing rather than remembered as a constant, because the bar's length
    is a per-level property and a number baked into a prompt would be wrong somewhere.
    The bar is the one full-width row drawn in colours that are not the board's
    background: a single run while untouched, two runs once it has been eaten into.

    Which of the two runs is the REMAINING one cannot be settled from a single frame, so
    it is not guessed. A level always opens with the bar full and therefore one colour,
    and the caller passes that colour back as ``full_colour`` on later reads. Without it
    the two segments are still reported, flagged ``confirmed: False``, rather than a
    direction being invented.

    THE SPENT PORTION MAY BE DRAWN IN THE BOARD'S BACKGROUND COLOUR. sb26 draws its bar
    in colours reserved for it, so ranking candidates by exclusivity and skipping any row
    containing the background worked there and hid an assumption. cd82 spends its bar into
    the background: row 63 reads ``{4: 64}`` on a fresh board and ``{4: 61, 5: 3}`` three
    moves later, where 5 IS the background. The row was therefore skipped the moment it
    became informative, and `clock()` returned every field None from the first action
    onward -- so on cd82 the agent could not see a single one of its six deaths coming,
    and those deaths cost 463 of the run's 713 actions.

    So once ``full_colour`` is known the bar is looked for a second way: the full-width
    two-segment row CONTAINING that colour, background or not. The strict exclusivity pass
    still runs first and still wins, which leaves sb26's reading byte-identical; this only
    answers where the strict pass finds nothing at all.

    AND THE ROW IS REMEMBERED, because that second pass is not selective enough on its own.
    Measured on cd82: the bar is row 63 and drains 64, 63, 62, 61 as actions are spent, but
    row 16 is a static piece of board furniture drawn in the same two colours, so it is
    equally "exclusive" and, being the lower index, won the tie. `clock()` then reported a
    frozen 18/64 forever -- worse than the blindness it replaced, because a frozen number
    looks like a reading. A bar does not move between frames, so the caller hands back the
    row it was found on and it is read directly, with the searches below as the fallback.
    """
    h, w = grid.shape
    counts: dict[int, int] = {}
    for line in grid:
        for value in line.tolist():
            counts[value] = counts.get(value, 0) + 1
    background = max(counts, key=counts.get)

    unknown = {"row": None, "left": None, "used": None, "total": None,
               "fraction": None, "full_colour": full_colour, "confirmed": False}

    def read(y, cells):
        seen = set(cells)
        if len(seen) == 1:
            return {"row": y, "left": w, "used": 0, "total": w, "fraction": 1.0,
                    "full_colour": cells[0], "confirmed": True}
        if full_colour is None or full_colour not in seen:
            a, b = cells[0], cells[-1]
            return {**unknown, "row": y, "total": w,
                    "segments": {a: cells.count(a), b: cells.count(b)}}
        left = cells.count(full_colour)
        return {"row": y, "left": left, "used": w - left, "total": w,
                "fraction": round(left / w, 3), "full_colour": full_colour,
                "confirmed": True}

    # The known bar, read where it was last seen. Still validated as bar-shaped, so a board
    # that redraws that row into something else falls through to the searches instead of
    # reporting nonsense from a stale coordinate.
    if row is not None and 0 <= row < h:
        cells = grid[row].tolist()
        seen = set(cells)
        runs = 1 + sum(1 for a, b in zip(cells, cells[1:]) if a != b)
        if 1 <= len(seen) <= 2 and runs <= 2 and (full_colour is None or full_colour in seen):
            return read(row, cells)

    # More than one row can look like a bar. On sb26 row 0 is a full-width two-colour
    # band of ordinary board colours, and on the stale frame served at a level boundary
    # it was picked as the meter and reported a full bar that did not exist. The bar is
    # told apart by being drawn in a colour RESERVED for it: c2/c3 appear nowhere else on
    # the board, while row 0's colours are used all over it. So candidates are ranked by
    # how much of their ink lies outside the row, and the most exclusive one wins.
    def scan(allow_background: bool, must_contain=None):
        found = []
        for y in range(h):
            cells = grid[y].tolist()
            seen = set(cells)
            if not 1 <= len(seen) <= 2:
                continue
            if must_contain is not None and must_contain not in seen:
                continue
            if background in seen and not allow_background:
                continue
            if 1 + sum(1 for a, b in zip(cells, cells[1:]) if a != b) > 2:
                continue
            elsewhere = sum(counts[c] for c in seen) - w
            found.append((elsewhere, y, cells))
        return found

    candidates = scan(allow_background=False)
    if not candidates and full_colour is not None:
        # Second pass, only for a bar we have already identified on a full board: the
        # spent half is allowed to be the background colour.
        candidates = scan(allow_background=True, must_contain=full_colour)

    if not candidates:
        return unknown

    _, y, cells = min(candidates)
    return read(y, cells)


def parse(grid, strict=False):
    """Split the board into clues, tray pieces, pads, frames and markers.

    Everything is derived from shape and repetition, never from a colour constant or a
    row index, because those move between levels and that is what broke every earlier
    parser.

    Returns None on a board this cannot describe. That includes the BLANK board the game
    draws once the last level is cleared: it has no rows to unpack, and raising there
    turned finishing the game into a traceback on the very turn that finished it. It also
    includes boards whose piece and pad counts are incoherent, and -- when `strict` is set
    -- any board that is not this parser's shape at all. See the note above the return.
    """
    import numpy as _np

    grid = _np.asarray(grid)
    if grid.ndim != 2 or grid.size == 0:
        return None
    blobs = objects(grid)
    h, w = grid.shape

    # Pads are the smallest repeated blob size on the board. Clues and tray pieces are
    # the two larger repeated sizes: clues sit above the pad band, tray pieces below.
    sizes: dict[int, list[dict]] = {}
    for b in blobs:
        sizes.setdefault(b["px"], []).append(b)
    repeated = {px: bs for px, bs in sizes.items() if len(bs) >= 2}
    if not repeated:
        return None

    pad_px = min(repeated)
    pads = sorted(repeated[pad_px], key=lambda b: (b["cy"], b["cx"]))

    # A frame is a hollow rectangle that CONTAINS pads. Without that condition every clue
    # ring counts as a frame, since a ring is also a small hollow rectangle, and level 1
    # parsed as five frames and zero clues.
    frames = [
        b for b in blobs
        if _is_frame(b, h, w) and any(_inside(p, b) for p in pads)
    ]

    # Clues and tray are the blobs ABOVE and BELOW the pad band. Deriving the split from
    # the pads rather than from the frames matters: level 1 has no frames at all, and
    # keying off frame extents returned zero clues there and no plan.
    pad_top = min(p["y0"] for p in pads)
    pad_bottom = max(p["y1"] for p in pads)
    candidates = [b for b in blobs if b not in frames and b["px"] > pad_px
                  and (b["x1"] - b["x0"] + 1) < w * 0.6]

    def band(members):
        """The dominant repeated shape in a band, ordered left to right.

        Taking every blob in the band was wrong twice over: a clue is a ring around a
        fill square, so each clue contributes two blobs, and the ring interiors and
        stray marker dots outnumbered the pieces. Pieces and clues are the size that
        repeats most; anything else in the band is decoration.

        Grouped by BOUNDING BOX, not by pixel count. From level 4 the game draws some
        pieces hollow: the level-4 tray holds a c14 square with its middle punched out,
        4x4 but 12px where its neighbours are 16px. Keying on pixel count put it in a
        group of one, the parse returned six pieces for seven clues, and the plan was
        abandoned. The footprint is what a hollow piece keeps.
        """
        if not members:
            return []
        counts: dict[tuple[int, int], list[dict]] = {}
        for b in members:
            box = (b["y1"] - b["y0"] + 1, b["x1"] - b["x0"] + 1)
            counts.setdefault(box, []).append(b)
        # Ties go to the SMALLER footprint, because `_enclosing` below lifts each pick
        # to the ring that wraps it. Preferring the larger box selected the rings
        # directly, `_enclosing` then found nothing to lift to, and level 1 planned four
        # placements of the neutral fill colour instead of the four target colours.
        best = max(counts.items(), key=lambda kv: (len(kv[1]), -kv[0][0] * kv[0][1]))[1]
        return sorted(best, key=lambda b: b["cx"])

    clues = band([b for b in candidates if b["y1"] < pad_top])
    tray = band([b for b in candidates if b["y0"] > pad_bottom])

    # A clue is drawn as a ring of the target colour around a fill square of a neutral
    # colour, and `band` picks whichever of the two repeats. The colour that matters is
    # the ring's, so for each clue prefer the enclosing blob when one exists. Picking the
    # fill gave four identical clue colours on level 1 and no piece matched any of them.
    clues = [_enclosing(blobs, c) or c for c in clues]
    tray = [_enclosing(blobs, t) or t for t in tray]

    # Earlier versions hunted for a MARKER: a ring of one frame's colour drawn inside
    # another, taken to mean "descend here". That reading held on levels 2 and 3 and
    # died on level 4, whose sub-frame is announced by no ring at all. The link is
    # simpler and it is always drawn: a child frame is placed under the parent pad it
    # follows, so its horizontal centre IS its insertion point. `traverse` uses that
    # and needs no marker.
    # WHAT THIS DESCRIPTION IS WORTH, stated rather than assumed. This parser was written
    # for one shape: a tray of pieces, one per pad, and a clue row addressing them.
    # Measured across the 25 public ARC-AGI-3 games (`corpus_survey.py`), that shape holds
    # on exactly ONE of them -- sb26. On the other 24 the code above still returns a
    # layout, and it is nonsense: tu93 comes back with 62 pads and no tray, dc22 with 13
    # pads and no tray, tn36 with a 1x27 clue row.
    #
    # Confident nonsense is worse than nothing. Every rule here assumes one tray piece per
    # pad, so a caller handed a bogus layout plans against a board that does not exist, and
    # the agent then looks like it is reasoning badly while reasoning correctly about a
    # false picture -- Gap 7 in HARNESS_GAPS.md, the expensive lesson of this repo.
    #
    # Two different things are needed, so they are separated rather than conflated:
    #
    #   `well_formed` is the PRISTINE signature, one tray piece per pad. It is True on an
    #   untouched sb26 board and False on the other 24 games' opening boards. It is also
    #   False on a half-played sb26 board, which is correct and not a complaint: the tray
    #   really has emptied. Ask it of an opening frame to decide whether this abstraction
    #   describes the game at all.
    #
    #   `strict=True` turns that same question into a refusal, for callers that would
    #   rather have None than something they must remember to check. It is off by default
    #   because `seated()` and the executor parse MID-LEVEL, where an emptied tray is the
    #   normal, healthy state, and refusing there would break the game we can already win.
    #
    # More tray pieces than pads is incoherent under any reading, so that is refused
    # unconditionally.
    if not pads or len(tray) > len(pads):
        return None
    well_formed = bool(tray) and len(tray) == len(pads)
    if strict and not well_formed:
        return None

    return {"frames": frames, "pads": pads, "clues": clues, "tray": tray,
            "well_formed": well_formed,
            "clue_structure": _clue_structure(clues, len(pads))}


def _collapse_clue_rows(clues):
    """Collapse a clue drawn over several rows into the one row it repeats.

    The clue is not always a single row of rings. Level 8 draws TWELVE rings over
    EIGHT pads in two rows of six, and every column holds the same colour in both
    rows -- the second row restates the first and carries no colour of its own.
    Flattened, that reads `8,8,11,11,12,12,9,9,14,14,15,15`, and the doubling is
    indistinguishable from a tray that happens to hold two of something. Measured on
    level 8: the agent fused the clue's doubling with the tray's and searched a rank
    of eight it had invented, spending 228 actions over nine turns without once
    testing a six-entry reading.

    So the rows are collapsed here, where the coordinates still exist, rather than
    guessed at later from a flat list where they do not. Returns
    (per_column_colours, n_rows, n_cols), and n_rows == 1 whenever the clue really is
    one row or its columns disagree -- a disagreeing column means the rows differ and
    the duplication reading would be a lie.
    """
    rows = sorted({int(round(float(c["cy"]))) for c in clues})
    cols = sorted({int(round(float(c["cx"]))) for c in clues})
    if len(rows) < 2 or len(clues) != len(rows) * len(cols):
        return [int(c["colour"]) for c in clues], 1, len(clues)

    grid = {}
    for c in clues:
        grid[(int(round(float(c["cx"]))), int(round(float(c["cy"]))))] = int(c["colour"])
    if len(grid) != len(clues):
        return [int(c["colour"]) for c in clues], 1, len(clues)

    per_column = []
    for x in cols:
        seen = {grid.get((x, y)) for y in rows}
        if len(seen) != 1 or None in seen:
            # The rows are not restatements of each other, so there is nothing to
            # collapse and saying otherwise would discard real colours.
            return [int(c["colour"]) for c in clues], 1, len(clues)
        per_column.append(seen.pop())
    return per_column, len(rows), len(cols)


def _clue_structure(clues, n_pads):
    """Describe the clue row's shape: a flat list, or a row containing a repeated block.

    From level 5 the row stops being one ring per pad. Level 5 draws NINE rings over
    EIGHT pads -- `6,14,8,8,14,8,8,11,15` -- and the ring colours do not even match the
    tray as a multiset, so an agent reading the row as a flat list gets a contradiction
    with no hint of where it came from. Measured across several runs: the agent wrote
    `assert len(clues) == len(pads)`, crashed, and spent the rest of the level guessing
    assignments rather than reading the row.

    That is a perception failure, not a reasoning one, so it is fixed here. What is
    reported is only what is DRAWN: that a contiguous block of colours repeats, which
    block it is, where its occurrences start, and the row with each occurrence replaced
    by a single None. The block is found by arithmetic that holds for any board -- a row
    longer than the pad count by `(repeats - 1) * (size - 1)` is consistent with a block
    of `size` appearing `repeats` times and each occurrence standing for one pad.

    What the row MEANS is left alone. Which pads the reduced row addresses, which pads
    the block fills, and what colour belongs on a collapsed position are not answered
    here; the None is a hole the agent has to fill from the board and the tray.
    """
    colours, n_rows, n_cols = _collapse_clue_rows(clues)
    drawn = [int(c["colour"]) for c in clues]
    # What the collapse found, carried on every reading below so the agent is never
    # told a row is flat without also being told it was two rows a moment ago.
    grid = {"rows": n_rows, "cols": n_cols, "drawn": drawn}

    flat = {"flat": True, "colours": list(colours), "block": None,
            "at": [], "reduced": list(colours), "grid": grid}
    if len(colours) == n_pads:
        return flat

    # A row SHORTER than the pad count is structured too, and saying otherwise is the
    # same lie that cost eleven runs on level 5. Level 7 draws seven rings over eight
    # pads as 8,9,14,11,14,9,8 -- a palindrome over three sibling frames whose outline
    # colours are 8, 9 and 14 -- and its tray holds three 9s and three 14s where the row
    # names two of each. No block decomposition explains a short row, so none is offered;
    # what is reported is that the row is not one ring per pad.
    unexplained = {"flat": False, "colours": list(colours), "block": None,
                   "at": [], "reduced": list(colours), "grid": grid}
    over = len(colours) - n_pads
    if over <= 0:
        return unexplained

    for size in range(2, n_pads):
        # A block of `size` fills one pad group, so the rest of the row addresses the
        # other `n_pads - size` pads, `repeats` of which are written out as blocks:
        #   len(row) = (n_pads - size) + repeats * (size - 1)
        numer = len(colours) - n_pads + size
        if numer <= 0 or numer % (size - 1):
            continue
        repeats = numer // (size - 1)
        if repeats < 2:
            continue
        for start in range(len(colours) - size + 1):
            block = colours[start:start + size]
            hits, at = [], 0
            while at <= len(colours) - size:
                if colours[at:at + size] == block:
                    hits.append(at)
                    at += size
                else:
                    at += 1
            if len(hits) != repeats:
                continue
            marked = set(hits)
            reduced, at = [], 0
            while at < len(colours):
                if at in marked:
                    reduced.append(None)
                    at += size
                else:
                    reduced.append(colours[at])
                    at += 1
            # The block is taken to fill a group of `size` pads, so what is left of the
            # row must address the rest of them. When that does not add up, this block
            # is a coincidence rather than the row's structure.
            if len(reduced) == n_pads - size:
                return {"flat": False, "colours": list(colours), "block": list(block),
                        "at": hits, "reduced": reduced, "grid": grid}
    return unexplained


def _pad_owner(frames, pad):
    """The tightest frame whose box contains this pad, or None."""
    holding = [f for f in frames
               if f["x0"] <= pad["cx"] <= f["x1"] and f["y0"] <= pad["cy"] <= f["y1"]]
    if not holding:
        return None
    return min(holding, key=lambda f: (f["y1"] - f["y0"]) * (f["x1"] - f["x0"]))


def _enclosing(blobs, blob):
    """The tightest blob that wraps this one, or None. Finds a ring around a fill."""
    holding = [b for b in blobs if _inside(blob, b)]
    if not holding:
        return None
    return min(holding, key=lambda b: (b["y1"] - b["y0"]) * (b["x1"] - b["x0"]))


def traverse(parsed):
    """Pads in the order the board's frame layout says to fill them.

    The rule, measured against the live game on levels 2, 3 and 4: frames sit in
    horizontal BANDS, one band per row of pads. A frame in a lower band is a child of
    whichever upper-band frame spans its horizontal centre, and that centre is also the
    point in the parent's own left-to-right pad sequence where the child's pads are
    spliced in. Walk the top band left to right, descending at each child's centre.

    Two things this deliberately does NOT do, both because they were tried and measured
    wrong. It does not look for marker rings: level 4's child frame has none, and the
    ring-based reading planned an order the game rejected. It does not band frames by
    their own top edge: level 2's two frames overlap vertically, so edge-banding merged
    them into one band and lost the nesting. Banding on the y of each frame's PADS is
    what separates them, since the pad rows are what the layout is actually built from.
    """
    frames = list(parsed["frames"])
    pads = parsed["pads"]

    own: dict[int, list[dict]] = {id(f): [] for f in frames}
    own[0] = []
    for pad in pads:
        host = _pad_owner(frames, pad)
        own[id(host) if host is not None else 0].append(pad)
    for group in own.values():
        group.sort(key=lambda b: b["cx"])

    # A frame holding no pads is scenery for ordering purposes and must not form a band
    # of its own, or an empty band becomes the root and the walk yields nothing.
    live = [f for f in frames if own[id(f)]]
    if not live:
        return sorted(own[0], key=lambda b: (b["cy"], b["cx"]))

    def pad_row(frame):
        group = own[id(frame)]
        return sum(p["cy"] for p in group) / len(group)

    bands: list[list[dict]] = []
    for frame in sorted(live, key=pad_row):
        if bands and abs(pad_row(bands[-1][0]) - pad_row(frame)) <= 3:
            bands[-1].append(frame)
        else:
            bands.append([frame])

    kids: dict[int, list[dict]] = {id(f): [] for f in frames}
    for depth in range(1, len(bands)):
        for frame in bands[depth]:
            centre = (frame["x0"] + frame["x1"]) / 2
            parents = [g for g in bands[depth - 1] if g["x0"] <= centre <= g["x1"]]
            if parents:
                tightest = min(parents, key=lambda g: g["x1"] - g["x0"])
                kids[id(tightest)].append(frame)

    def walk(frame):
        key = id(frame)
        items = [(p["cx"], "pad", p) for p in own[key]]
        items += [((c["x0"] + c["x1"]) / 2, "frame", c) for c in kids[key]]
        items.sort(key=lambda item: item[0])
        out: list[dict] = []
        for _, kind, obj in items:
            out.extend([obj] if kind == "pad" else walk(obj))
        return out

    order: list[dict] = []
    for root in sorted(bands[0], key=lambda f: f["x0"]):
        order.extend(walk(root))
    order.extend(own[0])

    seen = set()
    unique = []
    for pad in order:
        key = (pad["cx"], pad["cy"])
        if key not in seen:
            seen.add(key)
            unique.append(pad)
    return unique


def plan(grid):
    """(colour, (x, y)) placements in the order the board says to make them."""
    parsed = parse(grid)
    if not parsed:
        return None
    clues = parsed["clues"]
    if not clues:
        return None
    # The reference reading is tried FIRST, not as a fallback. Level 6 has nine clues
    # for nine pads, so the flat left-to-right reading looks applicable and is wrong.
    # Counting is not enough to tell the two encodings apart; `_reference` returns None
    # unless the row really does name frames and consume the tray exactly.
    referenced = _reference(parsed)
    if referenced:
        return referenced
    order = traverse(parsed)
    if len(order) == len(clues):
        return [(c["colour"], (p["cx"], p["cy"])) for c, p in zip(clues, order)]
    return _expand(parsed)


def _groups(parsed):
    """Pads bucketed by owning frame, each bucket left to right.

    Returns (root_pads, [(frame, pads), ...]) with the root taken to be the frame
    holding the most pads. Ownerless pads join the root. Returns None when the board
    has no child frame to nest into, since both nested readings need one.
    """
    frames, pads = parsed["frames"], parsed["pads"]
    buckets: dict[int, list[dict]] = {}
    hosts: dict[int, dict | None] = {}
    for pad in pads:
        host = _pad_owner(frames, pad)
        key = id(host) if host is not None else 0
        buckets.setdefault(key, []).append(pad)
        hosts[key] = host
    for group in buckets.values():
        group.sort(key=lambda b: b["cx"])
    if len(buckets) < 2:
        return None
    root_key = max(buckets, key=lambda k: len(buckets[k]))
    kids = [(hosts[k], buckets[k]) for k in buckets if k != root_key]
    return buckets[root_key], kids


def _reference(parsed):
    """Read the clue row as references: a frame's OUTLINE COLOUR names that frame.

    Measured on level 6, whose row is `9,11,11,12,15,15,14,6,6` over four frames in a
    2x2. The three colours 9, 12 and 14 are the outline colours of the three non-root
    frames, and the clues immediately after each one are exactly that frame's contents:
    9 introduces `11,11`, 12 introduces `15,15`, 14 introduces `6,6`. The reference
    tokens themselves occupy the root frame's three pads, which is why a piece of each
    frame's own colour sits in the tray.

    Brute force over level 6 confirmed this assignment and no other: root pads take
    9,12,14 left to right, and each named frame takes its block.

    This is a different encoding from `_expand`, which spells a child block out in full
    at every occurrence. Both appear on this board, so both are tried.
    """
    split = _groups(parsed)
    if not split:
        return None
    root, kids = split
    clues = [c["colour"] for c in parsed["clues"]]

    # With a SINGLE child frame both encodings fit the same clue count, and the tray
    # test cannot separate them because the clue row is a permutation of the tray under
    # either reading. Levels 2, 3 and 4 each have one child and measurably use the flat
    # reading; level 6 has three children and measurably uses this one. So a lone child
    # is left to the flat reader rather than guessed at.
    if len(kids) < 2:
        return None

    by_colour = {}
    for frame, pads in kids:
        by_colour.setdefault(frame["colour"], []).append((frame, pads))
    # An ambiguous reference colour would make the walk a guess rather than a reading.
    if any(len(v) > 1 for v in by_colour.values()):
        return None

    pairs: list[tuple[int, tuple[int, int]]] = []
    pending = dict(by_colour)
    at = 0
    for pad in root:
        if at >= len(clues):
            return None
        colour = clues[at]
        at += 1
        pairs.append((colour, (pad["cx"], pad["cy"])))
        if colour in pending:
            _, kid_pads = pending.pop(colour)[0]
            block = clues[at:at + len(kid_pads)]
            if len(block) != len(kid_pads):
                return None
            at += len(block)
            pairs += [(c, (p["cx"], p["cy"])) for c, p in zip(block, kid_pads)]
    if at != len(clues) or pending:
        return None

    # The tray is the independent check: it holds exactly one piece per pad, so a
    # correct reading uses up the tray exactly. A misreading almost never does.
    if sorted(c for c, _ in pairs) != sorted(t["colour"] for t in parsed["tray"]):
        return None
    return pairs


def _expand(parsed):
    """Read the clue row as a nested expression when it is longer than the pad count.

    From level 5 the row stops being a flat list. Level 5 shows nine clues for eight
    pads: `6,14,8,8,14,8,8,11,15`. The sub-frame holds three pads and the block
    `14,8,8` appears twice, so the row is `6,<sub>,<sub>,11,15` written out in full.
    Each occurrence collapses to ONE top-row pad, which is why the counts differ by
    exactly (occurrences - 1) * blocklen.

    Which colour goes on a collapsed pad is not stated in the row, so it is recovered
    from the tray: the tray holds one piece per pad, and after the literal clues are
    accounted for, the colour left over in the right quantity is the reference colour.
    On level 5 that is c9, twice, matching the two occurrences. Deriving it from the
    tray rather than from the sub-frame's outline colour matters, because both frame
    colours (c8 and c9) are present in that tray and the outline reading is ambiguous.

    Placement ORDER within an attempt does not matter; measured directly by clearing
    level 4 from four shuffled orders. Only the colour-to-pad assignment is graded.
    """
    frames, pads = parsed["frames"], parsed["pads"]
    clues = [c["colour"] for c in parsed["clues"]]
    tray = list(parsed["tray"])
    if len(tray) != len(pads):
        return None

    groups: dict[int, list[dict]] = {}
    for pad in pads:
        host = _pad_owner(frames, pad)
        groups.setdefault(id(host) if host is not None else 0, []).append(pad)
    for group in groups.values():
        group.sort(key=lambda b: b["cx"])
    ordered = sorted(groups.values(), key=lambda g: g[0]["cy"])
    if len(ordered) != 2:
        return None
    top, child = ordered

    # The row spells out the child block in full at every occurrence, so its length is
    # the top row's own length plus (size - 1) per occurrence.
    size = len(child)
    over = len(clues) - len(top)
    if size < 2 or over <= 0 or over % (size - 1):
        return None
    repeats = over // (size - 1)
    if repeats < 2:
        return None

    for start in range(len(clues) - size + 1):
        block = clues[start:start + size]
        hits, at = [], 0
        while at <= len(clues) - size:
            if clues[at:at + size] == block:
                hits.append(at)
                at += size
            else:
                at += 1
        if len(hits) != repeats:
            continue
        marked = set(hits)
        reduced, at = [], 0
        while at < len(clues):
            if at in marked:
                reduced.append(None)  # a reference to the child block
                at += size
            else:
                reduced.append(clues[at])
                at += 1
        if len(reduced) != len(top):
            continue

        # Whatever the tray still holds once every literal clue is spoken for is the
        # colour that stands for the child block.
        remaining = [t["colour"] for t in tray]
        for colour in [c for c in reduced if c is not None] + block:
            if colour not in remaining:
                break
            remaining.remove(colour)
        else:
            if len(set(remaining)) != 1 or len(remaining) != repeats:
                continue
            ref = remaining[0]
            plan_pairs = [
                (ref if c is None else c, (p["cx"], p["cy"]))
                for c, p in zip(reduced, top)
            ]
            plan_pairs += [(c, (p["cx"], p["cy"])) for c, p in zip(block, child)]
            return plan_pairs
    return None
