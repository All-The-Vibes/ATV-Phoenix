# ARC-AGI-3 corpus mission: beat Prime Agent

`MISSION.md` covers one game, sb26, and that game is finished 8/8. This file covers the
real benchmark: **all 25 public environments, 183 levels**, and the target we are trying
to beat. Read both. Every number here is either measured in this repo or cited to a
primary source; where something is unpublished it says so instead of guessing.

## The target

**Prime Agent (PrimeIntellect) scores 95.5% RHAE Best@1 on the 25 public games, with
183/183 levels complete**, using Opus 5. Three runs scored [95.0, 95.2, 95.5], Best@3
99.97%.

Source: <https://www.primeintellect.ai/blog/prime-agent> (August 2026). Public scorecard
for the median 95.2% run: <https://arcprize.org/scorecards/2af780b4-f2a1-43e9-a794-b23da3cd3f9f>

Read those numbers honestly, because the caveats change what beating them means:

* **Self-reported, not ARC-verified.** It is a blog post plus a public scorecard, on the
  25 PUBLIC games. It is not the semi-private Verified leaderboard and not the Kaggle
  private set.
* **Public games are the harder set.** ARC's testing policy states the public demo is
  harder than the semi-private set, agreement expected within +/-15pp. So this is not a
  soft target chosen for flattery.
* **It is a HARNESS result, not a model result.** ARC Prize's own basic harness scores
  frontier models at 0.18%-0.51% (GPT-5.5 High 0.43%, Opus 4.7 High 0.18%;
  <https://arcprize.org/blog/arc-agi-3-gpt-5-5-opus-4-7-analysis>). The distance from
  0.43% to 95.5% is almost entirely scaffolding. That is the encouraging part: the gap
  we face is engineering, and it is the kind of engineering this repo already does.
* **It beats the cited human expert baseline of 95.4%** -- though note ARC's own docs do
  not state that 95.4% figure anywhere we could fetch; PrimeIntellect attributes it to
  ARC. Treat the human number as approximate.

Independent confirmation we did do: `corpus_survey.py` sums the per-game level counts
from the live API to exactly **183**, matching their "183/183" claim. Their corpus
description is accurate.

## Where we stand, measured

| | Prime Agent | Us |
|---|---|---|
| Corpus RHAE | **95.5%** | **10.08%** |
| Games with a level cleared | 25 / 25 | 12 / 25 |
| Levels completed | 183 / 183 | 39 / 183 (21%) |
| Best single game | not broken out | sb26 **73.74%** |
| Model | Opus 5 | gpt-5.6-sol |

Per game, best scorable run at `start_level: 1`, scored max-of-runs the way
`EnvironmentScoreList.score` actually scores it. The twelve below are the CodeAct agent;
the remaining thirteen are the superseded `vision_agent`'s all-25 sweep (`novelty.json`,
0.00% each) and stand only as placeholders until played.

| game | levels | actions | human | deaths | RHAE | stopped |
|---|---|---|---|---|---|---|
| sb26 | 7/8 | 325 | 213 | 1 | **73.74%** | max_turns |
| cd82 | **6/6** | 394 | 171 | 0 | **61.68%** | won |
| ft09 | **6/6** | 809 | 208 | 4 | **48.18%** | won |
| lp85 | 5/8 | 394 | 388 | 3 | 38.02% | max_turns |
| vc33 | 3/7 | 457 | 447 | 6 | 14.80% | **congestion** |
| sc25 | 3/6 | 846 | 350 | 16 | 10.20% | max_turns |
| su15 | 3/9 | 718 | 361 | 15 | 3.60% | **congestion** |
| r11l | 1/6 | 690 | 233 | 17 | 1.60% | max_turns |
| sp80 | 2/6 | 2000 | 518 | - | 0.04% | vision_agent |
| tu93 | 1/9 | 280 | 462 | 7 | 0.02% | **congestion** |
| tr87 | 1/6 | 2059 | 414 | 8 | 0.01% | max_turns |
| tn36 | 1/7 | 1333 | 317 | 8 | 0.00% | max_turns |

