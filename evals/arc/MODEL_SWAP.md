# Swapping the model

The agent talks to whatever OpenAI-compatible endpoint the environment names. No
edit to `codeact_agent.py` is needed, which matters because an edit is a chance to
break a corpus that is mid-run.

## Azure (default)

Nothing to set. `ARC_PROVIDER` unset means Azure, `DefaultAzureCredential` for auth,
and `max_completion_tokens` as the output cap — the spelling Azure requires.

```powershell
python -m evals.arc.codeact_agent --games cd82 --max-turns 120 --patience 25 `
  --out eval/arc-results/cd82-x.json --trace eval/arc-results/trace-cd82-x.jsonl
```

## Fireworks (Kimi K3 and anything else they host)

```powershell
$env:ARC_PROVIDER   = "fireworks"
$env:FIREWORKS_API_KEY = "<key>"
$env:AOAI_DEPLOYMENT = "accounts/fireworks/models/kimi-k3"   # exact Fireworks model id

python -m evals.arc.codeact_agent --games cd82 --max-turns 120 --patience 25 `
  --out eval/arc-results/cd82-k3.json --trace eval/arc-results/trace-cd82-k3.jsonl
```

`ARC_BASE_URL` overrides the endpoint if Fireworks moves it. `--deployment` on the
command line overrides `AOAI_DEPLOYMENT`.

Two things change automatically with the provider, and both are things that would
otherwise fail at turn 1 of a two-hour run:

- **auth** — API key and `base_url` instead of a bearer token
- **the output-cap parameter** — `max_tokens`, because OpenAI-compatible hosts reject
  Azure's `max_completion_tokens`

A missing key raises at startup rather than after the first model call.

## Verify before spending a run

```powershell
python evals\arc\provider_check.py
```

Reports which provider is configured, which token parameter will be sent, and makes
one real call. Roughly a second and a few tokens; it has already caught the two
failure modes above.

## Choosing the test game

Pick a game with a **known result under the current model**, so the comparison means
something. `cd82` is the reference: 6/6 in 394 actions, 61.68%, and it has been run
many times, so its variance is understood. `sb26` (7/8, 73.74%) is the other.

Do **not** first-test a model on a game we have never cleared. A 0/9 on `bp35` says
nothing about the model — we do not clear it either.

## Reading the result

```powershell
python evals\arc\standings.py
```

Compare `level_actions` and `actions_spent` against the same game's existing card,
not just the level count. RHAE squares the action count, so a model that clears the
same levels in half the actions is worth far more than one that clears one extra
level slowly.
