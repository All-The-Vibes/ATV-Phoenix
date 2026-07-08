#!/usr/bin/env python3
"""scripts/real_agent.py -- repo-aware SWE-bench agent for the ATV-Phoenix north-star.

Unlike the old context-free agents (which fed the model only the issue text and
so produced diffs that rarely applied), this agent clones each instance's repo at
its ``base_commit`` and gives the model real file context. Two arms share that
context and differ only in the gate:

  * ``vanilla``  -- single-shot control: generate once, emit as-is.
  * ``phoenix``  -- verify-heal treatment: generate, then heal against
    ``git apply --check`` until the patch applies *by construction*.

Heavy SDK imports (openai, azure-identity) are lazy, so the module imports with
stdlib only and is unit-testable with an injected mock LLM (no Azure, no network).

CLI (run on the eval VM):
    python3 real_agent.py --arm vanilla < instances.json > pred_a.json
    python3 real_agent.py --arm phoenix < instances.json > pred_b.json
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

_DIFF_START = re.compile(r"(diff --git |--- )", re.M)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_SRC_EXT = {".py", ".js", ".ts", ".java", ".go", ".rb", ".c", ".cc", ".cpp", ".h", ".rs"}

_SYSTEM = (
    "You are a senior software engineer. Given a repository issue and the relevant "
    "source files, produce a MINIMAL fix as a single unified git diff (starting with "
    "'diff --git' and using '--- ', '+++ ', '@@' hunk headers). Output ONLY the diff, "
    "no prose, no code fences."
)


def extract_diff(text):
    """Pull a unified diff out of a model response (tolerant of fences / prose)."""
    if not text:
        return ""
    t = text.strip()
    fence = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", t, re.S)
    if fence:
        t = fence.group(1)
    start = _DIFF_START.search(t)
    if start:
        t = t[start.start():]
    t = t.strip()
    if t and not t.endswith("\n"):
        t += "\n"
    return t


def apply_check(repo_dir, patch):
    """Return (ok, stderr) for whether ``patch`` applies cleanly in ``repo_dir``."""
    if not patch or not patch.strip():
        return False, "empty patch"
    p = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=repo_dir, input=patch, capture_output=True, text=True,
    )
    return p.returncode == 0, (p.stderr or "").strip()


def _candidate_files(repo_dir, problem_statement, max_files=6):
    root = pathlib.Path(repo_dir)
    files = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix in _SRC_EXT and ".git" not in p.parts
    ]
    if not files:
        files = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    idents = {w.lower() for w in _IDENT.findall(problem_statement or "")}

    def score(p):
        s = 5 if p.stem.lower() in idents else 0
        try:
            head = p.read_text(errors="ignore")[:4000].lower()
            s += sum(1 for w in idents if w in head)
        except Exception:
            pass
        return s

    files.sort(key=score, reverse=True)
    return files[:max_files]


def build_context(repo_dir, problem_statement, max_files=6, max_bytes=8000):
    parts = []
    for p in _candidate_files(repo_dir, problem_statement, max_files):
        try:
            body = p.read_text(errors="ignore")
        except Exception:
            continue
        rel = p.relative_to(repo_dir)
        parts.append(f"### File: {rel}\n{body[:max_bytes]}")
    return "\n\n".join(parts)


def _messages(inst, context, feedback=None):
    user = (
        f"Repository: {inst.get('repo', '')}\n\n"
        f"Issue:\n{inst.get('problem_statement', '')}\n\n"
        f"Relevant files:\n{context}\n\n"
        "Produce the unified diff patch:"
    )
    msgs = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
    if feedback:
        msgs.append({
            "role": "user",
            "content": (
                "Your previous patch did NOT apply cleanly (`git apply --check` failed):\n"
                f"{feedback}\n\n"
                "Return a corrected unified diff that applies against the files shown. "
                "Match the exact existing lines and correct '@@' hunk headers."
            ),
        })
    return msgs


def generate_patch(inst, repo_dir, llm, feedback=None, context=None):
    if context is None:
        context = build_context(repo_dir, inst.get("problem_statement", ""))
    return extract_diff(llm(_messages(inst, context, feedback)))


def solve(inst, repo_dir, llm, arm="phoenix", max_heals=3):
    """Produce a model_patch for one instance.

    vanilla: single-shot (control). phoenix: verify-heal until it applies.
    """
    context = build_context(repo_dir, inst.get("problem_statement", ""))
    patch = generate_patch(inst, repo_dir, llm, context=context)
    if arm != "phoenix":
        return patch
    ok, err = apply_check(repo_dir, patch)
    heals = 0
    while not ok and heals < max_heals:
        heals += 1
        patch = generate_patch(inst, repo_dir, llm, feedback=err, context=context)
        ok, err = apply_check(repo_dir, patch)
    return patch


def run(instances, llm, resolve_repo, arm="phoenix", max_heals=3, model="gpt-5.1"):
    """Solve every instance, returning SWE-bench prediction dicts.

    ``resolve_repo(inst) -> repo_dir`` is injected so tests can supply a local
    fixture repo and production supplies a clone-on-demand resolver.
    """
    label = f"{model}-{arm}"
    preds = []
    for inst in instances:
        try:
            repo_dir = resolve_repo(inst)
            patch = solve(inst, repo_dir, llm, arm=arm, max_heals=max_heals)
        except Exception as e:  # never let one instance abort the whole run
            patch = ""
            print(f"  [warn] {inst.get('instance_id')}: {e}", file=sys.stderr, flush=True)
        preds.append({
            "instance_id": inst["instance_id"],
            "model_patch": patch,
            "model_name_or_path": label,
        })
        print(f"  solved {inst['instance_id']}", file=sys.stderr, flush=True)
    return preds


def _clone_resolver(cache_dir):
    """Clone-on-demand (partial clone, cached per repo, checkout base_commit)."""
    cache = {}

    def resolve(inst):
        repo = inst["repo"]
        commit = inst.get("base_commit")
        dest = cache.get(repo)
        if dest is None:
            dest = os.path.join(cache_dir, repo.replace("/", "__"))
            if not os.path.isdir(dest):
                subprocess.run(
                    ["git", "clone", "--filter=blob:none", "--quiet",
                     f"https://github.com/{repo}.git", dest],
                    check=True,
                )
            cache[repo] = dest
        if commit:
            subprocess.run(["git", "-C", dest, "checkout", "--quiet", commit], check=True)
        return dest

    return resolve


def _azure_llm():
    from openai import AzureOpenAI
    from azure.identity import ManagedIdentityCredential

    endpoint = os.environ["AOAI_ENDPOINT"]
    deployment = os.environ["AOAI_DEPLOYMENT"]
    cred = ManagedIdentityCredential()

    def token_provider():
        return cred.get_token("https://cognitiveservices.azure.com/.default").token

    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-12-01-preview",
    )

    def llm(messages):
        r = client.chat.completions.create(
            model=deployment, messages=messages, max_completion_tokens=4096,
        )
        return r.choices[0].message.content

    return llm


def main(argv=None):
    ap = argparse.ArgumentParser(description="Repo-aware SWE-bench agent (north-star).")
    ap.add_argument("--arm", choices=["vanilla", "phoenix"],
                    default=os.environ.get("ARM", "vanilla"))
    ap.add_argument("--max-heals", type=int, default=3)
    ap.add_argument("--model", default=os.environ.get("AOAI_DEPLOYMENT", "gpt-5.1"))
    ap.add_argument("--work-dir", default=None)
    args = ap.parse_args(argv)

    instances = json.load(sys.stdin)
    work = args.work_dir or tempfile.mkdtemp(prefix="ns_repos_")
    os.makedirs(work, exist_ok=True)
    resolve = _clone_resolver(work)
    llm = _azure_llm()
    preds = run(instances, llm, resolve, arm=args.arm,
                max_heals=args.max_heals, model=args.model)
    json.dump(preds, sys.stdout)


if __name__ == "__main__":
    main()
