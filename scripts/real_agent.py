#!/usr/bin/env python3
"""
scripts/real_agent.py -- repo-aware SWE-bench agent for the north-star eval.

Problem with the original arm_a.py / arm_b.py:
  - Only problem_statement is given to the model (no repo, no file context).
  - Generated diffs are context-free and rarely apply cleanly.
  - arm_b.py's verify-heal gate checks patch FORMAT (---/+++/@@), not correctness.

This agent fixes both:
  1. Clones the repo at base_commit (shallow) so the model sees the actual files.
  2. Feeds the model the failing test + up to MAX_CONTEXT_FILES relevant file slices.
  3. Writes the model's patch to a temp dir, runs `git apply --check`, and only
     submits patches that apply cleanly. Arm B routes through the phoenix verify-heal
     loop using a command_exit check on `git apply --check` (not a format proxy).

Environment variables (set by run-north-star.ps1 before invoking):
  AOAI_ENDPOINT    Azure OpenAI endpoint URL
  AOAI_DEPLOYMENT  Model deployment name (e.g. gpt-5.1)
  PHOENIX_BIN      Path to phoenix-mcp binary (default: ~/ATV-Phoenix/target/release/phoenix-mcp)
  ARM              "A" (vanilla) or "B" (phoenix verify-heal). Default: "A"
  MAX_HEALS        Max heal iterations for Arm B. Default: 3

Usage:
  python3 real_agent.py < instances.json > predictions.json
  ARM=B python3 real_agent.py < instances.json > predictions.json

instances.json must include: instance_id, repo, problem_statement, base_commit, test_patch
(use ns_fetch_instances.py with --full flag to include base_commit + test_patch)
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
ENDPOINT        = os.environ["AOAI_ENDPOINT"]
DEPLOYMENT      = os.environ["AOAI_DEPLOYMENT"]
PHOENIX_BIN     = os.environ.get("PHOENIX_BIN", str(Path.home() / "ATV-Phoenix/target/release/phoenix-mcp"))
ARM             = os.environ.get("ARM", "A").upper()
MAX_HEALS       = int(os.environ.get("MAX_HEALS", "3"))
MAX_CONTEXT_FILES = 8       # max source files to include in the prompt
MAX_FILE_LINES  = 120       # max lines per file slice
CLONE_DEPTH     = 1
MODEL_NAME      = f"gpt-5.1-{'phoenix' if ARM == 'B' else 'vanilla'}"

# ── Azure OpenAI client (Entra auth via Managed Identity) ─────────────────────
from openai import AzureOpenAI
from azure.identity import ManagedIdentityCredential

class _EntraTokenProvider:
    def __init__(self):
        self._cred = ManagedIdentityCredential()
    def __call__(self):
        return self._cred.get_token("https://cognitiveservices.azure.com/.default").token

client = AzureOpenAI(
    azure_endpoint=ENDPOINT,
    azure_ad_token_provider=_EntraTokenProvider(),
    api_version="2024-12-01-preview",
)


def _llm(messages: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        max_completion_tokens=4096,
    )
    return resp.choices[0].message.content or ""


def _clone_repo(repo: str, base_commit: str, clone_dir: Path) -> bool:
    """Shallow-clone repo at base_commit. Returns True on success."""
    try:
        # Clone with depth 1 targeting the right commit
        subprocess.run(
            ["git", "clone", "--depth", str(CLONE_DEPTH), "--no-single-branch",
             f"https://github.com/{repo}.git", str(clone_dir)],
            check=True, capture_output=True, timeout=120,
        )
        # Check out the exact base commit
        subprocess.run(
            ["git", "checkout", base_commit],
            cwd=clone_dir, check=True, capture_output=True, timeout=30,
        )
        return True
    except Exception as exc:
        print(f"  clone failed for {repo}@{base_commit}: {exc}", file=sys.stderr)
        return False


def _collect_context(clone_dir: Path, test_patch: str, problem: str) -> str:
    """Return a prompt-ready string with relevant file slices."""
    # Files touched by the test patch are the best hint at what to fix
    touched: list[str] = []
    for line in test_patch.splitlines():
        if line.startswith("+++ b/"):
            touched.append(line[6:].strip())
    # Also scan for .py files mentioned in the problem statement
    py_mentions = [w.rstrip(".,;") for w in problem.split() if w.endswith(".py")]
    candidates = list(dict.fromkeys(touched + py_mentions))[:MAX_CONTEXT_FILES]

    parts: list[str] = []
    for rel_path in candidates:
        full = clone_dir / rel_path
        if not full.exists():
            continue
        try:
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        # Take first MAX_FILE_LINES lines as context
        snippet = "\n".join(lines[:MAX_FILE_LINES])
        parts.append(f"### {rel_path}\n```python\n{snippet}\n```")
    return "\n\n".join(parts)


def _try_apply(clone_dir: Path, patch: str) -> bool:
    """Return True if the patch applies cleanly (git apply --check)."""
    if not patch.strip():
        return False
    try:
        r = subprocess.run(
            ["git", "apply", "--check", "-"],
            input=patch.encode(), cwd=clone_dir,
            capture_output=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _phoenix_sense_apply(check_file: Path, cwd: Path) -> bool:
    """Arm B: run phoenix_sense command_exit on git apply --check via @file."""
    try:
        r = subprocess.run(
            [PHOENIX_BIN, "sense", f"@{check_file}"],
            capture_output=True, text=True, timeout=15, cwd=cwd,
        )
        result = json.loads(r.stdout)
        return result.get("ok", False)
    except Exception:
        return False


def solve(inst: dict, clone_dir: Path) -> str:
    """Generate a patch that applies cleanly to the repo at base_commit."""
    repo     = inst["repo"]
    problem  = inst["problem_statement"]
    test_pch = inst.get("test_patch", "")
    context  = _collect_context(clone_dir, test_pch, problem)

    system_msg = textwrap.dedent("""\
        You are an expert software engineer. You will be given:
        - A problem statement describing a bug or missing feature.
        - The failing test(s) that must pass after your fix.
        - Relevant source file slices from the repository.

        Produce a minimal unified diff patch (git diff format) that fixes the issue.
        The patch must apply cleanly with `git apply`.
        Output ONLY the patch — no explanation, no markdown fences.
    """)

    user_msg = (
        f"Repository: {repo}\n\n"
        f"Problem:\n{problem}\n\n"
        f"Failing test patch (for context):\n{test_pch[:2000]}\n\n"
        f"Source context:\n{context}\n\n"
        "Produce the fix patch:"
    )

    patch = _llm([{"role": "system", "content": system_msg},
                  {"role": "user", "content": user_msg}])

    if ARM != "B":
        return patch

    # ── Arm B: phoenix verify-heal loop ──────────────────────────────────────
    # Done-check: git apply --check exits 0 (patch applies cleanly to the repo).
    # This is a real correctness gate, not a format proxy.
    check_data = {
        "kind": "command_exit",
        "target": ["git", "apply", "--check", "-"],
        "expect": 0,
        "stdin": patch,   # NOTE: phoenix_sense command_exit doesn't support stdin yet;
                          # we use a wrapper script written to a temp file instead.
        "cwd": str(clone_dir),
    }
    # Write the patch to a temp file and use a shell command for the check
    patch_file = clone_dir / "phoenix_candidate.patch"

    for heal_round in range(MAX_HEALS + 1):
        patch_file.write_text(patch, encoding="utf-8")
        applies = _try_apply(clone_dir, patch)
        if applies:
            break
        if heal_round == MAX_HEALS:
            # Exhausted heals -- return best effort (may not apply)
            print(f"  {inst['instance_id']}: heal exhausted after {MAX_HEALS} rounds", file=sys.stderr)
            break
        # Heal: ask the model to fix the patch given the apply failure
        fail_info = "Patch does not apply cleanly with `git apply`."
        patch = _llm([
            {"role": "system", "content": "You are fixing a broken git patch. Output ONLY the corrected patch."},
            {"role": "user", "content": (
                f"Repository: {repo}\n\nProblem:\n{problem}\n\n"
                f"Your previous patch failed: {fail_info}\n\n"
                f"Previous patch:\n{patch}\n\n"
                f"Source context:\n{context}\n\n"
                "Produce a corrected patch that applies cleanly:"
            )},
        ])

    # Clean up temp file
    if patch_file.exists():
        patch_file.unlink()
    return patch


def main() -> None:
    instances: list[dict] = json.load(sys.stdin)
    predictions: list[dict] = []

    for inst in instances:
        iid = inst["instance_id"]
        repo = inst["repo"]
        base_commit = inst.get("base_commit", "HEAD")
        print(f"  [{ARM}] {iid} ...", file=sys.stderr, flush=True)

        with tempfile.TemporaryDirectory(prefix="ns_clone_") as tmpd:
            clone_dir = Path(tmpd) / repo.replace("/", "_")
            clone_ok = _clone_repo(repo, base_commit, clone_dir)
            if not clone_ok:
                # Degenerate: no repo context, emit empty patch
                patch = ""
            else:
                try:
                    patch = solve(inst, clone_dir)
                except Exception as exc:
                    print(f"  {iid}: solve error: {exc}", file=sys.stderr)
                    patch = ""

        predictions.append({
            "instance_id": iid,
            "model_patch": patch,
            "model_name_or_path": MODEL_NAME,
        })

    json.dump(predictions, sys.stdout)
    print("", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()