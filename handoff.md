# ARC-AGI-3 - Handoff

**Written:** 2026-08-11, mid-session (master queue draining).
**Repo:** `C:\Users\shyamsridhar\code\ATV-Phoenix`
**Branch:** `arc/corpus-baseline-8of8` -> PR #189
**HEAD:** `4b468da` - pushed, `origin` matches.

---

## Read this paragraph first

Session start: **10.09% RHAE, 41 levels, 13 games on the board.**
Now: **12.24%, 54 levels, 19 games.** Six games have never cleared a level:
`bp35 wa30 re86 lf52 dc22` plus whatever is still queued.

The reason the corpus looked worse than it was: **eight games had never been played by
the agent at all.** Their 0.00% came from `novelty.json`, a random-policy sweep with 0
turns and 0 tokens. A zero from a policy baseline and a zero from an agent that tried
print identically, and the difference is the entire strategy.

**A master queue is draining.** Check it, do not re-derive it:

```powershell
Get-Content eval\arc-results\queue-m1.log -Tail 10
Get-ChildItem eval\arc-results\log-*-m1.txt | ForEach-Object { "$($_.BaseName) :: $(Get-Content $_.FullName -Tail 1)" }
```

Queue order was: bp35 ls20 sk48 g50t m0r0 dc22 re86 lf52 wa30 ar25, concurrency 3,
`--max-turns 220 --patience 90`. **If the machine restarted, the runner is dead** -
relaunch with the games that have no scorecard yet:

```powershell
python evals\arc\queue_runner.py --games <remaining> --tag m2 --concurrency 3 `
  --max-turns 220 --patience 90
```

**Do not `stop_powershell` a queue runner** - it kills the process tree and takes the
running agents with it. Measured: it killed g50t and sk48 mid-run. Per-turn
checkpointing saved both results, which is the only reason that was recoverable.

---

## Four defects fixed this session, all measured

**Gap 15 - a counter that falls was read as a counter that counts** (`588ba7e`).
`frame.levels_completed` is not monotone. The transition fired nine times for two real
levels, charged level 2 the last 49 of the 375 actions it cost, and told the agent
"LEVEL 1 CLEARED" seven times while it stood on level 3. Now gated on a high-water
mark. **Validated live on cn04**, a game it was never diagnosed on: the raw counter
fell to 0 at turn 23 and the harness correctly did nothing.

**Gap 11 - the lesson a death teaches is the lesson a death destroys** (`7e94d18`).
`Died` aborts the cell, so the `mechanic()` call recording what killed you never runs.
96 writes lost across 41 traces. A pre-scan of literal arguments recovers only 49 of 96
and misses the death-heaviest runs entirely, so the fix replays the unreached ledger
statements after the abort - the exec namespace outlives the exception with every
pre-action local still bound. **Validated in production on bp35:** pre-fix, 45 turns
and 20 deaths recorded **0** mechanics; post-fix, 67 turns recorded **3 mechanics, 1
note, and 9 salvaged writes.**

**Gap 17 - a credential refresh under load is a rate limit wearing a third name**
(`5a5a8c4`). Three concurrent runs refresh tokens against one Azure CLI, contend, and
one loses with `CredentialUnavailableError`. It was counted as a model failure. **It
cost two runs in one batch:** ar25 killed at 5/8 while clearing level 5 in 59 actions,
and ls20 killed at turn 18 of 160 and filed as 0/7. ls20 was requeued and reached
**2/7**.

**Gap 18 - a coordinate is not a rule of the game** (`4b468da`). Twelve runs called
`mechanic()` up to 111 times and `note()` **zero** times, and they are exactly the
stuck games. The prompt caused it: `note()` got one line, `mechanic()` got twenty-four
plus a sentence saying mechanic() is "the thing you write the answer into". ka59
stored level 1's coordinates as rules of the GAME, then spent 2,732 actions on level 2
steering by them - and a mechanic is never cleared by a level change, by design. Fixed
on both sides: the prompt states the redraw test, and the harness flags any rule naming
a coordinate in the ledger the agent re-reads every turn.

**Every stuck game was run under the broken prompt.** ka59, cn04, sp80 and bp35 are all
worth rerunning now purely for Gap 18.

---

## Where we actually stand

```
CORPUS RHAE                  : 10.09%
Prime Agent                  : 95.50%
gap                          : 85.41 points
games with a level cleared   : 13 of 25
levels cleared               : 41 of 183
```

Reproduce with `python evals\arc\standings.py`. **Never quote standings from memory** —
that has been wrong twice. The tool is the answer.

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
| s5i5 | 2 | 8 | 1515 | 638 | 0.41% | s5i5-b.json (rescued) |
| sp80 | 2 | 6 | 2000 | 518 | 0.04% | novelty.json |
| tu93 | 1 | 9 | 280 | 462 | 0.02% | tu93-a.json |
| tr87 | 1 | 6 | 2059 | 414 | 0.01% | tr87-a.json |
| tn36 | 1 | 7 | 1333 | 317 | 0.00% | tn36-a.json |
| **12 games** | **0** | — | — | — | **0.00%** | see the paragraph above |

**A perfect game is worth 4.00% of the corpus.** The gap does not close by perfecting the
three games that work.

---

## What is running right now

Launched by hand (started ~20:55 CDT, ~2–4h each):

| run | game | last seen |
|---|---|---|
| `ar25-a` | ar25 | turn 21, rate-limited |
| `ka59-c` | ka59 | turn 20, **level 1 reached**, 359 actions, 2 deaths |
| `cn04-a` | cn04 | turn 20, 163 actions, 0 deaths |

**A queue runner is holding eight more games** and will admit them as slots free:

```
ls20 g50t sk48 m0r0 dc22 re86 lf52 wa30
```

Read its state without parsing logs:

```powershell
Get-Content eval\arc-results\queue-status.json -Raw
Get-Content eval\arc-results\queue-q1.log -Tail 20
```

It admits a game only when fewer than 3 agents are alive **anywhere on the machine**, so
it cooperates with hand-launched runs rather than stacking on top of them. Concurrency is
3 because the endpoint's TPM is a fixed ceiling — the three current runs are already
logging `RateLimitError` waits, so more runs would split one allowance and add churn.

If the machine was restarted, **the queue runner is dead and must be relaunched**:

```powershell
python evals\arc\queue_runner.py --games <remaining> --tag q2 --concurrency 3 `
  --max-turns 160 --patience 90
```

