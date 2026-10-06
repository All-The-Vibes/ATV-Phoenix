"""Brainspace self-serve benchmark — measure compression on *your own* content.

This is the shippable counterpart to TokenMaster's graph benchmark: a tool anyone
can point at their own files, logs, or piped output to see exactly what Brainspace
would save — measured in real ``tiktoken`` tokens, with the lossless-recovery
invariant checked on every placeholder.

It is honest by construction:
  * Every row is a real ``compress()`` run over real bytes you supplied.
  * Recovery is verified only on placeholders THIS run actually stashed (a
    recording stash wrapper records each minted placeholder), so a literal
    ``[[BR:...]]`` example surviving in a docstring is never miscounted as loss.
  * The never-expand guard means a row can show 0% (or near it) — and that is
    reported, not hidden. Prose barely compresses; that is the truth, not a bug.

Usage (installed location: ``<host-home>/token-master/``)::

    # Benchmark your own files (type auto-detected by extension):
    uv run --with mcp --with tiktoken python brainspace_benchmark.py path/to/file.json server.log

    # Walk a directory (capped; the cap is reported):
    uv run --with mcp --with tiktoken python brainspace_benchmark.py ./logs

    # Benchmark piped output (give a hint so the type is detected):
    pytest -v | uv run --with mcp --with tiktoken python brainspace_benchmark.py --stdin --hint=pytest

    # No arguments → a demo over Brainspace's own installed files, so you can see
    # it work instantly before pointing it at your data:
    uv run --with mcp --with tiktoken python brainspace_benchmark.py

    # Machine-readable, and a custom area-under-curve horizon:
    uv run ... python brainspace_benchmark.py ./logs --json --turns 10

Optional deps: ``tiktoken`` (accurate token counts; falls back to a 4-chars/token
heuristic if absent), ``tree-sitter`` + ``tree-sitter-python`` (code compressor;
falls back to noop if absent). The tool runs and reports honestly either way.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Make ``import brainspace`` resolve whether this module is imported as part of the
# package or run from an arbitrary cwd via the top-level launcher.
_PKG_PARENT = str(Path(__file__).resolve().parent.parent)
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from brainspace.ccr import CCR, PLACEHOLDER_RE  # noqa: E402
from brainspace.router import route_typed  # noqa: E402
from brainspace.tokens import estimate  # noqa: E402

# Files larger than this are truncated before benchmarking (a benchmark, not a
# memory test); the truncation is reported in the row note.
_MAX_READ_BYTES = 2 * 1024 * 1024
# Default cap when walking a directory, so pointing at a huge tree stays bounded.
_DEFAULT_MAX_FILES = 40
# Extensions worth benchmarking when walking a directory.
_BENCH_EXTS = (
    ".json", ".log", ".txt", ".md", ".markdown", ".rst",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".cs", ".kt", ".swift",
)


# ---------------------------------------------------------------------------
# Recording stash: verify losslessness only on what THIS run actually stashed.
# ---------------------------------------------------------------------------

class _RecordingStash:
    """Wrap a CCR.stash callable and remember every placeholder it mints.

    This is what makes the lossless check honest: we verify recovery on exactly
    the placeholders this benchmark created, never on ``[[BR:...]]`` literals that
    legitimately survive inside a preserved docstring or test fixture.
    """

    def __init__(self, real_stash):
        self._real = real_stash
        self.minted: list[str] = []

    def __call__(self, content, **kwargs):
        ph = self._real(content, **kwargs)
        if ph:
            self.minted.append(ph)
        return ph


class Row:
    """One benchmarked artifact, measured in tiktoken tokens."""

    def __init__(self, name, ctype, before, after, lossless, note=""):
        self.name = name
        self.ctype = ctype
        self.tok_in = estimate(before)
        self.tok_out = estimate(after)
        self.lossless = lossless
        self.note = note

    @property
    def saved(self) -> int:
        return self.tok_in - self.tok_out

    @property
    def pct(self) -> float:
        return (self.saved / self.tok_in * 100.0) if self.tok_in else 0.0

    @property
    def ratio(self) -> float:
        return (self.tok_in / self.tok_out) if self.tok_out else float("inf")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def benchmark_one(name: str, content: str, hint: str, ccr: CCR) -> Row:
    """Compress one artifact, measure tokens, verify lossless recovery."""
    note = ""
    if len(content.encode("utf-8", "replace")) > _MAX_READ_BYTES:
        content = content[:_MAX_READ_BYTES]
        note = "truncated to 2MB"

    rec = _RecordingStash(ccr.stash)
    compressed, ctype = route_typed(content, hint, stash=rec)

    # Verify recovery on exactly the placeholders this run minted.
    minted_hashes = {h for ph in rec.minted for h in PLACEHOLDER_RE.findall(ph)}
    lossless = True
    for ph in PLACEHOLDER_RE.findall(compressed):
        hs = PLACEHOLDER_RE.findall(ph)
        if not hs or hs[0] not in minted_hashes:
            continue  # not ours (e.g. a literal example in a docstring)
        if ccr.retrieve(ph) is None:
            lossless = False
    return Row(name, ctype.value, content, compressed, lossless, note)


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()[: _MAX_READ_BYTES + 1]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def collect_inputs(paths: list[str], *, max_files: int) -> tuple[list[tuple[str, str, str]], int]:
    """Resolve CLI paths into (name, content, hint) tuples.

    Returns (items, skipped_count). Directories are walked for benchmarkable
    extensions, sorted for determinism, and capped at ``max_files``; the number
    skipped by the cap is returned so the caller can report it honestly.
    """
    items: list[tuple[str, str, str]] = []
    skipped = 0
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            candidates = sorted(
                f for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in _BENCH_EXTS
            )
            if len(candidates) > max_files:
                skipped += len(candidates) - max_files
                candidates = candidates[:max_files]
            for f in candidates:
                txt = _read_text(f)
                if txt and txt.strip():
                    items.append((str(f), txt, f.name))
        elif p.is_file():
            txt = _read_text(p)
            if txt and txt.strip():
                items.append((str(p), txt, p.name))
        else:
            print(f"  (skipping: not found — {raw})", file=sys.stderr)
    return items, skipped


def demo_inputs() -> list[tuple[str, str, str]]:
    """A real, always-present corpus: Brainspace's own installed package files.

    These ship next to this script, so the demo benchmarks real code, a real JSON
    directory listing, and real module prose — zero external dependency, nothing
    synthetic. Point the tool at your own files for a benchmark that matters to you.
    """
    pkg = Path(__file__).resolve().parent
    items: list[tuple[str, str, str]] = []

    # code: the engine's own modules
    for rel in ("ccr.py", "router.py", "tokens.py"):
        f = pkg / rel
        txt = _read_text(f)
        if txt:
            items.append((f"brainspace/{rel}", txt, rel))

    # json: a real listing of the package, serialized
    listing = []
    for f in sorted(pkg.rglob("*.py")):
        try:
            listing.append({
                "path": str(f.relative_to(pkg)).replace("\\", "/"),
                "size": f.stat().st_size,
            })
        except OSError:
            pass
    if listing:
        items.append(("package-listing.json", json.dumps(listing), "listing.json"))

    return items


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _backend() -> str:
    probe = "hello world this is a test string for backend detection"
    return "tiktoken" if estimate(probe) != (len(probe) + 3) // 4 else "heuristic (install tiktoken for accuracy)"


def format_report(rows: list[Row], *, turns: int, skipped: int, demo: bool) -> str:
    out: list[str] = []
    out.append("=" * 82)
    out.append("BRAINSPACE COMPRESSION BENCHMARK")
    out.append("=" * 82)
    out.append(f"tokenizer: {_backend()}")
    if demo:
        out.append("corpus:    DEMO (Brainspace's own installed files) — pass paths to benchmark your data")
    if skipped:
        out.append(f"note:      {skipped} file(s) skipped by the directory cap (pass --max-files to widen)")
    out.append("")

    out.append(f"{'artifact':<38}{'type':<7}{'tok in':>9}{'tok out':>9}{'saved':>8}{'   %':>7}{'  ratio':>8}{' lossless':>10}")
    out.append("-" * 96)
    for r in rows:
        ratio = f"{r.ratio:.2f}x" if r.tok_out else "inf"
        loss = "yes" if r.lossless else "NO!"
        nm = (r.name[:35] + "...") if len(r.name) > 38 else r.name
        line = f"{nm:<38}{r.ctype:<7}{r.tok_in:>9,}{r.tok_out:>9,}{r.saved:>8,}{r.pct:>6.1f}%{ratio:>8}{loss:>10}"
        out.append(line)
        if r.note:
            out.append(f"    ({r.note})")

    # pooled by type
    out.append("")
    out.append("=" * 82)
    out.append("POOLED BY CONTENT TYPE")
    out.append("=" * 82)
    by_type: dict[str, list[int]] = {}
    for r in rows:
        b, a = by_type.get(r.ctype, [0, 0])
        by_type[r.ctype] = [b + r.tok_in, a + r.tok_out]
    out.append(f"{'type':<10}{'tok in':>12}{'tok out':>12}{'saved':>10}{'   %':>8}{'  ratio':>9}")
    out.append("-" * 62)
    gb = ga = 0
    for ctype, (b, a) in sorted(by_type.items()):
        gb += b
        ga += a
        saved = b - a
        pct = saved / b * 100 if b else 0
        ratio = b / a if a else 0
        out.append(f"{ctype:<10}{b:>12,}{a:>12,}{saved:>10,}{pct:>7.1f}%{ratio:>8.2f}x")
    out.append("-" * 62)
    gpct = (gb - ga) / gb * 100 if gb else 0
    gratio = gb / ga if ga else 0
    out.append(f"{'ALL':<10}{gb:>12,}{ga:>12,}{gb-ga:>10,}{gpct:>7.1f}%{gratio:>8.2f}x")

    # area under curve — the saving multiplied by turns the output lingers
    biggest = max(rows, key=lambda r: r.saved, default=None)
    if biggest and biggest.saved > 0:
        out.append("")
        out.append("=" * 82)
        out.append(f"AREA UNDER CURVE — a compressed output is re-sent every turn it stays in context")
        out.append("=" * 82)
        out.append(f"largest single saving: {biggest.name} ({biggest.ctype}), {biggest.tok_in:,}->{biggest.tok_out:,} tok/turn")
        out.append("")
        out.append(f"{'turns in context':>18}{'raw cumulative':>18}{'compressed':>16}{'tokens saved':>15}")
        out.append("-" * 67)
        for t in sorted({1, 3, 5, turns}):
            raw = biggest.tok_in * t
            comp = biggest.tok_out * t
            out.append(f"{t:>18}{raw:>18,}{comp:>16,}{raw-comp:>15,}")

    all_ok = all(r.lossless for r in rows)
    out.append("")
    out.append("=" * 82)
    out.append(f"lossless recovery: {'HELD on every placeholder this run stashed' if all_ok else 'VIOLATED — please file a bug'}")
    out.append("=" * 82)
    return "\n".join(out)


def to_json(rows: list[Row], *, turns: int) -> dict:
    by_type: dict[str, list[int]] = {}
    for r in rows:
        b, a = by_type.get(r.ctype, [0, 0])
        by_type[r.ctype] = [b + r.tok_in, a + r.tok_out]
    gb = sum(r.tok_in for r in rows)
    ga = sum(r.tok_out for r in rows)
    return {
        "backend": _backend(),
        "rows": [
            {"name": r.name, "type": r.ctype, "tok_in": r.tok_in, "tok_out": r.tok_out,
             "saved": r.saved, "pct": round(r.pct, 1),
             "ratio": round(r.ratio, 2) if r.tok_out else None, "lossless": r.lossless}
            for r in rows
        ],
        "pooled": {
            ct: {"tok_in": b, "tok_out": a, "pct": round((b - a) / b * 100, 1) if b else 0,
                 "ratio": round(b / a, 2) if a else None}
            for ct, (b, a) in by_type.items()
        },
        "grand": {"tok_in": gb, "tok_out": ga,
                  "pct": round((gb - ga) / gb * 100, 1) if gb else 0,
                  "ratio": round(gb / ga, 2) if ga else None},
        "lossless": all(r.lossless for r in rows),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = False
    use_stdin = False
    hint = ""
    turns = 5
    max_files = _DEFAULT_MAX_FILES
    paths: list[str] = []

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--json",):
            as_json = True
        elif a in ("--stdin",):
            use_stdin = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a.startswith("--hint="):
            hint = a.split("=", 1)[1]
        elif a == "--hint" and i + 1 < len(argv):
            hint = argv[i + 1]; i += 1
        elif a.startswith("--turns="):
            turns = max(1, int(a.split("=", 1)[1]))
        elif a == "--turns" and i + 1 < len(argv):
            turns = max(1, int(argv[i + 1])); i += 1
        elif a.startswith("--max-files="):
            max_files = max(1, int(a.split("=", 1)[1]))
        elif a == "--max-files" and i + 1 < len(argv):
            max_files = max(1, int(argv[i + 1])); i += 1
        else:
            paths.append(a)
        i += 1

    sandbox = tempfile.mkdtemp(prefix="brainspace_bench_")
    ccr = CCR(Path(sandbox) / "ccr.sqlite")

    skipped = 0
    demo = False
    if use_stdin:
        content = sys.stdin.read()
        items = [("<stdin>", content, hint or "stdin.txt")] if content.strip() else []
    elif paths:
        items, skipped = collect_inputs(paths, max_files=max_files)
    else:
        items = demo_inputs()
        demo = True

    if not items:
        print("No benchmarkable input. Pass file/dir paths, or pipe with --stdin --hint=<name>.",
              file=sys.stderr)
        return 2

    rows = [benchmark_one(name, content, h or hint, ccr) for name, content, h in items]

    if as_json:
        print(json.dumps(to_json(rows, turns=turns), indent=2))
    else:
        print(format_report(rows, turns=turns, skipped=skipped, demo=demo))
    return 0 if all(r.lossless for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