Note sb26: the best-scoring sb26 run is a **7/8**, not the 8/8. Efficiency is squared, so
a run that clears one fewer level in 325 actions outscores one that clears them all in
245-plus-the-cost-of-the-eighth. Completion and score are different objectives and the
scorer means the second one.

**We are not 24 points behind. We are 85 points behind**, and the reason is coverage, not
quality. Read the next section before proposing any optimisation to sb26.

### The dominant lever is the thirteen games nobody has played

Thirteen of twenty-five games have never had a single CodeAct attempt. They contribute
exactly 0.00% each and they are 52% of the corpus. Our *median attempted* game scores
about 10%; our mean attempted game about 21%. Simply attempting the remaining thirteen at
our current, unimproved competence is worth roughly **+5 to +11 points of corpus RHAE** —
more than any harness improvement has ever returned, and it requires no new ideas.

Since a game is worth its best run and a bad run cannot lower it, there is no argument for
withholding an attempt. Play them.

### Deaths are the discriminator, not difficulty

Every game we have finished had 0-4 deaths. Every game we have failed had 8-20. A death
resets the level, so the actions before it buy nothing, and under a squared efficiency
penalty the level is worthless long before the agent stops paying for it.

### lp85 was stopped by the harness, not by the game

lp85 reached 5 of 8 having spent **394 actions against a 388-action human baseline for
the whole eight-level game** — still solving, at roughly human cost — and what ended it
was `--max-turns 90`. ARC charges actions and never turns. Runs now stamp `stopped` so
this is visible in the artifact instead of depending on who reads the log.

## The scoring math, and the one strategic fact it forces

From <https://docs.arcprize.org/methodology.md>:

    level_score = min(1.15, (human_baseline_actions / ai_actions) ** 2)
    game_score  = SUM(level_index * level_score, completed) / SUM(level_index, ALL levels)
    total       = mean(game_score across ALL games in the scorecard)

Three consequences, and the third is the whole strategy:

1. **Efficiency is squared.** Twice the human action count scores 25%, not 50%. Ten times
   scores 1%. Completing a level slowly is worth almost nothing.
2. **Unfinished levels keep their weight in the denominator.** Their weight is their
   index, so the last level of an 8-level game is 8/36 = 22% of that game on its own.
   Clearing level 1 perfectly and stopping caps the game at 1/36 = 2.8%.
3. **The total is the mean over ALL games, and a game you never play scores 0.** One
   perfect game out of 25 caps the corpus at 1.15/25 = **4.60%**.

So: **sb26 is nearly exhausted as a source of score.** Taking it from 71.48% to a perfect
115% -- which would require beating the human baseline on every one of eight levels --
adds **1.7 points** to the corpus total. Playing one new game to the quality we already
have on sb26 adds **2.9 points**. Breadth beats depth by a wide margin, and it is not
close.

Where sb26's remaining 43 points actually sit, if someone does want them: levels 6 and 8
score 0.142 and 0.103 against a 1.15 cap, and carry weights 6 and 8. Everything else is
already at cap or near it.

### A fourth consequence, and it decides how to spend attempts

Read from the scorer rather than the docs, in `arc_agi/scorecard.py`:

    class EnvironmentScoreList:
        @property
        def score(self) -> float:
            """Return the average score of the runs."""
            return max(run.score for run in self.runs)

The docstring says average and the code returns **max**. The code is what runs. So
**outside Competition Mode a game is worth its BEST run**, and a bad attempt costs
tokens and wall clock but never score.

That resolves the variance question we have been treating as the core risk. cd82 across
seven runs on identical code went 1/6, 5/6, 6/6, 2/6, 4/6, 6/6, 2/6 -- and under
max-of-runs that game is worth its 6/6. Prime Agent's three reported sweeps, [95.0, 95.2,
95.5], are the same arithmetic: the headline is the best one.

Two regimes, and the same number means different things in each:

* **Open scoring** -- variance is not a penalty. Throughput is the lever: more attempts
  on a game we have not beaten strictly help, and there is no reason to hold a run back.
* **Competition Mode** -- `has_environment(game_id)` refuses a second play, so it is one
  shot per game and variance is the entire game. Reliability only becomes the objective
  here.

