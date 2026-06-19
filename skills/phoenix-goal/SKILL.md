---
type: Phoenix Skill
name: phoenix-goal
description: Turn ONE high-level, possibly-vague goal into a runnable, objective acceptance check and a verifiable backlog, then drive it to completion. The critical step is FORMALIZE — deriving an executable done-check before any code, because a goal with no objective acceptance criterion has no honest termination. This is the DEFAULT entry for any hands-off "just go and finish it" request. Use at the start of an open-ended ask, when the user says /phoenix-goal, "achieve", "build me", "get this working end to end", "go", "go autonomous", "let's go", "just do it", "run it to done", or gives a goal without a spec. Hands off to phoenix-ralph for the loop. Not for an already-scoped backlog (use phoenix-ralph) or a single known fix (use phoenix-build).
license: MIT
---

# phoenix-goal — from a fuzzy goal to a demonstrated outcome

Goal-oriented autonomous execution (BabyAGI, ReAct, Anthropic's evaluator-optimizer) all share one
fatal weakness: **without an executable acceptance criterion there is no reliable "done".** Naive
agents loop forever generating busywork, or hallucinate completion. phoenix-goal fixes this by making
the *first* deliverable an **objective `done-check`**, not code.

> The most expensive bug is building the wrong thing correctly. The second most expensive is never
> knowing you're finished. phoenix-goal closes both by formalizing intent into a check that can fail.

## The flow

```
fuzzy goal  ("just go and finish it" — or any goal handed over without a spec yet)
   │
   ▼  FRAME + confirm  ── name the entry, the goal, and the done-check; invite correction before any edit
   │
   ▼  phoenix-think  ── deep interview + research ──▶  Intent Contract
   │                                                  whose DELIVERABLE is one runnable
   │                                                  acceptance check (a real command_exit)
   ▼  write .phoenix-ralph/done-check.json   (MUST start RED — prove it fails today)
   │
   ▼  phoenix-plan   ── decompose ──▶  backlog.json  (each item carries its OWN objective check)
   │
   ▼  hand off to  phoenix-ralph  (the loop)  ──▶  driver proves done-check failure-first ──▶ DONE
```

The difference from phoenix-ralph: **ralph takes a backlog you already have; goal derives the backlog
*and* the acceptance check from a single goal first.** Goal is the on-ramp; ralph is the engine.

## Steps

1. **FRAME the run — the handshake (always first, before any `phoenix-think` or edit).** The failure this
   step exists to prevent is silently "operating in the spirit of" a request and wandering off. So open
   with a short, explicit frame and **wait for a go**:
   - **Entry:** Phoenix's autonomous skills are `phoenix-goal`, `phoenix-auto` (its autopilot), and
     `phoenix-ralph` (the persistence loop). If the user arrived via an alias from another harness that maps
     to none of them, orient in one line — *"its autonomous entry is `phoenix-goal`, so I'll run it that
     way"* — no lecture.
   - **Goal heard:** restate the goal in one sentence, as you understood it.
   - **Done-check:** name the objective acceptance check you're about to FORMALIZE (a real test/build that
     exercises the goal, which must start RED). This is *what "done" will mean*.
   - **Shape + control:** one line on how it runs (formalize → decompose → loop; completion proven from the
     trace) and how to steer or stop it.
   - **Invite correction before the first edit**, then proceed to FORMALIZE.

   Keep it to a few lines. The point: the user always knows the goal, the finish line, and how to drive it
   *before* anything changes on disk.
2. **FORMALIZE (the hard, non-skippable part).** Run `phoenix-think`: interview the user / research the
   codebase until the goal is unambiguous, then write the **acceptance check** to
   `.phoenix-ralph/done-check.json`. It must be a real `command_exit` — a test or build that actually
   exercises the goal — and it must be RED right now. If you cannot write a check that fails today,
   the goal is still too vague: keep interviewing. *No code until this exists.*
3. **DECOMPOSE.** Run `phoenix-plan`: break the goal into small, independently-verifiable items in
   `.phoenix-ralph/backlog.json`. Each item gets its own objective `check`. Order by dependency so the
   build stays green between items.
4. **SCAFFOLD** the loop state: `PROMPT.md` (from `dist/ralph/PROMPT.template.md`), `progress.md`.
5. **HAND OFF** to **phoenix-ralph**: run `dist/ralph/phoenix-ralph.ps1`. The driver proves the
   done-check failure-first on an intact trace before it stops.
6. **REPORT** with the proof: `.phoenix-ralph/completed.json` + the trace head + the git tag.

## Who writes the checks (and why it matters)
The acceptance check is authored during FORMALIZE and **frozen** before implementation. The
implementing loop must satisfy the check, not weaken it. If a check genuinely needs to change,
that is a re-scope: stop, return to `phoenix-think`, re-baseline (watch the new check fail), and only
then continue. This separation — author the gate, then satisfy it — is what stops a system from
"optimizing the check instead of the goal".

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "They said 'just go' / 'go autonomous' — I'll start building." | First FRAME the run: name the entry, restate the goal and the done-check you'll formalize, and get a go. Editing before the user has seen the finish line is the wander this skill exists to prevent. |
| "The goal is clear enough, I'll start coding." | If you can't write a check that fails today, it isn't clear enough. Formalize first. |
| "I'll use `test -f output` as the acceptance check." | That's vacuous — it can't meaningfully fail. The done-check must exercise the actual behavior (a real test/build). |
| "I'll let the loop figure out what done means." | A loop with no objective termination runs forever or fakes done. Define the check up front. |
| "The goal shifted, I'll just relax the check." | Relaxing the gate to pass is optimizing the check, not the goal. Re-scope through phoenix-think and re-baseline. |
| "Decomposition is overhead, I'll one-shot it." | For anything multi-step, an un-decomposed goal can't keep the build green between changes. Plan into verifiable slices. |

## Red Flags — stop
- You started FORMALIZE or editing without first restating the goal + done-check to the user and getting a go. → Stop; do the FRAME handshake first.
- You're about to write code and `done-check.json` doesn't exist yet. → Formalize first.
- Your done-check passes on an untouched repo. → It's vacuous; re-target it at the unmet behavior.
- The backlog items have prose acceptance ("works well") instead of an objective `check`. → Rewrite each as a runnable check.
- You weakened the acceptance check to make the loop finish. → That's not done; re-scope honestly.

## Relationship to the other skills
phoenix-goal = **FORMALIZE + DECOMPOSE**, then it delegates the persistent execution to
**phoenix-ralph**. It leans on **phoenix-think** (to derive the check) and **phoenix-plan** (to derive
the backlog). It is the Phoenix realization of the Intent-to-Outcome loop's "intent → verifiable
acceptance criteria" step (see `docs/intent-to-outcome.md`).
