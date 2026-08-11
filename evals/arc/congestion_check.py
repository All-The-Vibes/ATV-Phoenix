"""Does the harness tell congestion apart from a real error?

A run is worth roughly four million tokens and two hours. It ends early for
exactly two honest reasons -- it won, or it spent its budget -- and one
dishonest one: the endpoint was busy and we read that as the agent giving up.

Measured on a four-run batch, every member of which died the dishonest way:

    lp85: three model calls failed in a row; stopping the run rather than
          burning 90 turns in silence

lp85 was at 7/8 with two deaths and 454 actions against a human baseline of
388. It had ninety turns left. What actually happened was an APITimeoutError
under load: the retry ladder matched only "429" and "rate limit", so a timeout
skipped backoff entirely and burned one of the three strikes that end a run.
All four runs in the batch recorded `stopped: "max_turns"` while sitting at a
third of their turn budget.

The classifier is one boolean buried in an except block, which is precisely the
kind of thing that rots without anyone noticing. This check runs free and
offline and pins both directions: congestion must be retried, and a genuine
bug must NOT be, because retrying a real error forty times just hides it for
eighty minutes.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc import codeact_agent  # noqa: E402


# What the endpoint says when it is busy. Every one of these has to reach the
# backoff ladder.
CONGESTION = [
    "Error code: 429 - Requests to the ChatCompletions_Create Operation under "
    "Azure OpenAI API have exceeded token rate limit",
    "Rate limit reached for gpt-5.6-sol",
    "Request timed out.",
    "APITimeoutError: Request timed out.",
    "The request timed out after 600 seconds",
    "Connection error.",
    "peer closed connection without sending complete message body",
    "Error code: 503 - Service temporarily unavailable",
    "Error code: 500 - The server had an error processing your request",
    "The engine is currently overloaded, please try again later",
    # A credential refresh under load is congestion wearing a third name. Three
    # concurrent runs refresh against one Azure CLI, contend, and one loses. Measured:
    # ar25 was at 5/8 with level 5 cleared in 59 actions -- still solving, and solving
    # fast -- when three of these in a row spent all three model-failure strikes and
    # ended the run. It was filed as `model_failures`, which reads as the model
    # breaking rather than as a token that was busy for ninety seconds.
    "CredentialUnavailableError: Failed to invoke the Azure CLI",
    "CredentialUnavailableError: Azure CLI not found on path",
    "ClientAuthenticationError: token expired and refresh failed",
]

# What a real defect says. None of these should be retried -- forty naps would
# turn a five-second failure into eighty minutes of silence.
GENUINE = [
    "Error code: 400 - This model's maximum context length is 272000 tokens, "
    "however you requested 289431 tokens",
    "Error code: 401 - Access denied due to invalid subscription key",
    "Error code: 404 - The API deployment for this resource does not exist",
    "AttributeError: 'NoneType' object has no attribute 'choices'",
    "KeyError: 'usage'",
]


def _classifier():
    """Lift the congestion test out of play() so we can exercise it directly.

    Reading it out of the source rather than importing a helper is deliberate:
    the bug being pinned was that the live expression drifted from what the
    comments claimed. A copy in the test would have stayed green through it.
    """
    src = inspect.getsource(codeact_agent.play)
    match = re.search(r"congested = \(\n(.*?)\n\s*\)\n", src, re.S)
    if not match:
        raise AssertionError(
            "could not find the `congested = (...)` expression in play(); if it "
            "was renamed or inlined, this check needs updating -- do not delete it"
        )
    expr = "(" + match.group(1) + ")"

    def classify(message: str) -> bool:
        return bool(eval(expr, {}, {"text": message.lower()}))  # noqa: S307

    return classify


def main() -> int:
    classify = _classifier()
    bad = 0

    print("congestion -- must reach the backoff ladder:")
    for message in CONGESTION:
        ok = classify(message)
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {message[:74]}")

    print("\ngenuine failure -- must NOT be retried:")
    for message in GENUINE:
        ok = not classify(message)
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {message[:74]}")

    src = inspect.getsource(codeact_agent.play)

    print("\nhow a starved run records itself:")
    for label, needle in (
        ("starvation names itself", 'stopped = "rate_limited"'),
        ("model failure names itself", 'stopped = "model_failures"'),
    ):
        ok = needle in src
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label} ({needle})")
    print("       both used to leave `stopped` at its initial \"max_turns\", so a run")
    print("       killed at turn 29 of 160 was filed as one that used its whole budget")

    ladder = re.search(r"for attempt in range\((\d+)\):", src)
    depth = int(ladder.group(1)) if ladder else 0
    ok = depth >= 40
    bad += not ok
    print(f"\n  {'PASS' if ok else 'FAIL'}  ladder runs {depth} attempts before conceding "
          f"(ten was ~12 minutes; six concurrent runs share one TPM allowance)")

    print("\n" + ("ALL GREEN" if not bad else f"{bad} FAILURE(S)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