We are optimising the first today. Do not import conclusions about reliability from one
regime into the other.

### RESET is free, and the agent was told it was fatal

Also read from the scorer: `update_scorecard` dispatches on the id of the action taken.
Id 0 is RESET and routes to `inc_reset_count`; ids 1-7 route to `inc_action_count`. RHAE
divides by the action count. **A reset never enters it.** And a reset restarts the
CURRENT level -- across 59 recorded traces the level count never once fell, including
sc25 holding levels=3 through ten consecutive deaths.

The prompt described this as `reset() -> restart from level 1`, and 53 of 61 recorded
runs never called it once. See Gap 10. What it buys is the BOARD, never the BUDGET:
actions already spent stay spent, so the rule is arithmetic -- reset when undoing by hand
costs more actions than replaying from pristine.

## The rules. Adhere strictly; these are not guidelines

### Competition Mode (<https://docs.arcprize.org/toolkit/competition_mode.md>)

    from arc_agi import Arcade, OperationMode
    arc = Arcade(operation_mode=OperationMode.COMPETITION)

1. Environments must be driven **through the API**; no local-only runs.
2. Scoring is against **ALL** available environments. Skipped games score 0 and stay in
   the denominator.
3. **Only Level Resets.** Game Resets become Level Resets.
4. **`make` may be called ONCE per environment.** One shot per game. No trial runs, no
   "let me try that again".
5. One Scorecard per session.
6. `get_scorecard` does not work mid-run. You cannot watch your score while playing.

**Rule 4 invalidates our current working style and the tools built around it.**
`level_jump.py` reaches a private `set_level` and `variant_probe.py` calls `make` four
times on one game. Both are legitimate offline instruments and both are **forbidden in a
competition run**. They already refuse to produce a score -- `level_jump.assert_not_scorable`
sets `scorable: false` -- and that separation must be preserved, not quietly eroded.
Never let a probe share a process with a scored run.

### Hardcoding

The Kaggle set is **private and hidden**, and ARC states plainly: *"Due to a hidden
hold-out set, these games can't be memorized."* A rule tuned to sb26's geometry scores
zero there. `MISSION.md` already forbids hardcoding sb26 facts into the prompt; extend
that to the whole corpus. What you may build is a **general discovery procedure**.

This is why the winning sb26 rule ("the hollow piece is the link to the other frame") is
deliberately absent from `mechanics.json`. It is an answer, not a mechanic. Mechanics are
things like "hollow pieces exist and must be lifted by their ring" -- true of the
renderer, not of one puzzle.

### Kaggle vs the API leaderboard -- pick the target deliberately

* **Kaggle (ARC Prize 2026, due 2026-11-02): no internet.** No GPT/Claude API. Local
  open-source weights only, <12h runtime, RTX 6000 class. Our gpt-5.6-sol agent **cannot
  enter**. Milestone 1 winners all used local models (Tufa Labs "The Duck" on Qwen 3.6
  27B; Reki and "forge" on Gemma-4-31B).
* **The API route** is where Prime Agent's 95.5% lives, and where we can compete as we
  are built today.

Beating Prime Agent means: **25 public games, via the API, scored by RHAE, mean over all
games.** Anything else is a different contest.

## The measured gap: our perception layer describes exactly one game

`python -m evals.arc.corpus_survey` -- free, offline, no model calls -- opens all 25
environments and asks `frames.parse` what it sees:

* `parse()` returns a layout for **24 of 25** games.
* Exactly **1 of 25** is actually sb26-shaped (one tray piece per pad): sb26.

The other 23 "successful" parses are noise wearing the shape of an answer: tu93 reports
62 pads and 0 tray pieces, dc22 reports 13 pads and 0 tray, tn36 reports a 1x27 clue row.
Every rule in this harness assumes one tray piece per pad, and that invariant holds in one
environment out of twenty-five.

**This is worse than failing to parse.** A parser that returns confident nonsense is a
harness that lies, and Gap 7 in `HARNESS_GAPS.md` is exactly the lesson about what happens
when the instrument misrepresents the world: the agent looks like it is reasoning badly
while it is in fact reasoning correctly against a false picture.

