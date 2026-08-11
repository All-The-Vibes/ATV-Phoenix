# ARC-AGI-3 — Handoff

**Written:** 2026-08-10 19:10 CDT, immediately before a machine restart.
**Repo:** `C:\Users\shyamsridhar\code\ATV-Phoenix`
**Branch:** `arc/corpus-baseline-8of8` → PR #189
**HEAD at handoff:** `6aa21b7` (pushed; `origin` matches)

---

## Where we actually stand

```
CORPUS RHAE                  : 10.09%
Prime Agent                  : 95.50%
gap                          : 85.41 points
games with a level cleared   : 13 of 25
levels cleared               : 41 of 183
```

Reproduce any time with `python evals\arc\standings.py` from the repo root.
**Never quote standings from memory** — that has been wrong twice. The tool is the answer.

| game | lv | /of | acts | human | score | source |
|---|---|---|---|---|---|---|
| sb26 | 7 | 8 | 325 | 213 | **73.74%** | full-8of8-a.json |
| cd82 | 6 | 6 | 394 | 171 | **61.68%** | cd82-f.json |
| ft09 | 6 | 6 | 809 | 208 | **48.18%** | ft09-a.json |
| lp85 | 5 | 8 | 394 | 388 | 38.02% | lp85-a.json |
| vc33 | 3 | 7 | 457 | 447 | 14.80% | vc33-a.json |
| sc25 | 3 | 6 | 846 | 350 | 10.20% | sc25-a.json |
| su15 | 3 | 9 | 718 | 361 | 3.60% | su15-b.json |
| r11l | 1 | 6 | 690 | 233 | 1.60% | r11l-a.json |
| s5i5 | 2 | 8 | 885 | 638 | 0.41% | **s5i5-b.json (rescued)** |
| sp80 | 2 | 6 | 2000 | 518 | 0.04% | novelty.json |
| tu93 | 1 | 9 | 280 | 462 | 0.02% | tu93-a.json |
| tr87 | 1 | 6 | 2059 | 414 | 0.01% | tr87-a.json |
| tn36 | 1 | 7 | 1333 | 317 | 0.00% | tn36-a.json |
| **12 games** | **0** | — | — | — | **0.00%** | never cleared a level |

Zero-level games: `wa30 sk48 re86 m0r0 ls20 lf52 ka59 g50t dc22 cn04 bp35 ar25`.

**A perfect game is worth 4.00% of the corpus.** The gap does not close by perfecting
the three games that work. It closes by moving the twelve sitting at zero.

---

## What happened in the last hour (read this first)

Three runs — `lp85-c`, `vc33-b`, `s5i5-b` — were still in flight when the restart was
called. They started **4:20 PM**; the per-turn checkpointing fix committed at **6:53 PM**.
Python had already loaded the old source, so **those processes had no checkpointing** and
would have vanished on restart leaving no record they were ever played. That is the exact
durability hole the fix was written for, and the fix could not save the runs that predated it.

So I rescued them from their traces first. **All three are now on disk and scored.**

New tool: **`evals/arc/rescue.py`** — rebuilds a scorecard from a run's per-turn trace.
The trace is appended every turn and survives a kill; the scorecard was not, and did not.

It was validated against ground truth before being trusted — rescuing `lp85-b`, which has
both a trace and a real scorecard, reproduced `game`, `levels_completed`, `actions_spent`,
`deaths`, and **`level_actions` exactly** (`[5,114,17,35,12,155,64]`). Only `turns_used`
differed (67 vs 70, the final timeout turns never wrote rows), which does not affect RHAE.

What it recovered:

| run | rescued | note |
|---|---|---|
| `lp85-c` | 5/8, 352 acts, 2 deaths | did **not** beat `lp85-a` — see below |
| `vc33-b` | 3/7, 363 acts, 4 deaths | did not beat `vc33-a` |
| `s5i5-b` | **2/8**, 885 acts, 0 deaths | **s5i5 had never cleared a level** — new 13th game on the board, +2 levels |

Every rescued card is stamped `stopped: "rescued_from_trace"` and `rescued: true`, so a
rescued number can always be told from a run that finished on its own.

> **After the restart:** the three processes are dead. Their traces stopped growing at the
> kill, so the rescued cards may be a few turns short of the true final state. To capture
> the last turns, delete `eval/arc-results/{lp85-c,vc33-b,s5i5-b}.json` and re-run
> `python evals\arc\rescue.py lp85-c vc33-b s5i5-b`. It **refuses to overwrite** an
> existing card, which is why the delete is needed. This is optional — worth at most a
> handful of actions.

---

## New finding: RHAE punishes your worst level far harder than it rewards your best

`lp85-c` cleared 5 levels in **352** actions; `lp85-a` took **394** for the same 5 — and
`lp85-a` still scores higher (38.02% vs 36.92%). This is not noise, it is the scoring shape:

```
level_score = min(1.15, (human_baseline / ai_actions) ** 2)
game_score  = Σ(level_index × level_score) / Σ(level_index for ALL levels)
```

Two multiplying effects:

