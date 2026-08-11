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


## Gap 8: correct scoping, ruinous wording -- the agent was told to re-buy its physics

Beliefs are scoped to the level and retired when it advances. That fix was right and is
still in place: without it a level-1 fact stayed marked PROVEN on level 2 and one run
spent a 2,075-action turn defending it against a board where it was false.

The wording around it made the opposite mistake. On su15 the agent was told it had
"retired 59 belief(s) earned on the previous board; they must be re-earned here", and
among those 59 was:

    a black obstacle on a particle's predicted northwest cell reflects that particle

That is not a fact about level 1's layout. It is how the game works, it was true on every
board in the game, and re-earning it is paid for in ACTIONS -- the one quantity RHAE
squares. The run then spent **1,044 of its 1,055 actions on the single level that
followed** and finished 2 of 9.

The gap was that the harness had exactly one kind of memory, so it had to choose between
trusting a dead fact and discarding a live law. It chose discarding, correctly, and then
told the agent to buy the law back at the worst possible exchange rate.

Two memories now, split by "would this still be true if the board were redrawn?":

    note()     -- this obstacle sits at (14,7)      dies at the boundary
    mechanic() -- obstacles reflect particles       survives it

`BeliefStore` gained a `durable` flag so the EVIDENCE crosses with the claim rather than
a bare sentence, and durable is not a promotion to true: a later red still refutes it,
and `keep()` refuses a claim nobody ever observed. The default stays `note()`, because a
forgotten law costs one re-derivation and a wrong law kept forever costs the run --
`unmechanic(n, because=...)` is the escape, and the death prompt now names the mechanics
list first, since those are the only beliefs no level change has ever cleared out.

**The transferable lesson**: scoping a belief and telling the agent what to do about the
scope change are two decisions, and getting the first one right does not make the second
one free.

## Gap 9: the harness ended the run and the artifact called it a capability ceiling

lp85 stopped at 5 of 8 levels having spent **394 actions against a 388-action human
baseline for the whole eight-level game**. It was still solving, at roughly human cost.
What stopped it was `--max-turns 90`.

ARC charges ACTIONS and never turns. A turn cap is purely a harness invention, so a
turn-capped run is the harness choosing the score -- and every unfinished run in the
results directory looked identical whether the agent had run out of ideas, out of action
budget, or out of turns.

Runs now stamp `stopped` as won / patience / action_cap / max_turns, with `turns_used`.
Check that field before reading any unfinished result as a limit of the agent.

## Gap 10: the only free move in the game, documented as the worst one

The API block handed to every agent described the reset primitive in four words:

    reset()             -> restart from level 1.

Both halves are false, and the harness had the evidence to know it. Two counters exist on
the ARC scorecard, `inc_action_count` and `inc_reset_count`, and `update_scorecard`
dispatches between them on the id of the action taken: id 0 is RESET and routes to the
reset counter, ids 1-7 route to the action counter. RHAE divides by the action count.
**A reset does not enter the number the score is computed from.** And every death in this
harness calls the same `_env.reset()` the agent's `reset()` calls -- so if reset restarted
the game, a run that died would reappear on level 1. Across 59 recorded traces the level
count never once fell. It restarts the CURRENT level and keeps every level already
cleared.

So the agent was told that the only free move available to it would throw away the entire
run. It behaved accordingly: **8 of 61 traces ever called `reset()` at all**, and six of
those eight are cd82 -- one of the three games we have beaten. On the other fifty-three
runs the agent paid actions to walk a board backwards by hand, and under a squared
penalty every one of those actions was charged twice.

The correction has to carry the caveat or it replaces one error with another: a reset
buys back the BOARD, never the BUDGET. Actions already spent on the level stay spent and
stay counted. The rule that follows is arithmetic, not judgement -- reset when undoing by
hand would cost more actions than replaying from pristine.

The death message had the same shape of defect and is fixed alongside it. It stated *"The
move-bar ran out"* to every game, including the eight that draw no bar, and advised
calling `clock()`, which on those games honestly returns nothing. It now reports the
measured lifespan, says plainly that the restart was free and the spent actions were not,
and branches on whether this game actually draws a bar.

**The transferable lesson**: an instrument that misdescribes a capability is worse than a
missing one. A missing primitive gets rediscovered; a primitive documented as
catastrophic gets avoided forever, and nothing in the trace ever says why. Pinned by
`python -m evals.arc.reset_check`.

## Gap 11: the rule gate answered green to twenty-four games it had never tested

Phoenix's whole claim is that a check which has never gone red proves nothing. The rule
gate broke that claim in the quietest way available.

`propose(rule)` replays a candidate rule over every level already cleared and refuses one
that only fits the board in front of it. With no solved level on file it returned this:

    {"ok": True, "reason": "nothing solved yet, so nothing to generalise over"}

