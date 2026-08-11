# ARC mission briefing

Read this file in full before you touch anything. It is the complete context for the
goal you were given. Every fact here was measured, not assumed.

**This file is about ONE game, sb26, and that game is finished 8/8. The benchmark is 25
games and 183 levels, and the target to beat is Prime Agent at 95.5% RHAE. That is
`CORPUS_MISSION.md`, and it is the live mission. Read this one for how the harness was
built and what it cost; read that one for what to do next.**

## The mission

Phoenix + gpt-5.6-sol beats ARC-AGI-3 on game sb26, all 8 levels.

**Status: DONE. 8/8, twice, on scorable runs starting at level 1.** Best run scored
RHAE 71.48% in 245 actions with ZERO deaths, against a 213-action human baseline
(`eval/arc-results/full-variant-d.json`). The other is `full-variant-b.json`, 8/8 at
56.16%. Both carry `"scorable": true` and `"start_level": 1`.

It is 2 of 3, not 3 of 3. The miss reached 7/8 and was cut off by the TURN budget with
its action budget largely unspent, having burned 14 turns on level 3. Turns are a
harness artifact; ARC charges actions. Run with `--max-turns 75 --patience 75`.

Phoenix is **in the agent loop**, not merely scoring afterwards:
`evals/arc/codeact_agent.py` imports `PhoenixLoop` from `evals/arc/phoenix_loop.py` and
injects `sense`/`accept` as REPL tools. Measured on the 8/8 run: `sense()` on all 29
turns, `propose()` on 28 of 29. Honest caveat: `phoenix_proven` is `[]` in both runs
because the agent never called `accept()` to promote a sensed belief. The gate runs;
nothing is being certified by it. That is the next thing worth fixing.

## First task: fix the gate, make it stricter

`evals/arc/gate_sb26.py` currently passes at RHAE >= 3.0%. That is wrong: a perfect
level 1 alone scores 3.1944% (per-level score caps at 1.15, game weight sum is 36), so
the gate can be passed without ever reaching level 2, which was its whole purpose.

Add a hard condition: `levels_completed >= 2`. Never weaken the gate, only strengthen it.

## How to run and inspect

    # A scorable run. Turns and patience are set high on purpose: they are harness
    # artifacts, and every earlier run that stopped short was cut by one of them while
    # its ACTION budget -- the thing ARC actually charges -- was still unspent.
    python -m evals.arc.codeact_agent --games sb26 --max-turns 75 --patience 75 \
        --out eval\arc-results\run.json --trace eval\arc-results\trace-run.jsonl

    # The three checks below cost NO API spend and no model calls. Run them before
    # paying for an agent run, and after any change to frames.py or codeact_agent.py.
    python -m evals.arc.clue_structure_check   # clue shape, all 8 levels
    python -m evals.arc.executor_check         # swaps, costs, hollow reads
    python -m evals.arc.variant_probe          # solid/hollow is load-bearing on level 8

    # Score a result against the official human baselines.
    python -c "import json; from evals.arc.rhae import score_run, load_baselines; \
        print(json.dumps(score_run(json.load(open('eval/arc-results/run.json'))['runs'], \
        load_baselines()), indent=2))"

    python evals\arc\show_trace.py eval\arc-results\trace-run.jsonl 5,8,10,12

`evals/arc/level_jump.py` starts a session on any level for HARNESS debugging only. A
jumped run reports `levels_completed` of 0 for the levels it skipped and marks itself
`"scorable": false`; no number from one is a result. Use it to ask "does the harness read
this board honestly", never "what is my score".

Each agent run costs 10-25 minutes of real API spend. One at a time. Score every one.

## Mechanically verified facts about sb26

I probed the engine directly. These are true:

* **Action 5 is COMMIT.** Placing pieces never clears a level by itself. I placed all
  four colours in the correct target order and `levels_completed` stayed 0. A single
  `press(5)` took it to 1.
* Level 1 solves in **9 actions** (8 clicks + 1 commit) against a human baseline of 18.
* Click a palette block to pick a colour up, click a destination slot to drop it. Two
  actions per placement.
* **Row indices move between levels.** Level 1: targets row 1, slots row 29, palette
  row 60. Level 2: slots row 58, palette elsewhere, and colours appear that do not exist
  on level 1. Any parser with hardcoded rows works exactly once and then reads garbage.
  That is the precise cause of the observed `verification mismatch; no action`.
* `evals/arc/sb26_solver.py` holds working helpers (`blocks`, `centres`,
  `find_geometry`, `solve`). Its level-1 path clears in 9 actions. Its level-2 geometry
  detection is **wrong**: it mistakes already-placed pieces for a palette. Fix it.

## Hard constraint: do not game the benchmark

Do **not** hardcode "action 5 is commit" or any sb26 row index into the agent's prompt.
That is a lookup table for one game and scores zero on the other 24. The agent has to
*discover* these facts. What you may build is a general **discovery procedure** that
would find them in any game.

## The diagnosed root cause

From real traces: the agent never runs a cheap experiment. It leaps to a confident
theory and then defends it with thousands of actions, or it freezes.

* Turn 8: theory "action 5 advances a timer" -> pressed it **56 times** -> died. One
  press would have disproved it.
* Turn 10: theory "level 2 is about piece ORDER" -> **2,075 actions in a single turn**
  permuting 22 routes.
* Turn 12: **0 actions**, pure analysis, no contact with the environment.

It never spends 5 actions to find out it is wrong. Fix that. A discovery phase that
presses each available action once and diffs the grid costs about 10 actions and would
have found the commit action immediately.

## Prime Agent architecture, worth borrowing

1. **RLM**: context is a variable; a persistent REPL is the only tool; sub-agent
   delegation happens as function calls inside the REPL.
