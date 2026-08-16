"""Will this model actually answer before we spend two hours finding out?

A provider swap has two failure modes and both surface at turn 1 of a long run:
the credential is wrong, or the output-cap parameter has the other provider's name
(`max_completion_tokens` on Azure, `max_tokens` everywhere else). Both cost the
whole run to discover the slow way.

Costs one real call and a few tokens.

    python evals/arc/provider_check.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evals.arc.codeact_agent import DEPLOYMENT, ENDPOINT, _TOKEN_LIMIT, make_client  # noqa: E402


def main() -> int:
    provider = os.environ.get("ARC_PROVIDER", "azure").lower()
    param = next(iter(_TOKEN_LIMIT))
    compat = provider in ("fireworks", "openai", "compat")

    print(f"provider   : {provider}")
    print(f"model      : {DEPLOYMENT}")
    print(f"endpoint   : {os.environ.get('ARC_BASE_URL') or ('fireworks default' if compat else ENDPOINT)}")
    print(f"token param: {param}")
    print(f"auth       : {'API key' if compat else 'DefaultAzureCredential'}")

    if compat and not (os.environ.get("FIREWORKS_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("\nFAIL  no FIREWORKS_API_KEY / OPENAI_API_KEY set")
        return 1
    if compat and param != "max_tokens":
        print(f"\nFAIL  compatible host will reject {param!r}; expected max_tokens")
        return 1
    if not compat and param != "max_completion_tokens":
        print(f"\nFAIL  Azure requires max_completion_tokens, not {param!r}")
        return 1

    print("\ncalling the model...")
    started = time.time()
    try:
        client = make_client()
        reply = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            **_TOKEN_LIMIT,
        )
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__} after {time.time() - started:.1f}s")
        print(f"      {str(exc)[:300]}")
        return 1

    text = (reply.choices[0].message.content or "").strip()
    print(f"PASS  answered in {time.time() - started:.1f}s -> {text[:60]!r}")

    # A model that cannot write a fenced python block cannot play this game at all:
    # the turn loop extracts ```python ... ``` and a reply without one is a lost turn.
    print("\nchecking it can emit a fenced python block...")
    try:
        reply = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{
                "role": "user",
                "content": "Reply with ONLY a python code block that prints the number 7.",
            }],
            **_TOKEN_LIMIT,
        )
        body = reply.choices[0].message.content or ""
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {str(exc)[:200]}")
        return 1

    if "```" not in body:
        print("FAIL  no fenced block came back; the turn loop parses ```python ... ```")
        print(f"      got: {body[:160]!r}")
        return 1
    print("PASS  fenced block returned")
    print("\nprovider ready. Pick a game with a known result -- cd82 (6/6, 61.68%) --")
    print("so the comparison measures the model rather than the game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