**First corpus task, and it is not optional: make `parse()` refuse.** It should return
None, or an explicit "I do not describe this board", whenever its own invariants fail --
tray count not matching pad count, zero tray pieces, a clue row that cannot address the
pads. A game it cannot describe must fall through to raw `objects()` and `board()`, which
are general. Free to build, free to check, and it removes an active source of lies before
any spend.

Corpus shape for planning, from the same survey: human baselines run from 171 actions
(cd82) to 1,843 (wa30), levels per game from 6 to 10, total human actions across the
corpus 17,135. sb26 at 213 actions is among the **smallest** games in the set. Do not
generalise difficulty from it.

## First contact with an unseen game, measured

`eval/arc-results/cd82-first.json` -- the agent, unchanged, on cd82, a game it had never
seen. Scorable, start level 1.

    1/6 levels.  713 actions.  7 deaths.  game score 0.34%.
    Level 1 cleared in 205 actions against a human baseline of 55.
    Corpus with sb26 and cd82 both counted: 2.87%.

Four things that were worth the spend to learn:

**It cleared a level of an unseen game.** Not nothing. The generic path works at all.

**It never called `layout()` once.** Not on any of 40 turns. It went straight to
`objects()` and `board()` and derived cd82's structure from what was drawn. So the
sb26-shaped parser was not the blocker here -- the agent correctly declined to reach for
it. That is worth knowing before anyone spends a week generalising `frames.py`: the
perception layer was not what cost us this game.

**cd82 is a different GENRE, and that was the blocker.** It is directional movement and
painting -- actions 3 and 4 move a tile and repaint about 100 cells -- not the pick-up and
drop-on-a-pad that every executor primitive in this harness implements. `try_assignment`,
`seated`, pads and tray are all inapplicable. The agent had to hand-roll movement, spent
205 actions on a 55-action level, then died seven times on level 2 over 508 more actions.
Genre, not perception, is the gap.

**The probe is expensive and sometimes learns nothing.** Measured over three unseen games:

| game | probe cost | click rows found | drag found |
|---|---|---|---|
| cd82 | 38 actions | 10 | no (correct: it is not a drag game) |
| r11l | 40 actions | 16 | no |
| ft09 | 58 actions | **0** | no |

On ft09 the probe spent 58 actions and found nothing at all -- and 58 actions is 28% of
the ENTIRE human budget for that six-level game. RHAE squares efficiency, so a probe that
returns nothing is not merely wasted, it caps the game's achievable score before play
begins. On cd82 the 38-action probe cost 69% of level 1's human baseline on its own.

That reframes the corpus problem. The bottleneck is not one perception layer; it is that
**a general agent must identify a game's genre and its own applicable primitives cheaply**,
and our only general instrument for that costs a third of the budget and can come back
empty. Making the probe adaptive -- stop as soon as the genre is decided, and decide it
from what is drawn rather than from a fixed script -- is worth more than generalising
`frames.py`.

## First contact with an unseen game, and what fixed it

### Before: the agent, unchanged, on a game it had never seen

`cd82-first.json` -- scorable, start level 1: **1/6 levels, 713 actions, 7 deaths, 0.34%**.
Level 1 alone cost 205 actions against a 55-action human baseline.

Three measured causes, none of them "the model is not smart enough":

**Deaths were 65% of the entire cost.** Six turns of 74-83 actions each, 463 of 713
actions, each one a full move bar walked into a wall.

**The agent was BLIND to its life budget.** `clock()` read a confident full bar on the
opening board and then returned every field None from the first action onward. It never
saw a single one of those six deaths coming. Cause: `frames.budget` disqualified any row
containing the board's background colour. sb26 draws its bar in reserved colours, so that
assumption never surfaced; cd82 spends its bar INTO the background, so the row was
rejected exactly when it became informative. Another instrument written against one game
and silently wrong on the next -- the same shape of bug as Gap 7.

**Notes were create-only, so contradictions accumulated instead of knowledge.** The run
ended holding both *"Do not click active blocks: clicks merge their pixels"* and *"CLICK
that domino to drop it"*, acting on both. Meanwhile it re-derived the same dead theories
over and over: Voronoi on four separate turns, orientation on six. That is Gap 4 -- create
and read, no delete -- costing a game.

