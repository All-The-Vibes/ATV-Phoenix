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


def parse(grid):
    """Split the board into clues, tray pieces, pads, frames and markers.

    Everything is derived from shape and repetition, never from a colour constant or a
    row index, because those move between levels and that is what broke every earlier
    parser.
    """
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
    return {"frames": frames, "pads": pads, "clues": clues, "tray": tray,
            "clue_structure": _clue_structure([c["colour"] for c in clues], len(pads))}


def _clue_structure(colours, n_pads):
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
    flat = {"flat": True, "colours": list(colours), "block": None,
            "at": [], "reduced": list(colours)}
    if len(colours) == n_pads:
        return flat

    # A row SHORTER than the pad count is structured too, and saying otherwise is the
    # same lie that cost eleven runs on level 5. Level 7 draws seven rings over eight
    # pads as 8,9,14,11,14,9,8 -- a palindrome over three sibling frames whose outline
    # colours are 8, 9 and 14 -- and its tray holds three 9s and three 14s where the row
    # names two of each. No block decomposition explains a short row, so none is offered;
    # what is reported is that the row is not one ring per pad.
    unexplained = {"flat": False, "colours": list(colours), "block": None,
                   "at": [], "reduced": list(colours)}
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
                        "at": hits, "reduced": reduced}
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