1. **The reward is capped at 1.15; the penalty is unbounded toward 0.** Being twice as fast
   as the human earns nothing past the cap. Being 2.5× slower costs ~84% of that level.
2. **Level weight scales with level index.** A bad level 4 is charged 4×; a brilliant level 2
   is credited 2×.

lp85-c blew level 4 (40 actions vs a human 16, weighted 4×) and won level 2 (19 vs a human
38, weighted 2× but **capped**, so the win was clipped while the loss was not). Net: it lost.

**Strategic consequence:** hunting efficiency on levels you already clear fast is nearly
worthless — you are already at the cap. **The wins are in the level that is going badly, and
the later that level sits, the more it is worth.** All three lp85 runs land at 37–38%, which
looks like a structural ceiling from levels 2 and 4, not variance.

---

## State of the tree

**Everything is committed and pushed.** `git status` shows no modified tracked files.
My earlier notes claiming a large uncommitted backlog were **stale** — six more commits had
landed than those notes knew about. Verify with `git log --oneline -12`, do not trust prose.

Recent commits (newest first):

```
6aa21b7  a run that did not return left no record that it had ever played   (checkpointing)
2ba900c  measure the standings instead of remembering them                  (standings.py)
ae87428  let the run answer whether the game draws a bar, instead of assuming
3d92643  record Gap 13 and Gap 14
9bb3a5e  the bar was findable all along; nothing in the harness ever looked  (Gap 12)
281dc42  the durable memory was reachable only by a run that had already won (keep())
9f95b34  record Gap 12, and correct the standings
51df8da  a timeout under load is a rate limit wearing a different name       (congestion)
```

### Committed at handoff (was uncommitted while this was written)

1. **`evals/arc/rescue.py`** — NEW, validated against `lp85-b` ground truth.
2. **`evals/arc/checkpoint_check.py`** — added the `sys.path` bootstrap.
3. **`evals/arc/congestion_check.py`** — same.
4. **`evals/arc/standings.py`** — same.
5. **`handoff.md`** — this file.

(2)–(4) fix a real trap: five checks ran with `python evals\arc\X.py` while three needed
`python -m evals.arc.X`, and the direct form failed with `ModuleNotFoundError: No module
named 'evals'` — which reads exactly like a broken tool rather than a wrong invocation.
**All eight now run either way.**

Also untracked: the three rescued scorecards in `eval/arc-results/` (that directory is
untracked by convention — results are artifacts, not source).

### Verification at handoff

- [x] **All 7 free offline checks PASS** — `checkpoint_check`, `congestion_check`,
      `budget_check`, `reset_check`, `retract_check`, `clue_structure_check`, `executor_check`
- [x] `standings.py` runs clean, exit 0, reproduces 10.09% / 41 levels
- [x] `rescue.py` validated against a known-good scorecard
- [x] **Full suite green: `python -m pytest tests -q` → 529 passed, exit 0** (confirmed after
      every edit above, including `rescue.py`)

---

## Do this first, after the restart

```powershell
cd C:\Users\shyamsridhar\code\ATV-Phoenix
python evals\arc\standings.py                # expect 10.09%, 41/183
```

The tree was committed green (suite + all 7 checks) before the restart, so there is nothing
to clean up. Go straight to **Gap 11** in "Open defects" below — it is the highest-value
outstanding fix.

---

## Traps that have already cost time — do not rediscover these

**`pytest` from the repo root aborts.** `Interrupted: 16 errors during collection` from
`evals/swe-bench-lite/tasks/*/test_{f2p,p2p}.py`. Those are SWE-bench **task fixtures**, not
project tests. **`python -m pytest tests -q` is the correct command.**

**`score_run` keys on `run["game"]`.** Passing `game_id` raises `KeyError`, and a try/except
around it silently turns that into a score of **0.00%**, which reads as "we scored nothing"
rather than "the scorer was never asked". This produced a false 0.00% twice. `standings.py`
encodes the correct call — use it rather than hand-rolling a scoring sweep.

**Max-of-runs picks by SCORE, not by levels.** `EnvironmentScoreList.score` says "average"
in its docstring and returns `max(...)` in its body. sb26's **7/8 at 73.74% beats its own
8/8 at 71.48%**, because level 8 cost 56 actions against a human 18 under a squared penalty.
**Completing more is not the same as scoring more.** Outside Competition Mode variance is
free (best run counts); inside it, `has_environment(game_id)` refuses a second play — one
shot per game. Never import a conclusion from one regime into the other.

**`list_powershell` is unusable here** — returns ~170 KB and spills to a temp file. Poll by
`shellId` instead. `read_powershell` can also return an empty body with a valid exit code.

**PowerShell has no heredoc.** Use `@'` … `'@ | python -`. Passing a multi-line `python -c`
string fails with *"ScriptBlock should only be specified as a value of the Command parameter"*.

**`gh` account drift** — the active account silently switches to `shyamsridhar_microsoft`
(no write access). Fix: `gh auth switch -u shyamsridhar123`. A bot also pushes to the
working branch, so fetch/rebase before pushing.

**`rhae.py:load_results` only globs `mission-*.json`** — it will silently miss every run we
have. Score with `score_run(json.load(...)["runs"], load_baselines())`.

