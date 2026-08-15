"""One place that builds the Azure credential for every ARC entry point.

WHY THIS FILE EXISTS. `DefaultAzureCredential` reaches the Azure CLI through
`AzureCliCredential`, which runs `az` in a subprocess under a timeout that
defaults to TEN SECONDS. On this machine `az account get-access-token` takes
10-21s (21s cold), so the wrapper times out and reports "Failed to invoke the
Azure CLI" -- an error that reads like a broken credential and is really a
stopwatch. Measured 2026-08-15: raw `az` succeeded solo (21.3s) and 3-way
concurrent (10.0-10.5s) while `DefaultAzureCredential` failed in BOTH shapes,
which is what rules out contention and leaves the timeout.

That failure is expensive rather than loud. `queue_runner` fetches one token for
the whole wave; when the fetch fails the token file is never written, every
child falls back to its own credential, fails identically, and the retry ladder
naps it as congestion. Wave ev21 spent 2h20m at turn 1 that way and scored
nothing.

Six call sites used to construct the credential themselves, so a timeout fixed
in one was still wrong in five. They now all come here.
"""
from __future__ import annotations

import os

SCOPE = "https://cognitiveservices.azure.com/.default"


def cli_timeout() -> int:
    """Seconds to let the Azure CLI answer.

    Six times the worst latency measured here (21.3s cold). The cost of being
    too generous is a slow start; the cost of being too tight is a wave that
    scores nothing for two hours, so the asymmetry decides the number.
    """
    raw = os.environ.get("ARC_AAD_CLI_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 120


def credential():
    """The credential every ARC process should use.

    `process_timeout` is the whole point of this function -- see the module
    docstring. Leaving it at the library default is the bug.
    """
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(process_timeout=cli_timeout())


def token() -> str:
    """A bearer token string, or raise."""
    return credential().get_token(SCOPE).token
