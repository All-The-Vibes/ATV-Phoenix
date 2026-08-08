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


def probe_actions(env, per_action: int = 6) -> dict:
    """Press each bare action a few times and record what it does."""
    report = {}
    for action in env.actions:
        if action == 6:  # click needs coordinates; handled by the sweep
            continue
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


def sweep_clicks(env, step: int = 4) -> list[dict]:
    """Find every cell where a click does something. Coarse grid, one pass."""
    if 6 not in env.actions:
        return []
    env.reset()
    live = []
    for y in range(step // 2, 64, step):
        for x in range(step // 2, 64, step):
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


def test_pairs(env, rows: list[dict], samples: int = 3) -> list[dict]:
    """Look for drag-and-drop by holding a source and sweeping for destinations.

    This is the test that cracked `sb26`, and it has to be done in this order. A
    destination is invisible to a solo-click sweep: clicking an empty tray slot changes
    nothing at all, so it never shows up as a live cell. It only responds once something
    is selected. So: pick up a source, then sweep the board again and see what answers.
    """
    findings = []
    if not rows:
        return findings

    # Baseline: which cells respond to a bare click, holding nothing.
    env.reset()
    solo: dict[tuple[int, int], int] = {}
    for y in range(2, 64, 4):
        for x in range(2, 64, 4):
            before = env.grid().copy()
            env.click(x, y)
            solo[(x, y)] = cells_changed(before, env.grid())

    source_row = max(rows, key=lambda r: r["count"])
    for xa in source_row["xs"][:samples]:
        env.reset()
        env.click(xa, source_row["y"])  # pick up

        for (x, y), solo_cells in solo.items():
            if y == source_row["y"]:
                continue
            before = env.grid().copy()
            env.click(x, y)
            paired = cells_changed(before, env.grid())
            if paired > solo_cells + 8:
                findings.append(
                    {
                        "from": {"x": xa, "y": source_row["y"]},
                        "to": {"x": x, "y": y},
                        "solo_cells": solo_cells,
                        "paired_cells": paired,
                        "bands": regions_changed(before, env.grid()),
                    }
                )
                return findings
            env.reset()
            env.click(xa, source_row["y"])  # re-arm for the next candidate
    return findings


def probe(env, click_step: int = 4) -> dict:
    """Full mechanical characterisation. Costs actions, costs no tokens."""
    actions = probe_actions(env)
    live = sweep_clicks(env, click_step)
    rows = cluster_targets(live)
    pairs = test_pairs(env, rows) if rows else []
    env.reset()
    return {
        "actions": actions,
        "click_rows": rows,
        "drag_and_drop": pairs,
        "kills_you": any(a["deaths"] for a in actions.values()),
        "actions_spent_probing": env.spent,
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