### The fix: Prime Agent's Continual Harness, minimally and honestly

Prime Agent's differentiator is not its model. ARC Prize's own harness scores frontier
models at 0.18-0.51% on this benchmark; Prime Agent reaches 95.5% with Opus 5. The
difference is harness state the agent can CRUD from its own trajectory, plus a `/refine`
step that applies the smallest relevant edit after a trajectory. We had create and read.

1. **`budget` reads a bar whose spent half is the background colour**, once the full
   colour is known from the opening board. General, not cd82-specific: measured across the
   corpus, **17 of 25 games now keep a readable bar while spending and none go blind**.
   Held by `budget_check.py`, which checks sb26 AND cd82, because proving a perception fix
   against one game is what caused this.
2. **`retract(n, because=...)`** -- the D in CRUD. A disproved note leaves the live list
   and is remembered in a DISPROVED list, because knowing a theory is dead is what stops
   the twelfth rediscovery of the eleventh dead idea. Scoped to the board, since a theory
   false here may be true on the next level. Held by `retract_check.py`.
3. **A death forces consolidation.** A death is the strongest refutation the game hands
   out and it used to teach nothing. The turn after one, the agent is told it died and
   must retract the belief that walked it there before spending another action. It costs
   no actions and asserts nothing about which belief is wrong -- that is the agent's job.

### After

| | before | after |
|---|---|---|
| cd82 levels | 1/6 | **5/6** |
| cd82 score | 0.34% | **50.88%** |
| deaths | 7 | **1** |
| actions | 713 | 480 |

Levels 4 and 5 were cleared FASTER than the human baseline (1.40x and 1.35x, both at the
1.15 cap). sb26 re-run end to end afterwards: still **8/8**, no regression.

**Corpus: 2.87% -> 4.89%.**

What is left on cd82 is discovery cost, not deaths: levels 1-3 ran at 0.37x, 0.06x and
0.25x of human. Level 2 costs 132 actions against a human's 8. That is the next target
there, and it is the same problem as ft09's empty probe -- identifying a game's genre
cheaply.

## How to work

1. **Offline before spend, always.** `corpus_survey`, `clue_structure_check`,
   `executor_check` and `variant_probe` cost nothing and no model calls. Every fix that
   produced 8/8 was found and proven offline first. Keep that ratio.
2. **A jumped run is never a result.** `level_jump.py` exists to ask "does the harness
   read this board honestly", never "what is my score". It marks itself unscorable; never
   remove that.
3. **Report N, not the best.** sb26 8/8 is 2 of 3 runs and is stated that way. Prime
   Agent reported [95.0, 95.2, 95.5] and their Best@1 separately, which is the standard to
   match. One green run is never proof.
4. **Score every run** with `rhae.py` against the live baselines, and quote the corpus
   total, not the game score, when claiming progress against Prime Agent.
5. **Turns and patience are harness artifacts.** ARC charges actions. Every run that
   stopped short of 8/8 was cut by a turn budget with actions unspent. Use
   `--max-turns 75 --patience 75` and let the action budget and deaths be the real limit.

## Honest open gaps

* **Phoenix runs but certifies nothing.** `sense()` fires every turn, `propose()` nearly
  every turn, but `phoenix_proven` is `[]` on both 8/8 runs because the agent never calls
  `accept()`. The gate is instrumented and idle. Fixing that is the highest-value
  Phoenix-side work and is tracked as Gaps 1-6 in `HARNESS_GAPS.md`.
* **No cross-game memory.** Prime Agent's Continual Harness (prompt / sub-agents / skills
  / memory, all CRUD-able, <https://arxiv.org/abs/2605.09998>) is the architectural
  difference that most plausibly explains 95.5% across 25 games. We have `skills.py`, an
  ARC-specific store, and Gap 3 records that Phoenix has no general equivalent.
* **We have never run a game other than sb26 with the agent.** Everything above about the
  other 24 games is perception-layer measurement, not gameplay. The first honest corpus
  number will come from running the agent on games it has never seen, and it should be
  expected to be bad.
