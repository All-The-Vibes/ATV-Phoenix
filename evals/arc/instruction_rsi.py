"""RSI on the ARC agent's own instruction: propose, measure, adopt only on gain.

WHAT WAS MISSING. `phoenix_learn.optimize` is a working reflective hill-climb --
bounded anchored edits, a learning-rate budget, a leakage firewall, and
`gate.decide` as the adoption verdict. `evals/arc` already imports
`phoenix_learn.gate`, `.accept` and `.split`. It imports `.optimize` nowhere. The
proposer half of the loop was built and never connected, which left the single
most leveraged artifact in the harness -- the system prompt that steers every
run -- a frozen constant only a human could edit.

That is the wrong thing to leave frozen. Same-class models score 0.18-0.51%
under ARC Prize's harness and 95.5% under Prime Agent's; this repo's corpus went
0.43% -> 31.18% with the model held constant. Every point came from someone
editing harness text by hand. This module is the machine doing that, under the
same gate a human change has to pass.

THE INVARIANTS, because an optimizer that edits its own instructions is exactly
where a loop can fool itself:

  * BOUNDED. Edits are anchored substrings under a learning-rate budget, so a
    generation nudges the instruction rather than rewriting it. An unanchored
    edit raises instead of silently corrupting the file every run depends on.
  * MEASURED, NOT ASSERTED. Adoption is `phoenix_learn.gate.decide` on held-out
    corpus evidence. The proposer's confidence is not evidence and never
    adopts anything.
  * REVERSIBLE. Every adopted generation is written whole to `history/`, so any
    regression is one file copy away from undone, and the lineage is auditable
    rather than a claim.
  * THE INCUMBENT IS THE DEFAULT. If nothing has been adopted, the agent runs
    the hand-written SYSTEM prompt exactly as before. This can only ever add.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from phoenix_learn.gate import decide
from phoenix_learn.optimize import apply_edits

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "eval" / "arc-results" / "instruction"
ACTIVE = HOME / "active.md"
HISTORY = HOME / "history"
LEDGER = HOME / "lineage.jsonl"

#: Characters of edit per generation. Small on purpose: the failure mode of a
#: self-editing prompt is a rewrite that scores differently for reasons nobody
#: can attribute, and a hill-climb only works if the steps are small enough that
#: the measurement means something.
LR_BUDGET = 400

#: A generation must beat the incumbent by more than this to be adopted. Wave
#: deltas of +/-0.05pp are routine noise in this loop; demanding half a point
#: keeps the lineage from drifting on coin flips.
MIN_GAIN_PP = 0.5


def load_active() -> str:
    """The instruction in force: the adopted one, else the hand-written seed.

    Falling back to `codeact_agent.SYSTEM` is what makes this additive. Nothing
    adopted yet means the agent runs exactly what it ran before.
    """
    if ACTIVE.exists():
        text = ACTIVE.read_text(encoding="utf-8").strip()
        if text:
            return text
    from evals.arc.codeact_agent import SYSTEM

    return SYSTEM


def propose(target: str, edits: list[dict], *, lr_budget: int = LR_BUDGET):
    """Apply bounded edits to `target`, returning the candidate and what happened.

    Thin pass-through to `phoenix_learn.optimize.apply_edits` so the ARC side
    gains no second copy of the edit semantics -- the budget rejection and the
    fail-closed anchor behaviour are the library's, tested there, reused here.
    """
    return apply_edits(target, edits, lr_budget=lr_budget)


def verdict_for(*, incumbent: float, candidate: float, n: int) -> dict:
    """Should this candidate replace the incumbent? Held-out evidence decides.

    `incumbent` and `candidate` are corpus RHAE fractions measured over the same
    games. `n` is how many games were scored -- a one-game swing is not a result
    on a 25-game corpus, and `decide` is given the sample size rather than being
    asked to trust a single lucky run.
    """
    gain_pp = (candidate - incumbent) * 100
    try:
        ruling = decide(
            baseline=incumbent, candidate=candidate, n=n,
            min_gain=MIN_GAIN_PP / 100.0,
        )
        adopt = bool(ruling.get("adopt", ruling.get("ok", False)))
        why = ruling.get("why") or ruling.get("reason") or "gate.decide"
    except TypeError:
        # The gate's signature is not this module's to pin. Fall back to the
        # same rule the gate encodes -- a real, sample-backed gain -- rather
        # than adopting because a call failed.
        adopt = gain_pp > MIN_GAIN_PP and n >= 3
        why = (f"{gain_pp:+.2f}pp over {n} games, "
               f"threshold {MIN_GAIN_PP}pp")
    if gain_pp <= MIN_GAIN_PP:
        adopt = False
        why = f"{gain_pp:+.2f}pp does not clear the {MIN_GAIN_PP}pp threshold"
    return {"adopt": adopt, "gain_pp": round(gain_pp, 3), "n": n, "why": why}


def adopt(candidate: str, *, incumbent_score: float, candidate_score: float,
          n: int, note: str = "") -> dict:
    """Install `candidate` as the active instruction IF the gate says so.

    Refusal is a normal outcome and is recorded, because a lineage that only
    logs its wins cannot tell a working hill-climb from a lucky one.
    """
    ruling = verdict_for(incumbent=incumbent_score,
                         candidate=candidate_score, n=n)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    HOME.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)

    if ruling["adopt"]:
        if ACTIVE.exists():
            shutil.copy2(ACTIVE, HISTORY / f"{stamp}-superseded.md")
        (HISTORY / f"{stamp}-adopted.md").write_text(candidate, encoding="utf-8")
        tmp = ACTIVE.with_suffix(".tmp")
        tmp.write_text(candidate, encoding="utf-8")
        tmp.replace(ACTIVE)
    else:
        (HISTORY / f"{stamp}-rejected.md").write_text(candidate, encoding="utf-8")

    entry = {
        "at": stamp, "adopted": ruling["adopt"], "why": ruling["why"],
        "incumbent": round(incumbent_score, 6),
        "candidate": round(candidate_score, 6),
        "gain_pp": ruling["gain_pp"], "games": n,
        "chars": len(candidate), "note": note,
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def revert() -> bool:
    """Drop back to the hand-written seed. The escape hatch has to be one call."""
    if not ACTIVE.exists():
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    HISTORY.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ACTIVE, HISTORY / f"{stamp}-reverted.md")
    ACTIVE.unlink()
    return True
