"""phoenix_learn.optimize — the candidate-proposing optimizer behind the measured-gain gate.

Ported from the live Goose continuous-learning loop (goose/tools/sia_h_run.py:run). This is the
*proposer* that feeds the gate shipped in issue #7: a GEPA-style generational loop that

  1. synthesizes a gen_0 instruction from PUBLIC prompts only (or takes a hand `seed`),
  2. reflect/mutates it against PUBLIC failures across generations,
  3. SELECTS the best generation on the DEV split (never on PRIVATE),
  4. scores the held-out PRIVATE split EXACTLY ONCE (gen_0 baseline + the selected candidate),
  5. runs the leakage firewall + anti-gaming lint, and
  6. routes the measured result through `phoenix_learn.gate.decide`.

It PROPOSES; it never adopts. The verdict is advisory — adoption stays a human-gated step behind a
`phoenix_accept` red->green trace (see AGENTS.md). Every model touch point is an injected callable
(`call_fn` / `meta_fn` / `edit_fn` / `grade_fn`), so the orchestration is deterministic, offline, and
zero-LLM under test; wiring real LLM defaults is a separate (CLI) concern, intentionally out of this
module so the library never reaches the network on import.
"""
from __future__ import annotations

from .gate import decide, transitions
from .split import forbidden_strings, lint_target, split_fixture


def split_diagnostics(pub, dev, priv):
    """Per-split row counts + grader-family histogram (selection/audit metadata, PUBLIC-safe)."""
    def fam(rows):
        c = {}
        for r in rows:
            m = r.get("grader", {}).get("match", "normalized")
            c[m] = c.get(m, 0) + 1
        return c
    return {"public_n": len(pub), "dev_n": len(dev), "private_n": len(priv),
            "public_match": fam(pub), "dev_match": fam(dev), "private_match": fam(priv)}


# --------------------------------------------------------------------------- prompts (PUBLIC only)
def build_meta_prompt(public_rows, k=4):
    """Synthesize a gen_0 instruction from a sample of PUBLIC prompts only (no answers, no held-out)."""
    sample = "\n".join(f"  - {r['intent']}" for r in public_rows[:k])
    return ("You are designing a concise, REUSABLE instruction that an AI will prepend to each "
            "of the following kinds of tasks to maximize correctness. Representative task prompts "
            f"(no answers given):\n{sample}\n\n"
            "Write a short, GENERAL procedure the AI should follow (e.g. restate constraints, "
            "solve, self-check every constraint before answering). Do NOT reference any specific "
            "task wording verbatim. Output ONLY the instruction text.")


def build_feedback_prompt(target, public_results):
    """Reflect/mutate prompt built from PUBLIC outcomes ONLY (dev/private never enter the loop)."""
    lines = "\n".join(
        f"  [{'OK' if r['ok'] else 'WRONG'}] task={r['intent']!r} model_answered={r['got']!r}"
        for r in public_results)
    return ("Here is the current instruction:\n---\n" + target + "\n---\n\n"
            "It was prepended to these tasks with these outcomes:\n" + lines + "\n\n"
            "Rewrite the instruction to fix the WRONG cases WITHOUT overfitting to any specific "
            "input (stay general; do not hard-code answers or memorize task wording). "
            "Output ONLY the improved instruction text.")


# --------------------------------------------------------------------------- scoring (audited grader)
def score(target, rows, call_fn, grade_fn):
    """Prepend `target` to each row's intent, call the model, grade with the AUDITED grader."""
    results, correct = [], 0
    for row in rows:
        fmt = row.get("grader", {}).get("answer_format", "answer")
        prompt = (target + "\n\n" + row["intent"]
                  + f"\n\nReply with ONLY the final answer. End with a line: ANSWER: <{fmt}>")
        text, cost = call_fn(prompt)
        ok, got = grade_fn(row, text)
        correct += 1 if ok else 0
        results.append({"intent": row["intent"], "got": got, "ok": ok, "cost": cost})
    acc = correct / len(rows) if rows else 0.0
    return {"acc": acc, "correct": correct, "n": len(rows), "results": results}


# --------------------------------------------------------------------------- bounded edits (SkillOpt-style proposer)
def _normalize_edit(edit):
    if not isinstance(edit, dict):
        raise ValueError("edits must be dicts")
    op = edit.get("op")
    anchor = edit.get("anchor")
    text = edit.get("text", "")
    if op not in {"add", "delete", "replace"}:
        raise ValueError(f"unknown edit op: {op!r}")
    if not isinstance(anchor, str) or not anchor:
        raise ValueError("edit anchor must be a non-empty string")
    if op in {"add", "replace"} and not isinstance(text, str):
        raise ValueError("edit text must be a string")
    if op == "delete":
        text = ""
    return {"op": op, "anchor": anchor, "text": text}


def _edit_fingerprint(edit):
    return (edit["op"], edit["anchor"], edit["text"])


def _edit_cost(edit):
    if edit["op"] == "add":
        return len(edit["text"])
    if edit["op"] == "delete":
        return len(edit["anchor"])
    return max(len(edit["anchor"]), len(edit["text"]))  # replace


def _apply_single_edit(target, edit):
    idx = target.find(edit["anchor"])
    if idx < 0:
        raise ValueError(f"edit anchor not found: {edit['anchor']!r}")
    left = target[:idx]
    right = target[idx + len(edit["anchor"]):]
    if edit["op"] == "add":
        return target[:idx + len(edit["anchor"])] + edit["text"] + right
    if edit["op"] == "delete":
        return left + right
    return left + edit["text"] + right