---

## Fixed this session

**Gap 15 — a counter that falls was read as a counter that counts** (`588ba7e`).
`frame.levels_completed` is not monotone; on s5i5 it oscillates inside a level. The
transition gate fired **nine** times for **two** real levels, carrying level numbers
`1,1,1,2,1,1,1,1,1`. It charged level 2 the last 49 of the 375 actions it cost, told the
agent "LEVEL 1 CLEARED" seven times while it stood on level 3, and wiped level notes each
time. Now gated on a new high-water mark. Pinned by
`python evals\arc\level_monotonic_check.py`.

**Gap 11 — the lesson a death teaches is the lesson a death destroys** (`7e94d18`).
`Died` aborts the cell, so the `mechanic()` call recording what killed you never runs.
`bp35-b` called it 17 times and recorded nothing; 96 writes were lost across 41 traces.
A pre-scan of literal arguments would have recovered only 49 of 96 — and missed `r11l`
and `su15` entirely, the two death-heaviest runs. Fixed by replaying the unreached ledger
statements after the abort, since the exec namespace outlives the exception with every
pre-action local still bound. Pinned by `python evals\arc\ledger_salvage_check.py`.

**Results are now stamped `harness: 2`.** A card written before Gap 15 may charge a level
a fraction of the actions it cost, and no amount of re-reading can tell — the damage
happened before the write. So the invariant binds what this build produces, and the 4
older cards and 10 older traces are **quarantined by name and counted**, not silently
trusted and not silently excused.

**Three restart-killed runs were rescued** from their traces:
`lp85-c` 5/8 in 1015 acts, `vc33-b` 3/7 in 894, `s5i5-b` 2/8 in 1515.
None beat the existing best for their game. `s5i5-b` now reports `level_actions=[107,375]`
— the Gap 15 fix reaching through the rescue path, exactly as the check predicted.

---

## Verification at handoff

- [x] `python -m pytest tests -q` → **529 passed**, exit 0 (run twice, after each fix)
- [x] All 9 free offline checks green, including the two new ones
- [x] `standings.py` runs clean, reproduces 10.09% / 41 levels / 13 games
- [x] `level_monotonic_check` ALL GREEN with 4 cards + 10 traces quarantined by name

---

## Traps that have already cost time — do not rediscover these

**`pytest` from the repo root aborts** with `Interrupted: 16 errors during collection`
(SWE-bench task fixtures, not project tests). **`python -m pytest tests -q` is correct.**

**`score_run` keys on `run["game"]`.** Passing `game_id` raises `KeyError`, and a
try/except turns that into **0.00%** — which reads as "we scored nothing" rather than "the
scorer was never asked". This produced a false zero twice. Use `standings.py`.

