"""Does the trajectory stay inside the context window? Offline, zero API spend.

A measured 6/8 run died at turn 18 of 80 with 7,700 of 8,000 actions unspent: `prune` kept
every turn's text forever, the trajectory outgrew the context window, and every later model
call failed behind a silent `continue`. This pins the cap, and pins that what survives is
still a well-formed conversation.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.codeact_agent import prune  # noqa: E402

# Read the cap from the function that owns it rather than restating it. This constant
# was hard-coded to 120_000, the budget was deliberately raised to 480_000 with the
# reasoning recorded in prune's docstring (the smaller cap cost a run its own memory
# after ~20 turns while games run 130-190 turns), and the check was not updated. It then
# reported RED for a change that was correct, which is a check that costs attention and
# buys nothing -- the same failure mode as a check that never fails, pointed the other
# way. Derived from the signature, it cannot go stale again.
BUDGET = inspect.signature(prune).parameters["budget"].default


def turn(n, with_image=True):
    """One user turn the size the real ones are: a board dump plus a data URL."""
    parts = [{"type": "text", "text": f"turn {n} board text " + "x" * 6000}]
    if with_image:
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                                                + "A" * 12000}})
    return [
        {"role": "user", "content": parts},
        {"role": "assistant", "content": f"turn {n} reasoning " + "y" * 4000},
    ]


def size(messages):
    """Every character that will be sent, images included."""
    total = 0
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            total += sum(len(p.get("text", ""))
                         or len(p.get("image_url", {}).get("url", "")) for p in c)
        else:
            total += len(c or "")
    return total


def text_size(messages):
    """Only what the budget governs.

    `prune` charges TEXT against the budget and deliberately excludes images, because a
    base64 board is useless to a model that is being shown the current board anyway, and
    charging it evicted several turns of the agent's reasoning -- measured at the cost of
    a level. This check kept counting image bytes against the cap, so it reported the
    pruner 15,783 chars over budget when the pruner was doing exactly what it was told.

    Images are still bounded, by the separate "at most 2 boards carry an image" check.
    Nothing is hidden: the total including images is printed either way.
    """
    total = 0
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            total += sum(len(p.get("text", "")) for p in c)
        else:
            total += len(c or "")
    return total


def images(messages):
    return sum(1 for m in messages if isinstance(m["content"], list)
               for p in m["content"] if p.get("type") == "image_url")


def main() -> int:
    ok = True

    history = []
    for n in range(80):
        history += turn(n)

    raw = size(history)
    kept = prune(history)
    got = size(kept)

    print(f"80 turns raw            : {raw:,} chars")
    print(f"after prune             : {got:,} chars ({len(kept)} messages)")
    text = text_size(kept)
    print(f"  of which text          : {text:,} chars  (the part the budget governs)")
    print(f"  of which images        : {got - text:,} chars  (excluded by design)")

    under = text <= BUDGET
    print(f"{'PASS' if under else 'FAIL'}  the trajectory is capped at {BUDGET:,}")
    ok = ok and under

    grew = raw > BUDGET
    print(f"{'PASS' if grew else 'FAIL'}  the bug was real (unpruned trajectory "
          f"is {raw // BUDGET}x the cap)")
    ok = ok and grew

    imgs = images(kept)
    print(f"{'PASS' if imgs <= 2 else 'FAIL'}  at most 2 boards carry an image ({imgs})")
    ok = ok and imgs <= 2

    recent = any("turn 79" in str(m["content"]) for m in kept)
    print(f"{'PASS' if recent else 'FAIL'}  the most recent turn survives")
    ok = ok and recent

    starts_user = bool(kept) and kept[0]["role"] == "user"
    print(f"{'PASS' if starts_user else 'FAIL'}  what survives starts on a user turn")
    ok = ok and starts_user

    # A short run must not be trimmed at all -- the cap is a ceiling, not a policy.
    short = []
    for n in range(4):
        short += turn(n)
    kept_short = prune(short)
    intact = len(kept_short) == len(short)
    print(f"{'PASS' if intact else 'FAIL'}  a short run is left intact "
          f"({len(kept_short)}/{len(short)} messages)")
    ok = ok and intact

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