def apply_edits(target, edits, *, lr_budget, rejected_fingerprints=None):
    """Apply bounded edits with a textual learning-rate budget.

    - `lr_budget` limits total edit-cost per epoch.
    - edits over budget are rejected (not silently applied).
    - malformed edits fail closed via ValueError.
    """
    if lr_budget < 0:
        raise ValueError("lr_budget must be non-negative")
    if rejected_fingerprints is None:
        rejected_fingerprints = set()
    candidate = target
    used = 0
    applied, rejected = [], []
    for raw in edits or []:
        edit = _normalize_edit(raw)
        fp = _edit_fingerprint(edit)
        if fp in rejected_fingerprints:
            continue
        cost = _edit_cost(edit)
        if used + cost > lr_budget:
            rejected.append(edit)
            rejected_fingerprints.add(fp)
            continue
        candidate = _apply_single_edit(candidate, edit)
        applied.append(edit)
        used += cost
    return candidate, applied, rejected, used


# --------------------------------------------------------------------------- the generational loop
def optimize(rows, *, max_gen=3, salt=0, seed=None, name="fixture",
             call_fn=None, meta_fn=None, edit_fn=None, grade_fn=None,
             lr_budget=120, feedback_fn=None):
    """Run the generational propose->select->measure loop and return an advisory gate verdict.

    `rows` is a list of fixture dicts ({"intent", "grader", "task_id"?}). All LLM touch points are
    injected: `call_fn(prompt)->(text, cost)` (required), `grade_fn(row, text)->(ok, got)` (required),
    `meta_fn(public_rows)->(target, cost)` (required unless `seed` is given), and
    `edit_fn(target, public_results, rejected_buffer, lr_budget)->(edits, cost)` (required when
    `max_gen > 1`; if absent, legacy `feedback_fn` is still accepted). The PRIVATE split is scored
    exactly once and never used for selection.
    """
    if call_fn is None or grade_fn is None:
        raise ValueError("optimize() requires call_fn and grade_fn (no implicit LLM is wired)")

    pub, dev, priv = split_fixture(rows, salt)
    diag = split_diagnostics(pub, dev, priv)
    forbidden = forbidden_strings(name, dev, priv)

    cost = 0.0
    # gen_0: a hand seed, else the Meta-Agent synthesizes a target from PUBLIC prompts only.
    if seed is not None:
        target = seed
    else:
        if meta_fn is None:
            raise ValueError("optimize() requires meta_fn when no seed is supplied")
        target, c = meta_fn(pub)
        cost += c

    gens = []           # selection metadata per generation (PUBLIC + DEV only -- never PRIVATE)
    targets = [target]
    rejected_buffer = []
    rejected_fingerprints = set()
    for g in range(max_gen):
        ps = score(target, pub, call_fn, grade_fn)
        ds = score(target, dev, call_fn, grade_fn)
        cost += sum(r["cost"] for r in ps["results"]) + sum(r["cost"] for r in ds["results"])
        gen_row = {"gen": g, "public_acc": ps["acc"], "dev_acc": ds["acc"],
                   "public_correct": ps["correct"], "dev_correct": ds["correct"]}
        if g < max_gen - 1:
            if edit_fn is not None:
                epoch_budget = max(1, int(lr_budget * (max_gen - g - 1) / max(1, max_gen - 1)))
                edits, c = edit_fn(target, ps["results"], list(rejected_buffer), epoch_budget)
                cost += c
                target, applied, rejected, used = apply_edits(
                    target, edits, lr_budget=epoch_budget, rejected_fingerprints=rejected_fingerprints)
                rejected_buffer.extend(rejected)
                gen_row.update({
                    "lr_budget": epoch_budget,
                    "edit_budget_used": used,
                    "applied_edits": len(applied),
                    "rejected_edits": len(rejected),
                })
            elif feedback_fn is not None:  # legacy whole-document fallback
                target, c = feedback_fn(target, ps["results"])   # PUBLIC failures only
                cost += c
            else:
                raise ValueError("optimize() requires edit_fn when max_gen > 1")
            targets.append(target)
        gens.append(gen_row)

    # SELECT the best generation by DEV (fallback PUBLIC when no dev rows) -- NEVER by PRIVATE.
    sel_key = "dev_acc" if dev else "public_acc"
    sel = max(gens, key=lambda x: (x[sel_key], -x["gen"]))
    sel_gen = sel["gen"]
    sel_target = targets[sel_gen]

    # PRIVATE scored ONCE: gen_0 baseline + the selected generation only (no repeated probing).
    g0_priv = score(targets[0], priv, call_fn, grade_fn)
    sel_priv = score(sel_target, priv, call_fn, grade_fn)
    cost += sum(r["cost"] for r in g0_priv["results"]) + sum(r["cost"] for r in sel_priv["results"])
    trans = transitions(g0_priv["results"], sel_priv["results"])

    gaming_hits = lint_target(sel_target, forbidden)
    decision = decide(
        gen0_priv_acc=g0_priv["acc"], sel_priv_acc=sel_priv["acc"],
        sel_priv_correct=sel_priv["correct"], gen0_priv_correct=g0_priv["correct"],
        trans=trans, private_n=len(priv), gaming_hits=gaming_hits)

    return {
        "name": name, "salt": salt, "max_gen": max_gen,
        "split": diag,
        "curve": gens,                         # PUBLIC + DEV accuracy across generations
        "selected_gen": sel_gen, "selected_by": sel_key,
        "selected_target": sel_target,
        "gen0_private_acc": round(g0_priv["acc"], 4), "gen0_private_correct": g0_priv["correct"],
        "selected_private_acc": round(sel_priv["acc"], 4), "selected_private_correct": sel_priv["correct"],
        "private_n": len(priv),
        "private_transitions": trans,
        "gaming_hits": gaming_hits,
        "rejected_edits": rejected_buffer,
        "decision": decision,                  # advisory: the gate decides eligibility, not adoption
        "cost_usd": round(cost, 4),
    }
