# Intent-to-Outcome (I2O): the system Phoenix is an early organ of

> _Radio before the television. Phoenix proves the signal; I2O adds the picture._

This document explains the larger idea behind ATV-Phoenix. Phoenix is a shippable product on its
own — a self-healing harness for coding agents — but it is also the **first working organ** of a
bigger system we call **Intent-to-Outcome (I2O)**.

---

## 1. The thesis

**Reliably convert a human's *intent* into a *verified outcome* — across all of digital life.**

Not "make the model smarter." Not sentience. The value comes from three things layered *around* a
frozen model:

1. **Persistence** — memory and identity that survive across sessions.
2. **Agency** — acting in the world through tools.
3. **Closed-loop verification** — measuring whether the intended outcome *actually happened*, then
   learning from the gap.

The third is the hard one, and the one almost everything skips. A chatbot has (1) and (2) in weak
form and essentially none of (3). I2O is the bet that **(3) is where reliability — and therefore
trust — actually comes from.**

---

## 2. The loop

I2O is a seven-stage loop. It is not new architecture; it is a *purpose* imposed on mechanisms that
already exist (memory, tools, an executor, an eval harness):

```
            ┌──────────────────────────────────────────────────────────┐
            │                                                          │
            ▼                                                          │
   SENSE ─▶ MODEL ─▶ FORMALIZE ─▶ PLAN/ACT ─▶ VERIFY ─▶ REFLECT/DISTILL
   (gather  (world   (intent →    (do the     (objective (turn the delta
    signal) state)   checkable    work)        evidence,  into a durable
                     criteria)                 not self-  skill / memory)
                                               grading)
```

| Stage | What it does |
|---|---|
| **SENSE** | Observe the world — for coding: the repo, test output, errors. For life: calendar, mail, chat. |
| **MODEL** | Maintain a structured picture of people / projects / decisions / conventions. |
| **FORMALIZE** | Turn a raw, fuzzy intent into **explicit, verifiable success criteria** — the *Intent Contract*. |
| **PLAN / ACT** | Decompose and do the work (the agent runtime — e.g. GitHub Copilot — executes). |
| **VERIFY** | Check the outcome against the criteria with **objective evidence**, never self-assessment. |
| **REFLECT / DISTILL** | Measure the delta; distill what worked into a skill, a memory, or a better check. |

**Proactivity** = running `SENSE → FORMALIZE` *unprompted*, surfacing *proposed* Intent Contracts for
a human to approve. Direction-setting stays human; the system compounds the means, not the goals.

---

## 3. The atomic unit: the Intent Contract

Everything that flows through the loop is an **Intent Contract**:

```
intent(raw)
  → goal(formalized world-state)
  → success_criteria(verifiable)
  → constraints(privacy / budget / time / reversibility)
  → evidence_plan(how we'll know)
  → outcome(observed + evidence)
  → delta(intended vs observed)
  → learning(distilled)
```

The contract is the thing that makes an outcome *checkable* instead of *vibed*. The moment intent
becomes explicit success criteria + an evidence plan, "did it work?" stops being a matter of opinion.

---

## 4. Radio before the television

Phoenix is **not** the whole loop. It productizes the three hardest *middle* stages —
**FORMALIZE → ACT → VERIFY (and heal)** — in the one domain where the grader can be made *perfect*:
**code, which either runs or doesn't.**

That narrowness is the strategy. **Radio proved the core primitive** — broadcast a signal over the
air, a receiver reconstructs it — *before* television inherited that exact infrastructure and added
the picture. Phoenix is the radio: it proves, on live agent sessions with hidden graders, that a
**frozen model + a thin enforcement harness converts "looks done" into "is done."** The full I2O
system is the television: the **same loop**, generalized across all of digital life, running
proactively and persistently. Same signal, same infrastructure, bigger screen.

### What carries over unchanged

| Principle | In Phoenix today | In the full I2O system |
|---|---|---|
| **The Intent Contract** | a `phoenix_sense` check *is* the success-criteria + evidence made executable | proposed automatically from sensed context, promoted by a human |
| **Evidence over self-grading** | `phoenix_sense` reports only objective signals; a fabricated "done!" is the failure mode it kills | the non-negotiable that keeps a *proactive* system trustworthy |
| **Enforce, don't offer** | value comes from the loop being *run*, not merely available (unprompted self-verify measured 0/10) | the heartbeat runs `SENSE→FORMALIZE→VERIFY` without being asked |
| **Frozen weights, human direction** | improvement is scaffolding-level (skills, checks, memory), evidence-gated | the human still sets goals; the system compounds the means |

