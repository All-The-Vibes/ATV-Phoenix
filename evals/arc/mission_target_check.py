"""Is the mission target still the mission target?

WHY THIS IS A CHECK AND NOT A COMMENT. On 2026-08-16 an agent -- me -- measured
what the CURRENT harness asymptotes to (~50% corpus), and then reported that
95.5% was unreachable and should be retargeted. Those are two different claims
and only the first was measured. Prime Agent scores 95.5% on these exact 25
public games with 183/183 levels and a public scorecard, so the second claim was
refuted by a document already sitting in this repo.

The failure mode is specific and it recurs: an agent hits a plateau, measures
the plateau honestly, and then quietly relabels it a ceiling. Prose in a charter
does not stop that -- the agent writes plausible prose right past it. A check
that fails does.

So this pins the target NUMERICALLY in every instrument that reports it. Lower
the bar anywhere and the build goes red. Raising it is fine; the point is that
the target may not drift DOWN toward whatever the build currently reaches.

Evidence the bar is real, kept here so it travels with the check: ARC Prize's
own harness scores frontier models at 0.18-0.51% while Prime Agent reaches 95.5%
with the same class of model -- a ~200x swing from scaffolding alone. This
repo's corpus went 0.43% -> 31.18% with the model held constant. The gap is
harness engineering.

Offline. No network, no scorecards.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Prime Agent's published RHAE Best@1 on the 25 public games, 183/183 levels.
#: https://www.primeintellect.ai/blog/prime-agent  (August 2026)
TARGET = 0.955

#: Every instrument that reports the gap. If one of these drifts, some report
#: starts flattering us, which is how a target gets lowered without a decision.
CONSTANTS = {
    "evals/arc/standings.py": "PRIME_AGENT",
    "evals/arc/corpus_watch.py": "PRIME_AGENT",
    "evals/arc/wavewatch.py": "PRIME_AGENT",
}

#: The charter clause that says a target is not an agent's to renegotiate.
CHARTER = "AGENTS.md"
CHARTER_MARK = "Targets are fixed; the HARNESS is the variable"


def main() -> int:
    failures: list[str] = []

    for rel, name in CONSTANTS.items():
        path = ROOT / rel
        if not path.exists():
            failures.append(f"{rel} is missing; the gap is reported from somewhere else now")
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(rf"^{name}\s*=\s*([0-9.]+)", body, re.M)
        if not match:
            failures.append(f"{rel}: {name} not found -- the target constant was renamed or removed")
            continue
        value = float(match.group(1))
        status = "ok" if value == TARGET else "DRIFTED"
        print(f"  {rel:<32} {name} = {value}   {status}")
        if value < TARGET:
            failures.append(
                f"{rel}: {name} = {value}, BELOW the {TARGET} target. "
                f"A target is not lowered to meet the build."
            )
        elif value != TARGET:
            failures.append(f"{rel}: {name} = {value}, expected {TARGET}")

    charter = ROOT / CHARTER
    if not charter.exists() or CHARTER_MARK not in charter.read_text(
            encoding="utf-8", errors="replace"):
        failures.append(
            f"{CHARTER} no longer carries the clause '{CHARTER_MARK}'. "
            f"That clause is what makes this check mean something."
        )
    else:
        print(f"  {CHARTER:<32} clause present                ok")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        print("\n  The target is Prime Agent's 95.5% and the method is RSI: evolve")
        print("  the harness until it clears the bar. A plateau of the current")
        print("  harness is a fact about the harness, not about the target.")
        return 1

    print(f"\nOK    target held at {TARGET:.1%} across every instrument")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