2. **Continual Harness**: the harness's own state (prompts, skills, memory, sub-agents)
   is CRUD-able by the agent from its own trajectory. We have create and read but **no
   delete**. Nothing retires a stale fact or invalidates a helper when the level changes.

## Phoenix, which you must wire in

Read the files before wiring. Adapt the shapes honestly if they do not fit; never fake
a call.

* `phoenix_learn.gate.decide(gen0_priv_acc=, sel_priv_acc=, sel_priv_correct=,
  gen0_priv_correct=, trans=, private_n=, gaming_hits=)` returns `ADOPT_ELIGIBLE`,
  `REJECT`, `REJECT_GAMING_DETECTED` or `EXPERIMENTAL_SMOKE_TEST`. Constants
  `ADOPT_MARGIN`, `ADOPT_MIN_N`, `ADOPT_MIN_NET` live in that file. Use it so no change
  is adopted on one lucky run.
* `phoenix_learn.optimize.optimize(rows, max_gen=, call_fn=, grade_fn=, edit_fn=,
  lr_budget=, ...)` is a reflective propose -> select -> measure loop over a text target
  with bounded edits. Use it to evolve the discovery procedure from measured outcomes.
* `phoenix_learn.optimize.apply_edits(target, edits, lr_budget=)` applies bounded edits
  and fails closed.

## Determinism, verified empirically

gpt-5.6-sol **rejects** `temperature=0` and `top_p` (HTTP 400, only the default 1 is
supported). But `seed` **is** honoured and produces byte-identical output.
`arc_agi.Arcade.make()` defaults to `seed=0`, so the environment is already
deterministic. Pass a seed to `client.chat.completions.create` in
`codeact_agent.play()` to make runs reproducible, and vary it deliberately for N samples.

## Measured history

| config | level-1 actions | total | RHAE |
|---|---|---|---|
| baseline | - | 50 | 0.36% |
| trajectory memory | - | 189 | 0.025% |
| boundary fix | 69 | 203 | 0.19% |
| boundary fix | 17 | 76 | 3.11% |
| act-pressure prompt | 224 | 1227 (13 deaths) | 0.018% REVERTED, do not retry |
| boundary fix | 83 | 325 | 0.13% |
| mechanics replay | 16 | 4244 | 3.19% |
| mechanics replay | 9 | 159 | - |
| Phoenix in the loop -> **4/8** | - | - | 20.28% |
| clue grid + hollow reads -> **7/8** | 9 | 325 (0 deaths) | - |
| piece variants -> **8/8** | 9 | 665 (3 deaths) | **56.16%** |
| piece variants -> **8/8** | 9 | **245 (0 deaths)** | **71.48%** |

The same config produced level-1 counts of 69, 17 and 83. One green run is never proof.
Use seeds and N >= 3. The 8/8 result itself is 2 of 3 runs, and it is reported that way.

## What finally unblocked levels 7 and 8

None of it was reasoning. Three harness defects made the answer unseeable, unsayable and
unlearnable. Each is now held by a check that costs no API spend:

1. **Clue geometry was thrown away before the agent saw it.** `_clue_structure` took a
   flat colour list, so level 8's twelve rings -- drawn 2x6, each column restated in both
   rows -- read as an undifferentiated rank of twelve. The agent fused that doubling with
   the tray's and searched a rank of eight it had invented: 228 actions, nine turns,
   nothing learned. `frames._collapse_clue_rows` now reports `[8,11,12,9,14,15]` plus the
   drawn shape. Held by `clue_structure_check.py`, which since this work checks all eight
   levels by jumping, not just the six the planner can reach.

2. **Two pieces of one colour were indistinguishable, and the answer needed them to be.**
   Level 8's tray holds two 8s and two 9s where one of each pair is SOLID and one HOLLOW,
   and they are not interchangeable. Measured: the identical winning colour map was
   submitted and refused twice in one run and cleared the level in another; of the four
   solid/hollow choices on that one map, exactly one wins. `try_assignment` mapped
   colour->pad, so the agent could not state the answer -- and `_as_pairs` coerced with
   `int`, so refusing one variant marked all four refuted, making the ledger rule out the
   truth. Now `seated_variants()`/`loose_variants()` report `(colour, hollow)` free, a
   target may be qualified `(colour, "hollow"|"solid")`, and hollow pieces are lifted by a
   ring pixel rather than their hole. Held by `variant_probe.py`, which proves the right
   qualifier clears the level AND the wrong one still loses.

3. **`parse()` crashed on the blank end-of-game board**, turning finishing the game into a
   traceback on the turn that finished it. It returns None now.

The winning turn wrote `(c, "hollow")` candidates and landed on solid-8 + hollow-9 on the
top row -- exactly what the offline probe predicted. The hollow piece is the LINK to the
other frame; that is the game's grammar, and the agent has to derive it each run.

**Do not write that rule into `mechanics.json`.** It is the answer, not a mechanic, and
baking it in contaminates every later run. The notes carry only mechanics: that hollow
pieces exist, are distinguishable, and must be lifted by their ring.

## Already done, do not redo

Trajectory memory across turns; `LevelCleared` raised on `levels_completed` increment;
per-level action attribution; `StallDetected` at 40 inert actions; WIN no longer resets;
the `alive()` bug in `press()`; `begin_turn()` actually called; SkillLibrary mechanics
replay.

## Rules

The deployment `gpt-5.6-sol` is fixed; never change it. Never weaken `gate_sb26.py`.
Judge by measurement only. Revert anything that lowers the score and say so plainly.

Report at the end: what you changed, where Phoenix is called from, every run with its
levels and RHAE, and the final gate state.
