#!/bin/sh
# Canonical LOCAL CI gate for ATV-Phoenix.
#
# Mirrors what .github/workflows/rust.yml + okf.yml used to enforce in the cloud, run
# locally so the project spends ~zero GitHub Action credits (the credit constraint).
# Exits non-zero on the first failure. Invoked by .githooks/pre-push and runnable by hand.
#
# scripts/ci-local.ps1 must gate the same targets; tests/test_release_drift.py asserts it.
set -e

cd "$(dirname "$0")/.."

# Resolve a python interpreter (Windows git-bash may expose `py`, not `python`).
PY="python"
command -v "$PY" >/dev/null 2>&1 || PY="py"
command -v "$PY" >/dev/null 2>&1 || { echo "ci-local: no python interpreter found on PATH"; exit 2; }

echo "== [1/8] cargo test --locked (full suite incl. install-integrity regression) =="
cargo test --locked

echo "== [2/8] pytest tests/okf =="
"$PY" -m pytest tests/okf -q

echo "== [3/8] pytest phoenix_learn (C3 measured-gain gate + optimizer) =="
"$PY" -m pytest tests/test_phoenix_learn.py tests/test_phoenix_learn_optimize.py -q

echo "== [4/8] pytest cloud workflow contracts =="
"$PY" -m pytest tests/test_cloud_setup.py tests/test_cloud_proof_workflow.py -q

echo "== [5/8] pytest release metadata (version/badge/changelog consistency + drift) =="
"$PY" -m pytest tests/test_version_consistency.py tests/test_release_drift.py -q

echo "== [6/8] release drift (work shipped since the version bump must be written down) =="
"$PY" scripts/release_drift.py

echo "== [7/8] okf_validate (committed code bundle) =="
"$PY" skills/phoenix-okf/scripts/okf_validate.py examples/okf-code-graph

echo "== [8/8] okf_validate (committed external bundle, strict links) =="
"$PY" skills/phoenix-okf/scripts/okf_validate.py examples/okf-external-demo --strict-links

echo "ci-local: ALL GREEN"
