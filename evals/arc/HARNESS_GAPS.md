# Phoenix harness gaps, found by using it on ARC

Round 1 took sb26 from 1/8 levels to 4/8 (RHAE 0.36% -> 20.28%) by wiring Phoenix into
the agent loop. Round 2 took it from 4/8 to **8/8** (RHAE 71.48%, 245 actions, zero
deaths). Both rounds exposed places where Phoenix, **as a harness**, made the integrator
do work Phoenix should have done. Each one below is evidence-backed by something that
actually happened in this repo, not a wish list.

Gaps 1-6 come from round 1. **Gap 7 comes from round 2 and is the most general of them**:
the harness could not express the answer, and recorded that as the answer being wrong.

## Gap 1: the core primitives are Rust-only, so Python agents reimplement them

`src/accept.rs` owns the failure-first rule: `saw_red`, `green_after_red`,
`currently_green` (lines 29-31). It is reachable only over MCP, from an agent's tool
call. A Python process cannot call it.

So `evals/arc/phoenix_loop.py` hand-rolled it: `Belief.failure_first` is a
reimplementation of the same three-state logic in a different language, with its own
subtly different semantics. Two implementations of the honesty core is one too many, and
the Python copy is the one now deciding what the ARC agent believes.

**Fix:** a `phoenix_learn.accept` module that owns failure-first in Python, with the Rust
side calling the same rule or a shared test fixture proving they agree. Any agent written
in Python should `from phoenix_learn.accept import verify_gate`, not rewrite it.

## Gap 2: the adoption gate cannot be used on expensive episodes

`phoenix_learn/gate.py` sets `ADOPT_MIN_N = 20`. One ARC run costs 4-10 minutes of real
API spend, so clearing that bar is 2-3 hours per decision. In practice `decide()` returns
`EXPERIMENTAL_SMOKE_TEST` every single time and gates nothing.

That is not a tuning problem. The gate assumes cheap, numerous, independent trials
(prompt rows). Episodic RL-style tasks have few, expensive, high-variance episodes.

**Fix:** an episodic decision rule alongside the row-based one. With N=3-5 runs it should
compare distributions rather than counts: require the candidate's worst run to beat the
baseline's median (stochastic dominance on the lower tail), which is cheap and honest.
Keep `ADOPT_MIN_N` for row fixtures; do not pretend one rule fits both.

## Gap 3: no cross-episode memory primitive

The skill library that let level 1 fall from 50 actions to 9 lives in
`evals/arc/skills.py`. It is ARC-specific. Phoenix has no general "what did I learn last
run" store, so every new domain rebuilds one.

This is exactly Prime Agent's Continual Harness, and we implement it per-domain instead
of once.

**Fix:** `phoenix_learn.memory` with a typed, gated store: a fact enters only when it
clears the acceptance rule, carries the evidence that admitted it, and is keyed by scope.

## Gap 4: create and read, no delete

Nothing in Phoenix retires a belief. When the ARC level changed, level-1 facts stayed
marked PROVEN and the agent kept applying them to a board where they were false. That is
the measured cause of `verification mismatch; no action` and of the 2,075-action turn.

The D in CRUD is the entire difference between memory and stale memory.

**Fix:** beliefs need a scope and an invalidation trigger. When the scope changes
(new level, new environment, new file), every belief scoped below it drops back to
unproven and must be re-earned. Cheap to implement, and it is the single highest-value
missing piece.

## Gap 5: no environment-characterisation primitive

`evals/arc/` now holds 34 Python files, most of them single-use probes:
`dig_sb26.py`, `look2_sb26.py`, `act2_sb26.py`, `order_sb26.py`, `place2_sb26.py`,
`box_probe.py`, `level4_probe.py`, `probe_level1.py`, `inspect_level.py`. Each one asks a
version of the same question: *what does this action do, and what changed?*

The breakthrough itself came from a discovery procedure that presses each action once and
diffs the state. That is domain-independent and it is not in Phoenix.

**Fix:** `phoenix_learn.discover` — given an action space and a state-snapshot function,
try each action, diff, and return a characterisation. ARC supplies the grid; a shell agent
supplies the filesystem; the procedure is the same.