Solved levels only arrive via `rules.remember(...)`, which the turn loop calls only when
`frames.parse` accepts the board. Parse accepts **one of the 25 public games**. So on the
other twenty-four, `solved` is empty from the first turn to the last, and every rule ever
proposed came back `ok: True` -- forever, having been compared against nothing. It also
installed that untested rule as `accepted`.

Measured across the recorded traces: **55 vacuous greens on cd82 alone**, and not one red
on any non-parsing game. The SYSTEM prompt meanwhile opened with *"YOUR DELIVERABLE IS A
RULE ... It is replayed against every level you have already solved, and refused if it
only fits the board in front of you"* -- three claims, none of them true on 24 games.

An untested verdict is now reported as untested: `tested: 0`, `applies: False`, `ok`
falsy so that `if propose(r)["ok"]` reads "not proven", and a reason that says in the
first four words that this is not a refutation. `accepted` is no longer set by a verdict
that examined no evidence. The prompt now tells the agent to check
`layout()["well_formed"]` FIRST and says plainly that on a game where it is False the
whole formalism is inert -- while keeping the universal half of the lesson, which is that
the deliverable is the reason and never the coordinates.

The live gate is unchanged and still goes both ways, which the check verifies rather than
assumes: a gate that can only refuse is no more honest than one that can only agree.

**The transferable lesson**: "the check passed" and "the check ran" are different facts,
and a gate that does not report the second one will eventually be believed about the
first. Pinned by `python -m evals.arc.rule_gate_honesty_check`.

---

## Gap 12 — the harness could not tell a busy endpoint from a broken agent

**Found:** a four-run batch died. Every member recorded `stopped: "max_turns"` while
sitting at roughly a third of its turn budget.

| run | levels | actions | deaths | turn |
|---|---|---|---|---|
| lp85-b | **7/8** | 454 | 2 | 70 / 160 |
| su15-b | 3/9 | 718 | 15 | 101 / 160 |
| sc25-c | 3/6 | 814 | 18 | 102 / 160 |
| vc33-a | 3/7 | 457 | 6 | 57 / 160 |

Read the scorecards alone and the story is an agent that exhausted its turns and stalled.
The logs say something else entirely, and they say it four times:

```
lp85: three model calls failed in a row; stopping the run rather than
      burning 90 turns in silence
```

The failures were `APITimeoutError`. The retry ladder tested for `"429"` and
`"rate limit"` and nothing else, so a timeout was classified as a genuine defect: it
skipped backoff, went to `call_error`, raised, and burned one of the three strikes that
end a run. Under a saturated endpoint timeouts arrive in bursts, so three strikes came
almost immediately. lp85 was **one level from finishing the game** with ninety turns and
two unspent deaths in hand.

**Two separate lies stacked here, which is why it survived so long.**

The first is classification: congestion arrives under many names — 429, timeout,
connection reset, 500, 503, "overloaded" — and the harness recognised two of them.

The second is the label. `stopped` is initialised to `"max_turns"` and *neither* early-exit
branch overwrote it, so a starved run and an exhausted run produced byte-identical
evidence. Every rate-limited run in our history was mis-filed, and tu93 — killed at turn
**29 of 160** with 280 of 8,000 actions spent — was read as an agent out of ideas.

**Fixed:** congestion is recognised by what it is rather than by one phrasing of it; the
ladder runs 40 attempts instead of 10; and both early exits now name themselves
(`rate_limited`, `model_failures`). Genuine failures — context-length 400s, auth 401s,
missing deployments, attribute errors — still fail fast, because retrying a real bug forty
times only hides it for eighty minutes.

**Pinned by:** `python -m evals.arc.congestion_check`. It lifts the live expression out of
`play()` with `inspect` rather than restating it, because the defect being pinned was a
live expression drifting from the comments around it — a copy in the test would have
stayed green through the whole failure.

**The measurement that made the batch fail in the first place:** process count buys no
throughput. Nine concurrent runs share one tokens-per-minute allowance, so they split the
same quota and add 429 churn on top. Measured: 45–82 rate-limit waits per run, and lp85 at
7/8 spending entire turns at zero actions while it waited. Concurrency is worth having for
wall-clock overlap, not for tokens, and past the endpoint's TPM it is strictly negative.

**The general shape, again.** This is Gap 7 wearing new clothes: an instrument that
answers confidently outside the conditions it was written for. The ladder was sized when
one run had an endpoint to itself, and it kept returning a verdict — "the agent stopped
improving" — long after that assumption stopped holding. The failure mode of this harness
is never silence. It is a confident wrong answer.

---

## Gap 13 — the only memory that outlives a level was reachable only by a run that had already won

