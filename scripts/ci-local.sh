#!/bin/sh
# Canonical LOCAL CI gate for ATV-Phoenix.
#
# Mirrors what .github/workflows/rust.yml + okf.yml used to enforce in the cloud, run
# locally so the project spends ~zero GitHub Action credits (the credit constraint).
# Exits non-zero on the first failure. Invoked by .githooks/pre-push and runnable by hand.
set -e

cd "$(dirname "$0")/.."

# Resolve a python interpreter (Windows git-bash may expose `py`, not `python`).
PY="python"
command -v "$PY" >/dev/null 2>&1 || PY="py"
command -v "$PY" >/dev/null 2>&1 || { echo "ci-local: no python interpreter found on PATH"; exit 2; }

echo "== [1/4] cargo test --locked (full suite incl. install-integrity regression) =="
cargo test --locked

echo "== [2/4] pytest tests/okf =="
"$PY" -m pytest tests/okf -q

echo "== [3/4] okf_validate (committed code bundle) =="
"$PY" skills/phoenix-okf/scripts/okf_validate.py examples/okf-code-graph

echo "== [4/4] okf_validate (committed external bundle, strict links) =="
"$PY" skills/phoenix-okf/scripts/okf_validate.py examples/okf-external-demo --strict-links

echo "ci-local: ALL GREEN"
