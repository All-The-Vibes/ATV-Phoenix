#!/usr/bin/env python3
"""run_okf_live.py — a real phoenix-context turn loop answered from an OKF bundle.

phoenix-context's rule: route a *structural* question to a prebuilt artifact and pay once for
orientation, instead of grep-and-read loops that re-pay every turn. This driver runs that loop for
real against the committed `examples/okf-code-graph/` bundle: an actual structural question is
answered by invoking `okf_ingest` (index-first -> filter -> open exactly one concept), capturing the
real subprocess output of every step and the tokens each step costs.

It then runs the grep-and-read baseline an agent would otherwise use for the SAME question, summed
across turns (the cost phoenix-context says actually matters), so the comparison is apples to apples.

Tokens: tiktoken o200k_base. No model is called; the measurement is deterministic.

Usage:
    python run_okf_live.py            # run the loop, print the transcript, write artifacts
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "examples" / "okf-code-graph"
INGEST = ROOT / "skills" / "phoenix-okf" / "scripts" / "okf_ingest.py"

ENC = tiktoken.get_encoding("o200k_base")


def tok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


def run(*args: str) -> str:
    """Invoke okf_ingest as a real subprocess and return its stdout."""
    out = subprocess.run([sys.executable, str(INGEST), str(BUNDLE), *args],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(out.stderr)
        raise SystemExit(f"okf_ingest failed: {' '.join(args)}")
    return out.stdout


def all_concept_files() -> list[Path]:
    return [p for p in sorted(BUNDLE.rglob("*.md")) if p.name not in ("index.md", "log.md")]


def grep_and_read(keyword: str) -> tuple[str, int, int]:
    """Model the grep baseline: grep the tree (cheap lines) then read each hit file in full."""
    matched_lines, hit_files = [], []
    for p in all_concept_files():
        text = p.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if keyword.lower() in ln.lower()]
        if lines:
            hit_files.append(p)
            rel = p.relative_to(BUNDLE).as_posix()
            matched_lines += [f"{rel}: {ln}" for ln in lines]
    grep_tok = tok("\n".join(matched_lines))
    read_tok = sum(tok(p.read_text(encoding="utf-8")) for p in hit_files)
    return "\n".join(matched_lines), grep_tok + read_tok, len(hit_files)


# A genuine structural question of the kind phoenix-context says to route to the graph.
QUESTION = "What cross-file (candidate) edges does src/heal.rs have, and what symbols does it define?"
CONCEPT = "concepts/src/heal.rs.md"
GREP_KEYWORD = "heal.rs"


def main() -> None:
    transcript: list[str] = []

    def say(line: str = "") -> None:
        transcript.append(line)
        print(line)

    say("=" * 78)
    say("phoenix-context LIVE RUN - structural question answered from an OKF bundle")
    say("=" * 78)
    say(f"Bundle  : {BUNDLE.relative_to(ROOT).as_posix()}")
    say(f"Question: {QUESTION}")
    say("")
    say("phoenix-context routing decision: this is a 'what does X relate to' structural")
    say("question -> route to the prebuilt knowledge artifact, do NOT grep-and-read.")
    say("")

    # --- The phoenix-context / OKF loop: pay once to orient, then open exactly what's needed. ---
    say("-" * 78)
    say("TURN 1 - orient: okf_ingest index-first outline (paid once for the whole session)")
    say("-" * 78)
    outline = run("--max", "100")
    outline_tok = tok(outline)
    head = "\n".join(outline.splitlines()[:12])
    say(head)
    say(f"... [outline truncated for display] ...  (outline = {outline_tok:,} tokens)")
    say("")

    say("-" * 78)
    say("TURN 2 - locate: okf_ingest --query Rust  (find the concept, no file reads)")
    say("-" * 78)
    query = run("--query", "Rust")
    query_tok = tok(query)
    say("\n".join(l for l in query.splitlines() if "heal.rs" in l or l.startswith("#"))[:600])
    say(f"... (query result = {query_tok:,} tokens; agent now opens exactly {CONCEPT})")
    say("")

    say("-" * 78)
    say(f"TURN 3 - open exactly one concept: okf_ingest --full {CONCEPT}")
    say("-" * 78)
    full = run("--full", CONCEPT)
    full_tok = tok(full)
    say(full.rstrip())
    say("")

    okf_total = outline_tok + query_tok + full_tok
    say("=" * 78)
    say("ANSWER (read straight off the concept's frontmatter + Relationships section).")
    say("=" * 78)
    say("")

    # --- Baseline: what grep-and-read would cost for the SAME question. ---
    _, grep_total, hits = grep_and_read(GREP_KEYWORD)

    say("-" * 78)
    say("COST - same answer, two ways (tiktoken o200k_base)")
    say("-" * 78)
    say(f"  OKF via phoenix-context : {okf_total:,} tok  "
        f"(outline {outline_tok:,} + query {query_tok:,} + 1 concept {full_tok:,})")
    say(f"  grep-and-read baseline  : {grep_total:,} tok  "
        f"(grep lines + {hits} matched file(s) read in full)")
    ratio = grep_total / max(okf_total, 1)
    verdict = (f"OKF is {ratio:.1f}x cheaper on this single turn"
               if ratio >= 1 else
               f"grep is {1/ratio:.1f}x cheaper on this single isolated turn")
    say(f"  -> {verdict}.")
    say("")
    say("Session reality: the outline is paid ONCE and reused for every later structural")
    say("question this session; grep-and-read re-pays its full cost on every new question.")
    say(f"Across N such questions: OKF ~= {outline_tok:,} + N*(small concept); "
        f"grep ~= N*{grep_total:,}.")

    # --- Persist artifacts. ---
    outdir = Path(__file__).resolve().parent
    (outdir / "transcript.txt").write_text("\n".join(transcript) + "\n", encoding="utf-8")
    record = {
        "question": QUESTION,
        "concept_opened": CONCEPT,
        "okf_outline_tok": outline_tok,
        "okf_query_tok": query_tok,
        "okf_full_tok": full_tok,
        "okf_total_tok": okf_total,
        "grep_total_tok": grep_total,
        "grep_hit_files": hits,
        "single_turn_ratio_grep_over_okf": round(grep_total / max(okf_total, 1), 3),
    }
    (outdir / "live-result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    say("")
    say(f"Wrote {(outdir / 'transcript.txt').relative_to(ROOT).as_posix()} and "
        f"{(outdir / 'live-result.json').relative_to(ROOT).as_posix()}.")


if __name__ == "__main__":
    main()
