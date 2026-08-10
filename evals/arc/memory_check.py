"""Can the agent see its own work on a long level? Offline, zero API spend.

The measured defect this exists to prevent. `prune` caps the resent trajectory by
character count; at the 5,092 characters a turn actually costs, that is about 22 turns.
A fair run spent 45 turns on level 7. For the whole second half of that level the agent
could not see the first half, and it showed: three consecutive turns of one run proposed
assignments that came straight back from `refuted()` as already played, and the run
before it cycled the same shapes.

Three things were wrong at once, and all three are checked here:

  * the refuted ledger reported a COUNT, not the assignments. A number is not a memory,
    so nothing in the prompt could stop a theory being re-derived once it scrolled out.
  * notes were the last 25 of the RUN, so a long level's early conclusions were evicted
    by its own later ones -- precisely when the trajectory could no longer reach them.
  * image data URLs were charged against the same character budget as reasoning, so a
    kept board cost several turns of history for nothing.

Every check below fails on the parent commit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.codeact_agent import prune  # noqa: E402
from evals.arc.rule_gate import RuleGate  # noqa: E402


def fake_attempt(colours, pads):
    return [(c, p) for c, p in zip(colours, pads)]


def main() -> int:
    ok = True

    # ── the ledger must state the assignments, not just how many there were ──────────
    pads = [(25, 16), (31, 16), (37, 16), (25, 29), (31, 29),
            (37, 29), (25, 42), (37, 42)]
    gate = RuleGate()
    tried = [
        [8, 9, 14, 9, 14, 8, 14, 9],
        [8, 9, 14, 14, 9, 8, 9, 14],
        [9, 8, 14, 9, 14, 8, 14, 9],
        [8, 14, 9, 9, 14, 8, 14, 9],
    ]
    for colours in tried:
        gate.refute(fake_attempt(colours, pads))

    table = gate.refuted_table()
    good = len(table) == len(tried) + 1  # a header plus one line per attempt
    print(f"{'PASS' if good else 'FAIL'}  the ledger lists every refuted assignment "
          f"({len(table) - 1} lines for {len(tried)} attempts)")
    ok = ok and good

    body = "\n".join(table)
    good = all(str(c) in body for c in (8, 9, 14)) and "pad order" in body
    print(f"{'PASS' if good else 'FAIL'}  it states colours against a stated pad order")
    ok = ok and good

    summary = gate.summary()
    good = all(line.strip() in summary for line in table)
    print(f"{'PASS' if good else 'FAIL'}  and the table reaches the prompt via summary()")
    ok = ok and good

    # Compact enough to be re-sent every turn: that is the whole point of it surviving
    # eviction. Eighty attempts must cost less than one turn of trajectory (~5,000 chars).
    big = RuleGate()
    for i in range(80):
        big.refute(fake_attempt([(i + j) % 16 for j in range(8)], pads))
    cost = len("\n".join(big.refuted_table()))
    good = cost < 5000
    print(f"{'PASS' if good else 'FAIL'}  80 refuted attempts cost {cost} chars "
          f"(< 5000, one turn of trajectory)")
    ok = ok and good

    # ── images must not evict reasoning ──────────────────────────────────────────────
    #
    # Built as a real trajectory alternates -- user turn, assistant reply -- because a
    # run of same-role messages is not what `prune` ever sees, and a leading assistant
    # message is legitimately dropped by the rule below it.
    def trajectory(turns, chars, with_image_on_last=False):
        out = []
        for i in range(turns):
            parts = [{"type": "text", "text": f"board {i} " + "b" * chars}]
            if with_image_on_last and i == turns - 1:
                parts.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + "A" * 60000}})
            out.append({"role": "user", "content": parts})
            out.append({"role": "assistant", "content": f"theory {i} " + "t" * chars})
        return out

    with_image = prune(trajectory(10, 4000, with_image_on_last=True), budget=120_000)
    without = prune(trajectory(10, 4000), budget=120_000)
    good = len(with_image) == len(without)
    print(f"{'PASS' if good else 'FAIL'}  a 60,000-char image does not evict reasoning "
          f"({len(with_image)} messages kept with it, {len(without)} without)")
    ok = ok and good

    # ── and the window must reach across a long level ────────────────────────────────
    long_level = prune(trajectory(45, 2500), budget=120_000)
    print(f"        (for reference: {len(long_level) // 2} of 45 turns of raw trajectory "
          f"survive; the ledger and notes are what cover the rest)")

    # ── one assignment, two shapes, one answer ───────────────────────────────────────
    #
    # `try_assignment` accepts a list of (colour, (x, y)) pairs OR a {(x, y): colour}
    # dict. `refuted` accepted only the first and raised
    # `TypeError: 'int' object is not subscriptable` on the second. Measured on a
    # level-7 debug session, an agent that had just been handed that flexibility used the
    # dict form and lost a turn to a crash inside the harness. Accepting a shape in one
    # function and crashing on it in the next is the harness's bug, not the caller's.
    from evals.arc.codeact_agent import _as_pairs

    as_pairs = fake_attempt(tried[0], pads)
    as_dict = {p: c for c, p in as_pairs}
    good = sorted(_as_pairs(as_pairs)) == sorted(_as_pairs(as_dict))
    print(f"{'PASS' if good else 'FAIL'}  both assignment shapes normalise to the same "
          f"thing")
    ok = ok and good

    good = gate.already_refuted(_as_pairs(as_dict))
    print(f"{'PASS' if good else 'FAIL'}  an assignment refuted as a list is recognised "
          f"when offered as a dict")
    ok = ok and good

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())