## Gap 6: the gate assumes determinism it does not have

Phoenix grades pass/fail as if a check is deterministic. On ARC the same config produced
level-1 action counts of 69, 17 and 83. A single green run proved nothing, and we adopted
a change on one anyway before catching it.

Empirically: `gpt-5.6-sol` rejects `temperature=0` and `top_p` (HTTP 400), but honours
`seed` and returns byte-identical output. The environment is already deterministic at
`seed=0`.

**Fix:** make seeds first class. A Phoenix check should record the seed it ran under, and
an adoption decision over a stochastic check should require N distinct seeds. A check that
cannot name its seed should be reported as unreproducible rather than green.

## Gap 7: the harness could not express the answer, and called that a wrong answer

This one cost a level and is the most general lesson here, because nothing about it is
ARC-specific.

`try_assignment` accepted a mapping of **colour -> pad**. On sb26 level 8 the tray holds
two 8s and two 9s where one of each pair is drawn SOLID and the other HOLLOW, and the two
are not interchangeable. So the winning answer is not a colour map at all, and the API the
agent had to speak through could not say it.

What that looked like from inside the loop, measured:

* The exact winning colour arrangement was submitted at turns 35 and 41 of one run and
  rejected both times. The same arrangement cleared the level in another run. A colour map
  cannot be both winning and losing; the harness was hiding the variable that differed.
* `seated()` answered in colours too, so the agent could not even OBSERVE what it had just
  placed. It had no way to notice the two attempts differed.
* Worst, `_as_pairs` coerced every colour with `int()`, so the refutation ledger keyed on
  colour alone. Refusing one of the four solid/hollow variants marked the other three
  tried. **The ledger was ruling out the correct answer**, and the more diligently the
  agent used it, the more certainly it excluded the truth.

The agent looked like it was reasoning badly. It was reasoning correctly against an
instrument that could not represent the answer, could not show the difference, and
recorded a refusal of one thing as a refusal of four.

**The general failure:** when an agent's action space is a lossy projection of the real
state space, every wrong answer is indistinguishable from an unsayable one. A harness owes
the agent three things that are separable and were each broken here:

1. **Observability** -- the agent can read back the full state it acted on, not a summary.
2. **Expressiveness** -- anything the environment distinguishes, the agent can say.
3. **Attribution** -- a refusal is recorded against what was actually tried, at the
   granularity the environment discriminates, never coarser.

Point 3 is the one to watch for. Memoising failures on a lossy key is a silent
correctness bug, not a performance optimisation, and it gets worse the more the agent
trusts it.

**Fix, for Phoenix generally:** a refutation store should key on the full action
description and refuse to collapse it. If the harness cannot tell two actions apart it
must record them as unrefuted rather than as tried, because "I cannot distinguish these"
and "I tried these and they failed" are opposite claims. The same applies to any
`sense`/`accept` ledger keyed on a summarised claim.

**Detection recipe, cheap and offline:** when a hypothesis is refused that you have good
independent reason to believe, enumerate the environment's own distinctions over that
hypothesis and try each. `evals/arc/variant_probe.py` does exactly this in four attempts
and no model calls: it fixed the colour map, varied only solid/hollow, and found that
exactly one of four wins. That single measurement converted "the agent reasons badly on
level 8" into "the interface is lossy", which was a one-hour fix rather than an open
research problem.

## The level-5 blocker: RESOLVED, and what it actually was

Levels 5 through 8 are all cleared now; the game is finished 8/8. The diagnosis above was
half right. Hollow pieces and duplicate colours were indeed the blocker, but not because
the clue row needed a nested reading:

* **Level 5** was a clue-shape problem, fixed by reporting the repeated block.
* **Level 7** was a perception problem: a hollow piece places its HOLE exactly over the
  pad and its ring entirely outside it, so reading the pad's own pixels saw background and
  `seated()` called occupied pads empty. Read over the piece's footprint instead.
* **Level 8** was Gap 7 above: not perception, not reasoning, but expressiveness.

The advice that paid off is worth repeating: `frames.py` can be tested offline against
every level for zero API spend, and `level_jump.py` will put a session on any level for
free. Every fix in this round was found and proven offline before an agent run was paid
for. Do that first, always.