### Phoenix → I2O stage map

| I2O stage | Phoenix mechanism |
|---|---|
| FORMALIZE | `phoenix-think` skill → an Intent Contract with an objective acceptance check *before* any code |
| ACT | the agent runtime (GitHub Copilot / Scout) edits under the lifecycle skills |
| VERIFY | `phoenix_sense` — command-exit / file-hash / regex, no self-grading |
| heal | `phoenix_heal` — bounded recovery (rollback to a blessed snapshot, or retry ≤3×), confirmed by an external recheck |
| evidence | `phoenix_verify_trace` — a tamper-evident, hash-chained record of everything sensed and healed |
| DISTILL | the 13-skill pack + `doctor` self-validation; checks and skills compound over time |

---

## 5. The research backlog (falsifiable hypotheses)

I2O advances as falsifiable hypotheses, each tested in the perfect-grader domain first. Results to
date are **directional** (small n, single model) — signals, not significance.

| # | Hypothesis | Status |
|---|---|---|
| **H1** | *Intent-fidelity* — criteria-first beats acting on the raw utterance | **Positive** where constraint-checking is the work: raw 0.833 → criteria-first 1.000 (**+0.167**), 0 regressions; replicated. Null on tasks the model already solves single-pass (the nulls *located the regime*). |
| **H2** | *Verifier-pass* — an author/verify split catches silent failures one pass misses | **Confirmed** on live Copilot (20 sessions): silent-failure **40% → 0%**, 0 regressions. |
| **H3** | *Memory-lift* — injecting the right project context lifts success | **Confirmed**: **0% → 100%** on a convention the model otherwise defaults wrong. |
| **SWE-bench-lite** | resolved-rate under the real FAIL_TO_PASS/PASS_TO_PASS contract | underspecified tier **50% → 100%**, overall **78% → 100%**, 0 regressions; both misses were silent failures. |
| **H4** | *Proactive-precision* — precision-gated proposals can hit a usable approval rate | open |
| **H5** | *Skill-compounding* — distilled skills improve success & cost over repeated exposure | open |
| **H6** | *Plan-depth* — decomposition helps complex tasks, hurts simple ones (a crossover exists) | open |

The pattern across all of them is the same and is the whole point: **an enforced objective gate pays
off exactly where the spec is thin** — and does no harm where the model already wins (ceiling, 0
regressions). See [`../evals/`](../evals/) for raw data behind each.

---

## 6. The breadth target (the four pillars)

The same Intent Contract loop is meant to serve four domains of digital life:

- **Work execution** — turn requests into verified, shipped work.
- **Career strategy** — long-horizon intents, evidence-grounded.
- **AI-learning** — keep current, distill what's durable.
- **Project delivery** — close open loops end-to-end.

Discipline: **close ONE loop end-to-end before chasing breadth.** Phoenix is that first closed loop,
in the coding domain.

---

## 7. Guardrails (why this stays trustworthy)

- **Proactivity is precision-first** — a proactive system that is wrong erodes trust faster than a
  passive one that is silent. Propose, don't act unilaterally.
- **Verification is the hard 80%** — generating an answer is easy; *knowing it's right* is the work.
- **Sealed graders + held-out tasks** — the system never grades itself with a checker it can edit;
  this is what prevents eval overfitting.
- **Frozen weights, evidence-gated improvement** — gains are at the scaffolding layer (skills, memory,
  checks) and must be proven on evidence, not self-declared. The model does not "wake up."
- **Honest framing** — results are reported with their n, their ceilings, and their limits. A null is
  triangulation, not a failure to hide.

---

## 8. Honest limits

This is **radio**, not television. Today's evidence is narrow-domain, small-n, single-model, and still
largely *reactive* rather than proactive. Turning the signal into the picture requires: replication to
significance, breadth across the four pillars, and a proactive loop that closes one full cycle
end-to-end without a human in every step. The infrastructure that makes the television possible —
objective sensing, bounded healing, an evidence trail, compounding skills — is what Phoenix proves and
ships.

---

_See also: [`../README.md`](../README.md) · [`../BUILDLOG.md`](../BUILDLOG.md) (the honest engineering
record) · [`../evals/`](../evals/) (raw data per hypothesis)._