**Max-of-runs picks by SCORE, not levels.** `EnvironmentScoreList.score` says "average"
and returns `max(...)`. sb26's **7/8 at 73.74% beats its own 8/8 at 71.48%**. Outside
Competition Mode variance is free; inside it `has_environment()` refuses a second play.
Never import a conclusion from one regime into the other.

**Scorecard JSON shape is not uniform** — some files are `{"runs": [...]}`, at least one
is a bare top-level list. A sweep that assumes one shape dies with `AttributeError`.

**`rhae.py:load_results` only globs `mission-*.json`** and will silently miss every run we
have.

**`list_powershell` is unusable here** — ~170 KB, spills to a temp file. Poll by
`shellId`. `read_powershell` can return an empty body with a valid exit code.

**PowerShell has no heredoc.** Use `@'` … `'@ | python -`. A multi-line `python -c` fails
with *"ScriptBlock should only be specified as a value of the Command parameter"*. A
`git commit -F -` with `<<'EOF'` also fails — write the message to a temp file instead.

**`gh` account drift** — silently switches to `shyamsridhar_microsoft` (no write access).
Fix: `gh auth switch -u shyamsridhar123`. A bot pushes to the branch; fetch/rebase first.

**Do NOT `git clean`.** Everything in `eval/arc-results/` and every diagnostic probe is
untracked **by convention**, not by accident.

---

## Open defects, ranked

**Gap 12 — bar discovery has no dedicated check.** Implemented (`9bb3a5e`), suite-green,
but `_bar_seen` changed shape (tuple → `dict[int, dict[int,int]]`) without a full audit of
its references.

**Gap 9 — death forensics, unbuilt.** A death records a count and nothing else: no last
action, no coordinates, no preceding sequence.

**`accept()` is called 0 times in every run ever traced** — it is absent from the SYSTEM
prompt, and `keep()` is absent from the REPL namespace. See Gap 10: an undocumented or
mis-described primitive is simply never used.

---

## The two biggest lessons so far

**1. The prompt told the agent the wrong objective.** SYSTEM said *"You are scored on
levels completed."* False. The agent optimised exactly that: 6/6 at **13.67%**. Fixing it
to the real RHAE formula plus live pace feedback took cd82 to **61.68%**. Biggest single
win of the project.

**2. Gap 10 — a mis-described primitive is actively avoided.** The API block claimed
`reset()` restarts from level 1 and costs actions. **Both false:** `update_scorecard`
dispatches on action id (0 = RESET → `inc_reset_count`; 1–7 → `inc_action_count`) and RHAE
divides by the **action** count. Usage went 8-across-61-traces → 16/21/9 in one batch after
correcting the text. Keep the caveat: *a reset buys back the BOARD, never the BUDGET.*

**Measured negative result — do not retry.** Telling a stalled agent to "try something
STRUCTURALLY different" reads as *run more experiments*: 1,026 → 4,212 actions, 13.67% →
0.53%. Under a squared efficiency penalty, encouraging exploration is close to the worst
possible advice. Reverted.

**RHAE punishes your worst level far harder than it rewards your best.** Reward is capped
at 1.15, the penalty is unbounded toward 0, and level weight scales with level index.
`lp85-c` cleared 5 levels in 352 actions and still scored *below* `lp85-a`'s 394. Hunting
efficiency on levels you already clear fast is nearly worthless. **The wins are in the
level that is going badly, and the later it sits, the more it is worth.**

---

## Next moves

1. **Let the queue drain.** Eight never-played games at ~3 concurrent is roughly six hours.
   Poll `queue-status.json`, not the logs.
2. **Re-run the standings after each batch.** A first level on any of the twelve is worth
   more than any efficiency gain on sb26/cd82/ft09.
3. **Re-run `bp35`** once the queue clears — 9 lost conclusions plus a never-discovered
   row-63 bar make it the clearest case where Gap 11 + Gap 12 together should change the
   outcome. It is queued last for exactly that reason.
4. **Re-run `sc25`** — bar-less, 18 deaths, stuck 3/6, and its deaths are a hard per-life
   action budget (~38–50), not a positional hazard.
5. **Re-read `trace-s5i5-b.jsonl` turns 49–139 through the Gap 15 lens.** 90 turns and
   1,033 actions with no recorded progress; much of it may be repeated loss-and-reclear
   while the harness insisted each re-entry was new. Largest unexplained burn in the
   corpus (3.7h, 7.3M tokens). Free to analyse.

**Deferred by standing instruction:** efficiency optimisation and hardening come *after*
100% completion.

---

## Cost model

~2–4h wall clock and 3.5–7.3M tokens per game run. Offline trace analysis is **free** —
diagnose from `eval/arc-results/trace-<run>.jsonl` before spending another run.
