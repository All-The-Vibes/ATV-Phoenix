"""Mechanical probing: learn a game's rules before spending a single token (issue #177).

This exists because of how level 1 of `sb26` was actually solved. Three model agents
burned roughly 90,000 tokens on it and scored nothing. A human probing session solved it
in minutes by doing something none of them did: act, diff the board, and record WHICH
REGION changed.

That procedure needs no model at all, so it should not cost one. The prober runs first
and hands the model facts instead of a blind board:

* which actions exist, and what each one changes when pressed
* whether the game can kill you, and how often
* which cells are clickable, found by sweep rather than by guessing
* whether a click selects something (toggle behaviour) or acts immediately
* which pairs of clicks do something neither does alone (drag and drop)

That last one is the whole game in `sb26`: clicking a tile does nothing useful, clicking
a tray slot does nothing at all, and clicking one then the other places a piece. No
amount of staring at a single frame reveals it. One pair test does.
"""
from __future__ import annotations

import numpy as np

BAND = 8  # rows per reported region


def regions_changed(before: np.ndarray, after: np.ndarray) -> list[int]:
    ys, _ = np.where(before != after)
    return sorted({int(y) // BAND * BAND for y in ys})


def cells_changed(before: np.ndarray, after: np.ndarray) -> int:
    return int((before != after).sum())


def probe_actions(env, per_action: int = 2, budget=None) -> dict:
    """Press each bare action a few times and record what it does."""
    report = {}
    for action in env.actions:
        if action == 6:  # click needs coordinates; handled by the sweep
            continue
        if budget and budget() <= 2:
            break
        env.reset()
        changes, deaths, bands = [], 0, set()
        for _ in range(per_action):
            before = env.grid().copy()
            deaths_before = env.deaths
            env.press(action)
            after = env.grid()
            changes.append(cells_changed(before, after))
            bands.update(regions_changed(before, after))
            if env.deaths > deaths_before:
                deaths += 1
        report[action] = {
            "avg_cells_changed": round(sum(changes) / len(changes), 1),
            "ever_changed": any(c > 0 for c in changes),
            "deaths": deaths,
            "bands": sorted(bands),
        }
    return report


def sweep_clicks(env, step: int = 8, budget=None) -> list[dict]:
    """Find cells where a click does something, under an action budget.

    Step 8 gives 64 probes instead of step 4's 256. Board furniture on these layouts sits
    on 8-cell boundaries, so the coarse grid finds the same rows for a quarter of the
    cost, and cost is score here.
    """
    if 6 not in env.actions:
        return []
    env.reset()
    live = []
    # Sample rows densely and columns coarsely. These boards are laid out in horizontal
    # bands (a target display, a tray, a piece rack), so which ROW responds is the
    # structural fact; the exact column within a row is refined later by reading the
    # grid, which is free. Step 8 on both axes cost 58 actions and missed the piece rack
    # entirely, which lost the drag-and-drop finding that makes the game solvable.
    #
    # COLUMN-MAJOR, because the budget cuts the sweep short and what it cuts matters.
    # Sweeping row-major samples the top of the board thoroughly and the bottom not at
    # all -- measured, that reached y=44 and reported ZERO live cells on a game that is
    # entirely clickable, because every live row sits below it. Iterating columns on the
    # OUTSIDE walks the full height every 16 clicks, so one column pass samples every
    # band. On unseen games that is the difference between a probe and a guess: we do not
    # know where an unfamiliar board keeps its furniture.
    #
    # AND STOP AS SOON AS A PASS FINDS SOMETHING. The sweep is not the point; it exists to
    # nominate candidate rows for the drag-and-drop test, which is what actually cracks
    # these games. Sweeping every point cost 54 of a 60-action budget and left nothing to
    # test pairs with, so the probe reported no drag-and-drop on a game that is entirely
    # drag-and-drop -- it spent its whole allowance proving the board was clickable, which
    # nobody doubted. A completed column that found live cells is enough to proceed on.
    for x in range(6, 64, 12):
        for y in range(2, 64, 4):
            if budget and budget() <= 2:
                return live
            before = env.grid().copy()
            env.click(x, y)
            n = cells_changed(before, env.grid())
            if n:
                live.append({"x": x, "y": y, "cells": n})
        if live:
            return live
    return live


def cluster_targets(live: list[dict]) -> list[dict]:
    """Group live click cells into rows, which is how these boards are laid out."""
    by_row: dict[int, list[dict]] = {}
    for hit in live:
        by_row.setdefault(hit["y"], []).append(hit)
    out = []
    for y, hits in sorted(by_row.items()):
        xs = sorted(h["x"] for h in hits)
        out.append(
            {
                "y": y,
                "xs": xs,
                "count": len(xs),
                "avg_cells": round(sum(h["cells"] for h in hits) / len(hits), 1),
            }
        )
    return out


def test_pairs(env, rows: list[dict], samples: int = 1, budget=None) -> list[dict]:
    """Look for drag-and-drop by holding a source and testing plausible destinations.

    Order matters: a destination is invisible to a solo-click sweep, because clicking an
    empty slot changes nothing and never registers as live. It only responds once
    something is held. So pick a source up first, then test.

    The earlier version re-swept all 256 grid points for every candidate source, costing
    about 600 actions. Under RHAE that is fatal. This version tests a coarse grid of
    plausible destinations and stops at the first confirmed drag.

    CANDIDATE ORDER IS CHOSEN FOR THE BUDGET, not for tidiness. Each candidate costs three
    actions, so a 60-action probe affords roughly eight of them, and which eight is
    therefore the whole design.

    AND CANDIDATES ARE BLOBS, NOT A COORDINATE GRID. The blind grid this used to walk
    stepped y as 20, 26, 32, 38, 44, while sb26's level-1 pads sit at y=29 and are two
    cells tall -- so no candidate could land on a pad, on any budget, and the probe
    reported no drag-and-drop on a game that is entirely drag-and-drop. A grid fine enough
    to guarantee a hit on an unknown board is far too expensive to walk.
    Destinations are THINGS: they are drawn, so they are blobs, and `boardread.objects`
    finds blobs without knowing anything about this game. Probing what is drawn instead of
    where we guessed costs less and generalises to boards we have never seen, which is the
    point of a prober. The coarse grid is kept only as a fallback for a board with nothing
    findable on it.
    """
    from evals.arc.boardread import objects as board_objects

    findings = []
    if not rows:
        return findings

    source_row = max(rows, key=lambda r: r["count"])

    def far_from_source(y):
        return abs(y - source_row["y"]) > 6

    seen = set()
    blob_candidates = []
    for blob in board_objects(env.grid()):
        point = (int(blob["cx"]), int(blob["cy"]))
        if point in seen or not far_from_source(point[1]):
            continue
        seen.add(point)
        blob_candidates.append(point)

    # Spread across rows before repeating one, for the same reason the click sweep goes
    # column-major: whatever the budget cuts should be detail, not a whole band.
    by_row: dict[int, list[tuple[int, int]]] = {}
    for x, y in blob_candidates:
        by_row.setdefault(y, []).append((x, y))
    candidates = [row.pop(0) for _ in range(max((len(v) for v in by_row.values()), default=0))
                  for row in by_row.values() if row]

    if not candidates:
        candidates = [
            (x, y)
            for x in range(12, 56, 6)
            for y in range(20, 48, 6)
            if far_from_source(y)
        ]

    for xa in source_row["xs"][:samples]:
        for x, y in candidates:
            if budget and budget() <= 3:
                return findings

            env.reset()
            before_solo = env.grid().copy()
            env.click(x, y)
            solo_cells = cells_changed(before_solo, env.grid())

            env.reset()
            env.click(xa, source_row["y"])  # pick the source up
            before_pair = env.grid().copy()
            env.click(x, y)
            paired = cells_changed(before_pair, env.grid())

            if paired > solo_cells + 8:
                findings.append(
                    {
                        "from": {"x": xa, "y": source_row["y"]},
                        "to": {"x": x, "y": y},
                        "solo_cells": solo_cells,
                        "paired_cells": paired,
                        "bands": regions_changed(before_pair, env.grid()),
                    }
                )
                return findings
    return findings


def probe(env, click_step: int = 8, budget: int = 60) -> dict:
    """Mechanical characterisation under an action budget.

    Every action here is charged by the benchmark. RHAE counts any input that alters game
    state and scores (human_actions / ai_actions) squared, so an unbudgeted probe wins the
    level and loses the score: 625 actions on sb26 against a human baseline of 22 for
    level 1 caps that level at 0.1 percent however well it is subsequently played.

    THE STALL GUARD IS SUSPENDED FOR THE DURATION. `Env.click` raises `StallDetected`
    after 40 consecutive actions that change nothing, which is the right rule for an AGENT
    -- repeating an action that does not affect the level is the measured way runs waste
    thousands of actions. It is exactly the wrong rule here. A probe is SAMPLING: it
    clicks a coarse grid to learn which cells are live, and on sb26 most of that grid is
    dead, so a long run of inert clicks is the finding rather than a malfunction. Measured:
    with the guard active, `sweep_clicks` died partway through its sweep and the probe
    reported no drag-and-drop on a game that is entirely drag-and-drop.

    The limit is restored afterwards, including on failure, so nothing downstream inherits
    a disarmed guard.
    """
    spent_before = env.spent
    stall_limit = getattr(env, "inert_limit", None)
    if stall_limit is not None:
        env.inert_limit = 10**9

    def remaining():
        return budget - (env.spent - spent_before)

    try:
        actions = probe_actions(env, per_action=2, budget=remaining)
        live = sweep_clicks(env, click_step, budget=remaining) if remaining() > 4 else []
        rows = cluster_targets(live)
        pairs = test_pairs(env, rows, budget=remaining) if rows and remaining() > 4 else []
        env.reset()
    finally:
        if stall_limit is not None:
            env.inert_limit = stall_limit
            env._inert = 0
    return {
        "actions": actions,
        "click_rows": rows,
        "drag_and_drop": pairs,
        "kills_you": any(a["deaths"] for a in actions.values()),
        "actions_spent_probing": env.spent - spent_before,
    }


def summarize(report: dict) -> str:
    """Plain-language probe result for the model prompt."""
    lines = ["MECHANICAL PROBE (measured, not guessed):"]

    for action, info in sorted(report["actions"].items()):
        if not info["ever_changed"]:
            lines.append(f"  action {action}: does NOTHING when pressed bare")
        else:
            kill = f", KILLED YOU {info['deaths']}x" in "" or (
                f", killed you {info['deaths']} times" if info["deaths"] else ""
            )
            lines.append(
                f"  action {action}: changes ~{info['avg_cells_changed']} cells "
                f"in rows {info['bands']}{kill}"
            )

    if report["click_rows"]:
        lines.append("  clickable cells found by sweep:")
        for row in report["click_rows"]:
            lines.append(
                f"    row y={row['y']}: {row['count']} live x positions {row['xs']} "
                f"(~{row['avg_cells']} cells each)"
            )
    else:
        lines.append("  no clickable cells found")

    if report["drag_and_drop"]:
        d = report["drag_and_drop"][0]
        lines.append(
            f"  DRAG AND DROP CONFIRMED: clicking ({d['from']['x']},{d['from']['y']}) "
            f"then ({d['to']['x']},{d['to']['y']}) changes {d['paired_cells']} cells, "
            f"but clicking the destination alone changes only {d['solo_cells']}. "
            f"Click a source to pick it up, then a destination to place it."
        )

    lines.append(
        "  this game CAN kill you; deaths reset the level"
        if report["kills_you"]
        else "  no deaths observed; you cannot lose by acting"
    )
    return "\n".join(lines)