`mechanic()` is the one belief that survives a level boundary, and its implementation was
never wrong: it appends on the strength of the call. What was missing is that nothing told
the agent WHEN to call it. So the agent invented a rule, and the rule it invented was
fatal in a specific way.

**Measured across every trace on disk:** 249 writes attempted, **190 of them placed under
`if levels() > start:`**, and **217 placed after a `press()` or `click()`** in the same
turn.

**Gating on a level clear is a deadlock.** On a game you are losing, no turn clears a
level, so no rule is ever kept — and that is precisely the game whose rules you need to
keep. su15 attempted 84 writes, cleared nothing while making them, and stored none. bp35
attempted 17, stored none, and spent the run proposing six mutually contradictory theories
of the same game — "the course auto-scrolls", "a vertically scrolling white corridor", "an
auto-bouncing platform climber" — because it re-derived what the game was every turn and
nothing it concluded outlived the turn that concluded it. Even lp85, running four times
faster than the human baseline, had stored nothing.

**Writing after an action loses the write to the raise.** A death raises at the action
that caused it, so a conclusion written at the bottom of the turn never runs: the lesson
the death just taught is the one lesson never saved.

**Fixed:** both habits are the agent filling a silence in the documentation, so both fixes
are text. The API entry now says to record from the observation — a level clear is not the
evidence for "action 3 moves left"; the movement diff already printed is — and to write
above the actions rather than below them. The death message names the discarded write, but
only when the symptom is present: an empty mechanics list after repeated deaths. Advice
printed on every death is advice learned to skip.

**Pinned by:** `python -m evals.arc.mechanic_check`, which reads the LIVE prompt text
bounded at the next API entry rather than a character radius. Its five original checks
passed green throughout the entire period the feature was dead, because they pin what
happens once the call runs — and the call was never reached. A test can be perfectly
correct about a mechanism nobody can get to.

---

## Gap 14 — the move bar was findable all along; nothing in the harness ever looked

`frames.budget` finds a bar-shaped row unaided — full width, at most two colours, at most
two runs — but a partly-drained bar has two segments, and one frame cannot say which is
the budget that remains. It correctly refuses to guess, and asks the caller to hand back
the colour the row showed while the bar was full.

**The caller is the agent.** So the whole mechanism sat behind the agent's own curiosity,
and on the games that need it most the agent is never curious. Measured on bp35:
thirty-seven turns, sixteen deaths, and **not one call to `clock()` in the entire run**.
Nothing was handed back, nothing was identified, and every death notice told it **"this
game DRAWS NO MOVE BAR"** — while row 63 was draining 63 → 43 → 38 → 29 in the object
dumps the agent had printed itself.

That sentence is the defect. "I could not read this" was rendered as "there is nothing
here to read", and the eight games we had recorded as bar-less were never confirmed to be
bar-less; they were confirmed to have agents who never asked.

**Fixed:** `_learn_bar_direction` runs off the changed-frame branch of `_step` rather than
off `clock()`, because the game this fixes is precisely the one whose agent never calls
`clock()`. A pristine bar is a single full-width run and is unambiguous on sight — bp35
opens exactly that way, so frame one always held the answer. Once drained, two frames
settle it by **conservation**: a bar keeps its width, so a cell leaving one segment
arrives in the other. Two-toned board furniture does not balance, and a row that never
moves is never named — the frozen 18/64 failure `cdd1f2a` fixed for the death path, now
prevented by construction instead of by a cache. Two rows draining at once is refused
rather than resolved by picking one.

**Pinned by:** `python -m evals.arc.barwatch_check`, on bp35's real geometry taken from
its trace, including the refill trap: the bar refills on death and reset, so a comparison
across a rebuild shows the remaining segment growing and names the spent colour as the
budget — a confident reading of exactly the wrong half.

**The shape, a fourth time.** An instrument that is honest about its own uncertainty, and
a harness that translates that honesty into a claim about the world on the agent's behalf.
`budget()` never lied; it returned `confirmed: False`. The death message is what turned
that into "no bar exists". The failure mode of this harness is never silence — it is a
confident wrong answer, and it is usually produced one layer above the component that was
being careful.

---

## Gap 15 — a counter that falls was read as a counter that counts

The SDK's `frame.levels_completed` is **not monotone**. On `s5i5` it oscillates inside a
single level, and the harness gated the level transition on the only rule that looks
obviously safe:

```python
if self._frame.levels_completed > before_levels:   # WRONG
```

Measured on `trace-s5i5-b.jsonl`, a run that cleared **two** levels: the transition fired
**nine** times, carrying level numbers **1, 1, 1, 2, 1, 1, 1, 1, 1**. Reading 1 after
having read 2 is only possible if the counter fell and climbed again.

