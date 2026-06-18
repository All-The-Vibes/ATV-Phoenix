---
type: Phoenix Skill
name: phoenix-think
description: The thinking-first stage of the Phoenix lifecycle. Before any code, deeply understand what is actually wanted through Socratic deep interview and evidence-grounded deep research, surface and resolve hidden assumptions, and converge on a crystal-clear intent whose deliverable is a runnable objective acceptance check. Use at the start of any non-trivial task, when an ask is vague or ambiguous, or when the user says /phoenix-think, "think first", "interview me", "don't assume", or "research this before building".
license: MIT
---

# phoenix-think — understand deeply, then define "done" objectively

> _The most expensive bug is building the wrong thing correctly._

Most agents skip straight to code on a half-understood ask and produce something plausible but wrong.
`phoenix-think` is the antidote: it spends cheap thinking-tokens up front to (1) extract what the user
*actually* wants, (2) ground it in real evidence from the codebase and the world, and (3) crystallize
it into an intent whose finish line is a **runnable objective check** — the gate the rest of the
Phoenix lifecycle (plan → build → review → ship) verifies against. No check, no proceed.

This stage is deliberately rich. Rushing it is the false economy this whole harness exists to prevent.

## Three movements (do them in order; loop until clarity)

### 1. ELICIT — Socratic deep interview (extract intent, don't assume it)
Ask **one focused question at a time**, each targeting the highest-uncertainty unknown. Prefer
questions that expose *hidden assumptions* over questions that confirm what you already believe.
Cover, as relevant:
- **Outcome:** What does success look like *to you*? How will *you* know it worked? (push for an
  observable signal, not a feeling)
- **Boundaries:** What is explicitly OUT of scope? What must NOT change or break?
- **Constraints:** performance, privacy, budget (calls/$), reversibility, deadline, who else is affected.
- **Context & priors:** Is there existing code, a convention, a past attempt, a preferred approach?
- **Edge cases & failure:** What inputs/states worry you? What does "wrong" look like?
- **Hidden assumptions:** State the assumptions you're making back to the user and ask them to confirm
  or correct each one. ("I'm assuming X — is that right?")

Track an informal **ambiguity score**: how much could still go wrong if you executed now? Keep
interviewing until that risk is low. Stop early if the user says "just do it" — respect their intent,
but state the top 1–2 assumptions you're proceeding on.

### 2. GROUND — evidence-grounded deep research (replace guesses with facts)
Do not theorize on assumptions. Investigate before deciding:
- **Codebase:** read the relevant code, conventions, tests, and prior art. Use structural retrieval
  (the bundled TokenMasterX graph: who-calls / what-breaks-if-I-change) to find the real blast radius
  instead of grepping blind. Identify the existing pattern to follow, not a generic default.
- **Project memory/conventions:** check for project-specific rules the model can't guess (naming,
  formats, idioms). A correct-looking default that violates a convention is a silent failure (see H3).
- **External (when the task needs it):** verify SDK/framework/API behavior against primary docs, not
  recall. Cite what you find; flag anything you could not verify as *unverified*.
- Record what you learned and — crucially — **what you still don't know.** Unknowns are honest and
  steer the next interview question.

### 3. CRYSTALLIZE — the Intent Contract + the acceptance gate (the Phoenix payload)
Converge everything above into a short, explicit contract:
```
INTENT (raw):       <the user's words, verbatim — never silently reinterpret>
GOAL (world-state): <the observable end-state: "X is true", not "do X">
ACCEPTANCE CHECK:   <a runnable phoenix_sense check that passes iff the goal is met>
                    e.g. {"kind":"command_exit","target":["pytest","-q","tests/test_x.py"],"expect":0}
CONSTRAINTS:        privacy · budget · reversibility · scope-out
ASSUMPTIONS:        <confirmed-with-user list; the risks you're proceeding on>
OPEN QUESTIONS:     <what's still unknown, and how you'll resolve it>
```
The **acceptance check is the deliverable of this stage.** It is what `phoenix-ship` will re-run before
anyone is allowed to say "done." If no test exists yet, the contract names "write that test" as the
first build step — because the check *defines* done.

## The hard rule
Do not hand off to `phoenix-plan` until you have an acceptance check you could **run today and watch
fail** on the unbuilt work. A gate that cannot fail measures nothing. If success genuinely cannot be
made objective (a pure judgment call), say so explicitly and name the strongest objective proxy you
can — never pretend a vibe is a verified outcome.

## Calibrate the depth (don't over-interview a trivial ask)
- **Trivial / precise ask** (file paths, exact behavior, existing acceptance criteria): skip the
  interview, do a quick codebase ground-check, write the one-line check, proceed.
- **Standard ask:** a few sharp questions + a focused codebase read.
- **Vague / high-stakes / "interview me":** the full three movements, multiple interview rounds, deep
  research, explicit assumption confirmation.

## Honesty
Surface assumptions instead of burying them. Report "unknown" rather than guessing. The output of good
thinking is not certainty — it is a *correctly-scoped* intent with an objective finish line and the
risks named out loud.

## Next
Hand the Intent Contract to **`phoenix-plan`**, which decomposes it into small, individually-verifiable
steps that compose up to the acceptance check.
