"""Does gpt-5.6-sol honour temperature/seed on Azure OpenAI?

The ARC environment is deterministic (arc_agi.Arcade.make defaults to seed=0 and the
level geometry carries no RNG), so every bit of the 69/17/83 spread in level-1 action
counts comes from the model. If sampling can be pinned, interventions become measurable;
if it cannot, every comparison needs N runs and a distributional test instead.

Two identical calls per configuration, compared byte for byte.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ENDPOINT = os.environ.get(
    "AOAI_ENDPOINT", "https://ai-shyamsridhar-2008.cognitiveservices.azure.com/"
)
DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-5.6-sol")

PROMPT = (
    "Invent three unusual two-word names for a colour-matching puzzle game. "
    "Reply with only the three names, comma separated."
)


def client():
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    from evals.arc import aad

    provider = get_bearer_token_provider(aad.credential(), aad.SCOPE)
    return AzureOpenAI(
        azure_endpoint=ENDPOINT,
        azure_ad_token_provider=provider,
        api_version="2024-12-01-preview",
    )


def call(api, **extra):
    reply = api.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": PROMPT}],
        max_completion_tokens=2000,
        **extra,
    )
    return (
        (reply.choices[0].message.content or "").strip(),
        getattr(reply, "system_fingerprint", None),
    )


def main() -> int:
    api = client()
    for label, kwargs in [
        ("no params (current agent behaviour)", {}),
        ("temperature=0, seed=42", {"temperature": 0, "seed": 42}),
    ]:
        print(f"\n=== {label} ===")
        try:
            first, fp1 = call(api, **kwargs)
            second, fp2 = call(api, **kwargs)
        except Exception as exc:
            print(f"  REJECTED: {type(exc).__name__}: {str(exc)[:220]}")
            continue
        print(f"  run 1: {first[:90]}")
        print(f"  run 2: {second[:90]}")
        print(f"  fingerprints: {fp1} / {fp2}")
        print(f"  IDENTICAL: {first == second}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