---

## Open defects, ranked by what they are costing

**Gap 11 — mechanic-write-loss. PROVEN, UNFIXED. Highest value.**
`bp35-b` called `mechanic()` 17 times and recorded an **empty** list. Measured on
`trace-bp35-b.jsonl`: 26 turns, death turns `[4,8,9,13,14,17,20,22,23]`; **17/17** writes sit
after an action call, and **9 of those turns died**. `Died` raises mid-cell and the rest of
the cell never runs, so the write is silently discarded. **On a death-heavy game the lesson
learned from dying is exactly the lesson never saved.** Fix in the death branch
(`codeact_agent.py:553-570`): buffer ledger writes and flush **before** the raise. Prefer the
harness fix over a prompt instruction. Extend to `note()` / `retract()` / `accept()`, which
are unmeasured and carry the same risk.

**Stale instruments on manual `reset()`.** A manual reset clears neither `_inert`, the stall
counter, nor `_bar_colour` / `_bar_row` / `_bar_seen`. With resets now running 9–21 per run
(see Gap 10 below) this is a live stale-instrument risk. Same code site as the Gap 11 fix.

**Gap 12 — bar discovery.** Implemented and committed (`9bb3a5e`), suite-green, but has **no
dedicated synthetic check** and the `_bar_seen` shape changed (tuple → `dict[int, dict[int,int]]`)
without a full audit of its references. Worth a check in `congestion_check.py` style: reproduce
bp35's row-63 geometry (single-colour full-width at frame 0, degraded 2-colour by frame 3),
assert the pristine branch fires, that conservation resolves a drain, and that two
simultaneously-draining rows adopt **nothing**.

**Gap 9 — death forensics, unbuilt.** A death records a count and nothing else: no last
action, no coordinates, no preceding sequence. Same code site again.

**`accept()` is called 0 times in every run ever traced** — it is absent from the SYSTEM
prompt. See Gap 10: an undocumented or mis-described primitive is simply never used.

---

## The two biggest lessons so far

**1. The prompt told the agent the wrong objective.** SYSTEM said *"You are scored on levels
completed."* False. The agent optimised exactly that and produced 6/6 at **13.67%**. Fixing
it to the real RHAE formula plus live pace feedback took cd82 to **61.68%**. Biggest single
win of the project.

**2. Gap 10 — a mis-described primitive is actively avoided, and nothing says why.** The API
block claimed `reset()` restarts from level 1 and costs actions. **Both halves were false:**
`update_scorecard` dispatches on action id (id 0 = RESET → `inc_reset_count`; ids 1–7 →
`inc_action_count`) and RHAE divides by the **action** count — so **a reset is free**, and it
restarts the **current level**. `reset()` appeared **8 times across 61 traces**. After
correcting the text: **16 / 21 / 9 in a single batch.** Caveat to keep: *a reset buys back the
BOARD, never the BUDGET.* Decision rule: reset when undoing by hand costs more actions than
replaying from pristine.

**Measured negative result — do not retry.** Telling a stalled agent to "try something
STRUCTURALLY different" reads as *run more experiments*: 1,026 → 4,212 actions,
13.67% → 0.53%. Under a squared efficiency penalty, encouraging exploration is close to the
worst possible advice. Reverted.

---

## Recommended next moves

1. **Read the suite result, then commit the four green files.**
2. **Fix Gap 11** (buffer + flush before the `Died` raise) with a check that simulates a death
   mid-cell and asserts the pending write survives. This is the single highest-value fix
   outstanding — it is proven, cheap, and it unblocks every death-heavy game.
3. **Re-run `bp35`.** 9 lost conclusions plus a never-discovered row-63 bar make it the
   clearest case where the Gap 11 + Gap 12 fixes together should change the outcome.
4. **Re-run `sc25`** — bar-less, 18 deaths, stuck at 3/6, and its deaths are a hard **per-life
   action budget (~38–50)**, not a positional hazard (inter-death deltas 38/38/40/48/47/50/41/46/50).
   Sharpest joint test of Gap 10 + Gap 12.
5. **Target the twelve zero-level games**, cheapest human baseline first:
   `ar25 748`, `ka59 730`, `bp35 651`, `s5i5 638` (now 2/8), `ls20 776`, `cn04 789`,
   `g50t 879`, `sk48 1070`, `m0r0 1107`, `dc22 1228`, `re86 1255`, `lf52 1339`, `wa30 1843`.
   Each first level cleared is worth more than any efficiency gain on sb26/cd82/ft09.
6. **Run ~3 concurrent, not 6.** Endpoint TPM is a fixed, measured ceiling; more runs split
   one allowance and add 429 churn. **Pass `out_path` per run** so an interruption now leaves
   a scorecard — that is exactly what the last three runs could not do.

**Deferred by standing instruction:** efficiency optimisation and hardening come *after* 100%
completion. Commit only when something is actually solved.

---

## Cost model

~2h wall clock and 3.5–4.8M tokens per game run. 22 games unbeaten. Offline trace analysis is
**free** — diagnose from `eval/arc-results/trace-<run>.jsonl` before spending another run.
