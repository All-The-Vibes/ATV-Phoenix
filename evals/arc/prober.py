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
    for y in range(2, 64, 4):
        for x in range(6, 64, 12):
            if budget and budget() <= 2:
                return live
            before = env.grid().copy()
            env.click(x, y)
            n = cells_changed(before, env.grid())
            if n:
                live.append({"x": x, "y": y, "cells": n})
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
    about 600 actions. Under RHAE that is fatal. This version tests the centre band,
    where these layouts put their trays, and stops at the first confirmed drag.
    """
    findings = []
    if not rows:
        return findings

    source_row = max(rows, key=lambda r: r["count"])
    candidates = [
        (x, y)
        for y in range(20, 48, 6)
        for x in range(12, 56, 6)
        if abs(y - source_row["y"]) > 6
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
    """
    spent_before = env.spent

    def remaining():
        return budget - (env.spent - spent_before)

    actions = probe_actions(env, per_action=2, budget=remaining)
    live = sweep_clicks(env, click_step, budget=remaining) if remaining() > 4 else []
    rows = cluster_targets(live)
    pairs = test_pairs(env, rows, budget=remaining) if rows and remaining() > 4 else []
    env.reset()
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
