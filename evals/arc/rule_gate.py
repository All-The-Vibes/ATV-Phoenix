"""Hold an agent's rule to a board it did not write the rule for.

Measured on sb26: the agent cleared level 2 by writing this, and was rewarded for it.

    expected_pads = {(22, 22), (28, 22), (40, 22), (22, 36), ...}
    assignment = [(12, (22, 22)), (15, (28, 22)), (6, (40, 22)), ...]

That is a lookup table for one board. It passes every test the harness had, because the
only test was "did the level clear". It is worth exactly nothing on the next board, which
is why per-level cost went 9 -> 16 -> 38 -> 126 actions and level 5 never fell.

`phoenix_learn/split.py` already states the principle for prompts: a candidate that
"embeds a held-out task ... verbatim is memorizing the test rather than generalizing, and
is rejected". This applies the same standard to the code the agent writes about a world.

The test is free. Every level the agent has already cleared is kept with the board as it
looked and the placement order that worked. A proposed rule is replayed against all of
them, in memory, costing zero actions. A rule that reproduces only the board in front of
it is a table, and is refused with the evidence of which levels it failed.

Held-out validation is what makes the deliverable a *rule*. Without it the cheapest way
to clear a board is to memorise it, and the agent was rationally doing exactly that.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable


def placements_from_clicks(log, layout) -> list:
    """The assignment that was on the board last, or nothing. See `rounds_from_clicks`."""
    rounds = rounds_from_clicks(log, layout)
    return rounds[-1] if rounds else []


def rounds_from_clicks(log, layout) -> list:
    """Every complete assignment the click log contains, oldest first.

    Reconstructing the (colour, pad) assignments the agent played, from clicks alone, so
    it stays free to write whatever code it likes rather than calling a placement API.
    Four things make this harder than reading the log in pairs, and all four were measured
    rather than imagined.

    First, not every click is part of a placement. The agent probes empty squares,
    misclicks, and looks around before touching anything. Reading `log[0]` as a pick-up
    and `log[1]` as a drop means one stray click shifts every placement after it by one.

    Second, a level is usually cleared on the second or third attempt, and the log spans
    all of them. Taking the FIRST complete set banks the attempt that failed and labels it
    the solution.

    Third, pieces are identified by POSITION, not by the pixel colour under the click.
    From level 4 the game draws some pieces hollow, and clicking the centre of the level-4
    c14 square reads the colour of the hole. Trusting that pixel dropped the level-4
    assignment on the floor.

    Fourth, from level 5 the tray holds DUPLICATES -- two c8s and two c9s on level 5,
    three pairs on level 6 -- so "have I seen this colour already" cannot mark the end of
    an attempt. Stock is counted against the tray instead.

    Every complete attempt is returned, not just the winning one, because the ones that
    FAILED are evidence too: they are the only thing that can tell apart two rules the
    solved levels both accept.
    """
    pads = layout.get("pads") or []
    tray = layout.get("tray") or []
    if not pads or not tray:
        return []

    def box_at(blobs, x, y):
        for b in blobs:
            if b["x0"] <= x <= b["x1"] and b["y0"] <= y <= b["y1"]:
                return b
        return None

    def pad_at(x, y):
        b = box_at(pads, x, y)
        return None if b is None else (int(b["cx"]), int(b["cy"]))

    wanted = sorted(int(t["colour"]) for t in tray)
    stock = Counter(wanted)

    def piece_at(x, y, colour):
        b = box_at(tray, x, y)
        if b is not None:
            return int(b["colour"])
        # Fallback for a piece the parse missed: the pixel, if it names a real piece.
        return colour if colour in stock else None

    rounds, current, holding = [], [], None

    def begin(colour):
        """Start holding `colour`, opening a new round if the tray is out of that colour."""
        nonlocal current
        if Counter(c for c, _ in current)[colour] >= stock[colour]:
            rounds.append(current)
            current = []
        return colour

    for x, y, colour in log:
        x, y, colour = int(x), int(y), int(colour)
        if holding is None:
            piece = piece_at(x, y, colour)
            if piece is not None:
                holding = begin(piece)
            continue
        pad = pad_at(x, y)
        if pad is not None:
            current.append((holding, pad))
            holding = None
            continue
        piece = piece_at(x, y, colour)
        if piece is not None:
            # Clicking a second piece while holding one means the first was put back or
            # swapped, not placed. Carrying it forward would drop it on whichever pad
            # came next and attribute a placement the agent never made.
            holding = begin(piece)
    rounds.append(current)

    return [r for r in rounds if sorted(c for c, _ in r) == wanted]


@dataclass
class SolvedBoard:
    """One level the agent has cleared, kept so a later rule can be tested on it."""

    level: int
    layout: dict
    order: list

    def matches(self, produced) -> bool:
        """Judge a candidate by the standard the BOARD uses: the assignment, not the path.

        Measured offline: a winning assignment replayed with its placement sequence
        shuffled still clears -- three shuffles each on levels 3, 4 and 5, nine for nine.
        So a rule that puts every colour on the right pad is correct even if it walks the
        pads in a different order, and comparing sequences refuses it anyway. That refusal
        is worse than useless: it is the gate telling the agent its correct rule is wrong,
        with a counterexample that is really only a difference in traversal.
        """
        if produced is None:
            return False
        try:
            got = sorted((int(c), (int(p[0]), int(p[1]))) for c, p in produced)
        except (TypeError, ValueError):
            return False
        want = sorted((int(c), (int(p[0]), int(p[1]))) for c, p in self.order)
        return got == want


@dataclass
class RuleGate:
    """The agent's deliverable is a rule, and this is what makes that true.

    `remember` records a board once its order is known to have worked. `propose` replays
    a candidate rule over every remembered board and refuses one that only fits the
    latest. Refusal names the levels that failed, so the agent gets a counterexample
    rather than a verdict.
    """

    solved: list[SolvedBoard] = field(default_factory=list)
    accepted: Callable | None = None
    history: list[dict] = field(default_factory=list)
    refuted: list[list] = field(default_factory=list)

    def remember(self, level: int, layout: dict, order: list) -> None:
        if any(b.level == level for b in self.solved):
            return
        self.solved.append(SolvedBoard(level=level, layout=layout, order=list(order)))

    # ---- refuted attempts on the CURRENT level -------------------------------------
    #
    # Passing the held-out test is necessary, not sufficient. Measured on level 5: the
    # agent proposed twelve distinct orders across thirteen turns, every one of them
    # reproduced levels 1-4 and was accepted, and every one of them failed on the board.
    # Levels 1-4 simply do not discriminate between the rule the agent held and the rule
    # level 5 wants, so the gate was confirming a theory the board kept refuting.
    #
    # An attempt that was actually played and did not clear is the one piece of evidence
    # levels 1-4 cannot supply. Recorded here, it costs its 17 actions exactly once: a
    # repeat is refused for free (the agent replayed one order twice), and the constraints
    # every refuted attempt shares are reported back, which is what exposes a fixation the
    # agent cannot see from inside. Of those twelve orders, all twelve interleaved the
    # child row into the parent row; not one tried finishing the parent row first.

    @staticmethod
    def _key(order) -> tuple:
        """Canonical identity of an attempt: WHICH COLOUR ON WHICH PAD, order discarded.

        Measured offline: a winning assignment replayed with its placement sequence
        shuffled still clears, three shuffles each on levels 3, 4 and 5, nine for nine.
        The board scores a mapping, not a path, so two attempts that differ only in the
        order the pieces were dropped are the same answer and the board cannot tell them
        apart. Keying on the sequence would let the agent spend seventeen actions
        re-testing an arrangement it had already been refused.
        """
        return tuple(sorted((int(c), (int(p[0]), int(p[1]))) for c, p in order))

    def refute(self, order) -> bool:
        """Record an assignment that was played on this level and did not clear it."""
        if not order:
            return False
        key = self._key(order)
        if any(self._key(o) == key for o in self.refuted):
            return False
        self.refuted.append(list(order))
        return True

    def already_refuted(self, order) -> bool:
        """Has this assignment already been played and failed? Costs zero actions."""
        if not order:
            return False
        key = self._key(order)
        return any(self._key(o) == key for o in self.refuted)

    def clear_refuted(self) -> None:
        """A new level is a new question; old refutations were about the old board."""
        self.refuted = []

    def shared_constraints(self, limit: int = 8) -> list[str]:
        """What EVERY refuted assignment agreed on, stated as testable restrictions.

        Derived mechanically from the agent's own failures, not from knowledge of the
        game. Two kinds, both about the mapping rather than the traversal order, because
        the order is not what the board scores:

        * a colour that was only ever tried on some of the pads. This is the one that
          matters. Measured on level 5: across nine distinct refused assignments the
          agent put both c9 pieces on a child pad every single time, and the assignment
          that actually clears puts both of them on the PARENT row. The agent could not
          see that from inside because every theory it held implied it.
        * a pad that was handed the same colour every time.

        An earlier version reported pad ORDERINGS. Its most confident findings were
        artefacts of a sequence that does not matter -- a pad always placed first
        trivially precedes every other pad -- and it said nothing about the mapping.
        """
        if len(self.refuted) < 3:
            return []
        maps = [{(int(p[0]), int(p[1])): int(c) for c, p in o} for o in self.refuted]
        pads = sorted(set().union(*(set(m) for m in maps)))

        seen: dict[int, set] = {}
        for m in maps:
            for pad, colour in m.items():
                seen.setdefault(colour, set()).add(pad)

        out = []
        for colour, tried in sorted(seen.items()):
            untried = [p for p in pads if p not in tried]
            if untried:
                out.append(
                    f"colour {colour} was ONLY ever placed on {sorted(tried)} "
                    f"-- never once on {untried}"
                )
        for pad in pads:
            colours = {m.get(pad) for m in maps}
            if len(colours) == 1 and None not in colours:
                out.append(f"pad {pad} was handed colour {colours.pop()} every time")
        return out[:limit]

    def propose(self, rule: Callable) -> dict:
        """Replay `rule` over every solved board. Costs zero game actions."""
        if not callable(rule):
            return {"ok": False, "reason": "propose() takes a function rule(layout)"}

        if not self.solved:
            self.accepted = rule
            verdict = {
                "ok": True,
                "reason": "nothing solved yet, so nothing to generalise over; "
                          "the rule is provisional until a level is cleared",
                "passed": [],
                "failed": [],
            }
            self.history.append(verdict)
            return verdict

        passed, failed = [], []
        for board in self.solved:
            try:
                produced = rule(board.layout)
            except Exception as exc:
                failed.append({"level": board.level, "why": f"{type(exc).__name__}: {exc}"})
                continue
            if board.matches(produced):
                passed.append(board.level)
            else:
                failed.append({
                    "level": board.level,
                    "why": "puts a different colour on at least one pad than the "
                           "assignment that cleared it",
                    "produced": produced if produced is None else list(produced)[:10],
                    "correct": board.order[:10],
                })

        ok = not failed
        if ok:
            self.accepted = rule

        verdict = {
            "ok": ok,
            "passed": passed,
            "failed": failed,
            "reason": (
                f"reproduces every solved level {passed}"
                if ok else
                f"passes {passed} but FAILS {[f['level'] for f in failed]}. A rule that "
                "only fits the board in front of you is a lookup table: it will cost you "
                "the next level and the one after that. Find what the failing boards have "
                "in common with this one and encode THAT."
            ),
        }
        self.history.append(verdict)
        return verdict

    def summary(self) -> str:
        if not self.solved:
            head = "RULE GATE: no solved levels recorded yet."
        else:
            levels = [b.level for b in self.solved]
            if self.accepted is None:
                head = (f"RULE GATE: {len(levels)} solved levels on file {levels}. "
                        "No rule has yet reproduced all of them. propose(fn) to try one.")
            else:
                head = (f"RULE GATE: accepted rule reproduces all solved levels {levels}. "
                        "It will be re-tested against every new level you clear.")
        if not self.refuted:
            return head

        lines = [head, f"REFUTED ON THIS LEVEL: {len(self.refuted)} distinct assignments "
                       "have been played here and did not clear it. Passing the held-out "
                       "test is necessary, not sufficient -- the solved levels cannot "
                       "tell these apart, but the board already has. refuted(order) "
                       "checks a candidate against them for zero actions, and ignores "
                       "the order you place in because the board does too."]
        shared = self.shared_constraints()
        if shared:
            lines.append(
                "Every one of those failed assignments agreed on: "
                + "; ".join(shared)
                + ". The board has refused all of them, so at least one of these is an "
                  "assumption you have never tested rather than something you "
                  "established. Try an assignment that breaks one."
            )
        return "\n".join(lines)