Three consequences, none of them visible in the scorecard:

1. **Attribution.** The action mark restarted on every false fire, so `level_actions`
   came out as nine entries. `score_run` slices `[:levels_completed]`, so level 2 was
   charged the **last 49** of the **375** actions it actually cost. Under a squared
   penalty that is not a rounding error.
2. **The harness lied to the agent.** Seven of the nine said *"LEVEL 1 CLEARED — the
   board below is a DIFFERENT level"* while the agent was standing on level 3.
3. **Knowledge destroyed on a schedule.** The transition branch wipes level notes,
   retractions, bar colour, pad boxes and tray boxes. Nine wipes for two real boundaries.

**Why every existing check missed it.** `reset_check` watches the trace's per-turn
`levels` field — and that field logs `self.best`, a running maximum. The oscillation
happens *between actions inside one turn*, so a per-turn sample is monotone even while the
counter is not. The instrument was sampling at a resolution coarser than the damage.

**Fixed:** gate on a new high-water mark. A new maximum is the only reading that means *a
level I had never finished before*, which is exactly what RHAE credits — the scorecard
reports `env.best`. It also makes `len(level_actions) == levels_completed` true by
construction, and it charges a level every action spent on it including replays. That is
the honest reading: **a replay buys back the board, never the budget.**

**Pinned by:** `python -m evals.arc.level_monotonic_check` — pins the gate by source
shape, replays the real s5i5 tick sequence through both rules (old: 9 entries; new:
`[107, 375]`), and sweeps disk for the invariant.

**Blast radius, measured:** 4 scorecards (`cd82-d`, `cd82-e`, `tu93-a`, `vc33-a`) and 10
traces recorded a level they had already cleared. Those artifacts cannot be repaired by
re-reading them — the actions were charged to the wrong level before the file was written.
So results now carry `harness: 2`, the invariant binds what this build produces, and older
artifacts are **quarantined by name and counted** rather than silently trusted or silently
excused.

---

## Gap 11 — the lesson a death teaches is the lesson a death destroys

`Died` aborts the agent's cell where it stands. Every statement after the dying action is
skipped — and the statement after a dying action is, reliably, the one recording what
killed it.

`bp35-b` called `mechanic()` **seventeen** times and finished with an **empty** mechanics
list. Swept across all 41 traces on disk: **96** calls to `mechanic`/`note`/`retract` sat
after an action on a turn that died, and every one was lost. The games that die most are
the games that learn least, which is exactly backwards.

**Why the obvious fix is only half a fix.** Reading the writes out of the cell before it
runs recovers only the ones whose arguments are literals: **49 of 96**. The other 47 build
their text from local variables, and they cluster in `r11l` and `su15` — the two
death-heaviest runs in the corpus. A fix that skips the death-heavy games is not a fix for
this defect.

**Fixed:** recover them *afterwards*. The exec namespace outlives the exception with every
pre-action local still bound, so replaying the unreached statement means now what it would
have meant then. Only statements whose calls are **all** ledger calls are replayed —
decided by the shape of the statement, not by a deny-list that would rot — which keeps a
salvage off the board, since after a death the board is pristine and would answer about a
different world. Lines that already wrote are skipped, so a half-executed cell cannot
double-record.

**Pinned by:** `python evals/arc/ledger_salvage_check.py` — five checks, including the
computed-text case a pre-scan cannot reach, and proof that a salvage never reads the
board. Measured with `python evals/arc/ledger_loss_probe.py`.

---

## Gap 16 — eight games were never played, and the standings said they had failed

Twelve games showed **0.00%** and were read as twelve failures. Eight of them
(`wa30 sk48 re86 m0r0 ls20 lf52 g50t dc22`) have **no agent trace on disk at all**.

Their scores all came from one source: `novelty.json`, dated 2026-08-08, carrying
`policy` and `budget_per_game` keys, **0 turns and 0 tokens for every game**. It is a
random-policy sweep. The model was never called.

Nothing in the standings table said so. A zero from a policy baseline and a zero from an
agent that tried and failed print identically, and the difference is the whole strategy:
one is a capability ceiling, the other is an empty chair.

**The shape, again.** Every gap in this file is the same failure — a confident answer
standing in for a missing measurement, produced one layer above the component that was
being careful. `novelty.json` never claimed to be an agent run. The standings table is
what turned "not attempted" into "attempted and scored zero".

**Fixed:** `evals/arc/queue_runner.py` keeps three agents alive until a queue drains,
admitting a game only when fewer than N agents are alive **anywhere on the machine**, so
it cooperates with hand-launched runs instead of doubling the load. Every run gets `--out`
and `--trace`, because a run that dies without either leaves no record it was ever played
— which is how this gap was created in the first place.
