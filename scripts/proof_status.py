#!/usr/bin/env python3
"""
scripts/proof_status.py -- decide whether a pull request's proof workflows actually ran.

Issue #138: GitHub holds Actions runs at conclusion `action_required` on pull requests
authored by the Copilot coding agent. Nobody approves them, so they never execute. Ten pull
requests merged on 2026-07-31 and 2026-08-01 took that path. They were still verified, by
hand, in a scratch worktree. That is real verification and it depends on a person
remembering to do it, which is the property CI exists to remove.

This script does not choose between the three fixes #138 lists. It answers the question all
three need answered: did the proofs for this head SHA actually execute, or does the merge
rest on someone's memory? Feed it the check-run payload and the changed-file list:

    gh api repos/OWNER/REPO/commits/<sha>/check-runs > runs.json
    gh pr view <n> --json files --jq '[.files[].path]' > files.json
    python scripts/proof_status.py --check-runs runs.json --changed-files files.json

Exit 0 when every required proof reached success. Exit 1 when one is missing, held at
`action_required`, or failed. Exit 2 on bad input.

`Phoenix proof` has no path filter in .github/workflows/phoenix-proof.yml, so it is required
on every pull request. `Connector proof` carries a paths: block, so it is required only when a
changed file matches it. Demanding it unconditionally would flag every docs pull request.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import sys

PHOENIX_PROOF = "Phoenix proof"
CONNECTOR_PROOF = "Connector proof"

# Mirrors the paths: block of .github/workflows/connector-proof.yml.
CONNECTOR_PATHS = (
    "phoenix_learn/**",
    "src/**",
    "tests/test_phoenix_learn*.py",
    "tests/test_connector_proof_ci.py",
    "Cargo.toml",
    "Cargo.lock",
    "build.rs",
    ".github/workflows/connector-proof.yml",
)

HELD = "action_required"


def matches_connector_paths(changed_files) -> bool:
    for path in changed_files:
        normalized = path.replace("\\", "/")
        for pattern in CONNECTOR_PATHS:
            if pattern.endswith("/**"):
                if normalized.startswith(pattern[:-2]):
                    return True
            elif fnmatch.fnmatch(normalized, pattern):
                return True
    return False


def _runs_named(check_runs, name):
    return [r for r in check_runs if r.get("name") == name]


def evaluate(check_runs, changed_files):
    """Return (ok, list_of_problem_strings). Pure, so the tests need no network."""
    required = [PHOENIX_PROOF]
    if matches_connector_paths(changed_files):
        required.append(CONNECTOR_PROOF)

    problems = []
    for name in required:
        runs = _runs_named(check_runs, name)
        if not runs:
            problems.append(
                f"{name}: no run recorded for this head sha, so nothing verified this change"
            )
            continue
        newest = runs[-1]
        conclusion = newest.get("conclusion")
        status = newest.get("status")
        if conclusion == HELD:
            problems.append(
                f"{name}: held at action_required, which means it was queued and never "
                "executed. A maintainer has to approve the run."
            )
        elif status != "completed":
            problems.append(f"{name}: status is {status!r}, not completed")
        elif conclusion != "success":
            problems.append(f"{name}: conclusion is {conclusion!r}, not success")

    return (not problems), problems


def _load(path, flag):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[proof-status] ERROR: cannot read {flag} {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check-runs", required=True,
                    help="JSON from gh api repos/O/R/commits/<sha>/check-runs")
    ap.add_argument("--changed-files", required=True,
                    help="JSON array of changed file paths")
    ap.add_argument("--json", action="store_true", help="emit a JSON verdict")
    args = ap.parse_args(argv)

    payload = _load(args.check_runs, "--check-runs")
    check_runs = payload.get("check_runs", payload) if isinstance(payload, dict) else payload
    changed_files = _load(args.changed_files, "--changed-files")
    if not isinstance(check_runs, list) or not isinstance(changed_files, list):
        print("[proof-status] ERROR: expected a list of check runs and a list of paths",
              file=sys.stderr)
        return 2

    ok, problems = evaluate(check_runs, changed_files)

    if args.json:
        print(json.dumps({"ok": ok, "problems": problems}))
    elif ok:
        print("[proof-status] PASS: every required proof executed and succeeded")
    else:
        for problem in problems:
            print(f"[proof-status] {problem}")
        print("[proof-status] FAIL: this pull request is gated by memory, not by CI")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
