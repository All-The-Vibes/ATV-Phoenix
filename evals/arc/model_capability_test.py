"""Can gpt-5.6-sol derive the game's rule, given the same evidence, outside our harness?

The claim under test is not "is Sol a good model". It is narrower and decidable: our ARC
agent wrote a hardcoded lookup table instead of a rule, and degraded 9 -> 16 -> 38 -> 126
actions across levels. If that is a model ceiling, Sol should also fail to induce the rule
when handed the evidence directly. If it is a harness failure, Sol should induce it fine.

Design: a held-out generalisation test. Show Sol the parsed board and the correct
placement order for levels 1-4. Ask it to state the general rule, then apply that rule to
levels 5 and 6, which it has never seen. Grade against ground truth from frames.py.

Nothing here is the agent. No turn budget, no image, no action costs, no reward for a
cheap answer. Just the model, the evidence, and the question.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, ".")

from evals.arc.frames import parse as frame_parse  # noqa: E402
from evals.arc.frames import plan as frame_plan  # noqa: E402
from evals.arc.policies import CLICK_ACTION  # noqa: E402

ENDPOINT = os.environ.get(
    "AOAI_ENDPOINT", "https://ai-shyamsridhar-2008.cognitiveservices.azure.com/"
)
DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-5.6-sol")
COMMIT = 5


def grid_of(frame):
    arr = np.array(frame.frame, dtype=np.int16)
    return arr[0] if arr.ndim == 3 else arr


def describe(layout) -> str:
    """The board as the agent itself would see it via layout(): shape only."""
    def brief(items):
        return [
            {"colour": o["colour"], "cx": o["cx"], "cy": o["cy"],
             "w": o["x1"] - o["x0"] + 1, "h": o["y1"] - o["y0"] + 1}
            for o in items
        ]

    return json.dumps(
        {
            "clues": brief(sorted(layout["clues"], key=lambda o: o["cx"])),
            "tray": brief(sorted(layout["tray"], key=lambda o: o["cx"])),
            "pads": brief(sorted(layout["pads"], key=lambda o: (o["cy"], o["cx"]))),
            "frames": brief(sorted(layout["frames"], key=lambda o: (o["cy"], o["cx"]))),
        },
        indent=1,
    )


def collect(levels=6):
    """Walk the game with the known-good solver, recording evidence per level.

    This mirrors `frame_play.main` exactly, including the two details that make it work:
    the tray is a consumable pool (from level 5 it holds duplicate colours, and a
    colour->position dict silently drops one), and a cleared level needs `press(7)` to
    settle the stale frame before the next board parses correctly.
    """
    import arc_agi

    from evals.arc.codeact_agent import Env, LevelCleared

    arc = arc_agi.Arcade()
    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    records = []
    while env.levels() < levels:
        layout = frame_parse(env.grid())
        order = frame_plan(env.grid())
        if not layout or not order:
            break
        records.append({
            "level": env.levels() + 1,
            "board": describe(layout),
            "order": [(c, list(pad)) for c, pad in order],
        })
        pool = list(layout["tray"])
        try:
            for colour, pad in order:
                src = next((t for t in pool if t["colour"] == colour), None)
                if src is None:
                    return records
                pool.remove(src)
                env.click(src["cx"], src["cy"])
                env.click(*pad)
            env.press(COMMIT)
        except LevelCleared:
            try:
                env.press(7)
            except LevelCleared:
                pass
            continue
        break
    return records


def client():
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    from evals.arc import aad

    provider = get_bearer_token_provider(aad.credential(), aad.SCOPE)
    return AzureOpenAI(azure_endpoint=ENDPOINT, azure_ad_token_provider=provider,
                       api_version="2024-12-01-preview")


PROMPT = """You are shown a puzzle game's boards, parsed by shape alone. No colour or row
position is hardcoded for you.

Each board has:
  clues  - small blocks in a row at the top, in left-to-right order
  tray   - the pieces available to place, at the bottom
  pads   - the empty destination slots
  frames - box outlines that group things

For each SOLVED example you also get `order`: the correct sequence of (colour, (x, y))
placements that cleared that level.

Your task has two parts.

PART 1. State the general RULE that turns clues + frames + pads into the correct order.
Be precise. The rule must work on a board you have not seen, where the rows, colours and
counts are all different.

PART 2. Apply your rule to the UNSOLVED boards and give the order for each.

Reply as JSON only:
{"rule": "<your rule in prose>", "predictions": {"5": [[colour,[x,y]], ...], "6": [...]}}
"""


def main() -> int:
    records = collect(6)
    print(f"collected {len(records)} levels of evidence")
    if len(records) < 6:
        print("could not collect 6 levels; aborting")
        return 1

    shown = records[:4]
    held_out = records[4:]

    parts = ["SOLVED EXAMPLES:\n"]
    for r in shown:
        parts.append(f"--- level {r['level']} board ---\n{r['board']}\n"
                     f"correct order: {json.dumps(r['order'])}\n")
    parts.append("\nUNSOLVED BOARDS (predict the order for these):\n")
    for r in held_out:
        parts.append(f"--- level {r['level']} board ---\n{r['board']}\n")

    api = client()
    reply = api.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": "\n".join(parts)}],
        max_completion_tokens=16000,
        seed=42,
    )
    text = reply.choices[0].message.content or ""
    print(f"\ntokens: {reply.usage.total_tokens:,}\n")

    start, end = text.find("{"), text.rfind("}")
    try:
        answer = json.loads(text[start:end + 1])
    except Exception:
        print("could not parse reply:\n", text[:1500])
        return 1

    print("RULE Sol induced:\n ", answer.get("rule", "(none)")[:1200], "\n")

    for r in held_out:
        got = answer.get("predictions", {}).get(str(r["level"]))
        want = r["order"]
        if got is None:
            print(f"level {r['level']}: no prediction")
            continue
        norm = [(int(c), (int(xy[0]), int(xy[1]))) for c, xy in got]
        ok = norm == [(int(c), (int(x), int(y))) for c, (x, y) in want]
        print(f"level {r['level']}: {'CORRECT' if ok else 'wrong'}")
        if not ok:
            print(f"  predicted {norm}")
            print(f"  truth     {[(c, tuple(xy)) for c, xy in want]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
