---
type: Phoenix Skill
name: phoenix-typescript
description: TypeScript craft where the type-checker IS the objective gate — treat `tsc --noEmit` as a phoenix_sense check, work strict, derive types instead of duplicating them, and eliminate `any`/unsafe casts. Grounded in Mat Pocock's (Total TypeScript) philosophy that types exist to power a fast feedback loop. Use on any TypeScript/JavaScript change, when configuring a TS project, or when the user says /phoenix-typescript, "fix the types", or "make it type-safe".
license: MIT
---

# phoenix-typescript — the type-checker is a phoenix_sense gate

> Encodes [Mat Pocock's / Total TypeScript](https://www.totaltypescript.com) philosophy: TypeScript
> wasn't built to make JS "strongly typed" — it was built to give JS a **fast, powerful feedback loop**.
> Phoenix treats that loop as a first-class objective check.

## Overview
The TypeScript language server and `tsc` form exactly the kind of objective signal Phoenix runs on: you
write code, the checker gives instant pass/fail, you adjust — all before runtime. So in Phoenix,
**`tsc --noEmit` is a `phoenix_sense` check**, on equal footing with tests. A change isn't done because
it "looks typed"; it's done when the type check is green.

## The gate
```
{"check":{"kind":"command_exit","target":["npx","tsc","--noEmit"],"expect":0}}
```
Run it as the inner-loop check for any TS edit (alongside the test gate). Red `tsc` = not done.

## The feedback loop

```
  edit .ts ──► tsc --noEmit (phoenix_sense) ──► ok? ──yes──► run tests ──► done
                     │                            no
                     ▼
              read the type error (DATA, not a nuisance)
                     │
                     ▼
              fix the TYPE, not @ts-ignore the symptom ──► re-sense
```

## Craft rules (each keeps the gate meaningful)
1. **Work strict.** `"strict": true` (and `noUncheckedIndexedAccess`) in `tsconfig.json`. Strictness is
   what makes the green check *mean* something; a loose config is a gate that can't fail.
2. **Kill `any` and unsafe casts.** `any` disables the checker locally — it's a hole in the gate. Prefer
   `unknown` + narrowing. An `as` cast asserts a truth the compiler can't verify; treat every cast as a
   place a real bug can hide, and justify it.
3. **Derive, don't duplicate.** One source of truth for a shape; derive the rest with `typeof`, indexed
   access (`T["field"]`), `Parameters`, `ReturnType`, `Pick`/`Omit`, `as const`. Duplicated types drift
   out of sync silently — exactly the failure types exist to prevent.
4. **Type the boundaries.** Validate external/untrusted data (API responses, params) at the edge (a
   schema validator), so the typed core can trust its inputs. Inside, let inference do the work — don't
   annotate what TS already knows.
5. **No `@ts-ignore` / `@ts-expect-error` to pass the gate.** Silencing the checker to get green is the
   TS equivalent of editing the test to match broken code. Fix the type. If a suppression is truly
   necessary, it needs a comment explaining why and a `phoenix_sense` test of the runtime behavior.

## The Pocock move: let the types catch the refactor
Before changing a function signature, change the type first and let `tsc` show you every call site that
breaks — that error list *is* your blast radius, for free. (Pair with `phoenix-context` for runtime call
graphs the type system can't see.)

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll just use `any` to get unblocked." | `any` punches a hole in the gate; the bug it hides surfaces at runtime where it's expensive. Use `unknown` + narrow. |
| "`@ts-ignore` makes the error go away." | It hides the error, not the bug — like editing a test to pass. Fix the type. |
| "The types look right, I'll skip `tsc`." | "Look right" is self-grading. Run `tsc --noEmit` — it's the objective check, and it's fast. |
| "I'll duplicate this type, it's quicker." | Duplicated types drift apart silently; the next change updates one and not the other. Derive from one source. |
| "Strict mode is too noisy." | The noise is real bugs the loose config was hiding. Strict is what makes green trustworthy. |

## Red Flags
- A new `any` or `as` cast with no justification. → Replace with `unknown`+narrowing, or justify the cast.
- `@ts-ignore`/`@ts-expect-error` added to make `tsc` pass. → Fix the type; suppressions are gate holes.
- The same shape typed in two places. → Derive one from the other.
- Claiming done without a green `tsc --noEmit`. → Run the type gate; it's a `phoenix_sense` check.

## Next
Combine with `phoenix-test` (runtime behavior gate), `phoenix-build` (surgical edits), and `phoenix-craft`
(simplicity). The two gates together — `tsc --noEmit` + tests — are a strong objective definition of done.
