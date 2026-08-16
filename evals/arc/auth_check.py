"""Does our Azure credential survive a SLOW Azure CLI?

TWO WEAKER VERSIONS OF THIS CHECK PASSED DURING THE OUTAGE THEY EXISTED TO
CATCH. The first asked "can we get a token" and went green because a probe had
just warmed `az` to 7.9s, under the 10s timeout. The second measured `az`
latency and demanded headroom -- and went green too, because by then `az` was
down to 4.3s. Observed range on this machine is 4.3s warm to 21.3s cold, a 5x
swing, so ANY check that samples current latency reports the weather rather than
the defect.

The defect is stable even when the symptom is not: `AzureCliCredential` applies
a subprocess timeout that defaults to 10 seconds, and this machine's `az` needs
more than that whenever it is cold or the box is busy. Wave ev21 sat at turn 1
for 2h20m on exactly that, reported as "Failed to invoke the Azure CLI" -- an
error that reads like a broken credential and is really a stopwatch.

So this check MANUFACTURES the slow CLI instead of waiting for one. It puts an
`az` shim on PATH that sleeps past the worst latency ever measured here and then
answers normally, and requires the real credential to come back with a token
anyway. Warm or cold, loaded or idle, the answer is the same: it fails on a 10s
timeout and passes on one wide enough for this machine.

The token the shim returns is a dummy. That is deliberate -- what is under test
is whether we wait long enough to hear the CLI out, not what it says.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, __file__.rsplit("evals", 1)[0].rstrip("\\/"))

from evals.arc import aad  # noqa: E402

# Worst real `az` measured here was 21.3s cold. Sleep past it, so passing this
# check means surviving the worst day actually observed, not an average one.
SLOW = 25
# Enough to let a correct timeout finish, short enough to fail a wrong one.
BUDGET = 90
DUMMY = "d" * 3000


def shim_dir() -> str:
    """A directory whose `az` is slow but healthy."""
    d = tempfile.mkdtemp(prefix="arc-slow-az-")
    # ping is the sleep that works from a non-console subprocess; `timeout` is
    # not available to a process started without a console.
    # Batch `echo` needs no quote escaping, and JSON contains none of the
    # characters cmd does care about (< > | &), so this goes out verbatim.
    payload = (
        '{"accessToken":"' + DUMMY + '",'
        '"expiresOn":"2099-01-01 00:00:00.000000",'
        '"expires_on":4070908800,'
        '"subscription":"check","tenant":"check",'
        '"tokenType":"Bearer"}'
    )
    with open(os.path.join(d, "az.cmd"), "w", encoding="ascii") as fh:
        fh.write("@echo off\r\n")
        fh.write(f"ping -n {SLOW + 1} 127.0.0.1 >nul\r\n")
        fh.write(f'echo {payload}\r\n')
    return d


def main() -> int:
    configured = aad.cli_timeout()
    print(f"configured timeout : {configured}s")
    print(f"simulated az delay : {SLOW}s  (worst real measurement was 21.3s)")

    d = shim_dir()
    original = os.environ.get("PATH", "")
    os.environ["PATH"] = d + os.pathsep + original
    try:
        which = shutil.which("az") or "(not found)"
        print(f"az resolves to     : {which}")
        if not which.lower().startswith(d.lower()):
            print("\nFAIL  the shim is not the `az` that will be used; this check "
                  "cannot\n      prove anything, so it refuses to pass.")
            return 1

        t0 = time.time()
        try:
            tok = aad.token()
        except Exception as exc:
            took = time.time() - t0
            print(f"\nFAIL  no token after {took:.1f}s against a {SLOW}s CLI.")
            print(f"      {type(exc).__name__}: {str(exc).splitlines()[0]}")
            print(f"\n      A {configured}s timeout cannot hear out a CLI that takes")
            print(f"      {SLOW}s. This is the ev21 outage, reproduced on demand.")
            return 1
        took = time.time() - t0

        if not tok or len(tok) < 100:
            print(f"\nFAIL  token looks wrong (len={len(tok) if tok else 0})")
            return 1
        if took > BUDGET:
            print(f"\nFAIL  token took {took:.1f}s, over the {BUDGET}s budget")
            return 1
        print(f"\nOK    token in {took:.1f}s despite a {SLOW}s CLI "
              f"(timeout {configured}s)")
        return 0
    finally:
        os.environ["PATH"] = original
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
